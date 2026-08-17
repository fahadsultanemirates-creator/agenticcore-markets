"""Small builders for constructing valid model instances in tests without
repeating every required field."""

from datetime import datetime, timezone

from app.models import ForexFundamentalsResult, Sentiment


def make_forex_fundamentals(score: float, sentiment: Sentiment) -> ForexFundamentalsResult:
    return ForexFundamentalsResult(
        symbol="EURUSD",
        as_of=datetime.now(timezone.utc),
        upcoming_events=[],
        central_bank_commentary="stub commentary",
        sentiment=sentiment,
        score=score,
        summary="stub fundamentals summary",
    )
