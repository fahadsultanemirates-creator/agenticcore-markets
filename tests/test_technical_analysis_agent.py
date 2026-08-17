import pytest

from app.agents.technical_analysis_agent import TechnicalAnalysisAgent
from app.assets import get_asset
from app.models import Sentiment


@pytest.mark.parametrize("symbol", ["EURUSD", "BTCUSD"])
async def test_technical_analysis_agent_produces_valid_result(symbol):
    asset = get_asset(symbol)
    agent = TechnicalAnalysisAgent()

    result = await agent.analyze(asset)

    assert result.symbol == symbol
    assert result.latest_close > 0
    assert 0 <= result.indicators.rsi_14 <= 100
    assert result.support_levels
    assert result.resistance_levels
    assert result.trend in Sentiment
    assert result.sentiment in Sentiment
    assert -1.0 <= result.score <= 1.0
    assert symbol == result.symbol
    assert result.summary  # non-empty narrative, not a bare number


async def test_shared_engine_handles_forex_and_crypto_symbols_identically():
    """The same TechnicalAnalysisAgent instance must serve both asset
    classes without special-casing — that's what lets crypto reuse the
    engine proven on forex."""
    agent = TechnicalAnalysisAgent()
    eurusd = await agent.analyze(get_asset("EURUSD"))
    btcusd = await agent.analyze(get_asset("BTCUSD"))

    assert eurusd.symbol == "EURUSD"
    assert btcusd.symbol == "BTCUSD"
    assert type(eurusd) is type(btcusd)
