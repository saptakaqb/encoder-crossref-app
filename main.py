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

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth import (
    authenticate_user, create_token, get_current_user,
    increment_search_count, add_history, get_history,
    get_all_users_for_client, require_admin, update_user,
    store_session,
)
from db_load import get_connection, find_parts, download_silver_locally, SILVER_VIEW
from matcher import load_config, match, dedup_by_family
from serializers import serialize_result, serialize_source
from url_lookup import load_sick_urls, load_posital_urls

# ── Simple cold/warm tracking (first match request = cold, rest = warm) ────
_match_request_count = 0
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

    # Pre-load matcher config to catch any config errors at startup
    cfg = load_config(CONFIG_PATH)
    print(f"  Matcher config loaded: {len(cfg['tier2'])} T2 fields, {len(cfg['tier3'])} T3 fields")

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

class LoginRequest(BaseModel):
    email:    str
    password: str

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
        "searches_used":      used_today,        # today's count (frontend unchanged)
        "searches_limit":     limit,             # now = daily limit
        "searches_remaining": max(0, limit - used_today),
        "allowed_sources":    user.get("allowed_sources", []),
        "allowed_targets":    user.get("allowed_targets", []),
        "direction":          user.get("direction", "source_only"),
        "status":             user.get("status"),
        "admin_email":        user.get("admin_email"),
        "last_search_date":   last_date,
    }


# ── Match endpoint ──────────────────────────────────────────────────────────

@app.post("/api/match")
async def run_match(body: MatchRequest, user: dict = Depends(get_current_user)):
    email = user["userId"]

    # ── Access control ────────────────────────────────────────────────────
    allowed_sources = user.get("allowed_sources", [])
    allowed_targets = user.get("allowed_targets", [])
    direction       = user.get("direction", "source_only")

    is_admin = user.get("role") in ("superadmin", "clientadmin")

    # Validate source
    if body.source_mfr not in allowed_sources:
        raise HTTPException(
            status_code=403,
            detail=f"Source manufacturer '{body.source_mfr}' is not in your allowed sources."
        )

    # Enforce target: endusers always search against their own client manufacturer
    if is_admin:
        effective_targets = body.target_mfrs
        if not effective_targets:
            raise HTTPException(status_code=400, detail="At least one target manufacturer required")
        invalid_targets = [t for t in effective_targets if t not in allowed_targets]
        if invalid_targets:
            raise HTTPException(status_code=403, detail=f"Not authorised to search against: {invalid_targets}")
        # Guard: never match source against itself
        effective_targets = [t for t in effective_targets if t != body.source_mfr]
        if not effective_targets:
            raise HTTPException(status_code=400, detail="Target manufacturer cannot be the same as source.")
    else:
        # Enduser: target is always locked to their client manufacturer
        client_mfr = user.get("client", "").lower()
        if not client_mfr:
            raise HTTPException(status_code=403, detail="User has no client manufacturer configured.")
        effective_targets = [client_mfr]

    # Cap top_n at 3 for endusers
    effective_top_n = body.top_n if is_admin else min(body.top_n, 3)

    # ── Search limit (atomic, hard stop) ──────────────────────────────────
    updated_user = increment_search_count(email)

    # ── Run matcher for each target ────────────────────────────────────────
    cfg = load_config(CONFIG_PATH)
    global _match_request_count
    _match_request_count += 1
    connection_type = "cold" if _match_request_count == 1 else "warm"
    t_start = time.time()

    all_scored: list[pd.DataFrame] = []
    src_dict: Optional[dict]       = None

    for target_mfr in effective_targets:
        t_target = time.time()
        try:
            src, scored = match(
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
            print(f"  [match] target={target_mfr} → {len(scored):,} scored | {round(time.time()-t_target,2)}s")
        except ValueError as e:
            # Part not found — propagate clearly
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            # Surface the real error — don't swallow it
            import traceback
            tb = traceback.format_exc()
            print(f"  [match] EXCEPTION for target={target_mfr}: {e}\n{tb}")
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
        deduped   = dedup_by_family(combined)
        top       = deduped.head(effective_top_n)

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

    add_history(email, {
        "src_part":      body.part_number,
        "source_mfr":    body.source_mfr,
        "target_mfrs":   effective_targets,
        "top_match":     top_match,
        "top_score":     str(top_score) if top_score else None,
        "search_number": used,
        "result_count":  len(results_json),
        "elapsed_s":     str(t_elapsed),
    })

    return {
        "source":             serialize_source(src_dict),
        "results":            results_json,
        "result_count":       len(results_json),
        "searches_used":      used,
        "searches_limit":     limit,
        "searches_remaining": max(0, limit - used),
        "elapsed_s":          t_elapsed,
        "connection_type":    connection_type,
    }


# ── Part manufacturer auto-detect ───────────────────────────────────────────

ALL_MANUFACTURERS = ["kubler", "epc", "sick", "posital"]

@app.get("/api/parts/detect")
async def detect_part_manufacturer(
    q:    str,
    user: dict = Depends(get_current_user),
):
    """
    Given a part number fragment, return the first allowed source manufacturer
    that contains it. Used by the frontend to auto-switch the source dropdown.
    """
    allowed = user.get("allowed_sources", []) or ALL_MANUFACTURERS

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

    return {"parts": df.to_dict(orient="records"), "count": len(df)}


# ── History ─────────────────────────────────────────────────────────────────

@app.get("/api/history")
async def user_history(limit: int = 20, user: dict = Depends(get_current_user)):
    records = get_history(user["userId"], limit=limit)
    # Convert top_score back to float for frontend
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
CANDIDATE: {result.get('part_number')} — {cand_mfr} {result.get('family')}
OVERALL SCORE: {round((result.get('total_score') or 0)*100, 1)}% | T2 Physical: {round((result.get('t2_score') or 0)*100, 1)}% | T3 Secondary: {round((result.get('t3_score') or 0)*100, 1)}%

SCORED PARAMETERS (T2 physical weighted 70%, T3 secondary weighted 30% — listed in decreasing importance):
{chr(10).join(scored_lines)}

ADDITIONAL SPECIFICATIONS (unscored — for completeness):
{chr(10).join(extra_lines)}

Return ONLY a valid JSON array (no markdown fences). Each element:
{{"level":"good"|"warning"|"issue"|"info", "field":"field name or overview", "text":"1-3 plain-English sentences"}}

Structure your response:
1. First entry: level "info", field "overview" — 2-3 sentences: overall suitability and key headline differences
2. Then one entry per SCORED field (T2 first, T3 second) in the order listed above, covering EVERY scored field:
   - "good" (85-100%): briefly confirm compatibility, note if any practical consideration
   - "warning" (60-84%): explain the difference and what the engineer must check
   - "issue" (<60%): explain the mismatch clearly and state whether it's a blocker or can be accommodated
3. Then a "summary" entry: level "info", field "summary" — 2 sentences on overall recommendation and any installation notes

Use each manufacturer's own field name (as given above) when referring to parameters. Be concise and technical. Use real units."""

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
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        data = resp.json()
        if resp.status_code != 200:
            err_msg = data.get("error", {}).get("message", resp.text)
            print(f"[explain] Claude API error {resp.status_code}: {err_msg}")
            raise HTTPException(status_code=502, detail=f"Claude API {resp.status_code}: {err_msg}")
        raw = "".join(b.get("text", "") for b in data.get("content", []))
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        blocks = json.loads(cleaned)
        return {"blocks": blocks if isinstance(blocks, list) else []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI explanation failed: {str(e)}")


class CreateUserRequest(BaseModel):
    name:            str
    email:           str
    password:        str
    searches_limit:  int       = 50
    allowed_sources: List[str] = []
    allowed_targets: List[str] = []
    direction:       str       = "source_only"
    client:          str       = ""


# ── Admin endpoints ─────────────────────────────────────────────────────────

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
        "userId":              body.email,
        "email":               body.email,
        "name":                body.name,
        "password_hash":       hash_password(body.password),
        "role":                "enduser",
        "client":              client,
        "searches_used_today": 0,
        "last_search_date":    "",
        "searches_limit":      body.searches_limit,
        "allowed_sources":     body.allowed_sources,
        "allowed_targets":     body.allowed_targets,
        "direction":           body.direction,
        "status":              "active",
        "admin_email":         admin.get("userId", ""),
        "created_at":          _dt.utcnow().isoformat(),
    }

    from auth import get_dynamo, USERS_TABLE
    get_dynamo().Table(USERS_TABLE).put_item(Item=new_user)

    return {"status": "created", "userId": body.email, "client": client}

@app.get("/api/admin/users")
async def list_users(admin: dict = Depends(require_admin)):
    from auth import get_all_users
    # Superadmin sees all users; clientadmin sees their client only
    if admin.get("role") == "superadmin":
        users = get_all_users()
    else:
        users = get_all_users_for_client(admin["client"])
    return {"users": [_safe_user(u) for u in users], "count": len(users)}


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


# ── Run directly ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)