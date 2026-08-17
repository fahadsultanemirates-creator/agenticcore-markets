"""Fundamentals for crypto assets: market cap/volume, on-chain activity,
and tokenomics/ecosystem news.
"""

from datetime import datetime, timezone

from app.agents.scoring import clamp, sentiment_from_score
from app.assets import AssetInfo
from app.data_sources.crypto_market import CryptoMarketClient
from app.models import CryptoFundamentalsResult, OnChainMetrics

_POSITIVE_WORDS = ("inflow", "accumulat", "record", "grow", "high demand", "reduc", "tightening")
_NEGATIVE_WORDS = ("outflow", "pressure", "decline", "uncertainty", "compress", "weigh")


class CryptoFundamentalsAgent:
    def __init__(self, crypto_market: CryptoMarketClient | None = None) -> None:
        self._crypto_market = crypto_market or CryptoMarketClient()

    async def analyze(self, asset: AssetInfo) -> CryptoFundamentalsResult:
        snapshot = await self._crypto_market.fetch_market_snapshot(asset)
        onchain = self._crypto_market.fetch_onchain_metrics(asset)
        ecosystem_notes = self._crypto_market.fetch_ecosystem_notes(asset)

        score = clamp(
            _netflow_score(onchain)
            + _turnover_score(snapshot["volume_24h_usd"], snapshot["market_cap_usd"])
            + _ecosystem_score(ecosystem_notes)
        )
        sentiment = sentiment_from_score(score)
        summary = _build_summary(asset, snapshot, onchain, ecosystem_notes, sentiment)

        return CryptoFundamentalsResult(
            symbol=asset.symbol,
            as_of=datetime.now(timezone.utc),
            market_cap_usd=snapshot["market_cap_usd"],
            volume_24h_usd=snapshot["volume_24h_usd"],
            circulating_supply=snapshot["circulating_supply"],
            onchain=onchain,
            ecosystem_notes=ecosystem_notes,
            sentiment=sentiment,
            score=score,
            summary=summary,
        )


def _netflow_score(onchain: OnChainMetrics) -> float:
    # Net outflow from exchanges (negative netflow) is typically read as
    # accumulation/bullish; net inflow suggests potential sell pressure.
    return clamp(-onchain.exchange_netflow_24h / 5000, -0.5, 0.5)


def _turnover_score(volume_24h: float, market_cap: float) -> float:
    if market_cap <= 0:
        return 0.0
    turnover = volume_24h / market_cap
    # Healthy turnover (~3-8%) is mildly bullish (liquid, active market);
    # very low turnover suggests waning interest.
    return clamp((turnover - 0.03) * 3, -0.3, 0.3)


def _ecosystem_score(notes: list[str]) -> float:
    text = " ".join(notes).lower()
    positive_hits = sum(word in text for word in _POSITIVE_WORDS)
    negative_hits = sum(word in text for word in _NEGATIVE_WORDS)
    return clamp((positive_hits - negative_hits) * 0.15, -0.3, 0.3)


def _build_summary(asset: AssetInfo, snapshot: dict, onchain: OnChainMetrics, notes: list[str], sentiment) -> str:
    flow_note = "net outflow from exchanges (accumulation signal)" if onchain.exchange_netflow_24h < 0 else "net inflow to exchanges (potential sell pressure)"
    return (
        f"Market cap ${snapshot['market_cap_usd']:,.0f} with 24h volume ${snapshot['volume_24h_usd']:,.0f}. "
        f"On-chain data shows {onchain.active_addresses_24h:,} active addresses and {flow_note}. "
        f"Ecosystem: {' '.join(notes)}"
    )
