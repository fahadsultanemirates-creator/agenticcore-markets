"""Wires the five agents together per asset, running the independent ones
concurrently, and fronts the whole pipeline with the shared cache layer so
concurrent subscribers requesting the same symbol share one computation.
"""

import asyncio
from datetime import datetime, timezone

from app.agents.crypto_fundamentals_agent import CryptoFundamentalsAgent
from app.agents.forex_fundamentals_agent import ForexFundamentalsAgent
from app.agents.news_aggregation_agent import NewsAggregationAgent
from app.agents.signal_synthesis_agent import SignalSynthesisAgent
from app.agents.technical_analysis_agent import TechnicalAnalysisAgent
from app.assets import AssetType, get_asset
from app.cache.cache_layer import TTLCache
from app.config import settings
from app.models import AssetAnalysis


class AnalysisOrchestrator:
    def __init__(self) -> None:
        self._technical_agent = TechnicalAnalysisAgent()
        self._forex_fundamentals_agent = ForexFundamentalsAgent()
        self._crypto_fundamentals_agent = CryptoFundamentalsAgent()
        self._news_agent = NewsAggregationAgent()
        self._signal_agent = SignalSynthesisAgent()
        self._cache: TTLCache[AssetAnalysis] = TTLCache(ttl_seconds=settings.analysis_cache_ttl_seconds)

    async def get_analysis(self, symbol: str) -> AssetAnalysis:
        asset = get_asset(symbol)  # raises KeyError for unsupported symbols

        async def compute() -> AssetAnalysis:
            fundamentals_agent = (
                self._forex_fundamentals_agent if asset.asset_type == AssetType.FOREX else self._crypto_fundamentals_agent
            )
            technical, fundamentals, news = await asyncio.gather(
                self._technical_agent.analyze(asset),
                fundamentals_agent.analyze(asset),
                self._news_agent.analyze(asset),
            )
            signal = self._signal_agent.synthesize(asset, technical, fundamentals, news)

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

        result, was_cached = await self._cache.get_or_compute(asset.symbol, compute)
        return result.model_copy(update={"cached": was_cached})


# Single shared instance: one cache, reused across requests within the process.
orchestrator = AnalysisOrchestrator()
