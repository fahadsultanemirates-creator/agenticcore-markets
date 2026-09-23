"""Unit tests for the pure parse functions in asset_resolver.py against
realistic CoinGecko /search and /coins/{id} payload shapes."""

from app.data_sources.asset_resolver import AssetResolver, parse_coin_platforms, parse_search_result


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
