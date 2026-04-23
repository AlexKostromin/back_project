from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token bucket rate limiter for controlling request rate to external sources."""

    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self._capacity = capacity
        self._refill_per_sec = refill_per_sec
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire one token, blocking until available."""
        async with self._lock:
            while True:
                self._refill_tokens()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                await asyncio.sleep(1.0 / self._refill_per_sec)

    def _refill_tokens(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._refill_per_sec
        self._tokens = min(self._capacity, self._tokens + added)
        self._last_refill = now
