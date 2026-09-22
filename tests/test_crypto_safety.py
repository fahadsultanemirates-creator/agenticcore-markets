"""Unit tests for the pure parse functions in crypto_safety.py against
realistic sample payloads shaped like GoPlus/DexScreener's actual documented
response formats (GoPlus in particular returns numeric/boolean fields as
strings -- a real, well-known quirk of that API, not a typo here)."""

from app.data_sources.crypto_safety import CryptoSafetyClient, parse_dexscreener_pairs, parse_goplus_result
from app.assets import get_asset


def test_parse_goplus_result_clean_token():
    raw = {
        "is_open_source": "1",
        "is_mintable": "0",
        "is_honeypot": "0",
        "is_blacklisted": "0",
        "transfer_pausable": "0",
        "buy_tax": "0.01",
        "sell_tax": "0.01",
        "holder_count": "5000",
        "holders": [
            {"address": "0xaaa", "is_contract": 0, "percent": "0.05"},
            {"address": "0xbbb", "is_contract": 0, "percent": "0.03"},
            {"address": "0xlp1", "is_contract": 1, "percent": "0.40"},  # LP pool, excluded from whale check
        ],
    }
    parsed = parse_goplus_result(raw)

    assert parsed["is_honeypot"] is False
    assert parsed["is_mintable"] is False
    assert parsed["is_blacklistable"] is False
    assert parsed["is_open_source"] is True
    assert parsed["buy_tax_pct"] == 1.0
    assert parsed["sell_tax_pct"] == 1.0
    assert parsed["holder_count"] == 5000
    # Only the two individual (non-contract) holders count toward
    # concentration -- the LP pool's 40% is excluded.
    assert abs(parsed["top10_holder_pct"] - 8.0) < 1e-9


def test_parse_goplus_result_flags_honeypot_and_mintable():
    raw = {
        "is_honeypot": "1",
        "is_mintable": "1",
        "is_blacklisted": "1",
        "buy_tax": "0.25",
        "sell_tax": "0.99",
        "holder_count": "12",
        "holders": [],
    }
    parsed = parse_goplus_result(raw)

    assert parsed["is_honeypot"] is True
    assert parsed["is_mintable"] is True
    assert parsed["is_blacklistable"] is True
    assert parsed["sell_tax_pct"] == 99.0


def test_parse_dexscreener_pairs_picks_highest_liquidity():
    pairs = [
        {"dexId": "thin-dex", "liquidity": {"usd": 5_000}, "fdv": 1_000_000, "marketCap": 900_000, "volume": {"h24": 10_000}},
        {"dexId": "main-dex", "liquidity": {"usd": 500_000}, "fdv": 1_000_000, "marketCap": 900_000, "volume": {"h24": 300_000}},
    ]
    parsed = parse_dexscreener_pairs(pairs)

    assert parsed is not None
    assert parsed["dex_id"] == "main-dex"
    assert parsed["liquidity_usd"] == 500_000


def test_parse_dexscreener_pairs_empty_list_returns_none():
    assert parse_dexscreener_pairs([]) is None


async def test_crypto_safety_client_synthetic_fallback_shape_for_ac_token():
    """No live GoPlus/DexScreener reachable in this environment (and even
    where they are, this asserts the contract shape regardless) -- either
    way fetch_token_security/fetch_liquidity must return the expected keys."""
    client = CryptoSafetyClient()
    asset = get_asset("ACUSD")

    security = await client.fetch_token_security(asset)
    liquidity = await client.fetch_liquidity(asset)

    assert security is not None
    assert set(security.keys()) >= {"is_honeypot", "is_mintable", "top10_holder_pct", "holder_count"}
    assert liquidity is not None
    assert set(liquidity.keys()) >= {"liquidity_usd", "fdv_usd", "market_cap_usd"}


async def test_crypto_safety_client_none_for_asset_without_contract():
    client = CryptoSafetyClient()
    asset = get_asset("BTCUSD")

    assert await client.fetch_token_security(asset) is None
    assert await client.fetch_liquidity(asset) is None
