"""Live OHLCV price feed for forex/commodities (TwelveData) and crypto
(CoinGecko's OHLC endpoint, tried first -- broader token coverage than
TwelveData, which is forex-oriented and doesn't carry the long tail of
crypto tokens), with deterministic synthetic sample data as the final
fallback. Shared by all three asset classes so technical_analysis_agent
stays identical regardless of what it's analyzing.

Also serves two internal-only proxy symbols (XAUUSD, US500USD) that
forex_fundamentals_agent/commodity_fundamentals_agent use purely to read
the global risk-on/risk-off regime -- not real tradable assets, not in
app/assets.py's registry.
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

def parse_coingecko_ohlc(rows: object) -> list[OHLCVBar] | None:
    """Pure parse of CoinGecko's OHLC response: a list of
    [timestamp_ms, open, high, low, close] rows, oldest first. Returns
    None for a malformed or suspiciously short (<10 bars) response --
    treated by the caller as "try the next source", not as an error."""
    if not isinstance(rows, list) or len(rows) < 10:
        return None
    return [
        OHLCVBar(
            timestamp=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=0.0,
        )
        for row in rows
    ]


_TWELVEDATA_URL = "https://api.twelvedata.com/time_series"
_COINGECKO_OHLC_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
# CoinGecko's free-tier OHLC endpoint returns coarser candles the further
# back you ask (roughly: 30-min candles for 1-2 days, 4-hour for up to 30
# days, 4-day beyond that) -- 30 days of 4-hour candles is the best
# density/lookback tradeoff available for a meaningful 50/200-period EMA
# without falling into the multi-day tier. The exact day-range cutoffs
# weren't verified against a live response before this was written
# (moderate confidence, unlike the well-documented base market-data
# endpoint already used elsewhere in this codebase) -- handled defensively
# below rather than assuming a specific bar count.
_COINGECKO_OHLC_DAYS = 30


class PriceFeedClient:
    async def fetch_ohlcv(self, asset: AssetInfo, bars: int = 120, interval: str = "1h") -> list[OHLCVBar]:
        if asset.asset_type == AssetType.CRYPTO:
            coingecko_bars = await self._fetch_coingecko_ohlc(asset)
            if coingecko_bars:
                return coingecko_bars
        if settings.twelvedata_api_key:
            return await self._fetch_twelvedata(asset, bars, interval)
        return self._synthetic_ohlcv(asset, bars)

    async def _fetch_coingecko_ohlc(self, asset: AssetInfo) -> list[OHLCVBar] | None:
        """Tried first for crypto, keyless, regardless of whether
        TWELVEDATA_API_KEY is set -- CoinGecko covers far more tokens than
        TwelveData. Only usable when coingecko_id is known (set statically
        for curated majors, or dynamically by asset_resolver.py). Returns
        None (not a fabricated bar list) on any failure or a suspiciously
        short response, so the caller falls through to its next source.

        Does NOT include volume -- this endpoint doesn't return it. Bars
        from this source carry volume=0.0, which volume_profile_poc treats
        as "no real volume data" and degrades to a neutral fallback rather
        than a misleading result.
        """
        if not asset.coingecko_id:
            return None
        try:
            url = _COINGECKO_OHLC_URL.format(coin_id=asset.coingecko_id)
            headers = {"x-cg-demo-api-key": settings.coingecko_api_key} if settings.coingecko_api_key else {}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers, params={"vs_currency": "usd", "days": _COINGECKO_OHLC_DAYS})
                resp.raise_for_status()
                rows = resp.json()
            return parse_coingecko_ohlc(rows)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return None

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
