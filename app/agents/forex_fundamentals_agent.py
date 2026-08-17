"""Fundamentals for forex pairs: upcoming economic calendar events, central
bank commentary/tone for both legs of the pair, and a resulting macro bias.
"""

from datetime import datetime, timezone

from app.agents.scoring import clamp, sentiment_from_score
from app.assets import AssetInfo
from app.data_sources.econ_calendar import EconCalendarClient
from app.data_sources.mock_utils import rng_for
from app.models import ForexFundamentalsResult

_HAWKISH_WORDS = ("hawk", "sticky", "persistent", "wage growth", "normaliz")
_DOVISH_WORDS = ("dove", "cooling", "soften", "recession", "disappoint", "weaken")


class ForexFundamentalsAgent:
    def __init__(self, econ_calendar: EconCalendarClient | None = None) -> None:
        self._econ_calendar = econ_calendar or EconCalendarClient()

    async def analyze(self, asset: AssetInfo) -> ForexFundamentalsResult:
        base_events = await self._econ_calendar.fetch_upcoming_events(asset.base)
        quote_events = await self._econ_calendar.fetch_upcoming_events(asset.quote)
        upcoming = sorted(base_events + quote_events, key=lambda e: e.scheduled_at)[:6]

        base_commentary = self._econ_calendar.central_bank_commentary(asset.base)
        quote_commentary = self._econ_calendar.central_bank_commentary(asset.quote)
        commentary = f"{asset.base}: {base_commentary} {asset.quote}: {quote_commentary}"

        base_tone = _tone_score(base_commentary)
        quote_tone = _tone_score(quote_commentary)

        # Deterministic stand-in for an aggregated macro-model bias (growth
        # differentials, rate expectations, etc.) until a dedicated macro
        # data provider is wired in. Central bank tone still moves the score.
        macro_bias = rng_for(asset.symbol, "macro_bias").uniform(-0.4, 0.4)
        score = clamp(macro_bias + (base_tone - quote_tone) * 0.3)
        sentiment = sentiment_from_score(score)

        high_impact_soon = [e for e in upcoming if e.impact == "high"]
        caution_note = (
            f" {len(high_impact_soon)} high-impact release(s) due in the next two weeks may add volatility around the current bias."
            if high_impact_soon
            else " No high-impact releases are imminent, so the current bias should hold barring surprises."
        )

        summary = (
            f"Central bank tone: {commentary}"
            f"{caution_note}"
        )

        return ForexFundamentalsResult(
            symbol=asset.symbol,
            as_of=datetime.now(timezone.utc),
            upcoming_events=upcoming,
            central_bank_commentary=commentary,
            sentiment=sentiment,
            score=score,
            summary=summary,
        )


def _tone_score(commentary: str) -> float:
    text = commentary.lower()
    hawkish_hits = sum(word in text for word in _HAWKISH_WORDS)
    dovish_hits = sum(word in text for word in _DOVISH_WORDS)
    return clamp((hawkish_hits - dovish_hits) * 0.25)
