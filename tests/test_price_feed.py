"""Unit tests for the pure parse function in price_feed.py against a
realistic CoinGecko OHLC response shape (list of [ts_ms, o, h, l, c])."""

from app.assets import get_asset
from app.data_sources.price_feed import PriceFeedClient, parse_coingecko_ohlc


def _rows(n: int) -> list:
    base_ts = 1_700_000_000_000
    return [[base_ts + i * 14_400_000, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i] for i in range(n)]


def test_parse_coingecko_ohlc_returns_bars_with_zero_volume():
    bars = parse_coingecko_ohlc(_rows(15))
    assert bars is not None
    assert len(bars) == 15
    assert all(b.volume == 0.0 for b in bars)
    assert bars[0].open == 100.0
    assert bars[0].close == 100.5


def test_parse_coingecko_ohlc_too_short_returns_none():
    assert parse_coingecko_ohlc(_rows(5)) is None


def test_parse_coingecko_ohlc_malformed_returns_none():
    assert parse_coingecko_ohlc({}) is None
    assert parse_coingecko_ohlc(None) is None


async def test_fetch_ohlcv_crypto_without_coingecko_id_falls_back_to_synthetic():
    client = PriceFeedClient()
    # ACUSD has no coingecko_id (too new/small to be indexed) -- must not
    # attempt a CoinGecko call at all, and without a TwelveData key,
    # degrades straight to synthetic data rather than erroring.
    bars = await client.fetch_ohlcv(get_asset("ACUSD"), bars=30)
    assert len(bars) == 30
