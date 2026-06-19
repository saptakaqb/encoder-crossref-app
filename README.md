# EncoderMatch — AI-Powered Industrial Hardware Cross-Reference Tool

**AQB Solutions** | Production v2.4.0 | Deployed on AWS ECS Fargate (ap-south-1)

---

## Overview

EncoderMatch is a cross-reference tool for industrial hardware components. Given a source component part number from one manufacturer, it finds the best replacement candidates from other manufacturers — ranked by technical compatibility using a multi-tier weighted scoring engine.

Currently focused on **rotary and linear encoders**, with valve cross-reference in development.

Designed for sales engineers and procurement teams who need to find hardware equivalents across competing brands quickly and accurately, without manually comparing datasheets.

---

## Supported Manufacturers (Encoders)

| Manufacturer | Role | Silver Rows |
|---|---|---|
| EPC (Encoder Products Company) | Source + Target | 1,520,586 |
| Kübler | Source + Target | 102,748 |
| Posital (FRABA) | Target only | 18,742 |
| Sick | Source + Target | 7,352 |
| Lika | Source + Target | 7,299 |
| Baumer | Source + Target | 475 |
| **Total** | | **1,657,202** |

---

## User Role System

EncoderMatch uses a 3-tier role hierarchy:

```
Superadmin (AQB Solutions)     — blue
    └── creates → Client Admin (e.g. Kübler Admin)   — purple
                      └── creates → End User          — teal (child) / emerald (direct)
```

Each role has a distinct colour applied consistently to avatars, row borders, and badges throughout the app.

| Role | Can Do | Cannot Do |
|---|---|---|
| **Superadmin** | Full access — all users, all manufacturers, all admin functions, adjust any limit | — |
| **Client Admin** | Search (scoped), create/manage their own users, view their users' analytics | Adjust any search limit or user quota (read-only — contact AQB to change) |
| **End User** | Search within their assigned manufacturer pools | Access admin console |

**Constraints flow down — never up:**
- Superadmin sets `allowed_results`, `searches_limit`, and `user_creation_limit` for each client admin
- Client admin cannot grant users more access than they themselves have
- All limit controls are read-only for client admin viewers; adjustments require superadmin

**Post-login routing:**
- Superadmin → Product selector page (Encoders / Valves)
- Client admin + End user → Cross-reference search directly (selector skipped)

---

## How It Works

### High-Level Flow

```
User enters part number
        ↓
Manufacturer detection (_parse_order_code)
        ↓
Real order code decode (Stage 2: Kübler / EPC decoder; Stage 2c: Lika positional)
        ↓
Silver Parquet lookup → Source encoder spec row
        ↓
Candidate fetch from target manufacturer Silver
  → Posital lifecycle filter (Exiting products excluded at module load)
        ↓
T1 hard-stop filtering (shaft type, voltage class, hollow bore tolerance,
  housing diameter, connector type — cable exempt)
        ↓
T2 + T3 weighted scoring (connection type weight redistributed for non-cable pairs)
        ↓
AI explanation generation (Claude API)
        ↓
Results returned to frontend
```

### Data Pipeline (ETL)

```
PDF Datasheets / Web Scraping
    ↓ Claude API extraction
Bronze1 JSON (raw spec extraction, one per model family)
    ↓ Python pipeline (constraint enforcement, axis expansion)
Bronze2 CSV (all valid orderable combinations)
    ↓ csv_to_silver_parquet.py
Silver Parquet (s3://aqb-data-analytics-demo/encoder_pipeline/silver/manufacturer=X/data.parquet)
    ↓ DuckDB httpfs
Live matching engine
```

### Silver Schema (42 columns)

| Group | Key Columns | Scoring Tier |
|---|---|---|
| Identity | manufacturer, part_number, product_family, shaft_type | T1 / Info |
| Resolution | cpr_values (JSON array), ppr_range_min/max, is_programmable | T2 (weight 0.30) |
| Output | output_circuit_canonical, output_voltage_class, supply_voltage_min/max_v | T1 / T2 / T3 |
| Housing | housing_diameter_mm, flange_type_canonical | T1+T2 (weight 0.10) |
| Shaft | shaft_bore_diameter_mm, shaft_load_radial/axial_n | T1+T2 / T3 |
| Environmental | ip_rating, operating_temp_min/max_c, shock/vibration_resistance_ms2 | T2 / T3 |
| Connection | connection_type_canonical, connector_pins | T1 / T2 / T3 |

### Scoring Engine

**T1 Hard Stops** (instant disqualification — not overridable):
- Shaft type mismatch (solid ↔ hollow_blind ↔ hollow_thru)
- Hollow bore diameter mismatch > 10%
- Output voltage class cross (low/TTL ↔ high/HTL)
- Housing diameter mismatch > 10% (solid shaft encoders only)
- **Connector type mismatch — cable exempt** (`exact_match_except_cable`): when both source and candidate use specific connector types (M12, M23, MS/MIL, DSub, M8, M16), they must match exactly. Skipped when source is cable (all candidates pass T1) or candidate is cable (passes T1, scored in T2).

**T2 Primary Score** (70% of final):

| Field | Weight | Scoring mode | Notes |
|---|---|---|---|
| CPR/PPR values | 0.30 | Recall: covered source values ÷ total source values | |
| IP rating | 0.20 | Directional: candidate ≥ source = 100%, shortfall penalised | |
| Connection type | 0.15 | Compatibility matrix: cable→cable=1.0, cable→M12=0.3 | Cable-involved rows only; non-cable handled by T1. Weight redistributed to other fields for non-cable pairs. |
| Output circuit | 0.15 | Compatibility matrix: PP↔TTL=0.4, Sin/Cos=0.0 cross | |
| Housing diameter | 0.10 | Proximity: closest diameter wins | |
| Shaft bore diameter | 0.10 | Proximity: closest bore wins | |

**T3 Secondary Score** (30% of final):

| Field | Weight | Scoring mode |
|---|---|---|
| Supply voltage | 0.25 | Directional: candidate range must cover source range |
| Sensing method | 0.20 | Preference match: same type=1.0, mismatch=0.5 |
| Max operating temp | 0.15 | Directional: candidate max ≥ source max = 100% |
| Shock resistance | 0.15 | Directional: higher capacity = 100% |
| Shaft load | 0.10 | Directional: higher capacity = 100% |
| Vibration resistance | 0.10 | Directional: higher capacity = 100% |
| Connector pins | 0.05 | Preference match |

**Final score** = `0.70 × T2 + 0.30 × T3`

Weights within each tier are adjustable per-user in the Scoring Weights page.

### Real Order Code Decoding

**Kübler decoder** (`kubler_decoder.py`): 31 families — 5000/5020, K58I/K80I, KIS/KIH40/50, A020, 7000/7020 series. Path A (numeric prefix) and Path B (K-series).

**EPC decoder** (`epc_decoder.py`): 28 entries, 25 families. Per-family position layouts.

**Lika positional decode** (`db_load.py`): `FAMILY-SUPPLY-CPR-BORE-...` structure. No separate decoder file.

Partial decode fallback: Stage 2 (full decode) → Stage 3 (PPR + family) → Stage 4 (family only).

---

## Architecture

### AWS Infrastructure

| Component | Detail |
|---|---|
| ECS Cluster | `encoder-app-cluster`, Fargate, ap-south-1 |
| Service | `encodermatch-service` |
| Task Definition | `encodermatch-app` revision 6+ |
| Container | 2 vCPU / 8GB memory, DUCKDB_MEMORY=6GB |
| Port | 8000 (FastAPI) |
| ECR | `155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app` |
| S3 | `aqb-data-analytics-demo`, prefix `encoder_pipeline/` |
| EC2 (ETL) | `encoder-crossref` t3.small, ap-south-1 |

### DynamoDB Tables

| Table | Purpose | PK / SK |
|---|---|---|
| `encodermatch_users` | All user accounts — role, quota, session, `created_by`, `allowed_results` | userId / — |
| `encodermatch_errors` | App error log | userId / timestamp |
| `encodermatch_history_aqb_solutions` | Search history — AQB superadmin | userId / timestamp |
| `encodermatch_history_{slug}` | Search history — per client (clientadmin + endusers share same table) | userId / timestamp |
| `encodermatch_feedback_aqb_solutions` | Thumbs up/down — AQB superadmin | userId / {search_id}#{candidate_pn} |
| `encodermatch_feedback_{slug}` | Thumbs up/down — per client | userId / {search_id}#{candidate_pn} |

**Table routing (`_client_slug` in `auth.py`):**
- `superadmin` → `aqb_solutions`
- `clientadmin` → client slug (same tables as their endusers)
- `enduser` → client slug

### App Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python) |
| Database | DuckDB (in-process, reads S3 Parquet via httpfs) |
| Frontend | React (single JSX file, no build step) |
| AI Explanations | Claude API (claude-sonnet-4-20250514) |
| Auth | JWT + DynamoDB session validation |

### Key Files

```
encoder_appv2/
├── main.py                  # FastAPI app, all API endpoints
├── db_load.py               # DuckDB connection, fetch_part, fetch_candidates
├── matcher.py               # T1/T2/T3 scoring engine — exact_match_except_cable, match_pair utility
├── matcher_config.json      # Scoring weights and T1 rules (config-driven, v1.4)
├── kubler_decoder.py        # Kübler real order code decoder (31 families)
├── epc_decoder.py           # EPC real order code decoder (28 entries)
├── auth.py                  # JWT auth, DynamoDB user/session/history ops, _client_slug()
├── serializers.py           # Response serialization, Kübler display code generation
├── url_lookup.py            # Product URL lookup (Sick, Posital, EPC, Baumer)
├── dynamo_setup.py          # ONE-TIME setup — !! DO NOT RE-RUN ON LIVE SYSTEM !!
├── static/
│   ├── index.html
│   └── EncoderMatch.jsx     # Full React frontend (4,801 lines, single file, no build step)
├── refresh_silver_ecs.py    # Trigger Silver hot-reload on ECS
└── Dockerfile
```

---

## Deployment

### Build and Deploy to ECS

```bash
# 1. Authenticate to ECR
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin 155930759570.dkr.ecr.ap-south-1.amazonaws.com

# 2. Build
docker build -t encodermatch-app . --no-cache

# 3. Tag
VERSION_TAG="v$(date +%m_%d)"
docker tag encodermatch-app:latest 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app:latest
docker tag encodermatch-app:latest 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app:$VERSION_TAG

# 4. Push
docker push 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app:latest
docker push 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app:$VERSION_TAG

# 5. Deploy
aws ecs update-service --cluster encoder-app-cluster --service encodermatch-service --force-new-deployment --region ap-south-1

# 6. Verify
curl http://<ECS_PUBLIC_IP>:8000/health/db
```

### Local Development

```bash
pip install -r requirements.txt
cp config_claude.example.py config_claude.py
# Add CLAUDE_API_KEY to config_claude.py

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

curl http://localhost:8000/health/db
```

### Pair Scoring CLI

```powershell
python matcher.py `
  --part "8.7000.1242.2048" `
  --source kubler `
  --target posital `
  --target-part "UTD-IPT0Z-XXXXX-4A7S-PRD"
```

### Silver Pipeline

```bash
# Dry-run (no S3 write)
python csv_to_silver_parquet.py --mfr lika --dry-run

# Write to S3
python csv_to_silver_parquet.py --mfr lika --s3

# All manufacturers
python csv_to_silver_parquet.py --mfr all --s3
```

---

## Known Issues / Deferred

| Issue | Impact | Status |
|---|---|---|
| **Large undeployed bundle** | 9 files changed across Jun 12–18 not yet on ECS | Deploy: `auth.py`, `dynamo_setup.py`, `serializers.py`, `url_lookup.py`, `EncoderMatch.jsx`, `main.py`, `index.html`, `matcher.py`, `matcher_config.json` |
| `CLAUDE.md` ECR name stale | Deployment commands in CLAUDE.md reference old `encoder-crossref-app` ECR name | Update to `encodermatch-app` before next deploy |
| UserDetailPage header avatar hardcoded | Large avatar in UserDetailPage uses hardcoded blue gradient instead of `rc.grd` from roleColors system | Minor cosmetic; fix in next UI pass |
| History replay empty source_mfr for old records | DynamoDB history records written before Jun 18 lack `source_mfr`. Clicking them pre-fills part number and targets but not source; "Code not recognized" guard may fire | Acceptable degradation; user can re-detect manually |
| No dev/prod environment separation | Test users in local dev appear in live ECS (same DynamoDB) | Add `ENV` prefix to all table names |
| `get_all_users_for_client` does full table scan | Slow as user count grows | Add GSI on `client` field in `encodermatch_users` |
| Kübler URL slugs not yet deployed | Some Kübler product URLs in result cards are broken | `url_lookup.py` slug fix designed, not deployed |
| Baumer remaining categories not yet scraped | Absolute, bearingless, programmable, functional safety categories missing | Scraping in progress |
| Absolute encoder Silver schema not designed | Absolute encoder data (Lika, Baumer) not yet in Silver | Design session required |
| EC2 ETL node is t3.small | Baumer scraper is memory-heavy | Upgrade to t3.medium |
| Elastic IP not assigned to ECS | Public IP changes on every Fargate restart | Assign Elastic IP |
| `refresh_silver_ecs.py` has hardcoded credentials | Security risk | Move to env vars |
| `dynamo_setup.py` has hardcoded passwords | Security risk | Move to env vars |
