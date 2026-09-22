"""Unit tests for the pure parse function in derivatives.py against a
realistic Binance klines payload shape (each row is a 12-element array,
index 5 = volume, index 9 = takerBuyBaseAssetVolume)."""

from app.assets import get_asset
from app.data_sources.derivatives import DerivativesClient, parse_taker_delta


def _kline(volume: float, taker_buy: float) -> list:
    return [0, "0", "0", "0", "0", str(volume), 0, "0", 0, str(taker_buy), "0", "0"]


def test_parse_taker_delta_net_buy():
    klines = [_kline(volume=100, taker_buy=70), _kline(volume=100, taker_buy=65)]
    delta = parse_taker_delta(klines)
    # taker_buy=135, taker_sell=65 across 200 total -> (135-65)/200*100 = 35
    assert abs(delta - 35.0) < 1e-9


def test_parse_taker_delta_net_sell():
    klines = [_kline(volume=100, taker_buy=20)]
    delta = parse_taker_delta(klines)
    assert delta < 0


def test_parse_taker_delta_empty_is_zero():
    assert parse_taker_delta([]) == 0.0


async def test_derivatives_client_synthetic_fallback_shape():
    client = DerivativesClient()
    snapshot = await client.fetch_snapshot(get_asset("BTCUSD"))

    assert set(snapshot.keys()) == {"open_interest_usd", "funding_rate_pct", "perp_taker_delta_pct"}
    assert snapshot["open_interest_usd"] > 0
