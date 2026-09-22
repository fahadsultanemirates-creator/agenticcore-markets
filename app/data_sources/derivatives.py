"""Futures positioning for crypto: open interest + funding rate + a taker
buy/sell volume delta standing in for full CVD, via Binance's public futures
API (keyless -- no BINANCE_API_KEY setting exists on purpose, market-data
endpoints don't require one).

Only meaningful for assets actually listed on Binance Futures -- a small or
brand-new token (like AgenticCore's own AC) legitimately isn't, and that
404/empty response is expected, not a bug: it degrades to synthetic the same
way an unsupported CoinGecko id already does in crypto_market.py.
"""

import httpx

from app.assets import AssetInfo
from app.data_sources.mock_utils import rng_for

_OPEN_INTEREST_URL = "https://fapi.binance.com/fapi/v1/openInterest"
_PREMIUM_INDEX_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"


def parse_taker_delta(klines: list[list]) -> float:
    """Pure parse: net taker-buy volume as a percentage of total taker
    volume across the given klines, from Binance's own
    takerBuyBaseAssetVolume field (index 9) vs. total volume (index 5).
    Positive = buyers net-aggressive (bullish flow), negative = sellers."""
    total_volume = 0.0
    taker_buy = 0.0
    for k in klines:
        total_volume += float(k[5])
        taker_buy += float(k[9])
    if total_volume <= 0:
        return 0.0
    taker_sell = total_volume - taker_buy
    return (taker_buy - taker_sell) / total_volume * 100


class DerivativesClient:
    def _perp_symbol(self, asset: AssetInfo) -> str:
        return f"{asset.base}USDT"

    async def fetch_snapshot(self, asset: AssetInfo) -> dict:
        symbol = self._perp_symbol(asset)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                oi_resp, premium_resp, klines_resp = await client.get(
                    _OPEN_INTEREST_URL, params={"symbol": symbol}
                ), await client.get(_PREMIUM_INDEX_URL, params={"symbol": symbol}), await client.get(
                    _KLINES_URL, params={"symbol": symbol, "interval": "1h", "limit": 24}
                )
                oi_resp.raise_for_status()
                premium_resp.raise_for_status()
                klines_resp.raise_for_status()

            open_interest_contracts = float(oi_resp.json()["openInterest"])
            mark_price = float(premium_resp.json()["markPrice"])
            funding_rate_pct = float(premium_resp.json()["lastFundingRate"]) * 100
            taker_delta_pct = parse_taker_delta(klines_resp.json())

            return {
                "open_interest_usd": open_interest_contracts * mark_price,
                "funding_rate_pct": funding_rate_pct,
                "perp_taker_delta_pct": taker_delta_pct,
            }
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return self._synthetic_snapshot(asset)

    def _synthetic_snapshot(self, asset: AssetInfo) -> dict:
        rng = rng_for(asset.symbol, "derivatives")
        return {
            "open_interest_usd": rng.uniform(50_000_000, 5_000_000_000),
            "funding_rate_pct": rng.uniform(-0.05, 0.05),
            "perp_taker_delta_pct": rng.uniform(-15, 15),
        }
