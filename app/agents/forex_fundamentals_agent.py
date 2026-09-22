"""Fundamentals for forex pairs: upcoming economic calendar events, central
bank commentary/tone for both legs, real US macro data when a FRED key is
set, the global risk-on/risk-off regime, and CFTC COT positioning -- the
non-technical side of the forex framework (HTF structure/momentum already
lives in the shared technical_analysis_agent).
"""

from datetime import datetime, timezone

from app.agents.indicators import sma
from app.agents.scoring import clamp, sentiment_from_score
from app.assets import AssetInfo, AssetType
from app.data_sources.cot_report import CotReportClient
from app.data_sources.econ_calendar import EconCalendarClient
from app.data_sources.macro_data import MacroDataClient
from app.data_sources.mock_utils import rng_for
from app.data_sources.price_feed import PriceFeedClient
from app.models import ForexFundamentalsResult, PositioningResult, RiskRegimeResult, Sentiment

_HAWKISH_WORDS = ("hawk", "sticky", "persistent", "wage growth", "normaliz")
_DOVISH_WORDS = ("dove", "cooling", "soften", "recession", "disappoint", "weaken")

# Currency risk-appetite classification for the risk-on/off overlay --
# deliberately coarse (EUR/JPY-as-funding-currency nuances etc. are real but
# out of scope for a heuristic macro overlay, not the core signal).
_HIGH_BETA_CCY = {"AUD", "NZD", "CAD", "GBP"}
_SAFE_HAVEN_CCY = {"USD", "JPY", "CHF"}

# Internal-only price-feed proxies for the risk regime read -- not real
# tradable symbols, so deliberately not in the asset registry.
_GOLD_PROXY = AssetInfo(symbol="XAUUSD", display_name="Gold / US Dollar", asset_type=AssetType.FOREX, base="XAU", quote="USD")
_EQUITIES_PROXY = AssetInfo(
    symbol="US500USD", display_name="S&P 500 / US Dollar", asset_type=AssetType.FOREX, base="US500", quote="USD"
)


class ForexFundamentalsAgent:
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

    async def analyze(self, asset: AssetInfo) -> ForexFundamentalsResult:
        base_events = await self._econ_calendar.fetch_upcoming_events(asset.base)
        quote_events = await self._econ_calendar.fetch_upcoming_events(asset.quote)
        upcoming = sorted(base_events + quote_events, key=lambda e: e.scheduled_at)[:6]

        base_commentary = self._econ_calendar.central_bank_commentary(asset.base)
        quote_commentary = self._econ_calendar.central_bank_commentary(asset.quote)
        commentary = f"{asset.base}: {base_commentary} {asset.quote}: {quote_commentary}"

        base_tone = _tone_score(base_commentary)
        quote_tone = _tone_score(quote_commentary)

        us_macro = await self._macro_data.fetch_us_snapshot()
        macro_bias, macro_note = _macro_bias(asset, us_macro)

        risk_regime = await self._fetch_risk_regime()
        risk_score = _risk_regime_score(risk_regime.regime, asset.base, asset.quote)

        positioning = [
            await self._cot_report.fetch_positioning(asset.base),
            await self._cot_report.fetch_positioning(asset.quote),
        ]
        cot_score = _cot_score(positioning, asset.base) - _cot_score(positioning, asset.quote)

        score = clamp(macro_bias + (base_tone - quote_tone) * 0.3 + risk_score + cot_score)
        sentiment = sentiment_from_score(score)

        high_impact_soon = [e for e in upcoming if e.impact == "high"]
        caution_note = (
            f" {len(high_impact_soon)} high-impact release(s) due in the next two weeks may add volatility around the current bias."
            if high_impact_soon
            else " No high-impact releases are imminent, so the current bias should hold barring surprises."
        )

        summary = (
            f"Central bank tone: {commentary}{caution_note} "
            f"{macro_note} "
            f"Global backdrop is {risk_regime.regime.replace('_', '-')} "
            f"(equities {risk_regime.equities_trend.value}, gold {risk_regime.safe_haven_demand.value}). "
            f"{_positioning_note(positioning)}"
        )

        return ForexFundamentalsResult(
            symbol=asset.symbol,
            as_of=datetime.now(timezone.utc),
            upcoming_events=upcoming,
            central_bank_commentary=commentary,
            risk_regime=risk_regime,
            positioning=positioning,
            sentiment=sentiment,
            score=score,
            summary=summary,
        )

    async def _fetch_risk_regime(self) -> RiskRegimeResult:
        gold_bars = await self._price_feed.fetch_ohlcv(_GOLD_PROXY, bars=60)
        equities_bars = await self._price_feed.fetch_ohlcv(_EQUITIES_PROXY, bars=60)
        gold_trend = _trend_from_closes([b.close for b in gold_bars])
        equities_trend = _trend_from_closes([b.close for b in equities_bars])

        if equities_trend == Sentiment.BULLISH and gold_trend != Sentiment.BULLISH:
            regime = "risk_on"
        elif equities_trend == Sentiment.BEARISH and gold_trend == Sentiment.BULLISH:
            regime = "risk_off"
        else:
            regime = "neutral"

        return RiskRegimeResult(regime=regime, equities_trend=equities_trend, safe_haven_demand=gold_trend)


def _trend_from_closes(closes: list[float]) -> Sentiment:
    if len(closes) < 50:
        return Sentiment.NEUTRAL
    s20, s50, current = sma(closes, 20), sma(closes, 50), closes[-1]
    if current > s20 > s50:
        return Sentiment.BULLISH
    if current < s20 < s50:
        return Sentiment.BEARISH
    return Sentiment.NEUTRAL


def _risk_regime_score(regime: str, base: str, quote: str) -> float:
    if regime == "neutral":
        return 0.0
    direction = 1 if regime == "risk_on" else -1  # risk-on favors high-beta currencies over havens
    score = 0.0
    if base in _HIGH_BETA_CCY:
        score += 0.3 * direction
    if base in _SAFE_HAVEN_CCY:
        score -= 0.3 * direction
    if quote in _HIGH_BETA_CCY:
        score -= 0.3 * direction
    if quote in _SAFE_HAVEN_CCY:
        score += 0.3 * direction
    return clamp(score, -0.4, 0.4)


def _cot_score(positioning: list[PositioningResult], currency: str) -> float:
    pos = next((p for p in positioning if p.currency == currency), None)
    if not pos or not pos.is_crowded_extreme or pos.net_speculative_position is None:
        return 0.0
    # Crowded long positioning is a contrarian bearish signal for that
    # currency (squeeze/mean-reversion risk), crowded short is contrarian bullish.
    return -0.25 if pos.net_speculative_position > 0 else 0.25


def _positioning_note(positioning: list[PositioningResult]) -> str:
    return " ".join(f"{p.currency} COT: {p.note}" for p in positioning)


def _macro_bias(asset: AssetInfo, us_macro: dict | None) -> tuple[float, str]:
    if us_macro is None or "USD" not in (asset.base, asset.quote):
        # No FRED key set, or USD isn't in this pair (FRED only covers US
        # data) -- keep the existing deterministic placeholder rather than
        # claiming a real macro read that isn't there.
        placeholder = rng_for(asset.symbol, "macro_bias").uniform(-0.4, 0.4)
        return placeholder, "US macro data unavailable (no FRED_API_KEY set) -- using placeholder macro bias."

    cpi = us_macro.get("cpi_yoy_pct")
    unemployment = us_macro.get("unemployment_rate_pct")
    payrolls = us_macro.get("payrolls_change_thousands")

    usd_score = 0.0
    notes = []
    if cpi is not None:
        if cpi > 3.0:
            usd_score += 0.15
            notes.append(f"CPI running hot at {cpi:.1f}% y/y")
        elif cpi < 2.0:
            usd_score -= 0.15
            notes.append(f"CPI cool at {cpi:.1f}% y/y")
    if unemployment is not None:
        if unemployment < 4.0:
            usd_score += 0.1
            notes.append(f"unemployment tight at {unemployment:.1f}%")
        elif unemployment > 5.0:
            usd_score -= 0.1
            notes.append(f"unemployment elevated at {unemployment:.1f}%")
    if payrolls is not None:
        if payrolls > 200:
            usd_score += 0.1
            notes.append(f"payrolls strong at +{payrolls:.0f}k")
        elif payrolls < 100:
            usd_score -= 0.1
            notes.append(f"payrolls soft at {payrolls:+.0f}k")

    usd_score = clamp(usd_score, -0.4, 0.4)
    # Positive usd_score means USD-supportive; sign flips depending on
    # which side of the pair USD sits on.
    signed_score = usd_score if asset.base == "USD" else -usd_score
    note_text = f"Real US macro read (FRED): {', '.join(notes) if notes else 'no strong signal either way'}."
    return signed_score, note_text


def _tone_score(commentary: str) -> float:
    text = commentary.lower()
    hawkish_hits = sum(word in text for word in _HAWKISH_WORDS)
    dovish_hits = sum(word in text for word in _DOVISH_WORDS)
    return clamp((hawkish_hits - dovish_hits) * 0.25)
