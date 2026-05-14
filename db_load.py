"""
db_load.py
==========
DuckDB connection manager for the encoder cross-reference pipeline.

Architecture: Option A — DuckDB queries S3 Silver Parquet directly via httpfs.
No local .duckdb file. Every query uses predicate pushdown + column pruning
against the hive-partitioned Silver Parquet on S3.

S3 layout expected:
    encoder_pipeline/silver/manufacturer=kubler/data.parquet
    encoder_pipeline/silver/manufacturer=epc/data.parquet
    encoder_pipeline/silver/manufacturer=sick/data.parquet

Usage:
    from db_load import get_connection, SILVER_VIEW

    con = get_connection()
    df  = con.execute(f"SELECT * FROM {SILVER_VIEW} WHERE manufacturer = 'epc'").fetchdf()
    con.close()

Or as a context manager:
    with get_connection() as con:
        df = con.execute(...).fetchdf()

AQB Solutions | May 2026
"""

import logging
import os
import time
import duckdb
import boto3
import pandas as pd

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("db_load")

# ── S3 config ─────────────────────────────────────────────────────────────────
S3_BUCKET  = os.environ.get("S3_BUCKET",  "aqb-data-analytics-demo")
S3_ROOT    = os.environ.get("S3_ROOT",    "encoder_pipeline")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

# ── DuckDB performance config (tune via task definition env vars) ─────────────
DUCKDB_THREADS = int(os.environ.get("DUCKDB_THREADS", "2"))   # match Fargate vCPU
DUCKDB_MEMORY  = os.environ.get("DUCKDB_MEMORY",  "6GB")      # leave headroom vs 8GB Fargate

# Hive-partitioned glob covering all manufacturers — S3 (httpfs fallback)
SILVER_GLOB = f"s3://{S3_BUCKET}/{S3_ROOT}/silver/manufacturer=*/data.parquet"

# Local cache: Silver downloaded here at startup via boto3 (no httpfs dependency)
LOCAL_SILVER_DIR  = "/tmp/silver"
LOCAL_SILVER_GLOB = f"{LOCAL_SILVER_DIR}/manufacturer=*/data.parquet"

# Name of the DuckDB view the matcher queries against
SILVER_VIEW = "silver"

# ── S3 -> local Silver download (boto3, works on Fargate task role) ────────────

def download_silver_locally() -> bool:
    """
    Download all Silver Parquet files from S3 to LOCAL_SILVER_DIR using boto3.

    Uses boto3 instead of DuckDB httpfs so that:
    - VPC S3 gateway endpoints are honoured
    - IAM task role credentials work correctly (no httpfs credential quirks)
    - DuckDB queries then read from local disk — fast, no network per query

    Returns True on success, False if anything fails (caller falls back to httpfs).
    Safe to call multiple times — skips files that already exist.
    """
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    prefix    = f"{S3_ROOT}/silver/"

    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        downloaded = 0
        skipped    = 0

        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".parquet"):
                    continue

                # Strip the S3 prefix -> relative path under LOCAL_SILVER_DIR
                # e.g. encoder_pipeline/silver/manufacturer=kubler/data.parquet
                #   ->  manufacturer=kubler/data.parquet
                rel   = key[len(prefix):]
                local = os.path.join(LOCAL_SILVER_DIR, rel)
                os.makedirs(os.path.dirname(local), exist_ok=True)

                if os.path.exists(local):
                    skipped += 1
                    continue

                size_mb = round(obj["Size"] / 1_048_576, 1)
                log.info(f"  Downloading {key} ({size_mb} MB) -> {local}")
                s3_client.download_file(S3_BUCKET, key, local)
                downloaded += 1

        log.info(
            f"Silver sync complete: {downloaded} downloaded, {skipped} already cached "
            f"| dir={LOCAL_SILVER_DIR}"
        )
        return True

    except Exception as exc:
        log.error(f"Silver download failed: {exc}")
        return False

# ── Internal helpers ───────────────────────────────────────────────────────────

def _get_aws_credentials():
    """
    Resolve AWS credentials via boto3 credential chain:
      1. Environment variables (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
      2. ~/.aws/credentials  (local dev)
      3. IAM instance profile / ECS task role  (Fargate production)
    Returns a frozen credential object with .access_key, .secret_key, .token.
    """
    session = boto3.Session()
    creds   = session.get_credentials()
    if creds is None:
        raise RuntimeError(
            "No AWS credentials found. Set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY "
            "or configure an IAM role."
        )
    return creds.get_frozen_credentials()


def _configure_s3(con: duckdb.DuckDBPyConnection, creds) -> None:
    """Install httpfs and configure S3 settings on a DuckDB connection."""
    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")
    con.execute(f"SET s3_region = '{AWS_REGION}';")
    con.execute(f"SET s3_access_key_id     = '{creds.access_key}';")
    con.execute(f"SET s3_secret_access_key = '{creds.secret_key}';")
    if creds.token:
        con.execute(f"SET s3_session_token = '{creds.token}';")


def _create_silver_view(con: duckdb.DuckDBPyConnection) -> None:
    _create_silver_view_from_glob(con, SILVER_GLOB)


def _create_silver_view_from_glob(con: duckdb.DuckDBPyConnection, glob_path: str) -> None:
    """
    Create the 'silver' view pointing at the given glob path (local or S3).
    hive_partitioning=true infers 'manufacturer' from directory names and
    enables partition pruning + predicate pushdown within each file.
    """
    con.execute(f"""
        CREATE OR REPLACE VIEW {SILVER_VIEW} AS
        SELECT *
        FROM read_parquet(
            '{glob_path}',
            hive_partitioning   = true,
            hive_types_autocast = false
        )
    """)


# ── Public API ────────────────────────────────────────────────────────────────

def get_connection() -> duckdb.DuckDBPyConnection:
    """
    Return a configured DuckDB connection with the 'silver' view.

    Prefers local Silver files if downloaded at startup (fast, no network per query).
    Falls back to S3 httpfs if local files are absent — this was the original
    working approach and remains the reliable fallback.

    Caller is responsible for closing: con.close() or use as context manager.
    """
    t0  = time.time()
    con = duckdb.connect()

    con.execute(f"PRAGMA threads={DUCKDB_THREADS};")
    # Use MB to avoid unit-parsing issues across DuckDB versions / platforms.
    # Parse DUCKDB_MEMORY env var (e.g. "6GB" -> 6144 MB), fallback to 6144 MB.
    _mem_raw = os.environ.get("DUCKDB_MEMORY", "6GB").strip().upper()
    _mem_mb  = (
        int(_mem_raw.replace("GB","").strip()) * 1024 if "GB" in _mem_raw else
        int(_mem_raw.replace("MB","").strip())        if "MB" in _mem_raw else
        6144
    )
    con.execute(f"PRAGMA memory_limit='{_mem_mb}MB';")

    # Use local files if available (downloaded at startup), else S3 httpfs
    local_files_exist = (
        os.path.isdir(LOCAL_SILVER_DIR) and
        any(
            fname.endswith(".parquet")
            for _, _, fnames in os.walk(LOCAL_SILVER_DIR)
            for fname in fnames
        )
    )

    if local_files_exist:
        glob_path = LOCAL_SILVER_GLOB
        mode      = "local"
    else:
        creds = _get_aws_credentials()
        _configure_s3(con, creds)
        glob_path = SILVER_GLOB
        mode      = "s3-httpfs"

    _create_silver_view_from_glob(con, glob_path)

    elapsed = round(time.time() - t0, 3)
    log.info(
        f"DuckDB connection ready | mode={mode} threads={DUCKDB_THREADS} "
        f"memory={DUCKDB_MEMORY} | setup={elapsed}s"
    )
    return con


# ── Convenience query helpers ─────────────────────────────────────────────────

def _parse_order_code(order_code: str) -> dict:
    """
    Parse a manufacturer order code into components.

    Extracts:
      family     — alphanumeric token that looks like a model family (e.g. "KIS40", "755A")
      ppr        — last all-digit segment if it looks like a PPR value (e.g. 1024)
      raw_tokens — all split tokens for debugging

    Handles formats:
      Kübler:  "8.KIS40.1342.1024"  -> family=KIS40, ppr=1024
      EPC:     "EPC-755A-S-1024-A"  -> family=755A,  ppr=1024
      Sick:    "DFS60E-S4EA01024"   -> family=DFS60E, ppr=None (embedded, not split)
    """
    import re
    tokens = re.split(r"[._-]", order_code)

    # Family: first token that starts with a letter and has length >= 3
    # Skip single-digit prefixes like "8" (Kübler system prefix) and "EPC" brand prefix
    family = None
    for t in tokens:
        if re.match(r"^[A-Za-z][A-Za-z0-9]+$", t) and len(t) >= 3 and t.upper() != "EPC":
            family = t
            break

    # PPR: last all-digit token that is a plausible PPR value (10–65536)
    ppr = None
    for t in reversed(tokens):
        if re.match(r"^\d+$", t):
            val = int(t)
            if 10 <= val <= 65536:
                ppr = val
                break

    return {"family": family, "ppr": ppr, "raw_tokens": tokens}


def fetch_part(con: duckdb.DuckDBPyConnection,
               part_number: str,
               manufacturer: str) -> dict | None:
    """
    Fetch a single source part by part_number + manufacturer.

    Three-stage lookup strategy:

    1. Exact match on part_number  — direct Silver lookup, fastest.

    2. PPR-aware family lookup  — parses the input as a real order code,
       extracts the family name and PPR value, then finds the Silver variant
       whose product_family matches AND whose cpr_values contains the PPR.
       If multiple variants match (different connection type / output circuit),
       returns all of them so the caller can prompt the user to disambiguate.
       e.g. "8.KIS40.1342.1024" -> family=KIS40, ppr=1024
            -> finds KIS40 variants where cpr_values contains 1024

    3. Family-only LIKE fallback  — if no PPR could be parsed, searches for
       any Silver row whose part_number contains the family token.

    NOTE (next session): replace stages 2 & 3 with a direct lookup on the
    planned `base_order_code` Silver field (e.g. "8.KIS40.1342.XXXX").
    That will make the lookup exact and remove the need for heuristic parsing.
    See: PIPELINE_CONTEXT_MAY11_2026.md § base_order_code

    Returns a dict of field->value for a single matched row,
    or None if nothing found.
    If stage 2 returns multiple variants, prints a disambiguation table
    and returns the first row (best guess by Silver sort order).
    """
    import re

    # ── Stage 1: exact match ──────────────────────────────────────────────────
    rows = con.execute(f"""
        SELECT *
        FROM {SILVER_VIEW}
        WHERE manufacturer = ?
          AND part_number   = ?
        LIMIT 1
    """, [manufacturer, part_number]).fetchdf()

    if not rows.empty:
        return rows.iloc[0].to_dict()

    # ── Stage 2: PPR-aware family lookup ─────────────────────────────────────
    parsed = _parse_order_code(part_number)
    family = parsed["family"]
    ppr    = parsed["ppr"]

    if family and ppr:
        # cpr_values is a JSON array string — check if PPR appears in it.
        # Using LIKE is safe here: PPR values are integers so "1024" won't
        # false-match "10240" because JSON arrays have ", " or "]" after each value.
        ppr_pattern = f"%{ppr}%"
        candidates = con.execute(f"""
            SELECT *
            FROM {SILVER_VIEW}
            WHERE manufacturer   = ?
              AND product_family  = ?
              AND (
                    cpr_values LIKE ?
                    OR (CAST(ppr_range_min AS INTEGER) <= ?
                        AND CAST(ppr_range_max AS INTEGER) >= ?)
                  )
            ORDER BY part_number
        """, [manufacturer, family, ppr_pattern, ppr, ppr]).fetchdf()

        if not candidates.empty:
            print(f"  [fetch_part] Parsed '{part_number}' -> "
                  f"family='{family}', PPR={ppr}")
            if len(candidates) == 1:
                print(f"  [fetch_part] Matched: {candidates.iloc[0]['part_number']}")
            else:
                print(f"  [fetch_part] {len(candidates)} variants match — "
                      f"using first. Use --find-parts to see all options:")
                display_cols = ["part_number", "shaft_type",
                                "output_circuit_canonical", "ip_rating",
                                "connection_type_canonical", "connector_pins"]
                print(candidates[display_cols].to_string(index=False))
                print()
            return candidates.iloc[0].to_dict()

    # ── Stage 3: family-only LIKE fallback ───────────────────────────────────
    if family:
        rows = con.execute(f"""
            SELECT *
            FROM {SILVER_VIEW}
            WHERE manufacturer = ?
              AND part_number LIKE ?
            LIMIT 1
        """, [manufacturer, f"%{family}%"]).fetchdf()

        if not rows.empty:
            matched = rows.iloc[0]["part_number"]
            print(f"  [fetch_part] No PPR match for '{part_number}'. "
                  f"Family-only fallback -> '{matched}'")
            return rows.iloc[0].to_dict()

    return None


def find_parts(con: duckdb.DuckDBPyConnection,
               manufacturer: str,
               family: str | None = None,
               part_fragment: str | None = None,
               limit: int = 20) -> "pd.DataFrame":
    """
    Browse available part numbers in Silver.

    Args:
        manufacturer:   e.g. "kubler"
        family:         filter by product_family (exact, case-sensitive)
        part_fragment:  LIKE filter on part_number (no wildcards needed — added automatically)
        limit:          max rows to return

    Returns a DataFrame with part_number, product_family, shaft_type,
    output_circuit_canonical, ip_rating, connection_type_canonical, cpr_values columns.

    Example:
        find_parts(con, "kubler", family="KIS40")
        find_parts(con, "epc", part_fragment="755A")
    """
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
        SELECT part_number,
               product_family,
               shaft_type,
               output_circuit_canonical,
               ip_rating,
               connection_type_canonical,
               connector_pins,
               cpr_values
        FROM {SILVER_VIEW}
        WHERE {where}
        ORDER BY product_family, part_number
        LIMIT {limit}
    """, params).fetchdf()


def fetch_candidates(con: duckdb.DuckDBPyConnection,
                     shaft_type: str,
                     output_voltage_class: str,
                     target_manufacturer: str,
                     src_ip_rating: int | None = None) -> "pd.DataFrame":
    """
    T1 SQL pre-filter: returns candidate rows for Python scoring.

    Hard stops in SQL (benefits from Silver sort order + hive partitioning):
      - manufacturer = target            -> reads single partition file
      - shaft_type exact match           -> row-group pruning (sorted first)
      - output_voltage_class exact match -> row-group pruning (sorted second)

    Soft IP filter (tolerance: candidate ip_rating >= src_ip_rating - 2):
      When src_ip_rating is provided, candidates clearly below the source IP
      are excluded. Tolerance of 2 keeps borderline matches (IP62 for IP64 source)
      while cutting clearly incompatible products.
      Example: KIS40 IP64 -> excludes IP50 and below, keeps IP62/65/67/69K.
      This reduces EPC candidates from ~80K to ~5-15K for typical queries.

    IP is still scored (not hard-stopped) — T2 penalises mismatches correctly.
    """
    conditions = [
        "manufacturer        = ?",
        "shaft_type          = ?",
        "output_voltage_class = ?",
    ]
    params = [target_manufacturer, shaft_type, output_voltage_class]

    ip_floor = None
    if src_ip_rating is not None:
        ip_floor = max(0, int(src_ip_rating) - 2)
        conditions.append("(ip_rating IS NULL OR ip_rating >= ?)")
        params.append(ip_floor)

    where_clause = "\n          AND ".join(conditions)

    t0 = time.time()
    result = con.execute(f"""
        SELECT *
        FROM {SILVER_VIEW}
        WHERE {where_clause}
    """, params).fetchdf()
    elapsed = round(time.time() - t0, 3)
    log.info(
        f"fetch_candidates | mfr={target_manufacturer} "
        f"shaft={shaft_type} voltage={output_voltage_class} "
        f"ip_floor={ip_floor if ip_floor is not None else 'none'} "
        f"-> {len(result):,} rows | {elapsed}s"
    )
    return result


# ── Cached connection singleton (Fargate long-lived process) ─────────────────
import threading as _threading

_cached_con: "duckdb.DuckDBPyConnection | None" = None
_cached_con_lock = _threading.Lock()


def is_connection_warm() -> bool:
    """True if a live cached connection already exists (warm start)."""
    return _cached_con is not None


def get_cached_connection() -> "duckdb.DuckDBPyConnection":
    """
    Thread-safe singleton DuckDB connection.
    First call opens S3/httpfs (cold, ~4s). Subsequent calls return cached (warm, <1s).
    Never closed — persists for the lifetime of the Fargate task.
    On DuckDB error the caller should call reset_cached_connection().
    """
    global _cached_con
    with _cached_con_lock:
        if _cached_con is None:
            log.info("DuckDB: cold start — opening S3 httpfs connection ...")
            _cached_con = get_connection()
            log.info("DuckDB: connection established and cached.")
        return _cached_con


def reset_cached_connection() -> None:
    """Force the next get_cached_connection() call to open a fresh connection."""
    global _cached_con
    with _cached_con_lock:
        _cached_con = None
        log.warning("DuckDB: cached connection reset — next query will cold-start.")


# ── Sanity check (run directly) ───────────────────────────────────────────────

def _sanity_check():
    """Quick validation: connect, count rows per manufacturer, sample one part."""
    print("Connecting to DuckDB (httpfs -> S3) ...")
    con = get_connection()

    print("\nRow counts per manufacturer:")
    counts = con.execute(f"""
        SELECT manufacturer, COUNT(*) AS rows
        FROM {SILVER_VIEW}
        GROUP BY manufacturer
        ORDER BY manufacturer
    """).fetchdf()
    print(counts.to_string(index=False))

    print("\nSilver schema (first 5 columns):")
    schema = con.execute(f"DESCRIBE {SILVER_VIEW}").fetchdf()
    print(schema.head(5).to_string(index=False))

    print("\nSample T1 candidate fetch (solid / universal -> epc):")
    candidates = fetch_candidates(
        con,
        shaft_type           = "solid",
        output_voltage_class = "universal",
        target_manufacturer  = "epc",
    )
    print(f"  {len(candidates):,} candidates returned")
    if not candidates.empty:
        print(f"  Sample part: {candidates.iloc[0]['part_number']}")

    con.close()
    print("\nSanity check passed.")


if __name__ == "__main__":
    _sanity_check()