"""Economic calendar events + central bank commentary for forex_fundamentals_agent.

No broadly free/standard economic-calendar API is wired in yet (candidates:
Trading Economics, Finnhub); this generates a realistic, deterministic
sample calendar per currency so the pipeline runs end-to-end. Swap in a real
provider by implementing `_fetch_live` once ECON_CALENDAR_API_KEY is set.
"""

from datetime import datetime, timedelta, timezone

from app.config import settings
from app.data_sources.mock_utils import rng_for
from app.models import EconomicEvent

_EVENT_TEMPLATES = {
    "USD": [
        ("Non-Farm Payrolls", "high"),
        ("CPI y/y", "high"),
        ("FOMC Rate Decision", "high"),
        ("Retail Sales m/m", "medium"),
        ("Unemployment Claims", "low"),
    ],
    "EUR": [
        ("ECB Rate Decision", "high"),
        ("Eurozone CPI y/y", "high"),
        ("German ZEW Sentiment", "medium"),
        ("PMI Composite", "medium"),
    ],
    "GBP": [
        ("BoE Rate Decision", "high"),
        ("UK CPI y/y", "high"),
        ("UK GDP m/m", "medium"),
    ],
    "JPY": [
        ("BoJ Rate Decision", "high"),
        ("Tokyo CPI y/y", "medium"),
        ("Tankan Manufacturing Index", "medium"),
    ],
    "AUD": [
        ("RBA Rate Decision", "high"),
        ("Australia CPI q/q", "high"),
        ("Employment Change", "medium"),
    ],
    "NZD": [
        ("RBNZ Rate Decision", "high"),
        ("New Zealand CPI q/q", "high"),
        ("GDT Price Index", "low"),
    ],
    "CAD": [
        ("BoC Rate Decision", "high"),
        ("Canada CPI y/y", "high"),
        ("Employment Change", "medium"),
    ],
    "CHF": [
        ("SNB Rate Decision", "high"),
        ("Switzerland CPI y/y", "medium"),
        ("KOF Economic Barometer", "low"),
    ],
}

_COMMENTARY = {
    "USD": "The Federal Reserve has maintained a data-dependent stance, balancing sticky services inflation against a cooling labor market.",
    "EUR": "The ECB has signaled caution on further cuts, citing persistent core inflation in services despite softening growth.",
    "GBP": "The Bank of England remains split between hawks concerned about wage growth and doves pointing to slowing consumer demand.",
    "JPY": "The Bank of Japan continues to normalize policy gradually, watching yen weakness and import-driven inflation closely.",
    "AUD": "The RBA has held a cautious tightening bias, citing resilient labor demand against a slower China-linked commodity outlook.",
    "NZD": "The RBNZ has signaled it's near the end of its cutting cycle, weighing a cooling domestic economy against sticky non-tradables inflation.",
    "CAD": "The Bank of Canada has leaned dovish as growth cools, though it remains wary of energy-price-driven inflation swings.",
    "CHF": "The SNB continues to watch franc strength closely, favoring a cautious rate path over disruptive intervention.",
}


class EconCalendarClient:
    async def fetch_upcoming_events(self, currency: str) -> list[EconomicEvent]:
        if settings.econ_calendar_api_key:
            return await self._fetch_live(currency)
        return self._synthetic_events(currency)

    async def _fetch_live(self, currency: str) -> list[EconomicEvent]:  # pragma: no cover - no provider wired yet
        raise NotImplementedError("Live economic calendar provider not yet integrated")

    def _synthetic_events(self, currency: str) -> list[EconomicEvent]:
        rng = rng_for(currency, "econ_calendar")
        templates = _EVENT_TEMPLATES.get(currency, [])
        now = datetime.now(timezone.utc)
        events = []
        for i, (name, impact) in enumerate(templates):
            events.append(
                EconomicEvent(
                    event=name,
                    country=currency,
                    scheduled_at=now + timedelta(days=rng.randint(1, 14), hours=rng.randint(0, 23)),
                    impact=impact,
                    forecast=f"{rng.uniform(-0.5, 3.5):.1f}%",
                    previous=f"{rng.uniform(-0.5, 3.5):.1f}%",
                )
            )
        return sorted(events, key=lambda e: e.scheduled_at)

    def central_bank_commentary(self, currency: str) -> str:
        return _COMMENTARY.get(currency, f"No recent central bank commentary available for {currency}.")
