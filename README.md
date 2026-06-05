# EncoderMatch — AI-Powered Industrial Encoder Cross-Reference Tool

**AQB Solutions** | Production v2 | Deployed on AWS ECS Fargate (ap-south-1)

---

## Overview

EncoderMatch is a cross-reference tool for industrial rotary encoders. Given a source encoder part number from one manufacturer, it finds the best replacement candidates from other manufacturers — ranked by technical compatibility using a multi-tier weighted scoring engine.

It is designed for sales engineers and procurement teams who need to find encoder equivalents across competing brands quickly and accurately, without manually comparing datasheets.

---

## Supported Manufacturers

| Manufacturer | Role | Silver Rows |
|---|---|---|
| EPC (Encoder Products Company) | Source + Target | 1,520,586 |
| Kübler | Source + Target | 102,748 |
| Posital (FRABA) | Target only | 18,742 |
| Sick | Source + Target | 7,352 |
| Lika | Source + Target | 4,072 |
| **Total** | | **1,653,500** |

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
T1 hard-stop filtering (shaft type, voltage class, hollow bore tolerance, housing OD, connection type)
        ↓
T2 + T3 weighted scoring
        ↓
AI explanation generation (Claude API)
        ↓
Results returned to frontend
```

### Data Pipeline (ETL)

Encoder datasheets → structured Silver Parquet on S3, read by DuckDB at query time.

```
PDF Datasheets
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

The canonical schema used by the matcher. Key groups:

| Group | Key Columns | Scoring Tier |
|---|---|---|
| Identity | manufacturer, part_number, product_family, shaft_type | T1 / Info |
| Resolution | cpr_values (JSON array), ppr_range_min/max, is_programmable | T2 (weight 0.35) |
| Output | output_circuit_canonical, output_voltage_class, supply_voltage_min/max_v | T1 / T2 / T3 |
| Housing | housing_diameter_mm, flange_type_canonical | T2 (weight 0.10) |
| Shaft | shaft_bore_diameter_mm, shaft_load_radial/axial_n | T1+T2 / T3 |
| Environmental | ip_rating, operating_temp_min/max_c, shock/vibration_resistance_ms2 | T2 / T3 |
| Connection | connection_type_canonical, connector_pins | T3 |

### Scoring Engine

**T1 Hard Stops** (instant disqualification):
- Shaft type mismatch (solid ↔ hollow_blind ↔ hollow_thru)
- Hollow bore diameter mismatch > 1mm
- Output voltage class cross (TTL ↔ universal/analog)
- Housing diameter mismatch > 10% (solid shaft only)
- Incompatible connector types (M12 ↔ MS/MIL, M23 ↔ DSub, etc.)

**T2 Primary Score** (70% of final):

| Field | Weight |
|---|---|
| CPR/PPR values | 0.30 |
| IP rating | 0.20 |
| Connection type | 0.15 |
| Output circuit | 0.15 |
| Housing diameter | 0.10 |
| Shaft bore diameter | 0.10 |

**T3 Secondary Score** (30% of final):

| Field | Weight |
|---|---|
| Supply voltage | 0.25 |
| Sensing method | 0.20 |
| Max operating temp | 0.15 |
| Shock resistance | 0.15 |
| Shaft load | 0.10 |
| Vibration resistance | 0.10 |
| Connector pins | 0.05 |

**Final score** = `0.70 × T2 + 0.30 × T3`

### Real Order Code Decoding

Users can enter real manufacturer order codes (not just synthetic internal codes). The decoders parse the code, extract Silver-queryable parameters, and retrieve the correct source row.

**Kübler decoder** (`kubler_decoder.py`): 31 families including 5000/5020 series, K58I/K80I, KIS/KIH40/50, A020, 7000/7020 series. Handles Path A (numeric prefix), Path B (K-series), and partial decode fallback.

**EPC decoder** (`epc_decoder.py`): 28 decoder entries covering all 25 EPC Silver families. Each family config declares its own position layout since EPC families use different ordering guide structures.

**Lika positional decode** (in `db_load.py`): Lika codes are structured as `FAMILY-SUPPLY-CPR-BORE-...` — family from token 0, CPR from token 2 if decimal. No separate decoder file needed.

Partial decode fallback stages:
- **Stage 2**: Full hardware decode → targeted Silver SQL
- **Stage 3**: PPR + family known → range/list match
- **Stage 4**: Family only → first available row

---

## Architecture

### AWS Infrastructure

| Component | Detail |
|---|---|
| ECS Cluster | `encoder-app-cluster`, Fargate, ap-south-1 |
| Service | `encodermatch-service` |
| Task Definition | `encodermatch-app` revision 6 (current) |
| Container | 2 vCPU / 8GB memory, DUCKDB_MEMORY=6GB |
| Port | 8000 (FastAPI) |
| ECR | `155930759570.dkr.ecr.ap-south-1.amazonaws.com/encoder-crossref-app` |
| S3 | `aqb-data-analytics-demo`, prefix `encoder_pipeline/` |
| EC2 (ETL) | `encoder-crossref` t3.small, ap-south-1 |

### DynamoDB Tables

| Table | Purpose |
|---|---|
| `encodermatch_users` | User accounts, quota, session tokens, role |
| `encodermatch_history_{slug}` | Per-client search history |
| `encodermatch_errors` | App error log |
| `encodermatch_feedback_{slug}` | Per-client thumbs up/down feedback |

### App Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python) |
| Database | DuckDB (in-process, reads S3 Parquet via httpfs or local .db) |
| Frontend | React (single JSX file, no build step) |
| AI Explanations | Claude API (claude-sonnet-4-20250514) |
| Auth | JWT |

### Key Files

```
encoder_appv2/
├── main.py                  # FastAPI app, API endpoints
├── db_load.py               # DuckDB connection, fetch_part, fetch_candidates, Posital lifecycle filter
├── matcher.py               # T1/T2/T3 scoring engine + pair scoring utility (match_pair)
├── matcher_config.json      # Scoring weights and T1 rules (config-driven, no code changes needed)
├── kubler_decoder.py        # Kübler real order code decoder (31 families)
├── epc_decoder.py           # EPC real order code decoder (28 entries, 25 families)
├── auth.py                  # JWT authentication, DynamoDB user/session/history management
├── serializers.py           # Response serialization (serialize_source, serialize_result)
├── url_lookup.py            # Sick/Posital product URL lookup
├── static/
│   ├── index.html           # App shell
│   └── EncoderMatch.jsx     # Full React frontend
├── refresh_silver_ecs.py    # Trigger Silver hot-reload on ECS via API
├── refresh_silver_local.py  # Trigger Silver hot-reload on local dev server
└── Dockerfile
```

---

## Deployment

### Build and Deploy to ECS

```bash
# 1. Authenticate to ECR
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin 155930759570.dkr.ecr.ap-south-1.amazonaws.com

# 2. Build
docker build -t encoder-crossref-app . --no-cache

# 3. Tag (always tag with a version in addition to latest)
VERSION_TAG="v$(date +%m_%d)"
docker tag encoder-crossref-app:latest 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encoder-crossref-app:latest
docker tag encoder-crossref-app:latest 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encoder-crossref-app:$VERSION_TAG

# 4. Push
docker push 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encoder-crossref-app:latest
docker push 155930759570.dkr.ecr.ap-south-1.amazonaws.com/encoder-crossref-app:$VERSION_TAG

# 5. Deploy
aws ecs update-service --cluster encoder-app-cluster --service encodermatch-service --force-new-deployment --region ap-south-1

# 6. Wait for stable
aws ecs wait services-stable --cluster encoder-app-cluster --services encodermatch-service --region ap-south-1
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in your config
cp config_claude.example.py config_claude.py
# Edit config_claude.py with your CLAUDE_API_KEY

# Run locally (reads Silver from S3 — requires AWS credentials)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Health check
curl http://localhost:8000/health/db
```

### Pair Scoring CLI (dev/testing)

```powershell
# Score one specific source vs one specific target part
python matcher.py `
  --part "8.7000.1242.2048" `
  --source kubler `
  --target posital `
  --target-part "UTD-IPT0Z-XXXXX-4A7S-PRD"
```

---

## Update History

### June 5, 2026 — Posital Lifecycle Filter, Pair Scoring, Bug Fixes

**`db_load.py`:**
- `_load_posital_exiting()`: reads Posital Bronze2 CSV from S3 at startup, returns frozenset of `Exiting` part numbers (7,492 of 18,742 total Posital rows)
- `POSITAL_EXITING_PARTS` module constant — filters Posital candidates in `fetch_candidates()` post-SQL
- Graceful fallback: if S3 read fails, logs warning and proceeds without filter

**`matcher.py`:**
- `match_pair()`: score one specific source vs one specific target, bypassing SQL candidate pool. Useful for validation and debugging
- `print_pair_result()`: T1/T2/T3 breakdown display with worst-first field ordering
- `--target-part` CLI flag activates pair mode
- `_safe_score()`, `_pair_fmt()` helpers

**`main.py` (BUG-F1):**
- Zero-score results now filtered: `combined = combined[combined["total_score"] > 0]`
- Proper `combined.empty` guard added before dedup/serialize block
- Fixes: encoders with empty spec fields (e.g. some Sick models) no longer surface 0% match cards

**`serializers.py` (BUG-A1):**
- `serialize_source()` now rounds float32 Parquet precision artifacts: `housing_diameter_mm` (1dp), `shaft_bore_diameter_mm` (3dp), `shock_resistance_ms2` (1dp), `vibration_resistance_ms2` (1dp), `shaft_load_radial_n` (1dp)

**`EncoderMatch.jsx`:**
- EPC prefix error message: specific guidance to omit `EPC-` prefix with example
- Reactive part number placeholder: changes per selected source manufacturer
- Shaft type labels: `hollow_blind` → `Hollow bore (blind)`, `hollow_thru` → `Hollow bore (through)`
- 429 daily limit: now shows error message via `setSearchError` instead of silently greying out
- Lika added to marketing copy
- "This period" → "Today" in quota display (3 occurrences)

### May 22, 2026 — EPC Real Order Code Decoder + ETL Fixes

- `epc_decoder.py`: full decoder for all 25 EPC Silver families (28 decoder entries), per-family position layouts, `shaft_type_by_code` (755A), `shaft_variant_map` (260), 6-digit CPR (TRP)
- `db_load.py`: EPC Stage 2b decode path, `_fetch_epc_by_decoded_spec` (5-attempt widening SQL)
- ETL: 15T/H and 25T/H sibling JSONs expanded — EPC Silver grows from 1,319,556 → **1,520,586 rows**
- Frontend: float32 rounding for source card display values

### May 21, 2026 — Kübler Real Order Code Decoder + Matcher Fixes

- `kubler_decoder.py`: full decoder for all 31 Kübler families, Path A and Path B
- Hollow encoder housing pre-filter fix (SQL filter skipped for hollow source)
- T1 `solid_only` condition on housing OD
- No-match reason system: structured `no_match_reasons` in API response + frontend `NoMatchBanner`
- ECS deployed as revision 4 (2 vCPU / 8GB)

---

## Known Issues / Deferred

| Issue | Impact | Fix |
|---|---|---|
| `output_voltage_class` T1 forbidden pairs uses `"low"`/`"high"` only | Dead code for EPC/Kübler/Sick vs Posital — SQL pre-filter masks it | Add TTL/universal/analog pairs to `matcher_config.json` |
| Kübler A020 `housing_diameter_mm` = null in Silver | Housing pre-filter skipped; T2 housing score = None | Populate 24.0mm in Silver ETL |
| Elastic IP not assigned | ECS public IP changes on every Fargate restart | Assign Elastic IP to ECS service |
| BUG-F2: ~2.3s DynamoDB latency per search | Sequential DynamoDB calls in match flow | Make `add_history` fire-and-forget |
| Posital `is_discontinued`/`replaced_by` not in Silver | Exiting products partially filtered; UCD→UTD replacement not surfaced | Re-scrape Posital with these fields, add to Silver schema |
| `_available_mfrs` field names inconsistent post-refresh | Database tab may misrender after Refresh Data | Align `id/display/count` vs `id/label/rows` |