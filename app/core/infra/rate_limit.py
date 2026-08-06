"""
In-memory sliding-window rate limiter for public / unauthenticated endpoints.

Limits are per gunicorn worker (not global across -w N). Good enough for
abuse dampening on the public login map; do not treat as a hard quota.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from fastapi import HTTPException, Request, status

from ...config import settings

_lock = threading.Lock()
_buckets: Dict[str, Deque[float]] = defaultdict(deque)


def client_ip_from_request(request: Request) -> str:
    """
    Resolve client IP for rate limiting.

    When ``settings.trusted_proxy_count`` is 0, use ``request.client.host``.
    When > 0, take the rightmost trusted hop from ``X-Forwarded-For``.
    """
    trusted = max(0, int(getattr(settings, "trusted_proxy_count", 0) or 0))
    if trusted > 0:
        xff = request.headers.get("x-forwarded-for") or ""
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            # Rightmost entry is the nearest proxy; count hops from the right.
            idx = max(0, len(parts) - trusted)
            return parts[idx]
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def check_rate_limit(
    *,
    key: str,
    max_requests: int,
    window_seconds: float,
) -> Tuple[bool, Optional[float]]:
    """
    Record a hit for ``key`` and return ``(allowed, retry_after_seconds)``.

    When not allowed, ``retry_after_seconds`` is the wait until the oldest
    hit in the window expires.
    """
    if max_requests <= 0 or window_seconds <= 0:
        return True, None

    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        bucket = _buckets[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= max_requests:
            retry_after = max(0.0, window_seconds - (now - bucket[0]))
            return False, retry_after
        bucket.append(now)
        return True, None


def enforce_rate_limit(
    request: Request,
    *,
    bucket: str,
    max_requests: int,
    window_seconds: float,
) -> None:
    """Raise HTTP 429 when the IP exceeds the limit for ``bucket``."""
    ip = client_ip_from_request(request)
    key = f"{bucket}:{ip}"
    allowed, retry_after = check_rate_limit(
        key=key,
        max_requests=max_requests,
        window_seconds=window_seconds,
    )
    if allowed:
        return
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = str(max(1, int(retry_after + 0.999)))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded. Please try again later.",
        headers=headers or None,
    )


def reset_rate_limits_for_tests() -> None:
    """Clear all buckets (test helper)."""
    with _lock:
        _buckets.clear()
