"""Sliding JWT refresh with hard session cap."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt

from app.config import settings
from app.core.auth.security import (
    create_access_token,
    decode_access_token,
    decode_access_token_payload,
    refresh_access_token,
)


def test_create_access_token_includes_auth_time():
    token = create_access_token(data={"sub": "pilot", "role": "pilot"})
    payload = decode_access_token_payload(token)
    assert payload is not None
    assert payload["sub"] == "pilot"
    assert "auth_time" in payload
    assert "exp" in payload
    data = decode_access_token(token)
    assert data is not None
    assert data.username == "pilot"
    assert data.auth_time == payload["auth_time"]


def test_refresh_extends_exp_within_hard_cap():
    auth_time = datetime.now(timezone.utc) - timedelta(hours=1)
    token = create_access_token(
        data={"sub": "pilot", "role": "pilot"},
        expires_delta=timedelta(minutes=5),
        auth_time=auth_time,
    )
    old_payload = decode_access_token_payload(token)
    assert old_payload is not None

    refreshed = refresh_access_token(token)
    assert refreshed is not None
    new_token, cookie_max_age = refreshed
    assert cookie_max_age > 0
    new_payload = decode_access_token_payload(new_token)
    assert new_payload is not None
    assert new_payload["auth_time"] == old_payload["auth_time"]
    assert new_payload["exp"] > old_payload["exp"]


def test_refresh_rejected_past_hard_cap(monkeypatch):
    monkeypatch.setattr(settings, "jwt_session_max_minutes", 60)
    monkeypatch.setattr(
        "app.core.auth.security.SESSION_MAX_MINUTES", 60, raising=False
    )
    # Re-bind the module constant used by refresh_access_token
    import app.core.auth.security as security_mod

    monkeypatch.setattr(security_mod, "SESSION_MAX_MINUTES", 60)

    auth_time = datetime.now(timezone.utc) - timedelta(hours=2)
    # Issue a token whose sliding window still looks valid but auth_time is past max.
    token = jwt.encode(
        {
            "sub": "pilot",
            "role": "pilot",
            "auth_time": int(auth_time.timestamp()),
            "iat": int(auth_time.timestamp()),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    assert refresh_access_token(token) is None


def test_refresh_legacy_token_without_auth_time():
    # Pre-sliding tokens only have exp (and optionally iat from jose defaults).
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "pilot",
            "role": "pilot",
            "iat": int((now - timedelta(hours=1)).timestamp()),
            "exp": now + timedelta(hours=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    refreshed = refresh_access_token(token)
    assert refreshed is not None
    new_token, _max_age = refreshed
    payload = decode_access_token_payload(new_token)
    assert payload is not None
    assert "auth_time" in payload
