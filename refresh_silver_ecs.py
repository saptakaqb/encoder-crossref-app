"""
refresh_silver_ecs.py
Discovers the running ECS task's public IP automatically,
then calls POST /api/admin/refresh-silver.

Usage:
    python refresh_silver_ecs.py
    python refresh_silver_ecs.py --dry-run   # just prints the discovered IP

Once an Elastic IP is assigned, replace ECS_URL below with the fixed URL
and skip the IP discovery block entirely.
"""
import argparse, sys, time
import boto3, requests

# ── Config ────────────────────────────────────────────────────────────────────
ECS_CLUSTER   = "encoder-app-cluster"
ECS_SERVICE   = "encodermatch-service"
AWS_REGION    = "ap-south-1"
APP_PORT      = 8000

EMAIL         = "saptak.s@aqbsolutions.com"
PASSWORD      = "saptak@admin1111"          # fill in
# ──────────────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true",
                    help="Discover IP and print URL only, don't call endpoint")
args = parser.parse_args()


# ── Step 1: discover ECS task public IP ───────────────────────────────────────
def get_ecs_public_ip() -> str:
    ecs = boto3.client("ecs", region_name=AWS_REGION)
    ec2 = boto3.client("ec2",  region_name=AWS_REGION)

    # Get running task ARN
    tasks = ecs.list_tasks(cluster=ECS_CLUSTER, serviceName=ECS_SERVICE,
                           desiredStatus="RUNNING")["taskArns"]
    if not tasks:
        raise RuntimeError("No running tasks found in service — is ECS deployed?")

    # Describe task to get ENI attachment
    detail = ecs.describe_tasks(cluster=ECS_CLUSTER, tasks=[tasks[0]])["tasks"][0]
    eni_id = None
    for att in detail.get("attachments", []):
        for kv in att.get("details", []):
            if kv["name"] == "networkInterfaceId":
                eni_id = kv["value"]
                break

    if not eni_id:
        raise RuntimeError("Could not find ENI on task — check task network mode")

    # Get public IP from ENI
    eni = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    ip  = eni["NetworkInterfaces"][0]["Association"]["PublicIp"]
    return ip


print("Discovering ECS task public IP ...")
try:
    ip      = get_ecs_public_ip()
    base    = f"http://{ip}:{APP_PORT}"
    print(f"  Task IP : {ip}")
    print(f"  Base URL: {base}")
except Exception as e:
    print(f"  ERROR: {e}")
    sys.exit(1)

if args.dry_run:
    print("\n--dry-run: stopping here.")
    sys.exit(0)


# ── Step 2: login ─────────────────────────────────────────────────────────────
print(f"\nLogging in as {EMAIL} ...")
try:
    r = requests.post(f"{base}/api/auth/login",
                      json={"email": EMAIL, "password": PASSWORD},
                      timeout=15)
    if r.status_code != 200:
        print(f"  Login failed ({r.status_code}): {r.text}")
        sys.exit(1)
    token = r.json().get("access_token") or r.json().get("token")
    print("  Token acquired.")
except requests.exceptions.ConnectionError:
    print(f"  Cannot reach {base} — check security group allows port {APP_PORT}")
    sys.exit(1)


# ── Step 3: call refresh-silver ───────────────────────────────────────────────
print("\nPOST /api/admin/refresh-silver ...")
print("  (this takes ~30s if Silver data changed on S3, ~3s if unchanged)")
t0 = time.time()

r = requests.post(
    f"{base}/api/admin/refresh-silver",
    headers={"Authorization": f"Bearer {token}"},
    timeout=120,
)

elapsed = round(time.time() - t0, 1)
print(f"  HTTP {r.status_code}  ({elapsed}s)")

if r.status_code == 200:
    data = r.json()
    print(f"  Status     : {data.get('status')}")
    print(f"  Total rows : {data.get('total_rows', 0):,}")
    print(f"  Elapsed    : {data.get('elapsed_s')}s")
    print(f"  Mfrs live  : {data.get('manufacturers')}")
    print("\nPASS -- ECS reload successful.")
elif r.status_code == 409:
    print("  409: reload already in progress.")
else:
    print(f"  FAIL: {r.text}")
    sys.exit(1)