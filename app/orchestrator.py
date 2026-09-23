"""Wires the five agents together per asset, running the independent ones
concurrently, and fronts the whole pipeline with the shared cache layer so
concurrent subscribers requesting the same symbol share one computation.
"""

import asyncio
from datetime import datetime, timezone
from typing import Literal

from app.agents.commodity_fundamentals_agent import CommodityFundamentalsAgent
from app.agents.crypto_fundamentals_agent import CryptoFundamentalsAgent
from app.agents.forex_fundamentals_agent import ForexFundamentalsAgent
from app.agents.news_aggregation_agent import NewsAggregationAgent
from app.agents.signal_synthesis_agent import SignalSynthesisAgent, safety_gate_failed
from app.agents.specialist_agent import SpecialistAgent
from app.agents.technical_analysis_agent import TechnicalAnalysisAgent
from app.assets import AssetType, get_asset, is_supported
from app.cache.cache_layer import TTLCache
from app.config import settings
from app.data_sources.asset_resolver import AssetResolver
from app.models import AssetAnalysis, FundamentalsResult, SignalCall, SynthesizedSignal


class AnalysisOrchestrator:
    def __init__(self) -> None:
        self._technical_agent = TechnicalAnalysisAgent()
        self._forex_fundamentals_agent = ForexFundamentalsAgent()
        self._crypto_fundamentals_agent = CryptoFundamentalsAgent()
        self._commodity_fundamentals_agent = CommodityFundamentalsAgent()
        self._news_agent = NewsAggregationAgent()
        self._signal_agent = SignalSynthesisAgent()
        self._specialist_agent = SpecialistAgent()
        self._asset_resolver = AssetResolver()
        self._cache: TTLCache[AssetAnalysis] = TTLCache(ttl_seconds=settings.analysis_cache_ttl_seconds)

    async def get_analysis(self, symbol: str, model: Literal["gemini", "claude"] | None = None) -> AssetAnalysis:
        if is_supported(symbol):
            asset = get_asset(symbol)
        else:
            # Not in the curated registry (28 forex majors, BTC/ETH/AC,
            # 5 commodities) -- forex and commodities are a closed universe,
            # so this only makes sense as a crypto token lookup. Resolve it
            # live via CoinGecko/DexScreener; a genuinely unknown/misspelled
            # symbol still raises KeyError, same contract as before.
            resolved = await self._asset_resolver.resolve_crypto(symbol)
            if resolved is None:
                raise KeyError(f"Unknown or unsupported symbol: {symbol}")
            asset = resolved

        async def compute() -> AssetAnalysis:
            if asset.asset_type == AssetType.FOREX:
                fundamentals_agent = self._forex_fundamentals_agent
            elif asset.asset_type == AssetType.COMMODITY:
                fundamentals_agent = self._commodity_fundamentals_agent
            else:
                fundamentals_agent = self._crypto_fundamentals_agent
            technical, fundamentals, news = await asyncio.gather(
                self._technical_agent.analyze(asset),
                fundamentals_agent.analyze(asset),
                self._news_agent.analyze(asset),
            )

            signal = None
            if model is not None:
                signal = await self._specialist_agent.synthesize(asset, technical, fundamentals, news, provider=model)
            if signal is None:
                # No model requested, no key configured for the requested
                # provider, or the LLM call failed -- the deterministic
                # formula never depends on an LLM being available at all.
                signal = self._signal_agent.synthesize(asset, technical, fundamentals, news)
            else:
                # signal_synthesis_agent enforces the safety-gate hard
                # override internally, but the specialist LLM path above
                # doesn't -- it only ever SEES the gate's failure as prose
                # in the fundamentals summary, nothing stops it from still
                # saying BUY if it judges the rest of the evidence bullish
                # enough. This is the same "skip the trade regardless of
                # chart patterns" rule from the framework; it has to be
                # unconditional, not just a strong suggestion in the
                # prompt, so it's re-applied here on top of whichever path
                # produced the signal.
                signal = _apply_safety_gate_override(fundamentals, signal)

            return AssetAnalysis(
                symbol=asset.symbol,
                asset_type=asset.asset_type,
                generated_at=datetime.now(timezone.utc),
                cached=False,
                technical=technical,
                fundamentals=fundamentals,
                news=news,
                signal=signal,
            )

        # The model choice must be part of the cache key -- otherwise a
        # "claude" request and a "gemini" request for the same symbol
        # within the same TTL window would collide, and whichever one
        # asked first would silently serve its answer to the other.
        cache_key = f"{asset.symbol}:{model or 'formula'}"
        result, was_cached = await self._cache.get_or_compute(cache_key, compute)
        return result.model_copy(update={"cached": was_cached})


def _apply_safety_gate_override(fundamentals: FundamentalsResult, signal: SynthesizedSignal) -> SynthesizedSignal:
    """Forces HOLD when the on-chain safety gate failed, regardless of
    what the specialist LLM decided -- a no-op if it already agreed (the
    common case) or if the gate didn't fail at all."""
    if signal.signal == SignalCall.HOLD or not safety_gate_failed(fundamentals):
        return signal
    override_note = (
        f"\n\nSAFETY GATE OVERRIDE: the on-chain safety gate failed ({' '.join(fundamentals.safety.red_flags)}) "
        f"-- this forces the signal to HOLD regardless of the specialist agent's {signal.signal.value} call above. "
        "A failed safety gate means skip this trade regardless of what the rest of the analysis says; that's not "
        "negotiable by model judgment."
    )
    return signal.model_copy(
        update={"signal": SignalCall.HOLD, "confidence": max(signal.confidence, 0.95), "reasoning": signal.reasoning + override_note}
    )


# Single shared instance: one cache, reused across requests within the process.
orchestrator = AnalysisOrchestrator()
