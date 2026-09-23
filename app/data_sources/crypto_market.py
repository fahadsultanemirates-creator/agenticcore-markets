"""Crypto market data (CoinGecko/CoinMarketCap) + on-chain metrics for
crypto_fundamentals_agent, with deterministic synthetic data fallback.
"""

import httpx

from app.assets import AssetInfo
from app.config import settings
from app.data_sources.mock_utils import rng_for
from app.models import OnChainMetrics

_COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}"
_COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"

_BASE_MARKET_CAP = {
    "BTC": 1_260_000_000_000.0,
    "ETH": 410_000_000_000.0,
}

_BASE_FDV_MULTIPLIER = {
    # BTC/ETH have no meaningful FDV gap (supply is ~fully circulating or
    # uncapped-but-not-inflationary in a way that matters here) -- keep the
    # synthetic fallback realistic rather than fabricating a dilution story.
    "BTC": 1.02,
    "ETH": 1.0,
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
        # CoinGecko's basic market-data endpoint is keyless-usable (the
        # setting only raises the rate limit when present) -- unlike
        # TwelveData, there's no reason to gate the live attempt behind
        # having a key at all, only to fall back gracefully if it fails.
        # coingecko_id is set statically for the curated majors (see
        # assets.py) and dynamically by asset_resolver.py for any other
        # token resolved at request time -- either way, no live call is
        # attempted for an asset it was never determined for.
        if asset.coingecko_id is None:
            return self._synthetic_market_snapshot(asset)
        try:
            return await self._fetch_coingecko(asset, asset.coingecko_id)
        except (httpx.HTTPError, ValueError, KeyError):
            return self._synthetic_market_snapshot(asset)

    async def _fetch_coingecko(self, asset: AssetInfo, coin_id: str) -> dict:
        url = _COINGECKO_URL.format(coin_id=coin_id)
        headers = {"x-cg-demo-api-key": settings.coingecko_api_key} if settings.coingecko_api_key else {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params={"localization": "false", "market_data": "true"})
            resp.raise_for_status()
            payload = resp.json()

        market = payload.get("market_data", {})
        market_cap = float(market.get("market_cap", {}).get("usd", 0.0))
        fdv = market.get("fully_diluted_valuation", {}).get("usd")
        return {
            "market_cap_usd": market_cap,
            "volume_24h_usd": float(market.get("total_volume", {}).get("usd", 0.0)),
            "circulating_supply": float(market.get("circulating_supply", 0.0)),
            "fdv_usd": float(fdv) if fdv else market_cap,
        }

    def _synthetic_market_snapshot(self, asset: AssetInfo) -> dict:
        rng = rng_for(asset.symbol, "market")
        base_cap = _BASE_MARKET_CAP.get(asset.base, 5_000_000_000.0)
        market_cap = base_cap * rng.uniform(0.95, 1.05)
        fdv_multiplier = _BASE_FDV_MULTIPLIER.get(asset.base, rng.uniform(1.2, 3.0))
        return {
            "market_cap_usd": market_cap,
            "volume_24h_usd": market_cap * rng.uniform(0.02, 0.08),
            "circulating_supply": _CIRCULATING_SUPPLY.get(asset.base, 100_000_000.0),
            "fdv_usd": market_cap * fdv_multiplier,
        }

    async def fetch_btc_dominance(self) -> float:
        """BTC's share of total crypto market cap -- the macro backdrop
        criterion ("over 80% of altcoins move with BTC's swings")."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(_COINGECKO_GLOBAL_URL)
                resp.raise_for_status()
                payload = resp.json()
            return float(payload["data"]["market_cap_percentage"]["btc"])
        except (httpx.HTTPError, ValueError, KeyError):
            return rng_for("GLOBAL", "btc_dominance").uniform(48.0, 58.0)

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
