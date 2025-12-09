"""Authentication helpers for admin login and session handling."""

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import bcrypt

SESSION_TTL_SECONDS = 60 * 60 * 4


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def issue_session_token(username: str, password_hash: str, ttl_seconds: int = SESSION_TTL_SECONDS) -> str:
    """Create a signed session token with an expiry bound to the username."""
    expires = int((datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).timestamp())
    payload = f"{username}:{expires}"
    signature = hmac.new(
        password_hash.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def validate_session_token(token: str, username: str, password_hash: str) -> bool:
    """Validate a signed session token for the given username."""
    parts = token.split(":")
    if len(parts) != 3:
        return False
    token_user, expires_raw, signature = parts
    if token_user != username:
        return False
    try:
        expires = int(expires_raw)
    except ValueError:
        return False
    if expires < int(datetime.now(timezone.utc).timestamp()):
        return False
    payload = f"{token_user}:{expires}"
    expected = hmac.new(
        password_hash.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def parse_basic_credentials(value: str) -> Optional[Tuple[str, str]]:
    """Decode Basic auth style credentials (header or token)."""
    candidate = value.strip()
    if candidate.lower().startswith("basic "):
        candidate = candidate[6:].strip()
    try:
        decoded = base64.b64decode(candidate).decode("utf-8")
    except Exception:
        return None
    if ":" not in decoded:
        return None
    username, password = decoded.split(":", 1)
    return username, password
