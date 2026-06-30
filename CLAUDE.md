# EncoderMatch — Claude Code Context
**Company:** AQB Solutions Private Ltd. | **Version:** v2.4.2 | **Updated:** June 30, 2026
**Deploy status:** Kübler service deployed June 29, 2026 — task def rev 8, IP `13.206.97.104`. ECR tag: `kubler-v2.4.2-2026-06-29`. Posital service at desired count 0 (intentional). **1 local change pending next deploy:** `static/EncoderMatch.jsx` (lifetime search count cards on UserDetailPage).

---

## 1. What This Project Is

AI-powered industrial encoder cross-reference platform. Input: source encoder part number (EPC, Sick, Posital, Lika, Baumer, Kübler). Output: ranked Kübler replacement candidates scored across 13 parameters via T1 hard stops → T2 physical match (70%) → T3 secondary specs (30%). Each result card shows: match score (0–100%), field-by-field breakdown, product URL, AI explanation (Claude Haiku). Users are sales engineers replacing industrial encoders without manually comparing datasheets.

**Active clients:** Posital (service `encodermatch-service`, desired count 0) | Kübler (live, service `encodermatch-kubler-service`, IP `13.206.97.104`, task def rev 8)

---

## 2. AWS Infrastructure (all ap-south-1 / Mumbai)

**ECS:** cluster `encoder-app-cluster`, Fargate, 2vCPU/8GB, port 8000, health check `GET /health` start-period 120s. Posital service: `encodermatch-service` (desired count 0). Kübler service: `encodermatch-kubler-service` (live, IP `13.206.97.104`). Task def: `encodermatch-app` rev 8 (registered Jun 29 — corrects image URI from `encoder-crossref-app` → `encodermatch-app`; rev 7 had wrong ECR repo name). Secrets Manager `valueFrom` for `CLAUDE_API_KEY` + `JWT_SECRET_KEY` since rev 7. No Elastic IP — IPs are dynamic. Use `python refresh_silver_ecs.py --dry-run` to discover current IP.

**ECR:** `155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app` — tagging: `latest` + `kubler-test-YYYY-MM-DD`. Old name `encoder-crossref-app` was wrong — all 7 references corrected June 22.

**S3:** bucket `aqb-data-analytics-demo`, prefix `encoder_pipeline/`. Silver Parquet (Snappy, hive-partitioned): `silver/manufacturer=X/data.parquet`. Counts: baumer 422, epc 1,520,586, kubler 102,748, lika 7,299, posital 18,742, sick 9,240 — total ~1.65M rows, ~10.3MB. Bronze2 CSVs in `bronze2/`: kubler 1.7MB uncompressed, epc 14.3MB gzip, posital 25.1MB uncompressed (gzip pending), lika gzip, sick not stored (scraped directly to Silver).

**DynamoDB (on-demand):** Global: `encodermatch_users` (PK: userId=email), `encodermatch_errors` (PK: userId, SK: timestamp). Per-client: `encodermatch_history_{slug}` (PK: userId, SK: timestamp), `encodermatch_feedback_{slug}` (PK: userId, SK: `{search_id}#{candidate_pn}`). Slugs: superadmin→`aqb_solutions`, Kübler→`kubler`, Posital→`posital`. Formula: `re.sub(r"[^a-z0-9]","_", client.lower().strip())`. Provisioned: users, errors, history/feedback for admin, aqb_solutions, posital. Kübler tables auto-created on first Kübler user login via `create_manufacturer_tables()` background thread. !! NEVER re-run `dynamo_setup.py` on live — `seed_users()` overwrites admin records unconditionally.

**EC2:** `encoder-crossref`, t3.small (upgrade to t3.medium pending — OOMs on Playwright). SSH key: `C:\Users\sadhy\Downloads\encoder-crossref-key.pem`. Purpose: Bronze1 PDF extraction, Bronze2 CSV production, scraping.

**Env vars (ECS task def rev 8):** `AWS_REGION=ap-south-1`, `DYNAMO_USERS_TABLE=encodermatch_users`, `S3_BUCKET=aqb-data-analytics-demo`, `S3_ROOT=encoder_pipeline`, `CORS_ORIGINS`. **Secrets (valueFrom):** `CLAUDE_API_KEY` → `arn:aws:secretsmanager:ap-south-1:155930759570:secret:encoder-crossref/anthropic-api-key-wiWEcO` (updated Jun 29 — was JSON-wrapped, now plain string) | `JWT_SECRET_KEY` → `arn:aws:secretsmanager:ap-south-1:155930759570:secret:encoder-crossref/jwt-secret-key-BrWF5C`. Local fallback: `config_claude.py` (gitignored) holds `CLAUDE_API_KEY` and `MODEL = "claude-haiku-4-5-20251001"`.

---

## 3. Key Files

| File | Size | Purpose |
|---|---|---|
| `main.py` | 60KB | All FastAPI endpoints + orchestration |
| `auth.py` | 22KB | JWT, DynamoDB user/session/history/feedback ops |
| `matcher.py` | 56KB | T1/T2/T3 scoring engine (fully config-driven) |
| `matcher_config.json` | 9KB | All scoring weights, T1 rules, compat matrices — edit here, no code change needed |
| `db_load.py` | 46KB | DuckDB 3-tier connection, Silver S3 download, fetch_part/candidates |
| `serializers.py` | 70KB | Result card + source card JSON, Kübler display order codes (31 families) |
| `kubler_decoder.py` | 126KB | Decodes Kübler real order codes (31 families, Path A + B) |
| `epc_decoder.py` | 43KB | Decodes EPC real order codes (28 entries, 25 families) |
| `url_lookup.py` | 8KB | Product URL resolution per manufacturer |
| `static/EncoderMatch.jsx` | 310KB | Entire React frontend — single file, no build step |
| `static/logo2.png` | 31KB | AQB logo — PNG not webp (Dockerfile COPY fixed Jun 22 — was BLOCKING) |
| `dynamo_setup.py` | 7KB | ONE-TIME ONLY — creates DynamoDB tables + seeds superadmin accounts |
| `refresh_silver_ecs.py` | 4KB | Hot-reload Silver on ECS without redeploy (auto-discovers task IP). WARNING: has hardcoded EMAIL + PASSWORD — move to env var |
| `kubler_handover_tests.py` | — | Post-deploy end-to-end test suite (self-contained, fill in 3 values) |

---

## 4. Deploy Status — ✅ Deployed June 29, 2026

Kübler service deployed June 29 via task def rev 8 (`encodermatch-app:latest` — correct ECR repo). Handover tests passed (31/31 searches, 9/9 security guards). ECR tag: `kubler-v2.4.2-2026-06-29`. Task IP: `13.206.97.104`.

**Note:** Task def rev 7 (registered Jun 24) had wrong ECR image URI `encoder-crossref-app:latest`. Rev 8 corrects this to `encodermatch-app:latest`. Always use rev 8+ for future deploys.

| File | Change | Status |
|---|---|---|
| `Dockerfile` | `logo2.webp` → `logo2.png` | ✅ Live |
| `main.py` | I-9 role guard, I-10/11 cross-client guards, I-12 user_creation_limit, I-22 zero-score backfill | ✅ Live |
| `auth.py` | I-14 last-client warning, `_client_slug` routing fix | ✅ Live |
| `static/EncoderMatch.jsx` | Jun 22 cosmetic fixes + Jun 18 changes | ✅ Live |
| `matcher.py` | `_t1_exact_match_except_cable()`, T1_RULE_REGISTRY, cable T2 weight redistribution | ✅ Live |
| `matcher_config.json` | connection_type T1 rule: `exact_match_except_cable` | ✅ Live |
| `static/index.html` | Favicon cache-bust | ✅ Live |
| `dynamo_setup.py` | "DO NOT RE-RUN" safety warning | ✅ Live |
| `serializers.py` | Kübler display order codes, 31 families | ✅ Live |
| `url_lookup.py` | Kübler URL slug fixes | ✅ Live |
| `CHANGELOG.md` | v2.4.1 entry | ✅ Live |

**v2.4.2 additions (deployed June 29, same task def rev 8, ECR tag `kubler-v2.4.2-2026-06-29`):**

| File | Change | Status |
|---|---|---|
| `db_load.py` | Posital partial matching (Stage 2d LIKE search), `POSITAL_FAMILY_PREFIXES`, `mfr_hint` for Posital codes | ✅ Live |
| `matcher.py` | Connection type scoring fix: M23↔M23 = 1.0, removed NaN redistribution for specific connectors | ✅ Live |
| `serializers.py` | 4 new Kübler families: A02H (flange_type mode), H120 (fixed flange), Sendix 7100, Sendix 7120 | ✅ Live |
| `static/EncoderMatch.jsx` | Copy button HTTP fallback (`execCommand`), prefill toast timer decoupled from replayParams | ✅ Live |

**Local-only changes (June 30 — pending next deploy, next version v2.4.3):**

| File | Change | Status |
|---|---|---|
| `static/EncoderMatch.jsx` | Lifetime search count cards on UserDetailPage: SA viewing CA → 3 cards (Grand Total, CA Searches, User Searches) at top of Overview; viewing enduser → 1 card (Total Searches). Fetches history with `limit=9999` for accurate lifetime counts. | 🔧 Local only |

---

## 5. Deploy Procedure (Windows PowerShell)

```powershell
# ECR login
aws ecr get-login-password --region ap-south-1 | `
  docker login --username AWS --password-stdin `
  155930759570.dkr.ecr.ap-south-1.amazonaws.com

# Build + tag + push
docker build -t encodermatch-app . --no-cache
$TAG = "kubler-v2.4.2-2026-06-29"  # update date/version each deploy
docker tag encodermatch-app:latest 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app:latest
docker tag encodermatch-app:latest 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app:$TAG
docker push 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app:latest
docker push 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app:$TAG

# Deploy Posital (currently at desired count 0 — increment when ready)
aws ecs update-service --cluster encoder-app-cluster --service encodermatch-service --task-definition encodermatch-app:8 --desired-count 1 --force-new-deployment --region ap-south-1

# Deploy Kübler (service EXISTS — use update-service, not create-service)
aws ecs update-service --cluster encoder-app-cluster --service encodermatch-kubler-service `
  --task-definition encodermatch-app:8 --force-new-deployment --region ap-south-1
# Network config: subnet-0e9d3cc8ad3405cf1 | sg-07e286c96523529e5 | assignPublicIp=ENABLED

# Get task IP (wait 90s after deploy for Silver download + DB build)
python refresh_silver_ecs.py --dry-run

# Health check
curl http://<ECS_IP>:8000/health/db
# Expected: {"status":"ok", all 6 manufacturers, total_rows ~1.65M}

# Run handover tests
python kubler_handover_tests.py
```

**Local dev:**
```powershell
cd C:\Users\sadhy\ai_cross_reference\incremental\encoder_appv2
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# Kill stuck uvicorn:
taskkill /IM python.exe /F
Remove-Item "C:\tmp\silver\encoders.db" -ErrorAction SilentlyContinue
```

---

## 6. Superadmin Credentials (from dynamo_setup.py)

| Email | Password |
|---|---|
| `akshay.b@aqbsolutions.com` | `akshay@admin9999` |
| `saptak.s@aqbsolutions.com` | `saptak@admin1111` |

---

## 7. Three-Tier Role System & Auth

**Roles:** superadmin (blue `#2563eb`) → clientadmin (purple `#7c3aed`) → enduser (teal `#0891b2`, child of CA) / enduser (emerald `#059669`, direct SA-created).

**Security guards (I-9 to I-12, enforced at API since Jun 22):**
- Clientadmin can ONLY create `enduser` → 403 otherwise
- Clientadmin cannot delete superadmin or other clientadmins → 403
- Clientadmin cannot delete/update cross-client users → 403
- `user_creation_limit` enforced at API: count `created_by == caller.userId` before write
- Clientadmin cannot PUT `searches_limit`, `allowed_results`, `user_creation_limit` → 403 (superadmin-only fields)
- Superadmin cannot delete clientadmin with active child users → 409

**Full permission matrix:**
| Operation | superadmin | clientadmin | enduser |
|---|---|---|---|
| Create clientadmin | ✅ | ❌ 403 | ❌ 403 |
| Create enduser | ✅ | ✅ within limit | ❌ 403 |
| Delete superadmin | ✅ | ❌ 403 | ❌ 403 |
| Delete own-client enduser | ✅ | ✅ | ❌ 403 |
| Delete cross-client user | ✅ | ❌ 403 | ❌ 403 |
| Delete CA with children | ❌ 409 | ❌ | ❌ |
| Delete self | ❌ 400 | ❌ 400 | ❌ 400 |
| Update user | ✅ any | ✅ own-client endusers only | ❌ |

**Auth details:**
- Password: SHA-256 with salt `"encodermatch_2026"` → `hashlib.sha256(f"encodermatch_2026{password}".encode()).hexdigest()`
- JWT: HS256, 24h expiry, claims: `sub`=email, `sid`=session_id
- Single-session: login writes UUID to `active_session_id` in DynamoDB; every request validates token `sid` matches DB value → mismatch = 401 "Session superseded"
- Search limit: atomic DynamoDB `ADD searches_used_today :one` with `ConditionExpression searches_used_today < :limit` → `ConditionalCheckFailedException` = 429. Day rollover: SET to 1 + stamp `last_search_date`. `status=locked` users can login but 429 on first search (by design — locked check is in `increment_search_count`, not login). `status=invited` blocked at login (403).
- Heartbeat: `POST /api/auth/heartbeat` every 5min (tab-visible only) → atomic `ADD total_time_spent_minutes :5`

---

## 8. Match Flow (POST /api/match)

```
MatchRequest: {part_number, source_mfr, target_mfrs, top_n, custom_weights}

1. Access control:
   superadmin → VALID_MANUFACTURERS (all)
   others → allowed_sources / allowed_targets from user record
   Guard: source_mfr in allowed_sources (403)
   Guard: effective_targets ∩ allowed_targets (403 if empty)
   Guard: target ≠ source (400)
   Cap: effective_top_n = min(body.top_n, user.allowed_results)

2. increment_search_count(email) → 429 if at limit or locked

3. For each target_mfr (sequential, not async):
     match(part_number, source_mfr, target_mfr, top_n*3, custom_weights)
       → fetch_part()        returns source dict (with CPR override)
       → fetch_candidates()  SQL pre-filter + POSITAL_EXITING_PARTS filter
       → apply_t1_python_rules()  5 T1 checks, returns filtered DataFrame
       → score_candidates()  vectorized T2/T3 numpy scoring
     Track targets_with_scored (before zero-score drop)
     Accumulate all_scored DataFrames, no_match_reasons dict

4. Combine → sort by total_score DESC → drop rows where total_score == 0

5. dedup_by_family() → one row per product_family (best score)
   head(effective_top_n)

6. serialize_result() × N → results_json

7. I-22 backfill: for targets in targets_with_scored but absent from results_json
   AND absent from no_match_reasons → inject "zero_score" reason

8. add_history() → DynamoDB (try/except → [WARN] log, never kills search)

9. Return: {search_id, source, results, result_count, no_match_reasons,
            searches_used, searches_limit, searches_remaining, elapsed_s, connection_type}
```

`_match_request_count` module-level: first call = "cold", rest = "warm" (reported in response). `custom_weights` stored in history as `w_t2_{field}`, `w_t3_{field}` Decimal fields via `_resolve_weights()`.

---

## 9. Scoring Engine (matcher.py + matcher_config.json)

### T1 Hard Stops — any failure = candidate excluded entirely
All 5 implemented as named functions in `T1_RULE_REGISTRY`. Config-driven via `tier1_hard_stops` in matcher_config.json.

| # | Field | Rule | Condition |
|---|---|---|---|
| 1 | `shaft_type` | `exact_match` | Skipped if either side empty/unknown |
| 2 | `shaft_bore_diameter_mm` | `within_tolerance_pct` 10% | `hollow_only` — skipped for solid |
| 3 | `output_voltage_class` | `forbidden_pairs` `[[low,high],[high,low]]` | Always applied |
| 4 | `housing_diameter_mm` | `within_tolerance_pct` 10% | `solid_only` — skipped for hollow/null |
| 5 | `connection_type_canonical` | `exact_match_except_cable` | Cable on either side → T1 skipped, falls to T2 |

**Connection type dual role (v2.4.2):** Both sides specific connector (M12, M23, MS/MIL, etc.) → T1 enforces exact match. T2 scores via `conn_compat_matrix` (M23↔M23=1.0, M12↔M23=0.5, etc.) at 0.15 weight — no NaN redistribution; same-connector matches now correctly contribute a 100% score rather than being zeroed out. Cable on either side → T1 skipped, T2 also scores via `conn_compat_matrix` at 0.15 weight.

### T2 Primary Score — 70% of final (weights sum to 1.0)
| Field | Weight | Method |
|---|---|---|
| `cpr_values` | 0.30 | `cpr_list_intersection` |
| `ip_rating` | 0.20 | `directional_gte` (step mode, tolerance=1, partial_score=0.5) |
| `connection_type_canonical` | 0.15 | `conn_compat_matrix` (cable cases only; redistributed for specific connectors) |
| `output_circuit_canonical` | 0.15 | `oc_compat_matrix` |
| `housing_diameter_mm` | 0.10 | `housing_diameter_score` |
| `shaft_bore_diameter_mm` | 0.10 | `bore_diameter_score` |

### T3 Secondary Score — 30% of final (weights sum to 1.0)
| Field | Weight | Method |
|---|---|---|
| `supply_voltage` | 0.25 | `voltage_range_overlap` (supply_voltage_min_v + supply_voltage_max_v) |
| `sensing_method` | 0.20 | `exact_match_score` (exact=1.0, mismatch=0.5) |
| `operating_temp_max_c` | 0.15 | `directional_gte` (ratio mode, 5°C tolerance) |
| `shock_resistance_ms2` | 0.15 | `directional_gte` (ratio mode) |
| `shaft_load_radial_n` | 0.10 | `directional_gte` (ratio mode) |
| `vibration_resistance_ms2` | 0.10 | `directional_gte` (ratio mode) |
| `connector_pins` | 0.05 | `connector_pins_score` (linear, max_diff=10) |

**Final score = 0.70 × T2 + 0.30 × T3.** Directional: candidate exceeding source = 100%. Null fields → weight redistributed proportionally among non-null fields in same tier (`_weighted_score()`). Score columns: `sc_t2_{field}`, `sc_t3_{field}`, `t2_score`, `t3_score`, `total_score`.

### Compatibility Matrices (matcher_config.json)
**Output circuit** (`oc_compat_matrix`, default 0.0):
Push-Pull↔TTL RS422=0.4 | Push-Pull↔OC=0.2 | TTL↔OC=0.1 | Sin/Cos only matches Sin/Cos=1.0

**Connection type** (`conn_compat_matrix`, default 0.1, cable cases in T2 only):
cable↔cable=1.0 | cable↔M12/M23/M8/MS-MIL=0.3 | M12↔M23=0.5 | M12↔M8=0.3 | M23↔MS-MIL=0.4

**Scoring params:** `housing_diameter_tight_mm`=2.0, `housing_diameter_loose_mm`=5.0, `bore_diameter_tight_mm`=0.1, `bore_diameter_loose_mm`=2.0, `connector_pins_max_diff`=10

**Config cache:** `_matcher_cfg` loaded once at startup (`load_config(CONFIG_PATH)`), never reloaded mid-run. `load_config()` validates T2 sum=1.0, T3 sum=1.0, tier2+tier3=1.0. `_validate_registries()` confirms all method/rule names registered. Adding NEW scoring method → register in `SCORING_REGISTRY` or `T1_RULE_REGISTRY`.

### No-match reason codes
`no_sql_candidates` | `shaft_type_no_match` | `bore_no_match` | `housing_no_match` | `voltage_class_incompatible` | `t1_no_match` | `zero_score` (v2.4.1 — candidates passed T1 but all scored 0) | `no_candidates` | `no_analog_output`

---

## 10. Database Layer (db_load.py)

**3-tier connection:** (1) `/tmp/silver/encoders.db` DuckDB native TABLE (~30× faster than Parquet) → (2) `/tmp/silver/*.parquet` Parquet VIEW fallback → (3) S3 httpfs last resort.

**Key functions:**
- `get_cached_connection()` — singleton. **NEVER close this.** Used by all API requests.
- `get_connection()` — new connection per call, for CLI scripts only (caller must close).
- `download_silver_locally()` — boto3 S3 download with size-check (`os.path.getsize` vs S3 `ContentLength`, skips unchanged files), then calls `build_local_db()`. Takes 45–90s first run.
- `reload_silver()` — called by `/api/admin/refresh-silver`. Re-downloads + rebuilds + resets cached connection.
- `SILVER_VIEW` — query target: `"encoders"` (native TABLE, Tier 1) or `"encoders_view"` (Parquet VIEW, Tier 2).
- `POSITAL_EXITING_PARTS` — frozenset loaded from Bronze2 CSV at module level. Applied post-SQL in `fetch_candidates()`. If S3 read fails → empty frozenset, filter silently disabled.
- `LIKA_FAMILY_PREFIXES` / `BAUMER_FAMILY_PREFIXES` / `POSITAL_FAMILY_PREFIXES` — frozensets for mfr_hint detection in `_parse_order_code()`.

**fetch_part() lookup stage sequence:**
1. Exact `part_number` match in Silver
2. Kübler decoder → targeted SQL (5-attempt widening): bore+output+supply+conn+IP → drop supply_max+IP → drop supply → drop conn → bore only
3. EPC decoder → same 5-attempt widening. CPR override: when PPR known, `cpr_values` overridden to `[specific_ppr]` so scorer asks "does candidate cover THIS PPR?" not full family range.
4. Lika positional decode (family=token[0], CPR=token[2] if decimal)
4d. Posital prefix LIKE search (v2.4.2): `part_number LIKE 'OCD-INR00%'` — handles partial codes of any length. Silver product_family names ("Through Hollow", "Compact Magnetic") do NOT match Posital order code prefixes (OCD, UCD, UTD, UCF, UCE, UCU), so family-name lookup never works for Posital; this stage bypasses that entirely.
5. PPR-aware family lookup (`cpr_values LIKE '%ppr%'` OR ppr_range covers ppr)
6. Family-only LIKE fallback

**fetch_candidates() SQL pre-filters:** `manufacturer = target` | `shaft_type = source` (skipped if source empty) | `output_voltage_class = source` (exact match) | IP floor: `>= src_ip - 2` (NULL kept) | Housing: `±15mm` absolute (solid only, NULL candidates kept, skipped for hollow source or null source housing).

---

## 11. Silver Schema (42 columns)

**Identity:** `manufacturer` (kubler/epc/sick/posital/lika/baumer), `part_number` (synthetic pipeline key — NOT real order code; EPC has `EPC-` prefix), `product_family`, `encoder_type` (always "incremental"), `sensing_method` (optical/magnetic), `source_datasheet`, `shaft_type` (solid/hollow_blind/hollow_thru).

**Resolution:** `cpr_values` (JSON array string — always `json.loads()`; null for programmable), `ppr_range_min`, `ppr_range_max`, `is_programmable` (bool).

**Output/Circuit:** `output_circuit_canonical` (TTL RS422/Push-Pull/Open Collector/Sin/Cos), `output_voltage_class` (low/universal/analog — **T1 field**), `supply_voltage_min_v`, `supply_voltage_max_v`, `num_output_channels` (A/AB/ABZ/ABZ+inv), `has_index` (bool), `pulse_frequency_max_kHz`, `power_consumption_max_mA`, `reverse_polarity_protection` (bool), `short_circuit_protection` (bool).

**Housing:** `housing_diameter_mm` (float32, null for NEMA/spring-element), `flange_type_canonical` (servo/face_mount/nema/synchro/clamping/square/torque_stop_flexible/torque_stop_rigid/stator_coupling/spring_element_short/spring_element_long), `housing_material`, `flange_material`.

**Shaft:** `shaft_bore_diameter_mm` (OD for solid, bore ID for hollow — **T1+T2 field**), `shaft_material`, `shaft_load_radial_n`, `shaft_load_axial_n`.

**Environmental:** `ip_rating` (int32, e.g. 50/65/67), `operating_temp_min_c`, `operating_temp_max_c`, `shock_resistance_ms2` (**always m/s²** — EPC g-values ×9.81 at ETL), `vibration_resistance_ms2`.

**Speed/Connection/Physical:** `max_speed_rpm`, `connection_type_canonical` (cable/M8/M12/M16/M23/MIL/terminal_block), `connector_pins` (null for cable), `startup_torque_nm`, `moment_of_inertia_gcm2`, `weight_kg`, `bearing_life_rev` (string), `mttfd_years`.

**Kübler-only passthrough:** `output_code`, `connection_type_code` (raw Bronze1 option codes for display order code enrichment in serializers.py).

`union_by_name=true` required in all `read_parquet()` — not all manufacturers populate all 42 columns.

---

## 12. Manufacturer Decoders

### Kübler (kubler_decoder.py, 126KB)
**Path A:** `8.FAMILY.OPTS.PPR` — 31 families. `KUBLER_FAMILY_ALIASES` maps order code token → Silver `product_family` (e.g. `"7000"`→`"Sendix 7000"`, `"5000"`→`"Sendix 5000"`, `"KIS40"`→`"KIS40"`). Option slots decoded positionally: [flange_code, shaft_bore_code, output_type_code, connection_type_code]. Special types: `shaft_bore_with_ip` (5823/5824/5825), `shaft_bore_with_type` (5834). `fixed_specs`: KIS50/KIH50 always ip_rating=65. Cable suffix (trailing `.0100` etc.) stripped before decode.

**Path B:** K-series `K58I.Oxxx.PPR.7chars.5chars[.cable]`. K58I-PR: seg1[1:3]=="PR". Version codes in seg3[1:3]: H1/H2/C1/C2→hollow_thru; S1/S3→solid. Bore codes 06/08/10/12/1A/2A overlap solid and hollow — version code disambiguates.

`validate_decoders()` runs all sample codes at startup, asserts expected values — fails startup if broken.

**14 verified test codes (all pass as of Jun 22):**
`8.KIH50.2631.1000` (KIH50, 1000PPR, h_thru 12.75mm) | `8.KIH50.2422.2048` (KIH50, 2048, h_thru 9.52mm) | `8.KIS40.1342.0500` (KIS40, 500, solid 6mm) | `8.KIS40.1342.1000` (KIS40, 1000, solid 6mm) | `8.KIH40.2442.1024` (KIH40, 1024, h_blind 8mm) | `8.KIH40.5462.1024` (KIH40, 1024, h_blind 8mm) | `8.KIS50.8122.2048` (KIS50, 2048, solid 6mm) | `8.KIS50.8D14.1024` (KIS50, 1024, solid 10mm) | `8.KIS50.B62P.1000` (KIS50, 1000, solid 8mm) | `8.KIH50.2911.1200` (KIH50, 1200PPR, h_thru 8mm — decoder OK, no Posital match for PPR=1200) | `8.KIH50.2344.0500` (KIH50, 500, h_thru 10mm) | `8.7000.1242.2048` (Sendix 7000, 2048, solid 10mm ATEX) | `8.7000.121B.1024.0100` (Sendix 7000, 1024, cable suffix stripped) | `8.5000.7358.1024` (Sendix 5000, 1024, solid 10mm)

### EPC (epc_decoder.py, 43KB)
Data-driven: each family is `EpcFamilyConfig` dataclass with positional layout. 28 entries, 25 Silver families. `shaft_type_by_code` for 755A. `shaft_variant_map` for 260 (B→hollow_blind, T/R→hollow_thru at pos2). `has_input_voltage_pos` for 15S/15T/25T — V5 token clips supply_voltage_max to 5.25V. EPC Silver `part_number` has `EPC-` prefix — users enter codes WITHOUT it (e.g. `755A-07-S-1024-R-HV-S-K00`). `_make_display_code()` in serializers.py strips prefix for display.

---

## 13. Serializers & URL Lookup

**`serialize_source(src, user_input_code)`** → source card JSON: part_number, manufacturer, family, shaft_type, housing_diameter, bore, ip_rating, output_circuit, connection_type, supply_voltage, temp, sensing_method, cpr_list/ppr_range.

**`serialize_result(row, src, rank, src_cpr, t2_cfg, t3_cfg)`** → result card dict with: `part_number`, `display_order_code` (generated by `_kubler_display_code()` using `output_code` + `connection_type_code` Silver passthrough columns), `manufacturer`, `family`, `rank`, `total_score`, `t2_score`, `t3_score`, `t2` dict, `t3` dict, `extra` dict, `product_url`, `t1_passed` list.

Each t2/t3 field: `{score, src_val, cand_val, src_native_label, cand_native_label, label}`. `NATIVE_FIELD_NAMES` maps canonical field → manufacturer's own field name (for display). `FIELD_LABELS` maps canonical field → generic label fallback.

**URL lookup:** Sick → `sick_urls.csv` (7K rows, loaded at startup by part_number key). Posital → `posital_urls.csv` (loaded at startup). Kübler → programmatic slug from family name (strips "Sendix " prefix, converts `-PR` suffix). EPC → `epc_urls.csv` overrides for TRU-TRAC; others use pattern. Baumer → pattern-based. Lika → not implemented (returns None).

---

## 14. API Endpoints

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/api/auth/login` | — | Returns JWT + user info. Sets active_session_id. |
| GET | `/api/auth/me` | user | Daily quota, allowed mfrs, role |
| POST | `/api/auth/heartbeat` | user | +5 min to total_time_spent_minutes |
| POST | `/api/match` | user | Main search. See match flow above. |
| POST | `/api/explain` | — | Claude Haiku AI explanation. Stateless, no auth. 422 if no scored features. |
| GET | `/api/manufacturers` | user | Silver mfrs with display names + row counts |
| GET | `/api/parts/detect` | user | Auto-detect mfr from part number. Searches combined allowed_sources+allowed_targets pool. |
| GET | `/api/parts` | user | Browse Silver (mfr, family, fragment params) |
| GET | `/api/history` | user | User search history (limit param, newest first) |
| POST | `/api/feedback` | user | Thumbs up/down — upserts to feedback table |
| DELETE | `/api/feedback` | user | Remove feedback (toggle off) |
| GET | `/api/feedback/{search_id}` | user | All feedback for a search (for button state restore) |
| POST | `/api/admin/users` | admin | Create user. I-9/I-12 guards applied. |
| GET | `/api/admin/users` | admin | List users (clientadmin scoped to own client) |
| PUT | `/api/admin/users/{email}` | admin | Update constraints. I-11/I-15 guards applied. |
| DELETE | `/api/admin/users/{email}` | admin | Delete user. Cascades to history+feedback (I-13). 409 if CA has children. |
| GET | `/api/admin/users/{email}/history\|errors\|feedback` | admin | Per-user data tabs |
| POST | `/api/admin/refresh-silver` | superadmin | Hot-reload Silver from S3. ~30s. Refreshes VALID_MANUFACTURERS. |
| GET | `/api/admin/analytics` | superadmin | All-client analytics (scans all history tables) |
| GET | `/api/admin/analytics/client` | clientadmin | Scoped analytics (own users only) |
| GET | `/health` | — | Alive check |
| GET | `/health/db` | — | Silver row counts per manufacturer |

---

## 15. Frontend (EncoderMatch.jsx, 310KB)

Single-file React, no build, loaded via CDN Babel transpile at runtime.

**Page routing (`page` state):** `login` → `selector` (superadmin only — others skip to `search`) → `search` | `history` | `admin` | `weights`.

**Key behaviour:**
- Idle timeout: 10 min. Session poll: 30s. Heartbeat: 5 min (tab-visible, live mode only).
- `isAdmin = role in [superadmin, clientadmin]`. DB Coverage panel = superadmin only. Quota bar = enduser only.
- History prefill: click row → pre-populate search panel (part number + source mfr). `replayParams` state. `setDetectedMfr` set to bypass "Code not recognized" without firing detect API. No auto-submit.
- Custom weight sliders: session-scoped, reset on login/refresh, not persisted to DB.
- Dynamic row count: `mfrs.reduce((s,m)=>s+m.count,0)` formatted as `X.XXM+`, falls back to `"1.65M+"`.

**Result card:** circular gauge (green >85%, amber 60–85%, red <60%), T2 + T3 bars, Show Details expands field breakdown, AI Explanation tab (on-demand Haiku call, cached for session), thumbs up/down (live mode only), View Product link.

**No-match banner:** shown for each target with a reason from `no_match_reasons` dict.

---

## 16. DynamoDB User Record Schema

```json
{
  "userId": "user@example.com",        "email": "user@example.com",
  "name": "Display Name",              "password_hash": "<sha256>",
  "role": "enduser|clientadmin|superadmin",
  "client": "Kübler",                  "status": "active|locked|invited",
  "searches_used_today": 0,            "last_search_date": "2026-06-23",
  "searches_limit": 50,                "allowed_results": 10,
  "allowed_sources": ["epc","sick"],   "allowed_targets": ["kubler"],
  "direction": "source_only|bidirectional",
  "user_creation_limit": 10,           "created_by": "admin@example.com",
  "admin_email": "admin@example.com",  "created_at": "2026-06-23T10:00:00",
  "last_login": "...",                 "last_seen": "...",
  "total_time_spent_minutes": 45,      "active_session_id": "<uuid>"
}
```

---

## 17. Known Open Issues

| ID | File | Issue | Priority |
|---|---|---|---|
| I-2 | auth.py | Locked accounts can login (429 on first search) — intentional | — |
| I-4 | JSX | Password `type="text"` — no browser autofill | Low |
| I-6 | JSX | Stale comment: ProductSelectorPage "Appears for all roles" (wrong since Jun 17) | Low |
| I-7 | JSX | Dead code: `encoderDest` clientadmin branch unreachable | Low |
| I-8 | JSX | UserDetailPage avatar hardcoded `#1e3a5f` instead of `roleColors()` | Low |
| I-15 | auth.py | `scan()` no `LastEvaluatedKey` pagination → silent 1MB truncation at 100+ users | Medium |
| I-16 | main.py | `list_tables()` max 100, no pagination → fails at 50+ clients | Medium |
| I-17 | All tables | No DynamoDB TTL — history/errors grow indefinitely | Medium |
| I-18 | encodermatch_users | No GSI on client/role — all filtered queries are full scans | Medium |
| I-21 | Silver/EPC | EPC 15S/15T/15H/25SP/25T/25H families may not be in Silver (~21/35 families ingested) | ⚠️ Verify before handover |
| I-23 | JSX | Source-only enduser dropdown includes allowed_targets manufacturers | Low |
| I-24 | JSX | Feedback `is_good_match` dual `=== true`/`=== 'true'` guards (legacy string) | Low |
| I-25 | main.py | Multi-target search sequential not `asyncio.gather()` | Future |
| — | serializers | `_available_mfrs` field names inconsistent post-refresh (`id/display/count` vs `id/label/rows`) | Low |
| — | refresh_silver_ecs.py | Hardcoded EMAIL + PASSWORD — move to env var or SSM | Medium |
| — | ECS | No Elastic IP — task IP changes on task replacement | Medium |
| — | S3 | Posital Bronze2 CSV not gzipped (25MB → ~3MB gzipped) | Medium |
| — | main.py | ~~CLAUDE_API_KEY as plaintext ECS env var~~ — **DONE Jun 24**: both CLAUDE_API_KEY + JWT_SECRET_KEY moved to Secrets Manager valueFrom in task def rev 7 | ✅ Done |

---

## 18. Kübler Handover Tests

**Before running:** fill in `kubler_handover_tests.py` lines 57–59:
```python
BASE_URL            = "http://<ECS_IP>:8000"
SUPERADMIN_EMAIL    = "saptak.s@aqbsolutions.com"
SUPERADMIN_PASSWORD = "saptak@admin1111"
```

**Run:** `python kubler_handover_tests.py`

**10 steps:** health check → SA login → cleanup old test accounts → create CA (`kubler.ca.test@kubler-test.com`, `KublerAdmin2026!`, limit=2, sources=[epc,sick,posital,lika,baumer], target=kubler) → create 2 endusers + attempt 3rd (must 403 — I-12 live test) → security tests T-A to T-F → 20 CA searches (4/mfr) → 12 EU searches → print result tables → write `kubler_test_results_YYYY-MM-DD.csv` + `kubler_test_summary_YYYY-MM-DD.txt`

**Security tests:**
- T-A: CA PUT `searches_limit` on enduser → must 403 (I-15 guard)
- T-B: CA PUT `allowed_results` on enduser → must 403
- T-C: SA DELETE CA with active users → must 409
- T-D: CA self-delete → must 400/403
- T-E: search with disallowed source mfr (nidec) → must 403
- T-F: delete enduser, verify history API still accessible

**Key expected results:**
- `DBS60E-RGFJD1024` (Sick hollow_blind) → Kübler: **⚠️ TEST CASE BROKEN** — Silver ETL misclassified this encoder as `hollow_thru` (should be `hollow_blind`; `DBS` = Blindhohlwelle in Sick naming). Returns 5 results instead of 0. Fix: correct `shaft_type` in Sick Silver ETL before using this as a handover test. Use a confirmed hollow_blind Sick encoder instead.
- 3rd enduser: **403** "User creation limit of 2 reached"
- EPC 15T hollow_thru → Kübler: KIH50 result ~75–90%
- Baumer EIL580 5000PPR → Kübler: result with low CPR score

**Production Kübler clientadmin — ✅ Handed over June 30:**
```python
{"email": "pierre.brucker@kuebler.com", "name": "Pierre Brucker", "role": "clientadmin", "client": "Kuebler"}
```
Credentials handed over to Kübler client June 30, 2026. Account active, first login June 30 07:06 IST.

**Cleanup after review:** ✅ Done June 30 — all test accounts deleted. DynamoDB history/feedback/errors wiped (~596 rows across 15 tables) for a clean production start. Only 3 accounts remain: `akshay.b@aqbsolutions.com`, `saptak.s@aqbsolutions.com` (superadmins), `pierre.brucker@kuebler.com` (Kübler CA).

---

## 19. Critical Coding Rules

1. **`int(v)` → always `safe_int()` = `int(float(v))`** — DuckDB returns varchar for some columns
2. **`cpr_values` always JSON array string** — always `json.loads(str(raw))`, never treat as scalar
3. **`resolution_ppr` is retired** — use `cpr_values` only
4. **`get_cached_connection()` is singleton — NEVER close it.** Use `get_connection()` for CLI scripts only.
5. **`union_by_name=true` required** in all `read_parquet()` calls
6. **Push-Pull `output_voltage_class` = always `"universal"`** (never "HTL")
7. **Shock/vibration always m/s²** — EPC g-values converted at ETL (×9.81)
8. **`POSITAL_EXITING_PARTS` must be assigned AFTER `logging.basicConfig()`** — earlier placement silently swallows startup log
9. **DynamoDB numerics use `Decimal(str(value))`** — boto3 rejects Python float
10. **`add_history()` wrapped in try/except** — history failures must never kill search response
11. **`delete_user()` cascades to history+feedback** (I-13). `encodermatch_errors` NOT touched — shared audit table.
12. **Weight changes in `matcher_config.json` need no code changes.** New scoring method type → register in `SCORING_REGISTRY` or `T1_RULE_REGISTRY` in matcher.py.
13. **EPC `part_number` in Silver has `EPC-` prefix** — serializers strip it for display
14. **Score columns: `sc_t2_{field}` and `sc_t3_{field}`** — no leading underscore
15. **`SELECT *` should be avoided** — pull only the ~25 columns needed by the scorer
16. **Two services, one cluster** — deploying Posital never affects Kübler and vice versa
---

## 20. Pending Work & Useful Commands

**Priority order:**
1. Verify EPC families in Silver before handover: `python matcher.py --find-parts --mfr epc --fragment 15S` (also 15T, 15H, 25SP, 25T, 25H)
2. ~~Deploy~~ ✅ Done — v2.4.2 deployed June 29, handover tests 31/31 passed
3. ~~Run `kubler_handover_tests.py` post-deploy~~ ✅ Done
4. ~~Clean up test accounts~~ ✅ Done June 30 — DynamoDB wiped clean, 3 accounts remain
5. Deploy `static/EncoderMatch.jsx` lifetime search count cards (v2.4.3)
6. Baumer absolute encoder scraping | Lika absolute Bronze2 fix (`interface_canonical=unknown` for AST6/AMT6 → SSI) | Gzip Posital Bronze2 | Absolute Silver schema design session

**ECS cost tracking:** Kübler service started June 29 19:28 IST. Rate: ~$0.134/hr (2vCPU/8GB Fargate, ap-south-1). Note stop time when shutting down to calculate session cost.

**Useful AWS CLI:**
```powershell
aws ecs list-services --cluster encoder-app-cluster --region ap-south-1
aws ecs update-service --cluster encoder-app-cluster --service encodermatch-kubler-service --force-new-deployment --region ap-south-1
aws s3 ls s3://aqb-data-analytics-demo/encoder_pipeline/silver/ --recursive --human-readable
aws dynamodb list-tables --region ap-south-1
aws dynamodb describe-table --table-name encodermatch_users --region ap-south-1 --query "Table.ItemCount"
```

**CLI tools:**
```powershell
python matcher.py --part "15T-02-SF-2048-N-V1-Q-PP-F00" --source epc --target kubler --top 5
python matcher.py --part "8.7000.1242.2048" --source kubler --target posital --target-part "UTD-IPT0Z-XXXXX-4A7S-PRD"
python matcher.py --find-parts --mfr kubler --family KIH50
python refresh_silver_ecs.py --dry-run
```

---

*AQB Solutions | v2.4.2 | June 30, 2026 | Kübler live — IP 13.206.97.104, task def rev 8. Kübler CA pierre.brucker@kuebler.com handed over Jun 30. DB wiped clean. 1 local change pending (lifetime search cards → v2.4.3).*