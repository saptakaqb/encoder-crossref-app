# EncoderMatch — Claude Code Context
**Project:** AI-powered industrial encoder cross-reference tool  
**Company:** AQB Solutions  
**Last updated:** June 05, 2026  

---

## What This Project Is

EncoderMatch takes a real encoder part number from one manufacturer and finds the best replacement candidates from other manufacturers, ranked by technical compatibility using a multi-tier weighted scoring engine.

Users are sales engineers and procurement teams replacing industrial encoders across brands without manually comparing datasheets.

---

## Repository & Infrastructure

| Item | Value |
|---|---|
| GitHub (personal) | `saptakaqb/encoder-crossref-app` |
| GitHub (org) | `aqbsol/encoder-crossref-app` |
| Branches | `main`, `kuebler`, `posital` |
| ECS Cluster | `encoder-app-cluster` |
| ECS Service | `encodermatch-service` |
| Task Definition | `encodermatch-app` revision 6 (current) |
| Fargate | 2 vCPU / 8 GB, port 8000 |
| DUCKDB_MEMORY | 6 GB (env var) |
| ECR | `155930759570.dkr.ecr.ap-south-1.amazonaws.com/encoder-crossref-app` |
| S3 Bucket | `aqb-data-analytics-demo` |
| S3 Root | `encoder_pipeline/` |
| Region | `ap-south-1` |
| EC2 (ETL only) | `encoder-crossref`, t3.small |

---

## Key Files

```
encoder_appv2/
├── main.py                  # FastAPI app — all API endpoints
├── db_load.py               # DuckDB connection, fetch_part, fetch_candidates, Posital lifecycle filter
├── matcher.py               # T1/T2/T3 scoring engine + match_pair() pair utility
├── matcher_config.json      # Scoring weights and T1 rules — edit weights here, not in code
├── kubler_decoder.py        # Kübler real order code decoder (31 families, 2 paths)
├── epc_decoder.py           # EPC real order code decoder (28 entries, 25 Silver families)
├── auth.py                  # JWT auth, DynamoDB user/session/history management
├── serializers.py           # serialize_source() and serialize_result()
├── url_lookup.py            # Product URL resolution per manufacturer
├── static/EncoderMatch.jsx  # Full React frontend (single file, no build step)
├── static/index.html        # HTML shell for React app
├── refresh_silver_ecs.py    # Trigger Silver hot-reload on ECS via API
├── refresh_silver_local.py  # Trigger Silver hot-reload on local instance
├── dynamo_setup.py          # One-time DynamoDB table creation utility
├── sick_urls.csv            # Sick part_number -> product URL (loaded at startup)
├── posital_urls.csv         # Posital part_number -> product URL (loaded at startup)
├── epc_urls.csv             # EPC family override URLs (TRU-TRAC series)
└── Dockerfile
```

---

## Silver Layer (as of June 05, 2026)

| Manufacturer | Rows | Status |
|---|---|---|
| EPC | 1,520,586 | Complete |
| Kübler | 102,748 | Complete |
| Posital | 18,742 | Complete |
| Sick | 7,352 | Complete |
| Lika | 4,072 | Complete |
| **Total** | **1,653,500** | |

**S3 paths:**
- Silver: `encoder_pipeline/silver/manufacturer={x}/data.parquet` (lowercase partition keys)
- Bronze2: `encoder_pipeline/bronze2/{manufacturer}/`
- Posital Bronze2: `encoder_pipeline/bronze2/posital/posital_raw_full.csv` (lifecycle filter reads from here)

**Future manufacturers** already in `MFR_DISPLAY` in `main.py` (ready when Silver partitions added):
`nidec`, `baumer`, `wachendorff`, `pepperl_fuchs`

---

## Architecture — Match Flow

```
POST /api/match
  → auth + quota check (DynamoDB)
  → fetch_part(source_pn, source_mfr)      # decoder + CPR override
  → fetch_candidates(target_mfr, ...)      # SQL T1 pre-filter + IP floor + housing pre-filter
  → filter Posital Exiting (POSITAL_EXITING_PARTS)
  → apply_t1_python_rules()                # 5 T1 hard stops
  → score_candidates()                     # vectorized numpy T2/T3
  → filter total_score > 0                 # prevents 0% match cards (BUG-F1 fix)
  → dedup_by_family()                      # one result per product family
  → head(effective_top_n)                  # max 3 for enduser
  → serialize_result() × N
  → add_history() (DynamoDB)
  → return JSON
```

**dedup_by_family():** Keeps one row per `product_family`, highest total_score. Without it, all top-N slots fill with variants of the same family. The `top_n * 3` fetch multiplier in `main.py` gives dedup headroom.

---

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/login` | — | Login → JWT + user info |
| GET | `/api/auth/me` | user | Current user info (daily quota) |
| POST | `/api/auth/heartbeat` | user | Increment time_spent_minutes (called every 5 min) |
| POST | `/api/match` | user | Run cross-reference match |
| POST | `/api/explain` | — | Claude AI explanation for one result |
| GET | `/api/manufacturers` | user | List Silver manufacturers (auto-discovers from partitions) |
| GET | `/api/parts/detect` | user | Auto-detect manufacturer from part number fragment |
| GET | `/api/parts` | user | Browse available parts in Silver |
| GET | `/api/history` | user | User's search history |
| POST | `/api/feedback` | user | Thumbs up/down per result card |
| DELETE | `/api/feedback` | user | Remove feedback |
| GET | `/api/feedback/{search_id}` | user | Fetch feedback for a search |
| POST | `/api/admin/users` | admin | Create new enduser |
| GET | `/api/admin/users` | admin | List users |
| PUT | `/api/admin/users/{id}` | admin | Update user constraints |
| DELETE | `/api/admin/users/{id}` | admin | Delete user |
| GET | `/api/admin/users/{email}/history` | admin | Per-user history |
| GET | `/api/admin/users/{email}/errors` | admin | Per-user error log |
| GET | `/api/admin/users/{email}/feedback` | admin | Per-user feedback |
| POST | `/api/admin/refresh-silver` | superadmin | Hot-reload Silver from S3 |
| GET | `/api/admin/analytics` | superadmin | Aggregated search analytics |
| GET | `/health` | — | App health check |
| GET | `/health/db` | — | DuckDB Silver row counts |

---

## Scoring Weights

**T2 (70% of final score):**
| Field | Weight |
|---|---|
| cpr_values | 0.30 |
| ip_rating | 0.20 |
| connection_type_canonical | 0.15 |
| output_circuit_canonical | 0.15 |
| housing_diameter_mm | 0.10 |
| shaft_bore_diameter_mm | 0.10 |

**T3 (30% of final score):**
| Field | Weight |
|---|---|
| supply_voltage | 0.25 |
| sensing_method | 0.20 |
| operating_temp_max_c | 0.15 |
| shock_resistance_ms2 | 0.15 |
| shaft_load_radial_n | 0.10 |
| vibration_resistance_ms2 | 0.10 |
| connector_pins | 0.05 |

**T1 Hard Stops** (instant disqualification):
- `shaft_type` exact match (skipped if either side is empty)
- `shaft_bore_diameter_mm` within ±10% (hollow only, skipped if solid source)
- `output_voltage_class` forbidden pairs (only low↔high pairs — TTL/universal/analog pairs MISSING, see Known Issues)
- `housing_diameter_mm` within ±10% (solid only, skipped if hollow or either side is null)
- `connection_type_canonical` forbidden pairs (M12↔MS/MIL, M23↔DSub blocked; cable exempt)

**Score columns stored as:** `sc_t2_{field}`, `sc_t3_{field}`, `t2_score`, `t3_score`, `total_score`

---

## DuckDB — Three-Tier Connection

1. Local `.db` file — Silver loaded into DuckDB native format (~30× faster) — `/tmp/silver/encoders.db`
2. Local Parquet VIEW — `/tmp/silver/manufacturer=*/data.parquet` (fallback if .db missing)
3. S3 httpfs — Last resort if no local files exist

**Important:**
- `get_cached_connection()` = module-level singleton for Fargate API process — **NEVER close it**
- `get_connection()` = opens a new connection, for one-off CLI scripts only (caller must close)
- Silver `.db` is built from Parquet on startup; `reload_silver()` rebuilds it without ECS restart
- DynamoDB data (users, history, feedback, errors) **persists across ECS restarts** — only in-memory state resets: DuckDB connection, `_available_mfrs`, `POSITAL_EXITING_PARTS`

---

## Fetch Part — Lookup Stages

```
Stage 1: Exact part_number match in Silver
Stage 2: Kübler real order code decode → targeted SQL (5-attempt widening)
         → CPR override: cpr_values overridden to [specific_ppr] so matcher scores
           "does candidate cover THIS PPR?" rather than full family range
Stage 2b: EPC real order code decode → targeted SQL (5-attempt widening)
           → same CPR override
Stage 2c: Lika positional decode (family=token[0], CPR=token[2] if decimal)
Stage 3: PPR-aware family lookup (cpr_values LIKE '%ppr%' OR ppr_range covers ppr)
Stage 4: Family-only LIKE fallback
```

**SQL widening attempts (Kübler/EPC):**
1. bore + output + supply(min+max) + connection + IP
2. bore + output + supply_min + connection (drop supply_max + IP)
3. bore + output + connection (drop supply)
4. bore + output (drop connection)
5. bore only (last resort)

---

## Fetch Candidates — SQL Pre-filters

**Hard stops in SQL** (row-group pruning enabled by Silver sort order):
- `manufacturer = target`
- `shaft_type = source_shaft_type` (skipped if source shaft_type is empty)
- `output_voltage_class = source_class` (exact match — catches TTL/universal/analog differences)

**Soft IP floor:** `ip_rating >= src_ip - 2` (excludes clearly below-IP candidates; NULL kept)

**Housing pre-filter (±15mm absolute, solid shaft only):**
- `housing_diameter_mm BETWEEN src_housing - 15 AND src_housing + 15`
- NULL housing_diameter_mm candidates always kept (NEMA flanges, spring-element flanges)
- Skipped for hollow shaft sources (mounting via torque arm, housing OD is not a hard constraint)
- Skipped when source housing is null (e.g., Kübler A020 — see Known Issues)

**Posital lifecycle filter** (applied after SQL, not in SQL):
- `POSITAL_EXITING_PARTS` frozenset loaded from Bronze2 CSV at module import
- 7,492 Exiting products filtered out of 18,742 total Posital rows
- **Must be assigned AFTER `logging.basicConfig`** — earlier placement silently swallows startup log

---

## User Roles & Access Control

| Role | Description |
|---|---|
| `superadmin` | Full access to all manufacturers, all admin endpoints |
| `clientadmin` | Admin for their client's users, can create/manage endusers |
| `enduser` | Restricted to `allowed_sources` + `allowed_targets` pool |

**Enduser access control:**
- `allowed_sources` and `allowed_targets` are independent multi-select lists
- Source dropdown shows combined `allowed_sources + allowed_targets` pool (bidirectional — any manufacturer in either pool can be the source)
- Target checkboxes show `allowed_targets` minus current source selection
- Auto-detection (`/api/parts/detect`) searches combined `allowed_sources + allowed_targets`
- `direction` field on user record: `"source_only"` (default) or `"bidirectional"`
- Max 3 results per search (enduser cap; admins get requested `top_n`)
- Daily search limit enforced, resets at UTC midnight

**Admins:**
- Bypass `allowed_sources/allowed_targets` — use `VALID_MANUFACTURERS` (auto-discovered from Silver)
- `VALID_MANUFACTURERS` populated at startup from Silver; fallback hardcoded set: `{kubler, epc, sick, posital, lika}`

---

## DynamoDB Tables

| Table | Keys | Purpose |
|---|---|---|
| `encodermatch_users` | hash: userId | User accounts, quota, session tokens, role |
| `encodermatch_history_{slug}` | hash: userId, range: timestamp | Per-client search history |
| `encodermatch_feedback_{slug}` | hash: userId, range: sk=`search_id#candidate_pn` | Per-client thumbs up/down |
| `encodermatch_errors` | hash: userId, range: timestamp | App error log |

- Slug derivation: superadmin/clientadmin → `"admin"`, enduser → sanitised `client` name
- Per-client history + feedback tables auto-created on user registration (background thread)
- `add_history()` is **synchronous** (not fire-and-forget) — causes ~2.3s latency per search (BUG-F2)

---

## Manufacturer Decoders

### Kübler (`kubler_decoder.py`)
**Path A** (numeric prefix `8.FAMILY.opts.ppr` — 31 families):
- Slot positions: [flange, shaft_bore, output_type, connection_type]
- Special slot types: `shaft_bore_with_ip` (5823/5824/5825), `shaft_bore_with_type` (5834/5834FS2/5834FS3)
- `fixed_specs`: KIS50/KIH50 always ip_rating=65
- Families with "05" prefix: 2400/2420 miniature encoders

**Path B** (K-series: `K58I.Oxxx.PPR.7chars.5chars[.cable]`):
- K58I-PR: detected via seg1[1:3]=="PR"; silver_family="K58I-PR"
- K80I: hollow_thru only; K80I-PR adds extended PPR range
- Version codes in seg3[1:3]: H1/H2/C1/C2→hollow_thru; S1/S3→solid
- Bore codes 06/08/10/12/1A/2A overlap solid and hollow — must use version code to disambiguate

**`KUBLER_FAMILY_ALIASES`**: maps order code token → Silver product_family (e.g. "5814"→"Sendix 5814", "7000"→"Sendix 7000")

**`validate_decoders()`**: runs every sample code at API startup, asserts expected values — fails startup if any decoder is broken.

### EPC (`epc_decoder.py`)
**Data-driven:** each family is an `EpcFamilyConfig` dataclass with position layout.
- 28 decoder entries across 25 Silver families
- `shaft_type_by_code`: 755A — shaft codes (07/08/06/32/20/19) → solid; all others → hollow_blind
- `shaft_variant_map`: 260 — B→hollow_blind, T/R→hollow_thru (at pos2)
- `has_input_voltage_pos`: 15S/15T/25T/etc. — V5 token at pos5 clips supply_voltage_max to 5.25V
- Trailing token scanner for optional temp/sealing tokens
- CPR up to 6 digits (TRP: 100,000 max)

---

## Critical Coding Rules

1. **Never use `int(v)` directly** — always use `safe_int()` which does `int(float(v))`. DuckDB returns all-varchar from Silver.
2. **`cpr_values` is always a JSON array string** — never one row per CPR value. Use `json.loads()` to parse.
3. **`resolution_ppr` integer field is retired** — do not use. Use `cpr_values` JSON array.
4. **DuckDB connections are not thread-safe** — never cache a new connection per request. Use `get_cached_connection()`.
5. **Silver `part_number` is a synthetic pipeline key** — not a real manufacturer order code. Real order codes are decoded by manufacturer decoders.
6. **`union_by_name=true` required** in `read_parquet` to handle schema merging across manufacturer partitions.
7. **Push-Pull `output_voltage_class` = always "universal"** (never "HTL").
8. **Shock/vibration values are always in m/s²** in Silver — EPC g-values converted during ETL (×9.81).
9. **`POSITAL_EXITING_PARTS` must be assigned AFTER `logging.basicConfig`** — otherwise startup log is silently swallowed.
10. **`SELECT *` should be avoided** — pull only the ~25 columns needed by scorer.
11. **`output_voltage_class` in Silver stores:** `"TTL"`, `"universal"`, `"analog"` for EPC/Kübler/Sick. Posital/Lika legacy Bronze2 used `"low"/"high"`. The SQL `output_voltage_class = ?` pre-filter works because it matches whatever is in Silver exactly. The Python T1 `forbidden_pairs` only has `["low","high"]` pairs — it is dead code for EPC/Kübler/Sick as the source.
12. **EPC synthetic `part_number` has `"EPC-"` prefix** — `_make_display_code()` in serializers strips it for display. Users enter codes WITHOUT the prefix (e.g. `15S-21-S-1024-A-OC-M1-F00-S`).
13. **Score columns are named `sc_t2_{field}` and `sc_t3_{field}`** (no leading underscore). The old `_t2_{field}` naming was a bug fixed before current version.

---

## Known Issues (Carry Forward)

| Issue | Impact | Fix |
|---|---|---|
| Kübler A020 `housing_diameter_mm` = null in Silver | Housing SQL pre-filter skipped, T2 score inflated | Populate 24.0mm in Silver ETL |
| `output_voltage_class` forbidden_pairs uses `"low"/"high"` only | Dead code for EPC/Kübler/Sick — SQL pre-filter masks it in normal flow; `match_pair()` also unaffected in current tests | Add `TTL/universal/analog` pairs to `matcher_config.json` |
| Posital `is_discontinued`/`replaced_by` not in Silver | UCD→UTD replacement not surfaced (both share family "Cube and Square", equal scores) | Re-scrape Posital, add fields to Silver schema |
| `_available_mfrs` field names inconsistent post-refresh | Database tab may misrender after Refresh Data: startup uses `id/display/count`, post-refresh uses `id/label/rows` | Align field naming |
| BUG-F2: ~2.3s DynamoDB latency per search | Slow search response | Make `add_history` fire-and-forget |
| BUG-F3: Kübler A020 housing null | See above | ETL fix |
| BUG-U5: T2 null score bar renders as red 0% | Visual confusing for enduser | Verify with live A020 test case |
| BUG-U6: End-user result cap of 3 not surfaced in UI | User confused why only 3 results | Hide or label "Results to Show" dropdown for endusers |
| Elastic IP not assigned | ECS public IP changes on Fargate restart | Assign Elastic IP |
| GitHub push pending | Recent changes not on remote | `git push` when ready |

---

## Pending Pipeline Work

- EPC families still needing Bronze1/Bronze2: 770 NEMA expansion; 8 families (702, 702 Motor Mount, 711, 715, 716, 758, 775, 776)
- Kübler Bronze2 gzip removal from `datasheet_to_csv_pipeline.py`
- Kübler 7100/7120/2430/2440/H120 families queued for Silver
- Absolute encoder Silver schema design (next major schema work)
- Posital `is_discontinued`/`replaced_by` fields — requires re-scrape

---

## Deployment Commands

```bash
# Build and push to ECR
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin 155930759570.dkr.ecr.ap-south-1.amazonaws.com
docker build -t encoder-crossref-app . --no-cache
VERSION_TAG="v$(date +%m_%d)"
docker tag encoder-crossref-app:latest 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encoder-crossref-app:latest
docker tag encoder-crossref-app:latest 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encoder-crossref-app:$VERSION_TAG
docker push 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encoder-crossref-app:latest
docker push 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encoder-crossref-app:$VERSION_TAG

# Deploy
aws ecs update-service --cluster encoder-app-cluster --service encodermatch-service --force-new-deployment --region ap-south-1

# Health check after deploy
curl http://<ECS_PUBLIC_IP>:8000/health/db
```

---

## Pair Scoring CLI (dev/testing only)

```powershell
python matcher.py `
  --part "8.7000.1242.2048" `
  --source kubler `
  --target posital `
  --target-part "UTD-IPT0Z-XXXXX-4A7S-PRD"
```

Test result (Jun 05): Kübler `8.7000.1242.2048` → Posital `UTD-IPT0Z-XXXXX-4A7S-PRD` = **82.5%** (T2=86.8%, T3=72.4%). Key misses: IP67 vs IP66 (T2 IP=0.500), optical vs magnetic (T3 sensing=0.500), shock 2500 vs 981 m/s² (T3 shock=0.392).

---

## Key Design Decisions

1. **DuckDB singleton** — never close; `get_cached_connection()` for the API process
2. **Silver .db file (~30× faster)** built at startup; hot-reload via `/api/admin/refresh-silver`
3. **CPR override** — when user enters a specific order code (PPR known), `cpr_values` overridden to `[ppr]` so scoring is "does candidate cover THIS PPR?" not "does it cover the full family range?"
4. **Posital exiting filter** — applied post-SQL (lifecycle not in Silver schema); frozenset at module level
5. **Per-client DynamoDB tables** — privacy isolation between clients; slug derived from client name
6. **Daily search limits** (not lifetime) with UTC midnight reset; atomic DynamoDB conditional update
7. **Admins bypass allowed_sources/targets** — use `VALID_MANUFACTURERS` (auto-discovered from Silver)
8. **Zero-score filter** — `combined[combined["total_score"] > 0]` prevents 0% match cards
9. **Null weight redistribution** — null fields' weights redistributed proportionally in `_weighted_score()`
10. **Bidirectional enduser search** — `allowed_sources + allowed_targets` pool is combined for source dropdown and auto-detect

---

## ETL Rules Documents

- `ENCODER_ETL_EXTRACTION_RULES.md` — core rules for all manufacturers
- `EPC_EXTRACTION_RULES.md` — EPC-specific Bronze1/Bronze2 rules
- `KUBLER_EXTRACTION_RULES.md` — Kübler-specific rules
