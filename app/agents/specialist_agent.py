"""Specialist LLM agent: takes everything the deterministic pipeline
already computed (technical incl. persistent S/R memory, fundamentals,
news) and produces the actual final verdict -- a real judgment call from
an LLM reading the evidence, not a template narrating a fixed formula.
Per the explicit design decision: the LLM makes the final BUY/SELL/HOLD
call itself, weighing conflicting signals with judgment a fixed weighted
average can't.

Two providers, chosen per request by the caller (e.g. free/demo tier ->
Gemini, paid tier -> Claude) via SpecialistAgent.synthesize(...,
provider=...):

- Claude (claude-opus-5 by default): official `anthropic` SDK,
  `client.messages.parse()` with a Pydantic output schema -- the
  documented, high-confidence structured-output pattern for this SDK.
- Gemini (gemini-2.5-flash by default): official `google-genai` SDK.
  MODERATE confidence on the exact structured-output parameter shape --
  Gemini isn't covered by this project's Claude-focused reference
  material, so this tries schema-constrained JSON first and falls back to
  parsing JSON out of plain text on any failure, the same defensive
  discipline this codebase already applies to its other moderate-
  confidence integrations (ECB, DefiLlama).

Neither provider is called if its key isn't configured, or if the call
fails for any reason -- callers (orchestrator.py) fall back to the
existing deterministic signal_synthesis_agent, which never depends on an
LLM at all. This is a hard requirement, not a nicety: a trading-signal
service can't go down because an LLM provider had an outage.
"""

import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from app.assets import AssetInfo
from app.config import settings
from app.models import ComponentScores, FundamentalsResult, NewsAggregationResult, SignalCall, SynthesizedSignal, TechnicalAnalysisResult

_SYSTEM_PROMPT = (
    "You are a specialist trading analyst. You will be given real computed technical, fundamental, and news "
    "data for one asset -- including a persistent support/resistance memory system that tracks how many times "
    "each price level has actually been tested and whether it held or broke. Weigh the evidence yourself, "
    "including any conflicts between technical structure and fundamentals, and give a final BUY, SELL, or HOLD "
    "call with your own reasoning. Do not just restate the numbers back -- explain what they mean together and "
    "why they lead to your call. If the evidence is thin or contradictory, say so plainly and prefer HOLD. "
    "confidence must be a number from 0.0 to 1.0."
)


class _Verdict(BaseModel):
    signal: Literal["BUY", "SELL", "HOLD"]
    confidence: float
    reasoning: str


def _build_evidence_prompt(
    asset: AssetInfo,
    technical: TechnicalAnalysisResult,
    fundamentals: FundamentalsResult,
    news: NewsAggregationResult,
) -> str:
    return "\n".join(
        [
            f"Asset: {asset.symbol} ({asset.asset_type.value})",
            "",
            f"TECHNICAL (computed sentiment: {technical.sentiment.value}, score {technical.score:+.2f}):",
            technical.summary,
            "",
            f"FUNDAMENTALS (computed sentiment: {fundamentals.sentiment.value}, score {fundamentals.score:+.2f}):",
            fundamentals.summary,
            "",
            f"NEWS (computed sentiment: {news.sentiment.value}, score {news.score:+.2f}):",
            news.summary,
        ]
    )


class SpecialistAgent:
    async def synthesize(
        self,
        asset: AssetInfo,
        technical: TechnicalAnalysisResult,
        fundamentals: FundamentalsResult,
        news: NewsAggregationResult,
        provider: Literal["gemini", "claude"],
    ) -> SynthesizedSignal | None:
        """Returns None (never a fabricated verdict) when the requested
        provider's key isn't configured or the call fails for any reason
        -- the caller is expected to fall back to signal_synthesis_agent."""
        evidence = _build_evidence_prompt(asset, technical, fundamentals, news)
        verdict = await self._call_claude(evidence) if provider == "claude" else await self._call_gemini(evidence)
        if verdict is None:
            return None

        return SynthesizedSignal(
            symbol=asset.symbol,
            asset_type=asset.asset_type,
            as_of=datetime.now(timezone.utc),
            signal=SignalCall(verdict.signal),
            confidence=max(0.0, min(1.0, verdict.confidence)),
            component_scores=ComponentScores(technical=technical.score, fundamental=fundamentals.score, news=news.score),
            reasoning=verdict.reasoning,
        )

    async def _call_claude(self, evidence: str) -> _Verdict | None:
        if not settings.anthropic_api_key:
            return None
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            response = await client.messages.parse(
                model=settings.anthropic_model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": evidence}],
                output_format=_Verdict,
            )
            return response.parsed_output
        except Exception:
            # Broad by design: any SDK/network/parsing failure here must
            # degrade to the deterministic fallback, never crash the
            # analysis pipeline or surface a raw LLM-provider error.
            return None

    async def _call_gemini(self, evidence: str) -> _Verdict | None:
        if not settings.gemini_api_key:
            return None
        try:
            return await self._call_gemini_structured(evidence)
        except Exception:
            return await self._call_gemini_plain_text_fallback(evidence)

    async def _call_gemini_structured(self, evidence: str) -> _Verdict | None:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=f"{_SYSTEM_PROMPT}\n\n{evidence}",
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=_Verdict),
        )
        return _Verdict.model_validate_json(response.text)

    async def _call_gemini_plain_text_fallback(self, evidence: str) -> _Verdict | None:
        """Used when the schema-constrained call above fails for any
        reason (e.g. a parameter this SDK version doesn't accept) --
        asks for JSON directly in the prompt and parses it defensively."""
        try:
            from google import genai

            client = genai.Client(api_key=settings.gemini_api_key)
            prompt = (
                f"{_SYSTEM_PROMPT}\n\n{evidence}\n\n"
                'Respond with ONLY a JSON object, no other text: '
                '{"signal": "BUY" or "SELL" or "HOLD", "confidence": <0.0-1.0>, "reasoning": "<string>"}'
            )
            response = await client.aio.models.generate_content(model=settings.gemini_model, contents=prompt)
            text = response.text.strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:]
            return _Verdict.model_validate(json.loads(text.strip()))
        except Exception:
            return None
