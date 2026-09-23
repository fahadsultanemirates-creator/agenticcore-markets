"""Persistent support/resistance memory: unlike a stateless per-request
pivot scan (indicators.support_resistance), this accumulates real history
across requests over time -- tracking how many times each zone has been
tested, whether it held or broke, and scoring "strength" from that
history. This is the actual decision-relevant fact a level-based trading
framework runs on: not just "there's support near X" but "support at X
has held 6 of 7 tests over the past 5 weeks."

Zone clustering: a new pivot merges into an existing zone if it's within
a relative tolerance band of that zone's price -- 0.15% for forex/
commodities, 1% for crypto (wider, given crypto's larger effective
spreads/volatility) -- otherwise it creates a new zone.

Hold vs. break are classified by two INDEPENDENT mechanisms, deliberately
not one shared pivot check:

- A hold is pivot-anchored: after a new pivot forms near an existing
  zone (a bounce), price moving away from the zone by more than the
  tolerance without first closing through it counts as a hold.
- A break does NOT require a pivot to form at the break point -- a rally
  that was already underway can blow straight through a level with no
  local peak/trough forming there at all. So breaks are detected by
  scanning every zone against all bars newer than that zone's last test,
  independent of pivot detection: 2+ consecutive closes beyond the zone
  by more than the tolerance (filters out a single wick) confirms it,
  and flips the zone's kind (classic "old resistance becomes new
  support") rather than retiring it.

Re-processing the same historical pivot on every request would silently
inflate touch counts every time someone just asks for analysis again,
without any new market data actually occurring -- a real correctness
trap for a "memory" system. This is prevented with a per-symbol
watermark (the timestamp of the latest bar involved in a CONFIRMED
touch): pivots at or before the watermark are skipped, and processing
stops at the first still-unresolved pivot in chronological order so it
gets reconsidered on a later request, once fresher bars can resolve it.
The break scanner uses its own per-zone watermark (last_tested) for the
same reason.
"""

from app.assets import AssetInfo, AssetType
from app.data_sources.sr_memory_store import SrMemoryStore
from app.models import KeyLevel, OHLCVBar

_FOREX_COMMODITY_TOLERANCE_PCT = 0.0015  # 0.15%
_CRYPTO_TOLERANCE_PCT = 0.01  # 1%
_NEARBY_WINDOW_MULTIPLIER = 20  # how far from current price a zone can be and still count as "key"
_BREAK_CONFIRMATION_BARS = 2
_PIVOT_WINDOW = 3
_MAX_LEVELS_PER_SIDE = 3

_STRENGTH_THRESHOLDS = [(8, "very strong"), (4, "strong"), (1, "moderate")]


def _tolerance_for(asset: AssetInfo) -> float:
    return _CRYPTO_TOLERANCE_PCT if asset.asset_type == AssetType.CRYPTO else _FOREX_COMMODITY_TOLERANCE_PCT


def _find_pivots(bars: list[OHLCVBar]) -> list[tuple[int, float, str]]:
    """Same local swing-high/low logic as indicators.support_resistance,
    but keeps the bar index and timestamp context this module needs for
    break/hold classification and the watermark, which the shared
    (stateless) function doesn't track."""
    closes = [b.close for b in bars]
    pivots: list[tuple[int, float, str]] = []
    for i in range(_PIVOT_WINDOW, len(closes) - _PIVOT_WINDOW):
        segment = closes[i - _PIVOT_WINDOW : i + _PIVOT_WINDOW + 1]
        center = closes[i]
        if center == min(segment):
            pivots.append((i, center, "support"))
        if center == max(segment):
            pivots.append((i, center, "resistance"))
    return pivots


def _classify_hold(bars: list[OHLCVBar], pivot_index: int, zone_price: float, kind: str, tolerance_pct: float) -> str | None:
    """Only ever returns "hold" or None -- a close beyond the zone in the
    breaking direction means this touch isn't a clean bounce, so this
    gives up and lets the independent break scanner (_find_confirmed_break)
    decide what actually happens next, rather than trying to track
    consecutive-beyond-bars from an arbitrary pivot's vantage point."""
    threshold = zone_price * tolerance_pct
    # Breaking a resistance means closing above it; breaking a support
    # means closing below it -- this sign flips which direction counts.
    beyond_direction = 1 if kind == "resistance" else -1

    for bar in bars[pivot_index + 1 :]:
        distance = (bar.close - zone_price) * beyond_direction
        if distance > threshold:
            return None
        if -distance > threshold:
            return "hold"
    return None  # not enough follow-through bars yet -- resolved on a later update


def _find_confirmed_break_ts(bars: list[OHLCVBar], zone_price: float, kind: str, tolerance_pct: float, after_ts: float) -> float | None:
    """Scans every bar strictly newer than `after_ts` (the zone's last
    test) for 2+ consecutive closes beyond the zone -- independent of
    whether a pivot formed at that point, since a breakout doesn't need
    to peak/trough right at the level to count."""
    threshold = zone_price * tolerance_pct
    beyond_direction = 1 if kind == "resistance" else -1

    consecutive = 0
    for bar in bars:
        if bar.timestamp.timestamp() <= after_ts:
            continue
        distance = (bar.close - zone_price) * beyond_direction
        if distance > threshold:
            consecutive += 1
            if consecutive >= _BREAK_CONFIRMATION_BARS:
                return bar.timestamp.timestamp()
        else:
            consecutive = 0
    return None


def _strength_label(hold_count: int, touch_count: int, break_count: int) -> str:
    if touch_count <= 1:
        return "new"
    score = hold_count * 2 + touch_count - break_count * 1.5
    for threshold, label in _STRENGTH_THRESHOLDS:
        if score >= threshold:
            return label
    return "weak"


class SrMemoryAgent:
    def __init__(self, store: SrMemoryStore | None = None) -> None:
        self._store = store or SrMemoryStore()

    def update_and_get_key_levels(self, asset: AssetInfo, bars: list[OHLCVBar], current_price: float) -> list[KeyLevel]:
        if len(bars) < _PIVOT_WINDOW * 2 + 1 or current_price <= 0:
            return []
        tolerance_pct = _tolerance_for(asset)
        self._process_pivot_holds(asset.symbol, bars, tolerance_pct)
        self._process_breaks(asset.symbol, bars, tolerance_pct)
        return self._get_key_levels(asset.symbol, current_price, tolerance_pct)

    def _process_pivot_holds(self, symbol: str, bars: list[OHLCVBar], tolerance_pct: float) -> None:
        watermark = self._store.get_watermark(symbol)
        pivots = sorted(_find_pivots(bars), key=lambda p: bars[p[0]].timestamp)

        new_watermark = watermark
        for pivot_index, price, kind in pivots:
            pivot_ts = bars[pivot_index].timestamp.timestamp()
            if pivot_ts <= watermark:
                continue

            zone = self._store.find_nearby_zone(symbol, price, tolerance_pct)
            if zone is None:
                self._store.create_zone(symbol, price, kind, ts=pivot_ts)
                new_watermark = pivot_ts
                continue

            outcome = _classify_hold(bars, pivot_index, zone["price"], zone["kind"], tolerance_pct)
            if outcome is None:
                # Stop here, in chronological order -- leaving the
                # watermark before this pivot means it gets a fair
                # re-check once fresher bars exist (it may resolve as a
                # hold later, or the break scanner may pick it up first).
                break
            self._store.record_touch(zone["id"], price, outcome, ts=pivot_ts)
            new_watermark = pivot_ts

        if new_watermark != watermark:
            self._store.set_watermark(symbol, new_watermark)

    def _process_breaks(self, symbol: str, bars: list[OHLCVBar], tolerance_pct: float) -> None:
        # Independent of pivot detection -- re-reads zones fresh so it
        # sees any holds _process_pivot_holds just recorded (their
        # updated last_tested correctly narrows this scan's window).
        for zone in self._store.get_zones(symbol):
            break_ts = _find_confirmed_break_ts(bars, zone["price"], zone["kind"], tolerance_pct, after_ts=zone["last_tested"])
            if break_ts is not None:
                self._store.record_touch(zone["id"], zone["price"], "break", ts=break_ts)

    def _get_key_levels(self, symbol: str, current_price: float, tolerance_pct: float) -> list[KeyLevel]:
        zones = self._store.get_zones(symbol)
        window = tolerance_pct * _NEARBY_WINDOW_MULTIPLIER
        nearby = [z for z in zones if abs(z["price"] - current_price) / current_price <= window]

        support = sorted(
            (z for z in nearby if z["kind"] == "support" and z["price"] < current_price), key=lambda z: -z["price"]
        )[:_MAX_LEVELS_PER_SIDE]
        resistance = sorted(
            (z for z in nearby if z["kind"] == "resistance" and z["price"] > current_price), key=lambda z: z["price"]
        )[:_MAX_LEVELS_PER_SIDE]

        levels = [
            KeyLevel(
                price=z["price"],
                kind=z["kind"],
                touch_count=z["touch_count"],
                hold_count=z["hold_count"],
                break_count=z["break_count"],
                strength_label=_strength_label(z["hold_count"], z["touch_count"], z["break_count"]),
            )
            for z in (support + resistance)
        ]
        return sorted(levels, key=lambda level: abs(level.price - current_price))
