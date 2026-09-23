"""Resolves an arbitrary crypto token symbol/name -- one NOT in the
curated static registry (app/assets.py) -- into an AssetInfo at request
time, via CoinGecko's free, keyless search + coin-detail endpoints. This
is what makes "type any token and get its signal" work per the roadmap,
without pre-registering every token that exists.

Two-step lookup, both high-confidence/well-documented CoinGecko endpoints
(the same /coins/{id} shape crypto_market.py already parses for live
market data):

1. /search?query=<symbol> -- finds the best-matching coin id. Coins come
   back already ranked by relevance/market cap; this additionally prefers
   an exact symbol match, since a query like "pepe" can otherwise match
   many low-cap imitators before the real one.
2. /coins/{id} -- carries `platforms` (contract addresses per chain),
   which is what lets the on-chain safety gate run for a dynamically
   resolved token instead of just skipping it.

Only chains this framework can actually run the safety gate against (the
GoPlus chain_id mapping below) get contract_address/chain_id populated --
a token that only exists on an unmapped chain still resolves and gets
technical/fundamentals/news/signal analysis, just without the safety gate
(has_contract=False, same treatment as BTC/ETH). That's the honest
answer: without a confirmed GoPlus chain_id for that chain, running the
check would be guessing, not checking.
"""

import httpx

from app.assets import AssetInfo, AssetType

_SEARCH_URL = "https://api.coingecko.com/api/v3/search"
_COIN_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}"

# CoinGecko platform slug -> GoPlus/DexScreener chain_id. Only chains
# crypto_safety.py's GoPlus integration is confirmed to support are
# mapped here; an unmapped chain means the safety gate is skipped for
# that token, not guessed at with an unconfirmed chain_id.
_PLATFORM_CHAIN_IDS = {
    "ethereum": 1,
    "binance-smart-chain": 56,
    "polygon-pos": 137,
    "arbitrum-one": 42161,
    "optimistic-ethereum": 10,
    "base": 8453,
    "avalanche": 43114,
    "fantom": 250,
}


def parse_search_result(payload: dict, query: str) -> dict | None:
    """Pure parse of CoinGecko's /search response."""
    coins = payload.get("coins") or []
    if not coins:
        return None
    query_upper = query.upper()
    exact = next((c for c in coins if c.get("symbol", "").upper() == query_upper), None)
    best = exact or coins[0]
    coin_id = best.get("id")
    if not coin_id:
        return None
    return {
        "coin_id": coin_id,
        "symbol": (best.get("symbol") or query_upper).upper(),
        "name": best.get("name") or query_upper,
    }


def parse_coin_platforms(payload: dict) -> dict | None:
    """Pure parse: finds the first platform this framework can actually
    run the safety gate against among a coin's listed contract addresses.
    Returns None when the token isn't on any confirmed-supported chain --
    not "no contract exists," just "not one we can check here"."""
    platforms = payload.get("platforms") or {}
    for platform_slug, chain_id in _PLATFORM_CHAIN_IDS.items():
        address = platforms.get(platform_slug)
        if address:
            return {"contract_address": address, "chain_id": chain_id}
    return None


class AssetResolver:
    async def resolve_crypto(self, query: str) -> AssetInfo | None:
        query = query.strip()
        if not query:
            return None
        # Accept either a bare symbol ("PEPE") or one already in this app's
        # BASEQUOTE convention ("PEPEUSD") -- strip a trailing USD so the
        # CoinGecko search term is the actual token symbol either way.
        search_term = query[:-3] if query.upper().endswith("USD") and len(query) > 3 else query

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                search_resp = await client.get(_SEARCH_URL, params={"query": search_term})
                search_resp.raise_for_status()
                match = parse_search_result(search_resp.json(), search_term)
                if match is None:
                    return None

                coin_resp = await client.get(
                    _COIN_URL.format(coin_id=match["coin_id"]),
                    params={
                        "localization": "false",
                        "tickers": "false",
                        "market_data": "false",
                        "community_data": "false",
                        "developer_data": "false",
                    },
                )
                coin_resp.raise_for_status()
                platform = parse_coin_platforms(coin_resp.json())
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

        return AssetInfo(
            symbol=f"{match['symbol']}USD",
            display_name=f"{match['name']} / US Dollar",
            asset_type=AssetType.CRYPTO,
            base=match["symbol"],
            quote="USD",
            contract_address=platform["contract_address"] if platform else None,
            chain_id=platform["chain_id"] if platform else None,
            coingecko_id=match["coin_id"],
            is_dynamic=True,
        )
