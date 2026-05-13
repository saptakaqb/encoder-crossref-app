"""
auth.py
=======
JWT authentication and DynamoDB user operations for EncoderMatch.

Changes from v1:
  - Daily search limits (resets UTC midnight, not lifetime counter)
  - Single active session enforcement (new login invalidates previous)
  - SES notification placeholder when user hits daily limit

AQB Solutions | May 2026
"""

import hashlib
import os
import threading
from datetime import datetime, timedelta
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# ── Config ─────────────────────────────────────────────────────────────────
SECRET_KEY    = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-before-prod")
ALGORITHM     = "HS256"
TOKEN_EXPIRE  = int(os.environ.get("TOKEN_EXPIRE_HOURS", 24))
REGION        = os.environ.get("AWS_REGION", "ap-south-1")
USERS_TABLE   = os.environ.get("DYNAMO_USERS_TABLE",   "encodermatch_users")
HISTORY_TABLE = os.environ.get("DYNAMO_HISTORY_TABLE", "encodermatch_history")
SES_SENDER    = os.environ.get("SES_SENDER_EMAIL", "")  # set once SES verified

security = HTTPBearer()

# ── DynamoDB client ────────────────────────────────────────────────────────
_dynamo = None

def get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = boto3.resource("dynamodb", region_name=REGION)
    return _dynamo


# ── Helpers ────────────────────────────────────────────────────────────────

def _today_utc() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


# ── Password ───────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = "encodermatch_2026"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

def verify_password(plain: str, hashed: str) -> bool:
    return hash_password(plain) == hashed


# ── JWT ────────────────────────────────────────────────────────────────────

def create_token(email: str, session_id: str) -> str:
    """
    JWT now embeds session_id (sid claim).
    Validated against DynamoDB active_session_id on every authenticated request.
    New login overwrites active_session_id → old tokens get 401.
    """
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE)
    return jwt.encode(
        {"sub": email, "sid": session_id, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

def decode_token(token: str) -> tuple[Optional[str], Optional[str]]:
    """Returns (email, session_id). Both None on any error."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub"), payload.get("sid")
    except JWTError:
        return None, None


# ── Session management ─────────────────────────────────────────────────────

def store_session(email: str, session_id: str) -> None:
    """
    Write active_session_id to user record at login.
    Previous session_id is overwritten — that session gets 401 on next request.
    """
    table = get_dynamo().Table(USERS_TABLE)
    table.update_item(
        Key={"userId": email},
        UpdateExpression="SET active_session_id = :sid, last_login = :ts",
        ExpressionAttributeValues={
            ":sid": session_id,
            ":ts":  datetime.utcnow().isoformat(),
        },
    )


# ── DynamoDB user operations ───────────────────────────────────────────────

def get_user(email: str) -> Optional[dict]:
    table = get_dynamo().Table(USERS_TABLE)
    resp  = table.get_item(Key={"userId": email})
    return resp.get("Item")


def authenticate_user(email: str, password: str) -> Optional[dict]:
    user = get_user(email)
    if not user:
        return None
    if not verify_password(password, user.get("password_hash", "")):
        return None
    return user


def _notify_limit_reached_async(user: dict) -> None:
    """
    Fire-and-forget: log + optional SES when user hits daily limit.
    TODO: Uncomment SES block once:
      1. SES sender email verified in ap-south-1
      2. SES production access granted (out of sandbox)
      3. Fargate task role has ses:SendEmail permission
    """
    def _send():
        name   = user.get("name", user.get("userId", "Unknown"))
        email  = user.get("userId", "")
        client = user.get("client", "")
        limit  = user.get("searches_limit", 0)
        admin  = user.get("admin_email", "")
        today  = _today_utc()
        print(
            f"[DAILY LIMIT] {name} ({email}) · client={client} "
            f"hit daily limit of {limit} on {today}"
        )
        # ── SES (uncomment when ready) ──────────────────────────────────
        # if not SES_SENDER:
        #     return
        # try:
        #     ses = boto3.client("ses", region_name=REGION)
        #     ses.send_email(
        #         Source=SES_SENDER,
        #         Destination={"ToAddresses": [admin]},
        #         Message={
        #             "Subject": {"Data": f"[EncoderMatch] {name} hit daily limit"},
        #             "Body": {"Text": {"Data": (
        #                 f"User: {name} ({email})\n"
        #                 f"Client: {client}\n"
        #                 f"Daily limit: {limit}\n"
        #                 f"Date: {today}\n\n"
        #                 f"Adjust in the admin console."
        #             )}},
        #         },
        #     )
        # except Exception as e:
        #     print(f"[SES] Notification failed: {e}")
    threading.Thread(target=_send, daemon=True).start()


def increment_search_count(email: str) -> dict:
    """
    Daily search limit — resets at UTC midnight.

    1. Read user record.
    2. If last_search_date != today → new day, reset counter to 1 atomically.
    3. If same day and used >= limit → 403 + async notification.
    4. Conditional increment (guards concurrent requests with DynamoDB condition).

    Returns: updated user record (ALL_NEW).
    Raises: HTTPException 403 on limit or lock.
    """
    table = get_dynamo().Table(USERS_TABLE)
    user  = get_user(email)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.get("status") == "locked":
        raise HTTPException(
            status_code=403,
            detail=f"Account locked. Contact {user.get('admin_email', 'your administrator')}.",
        )
    if user.get("status") == "invited":
        raise HTTPException(status_code=403, detail="Account not yet activated.")

    today      = _today_utc()
    last_date  = user.get("last_search_date", "")
    limit      = int(user.get("searches_limit", 100))
    used_today = int(user.get("searches_used_today", 0)) if last_date == today else 0

    if used_today >= limit:
        _notify_limit_reached_async(user)
        raise HTTPException(
            status_code=403,
            detail=(
                f"Daily search limit of {limit} reached. "
                f"Resets at midnight UTC. "
                f"Contact {user.get('admin_email', 'your administrator')} to adjust."
            ),
        )

    try:
        if last_date != today:
            # New day — reset to 1 and stamp date
            resp = table.update_item(
                Key={"userId": email},
                UpdateExpression=(
                    "SET searches_used_today = :one, last_search_date = :today"
                ),
                ExpressionAttributeValues={":one": 1, ":today": today},
                ReturnValues="ALL_NEW",
            )
        else:
            # Same day — atomic conditional increment
            resp = table.update_item(
                Key={"userId": email},
                UpdateExpression="ADD searches_used_today :one",
                ConditionExpression="searches_used_today < :limit",
                ExpressionAttributeValues={":one": 1, ":limit": limit},
                ReturnValues="ALL_NEW",
            )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            _notify_limit_reached_async(user)
            raise HTTPException(
                status_code=403,
                detail=f"Daily search limit of {limit} reached. Resets at midnight UTC.",
            )
        raise

    return resp["Attributes"]


def add_history(email: str, record: dict) -> None:
    table = get_dynamo().Table(HISTORY_TABLE)
    table.put_item(Item={
        "userId":    email,
        "timestamp": datetime.utcnow().isoformat(),
        **record,
    })


def get_history(email: str, limit: int = 20) -> list:
    table = get_dynamo().Table(HISTORY_TABLE)
    resp  = table.query(
        KeyConditionExpression=Key("userId").eq(email),
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])


def get_all_users_for_client(client: str) -> list:
    table = get_dynamo().Table(USERS_TABLE)
    resp  = table.scan(
        FilterExpression="client = :c",
        ExpressionAttributeValues={":c": client},
    )
    return resp.get("Items", [])


def update_user(email: str, updates: dict) -> None:
    table = get_dynamo().Table(USERS_TABLE)
    expressions = []
    attr_names  = {}
    attr_values = {}
    for i, (key, val) in enumerate(updates.items()):
        ph   = f":v{i}"
        nph  = f"#k{i}"
        expressions.append(f"{nph} = {ph}")
        attr_names[nph]  = key
        attr_values[ph]  = val
    table.update_item(
        Key={"userId": email},
        UpdateExpression="SET " + ", ".join(expressions),
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=attr_values,
    )


# ── FastAPI dependencies ────────────────────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    1. Decode JWT → (email, session_id).
    2. Look up user in DynamoDB.
    3. Compare token's session_id against active_session_id in DB.
       Mismatch = another login has superseded this session → 401.
    """
    token = credentials.credentials
    email, session_id = decode_token(token)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user(email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Single-session guard (skip for legacy tokens without sid claim)
    if session_id and user.get("active_session_id") and \
            user["active_session_id"] != session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session superseded — please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def delete_user(email: str) -> None:
    """Permanently delete a user record. Admin use only."""
    table = get_dynamo().Table(USERS_TABLE)
    table.delete_item(Key={"userId": email})


def get_all_users() -> list:
    """Scan entire users table. Superadmin use only."""
    table = get_dynamo().Table(USERS_TABLE)
    resp  = table.scan()
    return resp.get("Items", [])


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("clientadmin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_superadmin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user
