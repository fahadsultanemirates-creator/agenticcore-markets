"""Pulls and summarizes recent, timestamped news per asset. Shared by both
forex and crypto — sentiment scoring is asset-agnostic once headlines are
tagged with a per-item Sentiment.
"""

from datetime import datetime, timezone

from app.agents.scoring import clamp, sentiment_from_score
from app.assets import AssetInfo
from app.data_sources.news_feed import NewsFeedClient
from app.models import NewsAggregationResult, NewsItem, Sentiment

_SENTIMENT_WEIGHT = {Sentiment.BULLISH: 1.0, Sentiment.NEUTRAL: 0.0, Sentiment.BEARISH: -1.0}


class NewsAggregationAgent:
    def __init__(self, news_feed: NewsFeedClient | None = None) -> None:
        self._news_feed = news_feed or NewsFeedClient()

    async def analyze(self, asset: AssetInfo) -> NewsAggregationResult:
        items = await self._news_feed.fetch_news(asset, limit=5)
        score = _aggregate_score(items)
        sentiment = sentiment_from_score(score)
        summary = _build_summary(asset, items, sentiment)

        return NewsAggregationResult(
            symbol=asset.symbol,
            as_of=datetime.now(timezone.utc),
            items=items,
            sentiment=sentiment,
            score=score,
            summary=summary,
        )


def _aggregate_score(items: list[NewsItem]) -> float:
    if not items:
        return 0.0
    return clamp(sum(_SENTIMENT_WEIGHT[item.sentiment] for item in items) / len(items))


def _build_summary(asset: AssetInfo, items: list[NewsItem], sentiment: Sentiment) -> str:
    if not items:
        return f"No recent news found for {asset.symbol}."
    headline_list = "; ".join(f'"{item.headline}" ({item.source})' for item in items[:3])
    return f"Recent coverage skews {sentiment.value}. Top headlines: {headline_list}."
