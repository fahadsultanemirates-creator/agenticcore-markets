from datetime import datetime, timezone

from app.agents.signal_synthesis_agent import SignalSynthesisAgent
from app.assets import get_asset
from app.models import (
    NewsAggregationResult,
    Sentiment,
    SignalCall,
    TechnicalAnalysisResult,
    TechnicalIndicators,
)
from tests.factories import make_forex_fundamentals


def make_technical(score: float, sentiment: Sentiment) -> TechnicalAnalysisResult:
    return TechnicalAnalysisResult(
        symbol="EURUSD",
        as_of=datetime.now(timezone.utc),
        latest_close=1.085,
        indicators=TechnicalIndicators(
            rsi_14=55, macd=0.001, macd_signal=0.0005, macd_histogram=0.0005,
            sma_20=1.08, sma_50=1.07, ema_12=1.084, ema_26=1.082,
            ema_50=1.075, ema_200=1.06, atr_14=0.002,
        ),
        support_levels=[1.08],
        resistance_levels=[1.09],
        volume_poc=1.085,
        rsi_divergence=None,
        trend=sentiment,
        sentiment=sentiment,
        score=score,
        summary="stub technical summary",
    )


def make_news(score: float, sentiment: Sentiment) -> NewsAggregationResult:
    return NewsAggregationResult(
        symbol="EURUSD", as_of=datetime.now(timezone.utc), items=[],
        sentiment=sentiment, score=score, summary="stub news summary",
    )


def test_all_bullish_inputs_produce_buy_with_high_confidence():
    asset = get_asset("EURUSD")
    agent = SignalSynthesisAgent()

    result = agent.synthesize(
        asset,
        make_technical(0.8, Sentiment.BULLISH),
        make_forex_fundamentals(0.8, Sentiment.BULLISH),
        make_news(0.8, Sentiment.BULLISH),
    )

    assert result.signal == SignalCall.BUY
    assert result.confidence > 0.5
    assert "BUY" in result.reasoning
    assert "agree" in result.reasoning.lower()


def test_all_bearish_inputs_produce_sell():
    asset = get_asset("EURUSD")
    agent = SignalSynthesisAgent()

    result = agent.synthesize(
        asset,
        make_technical(-0.8, Sentiment.BEARISH),
        make_forex_fundamentals(-0.8, Sentiment.BEARISH),
        make_news(-0.8, Sentiment.BEARISH),
    )

    assert result.signal == SignalCall.SELL


def test_mixed_neutral_inputs_produce_hold_with_lower_confidence():
    asset = get_asset("EURUSD")
    agent = SignalSynthesisAgent()

    strong_buy = agent.synthesize(
        asset,
        make_technical(0.8, Sentiment.BULLISH),
        make_forex_fundamentals(0.8, Sentiment.BULLISH),
        make_news(0.8, Sentiment.BULLISH),
    )
    mixed = agent.synthesize(
        asset,
        make_technical(0.8, Sentiment.BULLISH),
        make_forex_fundamentals(-0.8, Sentiment.BEARISH),
        make_news(0.0, Sentiment.NEUTRAL),
    )

    assert mixed.signal == SignalCall.HOLD
    assert mixed.confidence < strong_buy.confidence
    assert "mixed" in mixed.reasoning.lower()


def test_reasoning_includes_each_agent_summary():
    asset = get_asset("EURUSD")
    agent = SignalSynthesisAgent()

    result = agent.synthesize(
        asset,
        make_technical(0.5, Sentiment.BULLISH),
        make_forex_fundamentals(0.1, Sentiment.NEUTRAL),
        make_news(-0.1, Sentiment.NEUTRAL),
    )

    assert "stub technical summary" in result.reasoning
    assert "stub news summary" in result.reasoning
