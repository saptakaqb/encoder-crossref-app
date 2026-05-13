# EncoderMatch

AI-powered incremental encoder cross-reference platform for AQB Solutions.

Enables sales engineers to find replacement encoders across competitor catalogues using a tiered scoring engine with Claude AI-generated explanations.

---

## Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Local Development Setup](#local-development-setup)
- [Project Structure](#project-structure)
- [Data Pipeline](#data-pipeline)
- [Scoring Engine](#scoring-engine)
- [User Roles & Access Control](#user-roles--access-control)
- [API Reference](#api-reference)
- [ECS Deployment](#ecs-deployment)
- [Environment Variables](#environment-variables)
- [Running Tests](#running-tests)
- [Scaling Notes](#scaling-notes)
- [Known Limitations](#known-limitations)

---

## Architecture Overview

```
Browser (React/JSX)
      │
      ▼
FastAPI (main.py)  ←──  DynamoDB (users, history)
      │
      ▼
matcher.py  ──►  DuckDB  ──►  Silver Parquet (/tmp/silver/)
                                    ▲
                              Downloaded from S3
                              at container startup
                              via boto3
      │
      ▼
Claude API  (AI explanation, /api/explain)
```

- **Frontend**: Single-file React app served as static JSX (no build step, Babel via CDN)
- **Backend**: FastAPI, single `uvicorn` process
- **Database**: DuckDB (in-process), reads Parquet files from local disk (downloaded from S3 at startup)
- **Auth**: JWT tokens, single-session enforcement via DynamoDB
- **Users**: Stored in DynamoDB (`encodermatch_users`)
- **History**: Stored in DynamoDB (`encodermatch_history`)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 (CDN), Tailwind (CDN), IBM Plex fonts |
| Backend | Python 3.11, FastAPI, Uvicorn |
| Query engine | DuckDB 1.1.3 + PyArrow |
| Data storage | AWS S3 (Parquet), AWS DynamoDB |
| ETL | Pandas, PyArrow, boto3 |
| Auth | JWT (python-jose), bcrypt (passlib) |
| AI | Anthropic Claude API (`claude-sonnet-4-6`) |
| Deployment | Docker, AWS ECS Fargate (2 vCPU / 8 GB) |
| Container registry | AWS ECR |

---

## Local Development Setup

### Prerequisites

- Python 3.10+
- AWS CLI configured with credentials that have S3 read + DynamoDB read/write access
- An Anthropic API key

### Step 1 — Clone and install

```bash
git clone https://github.com/saptakaqb/ai-cross-reference.git
cd ai-cross-reference/encoder_app
pip install -r requirements.txt
```

### Step 2 — Configure secrets

```bash
cp config_claude.example.py config_claude.py
```

Edit `config_claude.py` and fill in your Anthropic API key:

```python
CLAUDE_API_KEY = "sk-ant-api03-YOUR-KEY-HERE"
MODEL = "claude-sonnet-4-6"
```

### Step 3 — Configure AWS credentials

```bash
aws configure
```

Enter when prompted:
- **Access Key ID**: your AWS access key
- **Secret Access Key**: your AWS secret key
- **Region**: `ap-south-1`
- **Output format**: `json`

The app needs access to:
- `S3`: `aqb-data-analytics-demo` bucket (read)
- `DynamoDB`: `encodermatch_users`, `encodermatch_history` tables (read/write)

### Step 4 — Start the app

```bash
uvicorn main:app --port 8000 --reload
```

On first boot, Silver Parquet files (~142 MB total) are downloaded from S3 to `/tmp/silver/` automatically:

```
EncoderMatch API starting up ...
  Matcher config loaded: 6 T2 fields, 7 T3 fields
  Downloading Silver from S3 (boto3) ...
    Downloading manufacturer=kubler/data.parquet  (8.2 MB)
    Downloading manufacturer=epc/data.parquet     (118.4 MB)
    Downloading manufacturer=sick/data.parquet    (3.9 MB)
    Downloading manufacturer=posital/data.parquet (9.7 MB)
  Silver cached locally — queries will use local disk.
  Ready.
```

**First boot**: ~30–60s (home internet → S3 ap-south-1).  
**Subsequent restarts**: near-instant (`/tmp/silver/` persists until machine reboot).

Open `http://localhost:8000` in your browser.

### Default credentials (shared dev)

```
saptak.s@aqbsolutions.com  /  saptak@admin1111    superadmin
akshay.b@aqbsolutions.com  /  akshay@admin9999    superadmin
test@posital.com           /  posital@test123     enduser (Posital, 5 searches/day)
```

> ⚠️ **DynamoDB is shared** — all developers connect to the same tables as production.
> Create a separate dev DynamoDB or use a dedicated test account before onboarding external developers.

---

## Project Structure

```
encoder_app/
│
├── main.py                   # FastAPI app — routes, auth, match endpoint, AI explain
├── auth.py                   # JWT logic, user CRUD against DynamoDB
├── matcher.py                # Scoring engine — T1 hard stops, T2/T3 weighted scoring
├── matcher_config.json       # Scoring weights (T2 × 6 fields, T3 × 7 fields)
├── db_load.py                # DuckDB connection, S3 Silver download, fetch_part/candidates
├── serializers.py            # Result serialisation — native field labels, formatters
├── url_lookup.py             # Product URL lookup (Sick, Posital, EPC CSV-backed)
├── dynamo_setup.py           # One-time DynamoDB table creation script
├── config_claude.py          # ← GITIGNORED — local Claude API key + model
├── config_claude.example.py  # Template — copy to config_claude.py
│
├── EncoderMatch.jsx          # Single-file React frontend (served as static file)
├── index.html                # Shell HTML — loads React + Babel from CDN
│
├── requirements.txt          # Python dependencies
├── Dockerfile                # Multi-stage Docker build for ECS
│
├── sick_urls.csv             # Sick product URL lookup table
├── posital_urls.csv          # Posital product URL lookup table
├── epc_urls.csv              # EPC product URL lookup table
│
└── test_encodermatch.py      # Pytest test suite (13 test classes, ~80 test cases)

etl/
├── datasheet_to_csv_pipeline.py      # Kübler Bronze1 → Bronze2 ETL
├── epc_datasheet_to_csv_pipeline.py  # EPC Bronze1 → Bronze2 ETL
└── csv_to_silver_parquet.py          # Bronze2 CSV → Silver Parquet (all manufacturers)
```

---

## Data Pipeline

Silver data lives on S3 and is downloaded to the container at startup. The pipeline that produces it:

```
PDF Datasheets
      │
      ▼  (Claude API extraction)
Bronze1 JSON   ← raw extracted fields, manufacturer-native names
      │
      ▼  (rule enforcement, expansion)
Bronze2 CSV    ← normalised, validated, cumulative master per manufacturer
      │
      ▼  (csv_to_silver_parquet.py)
Silver Parquet ← 42-col canonical schema, typed, hive-partitioned by manufacturer
      │
      ▼
S3: encoder_pipeline/silver/manufacturer=<mfr>/data.parquet
```

### Manufacturers in Silver

| Manufacturer | Rows | S3 path |
|---|---|---|
| Kübler | ~14,700 | `silver/manufacturer=kubler/data.parquet` |
| EPC | ~232,000 | `silver/manufacturer=epc/data.parquet` |
| Sick | ~7,400 | `silver/manufacturer=sick/data.parquet` |
| Posital | ~18,700 | `silver/manufacturer=posital/data.parquet` |

### Adding new families to an existing manufacturer

```bash
# 1. Run ETL to append new families to Bronze2 CSV on S3
python datasheet_to_csv_pipeline.py --family <NewFamily> --pages <n>-<m>

# 2. Dry-run Silver transform — check fill rates, look for ⚠ warnings
python csv_to_silver_parquet.py --mfr kubler --dry-run

# 3. Write Silver to S3
python csv_to_silver_parquet.py --mfr kubler --s3

# 4. Redeploy ECS so the new Silver is downloaded at startup
aws ecs update-service --cluster encoder-app-cluster \
    --service encodermatch-service --force-new-deployment --region ap-south-1
```

---

## Scoring Engine

Matching is intentionally directional — scoring A→B and B→A can differ.

### T1 Hard Stops (score = 0, candidate excluded)

| Rule | Reason |
|---|---|
| `shaft_type` mismatch (solid vs hollow) | Mechanically incompatible |
| TTL ↔ HTL cross | Electrically incompatible |
| Hollow bore diameter mismatch | Cannot mount |

### T2 — Physical Match (weight: 70% of final score)

| Field | Default weight |
|---|---|
| CPR / PPR coverage | 0.35 |
| IP rating | 0.20 |
| Output circuit type | 0.15 |
| Housing diameter | 0.10 |
| Shaft/bore diameter | 0.10 |
| Connection type | 0.10 (adjusted) |

### T3 — Secondary Specs (weight: 30% of final score)

| Field | Default weight |
|---|---|
| Supply voltage range | 0.25 |
| Sensing method | 0.20 |
| Max operating temperature | 0.10 |
| Shock resistance | 0.15 |
| Shaft load | 0.10 |
| Vibration resistance | 0.10 |
| Connector pins | 0.05 (adjusted) |

**Final score** = 0.70 × T2 + 0.30 × T3

Weights are user-adjustable per session via the Scoring Weights page. CPR scoring uses list-intersection recall: `len(src_values ∩ candidate_values) / len(src_values)`. Programmable candidates that cover the full source range score 1.0.

---

## User Roles & Access Control

| Role | Source pool | Target pool | Daily limit | Bidirectional |
|---|---|---|---|---|
| `superadmin` | All manufacturers | All manufacturers | Unlimited | ✅ |
| `clientadmin` | All manufacturers | All manufacturers | Unlimited | ✅ |
| `enduser` | Set by admin | Locked to `client` | Set by admin | ❌ |

Enduser target is locked server-side — cannot be overridden by the frontend. Part number validation: if a part is not found in the selected source manufacturer's Silver data, the API returns 404.

---

## API Reference

All endpoints require `Authorization: Bearer <jwt>` unless noted.

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | None | App health check |
| `GET` | `/health/db` | None | DuckDB + Silver row counts per manufacturer |
| `POST` | `/api/auth/login` | None | Login → JWT token |
| `GET` | `/api/auth/me` | ✅ | Current user info |
| `POST` | `/api/match` | ✅ | Cross-reference search |
| `GET` | `/api/parts/detect` | ✅ | Auto-detect manufacturer from part number |
| `GET` | `/api/parts` | ✅ | Browse parts by manufacturer/family |
| `POST` | `/api/explain` | ✅ | Claude AI explanation for a match result |
| `GET` | `/api/history` | ✅ | Search history for current user |
| `GET` | `/api/admin/users` | Admin | List all users |
| `POST` | `/api/admin/users` | Admin | Create new user |
| `DELETE` | `/api/admin/users/{email}` | Admin | Delete user |

### POST `/api/match` — example request

```json
{
  "part_number":  "8.KIS40.1342.1024",
  "source_mfr":  "kubler",
  "target_mfrs": ["epc", "sick", "posital"],
  "top_n":        5,
  "custom_weights": {
    "tier2": { "ip_rating": 0.4, "cpr_values": 0.3 },
    "tier3": { "supply_voltage": 0.3 }
  }
}
```

---

## ECS Deployment

### Prerequisites

- AWS CLI configured
- Docker running
- Logged in to ECR

### Deploy commands

```bash
# 1. ECR login
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin \
  155930759570.dkr.ecr.ap-south-1.amazonaws.com

# 2. Build
cd encoder_app
docker build -t encodermatch-app .

# 3. Tag
docker tag encodermatch-app:latest \
  155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app:latest

# 4. Push
docker push \
  155930759570.dkr.ecr.ap-south-1.amazonaws.com/encodermatch-app:latest

# 5. Force redeploy
aws ecs update-service \
  --cluster encoder-app-cluster \
  --service encodermatch-service \
  --force-new-deployment \
  --region ap-south-1

# 6. Watch rollout (blocks until stable, ~2–3 min)
aws ecs wait services-stable \
  --cluster encoder-app-cluster \
  --services encodermatch-service \
  --region ap-south-1
```

> ⚠️ The ECS public IP changes on every force-redeploy. No Elastic IP is assigned yet.  
> Get the new IP from: ECS Console → cluster → task → Network tab.

### After deploy — verify

```
http://<new-ip>:8000/health/db
```

Should return `"status": "ok"` with row counts for all 4 manufacturers. If it returns an error, the traceback in the response body will show the root cause.

---

## Environment Variables

Set in ECS task definition. For local dev, these are read with sensible defaults — only `CLAUDE_API_KEY` (via `config_claude.py`) and AWS credentials are required.

| Variable | Default | Description |
|---|---|---|
| `AWS_REGION` | `ap-south-1` | AWS region |
| `S3_BUCKET` | `aqb-data-analytics-demo` | S3 bucket for Silver Parquet |
| `S3_ROOT` | `encoder_pipeline` | S3 key prefix |
| `DYNAMO_USERS_TABLE` | `encodermatch_users` | DynamoDB users table |
| `DYNAMO_HISTORY_TABLE` | `encodermatch_history` | DynamoDB history table |
| `JWT_SECRET_KEY` | *(required)* | JWT signing secret — rotate before client handoff |
| `CLAUDE_API_KEY` | *(from config_claude.py)* | Anthropic API key |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model string |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |
| `TOKEN_EXPIRE_HOURS` | `24` | JWT token lifetime |
| `DUCKDB_THREADS` | `2` | DuckDB thread count (match Fargate vCPU) |
| `DUCKDB_MEMORY` | `6GB` | DuckDB memory limit |

---

## Running Tests

```bash
# Local (against localhost:8000)
pip install pytest requests
pytest test_encodermatch.py -v --tb=short

# Against ECS (set BASE_URL)
BASE_URL=http://<ecs-ip>:8000 pytest test_encodermatch.py -v --tb=short

# Specific test class only
pytest test_encodermatch.py::TestHealth -v
pytest test_encodermatch.py::TestSearchAdmin -v
pytest test_encodermatch.py::TestSecurity -v
```

Test classes:

| Class | Coverage |
|---|---|
| `TestHealth` | App + DB health, Silver row counts |
| `TestAuthentication` | Login, JWT, session enforcement |
| `TestSearchAdmin` | Search results, scoring, dedup, field structure |
| `TestSearchEnduser` | Target locking, source restrictions, top_n cap |
| `TestDailyLimit` | Counter increment, remaining decrement |
| `TestAutoDetect` | `/api/parts/detect` endpoint |
| `TestSearchHistory` | History endpoint, record fields, pagination |
| `TestAdminUserManagement` | Create, delete, list users; access control |
| `TestPartsBrowser` | Browse by manufacturer, family, fragment |
| `TestSecurity` | SQL injection, token tampering, role enforcement |
| `TestScoringValidation` | Score range, formula, CPR, T2/T3 fields |
| `TestAPIContract` | Response structure, field consistency |
| `TestPerformance` | Warm search timing, elapsed_s accuracy |

---

## Scaling Notes

Silver storage and startup download will grow as more manufacturers and families are added.

| Silver size | Action required |
|---|---|
| ~142 MB (current) | No action — 120s health check start-period |
| ~500 MB | Increase `start-period` to 180s in Dockerfile |
| ~1 GB | Increase `start-period` to 300s + implement background download with httpfs fallback during startup |
| ~2–5 GB | Mount EFS volume to Fargate — files persist across deployments, only delta downloaded on redeploy |
| 5 GB+ | Consider Athena or persistent EC2 with EBS-mounted DuckDB |

EPC Silver currently has ~2 row groups for 232K rows. Re-uploading with `row_group_size=5000` in `csv_to_silver_parquet.py → write_parquet_s3()` would give ~46 row groups and improve DuckDB predicate pushdown 2–4×.

---

## Known Limitations

- **No Elastic IP** — ECS public IP changes on every force-redeploy. Assign an Elastic IP or add an NLB before client handoff.
- **Shared DynamoDB** — all environments use the same tables. Separate dev/prod tables recommended.
- **Single Fargate task** — no auto-scaling. One task handles all traffic.
- **AI explanations require a funded Anthropic API key** — if the key runs out of credits, `/api/explain` returns an error but all other search functionality remains unaffected.
- **Silver re-download on each ECS restart** — ~10s same-region today. Will need EFS or background download strategy as Silver grows (see Scaling Notes).
- **`config_claude.py` is gitignored** — never commit this file. Rotate `CLAUDE_API_KEY` before client handoff.

---

*AQB Solutions | EncoderMatch v1.0 | May 2026*