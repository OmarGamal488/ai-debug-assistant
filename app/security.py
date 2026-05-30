"""security.py — Password hashing and signed session-cookie utilities.

All session state lives in a tamper-proof signed cookie (itsdangerous
URLSafeTimedSerializer). No session table is required; the user_id is
recovered from the cookie on each request.
"""

import os

import itsdangerous
from dotenv import load_dotenv
from fastapi import Request
from passlib.context import CryptContext
from sqlmodel import Session, select

load_dotenv()

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*."""
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Return True if *password* matches *hashed*."""
    return pwd_context.verify(password, hashed)


# ---------------------------------------------------------------------------
# Signed session cookies
# ---------------------------------------------------------------------------

_SECRET_KEY: str = os.getenv("SECRET_KEY", "")
if not _SECRET_KEY or len(_SECRET_KEY) < 32:
    raise RuntimeError(
        "SECRET_KEY env var must be set to a strong random value (>=32 chars). "
        'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
    )

serializer = itsdangerous.URLSafeTimedSerializer(_SECRET_KEY)

SESSION_COOKIE = "session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days in seconds


def make_session_token(user_id: int) -> str:
    """Serialize *user_id* into a tamper-proof, time-stamped cookie value."""
    return serializer.dumps(user_id)


def read_session_token(token: str) -> int | None:
    """Decode *token* and return the user_id, or None if invalid/expired."""
    try:
        value = serializer.loads(token, max_age=COOKIE_MAX_AGE)
        return int(value)
    except (
        itsdangerous.BadSignature,
        itsdangerous.SignatureExpired,
        Exception,
    ):
        return None


def get_current_user(request: Request, session: Session):
    """Return the authenticated User for this request, or None.

    Reads the signed session cookie, verifies it, and looks up the User row.
    This is a plain helper — NOT a FastAPI Depends — so that protected routes
    can redirect to /login instead of raising a 401.
    """
    # Import here to avoid circular imports (models imports nothing from here)
    from app.models import User  # noqa: PLC0415

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None

    user_id = read_session_token(token)
    if user_id is None:
        return None

    user = session.exec(select(User).where(User.id == user_id)).first()
    return user
