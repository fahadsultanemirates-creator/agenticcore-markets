"""Crypto market data (CoinGecko/CoinMarketCap) + on-chain metrics for
crypto_fundamentals_agent, with deterministic synthetic data fallback.
"""

import httpx

from app.assets import AssetInfo
from app.config import settings
from app.data_sources.mock_utils import rng_for
from app.models import OnChainMetrics

_COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}"

_COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
}

_BASE_MARKET_CAP = {
    "BTC": 1_260_000_000_000.0,
    "ETH": 410_000_000_000.0,
}

_CIRCULATING_SUPPLY = {
    "BTC": 19_700_000.0,
    "ETH": 120_300_000.0,
}

_ECOSYSTEM_NOTES = {
    "BTC": [
        "Spot ETF inflows have been a persistent net-positive demand source in recent weeks.",
        "Miner reserves continue a slow decline post-halving, tightening exchange-available supply.",
    ],
    "ETH": [
        "Layer-2 activity continues to grow, though it draws fee revenue away from L1.",
        "Staking participation remains high, reducing liquid circulating supply.",
    ],
}


class CryptoMarketClient:
    async def fetch_market_snapshot(self, asset: AssetInfo) -> dict:
        if settings.coingecko_api_key:
            return await self._fetch_coingecko(asset)
        return self._synthetic_market_snapshot(asset)

    async def _fetch_coingecko(self, asset: AssetInfo) -> dict:
        coin_id = _COINGECKO_IDS.get(asset.base)
        if coin_id is None:
            return self._synthetic_market_snapshot(asset)

        url = _COINGECKO_URL.format(coin_id=coin_id)
        headers = {"x-cg-demo-api-key": settings.coingecko_api_key} if settings.coingecko_api_key else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params={"localization": "false", "market_data": "true"})
            resp.raise_for_status()
            payload = resp.json()

        market = payload.get("market_data", {})
        return {
            "market_cap_usd": float(market.get("market_cap", {}).get("usd", 0.0)),
            "volume_24h_usd": float(market.get("total_volume", {}).get("usd", 0.0)),
            "circulating_supply": float(market.get("circulating_supply", 0.0)),
        }

    def _synthetic_market_snapshot(self, asset: AssetInfo) -> dict:
        rng = rng_for(asset.symbol, "market")
        base_cap = _BASE_MARKET_CAP.get(asset.base, 5_000_000_000.0)
        market_cap = base_cap * rng.uniform(0.95, 1.05)
        return {
            "market_cap_usd": market_cap,
            "volume_24h_usd": market_cap * rng.uniform(0.02, 0.08),
            "circulating_supply": _CIRCULATING_SUPPLY.get(asset.base, 100_000_000.0),
        }

    def fetch_onchain_metrics(self, asset: AssetInfo) -> OnChainMetrics:
        # No on-chain data provider wired in yet (candidates: Glassnode,
        # IntoTheBlock). Synthetic values keep crypto_fundamentals_agent
        # exercising the same shape a live provider would return.
        rng = rng_for(asset.symbol, "onchain")
        return OnChainMetrics(
            active_addresses_24h=rng.randint(200_000, 1_100_000),
            transaction_count_24h=rng.randint(250_000, 900_000),
            exchange_netflow_24h=rng.uniform(-5000, 5000),
        )

    def fetch_ecosystem_notes(self, asset: AssetInfo) -> list[str]:
        return _ECOSYSTEM_NOTES.get(asset.base, [f"No notable ecosystem developments flagged for {asset.base}."])
