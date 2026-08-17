"""Combines technical + fundamental + news analysis into one final signal
with reasoning — not a bare BUY/SELL/HOLD call, but why.
"""

import statistics
from datetime import datetime, timezone

from app.agents.scoring import clamp
from app.assets import AssetInfo
from app.models import (
    ComponentScores,
    FundamentalsResult,
    NewsAggregationResult,
    SignalCall,
    SynthesizedSignal,
    TechnicalAnalysisResult,
)

_WEIGHTS = {"technical": 0.40, "fundamental": 0.35, "news": 0.25}
_BUY_THRESHOLD = 0.20
_SELL_THRESHOLD = -0.20


class SignalSynthesisAgent:
    def synthesize(
        self,
        asset: AssetInfo,
        technical: TechnicalAnalysisResult,
        fundamentals: FundamentalsResult,
        news: NewsAggregationResult,
    ) -> SynthesizedSignal:
        component_scores = ComponentScores(
            technical=technical.score,
            fundamental=fundamentals.score,
            news=news.score,
        )

        final_score = clamp(
            technical.score * _WEIGHTS["technical"]
            + fundamentals.score * _WEIGHTS["fundamental"]
            + news.score * _WEIGHTS["news"]
        )

        if final_score >= _BUY_THRESHOLD:
            signal = SignalCall.BUY
        elif final_score <= _SELL_THRESHOLD:
            signal = SignalCall.SELL
        else:
            signal = SignalCall.HOLD

        confidence = _confidence(final_score, component_scores)
        reasoning = _build_reasoning(asset, signal, final_score, confidence, technical, fundamentals, news)

        return SynthesizedSignal(
            symbol=asset.symbol,
            asset_type=asset.asset_type,
            as_of=datetime.now(timezone.utc),
            signal=signal,
            confidence=confidence,
            component_scores=component_scores,
            reasoning=reasoning,
        )


def _confidence(final_score: float, component_scores: ComponentScores) -> float:
    magnitude = abs(final_score)
    scores = [component_scores.technical, component_scores.fundamental, component_scores.news]
    disagreement = statistics.pstdev(scores)
    agreement = clamp(1 - disagreement, 0, 1)
    return round(clamp((magnitude + agreement) / 2, 0.05, 0.95), 2)


def _build_reasoning(
    asset: AssetInfo,
    signal: SignalCall,
    final_score: float,
    confidence: float,
    technical: TechnicalAnalysisResult,
    fundamentals: FundamentalsResult,
    news: NewsAggregationResult,
) -> str:
    drivers = [
        f"Technical ({technical.sentiment.value}, score {technical.score:+.2f}): {technical.summary}",
        f"Fundamentals ({fundamentals.sentiment.value}, score {fundamentals.score:+.2f}): {fundamentals.summary}",
        f"News ({news.sentiment.value}, score {news.score:+.2f}): {news.summary}",
    ]

    sentiments = {technical.sentiment, fundamentals.sentiment, news.sentiment}
    alignment_note = (
        "All three inputs agree, which supports higher conviction."
        if len(sentiments) == 1
        else "Inputs are mixed, which tempers conviction on this call."
    )

    header = (
        f"{asset.symbol}: {signal.value} (composite score {final_score:+.2f}, confidence {confidence:.0%}). "
        f"{alignment_note}"
    )

    return header + "\n\n" + "\n\n".join(drivers)
