"""Shared technical analysis engine for both forex and crypto.

Pulls OHLCV from the price feed and computes RSI/MACD/moving averages and
support/resistance. Asset-class-agnostic by design: the same code path
serves EURUSD and BTCUSD, which is what lets crypto reuse this engine
untouched once the forex pipeline is proven out.

key_levels (from sr_memory.py) is the persistent support/resistance memory
-- weighted as a real, primary component of the score below, not a minor
nudge, per real-world results from a live level-based forex system this
framework is meant to mirror: technical structure and tested S/R held up,
economic-calendar/news-driven signals didn't.
"""

from datetime import datetime, timezone

from app.agents.indicators import (
    atr,
    detect_rsi_divergence,
    ema_series,
    macd,
    rsi,
    rsi_series,
    sma,
    support_resistance,
    volume_profile_poc,
)
from app.agents.scoring import clamp as _clamp
from app.agents.scoring import sentiment_from_score as _sentiment_from_score
from app.agents.sr_memory import SrMemoryAgent
from app.assets import AssetInfo
from app.data_sources.price_feed import PriceFeedClient
from app.models import KeyLevel, Sentiment, TechnicalAnalysisResult, TechnicalIndicators

# 250 hourly bars (~10 days) gives the 200-period EMA enough warm-up to be
# meaningful -- with only 120 bars its seed value (the series' first close)
# still carries too much weight.
_BARS_FOR_ANALYSIS = 250

_KEY_LEVEL_STRENGTH_WEIGHT = {"new": 0.0, "weak": 0.1, "moderate": 0.3, "strong": 0.6, "very strong": 1.0}


class TechnicalAnalysisAgent:
    def __init__(self, price_feed: PriceFeedClient | None = None, sr_memory: SrMemoryAgent | None = None) -> None:
        self._price_feed = price_feed or PriceFeedClient()
        self._sr_memory = sr_memory or SrMemoryAgent()

    async def analyze(self, asset: AssetInfo) -> TechnicalAnalysisResult:
        bars = await self._price_feed.fetch_ohlcv(asset, bars=_BARS_FOR_ANALYSIS)
        closes = [bar.close for bar in bars]
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]
        volumes = [bar.volume for bar in bars]
        current_price = closes[-1]

        rsi_14 = rsi(closes, 14)
        macd_value, macd_signal, macd_hist = macd(closes)
        sma_20 = sma(closes, 20)
        sma_50 = sma(closes, 50)
        ema_12 = ema_series(closes, 12)[-1]
        ema_26 = ema_series(closes, 26)[-1]
        ema_50 = ema_series(closes, 50)[-1]
        ema_200 = ema_series(closes, 200)[-1]
        atr_14 = atr(highs, lows, closes, 14)
        support, resistance = support_resistance(closes, current_price)
        volume_poc = volume_profile_poc(highs, lows, closes, volumes)
        rsi_divergence = detect_rsi_divergence(closes, rsi_series(closes, 14))
        key_levels = self._sr_memory.update_and_get_key_levels(asset, bars, current_price)

        indicators = TechnicalIndicators(
            rsi_14=rsi_14,
            macd=macd_value,
            macd_signal=macd_signal,
            macd_histogram=macd_hist,
            sma_20=sma_20,
            sma_50=sma_50,
            ema_12=ema_12,
            ema_26=ema_26,
            ema_50=ema_50,
            ema_200=ema_200,
            atr_14=atr_14,
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

        # 50/200 EMA alignment ("golden"/"death" cross structure) -- the
        # higher-timeframe counterpart to the sma20/50-based trend_score
        # above, per the "50/200 EMA slope confirms whether momentum backs
        # the thesis" criterion.
        if current_price > ema_50 > ema_200:
            ema_alignment_score = 1.0
        elif current_price < ema_50 < ema_200:
            ema_alignment_score = -1.0
        else:
            ema_alignment_score = _clamp((current_price - ema_200) / ema_200 * 5)

        key_level_score = _key_level_score(key_levels, current_price)

        # key_level_score is a real, primary component here -- not a minor
        # nudge like divergence below -- per real-world results from a
        # live level-based forex system: tested S/R structure held up,
        # economic-calendar/news-driven signals didn't.
        score = _clamp((rsi_score + macd_score + trend_score + ema_alignment_score + key_level_score) / 5)
        # Divergence is a leading-exhaustion signal, not a component
        # weighted equally with the others -- it nudges the composite
        # rather than dominating it.
        if rsi_divergence == "bullish":
            score = _clamp(score + 0.15)
        elif rsi_divergence == "bearish":
            score = _clamp(score - 0.15)

        sentiment = _sentiment_from_score(score)
        trend = _sentiment_from_score(trend_score)

        summary = _build_summary(
            rsi_14,
            macd_hist,
            current_price,
            sma_20,
            sma_50,
            ema_50,
            ema_200,
            atr_14,
            volume_poc,
            rsi_divergence,
            support,
            resistance,
            trend,
            key_levels,
        )

        return TechnicalAnalysisResult(
            symbol=asset.symbol,
            as_of=datetime.now(timezone.utc),
            latest_close=current_price,
            indicators=indicators,
            support_levels=support,
            resistance_levels=resistance,
            key_levels=key_levels,
            volume_poc=volume_poc,
            rsi_divergence=rsi_divergence,
            trend=trend,
            sentiment=sentiment,
            score=score,
            summary=summary,
        )


def _key_level_score(key_levels: list[KeyLevel], current_price: float) -> float:
    """The persistent-memory counterpart to trend_score/ema_alignment_score
    above -- how strong is the nearest remembered support/resistance zone,
    and which side of price is it on. A strong support nearby is a bullish
    lean (the zone has held before); a strong resistance nearby is bearish.
    A brand-new or weak level contributes almost nothing, by design --
    strength has to be earned through tested history."""
    if not key_levels:
        return 0.0
    closest = min(key_levels, key=lambda level: abs(level.price - current_price))
    weight = _KEY_LEVEL_STRENGTH_WEIGHT.get(closest.strength_label, 0.0)
    return weight if closest.kind == "support" else -weight


def _build_summary(
    rsi_14: float,
    macd_hist: float,
    price: float,
    sma_20: float,
    sma_50: float,
    ema_50: float,
    ema_200: float,
    atr_14: float,
    volume_poc: float,
    rsi_divergence: str | None,
    support: list[float],
    resistance: list[float],
    trend: Sentiment,
    key_levels: list[KeyLevel],
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
    ema_note = (
        "the 50-EMA sits above the 200-EMA, confirming higher-timeframe bullish structure"
        if ema_50 > ema_200
        else "the 50-EMA sits below the 200-EMA, confirming higher-timeframe bearish structure"
    )
    divergence_note = (
        f" A {rsi_divergence} RSI divergence is present, warning the recent {'low' if rsi_divergence == 'bullish' else 'high'} may be losing momentum."
        if rsi_divergence
        else ""
    )

    key_level_note = ""
    if key_levels:
        closest = min(key_levels, key=lambda level: abs(level.price - price))
        if closest.touch_count > 1:
            key_level_note = (
                f" Memory: price is near a {closest.strength_label} {closest.kind} at {closest.price:.4f}, "
                f"tested {closest.touch_count} time(s) ({closest.hold_count} held, {closest.break_count} broke)."
            )

    return (
        f"RSI(14) at {rsi_14:.1f} is in {rsi_note}. "
        f"MACD histogram is {macd_note}. "
        f"Price ({price:.4f}) is {trend_note}, and {ema_note}. "
        f"ATR(14) of {atr_14:.4f} sets the current volatility baseline for stop sizing. "
        f"Nearest support at {support[0]:.4f}, nearest resistance at {resistance[0]:.4f}, "
        f"with the highest-volume node (point of control) at {volume_poc:.4f}.{divergence_note}{key_level_note}"
    )
