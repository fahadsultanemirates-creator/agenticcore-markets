"""General financial news feed for news_aggregation_agent, shared by forex
and crypto. Falls back to deterministic sample headlines when NEWS_API_KEY
is unset.
"""

from datetime import datetime, timedelta, timezone

from app.assets import AssetInfo
from app.config import settings
from app.data_sources.mock_utils import rng_for
from app.models import NewsItem, Sentiment

_HEADLINE_TEMPLATES: dict[str, list[tuple[str, Sentiment]]] = {
    "EUR": [
        ("ECB officials signal patience on rate path amid sticky services inflation", Sentiment.NEUTRAL),
        ("Eurozone manufacturing PMI beats forecasts, easing recession worries", Sentiment.BULLISH),
        ("Political uncertainty in France weighs on euro sentiment", Sentiment.BEARISH),
    ],
    "USD": [
        ("Fed officials push back on near-term rate cut expectations", Sentiment.BULLISH),
        ("US labor market shows signs of cooling in latest jobs report", Sentiment.BEARISH),
        ("Dollar steady as traders await next inflation print", Sentiment.NEUTRAL),
    ],
    "GBP": [
        ("BoE policymaker flags persistent wage growth as inflation risk", Sentiment.BULLISH),
        ("UK retail sales disappoint, raising growth concerns", Sentiment.BEARISH),
    ],
    "JPY": [
        ("Yen weakens as BoJ maintains cautious normalization pace", Sentiment.BEARISH),
        ("Japan flags possible intervention as yen volatility rises", Sentiment.NEUTRAL),
    ],
    "BTC": [
        ("Bitcoin ETF inflows extend streak as institutional demand grows", Sentiment.BULLISH),
        ("On-chain data shows long-term holders continuing to accumulate", Sentiment.BULLISH),
        ("Regulatory uncertainty in key markets weighs on crypto sentiment", Sentiment.BEARISH),
    ],
    "ETH": [
        ("Ethereum layer-2 ecosystem sees record activity following upgrade", Sentiment.BULLISH),
        ("Staking yields compress as validator queue grows", Sentiment.NEUTRAL),
        ("Competition from alternative L1s pressures ETH market share narrative", Sentiment.BEARISH),
    ],
}

_SOURCES = ["Reuters", "Bloomberg", "CoinDesk", "Financial Times", "MarketWatch"]


class NewsFeedClient:
    async def fetch_news(self, asset: AssetInfo, limit: int = 5) -> list[NewsItem]:
        if settings.news_api_key:
            return await self._fetch_live(asset, limit)
        return self._synthetic_news(asset, limit)

    async def _fetch_live(self, asset: AssetInfo, limit: int) -> list[NewsItem]:  # pragma: no cover - no provider wired yet
        raise NotImplementedError("Live news provider not yet integrated")

    def _synthetic_news(self, asset: AssetInfo, limit: int) -> list[NewsItem]:
        rng = rng_for(asset.symbol, "news")
        pool: list[tuple[str, Sentiment]] = []
        for currency in {asset.base, asset.quote}:
            pool.extend(_HEADLINE_TEMPLATES.get(currency, []))
        if not pool:
            pool = [(f"No major headlines for {asset.symbol} in the last 24 hours.", Sentiment.NEUTRAL)]

        rng.shuffle(pool)
        now = datetime.now(timezone.utc)
        items = []
        for i, (headline, sentiment) in enumerate(pool[:limit]):
            items.append(
                NewsItem(
                    headline=headline,
                    source=_SOURCES[rng.randrange(len(_SOURCES))],
                    published_at=now - timedelta(hours=rng.randint(1, 36)),
                    url=f"https://news.example.com/{asset.symbol.lower()}/{i}",
                    sentiment=sentiment,
                )
            )
        return sorted(items, key=lambda item: item.published_at, reverse=True)
