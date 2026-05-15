# EncoderMatch — FastAPI + React frontend
# Serves API at /api/* and frontend at /

FROM python:3.11-slim

WORKDIR /app

# ── System deps ────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Pipeline scripts ───────────────────────────────────────────────────────
COPY main.py auth.py serializers.py url_lookup.py ./
COPY matcher.py db_load.py matcher_config.json ./

# ── URL lookup data ────────────────────────────────────────────────────────
# Sick URLs are SKU-level — bundled with the image (7K rows, ~1MB)
# EPC and Kübler URLs are derived programmatically — no file needed
COPY sick_urls.csv ./
COPY posital_urls.csv ./

# ── Frontend static files ──────────────────────────────────────────────────
RUN mkdir -p static
COPY index.html static/index.html
COPY EncoderMatch.jsx static/EncoderMatch.jsx
COPY static/logo2.webp static/logo2.webp

# ── Environment defaults (override at runtime) ─────────────────────────────
ENV AWS_REGION=ap-south-1
ENV DYNAMO_USERS_TABLE=encodermatch_users
ENV DYNAMO_HISTORY_TABLE=encodermatch_history
ENV CORS_ORIGINS=http://localhost:8080,http://localhost:3000
ENV JWT_SECRET_KEY=change-this-before-prod
ENV S3_BUCKET=aqb-data-analytics-demo
ENV S3_ROOT=encoder_pipeline

# ── Port ───────────────────────────────────────────────────────────────────
EXPOSE 8000

# ── Health check for ECS ───────────────────────────────────────────────────
# start-period covers Silver download from S3 at startup (boto3, same-region).
# Current Silver ~142MB → ~10s download. Budget 120s for headroom + future growth.
#
# SCALING NOTE — adjust start-period as Silver grows:
#   ~142MB today  →  start-period=120s   (current)
#   ~500MB        →  start-period=180s
#   ~1GB          →  start-period=300s
#
# When Silver reaches ~500MB–1GB, switch to background download with httpfs
# fallback during startup (app becomes available immediately, switches to local
# files once download completes). See db_load.py download_silver_locally().
#
# When Silver reaches ~2–5GB, mount EFS to Fargate for persistent storage
# across deployments — only delta files downloaded on redeploy, near-instant startup.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# ── Start ──────────────────────────────────────────────────────────────────
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
