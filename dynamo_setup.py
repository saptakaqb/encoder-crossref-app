"""
dynamo_setup.py
===============
Run once to create DynamoDB tables and seed AQB admin accounts.
Regular users are created through the admin console.

    python dynamo_setup.py

Safe to re-run — skips table creation if tables already exist,
updates existing accounts if already seeded.

AQB Solutions | May 2026
"""

import boto3
import hashlib
import os
from datetime import datetime

REGION        = os.environ.get("AWS_REGION",           "ap-south-1")
USERS_TABLE   = os.environ.get("DYNAMO_USERS_TABLE",   "encodermatch_users")
HISTORY_TABLE = os.environ.get("DYNAMO_HISTORY_TABLE", "encodermatch_history")
ERRORS_TABLE  = os.environ.get("DYNAMO_ERRORS_TABLE",  "encodermatch_errors")

def hash_password(password: str) -> str:
    salt = "encodermatch_2026"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

def create_tables(dynamo):
    existing = [t.name for t in dynamo.tables.all()]

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

    if HISTORY_TABLE not in existing:
        dynamo.create_table(
            TableName=HISTORY_TABLE,
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
        print(f"  Created table: {HISTORY_TABLE}")
    else:
        print(f"  Table already exists: {HISTORY_TABLE}")

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

    for name in [USERS_TABLE, HISTORY_TABLE, ERRORS_TABLE]:
        dynamo.Table(name).wait_until_exists()
        print(f"  Table active: {name}")


ALL_MANUFACTURERS = ["kubler", "epc", "sick", "posital"]

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
    {
        "userId":              "test@posital.com",
        "email":               "test@posital.com",
        "name":                "Posital Tester",
        "password_hash":       hash_password("posital@test123"),
        "role":                "enduser",
        "client":              "posital",
        "searches_used_today": 0,
        "last_search_date":    "",
        "searches_limit":      5,
        "allowed_sources":     ["kubler", "epc", "sick"],
        "allowed_targets":     ["posital"],
        "direction":           "source_only",
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
    print("\nAll other users to be created via the admin console.")


if __name__ == "__main__":
    main()