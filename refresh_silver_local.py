"""
test_refresh_silver.py
Quick smoke test for POST /api/admin/refresh-silver.
Run from encoder_app/ folder while uvicorn is running locally.

Usage:
    python test_refresh_silver.py
    python test_refresh_silver.py --url https://your-ecs-url.com
"""
import argparse, sys
import requests

BASE_URL  = "http://127.0.0.1:8000"
EMAIL     = "saptak.s@aqbsolutions.com"   # superadmin
PASSWORD  = "saptak@admin1111"           # fill in

parser = argparse.ArgumentParser()
parser.add_argument("--url", default=BASE_URL)
parser.add_argument("--email", default=EMAIL)
parser.add_argument("--password", default=PASSWORD)
args = parser.parse_args()

base = args.url.rstrip("/")

# ── Step 1: login ─────────────────────────────────────────────────────────────
print(f"Logging in as {args.email} ...")
r = requests.post(f"{base}/api/auth/login",
                  json={"email": args.email, "password": args.password})
if r.status_code != 200:
    print(f"Login failed ({r.status_code}): {r.text}")
    sys.exit(1)

token = r.json().get("access_token") or r.json().get("token")
print(f"  Token acquired.")

# ── Step 2: hit the reload endpoint ───────────────────────────────────────────
print("\nPOST /api/admin/refresh-silver ...")
r = requests.post(
    f"{base}/api/admin/refresh-silver",
    headers={"Authorization": f"Bearer {token}"},
    timeout=120,   # reload can take ~30s
)

print(f"  Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    print(f"  Status     : {data.get('status')}")
    print(f"  Total rows : {data.get('total_rows', 0):,}")
    print(f"  Elapsed    : {data.get('elapsed_s')}s")
    print(f"  Mfrs live  : {data.get('manufacturers')}")
    print("\nPASS -- reload endpoint working.")
elif r.status_code == 409:
    print("  409 Conflict: reload already in progress (expected if called twice fast).")
else:
    print(f"  FAIL: {r.text}")
    sys.exit(1)