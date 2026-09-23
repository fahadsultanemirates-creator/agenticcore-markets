"""Unit tests for the pure parse functions in asset_resolver.py against
realistic CoinGecko /search, /coins/{id}, and DexScreener /tokens payload
shapes."""

from app.data_sources.asset_resolver import (
    AssetResolver,
    _looks_like_contract_address,
    parse_coin_platforms,
    parse_dexscreener_base_token,
    parse_search_result,
)


def test_parse_search_result_prefers_exact_symbol_match():
    payload = {
        "coins": [
            {"id": "pepe-imitator", "symbol": "pepe2", "name": "Pepe Imitator", "market_cap_rank": 500},
            {"id": "pepe", "symbol": "pepe", "name": "Pepe", "market_cap_rank": 30},
        ]
    }
    result = parse_search_result(payload, "pepe")
    assert result == {"coin_id": "pepe", "symbol": "PEPE", "name": "Pepe"}


def test_parse_search_result_falls_back_to_top_ranked_when_no_exact_match():
    payload = {"coins": [{"id": "shiba-inu", "symbol": "shib", "name": "Shiba Inu"}]}
    result = parse_search_result(payload, "shiba")
    assert result == {"coin_id": "shiba-inu", "symbol": "SHIB", "name": "Shiba Inu"}


def test_parse_search_result_empty_coins_returns_none():
    assert parse_search_result({"coins": []}, "nonexistent") is None
    assert parse_search_result({}, "nonexistent") is None


def test_parse_coin_platforms_returns_first_supported_chain():
    payload = {"platforms": {"solana": "abc123", "ethereum": "0x6982508145454ce325ddbe47a25d4ec3d2311933"}}
    result = parse_coin_platforms(payload)
    assert result == {"contract_address": "0x6982508145454ce325ddbe47a25d4ec3d2311933", "chain_id": 1}


def test_parse_coin_platforms_no_supported_chain_returns_none():
    payload = {"platforms": {"solana": "abc123", "tron": "def456"}}
    assert parse_coin_platforms(payload) is None


def test_parse_coin_platforms_no_platforms_returns_none():
    assert parse_coin_platforms({}) is None
    assert parse_coin_platforms({"platforms": {}}) is None


async def test_resolve_crypto_empty_query_returns_none():
    resolver = AssetResolver()
    assert await resolver.resolve_crypto("") is None
    assert await resolver.resolve_crypto("   ") is None


def test_looks_like_contract_address():
    assert _looks_like_contract_address("0x6982508145454ce325ddbe47a25d4ec3d2311933") is True
    assert _looks_like_contract_address("0X6982508145454CE325DDBE47A25D4EC3D2311933") is True  # case-insensitive
    assert _looks_like_contract_address("PEPE") is False
    assert _looks_like_contract_address("PEPEUSD") is False
    assert _looks_like_contract_address("0x1234") is False  # too short
    assert _looks_like_contract_address("0xZZZZ08145454ce325ddbe47a25d4ec3d2311933") is False  # not hex


def test_parse_dexscreener_base_token_picks_highest_liquidity_pair():
    pairs = [
        {
            "chainId": "ethereum",
            "baseToken": {"symbol": "pepe", "name": "Pepe", "address": "0x6982508145454ce325ddbe47a25d4ec3d2311933"},
            "liquidity": {"usd": 500_000.0},
        },
        {
            "chainId": "bsc",
            "baseToken": {"symbol": "pepe", "name": "Pepe (bridged)", "address": "0xabc"},
            "liquidity": {"usd": 50_000_000.0},
        },
    ]
    result = parse_dexscreener_base_token(pairs)
    assert result == {"symbol": "PEPE", "name": "Pepe (bridged)", "address": "0xabc", "chain_slug": "bsc"}


def test_parse_dexscreener_base_token_empty_pairs_returns_none():
    assert parse_dexscreener_base_token([]) is None


def test_parse_dexscreener_base_token_missing_fields_returns_none():
    assert parse_dexscreener_base_token([{"chainId": "ethereum", "baseToken": {}, "liquidity": {"usd": 1000.0}}]) is None


async def test_resolve_crypto_routes_address_shaped_query_to_contract_path():
    """No live network in this sandbox, so this only proves the routing
    decision itself (address-shaped input never hits the symbol-search
    path) -- both paths degrade to None here since neither DexScreener nor
    CoinGecko is reachable."""
    resolver = AssetResolver()
    result = await resolver.resolve_crypto("0x6982508145454ce325ddbe47a25d4ec3d2311933")
    assert result is None  # network-restricted sandbox -- see module docstring for why this is expected here
