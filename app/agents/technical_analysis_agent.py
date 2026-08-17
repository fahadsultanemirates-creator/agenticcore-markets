"""Shared technical analysis engine for both forex and crypto.

Pulls OHLCV from the price feed and computes RSI/MACD/moving averages and
support/resistance. Asset-class-agnostic by design: the same code path
serves EURUSD and BTCUSD, which is what lets crypto reuse this engine
untouched once the forex pipeline is proven out.
"""

from datetime import datetime, timezone

from app.agents.indicators import ema_series, macd, rsi, sma, support_resistance
from app.agents.scoring import clamp as _clamp
from app.agents.scoring import sentiment_from_score as _sentiment_from_score
from app.assets import AssetInfo
from app.data_sources.price_feed import PriceFeedClient
from app.models import Sentiment, TechnicalAnalysisResult, TechnicalIndicators


class TechnicalAnalysisAgent:
    def __init__(self, price_feed: PriceFeedClient | None = None) -> None:
        self._price_feed = price_feed or PriceFeedClient()

    async def analyze(self, asset: AssetInfo) -> TechnicalAnalysisResult:
        bars = await self._price_feed.fetch_ohlcv(asset, bars=120)
        closes = [bar.close for bar in bars]
        current_price = closes[-1]

        rsi_14 = rsi(closes, 14)
        macd_value, macd_signal, macd_hist = macd(closes)
        sma_20 = sma(closes, 20)
        sma_50 = sma(closes, 50)
        ema_12 = ema_series(closes, 12)[-1]
        ema_26 = ema_series(closes, 26)[-1]
        support, resistance = support_resistance(closes, current_price)

        indicators = TechnicalIndicators(
            rsi_14=rsi_14,
            macd=macd_value,
            macd_signal=macd_signal,
            macd_histogram=macd_hist,
            sma_20=sma_20,
            sma_50=sma_50,
            ema_12=ema_12,
            ema_26=ema_26,
        )

        rsi_score = _clamp((rsi_14 - 50) / 50)
        macd_scale = max(abs(macd_value), abs(macd_signal), 1e-9) * 2
        macd_score = _clamp(macd_hist / macd_scale)
        if current_price > sma_20 > sma_50:
            trend_score = 1.0
        elif current_price < sma_20 < sma_50:
            trend_score = -1.0
        else:
            trend_score = _clamp((current_price - sma_50) / sma_50 * 5)

        score = _clamp((rsi_score + macd_score + trend_score) / 3)
        sentiment = _sentiment_from_score(score)
        trend = _sentiment_from_score(trend_score)

        summary = _build_summary(rsi_14, macd_hist, current_price, sma_20, sma_50, support, resistance, trend)

        return TechnicalAnalysisResult(
            symbol=asset.symbol,
            as_of=datetime.now(timezone.utc),
            latest_close=current_price,
            indicators=indicators,
            support_levels=support,
            resistance_levels=resistance,
            trend=trend,
            sentiment=sentiment,
            score=score,
            summary=summary,
        )


def _build_summary(
    rsi_14: float,
    macd_hist: float,
    price: float,
    sma_20: float,
    sma_50: float,
    support: list[float],
    resistance: list[float],
    trend: Sentiment,
) -> str:
    rsi_note = (
        "overbought territory" if rsi_14 > 70 else "oversold territory" if rsi_14 < 30 else "neutral territory"
    )
    macd_note = "positive, favoring upside momentum" if macd_hist > 0 else "negative, favoring downside momentum"
    trend_note = {
        Sentiment.BULLISH: "trading above both the 20- and 50-period moving averages, indicating an established uptrend",
        Sentiment.BEARISH: "trading below both the 20- and 50-period moving averages, indicating an established downtrend",
        Sentiment.NEUTRAL: "chopping around its short-term moving averages with no clear trend",
    }[trend]

    return (
        f"RSI(14) at {rsi_14:.1f} is in {rsi_note}. "
        f"MACD histogram is {macd_note}. "
        f"Price ({price:.4f}) is {trend_note}. "
        f"Nearest support at {support[0]:.4f}, nearest resistance at {resistance[0]:.4f}."
    )
