"""
main.py
=======
FastAPI application for EncoderMatch — encoder cross-reference tool.

Endpoints:
  POST /api/auth/login       — email + password → JWT token + user info
  GET  /api/auth/me          — current user info
  POST /api/match            — run cross-reference match
  GET  /api/parts            — browse available parts in Silver
  GET  /api/history          — user search history
  GET  /api/admin/users      — list users for client admin
  PUT  /api/admin/users/{id} — update user constraints
  GET  /health               — health check (no auth)

Frontend static files served from ./static/ at /

AQB Solutions | May 2026
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import json
import math
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd
import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from auth import (
    authenticate_user, create_token, get_current_user, require_admin, require_superadmin,
    get_user, update_user, delete_user, get_all_users,
    get_all_users_for_client, add_history, get_history,
    increment_search_count, store_session,
    log_error, get_user_errors, add_heartbeat,
    add_feedback, delete_feedback, get_feedback_for_search, get_user_feedback,
    create_manufacturer_tables, _client_slug,
)
from db_load import get_connection, find_parts, download_silver_locally, reload_silver, SILVER_VIEW
from kubler_decoder import validate_decoders as _validate_kubler_decoders
from matcher import load_config, match, dedup_by_family
from serializers import serialize_result, serialize_source
from url_lookup import load_sick_urls, load_posital_urls

# ── Simple cold/warm tracking (first match request = cold, rest = warm) ────
_match_request_count = 0

# ── Cached matcher config (loaded once at startup, reused on every request) ──
_matcher_cfg: dict | None = None
app = FastAPI(
    title="EncoderMatch API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
)

# ── CORS ───────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:8080,http://localhost:3000,http://localhost:8000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Config paths ────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "matcher_config.json"

# ── Startup ────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    print("EncoderMatch API starting up ...")
    load_sick_urls("sick_urls.csv")
    load_posital_urls("posital_urls.csv")

    _validate_kubler_decoders()

    # Pre-load matcher config once — cached in _matcher_cfg for all requests
    global _matcher_cfg
    _matcher_cfg = load_config(CONFIG_PATH)
    print(f"  Matcher config loaded: {len(_matcher_cfg['tier2'])} T2 fields, {len(_matcher_cfg['tier3'])} T3 fields")

    # Download Silver Parquet from S3 → /tmp/silver/ via boto3
    # This avoids DuckDB httpfs network issues on ECS Fargate and makes queries fast
    print("  Downloading Silver from S3 (boto3) ...")
    import asyncio
    loop    = asyncio.get_event_loop()
    success = await loop.run_in_executor(None, download_silver_locally)
    if success:
        print("  Silver cached locally — queries will use local disk.")
    else:
        print("  [WARN] Silver download failed — falling back to S3 httpfs per request.")

    # Discover available manufacturers from Silver — populates VALID_MANUFACTURERS
    # and _available_mfrs so any new Silver partition is automatically recognised.
    global VALID_MANUFACTURERS, _available_mfrs
    try:
        con = get_connection()
        df  = con.execute(
            f"SELECT manufacturer, COUNT(*) AS rows FROM {SILVER_VIEW} "
            f"GROUP BY manufacturer ORDER BY rows DESC"
        ).fetchdf()
        con.close()
        VALID_MANUFACTURERS = set(df["manufacturer"].tolist())
        _available_mfrs = [
            {
                "id":      row["manufacturer"],
                "display": MFR_DISPLAY.get(row["manufacturer"],
                                           row["manufacturer"].replace("_", " ").title()),
                "count":   int(row["rows"]),
            }
            for _, row in df.iterrows()
        ]
        print(f"  Manufacturers in Silver: {sorted(VALID_MANUFACTURERS)}")
    except Exception as _mfr_err:
        print(f"  [WARN] Could not load manufacturer list from Silver: {_mfr_err}")

    print("  Ready.")


# ── Static frontend ────────────────────────────────────────────────────────
# Looks for static files in ./static/ first, then current directory
_base = Path(__file__).parent
STATIC_DIR = _base / "static" if (_base / "static").exists() else _base

app.mount("/assets", StaticFiles(directory=str(STATIC_DIR)), name="assets")

@app.get("/", include_in_schema=False)
async def serve_frontend():
    f = STATIC_DIR / "index.html"
    if not f.exists():
        return JSONResponse({"error": "index.html not found. Copy it to the app folder or static/ subfolder."}, status_code=404)
    return FileResponse(str(f))

@app.get("/EncoderMatch.jsx", include_in_schema=False)
async def serve_jsx():
    f = STATIC_DIR / "EncoderMatch.jsx"
    if not f.exists():
        return JSONResponse({"error": "EncoderMatch.jsx not found."}, status_code=404)
    return FileResponse(str(f))


# ── Health check ────────────────────────────────────────────────────────────
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve encoder wheel as inline SVG favicon — eliminates browser 404 noise."""
    from fastapi.responses import Response
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<circle cx="16" cy="16" r="16" fill="#1855d4"/>'
        '<circle cx="16" cy="16" r="12" fill="none" stroke="white" stroke-width="2"/>'
        '<circle cx="16" cy="16" r="6" fill="none" stroke="white" stroke-width="2"/>'
        '<circle cx="16" cy="16" r="2.5" fill="white"/>'
        '<line x1="16" y1="4" x2="16" y2="10" stroke="white" stroke-width="1.8" stroke-linecap="round"/>'
        '<line x1="16" y1="22" x2="16" y2="28" stroke="white" stroke-width="1.8" stroke-linecap="round"/>'
        '<line x1="4" y1="16" x2="10" y2="16" stroke="white" stroke-width="1.8" stroke-linecap="round"/>'
        '<line x1="22" y1="16" x2="28" y2="16" stroke="white" stroke-width="1.8" stroke-linecap="round"/>'
        '</svg>'
    )
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/health/db")
async def health_db():
    """
    Diagnostic: test DuckDB Silver access and return row counts per manufacturer.
    Visit http://<host>:8000/health/db to check if S3/local data is accessible.
    No auth required.
    """
    import os
    local_exists = os.path.isdir("/tmp/silver") and any(
        f.endswith(".parquet")
        for _, _, files in os.walk("/tmp/silver")
        for f in files
    )
    try:
        con = get_connection()
        df  = con.execute(
            f"SELECT manufacturer, COUNT(*) AS rows FROM {SILVER_VIEW} "
            f"GROUP BY manufacturer ORDER BY manufacturer"
        ).fetchdf()
        con.close()
        return {
            "status":       "ok",
            "mode":         "local" if local_exists else "s3-httpfs",
            "local_silver": local_exists,
            "counts":       df.to_dict(orient="records"),
            "total_rows":   int(df["rows"].sum()),
        }
    except Exception as e:
        import traceback
        return {
            "status":       "error",
            "mode":         "local" if local_exists else "s3-httpfs",
            "local_silver": local_exists,
            "error":        str(e),
            "traceback":    traceback.format_exc(),
        }


# ── Request / Response models ───────────────────────────────────────────────

# ── Manufacturer registry ─────────────────────────────────────────────────
# Display names for known manufacturers. Unknown manufacturers fall back to
# title-case of their Silver partition key (e.g. "baumer" → "Baumer").
MFR_DISPLAY: dict[str, str] = {
    "kubler":        "Kübler",
    "epc":           "EPC",
    "sick":          "Sick",
    "posital":       "Posital",
    "lika":          "Lika",
    "nidec":         "Nidec",
    "baumer":        "Baumer",
    "wachendorff":   "Wachendorff",
    "pepperl_fuchs": "Pepperl+Fuchs",
}

# Populated at startup from Silver — any manufacturer partition discovered there
# is automatically valid. Hardcoded fallback covers cold-start before Silver loads.
VALID_MANUFACTURERS: set[str] = {"kubler", "epc", "sick", "posital", "lika"}

# Ordered list with display names and counts — served by /api/manufacturers
_available_mfrs: list[dict] = []

class LoginRequest(BaseModel):
    email:    str = Field(..., min_length=1, description="User email address")
    password: str = Field(..., min_length=1)


class MatchRequest(BaseModel):
    part_number:    str
    source_mfr:     str
    target_mfrs:    List[str]
    top_n:          int = 10
    custom_weights: Optional[dict] = None   # {"tier2":{field:w,...},"tier3":{field:w,...}}

class UpdateUserRequest(BaseModel):
    searches_limit:  Optional[int]       = None
    allowed_targets: Optional[List[str]] = None
    direction:       Optional[str]       = None
    status:          Optional[str]       = None

class FeedbackRequest(BaseModel):
    search_id:               str
    candidate_part_number:   str
    source_part_number:      str
    is_good_match:           bool


# ── Auth endpoints ──────────────────────────────────────────────────────────

@app.post("/api/auth/login")
async def login(body: LoginRequest):
    user = authenticate_user(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.get("status") == "invited":
        raise HTTPException(status_code=403, detail="Account not yet activated. Check your email.")

    session_id = str(uuid.uuid4())
    store_session(body.email, session_id)
    token = create_token(body.email, session_id)
    return {
        "access_token": token,
        "token_type":   "bearer",
        "user":         _safe_user(user),
    }


@app.get("/api/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return _safe_user(user)


def _safe_user(user: dict) -> dict:
    """Strip sensitive fields. Expose daily search quota (not lifetime counter)."""
    today      = datetime.utcnow().strftime("%Y-%m-%d")
    last_date  = user.get("last_search_date", "")
    used_today = int(user.get("searches_used_today", 0)) if last_date == today else 0
    limit      = int(user.get("searches_limit", 0))
    return {
        "userId":             user.get("userId"),
        "email":              user.get("email"),
        "name":               user.get("name"),
        "role":               user.get("role"),
        "client":             user.get("client"),
        "searches_used":      used_today,
        "searches_limit":     limit,
        "searches_remaining": max(0, limit - used_today),
        "allowed_sources":    user.get("allowed_sources", []),
        "allowed_targets":    user.get("allowed_targets", []),
        "direction":          user.get("direction", "source_only"),
        "status":             user.get("status"),
        "admin_email":        user.get("admin_email"),
        "last_search_date":   last_date,
    }


from decimal import Decimal as _Decimal

def _resolve_weights(cfg: dict, custom_weights: dict | None) -> dict:
    """
    Flatten the effective per-field weights into individual history record fields.
    Falls back to matcher_config.json defaults for any field not overridden.

    Produces fields like:
      w_t2_cpr_values, w_t2_ip_rating, ...,
      w_t3_supply_voltage, w_t3_sensing_method, ...,
      weights_customized (bool)

    Values are stored as Decimal — boto3 DynamoDB resource API rejects Python float.
    Using Decimal(str(v)) avoids binary floating-point precision artifacts.
    """
    cw_t2 = (custom_weights or {}).get("tier2", {})
    cw_t3 = (custom_weights or {}).get("tier3", {})
    out: dict = {"weights_customized": custom_weights is not None}
    for field, fc in cfg["tier2"].items():
        out[f"w_t2_{field}"] = _Decimal(str(round(float(cw_t2.get(field, fc["weight"])), 6)))
    for field, fc in cfg["tier3"].items():
        out[f"w_t3_{field}"] = _Decimal(str(round(float(cw_t3.get(field, fc["weight"])), 6)))
    return out


def _admin_user(user: dict) -> dict:
    """Extended user dict for admin views — includes tracking fields."""
    base = _safe_user(user)
    base.update({
        "created_at":               user.get("created_at", ""),
        "last_login":               user.get("last_login", ""),
        "last_seen":                user.get("last_seen", ""),
        "total_time_spent_minutes": int(user.get("total_time_spent_minutes", 0)),
    })
    return base


# ── Match endpoint ──────────────────────────────────────────────────────────

@app.post("/api/match")
async def run_match(body: MatchRequest, user: dict = Depends(get_current_user)):
    email = user["userId"]

    # ── Access control ────────────────────────────────────────────────────
    is_admin = user.get("role") in ("superadmin", "clientadmin")
    direction = user.get("direction", "source_only")

    # Admins always have access to every manufacturer currently in Silver.
    # Their DynamoDB allowed_sources/allowed_targets are never updated when a
    # new manufacturer is added, so we use VALID_MANUFACTURERS for admins instead.
    if is_admin:
        allowed_sources = list(VALID_MANUFACTURERS)
        allowed_targets = list(VALID_MANUFACTURERS)
    else:
        allowed_sources = user.get("allowed_sources", [])
        allowed_targets = user.get("allowed_targets", [])

    # Validate source
    if body.source_mfr not in allowed_sources:
        raise HTTPException(
            status_code=403,
            detail=f"Source manufacturer '{body.source_mfr}' is not in your allowed sources."
        )

    # Enforce target: validate requested targets against user's allowed pool
    if is_admin:
        effective_targets = body.target_mfrs
        if not effective_targets:
            raise HTTPException(status_code=400, detail="At least one target manufacturer required")
    else:
        # Enduser: requested targets must be within their allowed_targets pool
        if not allowed_targets:
            raise HTTPException(status_code=403, detail="No target manufacturers configured for this account.")
        effective_targets = [t for t in body.target_mfrs if t in allowed_targets]
        if not effective_targets:
            raise HTTPException(status_code=403, detail="Requested target manufacturer is not in your allowed targets.")

    # Guard: never match source against itself (applies to all roles)
    effective_targets = [t for t in effective_targets if t != body.source_mfr]
    if not effective_targets:
        raise HTTPException(status_code=400, detail="Target manufacturer cannot be the same as source.")

    # Cap top_n at 3 for endusers
    effective_top_n = body.top_n if is_admin else min(body.top_n, 3)

    # ── Search limit (atomic, hard stop) ──────────────────────────────────
    updated_user = increment_search_count(email)

    # ── Run matcher for each target ────────────────────────────────────────
    # Use the module-level cached config — loaded once at startup, never reloaded.
    cfg = _matcher_cfg or load_config(CONFIG_PATH)
    global _match_request_count
    _match_request_count += 1
    connection_type = "cold" if _match_request_count == 1 else "warm"
    t_start = time.time()

    all_scored: list[pd.DataFrame]  = []
    src_dict: Optional[dict]        = None
    no_match_reasons: dict[str, dict] = {}   # target_mfr → reason dict

    for target_mfr in effective_targets:
        t_target = time.time()
        try:
            src, scored, reason = match(
                part_number    = body.part_number,
                source_mfr     = body.source_mfr,
                target_mfr     = target_mfr,
                top_n          = effective_top_n * 3,
                config_path    = CONFIG_PATH,
                custom_weights = body.custom_weights,
            )
            if src_dict is None and src:
                src_dict = src
            if not scored.empty:
                all_scored.append(scored)
            elif reason:
                no_match_reasons[target_mfr] = reason
            print(f"  [match] target={target_mfr} -> {len(scored):,} scored | {round(time.time()-t_target,2)}s")
        except ValueError as e:
            # Part not found — propagate clearly
            log_error(email, "/api/match", 404, str(e),
                      {"part": body.part_number, "source": body.source_mfr, "target": target_mfr})
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            # Surface the real error — don't swallow it
            import traceback
            tb = traceback.format_exc()
            print(f"  [match] EXCEPTION for target={target_mfr}: {e}\n{tb}")
            log_error(email, "/api/match", 500, str(e),
                      {"part": body.part_number, "source": body.source_mfr, "target": target_mfr})
            raise HTTPException(
                status_code=500,
                detail=f"Match engine error ({target_mfr}): {str(e)}"
            )

    t_elapsed = round(time.time() - t_start, 2)
    print(f"  [match] TOTAL {t_elapsed}s ({connection_type}) | {len(effective_targets)} target(s) | part={body.part_number} src={body.source_mfr}")

    if not src_dict:
        raise HTTPException(
            status_code=404,
            detail=f"Part '{body.part_number}' not found in '{body.source_mfr}' database."
        )

    # ── Combine + dedup + rank ─────────────────────────────────────────────
    if not all_scored:
        results_json = []
    else:
        combined = pd.concat(all_scored, ignore_index=True)
        combined  = combined.sort_values("total_score", ascending=False)

        # Drop zero-score results — these arise when both source and candidate
        # have no populated scoring fields (e.g. Sick encoder with empty shaft_type
        # matching a Posital Industry Classics row with no usable specs).
        # A total_score of exactly 0 is never a useful recommendation.
        combined = combined[combined["total_score"] > 0]

        if combined.empty:
            results_json = []
        else:
            deduped = dedup_by_family(combined)
            top     = deduped.head(effective_top_n)

            # Source CPR list (for overlap calculation)
            src_cpr_raw = src_dict.get("cpr_values")
            try:
                src_cpr = json.loads(str(src_cpr_raw)) if src_cpr_raw else []
            except Exception:
                src_cpr = []

            results_json = [
                serialize_result(
                    row      = row.to_dict(),
                    src      = src_dict,
                    rank     = rank,
                    src_cpr  = src_cpr,
                    t2_cfg   = cfg["tier2"],
                    t3_cfg   = cfg["tier3"],
                )
                for rank, (_, row) in enumerate(top.iterrows(), 1)
            ]

    # ── Record history ─────────────────────────────────────────────────────
    top_match = results_json[0]["part_number"] if results_json else None
    top_score = results_json[0]["total_score"] if results_json else None
    used       = int(updated_user.get("searches_used_today", 0))
    limit      = int(updated_user.get("searches_limit", 0))
    search_id  = str(uuid.uuid4())   # unique ID for this search — used to link feedback records
    user_slug  = _client_slug(user.get("client", ""), user.get("role", "enduser"))

    try:
        add_history(email, {
            "search_id":     search_id,
            "src_part":      body.part_number,
            "source_mfr":    body.source_mfr,
            "target_mfrs":   effective_targets,
            "top_match":     top_match,
            "top_score":     str(top_score) if top_score else None,
            "search_number": used,
            "result_count":  len(results_json),
            "elapsed_s":     str(t_elapsed),
            **_resolve_weights(cfg, body.custom_weights),
        }, slug=user_slug)
    except Exception as _hist_err:
        print(f"[WARN] add_history failed (slug={user_slug}): {_hist_err}")

    return {
        "search_id":          search_id,
        "source":             serialize_source(src_dict, user_input_code=body.part_number),
        "results":            results_json,
        "result_count":       len(results_json),
        "no_match_reasons":   no_match_reasons,
        "searches_used":      used,
        "searches_limit":     limit,
        "searches_remaining": max(0, limit - used),
        "elapsed_s":          t_elapsed,
        "connection_type":    connection_type,
    }


# ── Part manufacturer auto-detect ───────────────────────────────────────────

# ALL_MANUFACTURERS is now dynamic — use _available_mfrs or VALID_MANUFACTURERS

@app.get("/api/manufacturers")
async def list_manufacturers(user: dict = Depends(get_current_user)):
    """
    Return all manufacturers currently present in Silver, with display names
    and row counts. Populated at startup — automatically includes any new
    manufacturer partition added to Silver without code changes.
    """
    return {"manufacturers": _available_mfrs}


@app.get("/api/parts/detect")
async def detect_part_manufacturer(
    q:    str = Query(..., min_length=1, description="Part number fragment to detect"),
    user: dict = Depends(get_current_user),
):
    """
    Given a part number fragment, return the first allowed source manufacturer
    that contains it. Used by the frontend to auto-switch the source dropdown.
    """
    is_admin = user.get("role") in ("superadmin", "clientadmin")
    if is_admin:
        allowed = list(VALID_MANUFACTURERS)
    else:
        # Search across both allowed_sources and allowed_targets — with bidirectional
        # search, any manufacturer in either pool can be used as the source.
        src      = user.get("allowed_sources", [])
        tgt      = user.get("allowed_targets", [])
        combined = list(dict.fromkeys(src + tgt))   # deduplicated, order preserved
        allowed  = combined or list(VALID_MANUFACTURERS)

    con = get_connection()
    try:
        from db_load import fetch_part
        for mfr in allowed:
            result = fetch_part(con, q, mfr)
            if result:
                return {
                    "manufacturer": mfr,
                    "part_number":  q,
                    "family":       result.get("product_family", ""),
                }
    finally:
        con.close()

    raise HTTPException(
        status_code=404,
        detail=f"Part '{q}' not found in any of your allowed source manufacturers.",
    )


# ── Parts browser ───────────────────────────────────────────────────────────

def _clean_records(df) -> list:
    """Convert DataFrame to JSON-safe records — replaces float nan with None."""
    records = df.to_dict(orient="records")
    return [
        {k: (None if isinstance(v, float) and math.isnan(v) else v)
         for k, v in row.items()}
        for row in records
    ]

@app.get("/api/parts")
async def browse_parts(
    mfr:      str,
    family:   Optional[str] = None,
    fragment: Optional[str] = None,
    limit:    int = 20,
    user: dict = Depends(get_current_user),
):
    allowed = user.get("allowed_sources", []) + user.get("allowed_targets", [])
    if mfr not in allowed:
        raise HTTPException(status_code=403, detail=f"Access to '{mfr}' not permitted")

    con = get_connection()
    try:
        df = find_parts(con, manufacturer=mfr, family=family, part_fragment=fragment, limit=limit)
    finally:
        con.close()

    return {"parts": _clean_records(df), "count": len(df)}


# ── History ─────────────────────────────────────────────────────────────────

@app.get("/api/history")
async def user_history(limit: int = 20, user: dict = Depends(get_current_user)):
    slug    = _client_slug(user.get("client", ""), user.get("role", "enduser"))
    records = get_history(user["userId"], limit=limit, slug=slug)
    for r in records:
        if "top_score" in r and r["top_score"] is not None:
            try:
                r["top_score"] = float(r["top_score"])
            except (TypeError, ValueError):
                r["top_score"] = None
        if "elapsed_s" in r:
            try:
                r["elapsed_s"] = float(r["elapsed_s"])
            except Exception:
                pass
    return {"history": records, "count": len(records)}


# ── AI Explanation endpoint ────────────────────────────────────────────────

class ExplainRequest(BaseModel):
    result: dict
    source: dict

@app.post("/api/explain")
async def explain_match(body: ExplainRequest):
    """
    Generate AI explanation for a match result using Claude API.
    Uses CLAUDE_API_KEY from environment (or config_claude.py as fallback).
    No auth required — explanation is stateless and contains no user data.
    """
    import httpx

    # Resolve API key: env var first, config_claude.py as fallback
    api_key = os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        try:
            from config_claude import CLAUDE_API_KEY
            api_key = CLAUDE_API_KEY
        except ImportError:
            raise HTTPException(status_code=503, detail="Claude API key not configured")

    # Resolve model: env var → config_claude.MODEL → hardcoded default
    model = os.environ.get("CLAUDE_MODEL")
    if not model:
        try:
            from config_claude import MODEL as _CFG_MODEL
            model = _CFG_MODEL
        except (ImportError, AttributeError):
            model = "claude-sonnet-4-6"

    result = body.result
    source = body.source

    src_mfr  = source.get("manufacturer", "Source")
    cand_mfr = result.get("manufacturer_full", "Candidate")

    # Build field lines — T2 first (by weight desc), then T3 (by weight desc)
    T2_ORDER = ["cpr_values","ip_rating","connection_type_canonical",
                "output_circuit_canonical","housing_diameter_mm","shaft_bore_diameter_mm"]
    T3_ORDER = ["supply_voltage","sensing_method","operating_temp_max_c",
                "shock_resistance_ms2","shaft_load_radial_n","vibration_resistance_ms2","connector_pins"]

    t2_data = result.get("t2", {})
    t3_data = result.get("t3", {})
    extra   = result.get("extra", {})

    def field_line(tier, field, f):
        score_pct = round((f.get("score") or 0) * 100, 1) if f.get("score") is not None else "n/a"
        src_native  = f.get("src_native_label") or f.get("label", field)
        cand_native = f.get("cand_native_label") or f.get("label", field)
        return (
            f"[{tier}] {src_mfr} '{src_native}'={f.get('src_val','—')} | "
            f"{cand_mfr} '{cand_native}'={f.get('cand_val','—')} | score={score_pct}%"
        )

    scored_lines = []
    for field in T2_ORDER:
        if field in t2_data:
            scored_lines.append(field_line("T2", field, t2_data[field]))
    for field in T3_ORDER:
        if field in t3_data:
            scored_lines.append(field_line("T3", field, t3_data[field]))

    # Guard: if there is no scored feature data, we cannot generate a meaningful explanation.
    if not scored_lines:
        raise HTTPException(
            status_code=422,
            detail="Not enough scored feature data to generate an AI explanation for this result.",
        )

    extra_lines = []
    for field, f in extra.items():
        src_native  = f.get("src_native_label") or f.get("label", field)
        cand_native = f.get("cand_native_label") or f.get("label", field)
        extra_lines.append(
            f"[INFO] {src_mfr} '{src_native}'={f.get('src_val','—')} | "
            f"{cand_mfr} '{cand_native}'={f.get('cand_val','—')}"
        )

    prompt = f"""You are an industrial encoder cross-reference expert helping a sales engineer evaluate a replacement encoder.

SOURCE: {source.get('part_number')} — {src_mfr} {source.get('family')}
CANDIDATE: {result.get('display_order_code') or result.get('part_number')} — {cand_mfr} {result.get('family')}
OVERALL SCORE: {round((result.get('total_score') or 0)*100, 1)}%

SCORED PARAMETERS (T2 physical weighted 70%, T3 secondary weighted 30%):
{chr(10).join(scored_lines)}

Return ONLY a valid JSON array (no markdown fences, no preamble). Rules:
1. First entry: {{"level":"info","field":"overview","text":"{round((result.get('total_score') or 0)*100,1)}% match — [one sentence verdict covering the key compatibility picture]"}}
2. For each scored parameter with score < 80%: one entry explaining the gap or risk. Skip fields scoring 80% or above entirely.
3. If a field scores 0% or is clearly a blocker, use level "issue". If it scores 1-79%, use level "warning".
4. Each text field: one brief technical sentence, no preamble like "The" or "Note that". Use real units. Use each manufacturer's own field name.
5. Do NOT include any "good", "summary", or "info" entries beyond the overview.
6. Maximum 8 entries total (overview + up to 7 risk/warning entries)."""

    api_error: Optional[HTTPException] = None
    raw_text: Optional[str] = None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 4000,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        data = resp.json()
        if resp.status_code != 200:
            err_msg = data.get("error", {}).get("message", resp.text)
            print(f"[explain] Claude API error {resp.status_code}: {err_msg}")
            api_error = HTTPException(status_code=502, detail=f"Claude API {resp.status_code}: {err_msg}")
        else:
            raw_text = "".join(b.get("text", "") for b in data.get("content", []))
    except Exception as e:
        log_error("anonymous", "/api/explain", 500, f"request failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI explanation request failed: {str(e)}")

    # Raise API-level errors outside the httpx try block so they are not re-caught
    if api_error:
        raise api_error

    try:
        print(f"[explain] raw response ({len(raw_text)} chars): {raw_text[:300]!r}")
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        if not cleaned.startswith("["):
            m = re.search(r'\[[\s\S]*\]', cleaned)
            if not m:
                raise ValueError(f"No JSON array found in response: {cleaned[:200]!r}")
            cleaned = m.group(0)
        blocks = json.loads(cleaned)
        if not isinstance(blocks, list):
            raise ValueError(f"Expected JSON array, got {type(blocks).__name__}")
        return {"blocks": blocks}
    except Exception as e:
        print(f"[explain] parse failed: {e} | raw={raw_text[:500]!r}")
        log_error("anonymous", "/api/explain", 500, f"parse failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI explanation response parse failed: {str(e)}")


class CreateUserRequest(BaseModel):
    name:            str
    email:           str
    password:        str
    searches_limit:  int       = Field(50, ge=0, description="Daily search limit; 0 = locked account")
    allowed_sources: List[str] = []
    allowed_targets: List[str] = []
    direction:       str       = "source_only"
    client:          str       = ""

    @field_validator("client")
    @classmethod
    def client_must_be_valid(cls, v):
        if v and v not in VALID_MANUFACTURERS:
            raise ValueError(f"client must be one of {sorted(VALID_MANUFACTURERS)} or empty")
        return v


# ── Admin endpoints ─────────────────────────────────────────────────────────



@app.post("/api/admin/refresh-silver")
async def refresh_silver(admin: dict = Depends(require_superadmin)):
    """
    Hot-reload Silver data from S3 without ECS redeployment.
    S3 Silver -> /tmp/silver/ (size-checked) -> rebuild .db -> fresh connection.
    Also refreshes VALID_MANUFACTURERS. Superadmin only. Expect ~30s downtime.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        stats = await loop.run_in_executor(None, reload_silver)

        # Refresh VALID_MANUFACTURERS so newly added partitions are visible.
        global VALID_MANUFACTURERS, _available_mfrs
        try:
            con = get_connection()
            df  = con.execute(
                f"SELECT manufacturer, COUNT(*) AS rows FROM {SILVER_VIEW} "
                f"GROUP BY manufacturer ORDER BY rows DESC"
            ).fetchdf()
            con.close()
            VALID_MANUFACTURERS = set(df["manufacturer"].tolist())
            _available_mfrs = [
                {"id": m, "label": MFR_DISPLAY.get(m, m.title()), "rows": int(r)}
                for m, r in zip(df["manufacturer"], df["rows"])
            ]
            print(f"  VALID_MANUFACTURERS refreshed: {VALID_MANUFACTURERS}")
        except Exception as mfr_err:
            print(f"  [WARN] VALID_MANUFACTURERS refresh failed: {mfr_err}")

        stats["manufacturers"] = list(VALID_MANUFACTURERS)
        return stats

    except RuntimeError as exc:
        code = 409 if "in progress" in str(exc) else 500
        raise HTTPException(status_code=code, detail=str(exc))
    except Exception as exc:
        print(f"  [ERROR] /api/admin/refresh-silver failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Reload failed: {exc}")



@app.get("/api/admin/analytics")
async def get_analytics(admin: dict = Depends(require_superadmin)):
    """
    Live analytics: user stats from encodermatch_users + search stats
    aggregated across all encodermatch_history_* tables.
    Superadmin only.
    """
    import asyncio
    from collections import Counter
    from datetime import datetime

    def _fetch():
        import boto3 as _boto3, os
        from auth import get_dynamo
        _region    = os.environ.get("AWS_REGION", "ap-south-1")
        dynamo     = get_dynamo()
        ddb_client = _boto3.client("dynamodb", region_name=_region)

        # ── User stats ────────────────────────────────────────────────────────
        users = dynamo.Table("encodermatch_users").scan()["Items"]
        from datetime import date as _date
        today = _date.today().isoformat()
        total = len(users)
        locked = 0
        for u in users:
            status    = u.get("status", "active")
            last_date = u.get("last_search_date", "")
            # Daily reset: searches_used_today only counts if last search was today
            used  = int(u.get("searches_used_today", 0) or 0) if last_date == today else 0
            limit = int(u.get("searches_limit", 99999) or 99999)
            if status == "locked" or used >= limit:
                locked += 1
        active = total - locked

        # ── History tables (all encodermatch_history_* tables) ────────────────
        all_tables  = ddb_client.list_tables()["TableNames"]
        hist_tables = [t for t in all_tables if t.startswith("encodermatch_history_")]

        month_start = datetime.utcnow().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        from boto3.dynamodb.conditions import Attr
        all_searches = []
        for tname in hist_tables:
            resp = dynamo.Table(tname).scan(
                FilterExpression=Attr("timestamp").gte(month_start)
            )
            all_searches.extend(resp.get("Items", []))

        total_searches = len(all_searches)

        # Top parts (by frequency)
        part_counts = Counter(
            s["src_part"] for s in all_searches if s.get("src_part")
        )
        top_parts = [
            {"part": p, "count": c}
            for p, c in part_counts.most_common(5)
        ]

        # Search flows (source_mfr → target_mfr pairs)
        flow_counts = Counter()
        for s in all_searches:
            src     = s.get("source_mfr", "")
            targets = s.get("target_mfrs", [])
            if src and targets:
                for t in targets:
                    flow_counts[(src, t)] += 1
        flow_total = sum(flow_counts.values()) or 1
        flows = [
            {"src": src, "tgt": tgt, "count": cnt,
             "pct": round(cnt / flow_total * 100)}
            for (src, tgt), cnt in flow_counts.most_common(6)
        ]

        # Avg top score
        scores = []
        for s in all_searches:
            try: scores.append(float(s["top_score"]))
            except Exception: pass
        avg_score = round(sum(scores) / len(scores) * 100, 1) if scores else 0.0

        # Most used target
        tgt_counts = Counter()
        for s in all_searches:
            for t in s.get("target_mfrs", []):
                tgt_counts[t] += 1
        top_tgt, top_tgt_count = tgt_counts.most_common(1)[0] if tgt_counts else ("—", 0)

        return {
            "users":    {"total": total, "active": active, "locked": locked},
            "searches": {
                "this_month":      total_searches,
                "avg_top_score":   avg_score,
                "top_target":      top_tgt,
                "top_target_count": top_tgt_count,
            },
            "top_parts": top_parts,
            "flows":     flows,
        }

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch)
    except Exception as exc:
        print(f"  [ERROR] /api/admin/analytics failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/admin/users")
async def create_user(
    body:  CreateUserRequest,
    admin: dict = Depends(require_admin),
):
    """Create a new end user. Admin only. Password set immediately — no invite flow."""
    from auth import hash_password, get_user
    from datetime import datetime as _dt

    if get_user(body.email):
        raise HTTPException(status_code=409, detail=f"User '{body.email}' already exists.")

    client = body.client or admin.get("client", "")

    new_user = {
        "userId":                   body.email,
        "email":                    body.email,
        "name":                     body.name,
        "password_hash":            hash_password(body.password),
        "role":                     "enduser",
        "client":                   client,
        "searches_used_today":      0,
        "last_search_date":         "",
        "searches_limit":           body.searches_limit,
        "allowed_sources":          body.allowed_sources,
        "allowed_targets":          body.allowed_targets,
        "direction":                body.direction,
        "status":                   "active",
        "admin_email":              admin.get("userId", ""),
        "created_at":               _dt.utcnow().isoformat(),
        "last_login":               "",
        "last_seen":                "",
        "total_time_spent_minutes": 0,
    }

    from auth import get_dynamo, USERS_TABLE
    get_dynamo().Table(USERS_TABLE).put_item(Item=new_user)

    # Provision per-manufacturer tables for this user's client asynchronously.
    # Runs in a background thread so user creation returns immediately.
    import threading as _threading
    _threading.Thread(
        target=create_manufacturer_tables,
        args=(client, "enduser"),
        daemon=True,
    ).start()

    return {"status": "created", "userId": body.email, "client": client}

@app.get("/api/admin/users")
async def list_users(admin: dict = Depends(require_admin)):
    from auth import get_all_users
    # Superadmin sees all users; clientadmin sees their client only
    if admin.get("role") == "superadmin":
        users = get_all_users()
    else:
        users = get_all_users_for_client(admin["client"])
    return {"users": [_admin_user(u) for u in users], "count": len(users)}


@app.delete("/api/admin/users/{user_id}")
async def delete_user_endpoint(
    user_id: str,
    admin: dict = Depends(require_admin),
):
    """Delete a user. Admin only. Cannot delete yourself."""
    from auth import delete_user, get_user as _get_user
    if user_id == admin.get("userId"):
        raise HTTPException(status_code=400, detail="Cannot delete your own account.")
    if not _get_user(user_id):
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")
    delete_user(user_id)
    return {"status": "deleted", "userId": user_id}


@app.put("/api/admin/users/{user_id}")
async def update_user_constraints(
    user_id: str,
    body: UpdateUserRequest,
    admin: dict = Depends(require_admin),
):
    target = user_id  # email is the userId
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    update_user(target, updates)
    return {"status": "updated", "userId": target, "updates": updates}


# ── Heartbeat — time tracking ────────────────────────────────────────────────

@app.post("/api/auth/heartbeat")
async def heartbeat(user: dict = Depends(get_current_user)):
    """
    Called every 5 minutes by the frontend while the tab is active.
    Atomically increments total_time_spent_minutes in the user record.
    """
    add_heartbeat(user["userId"], minutes=5)
    return {"ok": True}


# ── Admin per-user analytics endpoints ──────────────────────────────────────

@app.get("/api/admin/users/{email}/history")
async def get_user_history_admin(
    email: str,
    limit: int = 50,
    admin: dict = Depends(require_admin),
):
    """Return search history for any user. Admin only."""
    target = get_user(email)
    if not target:
        raise HTTPException(status_code=404, detail=f"User '{email}' not found")
    slug    = _client_slug(target.get("client", ""), target.get("role", "enduser"))
    records = get_history(email, limit=limit, slug=slug)
    for r in records:
        for field in ("top_score", "elapsed_s"):
            if field in r and r[field] is not None:
                try:
                    r[field] = float(r[field])
                except (TypeError, ValueError):
                    r[field] = None
    return {"history": records, "count": len(records), "email": email}


@app.get("/api/admin/users/{email}/errors")
async def get_user_errors_admin(
    email: str,
    limit: int = 50,
    admin: dict = Depends(require_admin),
):
    """Return error log for any user. Admin only."""
    records = get_user_errors(email, limit=limit)
    return {"errors": records, "count": len(records), "email": email}


# ── Feedback endpoints (thumbs up / down on result cards) ────────────────────

@app.post("/api/feedback")
async def submit_feedback(
    body: FeedbackRequest,
    user: dict = Depends(get_current_user),
):
    slug = _client_slug(user.get("client", ""), user.get("role", "enduser"))
    add_feedback(
        email         = user["userId"],
        search_id     = body.search_id,
        candidate_pn  = body.candidate_part_number,
        source_pn     = body.source_part_number,
        is_good_match = body.is_good_match,
        slug          = slug,
    )
    return {"status": "ok"}


@app.delete("/api/feedback")
async def remove_feedback(
    search_id:    str,
    candidate_pn: str,
    user: dict = Depends(get_current_user),
):
    slug = _client_slug(user.get("client", ""), user.get("role", "enduser"))
    delete_feedback(user["userId"], search_id, candidate_pn, slug=slug)
    return {"status": "ok"}


@app.get("/api/feedback/{search_id}")
async def get_search_feedback(
    search_id: str,
    user: dict = Depends(get_current_user),
):
    slug    = _client_slug(user.get("client", ""), user.get("role", "enduser"))
    records = get_feedback_for_search(user["userId"], search_id, slug=slug)
    return {"feedback": records}


@app.get("/api/admin/users/{email}/feedback")
async def get_user_feedback_admin(
    email: str,
    limit: int = 50,
    admin: dict = Depends(require_admin),
):
    """Return feedback records for any user. Admin only."""
    target  = get_user(email)
    if not target:
        raise HTTPException(status_code=404, detail=f"User '{email}' not found")
    slug    = _client_slug(target.get("client", ""), target.get("role", "enduser"))
    records = get_user_feedback(email, limit=limit, slug=slug)
    return {"feedback": records, "count": len(records), "email": email}


# ── Run directly ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)