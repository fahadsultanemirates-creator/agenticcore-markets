import asyncio

import pytest

from app.cache.cache_layer import TTLCache


async def test_get_or_compute_caches_within_ttl():
    cache: TTLCache[int] = TTLCache(ttl_seconds=60)
    calls = 0

    async def compute() -> int:
        nonlocal calls
        calls += 1
        return 42

    value1, cached1 = await cache.get_or_compute("k", compute)
    value2, cached2 = await cache.get_or_compute("k", compute)

    assert value1 == value2 == 42
    assert cached1 is False
    assert cached2 is True
    assert calls == 1


async def test_get_or_compute_recomputes_after_expiry():
    cache: TTLCache[int] = TTLCache(ttl_seconds=0)
    calls = 0

    async def compute() -> int:
        nonlocal calls
        calls += 1
        return calls

    value1, _ = await cache.get_or_compute("k", compute)
    await asyncio.sleep(0.01)
    value2, cached2 = await cache.get_or_compute("k", compute)

    assert value1 == 1
    assert value2 == 2
    assert cached2 is False


async def test_concurrent_requests_share_single_computation():
    cache: TTLCache[int] = TTLCache(ttl_seconds=60)
    calls = 0

    async def compute() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return calls

    results = await asyncio.gather(*(cache.get_or_compute("k", compute) for _ in range(10)))

    assert calls == 1
    assert all(value == 1 for value, _ in results)


async def test_different_keys_are_independent():
    cache: TTLCache[str] = TTLCache(ttl_seconds=60)

    async def compute_a() -> str:
        return "a"

    async def compute_b() -> str:
        return "b"

    value_a, _ = await cache.get_or_compute("a", compute_a)
    value_b, _ = await cache.get_or_compute("b", compute_b)

    assert value_a == "a"
    assert value_b == "b"
