from app.agents.news_aggregation_agent import NewsAggregationAgent
from app.assets import get_asset
from app.models import Sentiment


async def test_news_aggregation_agent_produces_timestamped_items():
    agent = NewsAggregationAgent()
    result = await agent.analyze(get_asset("EURUSD"))

    assert result.symbol == "EURUSD"
    assert result.items
    for item in result.items:
        assert item.headline
        assert item.source
        assert item.published_at is not None
        assert item.sentiment in Sentiment
    # newest first
    timestamps = [item.published_at for item in result.items]
    assert timestamps == sorted(timestamps, reverse=True)
    assert result.sentiment in Sentiment
    assert -1.0 <= result.score <= 1.0


async def test_news_aggregation_agent_works_for_crypto_symbol():
    agent = NewsAggregationAgent()
    result = await agent.analyze(get_asset("BTCUSD"))

    assert result.symbol == "BTCUSD"
    assert result.items
