import asyncio
import time


class TokenBucket:
    """Async token-bucket rate limiter: `capacity` tokens refilled continuously
    over `period` seconds. Callers await `acquire()` before making a call."""

    def __init__(self, capacity: int, period_seconds: float) -> None:
        self.capacity = capacity
        self.period_seconds = period_seconds
        self._tokens = float(capacity)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated_at
        self._tokens = min(self.capacity, self._tokens + elapsed * (self.capacity / self.period_seconds))
        self._updated_at = now

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                deficit = 1 - self._tokens
                wait_time = deficit * (self.period_seconds / self.capacity)
            await asyncio.sleep(wait_time)


# HubSpot's documented limits (details.md §4), throttled slightly below the
# hard cap so we rarely hit a real 429.
HUBSPOT_GENERAL_LIMIT = TokenBucket(capacity=100, period_seconds=10)
HUBSPOT_SEARCH_LIMIT = TokenBucket(capacity=4, period_seconds=1)
