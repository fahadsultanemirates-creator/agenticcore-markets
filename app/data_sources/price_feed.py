"""Live OHLCV price feed for forex and crypto (TwelveData), with
deterministic synthetic sample data as a fallback when no API key is
configured. Shared by both asset classes so technical_analysis_agent stays
identical regardless of what it's analyzing.

Also serves two internal-only proxy symbols (XAUUSD, US500USD) that
forex_fundamentals_agent uses purely to read the global risk-on/risk-off
regime -- not real tradable assets, not in app/assets.py's registry.
"""

from datetime import datetime, timedelta, timezone

import httpx

from app.assets import AssetInfo, AssetType
from app.config import settings
from app.data_sources.mock_utils import rng_for
from app.models import OHLCVBar

_BASE_PRICE = {
    # Majors
    "EURUSD": 1.0850, "GBPUSD": 1.2700, "AUDUSD": 0.6600, "NZDUSD": 0.6100,
    "USDCAD": 1.3600, "USDCHF": 0.8800, "USDJPY": 155.00,
    # EUR crosses
    "EURGBP": 0.8540, "EURAUD": 1.6440, "EURNZD": 1.7790, "EURCAD": 1.4760,
    "EURCHF": 0.9550, "EURJPY": 168.20,
    # GBP crosses
    "GBPAUD": 1.9240, "GBPNZD": 2.0810, "GBPCAD": 1.7270, "GBPCHF": 1.1180, "GBPJPY": 196.90,
    # AUD crosses
    "AUDNZD": 1.0820, "AUDCAD": 0.8980, "AUDCHF": 0.5810, "AUDJPY": 102.30,
    # NZD crosses
    "NZDCAD": 0.8300, "NZDCHF": 0.5370, "NZDJPY": 94.55,
    # CAD/CHF crosses
    "CADCHF": 0.6470, "CADJPY": 113.97, "CHFJPY": 176.14,
    # Crypto
    "BTCUSD": 64000.0,
    "ETHUSD": 3400.0,
    "ACUSD": 0.0000001,
    # Commodities
    "XAUUSD": 2650.0,
    "XAGUSD": 31.00,
    "USOILUSD": 70.00,
    "UKOILUSD": 74.00,
    "NATGASUSD": 2.80,
    # Internal-only risk-regime proxy (see forex_fundamentals_agent.py)
    "US500USD": 5900.0,
}

_TWELVEDATA_URL = "https://api.twelvedata.com/time_series"


class PriceFeedClient:
    async def fetch_ohlcv(self, asset: AssetInfo, bars: int = 120, interval: str = "1h") -> list[OHLCVBar]:
        if settings.twelvedata_api_key:
            return await self._fetch_twelvedata(asset, bars, interval)
        return self._synthetic_ohlcv(asset, bars)

    async def _fetch_twelvedata(self, asset: AssetInfo, bars: int, interval: str) -> list[OHLCVBar]:
        td_symbol = f"{asset.base}/{asset.quote}"
        params = {
            "symbol": td_symbol,
            "interval": interval,
            "outputsize": bars,
            "apikey": settings.twelvedata_api_key,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_TWELVEDATA_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()

        values = payload.get("values")
        if not values:
            # Provider hiccup/rate limit: degrade to synthetic data rather
            # than breaking the whole pipeline for one flaky call.
            return self._synthetic_ohlcv(asset, bars)

        bars_out = [
            OHLCVBar(
                timestamp=datetime.fromisoformat(v["datetime"]).replace(tzinfo=timezone.utc),
                open=float(v["open"]),
                high=float(v["high"]),
                low=float(v["low"]),
                close=float(v["close"]),
                volume=float(v.get("volume") or 0.0),
            )
            for v in values
        ]
        return list(reversed(bars_out))  # provider returns newest-first

    def _synthetic_ohlcv(self, asset: AssetInfo, bars: int) -> list[OHLCVBar]:
        rng = rng_for(asset.symbol, "ohlcv")
        base_price = _BASE_PRICE.get(asset.symbol, 100.0)
        if asset.asset_type == AssetType.CRYPTO:
            volatility_pct = 0.006
        elif asset.asset_type == AssetType.COMMODITY:
            volatility_pct = 0.012  # oil/gas in particular are more volatile than forex majors
        else:
            volatility_pct = 0.0015
        volatility = base_price * volatility_pct

        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        price = base_price
        out: list[OHLCVBar] = []
        for i in range(bars):
            ts = now - timedelta(hours=(bars - i))
            drift = rng.uniform(-volatility, volatility)
            open_ = price
            # Floor relative to the asset's own price, not a fixed absolute
            # -- a hardcoded 0.0001 floor would badly distort a sub-cent
            # token like AC (base price 0.0000001), flattening it to 1000x
            # its intended value on almost every bar.
            close = max(base_price * 0.5, open_ + drift)
            high = max(open_, close) + abs(rng.uniform(0, volatility * 0.5))
            low = min(open_, close) - abs(rng.uniform(0, volatility * 0.5))
            volume = rng.uniform(500, 5000) * (10 if asset.asset_type == AssetType.CRYPTO else 1)
            out.append(OHLCVBar(timestamp=ts, open=open_, high=high, low=low, close=close, volume=volume))
            price = close
        return out
