from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from gitforce.app.config.settings import get_settings


class TokenBucket:
    """Simple in-memory token bucket used by the rate limiter."""

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_per_second = refill_per_second
        self.last = time.monotonic()

    def take(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last
        self.tokens = min(
            self.capacity,
            self.tokens + elapsed * self.refill_per_second,
        )
        self.last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiting per client IP (Phase 12). Returns 429
    with a Retry-After header when a client exceeds its budget."""

    _buckets: dict[str, TokenBucket] = {}
    _max_buckets = 10_000

    def _settings(self):
        settings = get_settings()
        return {
            "enabled": settings.rate_limit_enabled,
            "capacity": settings.rate_limit_burst,
            "refill": settings.rate_limit_requests_per_minute / 60.0,
        }

    def _bucket_for(self, client_ip: str, capacity: int, refill: float) -> TokenBucket:
        bucket = self._buckets.get(client_ip)
        if bucket is None:
            if len(self._buckets) >= self._max_buckets:
                # Evict oldest entry to bound memory.
                self._buckets.pop(next(iter(self._buckets)))
            bucket = TokenBucket(capacity, refill)
            self._buckets[client_ip] = bucket
        return bucket

    async def dispatch(self, request: Request, call_next):
        cfg = self._settings()
        if not cfg["enabled"]:
            return await call_next(request)
        client_ip = request.client.host if request.client else "unknown"
        bucket = self._bucket_for(client_ip, cfg["capacity"], cfg["refill"])
        if not bucket.take():
            retry_after = max(1, int(1.0 / max(cfg["refill"], 0.01)))
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Try again shortly.",
                },
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
