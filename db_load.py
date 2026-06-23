"""
db_load.py
==========
DuckDB connection manager for the encoder cross-reference pipeline.

Architecture (3-tier, fastest first):
  1. Persistent .db  — Silver loaded into DuckDB native format at startup.
                       Queries run against compressed, indexed TABLE (~30x faster
                       than Parquet VIEW). Rebuilt only when S3 Silver changes.
  2. Parquet VIEW    — Fallback if .db build fails. Slower (Parquet decode per
                       query) but functionally identical.
  3. S3 httpfs       — Last resort if no local files exist.

Startup sequence (called from main.py):
    download_silver_locally()   — S3 -> /tmp/silver/*.parquet (size-checked)
                                   -> builds /tmp/silver/encoders.db if stale

S3 layout expected:
    encoder_pipeline/silver/manufacturer=kubler/data.parquet
    encoder_pipeline/silver/manufacturer=epc/data.parquet
    encoder_pipeline/silver/manufacturer=sick/data.parquet

Usage:
    from db_load import get_cached_connection, SILVER_VIEW

    con = get_cached_connection()   # singleton — NEVER close this
    df  = con.execute(f"SELECT * FROM {SILVER_VIEW} LIMIT 5").fetchdf()

AQB Solutions | May 2026
"""

import logging
import math
import os
import time
import threading as _threading

import duckdb
import boto3
import pandas as pd

from kubler_decoder import decode_kubler_order_code, KUBLER_FAMILY_ALIASES
from epc_decoder   import decode_epc_order_code,    EPC_FAMILY_CONFIGS

# Known Lika family tokens -- used for mfr_hint detection in _parse_order_code.
# Extend this set as Lika Silver coverage grows.
# Families sourced from Silver (June 2026) -- update when new datasheets added.
# R.C50MI omitted: dot in name makes first-token split give "R" (too short);
# detection falls through to Lika via Stage 2c dash-split instead.
LIKA_FAMILY_PREFIXES: frozenset = frozenset({
    # C-series (standard optical)
    "C50", "C80", "C81", "C82", "C83", "C100", "C101",
    # CK-series (hollow-bore kit)
    "CK41", "CK46", "CK61",
    # I-series (kit encoders)
    "I28", "I30", "I40", "I41", "I58R", "I105", "I115", "I116",
    # ICS / IM / IR
    "ICS", "IM28", "IR01",
    # MC / MI series (magnetic incremental)
    "MC36", "MC36K", "MC58", "MC59", "MC60",
    "MI36", "MI36K", "MI58", "MI58S",
    # SMB / SME / SMK / SMIG series (magnetic, linear, special)
    "SMB2", "SMB5",
    "SME11", "SME12", "SME21", "SME22", "SME51", "SME52",
    "SMK", "SMIG",
})

# Baumer family prefix set — used to set mfr_hint="baumer" in _parse_order_code.
# Only includes families whose first hyphen-separated token is unambiguous.
# Space-separated Baumer part numbers (e.g. "HOG 9", "POG 86") have no clean
# first token and fall through to Stage 3/4 family-name lookup — correct behaviour.
BAUMER_FAMILY_PREFIXES: frozenset = frozenset({
    # Industrial incremental — 58mm optical series
    "EIL576S", "EIL580", "EIL580P", "EXEIL580", "EXEIL580P",
    "EN380", "EN580E", "EXEN580E",
    # Heavy duty incremental — HOG/POG 1000-series (NEMA + explosion-proof)
    "EHOG840", "EHOG860", "EHOG870", "EHOG890",
    "EHOG1060", "EHOG1070", "EHOG1090", "EHOG1095",
    "HOG840", "HOG860", "HOG870", "HOG890",
    "HOG1060", "HOG1070", "HOG1090", "HOG1095",
    "HOG163",
    # Heavy duty — SinCos + combination
    "HOGS",
    # Heavy duty — combination encoders with fixed-length part numbers
    "HMG10", "PMG10",
    # Bearingless incremental
    "EB260", "EB260F", "EB260K", "EB200E",
    "HDmagMHGE", "HDmagMHGP",
    "ITD22H00", "ITD49H00", "ITD69H00", "ITD89H00",
    # Other distinct families
    "EExHOG", "EExOG",
    # HS35 (US-market hollow shaft series)
    "HS35F", "HS35P", "HS35S",
})

# ── Posital lifecycle filter ──────────────────────────────────────────────────

def _load_posital_exiting() -> frozenset:
    """
    Read Posital Bronze2 CSV from S3 and return a frozenset of part numbers
    whose Product Life Cycle is 'Exiting'.

    Called once at module load. If the S3 read fails for any reason (missing
    file, no credentials, network error) the function logs a warning and
    returns an empty frozenset so the app continues working without the filter.
    """
    key = f"{os.environ.get('S3_ROOT', 'encoder_pipeline')}/bronze2/posital/posital_raw_full.csv"
    bucket = os.environ.get("S3_BUCKET", "aqb-data-analytics-demo")
    region = os.environ.get("AWS_REGION", "ap-south-1")
    try:
        import boto3, io
        s3  = boto3.client("s3", region_name=region)
        obj = s3.get_object(Bucket=bucket, Key=key)
        df  = __import__("pandas").read_csv(
            io.BytesIO(obj["Body"].read()),
            usecols=["Product Name", "Product Life Cycle"],
        )
        exiting = frozenset(
            df.loc[df["Product Life Cycle"] == "Exiting", "Product Name"]
            .dropna()
            .str.strip()
        )
        logging.getLogger("db_load").info(
            f"Posital lifecycle filter loaded: {len(exiting):,} Exiting parts excluded."
        )
        return exiting
    except Exception as exc:
        logging.getLogger("db_load").warning(
            f"Posital lifecycle filter unavailable — {exc}. "
            "Exiting products will not be filtered from search results."
        )
        return frozenset()


# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("db_load")

# Initialised empty — populated by load_posital_lifecycle_filter() called from
# main.py startup(). Never called at module level to avoid blocking import on
# an S3 network call before uvicorn has even started.
POSITAL_EXITING_PARTS: frozenset = frozenset()


def load_posital_lifecycle_filter() -> None:
    """
    Populate POSITAL_EXITING_PARTS from the Posital Bronze2 CSV on S3.

    Called once from main.py startup() — NOT at module import time.
    Runs in the startup context so a slow/failed S3 call never blocks the
    Python import chain. On failure the filter stays empty and the app
    continues normally (Exiting products appear in results but are not
    a correctness issue — just a UX concern).
    """
    global POSITAL_EXITING_PARTS
    result = _load_posital_exiting()
    POSITAL_EXITING_PARTS = result
    print(f"  Posital lifecycle filter: {len(result):,} Exiting parts loaded.", flush=True)

# ── S3 config ─────────────────────────────────────────────────────────────────
S3_BUCKET  = os.environ.get("S3_BUCKET",  "aqb-data-analytics-demo")
S3_ROOT    = os.environ.get("S3_ROOT",    "encoder_pipeline")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

# ── DuckDB performance config ─────────────────────────────────────────────────
DUCKDB_THREADS = int(os.environ.get("DUCKDB_THREADS", "2"))
DUCKDB_MEMORY  = os.environ.get("DUCKDB_MEMORY",  "6GB")

# S3 glob (httpfs fallback only)
SILVER_GLOB = f"s3://{S3_BUCKET}/{S3_ROOT}/silver/manufacturer=*/data.parquet"

# Local cache paths (primary query target)
LOCAL_SILVER_DIR  = "/tmp/silver"
LOCAL_SILVER_GLOB = f"{LOCAL_SILVER_DIR}/manufacturer=*/data.parquet"
LOCAL_DB_PATH     = f"{LOCAL_SILVER_DIR}/encoders.db"   # persistent DuckDB table

SILVER_VIEW = "silver"


# ── S3 -> local Silver download ────────────────────────────────────────────────

def download_silver_locally() -> bool:
    """
    Download Silver Parquet files from S3 to LOCAL_SILVER_DIR via boto3,
    then build (or skip) the persistent DuckDB .db file.

    Size-check logic: compares S3 object size vs local file size before skipping.
    If sizes differ (Silver was rebuilt after an ETL run), the local file is
    re-downloaded and the .db is force-rebuilt so queries never serve stale data.

    Returns True on success, False if anything fails.
    """
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    prefix    = f"{S3_ROOT}/silver/"

    try:
        paginator  = s3_client.get_paginator("list_objects_v2")
        downloaded = 0
        refreshed  = 0
        skipped    = 0

        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".parquet"):
                    continue

                rel   = key[len(prefix):]
                local = os.path.join(LOCAL_SILVER_DIR, rel)
                os.makedirs(os.path.dirname(local), exist_ok=True)

                local_size = os.path.getsize(local) if os.path.exists(local) else -1
                if local_size == obj["Size"]:
                    skipped += 1
                    continue

                action  = "Refreshing" if local_size != -1 else "Downloading"
                size_mb = round(obj["Size"] / 1_048_576, 1)
                log.info(f"  {action} {key} ({size_mb} MB) -> {local}")
                s3_client.download_file(S3_BUCKET, key, local)

                if local_size != -1:
                    refreshed += 1
                else:
                    downloaded += 1

        log.info(
            f"Silver sync complete: {downloaded} downloaded, "
            f"{refreshed} refreshed (stale), {skipped} already current"
        )

        # Build persistent .db:
        #   force=True  -> Parquet changed, always rebuild
        #   force=False -> Parquet current, only build if .db missing
        parquet_changed = (downloaded + refreshed) > 0
        db_ok = build_local_db(force=parquet_changed)
        return db_ok

    except Exception as exc:
        log.error(f"Silver download failed: {exc}")
        return False


def build_local_db(force: bool = False) -> bool:
    """
    Load Silver Parquet files into a persistent DuckDB .db file.

    force=True  — always rebuild (called when Parquet was re-downloaded).
    force=False — skip if .db already exists (Parquet was current on this boot).

    The .db file stores Silver as a native DuckDB TABLE with lightweight
    compression and zonemaps — queries run ~30x faster than against Parquet VIEW.

    Returns True on success, False on failure (caller falls back to Parquet VIEW).
    """
    if not force and os.path.exists(LOCAL_DB_PATH):
        log.info("Silver .db already current — skipping rebuild.")
        return True

    log.info(f"Building persistent DuckDB .db from local Parquet ...")
    t0 = time.time()

    # Remove stale .db before rebuild to avoid duckdb.IOException
    if os.path.exists(LOCAL_DB_PATH):
        try:
            os.remove(LOCAL_DB_PATH)
        except OSError as e:
            log.warning(f"Could not remove stale .db: {e}")

    try:
        con = duckdb.connect(LOCAL_DB_PATH)
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"""
            CREATE TABLE {SILVER_VIEW} AS
            SELECT * FROM read_parquet(
                '{LOCAL_SILVER_GLOB}',
                hive_partitioning   = true,
                hive_types_autocast = false,
                union_by_name       = true
            )
        """)
        count   = con.execute(f"SELECT COUNT(*) FROM {SILVER_VIEW}").fetchone()[0]
        elapsed = round(time.time() - t0, 2)
        log.info(f"Silver .db built: {count:,} rows in {elapsed}s -> {LOCAL_DB_PATH}")
        con.close()
        return True

    except Exception as exc:
        log.error(f"Silver .db build failed: {exc}")
        # Remove corrupt .db so get_connection() falls back to Parquet VIEW
        if os.path.exists(LOCAL_DB_PATH):
            try:
                os.remove(LOCAL_DB_PATH)
            except OSError:
                pass
        return False


# ── Internal helpers ───────────────────────────────────────────────────────────

def _get_aws_credentials():
    session = boto3.Session()
    creds   = session.get_credentials()
    if creds is None:
        raise RuntimeError("No AWS credentials found.")
    return creds.get_frozen_credentials()


def _configure_s3(con: duckdb.DuckDBPyConnection, creds) -> None:
    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")
    con.execute(f"SET s3_region = '{AWS_REGION}';")
    con.execute(f"SET s3_access_key_id     = '{creds.access_key}';")
    con.execute(f"SET s3_secret_access_key = '{creds.secret_key}';")
    if creds.token:
        con.execute(f"SET s3_session_token = '{creds.token}';")


def _create_silver_view_from_glob(con: duckdb.DuckDBPyConnection, glob_path: str) -> None:
    con.execute(f"""
        CREATE OR REPLACE VIEW {SILVER_VIEW} AS
        SELECT *
        FROM read_parquet(
            '{glob_path}',
            hive_partitioning   = true,
            hive_types_autocast = false,
            union_by_name       = true
        )
    """)


# ── Public API ────────────────────────────────────────────────────────────────

def get_connection() -> duckdb.DuckDBPyConnection:
    """
    Open a new DuckDB connection with Silver data accessible as SILVER_VIEW.

    Priority:
      1. Persistent .db  — Silver TABLE in DuckDB native format (~30x faster).
      2. Local Parquet   — VIEW over /tmp/silver/*.parquet (fallback).
      3. S3 httpfs       — VIEW over S3 Parquet (last resort, slow).

    NOTE: For the Fargate API process, use get_cached_connection() instead —
    it returns the long-lived singleton and avoids connection setup overhead
    on every request. Use get_connection() only for one-off CLI scripts where
    the caller explicitly manages and closes the connection.
    """
    t0 = time.time()

    _mem_raw = DUCKDB_MEMORY.strip().upper()
    _mem_mb  = (
        int(_mem_raw.replace("GB", "").strip()) * 1024 if "GB" in _mem_raw else
        int(_mem_raw.replace("MB", "").strip())        if "MB" in _mem_raw else
        6144
    )

    # ── Tier 1: persistent .db ────────────────────────────────────────────────
    if os.path.exists(LOCAL_DB_PATH):
        try:
            con = duckdb.connect(LOCAL_DB_PATH, read_only=True)
            con.execute(f"PRAGMA threads={DUCKDB_THREADS};")
            con.execute(f"PRAGMA memory_limit='{_mem_mb}MB';")
            # Silver TABLE already exists in .db — no view creation needed
            elapsed = round(time.time() - t0, 3)
            log.info(
                f"DuckDB connection ready | mode=local-db threads={DUCKDB_THREADS} "
                f"memory={DUCKDB_MEMORY} | setup={elapsed}s"
            )
            return con
        except Exception as exc:
            log.warning(f"Failed to open .db, falling back to Parquet: {exc}")

    # ── Tier 2: local Parquet VIEW ────────────────────────────────────────────
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={DUCKDB_THREADS};")
    con.execute(f"PRAGMA memory_limit='{_mem_mb}MB';")

    local_files_exist = (
        os.path.isdir(LOCAL_SILVER_DIR) and
        any(
            fname.endswith(".parquet")
            for _, _, fnames in os.walk(LOCAL_SILVER_DIR)
            for fname in fnames
        )
    )

    if local_files_exist:
        _create_silver_view_from_glob(con, LOCAL_SILVER_GLOB)
        mode = "local-parquet"
    else:
        # ── Tier 3: S3 httpfs ─────────────────────────────────────────────────
        creds = _get_aws_credentials()
        _configure_s3(con, creds)
        _create_silver_view_from_glob(con, SILVER_GLOB)
        mode = "s3-httpfs"

    elapsed = round(time.time() - t0, 3)
    log.info(
        f"DuckDB connection ready | mode={mode} threads={DUCKDB_THREADS} "
        f"memory={DUCKDB_MEMORY} | setup={elapsed}s"
    )
    return con


# ── Cached singleton (Fargate API process) ────────────────────────────────────

_cached_con: "duckdb.DuckDBPyConnection | None" = None
_cached_con_lock = _threading.Lock()


def is_connection_warm() -> bool:
    return _cached_con is not None


def get_cached_connection() -> "duckdb.DuckDBPyConnection":
    """
    Thread-safe singleton DuckDB connection for the long-lived Fargate process.

    Cold start (first call): opens connection, creates Silver view (~1–4s).
    Warm start (subsequent calls): returns cached connection instantly (<1ms).

    IMPORTANT: Never call con.close() on the result. The connection must persist
    for the lifetime of the Fargate task. Call reset_cached_connection() to
    force a reconnect on unrecoverable errors.
    """
    global _cached_con
    with _cached_con_lock:
        if _cached_con is None:
            log.info("DuckDB: cold start — opening connection ...")
            _cached_con = get_connection()
            log.info("DuckDB: connection cached.")
        return _cached_con


def reset_cached_connection() -> None:
    global _cached_con
    with _cached_con_lock:
        _cached_con = None
        log.warning("DuckDB: cached connection reset — next query will cold-start.")


# -- Admin hot-reload --------------------------------------------------------

_reload_lock = _threading.Lock()


def reload_silver() -> dict:
    """
    Hot-reload Silver without ECS redeployment.

    Steps:
      1. Close and drop the cached connection (allows .db deletion on Windows).
      2. Re-sync S3 Silver Parquet -> /tmp/silver/ (size-checked, only changed partitions).
      3. Rebuild local .db from refreshed Parquet files.
      4. Open and cache a fresh connection against the new .db.

    Concurrent calls are rejected immediately (RuntimeError).
    Run this in a thread pool -- it is blocking I/O + CPU.

    Returns dict: { status, total_rows, elapsed_s }
    """
    if not _reload_lock.acquire(blocking=False):
        raise RuntimeError("Reload already in progress -- try again shortly")

    t0 = time.time()
    try:
        global _cached_con

        # Step 1: close cached connection before touching the .db file.
        # On Windows an open file handle blocks deletion; on Linux harmless.
        with _cached_con_lock:
            if _cached_con is not None:
                try:
                    _cached_con.close()
                except Exception:
                    pass
                _cached_con = None
                log.info("Silver reload: cached connection closed.")

        # Step 2 + 3: S3 sync and .db rebuild (size-checked).
        ok = download_silver_locally()
        if not ok:
            raise RuntimeError("Silver sync or .db rebuild failed -- check server logs")

        # Step 4: open fresh cached connection and warm it up.
        con       = get_cached_connection()
        row_count = con.execute(f"SELECT COUNT(*) FROM {SILVER_VIEW}").fetchone()[0]

        elapsed = round(time.time() - t0, 1)
        log.info(f"Silver reload complete: {row_count:,} rows in {elapsed}s")
        return {"status": "ok", "total_rows": row_count, "elapsed_s": elapsed}

    except Exception:
        # Reset connection so the app can recover on next request.
        with _cached_con_lock:
            _cached_con = None
        raise
    finally:
        _reload_lock.release()


# ── Query helpers ─────────────────────────────────────────────────────────────

def _parse_order_code(order_code: str, manufacturer: str = "") -> dict:
    """
    Parse a manufacturer order code into family + PPR tokens.

    Handles:
      Kübler:  "8.KIS40.1342.1024"  -> family="KIS40",  ppr=1024
      Kübler:  "8.5814.122A.2048"   -> family="Sendix 5814", ppr=2048
                                       (numeric-only tokens normalised via KUBLER_FAMILY_ALIASES)
      EPC:     "EPC-755A-07-S-XXXX-R-HV-S-K00" -> family=755A, ppr=None, mfr_hint=epc
      Sick:    "DFS60E-S4EA01024"   -> family=DFS60E, ppr=None

    Returns mfr_hint when the order code unambiguously identifies a manufacturer.
    """
    import re

    oc_upper = order_code.upper()

    # EPC synthetic codes start with "EPC-"; real EPC codes start with a
    # known family token (e.g. "802S-", "755A-", "15S-", "58TF-").
    mfr_hint = None
    first_token = re.split(r"[._-]", order_code)[0].upper()
    if oc_upper.startswith("EPC-") or first_token in {k.upper() for k in EPC_FAMILY_CONFIGS}:
        mfr_hint = "epc"
    elif first_token in LIKA_FAMILY_PREFIXES:
        mfr_hint = "lika"
    elif first_token in BAUMER_FAMILY_PREFIXES:
        mfr_hint = "baumer"

    tokens = re.split(r"[._-]", order_code)

    family = None

    # For Kübler, try dot-split first: parts[1] is always the family token
    # (handles purely numeric families like "5814", "2400" that the alpha-leading
    # regex below would miss).
    if manufacturer.lower() == "kubler":
        parts = [p for p in order_code.strip().split(".") if p]
        if len(parts) >= 4:
            candidate = parts[1]
            # Normalise via alias map: "5814" -> "Sendix 5814", "A020" -> "A020"
            family = KUBLER_FAMILY_ALIASES.get(candidate, candidate)

    # Generic alpha-leading fallback (used for non-Kübler and as Kübler backup)
    if family is None:
        for t in tokens:
            if re.match(r"^[A-Za-z][A-Za-z0-9]+$", t) and len(t) >= 3 and t.upper() not in ("EPC",):
                family = t
                break

    ppr = None
    for t in reversed(tokens):
        if re.match(r"^\d+$", t):
            val = int(t)
            if 10 <= val <= 65536:
                ppr = val
                break

    return {"family": family, "ppr": ppr, "raw_tokens": tokens, "mfr_hint": mfr_hint}


def _fetch_kubler_by_decoded_spec(con: duckdb.DuckDBPyConnection,
                                   decoded) -> "dict | None":
    """
    Progressively looser SQL queries for a fully-decoded Kübler order code.

    Attempt 1 — bore + output + supply_v (min+max) + connection + IP + shaft_type
    Attempt 2 — bore + output + supply_min + connection  (drop IP)
    Attempt 3 — bore + output + connection               (drop supply_v)
    Attempt 4 — bore + output                            (drop connection)
    Attempt 5 — bore only                                (last resort)

    shaft_type_override (e.g. "solid", "hollow_thru") is added to every attempt
    when available — prevents K58I shaft rows matching K58I hollow rows.

    Returns the first matching Silver row as a dict, or None if all fail.
    """
    base_cond   = "manufacturer = 'kubler' AND product_family = ?"
    base_params = [decoded.silver_family]

    # Optional shaft_type filter — always include when known
    shaft_cond   = ""
    shaft_params: list = []
    if decoded.shaft_type_override:
        shaft_cond   = " AND shaft_type = ?"
        shaft_params = [decoded.shaft_type_override]

    bore_cond = "ABS(shaft_bore_diameter_mm - ?) < 1.0"

    def _run(extra_cond: str, extra_params: list, label: str) -> "dict | None":
        sql = f"""
            SELECT * FROM {SILVER_VIEW}
            WHERE {base_cond}{shaft_cond}
              AND {extra_cond}
            ORDER BY ABS(shaft_bore_diameter_mm - ?)
            LIMIT 1
        """
        rows = con.execute(
            sql,
            base_params + shaft_params + extra_params + [decoded.shaft_bore_mm]
        ).fetchdf()
        if not rows.empty:
            log.info(
                f"  [fetch_kubler] {label}: "
                f"family={decoded.silver_family}  bore={decoded.shaft_bore_mm}mm  "
                f"{decoded.output_circuit_canonical}  {decoded.connection_type_canonical}"
            )
            return rows.iloc[0].to_dict()
        return None

    # Attempt 1: full match — bore + output + supply(min+max) + connection + IP
    if all([decoded.shaft_bore_mm, decoded.output_circuit_canonical,
            decoded.supply_voltage_min_v is not None,
            decoded.supply_voltage_max_v is not None,
            decoded.connection_type_canonical]):
        ip_cond   = " AND ip_rating = ?" if decoded.ip_rating is not None else ""
        ip_params = [decoded.ip_rating]  if decoded.ip_rating is not None else []
        row = _run(
            f"{bore_cond} AND output_circuit_canonical = ?"
            f" AND ABS(supply_voltage_min_v - ?) < 0.5"
            f" AND ABS(supply_voltage_max_v - ?) < 0.5"
            f" AND connection_type_canonical = ?"
            f"{ip_cond}",
            [decoded.shaft_bore_mm,
             decoded.output_circuit_canonical,
             decoded.supply_voltage_min_v,
             decoded.supply_voltage_max_v,
             decoded.connection_type_canonical] + ip_params,
            "full match"
        )
        if row:
            return row

    # Attempt 2: bore + output + supply_min + connection  (drop supply_max + IP)
    if all([decoded.shaft_bore_mm, decoded.output_circuit_canonical,
            decoded.supply_voltage_min_v is not None,
            decoded.connection_type_canonical]):
        row = _run(
            f"{bore_cond} AND output_circuit_canonical = ?"
            f" AND ABS(supply_voltage_min_v - ?) < 0.5"
            f" AND connection_type_canonical = ?",
            [decoded.shaft_bore_mm,
             decoded.output_circuit_canonical,
             decoded.supply_voltage_min_v,
             decoded.connection_type_canonical],
            "bore+output+supply_min+connection"
        )
        if row:
            return row

    # Attempt 3: bore + output + connection  (drop supply entirely)
    if all([decoded.shaft_bore_mm, decoded.output_circuit_canonical,
            decoded.connection_type_canonical]):
        row = _run(
            f"{bore_cond} AND output_circuit_canonical = ?"
            f" AND connection_type_canonical = ?",
            [decoded.shaft_bore_mm,
             decoded.output_circuit_canonical,
             decoded.connection_type_canonical],
            "bore+output+connection"
        )
        if row:
            return row

    # Attempt 4: bore + output
    if all([decoded.shaft_bore_mm, decoded.output_circuit_canonical]):
        row = _run(
            f"{bore_cond} AND output_circuit_canonical = ?",
            [decoded.shaft_bore_mm, decoded.output_circuit_canonical],
            "bore+output"
        )
        if row:
            return row

    # Attempt 5: bore only
    if decoded.shaft_bore_mm:
        row = _run(bore_cond, [decoded.shaft_bore_mm], "bore only")
        if row:
            return row

    log.warning(
        f"  [fetch_kubler] No Silver row found: "
        f"family={decoded.silver_family}  bore={decoded.shaft_bore_mm}mm"
    )
    return None



def _fetch_epc_by_decoded_spec(con: duckdb.DuckDBPyConnection,
                                decoded) -> "dict | None":
    """
    Progressively looser SQL queries for a fully-decoded EPC real order code.

    Mirrors _fetch_kubler_by_decoded_spec — same 5-attempt widening strategy.
    Uses shaft_type (solid / hollow_blind / hollow_thru) as a hard filter on every
    attempt since EPC families often share a Silver product_family name across
    shaft types (e.g. 755A has both solid and hollow_blind rows).

    Attempt 1 — bore + shaft_type + output + supply_v + connection + IP
    Attempt 2 — bore + shaft_type + output + connection  (drop supply + IP)
    Attempt 3 — bore + shaft_type + output               (drop connection)
    Attempt 4 — bore + shaft_type                        (drop output)
    Attempt 5 — family + shaft_type only                 (last resort)
    """
    base_cond   = "manufacturer = 'epc' AND product_family = ?"
    base_params = [decoded.silver_family]

    shaft_cond   = " AND shaft_type = ?" if decoded.shaft_type else ""
    shaft_params = [decoded.shaft_type]  if decoded.shaft_type else []

    bore_cond = "ABS(shaft_bore_diameter_mm - ?) < 1.0"

    def _run(extra_cond: str, extra_params: list, label: str) -> "dict | None":
        sql = f"""
            SELECT * FROM {SILVER_VIEW}
            WHERE {base_cond}{shaft_cond}
              AND {extra_cond}
            ORDER BY ABS(shaft_bore_diameter_mm - ?)
            LIMIT 1
        """
        rows = con.execute(
            sql,
            base_params + shaft_params + extra_params + [decoded.shaft_bore_mm]
        ).fetchdf()
        if not rows.empty:
            log.info(
                f"  [fetch_epc] {label}: "
                f"family={decoded.silver_family}  bore={decoded.shaft_bore_mm}mm  "
                f"shaft={decoded.shaft_type}  {decoded.output_circuit_canonical}"
            )
            return rows.iloc[0].to_dict()
        return None

    def _run_no_bore(extra_cond: str, extra_params: list, label: str) -> "dict | None":
        """Fallback when bore is unknown — no ORDER BY bore distance."""
        sql = f"""
            SELECT * FROM {SILVER_VIEW}
            WHERE {base_cond}{shaft_cond}
              AND {extra_cond}
            ORDER BY part_number
            LIMIT 1
        """
        rows = con.execute(sql, base_params + shaft_params + extra_params).fetchdf()
        if not rows.empty:
            log.info(f"  [fetch_epc] {label}: family={decoded.silver_family}")
            return rows.iloc[0].to_dict()
        return None

    # Attempt 1: full match — bore + output + supply_v + connection + IP
    if all([decoded.shaft_bore_mm, decoded.output_circuit_canonical,
            decoded.supply_voltage_min_v is not None,
            decoded.connection_type_canonical]):
        ip_cond   = " AND ip_rating = ?" if decoded.ip_rating is not None else ""
        ip_params = [decoded.ip_rating]  if decoded.ip_rating is not None else []
        row = _run(
            f"{bore_cond} AND output_circuit_canonical = ?"
            f" AND ABS(supply_voltage_min_v - ?) < 0.5"
            f" AND connection_type_canonical = ?"
            f"{ip_cond}",
            [decoded.shaft_bore_mm,
             decoded.output_circuit_canonical,
             decoded.supply_voltage_min_v,
             decoded.connection_type_canonical] + ip_params,
            "full match"
        )
        if row:
            return row

    # Attempt 2: bore + output + connection  (drop supply + IP)
    if all([decoded.shaft_bore_mm, decoded.output_circuit_canonical,
            decoded.connection_type_canonical]):
        row = _run(
            f"{bore_cond} AND output_circuit_canonical = ?"
            f" AND connection_type_canonical = ?",
            [decoded.shaft_bore_mm,
             decoded.output_circuit_canonical,
             decoded.connection_type_canonical],
            "bore+output+connection"
        )
        if row:
            return row

    # Attempt 3: bore + output  (drop connection)
    if all([decoded.shaft_bore_mm, decoded.output_circuit_canonical]):
        row = _run(
            f"{bore_cond} AND output_circuit_canonical = ?",
            [decoded.shaft_bore_mm, decoded.output_circuit_canonical],
            "bore+output"
        )
        if row:
            return row

    # Attempt 4: bore + shaft_type only  (drop output)
    if decoded.shaft_bore_mm:
        row = _run(bore_cond, [decoded.shaft_bore_mm], "bore only")
        if row:
            return row

    # Attempt 5: family + shaft_type only (no bore)
    row = _run_no_bore("1=1", [], "family+shaft_type only")
    if row:
        return row

    log.warning(
        f"  [fetch_epc] No Silver row found: "
        f"family={decoded.silver_family}  bore={decoded.shaft_bore_mm}mm  "
        f"shaft={decoded.shaft_type}"
    )
    return None


def fetch_part(con: duckdb.DuckDBPyConnection,
               part_number: str,
               manufacturer: str) -> dict | None:
    """
    Fetch a single source part by part_number + manufacturer.

    Lookup stages
    -------------
    1. Exact match on Silver part_number column.
    2. (Kübler only) Real order-code decode -> targeted SQL on hardware params.
       If decode succeeds, overrides cpr_values with [specific_ppr] so the
       matcher scores candidates on "does it cover this exact PPR?" rather than
       the full family catalog list.
    3. PPR-aware family lookup: family + cpr_values LIKE '%ppr%'.
       For Kübler, the family name is normalised via KUBLER_FAMILY_ALIASES so
       numeric tokens like "5814" correctly resolve to "Sendix 5814" in Silver.
    4. Family-only LIKE fallback.

    Returns a dict of field->value for one Silver row, or None if not found.
    """
    import json as _json

    # ── Stage 1: exact part_number match ────────────────────────────────────
    rows = con.execute(f"""
        SELECT * FROM {SILVER_VIEW}
        WHERE manufacturer = ? AND part_number = ?
        LIMIT 1
    """, [manufacturer, part_number]).fetchdf()
    if not rows.empty:
        return rows.iloc[0].to_dict()

    # ── Stage 2: Kübler real order code decode ───────────────────────────────
    silver_family: "str | None" = None
    specific_ppr:  "int | None" = None

    if manufacturer.lower() == "kubler":
        decoded = decode_kubler_order_code(part_number)
        if decoded is not None:
            silver_family = decoded.silver_family
            specific_ppr  = decoded.ppr

            if decoded.decode_success:
                row = _fetch_kubler_by_decoded_spec(con, decoded)
                if row is not None:
                    # Override cpr_values to the single PPR the customer specified.
                    # This makes the matcher score "does candidate cover 2048?"
                    # rather than "does candidate cover all 12 family PPR values?"
                    if specific_ppr is not None:
                        row["cpr_values"] = _json.dumps([specific_ppr])
                        log.info(f"  [fetch_part] CPR override -> [{specific_ppr}]")
                    return row
            else:
                log.info(f"  [fetch_part] Kübler partial decode: "
                         f"family={silver_family!r} ppr={specific_ppr} "
                         f"| {'; '.join(decoded.decode_notes)}")
            # Partial decode: fall through to Stage 3 with normalised family name

    # ── Stage 2b: EPC real order code decode ────────────────────────────────
    if manufacturer.lower() == "epc":
        decoded_epc = decode_epc_order_code(part_number)
        if decoded_epc is not None:
            silver_family = decoded_epc.silver_family
            specific_ppr  = decoded_epc.ppr

            if decoded_epc.decode_success:
                row = _fetch_epc_by_decoded_spec(con, decoded_epc)
                if row is not None:
                    if specific_ppr is not None:
                        import json as _json2
                        row["cpr_values"] = _json2.dumps([specific_ppr])
                        log.info(f"  [fetch_part] EPC CPR override -> [{specific_ppr}]")
                    return row
            else:
                log.info(f"  [fetch_part] EPC partial decode: "
                         f"family={silver_family!r} ppr={specific_ppr} "
                         f"| {'; '.join(decoded_epc.decode_notes)}")
            # Partial decode: fall through to Stage 3 with known family name

    # ── Stage 2c: Lika positional decode ──────────────────────────────────
    # Lika codes are always: FAMILY-SUPPLY-CPR-BORE-...
    # CPR is at dash-split index 2. Family is at index 0.
    # No full decoder needed -- positional extract is sufficient.
    if manufacturer.lower() == "lika" and silver_family is None:
        _lika_parts = part_number.split("-")
        if len(_lika_parts) >= 1:
            silver_family = _lika_parts[0]   # always the family name
        if len(_lika_parts) >= 3 and _lika_parts[2].isdecimal():
            specific_ppr = int(_lika_parts[2])
            log.info(f"  [fetch_part] Lika positional decode: "
                     f"family={silver_family!r} ppr={specific_ppr}")

    # ── Stage 3: PPR-aware family lookup ────────────────────────────────────
    parsed   = _parse_order_code(part_number, manufacturer)
    # Use Silver-normalised family name if decode gave us one; otherwise parsed token
    family   = silver_family or parsed["family"]
    ppr      = specific_ppr  or parsed["ppr"]
    mfr_hint = parsed.get("mfr_hint")

    if mfr_hint and mfr_hint != manufacturer.lower():
        return None

    if family and ppr:
        ppr_pattern = f"%{ppr}%"
        candidates  = con.execute(f"""
            SELECT * FROM {SILVER_VIEW}
            WHERE manufacturer  = ?
              AND product_family = ?
              AND (
                    cpr_values LIKE ?
                    OR (CAST(ppr_range_min AS INTEGER) <= ?
                        AND CAST(ppr_range_max AS INTEGER) >= ?)
                  )
            ORDER BY part_number
        """, [manufacturer, family, ppr_pattern, ppr, ppr]).fetchdf()

        if not candidates.empty:
            log.info(f"  [fetch_part] PPR-family match: '{part_number}' -> "
                     f"family='{family}' PPR={ppr}  ({len(candidates)} candidates, using first)")
            row = candidates.iloc[0].to_dict()
            # Still override cpr_values with the specific PPR when we have one
            if specific_ppr is not None:
                row["cpr_values"] = _json.dumps([specific_ppr])
            return row

    # ── Stage 4: family-only fallback ───────────────────────────────────────
    if family:
        rows = con.execute(f"""
            SELECT * FROM {SILVER_VIEW}
            WHERE manufacturer   = ?
              AND product_family = ?
            LIMIT 1
        """, [manufacturer, family]).fetchdf()
        if not rows.empty:
            matched = rows.iloc[0]["part_number"]
            log.info(f"  [fetch_part] Family fallback '{family}' -> '{matched}'")
            return rows.iloc[0].to_dict()

    return None


def find_parts(con: duckdb.DuckDBPyConnection,
               manufacturer: str,
               family: str | None = None,
               part_fragment: str | None = None,
               limit: int = 20) -> "pd.DataFrame":
    """Browse available part numbers in Silver."""
    conditions = ["manufacturer = ?"]
    params: list = [manufacturer]

    if family:
        conditions.append("product_family = ?")
        params.append(family)
    if part_fragment:
        conditions.append("part_number LIKE ?")
        params.append(f"%{part_fragment}%")

    where = " AND ".join(conditions)
    return con.execute(f"""
        SELECT part_number, product_family, shaft_type,
               output_circuit_canonical, ip_rating,
               connection_type_canonical, connector_pins, cpr_values
        FROM {SILVER_VIEW}
        WHERE {where}
        ORDER BY product_family, part_number
        LIMIT {limit}
    """, params).fetchdf()


def fetch_candidates(con: duckdb.DuckDBPyConnection,
                     shaft_type: str,
                     output_voltage_class: str,
                     target_manufacturer: str,
                     src_ip_rating: int | None = None,
                     src_housing_mm: float | None = None) -> "pd.DataFrame":
    """
    T1 SQL pre-filter: returns candidate rows for Python scoring.

    Hard stops in SQL (Silver sort order enables row-group pruning):
      - manufacturer = target
      - shaft_type   exact match
      - output_voltage_class exact match

    Soft IP floor (src - 2): excludes candidates clearly below source IP rating.
    Example: source IP64 -> floor=62, drops IP50 and below.

    Housing diameter pre-filter (±15 mm): when source housing diameter is known,
    candidates outside src±25mm are excluded. NULL housing_diameter_mm candidates
    (NEMA, spring-element flanges) are always kept regardless of this filter.
    This reduces EPC candidate volume by ~60-70% for typical shaft encoder queries
    (e.g. a 58mm Kübler source excludes 165mm and 228mm EPC C-Face models before
    any Python scoring begins).

    IP and housing are still scored in T2 — the filters only trim clearly
    out-of-range candidates, not borderline cases.
    """
    conditions = [
        "manufacturer         = ?",
        "output_voltage_class = ?",
    ]
    params: list = [target_manufacturer, output_voltage_class]

    # shaft_type is a T1 hard stop only when the source has a known shaft type.
    # If shaft_type is empty/null (some Sick encoders don't populate this field),
    # omit the filter so candidates aren't silently excluded at the SQL stage.
    # The Python-level T1 check in matcher.py still enforces shaft_type when known.
    if shaft_type:
        conditions.insert(1, "shaft_type = ?")
        params.insert(1, shaft_type)

    ip_floor = None
    if src_ip_rating is not None:
        ip_floor = max(0, int(src_ip_rating) - 2)
        conditions.append("(ip_rating IS NULL OR ip_rating >= ?)")
        params.append(ip_floor)

    housing_filter_str = None
    # Housing pre-filter is skipped for hollow encoders.
    # For hollow shaft installations the encoder slides onto the shaft and is
    # held by a torque arm or spring element — the housing OD is a soft
    # preference, not a hard physical constraint the way it is for solid shaft
    # face-mount or servo-flange encoders.  Applying a tight ±15mm window was
    # silently dropping valid candidates (e.g. a 100mm Posital hollow for an
    # 80mm K80I source).  T2 scoring still penalises housing diameter mismatches
    # for hollow encoders — this filter only controls the SQL pre-fetch volume.
    if src_housing_mm is not None and shaft_type not in ("hollow_blind", "hollow_thru"):
        try:
            h = float(src_housing_mm)
            if not math.isnan(h) and h > 0:
                lo = h - 15.0
                hi = h + 15.0
                conditions.append(
                    "(housing_diameter_mm IS NULL OR "
                    "(housing_diameter_mm >= ? AND housing_diameter_mm <= ?))"
                )
                params.extend([lo, hi])
                housing_filter_str = f"{lo:.1f}–{hi:.1f} mm"
        except (TypeError, ValueError):
            pass

    where_clause = "\n          AND ".join(conditions)

    t0     = time.time()
    result = con.execute(f"""
        SELECT *
        FROM {SILVER_VIEW}
        WHERE {where_clause}
    """, params).fetchdf()
    elapsed = round(time.time() - t0, 3)

    # Filter out Posital products with lifecycle = "Exiting".
    # POSITAL_EXITING_PARTS is loaded once at startup from Bronze2 CSV.
    # Applied after SQL fetch (not in SQL) since lifecycle isn't in Silver.
    posital_filtered = 0
    if target_manufacturer == "posital" and POSITAL_EXITING_PARTS:
        before = len(result)
        result = result[~result["part_number"].isin(POSITAL_EXITING_PARTS)]
        posital_filtered = before - len(result)

    log.info(
        f"fetch_candidates | mfr={target_manufacturer} shaft={shaft_type} "
        f"voltage={output_voltage_class} ip_floor={ip_floor or 'none'} "
        f"housing={housing_filter_str or 'none'} "
        f"posital_exiting_filtered={posital_filtered} "
        f"-> {len(result):,} rows | {elapsed}s"
    )
    return result


# ── Sanity check ──────────────────────────────────────────────────────────────

def _sanity_check():
    print("Connecting to DuckDB ...")
    con = get_connection()

    counts = con.execute(f"""
        SELECT manufacturer, COUNT(*) AS rows
        FROM {SILVER_VIEW}
        GROUP BY manufacturer ORDER BY manufacturer
    """).fetchdf()
    print("\nRow counts:\n", counts.to_string(index=False))

    print("\nSample fetch (solid/universal -> epc):")
    cands = fetch_candidates(con, "solid", "universal", "epc")
    print(f"  {len(cands):,} candidates")

    con.close()
    print("Sanity check passed.")


if __name__ == "__main__":
    _sanity_check()