"""Tests for specialist_agent.py's guard paths -- the parts reachable
without a live Claude/Gemini call or a configured API key. Live calls
can't be exercised in this sandbox (no keys configured, no egress), so
this covers the "never fabricate a verdict, always let the caller fall
back" contract, which is the part that matters most for a service that
can't go down because an LLM provider had an outage."""

from app.assets import get_asset
from app.config import settings
from app.models import CryptoFundamentalsResult, NewsAggregationResult, Sentiment, TechnicalAnalysisResult, TechnicalIndicators
from app.agents.specialist_agent import SpecialistAgent
from datetime import datetime, timezone


def _make_technical() -> TechnicalAnalysisResult:
    return TechnicalAnalysisResult(
        symbol="BTCUSD",
        as_of=datetime.now(timezone.utc),
        latest_close=64000.0,
        indicators=TechnicalIndicators(
            rsi_14=55.0, macd=1.0, macd_signal=0.8, macd_histogram=0.2, sma_20=63000.0, sma_50=62000.0,
            ema_12=63500.0, ema_26=63200.0, ema_50=62800.0, ema_200=60000.0, atr_14=500.0,
        ),
        support_levels=[63000.0],
        resistance_levels=[65000.0],
        volume_poc=64000.0,
        rsi_divergence=None,
        trend=Sentiment.BULLISH,
        sentiment=Sentiment.BULLISH,
        score=0.3,
        summary="stub technical summary",
    )


def _make_news() -> NewsAggregationResult:
    return NewsAggregationResult(
        symbol="BTCUSD", as_of=datetime.now(timezone.utc), items=[], sentiment=Sentiment.NEUTRAL, score=0.0, summary="stub news"
    )


async def test_call_claude_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    agent = SpecialistAgent()
    result = await agent._call_claude("some evidence")
    assert result is None


async def test_call_gemini_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", None)
    agent = SpecialistAgent()
    result = await agent._call_gemini("some evidence")
    assert result is None


async def test_synthesize_returns_none_when_no_keys_configured(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", None)
    agent = SpecialistAgent()
    asset = get_asset("BTCUSD")
    technical = _make_technical()
    from tests.factories import make_crypto_fundamentals

    fundamentals = make_crypto_fundamentals(0.2, Sentiment.NEUTRAL)
    news = _make_news()

    result = await agent.synthesize(asset, technical, fundamentals, news, provider="claude")
    assert result is None
    result = await agent.synthesize(asset, technical, fundamentals, news, provider="gemini")
    assert result is None


async def test_call_claude_returns_none_on_malformed_key(monkeypatch):
    """A key IS set but is obviously invalid -- the SDK call will fail,
    and that failure must degrade to None, not raise."""
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-invalid-test-key")
    agent = SpecialistAgent()
    result = await agent._call_claude("some evidence")
    assert result is None
