"""In-memory TTL cache shared across subscribers.

Many subscribers request analysis for the same handful of popular assets
(EURUSD, BTCUSD, ...). Recomputing the full agent pipeline per request would
multiply data-source calls for no benefit, since the underlying market data
only moves meaningfully every few minutes. This cache lets concurrent
requests for the same symbol share one in-flight computation and reuse the
result until it expires.

The interface (`get_or_compute`) is storage-agnostic: swapping this for a
Redis-backed implementation later requires no changes to callers.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, _Entry[T]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    def peek(self, key: str) -> T | None:
        entry = self._entries.get(key)
        if entry is None or entry.expires_at <= time.monotonic():
            return None
        return entry.value

    async def get_or_compute(self, key: str, compute: Callable[[], Awaitable[T]]) -> tuple[T, bool]:
        """Return (value, was_cached). Concurrent callers for the same key
        share a single computation instead of stampeding the data sources."""
        cached = self.peek(key)
        if cached is not None:
            return cached, True

        lock = await self._lock_for(key)
        async with lock:
            # Re-check: another caller may have computed it while we waited.
            cached = self.peek(key)
            if cached is not None:
                return cached, True

            value = await compute()
            self._entries[key] = _Entry(value=value, expires_at=time.monotonic() + self._ttl_seconds)
            return value, False

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()
