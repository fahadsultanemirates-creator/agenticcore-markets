"""Combines technical + fundamental + news analysis into one final signal
with reasoning — not a bare BUY/SELL/HOLD call, but why.
"""

import statistics
from datetime import datetime, timezone

from app.agents.scoring import clamp
from app.assets import AssetInfo
from app.models import (
    ComponentScores,
    CryptoFundamentalsResult,
    FundamentalsResult,
    NewsAggregationResult,
    SignalCall,
    SynthesizedSignal,
    TechnicalAnalysisResult,
)

_WEIGHTS = {"technical": 0.40, "fundamental": 0.35, "news": 0.25}
_BUY_THRESHOLD = 0.20
_SELL_THRESHOLD = -0.20


def safety_gate_failed(fundamentals: FundamentalsResult) -> bool:
    """Shared with orchestrator.py, which applies this same check as a
    universal override on top of whichever agent produced the signal (this
    formula, or specialist_agent.py's LLM) -- an LLM reading the evidence
    could in principle still say BUY on a failed safety gate if nothing
    enforces the rule outside this class, since it only sees the gate's
    summary as prose, not as a hard constraint it's bound to obey."""
    return (
        isinstance(fundamentals, CryptoFundamentalsResult)
        and fundamentals.safety.has_contract
        and not fundamentals.safety.passed
    )


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

        gate_failed = safety_gate_failed(fundamentals)

        if gate_failed:
            # Hard override, not a weighted vote: a failed on-chain safety
            # gate means skip the trade regardless of how bullish technicals
            # or news look -- exactly the rule the framework was built
            # against. This can flip what the composite score alone would
            # have said.
            signal = SignalCall.HOLD
        elif final_score >= _BUY_THRESHOLD:
            signal = SignalCall.BUY
        elif final_score <= _SELL_THRESHOLD:
            signal = SignalCall.SELL
        else:
            signal = SignalCall.HOLD

        confidence = 0.95 if gate_failed else _confidence(final_score, component_scores)
        reasoning = _build_reasoning(asset, signal, final_score, confidence, technical, fundamentals, news, gate_failed)

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
    safety_gate_failed: bool = False,
) -> str:
    drivers = [
        f"Technical ({technical.sentiment.value}, score {technical.score:+.2f}): {technical.summary}",
        f"Fundamentals ({fundamentals.sentiment.value}, score {fundamentals.score:+.2f}): {fundamentals.summary}",
        f"News ({news.sentiment.value}, score {news.score:+.2f}): {news.summary}",
    ]

    if safety_gate_failed:
        assert isinstance(fundamentals, CryptoFundamentalsResult)
        header = (
            f"{asset.symbol}: {signal.value} -- SAFETY GATE OVERRIDE. "
            f"{' '.join(fundamentals.safety.red_flags)} "
            f"This overrides the composite score (which was {final_score:+.2f}): a failed on-chain safety check "
            f"means skip this trade regardless of what technicals or news say."
        )
        return header + "\n\n" + "\n\n".join(drivers)

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
