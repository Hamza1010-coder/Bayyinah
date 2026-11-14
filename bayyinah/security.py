"""Auth and rate limiting.

Deliberately small. This keeps the demo honest about what "secured" means here:
a shared API key and an in-memory token bucket. Multi-tenant auth, key rotation
and per-tenant quotas are a real product's job, not a demo's.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    capacity: int
    refill_per_second: float
    tokens: float = field(init=False)
    last: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = float(self.capacity)
        self.last = time.monotonic()

    def allow(self, cost: float = 1.0) -> tuple[bool, float]:
        now = time.monotonic()
        elapsed = now - self.last
        self.last = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        if self.tokens >= cost:
            self.tokens -= cost
            return True, 0.0
        deficit = cost - self.tokens
        return False, round(deficit / self.refill_per_second, 2)


class RateLimiter:
    def __init__(self, per_minute: int = 60):
        self.capacity = max(1, per_minute)
        self.buckets: dict[str, TokenBucket] = {}

    def check(self, key: str) -> tuple[bool, float]:
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = TokenBucket(capacity=self.capacity, refill_per_second=self.capacity / 60.0)
            self.buckets[key] = bucket
        return bucket.allow()


def is_authorized(provided: str | None, expected: str | None) -> bool:
    if not expected:
        return True  # dev mode: no key configured
    if not provided:
        return False
    # constant-time compare to avoid trivial timing leaks
    import hmac

    return hmac.compare_digest(provided.strip(), expected.strip())
