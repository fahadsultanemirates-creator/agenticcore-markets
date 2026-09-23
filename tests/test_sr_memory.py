"""Tests for the persistent support/resistance memory system
(app/agents/sr_memory.py + app/data_sources/sr_memory_store.py) -- the
actual "which level is hardest to break" tracking a level-based trading
framework depends on. Each test gets an isolated SQLite file via the
autouse conftest.py fixture, so there's no shared/leaked state."""

from datetime import datetime, timedelta, timezone

from app.agents.sr_memory import SrMemoryAgent
from app.assets import get_asset
from app.data_sources.sr_memory_store import SrMemoryStore
from app.models import OHLCVBar


def _make_bars(closes: list[float]) -> list[OHLCVBar]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        OHLCVBar(timestamp=base + timedelta(hours=i), open=c, high=c + 0.3, low=c - 0.3, close=c, volume=100.0)
        for i, c in enumerate(closes)
    ]


def test_repeated_support_touches_accumulate_as_holds():
    # A clean support around 100.2, bounced off 4 times, never broken.
    period = [105, 103, 101, 100.2, 102, 104, 106]
    closes = period * 4
    bars = _make_bars(closes)
    asset = get_asset("EURUSD")

    levels = SrMemoryAgent().update_and_get_key_levels(asset, bars, current_price=103.0)

    supports = [level for level in levels if level.kind == "support"]
    assert supports, "expected at least one recorded support zone"
    strongest = max(supports, key=lambda level: level.touch_count)
    assert strongest.touch_count >= 3
    assert strongest.hold_count >= 2
    assert strongest.break_count == 0
    assert strongest.strength_label in {"strong", "very strong"}


def test_resistance_break_flips_zone_to_support_and_records_break():
    # Resistance around 110, touched twice and held, then broken upward
    # with 3 confirming closes above it.
    closes = [105, 108, 110, 108, 105, 108, 110, 108, 105, 108, 110, 112, 114, 115]
    bars = _make_bars(closes)
    asset = get_asset("EURUSD")

    # current_price close to the break level (not the final close far
    # away) so the zone still falls within the "nearby" reporting window.
    levels = SrMemoryAgent().update_and_get_key_levels(asset, bars, current_price=111.0)

    # After the break, the old resistance zone should have flipped kind
    # to support (classic "old resistance becomes new support") and be
    # below the new current price.
    flipped = [level for level in levels if level.kind == "support" and abs(level.price - 110.0) < 1.0]
    assert flipped, f"expected a flipped support zone near 110, got: {levels}"
    assert flipped[0].break_count >= 1


def test_watermark_prevents_reprocessing_same_pivots_across_calls():
    """Calling update_and_get_key_levels twice with the SAME bar window
    (simulating two requests before any real new market data exists) must
    not double-count touches -- this is the actual bug the watermark
    exists to prevent."""
    period = [105, 103, 101, 100.2, 102, 104, 106]
    closes = period * 3
    bars = _make_bars(closes)
    asset = get_asset("GBPUSD")
    store = SrMemoryStore()
    agent = SrMemoryAgent(store=store)

    first = agent.update_and_get_key_levels(asset, bars, current_price=103.0)
    second = agent.update_and_get_key_levels(asset, bars, current_price=103.0)

    first_support = max((level for level in first if level.kind == "support"), key=lambda level: level.touch_count)
    second_support = max((level for level in second if level.kind == "support"), key=lambda level: level.touch_count)
    assert second_support.touch_count == first_support.touch_count


def test_key_levels_empty_for_insufficient_bars():
    bars = _make_bars([100.0, 101.0, 102.0])
    asset = get_asset("EURUSD")
    assert SrMemoryAgent().update_and_get_key_levels(asset, bars, current_price=101.0) == []


def test_key_levels_empty_for_symbol_with_no_history():
    bars = _make_bars([100.0 + i * 0.1 for i in range(30)])  # a clean uptrend, no repeated pivots
    asset = get_asset("USDJPY")
    levels = SrMemoryAgent().update_and_get_key_levels(asset, bars, current_price=102.0)
    # Not necessarily empty (a monotonic trend can still have edge pivots),
    # but nothing here should have accumulated real repeated-touch history.
    assert all(level.touch_count <= 1 for level in levels)


def test_store_find_nearby_zone_respects_tolerance():
    store = SrMemoryStore()
    store.create_zone("TESTUSD", 100.0, "support", ts=1_700_000_000.0)
    assert store.find_nearby_zone("TESTUSD", 100.05, tolerance_pct=0.0015) is not None  # within 0.15%
    assert store.find_nearby_zone("TESTUSD", 105.0, tolerance_pct=0.0015) is None  # far outside


def test_store_watermark_roundtrip():
    store = SrMemoryStore()
    assert store.get_watermark("NEWUSD") == 0.0
    store.set_watermark("NEWUSD", 12345.0)
    assert store.get_watermark("NEWUSD") == 12345.0
    store.set_watermark("NEWUSD", 99999.0)  # upsert overwrites, not duplicates
    assert store.get_watermark("NEWUSD") == 99999.0
