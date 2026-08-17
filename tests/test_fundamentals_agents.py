from app.agents.crypto_fundamentals_agent import CryptoFundamentalsAgent
from app.agents.forex_fundamentals_agent import ForexFundamentalsAgent
from app.assets import get_asset
from app.models import Sentiment


async def test_forex_fundamentals_agent_produces_valid_result():
    agent = ForexFundamentalsAgent()
    result = await agent.analyze(get_asset("EURUSD"))

    assert result.symbol == "EURUSD"
    assert result.upcoming_events
    assert all(e.impact in {"low", "medium", "high"} for e in result.upcoming_events)
    assert "EUR" in result.central_bank_commentary
    assert "USD" in result.central_bank_commentary
    assert result.sentiment in Sentiment
    assert -1.0 <= result.score <= 1.0
    assert result.summary


async def test_crypto_fundamentals_agent_produces_valid_result():
    agent = CryptoFundamentalsAgent()
    result = await agent.analyze(get_asset("BTCUSD"))

    assert result.symbol == "BTCUSD"
    assert result.market_cap_usd > 0
    assert result.volume_24h_usd > 0
    assert result.circulating_supply > 0
    assert result.onchain.active_addresses_24h > 0
    assert result.ecosystem_notes
    assert result.sentiment in Sentiment
    assert -1.0 <= result.score <= 1.0
    assert result.summary
