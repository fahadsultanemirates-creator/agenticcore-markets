"""Shared scoring helpers used by every agent that produces a -1..1 score."""

from app.models import Sentiment


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def sentiment_from_score(score: float) -> Sentiment:
    if score > 0.15:
        return Sentiment.BULLISH
    if score < -0.15:
        return Sentiment.BEARISH
    return Sentiment.NEUTRAL
