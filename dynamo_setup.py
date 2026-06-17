"""
dynamo_setup.py
===============
Run ONCE on a fresh environment to create DynamoDB tables and seed AQB admin accounts.
Regular users are created through the admin console.

    python dynamo_setup.py

!! DO NOT RE-RUN ON A LIVE SYSTEM !!
seed_users() calls put_item() unconditionally — it will overwrite live admin records
and reset passwords to the plaintext values hardcoded in this script.
Table creation is idempotent (skips existing tables), but user seeding is NOT.

Per-client history and feedback tables (e.g. encodermatch_history_posital,
encodermatch_feedback_posital) are created dynamically when users are created
via the admin console. The _admin and _aqb_solutions tables are created here at setup.

AQB Solutions | June 2026
"""

import boto3
import hashlib
import os
import re
from datetime import datetime

REGION       = os.environ.get("AWS_REGION",          "ap-south-1")
USERS_TABLE  = os.environ.get("DYNAMO_USERS_TABLE",  "encodermatch_users")
ERRORS_TABLE = os.environ.get("DYNAMO_ERRORS_TABLE", "encodermatch_errors")

# Static admin tables — always created at setup
ADMIN_HISTORY_TABLE  = "encodermatch_history_admin"
ADMIN_FEEDBACK_TABLE = "encodermatch_feedback_admin"


def hash_password(password: str) -> str:
    salt = "encodermatch_2026"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def client_slug(client: str) -> str:
    """Convert a client name to a safe DynamoDB table suffix.
    e.g. 'Posital (FRABA)' → 'posital_fraba', 'AQB Solutions' → 'aqb_solutions'
    """
    slug = re.sub(r"[^a-z0-9]", "_", client.lower().strip())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "unknown"


def _make_history_table(dynamo, table_name: str, existing: list) -> None:
    if table_name in existing:
        print(f"  Table already exists: {table_name}")
        return
    dynamo.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "userId",    "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "userId",    "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    print(f"  Created table: {table_name}")


def _make_feedback_table(dynamo, table_name: str, existing: list) -> None:
    if table_name in existing:
        print(f"  Table already exists: {table_name}")
        return
    dynamo.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "userId", "KeyType": "HASH"},
            {"AttributeName": "sk",     "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "userId", "AttributeType": "S"},
            {"AttributeName": "sk",     "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    print(f"  Created table: {table_name}")


def create_tables(dynamo):
    existing = [t.name for t in dynamo.tables.all()]

    # ── Shared tables (no manufacturer split) ─────────────────────────────
    if USERS_TABLE not in existing:
        dynamo.create_table(
            TableName=USERS_TABLE,
            KeySchema=[{"AttributeName": "userId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "userId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"  Created table: {USERS_TABLE}")
    else:
        print(f"  Table already exists: {USERS_TABLE}")

    if ERRORS_TABLE not in existing:
        dynamo.create_table(
            TableName=ERRORS_TABLE,
            KeySchema=[
                {"AttributeName": "userId",    "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "userId",    "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"  Created table: {ERRORS_TABLE}")
    else:
        print(f"  Table already exists: {ERRORS_TABLE}")

    # ── Admin tables (AQB internal searches) ──────────────────────────────
    _make_history_table(dynamo, ADMIN_HISTORY_TABLE, existing)
    _make_feedback_table(dynamo, ADMIN_FEEDBACK_TABLE, existing)

    # Wait for all tables to be active
    core_tables = [USERS_TABLE, ERRORS_TABLE, ADMIN_HISTORY_TABLE, ADMIN_FEEDBACK_TABLE]
    for name in core_tables:
        dynamo.Table(name).wait_until_exists()
        print(f"  Table active: {name}")


ALL_MANUFACTURERS = ["kubler", "epc", "sick", "posital", "lika"]

SEED_USERS = [
    {
        "userId":              "akshay.b@aqbsolutions.com",
        "email":               "akshay.b@aqbsolutions.com",
        "name":                "Akshay B",
        "password_hash":       hash_password("akshay@admin9999"),
        "role":                "superadmin",
        "client":              "AQB Solutions",
        "searches_used_today": 0,
        "last_search_date":    "",
        "searches_limit":      99999,
        "allowed_sources":     ALL_MANUFACTURERS,
        "allowed_targets":     ALL_MANUFACTURERS,
        "direction":           "bidirectional",
        "status":              "active",
        "admin_email":         "akshay.b@aqbsolutions.com",
        "created_at":          datetime.utcnow().isoformat(),
    },
    {
        "userId":              "saptak.s@aqbsolutions.com",
        "email":               "saptak.s@aqbsolutions.com",
        "name":                "Saptak S",
        "password_hash":       hash_password("saptak@admin1111"),
        "role":                "superadmin",
        "client":              "AQB Solutions",
        "searches_used_today": 0,
        "last_search_date":    "",
        "searches_limit":      99999,
        "allowed_sources":     ALL_MANUFACTURERS,
        "allowed_targets":     ALL_MANUFACTURERS,
        "direction":           "bidirectional",
        "status":              "active",
        "admin_email":         "saptak.s@aqbsolutions.com",
        "created_at":          datetime.utcnow().isoformat(),
    },
]


def seed_users(dynamo):
    table = dynamo.Table(USERS_TABLE)
    for user in SEED_USERS:
        table.put_item(Item=user)
        print(f"  Seeded: {user['email']} ({user['role']})")


def main():
    print(f"Connecting to DynamoDB in {REGION} ...")
    dynamo = boto3.resource("dynamodb", region_name=REGION)

    print("\nCreating tables ...")
    create_tables(dynamo)

    print("\nSeeding admin accounts ...")
    seed_users(dynamo)

    print("\nSetup complete.")
    print("\nAdmin credentials:")
    print("  akshay.b@aqbsolutions.com  / akshay@admin9999")
    print("  saptak.s@aqbsolutions.com  / saptak@admin1111")
    print("\nPer-manufacturer tables (e.g. encodermatch_history_posital)")
    print("are created automatically when end users are added via the admin console.")


if __name__ == "__main__":
    main()