"""Fundamentals for commodities (gold, silver, WTI/Brent crude, natural
gas): the real-yield/USD-rate backdrop (the actual mechanism by which Fed
policy moves non-yielding metals -- higher real yields raise the
opportunity cost of holding them), the global risk-on/risk-off regime
(safe-haven demand for precious metals vs. growth-linked demand for
energy), and CFTC COT positioning on the commodity's own futures --
reusing the same real building blocks forex_fundamentals_agent already
has (FRED, the shared risk-regime read, COT), but without any of that
agent's currency-pair assumptions: a commodity has no central bank or
economic calendar of its own.

What this deliberately does NOT cover: physical supply/demand fundamentals
(OPEC production quotas, EIA crude/gas inventory draws/builds, mine
production). Those need either a paid data provider or EIA's API (which
does have a free tier, but its exact schema wasn't confirmed against a
live response before this was written -- same "don't guess an unconfirmed
schema" rule the rest of this framework follows). Left as an honest gap,
not fabricated -- see the README's data-sources table.
"""

from datetime import datetime, timezone

from app.agents.risk_regime import fetch_risk_regime
from app.agents.scoring import clamp, sentiment_from_score
from app.assets import AssetInfo
from app.data_sources.cot_report import CotReportClient
from app.data_sources.econ_calendar import EconCalendarClient
from app.data_sources.macro_data import MacroDataClient
from app.data_sources.price_feed import PriceFeedClient
from app.models import CommodityFundamentalsResult, PositioningResult, RateBackdropResult

# Precious metals are non-yielding and trade on the real-yield/safe-haven
# channel; energy trades far more on supply/demand and growth expectations
# -- the two groups get different weight on each factor below.
_PRECIOUS_METALS = {"XAU", "XAG"}

# Long-run inflation-expectation anchor used only to build a rough
# real-yield proxy from the nominal 10Y (a precise real yield needs its own
# TIPS-based FRED series) -- a defensible approximation, not the exact figure.
_INFLATION_EXPECTATION_ANCHOR_PCT = 2.5


class CommodityFundamentalsAgent:
    def __init__(
        self,
        econ_calendar: EconCalendarClient | None = None,
        macro_data: MacroDataClient | None = None,
        cot_report: CotReportClient | None = None,
        price_feed: PriceFeedClient | None = None,
    ) -> None:
        self._econ_calendar = econ_calendar or EconCalendarClient()
        self._macro_data = macro_data or MacroDataClient()
        self._cot_report = cot_report or CotReportClient()
        self._price_feed = price_feed or PriceFeedClient()

    async def analyze(self, asset: AssetInfo) -> CommodityFundamentalsResult:
        # USD releases (Fed decisions, CPI, payrolls) are what actually
        # move the rate/yield channel that matters here -- reuse the same
        # USD calendar forex_fundamentals_agent uses for its USD leg.
        upcoming = (await self._econ_calendar.fetch_upcoming_events("USD"))[:6]

        us_macro = await self._macro_data.fetch_us_snapshot()
        rate_backdrop, rate_score = _build_rate_backdrop(asset, us_macro)

        risk_regime = await fetch_risk_regime(self._price_feed)
        risk_score = _risk_regime_score(asset, risk_regime.regime)

        positioning = await self._cot_report.fetch_positioning(asset.base)
        cot_score = _cot_score(positioning)

        score = clamp(rate_score + risk_score + cot_score)
        sentiment = sentiment_from_score(score)

        high_impact_soon = [e for e in upcoming if e.impact == "high"]
        caution_note = (
            f" {len(high_impact_soon)} high-impact USD release(s) due in the next two weeks may add volatility "
            "around the current bias."
            if high_impact_soon
            else " No high-impact USD releases are imminent, so the current bias should hold barring surprises."
        )

        summary = (
            f"Rate backdrop: {rate_backdrop.note}{caution_note} "
            f"Global backdrop is {risk_regime.regime.replace('_', '-')} "
            f"(equities {risk_regime.equities_trend.value}, gold {risk_regime.safe_haven_demand.value}). "
            f"COT: {positioning.note} "
            "Note: physical supply/demand fundamentals (OPEC output, EIA inventories, mine production) are not "
            "covered by this framework yet -- see the README for why."
        )

        return CommodityFundamentalsResult(
            symbol=asset.symbol,
            as_of=datetime.now(timezone.utc),
            upcoming_events=upcoming,
            rate_backdrop=rate_backdrop,
            risk_regime=risk_regime,
            positioning=positioning,
            sentiment=sentiment,
            score=score,
            summary=summary,
        )


def _build_rate_backdrop(asset: AssetInfo, us_macro: dict | None) -> tuple[RateBackdropResult, float]:
    if us_macro is None:
        return RateBackdropResult(note="No FRED data available -- rate/yield backdrop unknown, not counted in the score."), 0.0

    fed_funds = us_macro.get("fed_funds_rate_pct")
    ust10y = us_macro.get("ust_10y_yield_pct")

    if asset.base not in _PRECIOUS_METALS:
        # Energy trades far more on supply/demand than the rate channel --
        # note it for context, but don't weight it in the score.
        note = (
            f"US 10Y yield at {ust10y:.2f}%, fed funds at {fed_funds:.2f}% -- a secondary factor for energy "
            "versus physical supply/demand."
            if ust10y is not None and fed_funds is not None
            else "Rate backdrop incomplete (FRED data partially unavailable)."
        )
        return RateBackdropResult(fed_funds_rate_pct=fed_funds, ust_10y_yield_pct=ust10y, note=note), 0.0

    if ust10y is None:
        return RateBackdropResult(fed_funds_rate_pct=fed_funds, note="10Y yield unavailable -- rate/yield backdrop unknown."), 0.0

    real_yield_proxy = ust10y - _INFLATION_EXPECTATION_ANCHOR_PCT
    # Higher real yields raise the opportunity cost of holding a
    # non-yielding asset -- bearish for gold/silver, and vice versa.
    score = clamp(-real_yield_proxy / 3, -0.35, 0.35)
    direction = "a headwind" if score < 0 else "a tailwind" if score > 0 else "roughly neutral"
    note = f"US 10Y yield at {ust10y:.2f}% (real-yield proxy ~{real_yield_proxy:+.2f}%) -- {direction} for non-yielding metals."
    return RateBackdropResult(fed_funds_rate_pct=fed_funds, ust_10y_yield_pct=ust10y, note=note), score


def _risk_regime_score(asset: AssetInfo, regime: str) -> float:
    if regime == "neutral":
        return 0.0
    if asset.base in _PRECIOUS_METALS:
        # Risk-off drives safe-haven demand for metals; risk-on pressures them.
        return 0.25 if regime == "risk_off" else -0.25
    # Energy: risk-on (growth optimism) supports demand; risk-off pressures it.
    return 0.2 if regime == "risk_on" else -0.2


def _cot_score(pos: PositioningResult) -> float:
    if not pos.is_crowded_extreme or pos.net_speculative_position is None:
        return 0.0
    # Crowded long positioning is a contrarian bearish signal (squeeze/
    # mean-reversion risk), crowded short is contrarian bullish.
    return -0.25 if pos.net_speculative_position > 0 else 0.25
