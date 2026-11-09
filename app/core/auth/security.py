from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.config import \
    settings  # Assuming your settings are accessible like this

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = settings.jwt_algorithm
SECRET_KEY = settings.jwt_secret_key
ACCESS_TOKEN_EXPIRE_MINUTES = settings.jwt_access_token_expire_minutes
SESSION_MAX_MINUTES = settings.jwt_session_max_minutes


class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None
    auth_time: Optional[int] = None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def _as_utc_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    *,
    auth_time: Optional[datetime] = None,
) -> str:
    """Issue a JWT. ``auth_time`` is the original login instant (Unix seconds)."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    auth_dt = _as_utc_datetime(auth_time) or now
    auth_unix = int(auth_dt.timestamp())

    if expires_delta:
        sliding_expire = now + expires_delta
    else:
        sliding_expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    hard_cap = auth_dt + timedelta(minutes=SESSION_MAX_MINUTES)
    expire = min(sliding_expire, hard_cap)
    if expire <= now:
        # Already at/past hard cap — still issue a short-lived token so the
        # client can detect expiry cleanly on the next request.
        expire = now + timedelta(seconds=1)

    to_encode.update(
        {"exp": expire, "auth_time": auth_unix, "iat": int(now.timestamp())}
    )
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[TokenData]:
    """Decodes a JWT access token and returns TokenData, or None if invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        role: Optional[str] = payload.get("role")
        if username is None or role is None:
            return None
        auth_time_raw = payload.get("auth_time")
        auth_time = int(auth_time_raw) if auth_time_raw is not None else None
        return TokenData(username=username, role=role, auth_time=auth_time)
    except JWTError as e:
        # Log the error for debugging
        print(f"JWT decode error: {e}")
        return None


def decode_access_token_payload(token: str) -> Optional[Dict[str, Any]]:
    """Return full JWT payload if valid; None if expired/invalid."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def refresh_access_token(token: str) -> Optional[Tuple[str, int]]:
    """
    Reissue a token with a slid expiry, capped by auth_time + session max.

    Returns (new_token, cookie_max_age_seconds) or None if the token cannot be refreshed.
    Legacy tokens without auth_time use iat (preferred) or current exp as the login anchor.
    """
    payload = decode_access_token_payload(token)
    if not payload:
        return None
    username = payload.get("sub")
    role = payload.get("role")
    if not username or not role:
        return None

    now = datetime.now(timezone.utc)
    auth_raw = payload.get("auth_time")
    if auth_raw is None:
        auth_raw = payload.get("iat")
    if auth_raw is None:
        # Pre-sliding tokens: treat remaining exp window as the original login
        # window ending at exp (auth_time ≈ exp - access lifetime).
        exp_dt = _as_utc_datetime(payload.get("exp"))
        if exp_dt is None:
            return None
        auth_dt = exp_dt - timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        auth_dt = _as_utc_datetime(auth_raw)
        if auth_dt is None:
            return None

    hard_cap = auth_dt + timedelta(minutes=SESSION_MAX_MINUTES)
    if now >= hard_cap:
        return None

    new_token = create_access_token(
        data={"sub": username, "role": role},
        auth_time=auth_dt,
    )
    remaining_seconds = max(1, int((hard_cap - now).total_seconds()))
    cookie_max_age = min(
        settings.jwt_access_token_expire_minutes * 60,
        remaining_seconds,
    )
    return new_token, cookie_max_age
