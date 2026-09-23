"""Resolves an arbitrary crypto token -- one NOT in the curated static
registry (app/assets.py) -- into an AssetInfo at request time. This is
what makes "type any token and get its signal" work per the roadmap,
without pre-registering every token that exists. Two independent entry
points, chosen by what the caller typed:

1. A symbol/name ("PEPE", "PEPEUSD") -- resolved via CoinGecko's free,
   keyless /search + /coins/{id} endpoints (the same /coins/{id} shape
   crypto_market.py already parses for live market data). /search finds
   the best-matching coin id (preferring an exact symbol match, since a
   query like "pepe" can otherwise match many low-cap imitators before
   the real one); /coins/{id} carries `platforms` (contract addresses per
   chain). This path only finds tokens CoinGecko has already indexed.

2. A raw contract address ("0x...", 42 hex chars) -- resolved DIRECTLY via
   DexScreener's /tokens/{address} endpoint instead, which queries the
   chain/DEX itself rather than any index. This covers a token that's
   real and has DEX liquidity but is too new or too small for CoinGecko
   to have indexed yet -- the gap the symbol-search path can't close by
   itself. A CoinGecko id is still opportunistically looked up afterward
   (via /coins/{platform}/contract/{address}) so live market-cap/OHLC data
   works too if it happens to be indexed; failing that enrichment doesn't
   fail the resolution, it just means market/technical data for that
   token stays synthetic while safety/liquidity (which don't need
   CoinGecko at all) are still real.

Only chains this framework can actually run the safety gate against (the
chain_id mappings below) get contract_address/chain_id populated -- a
token on an unmapped chain still resolves and gets full
technical/fundamentals/news/signal analysis, just without the safety gate
(has_contract=False, same treatment as BTC/ETH). That's the honest
answer: without a confirmed chain_id for that chain, running the check
would be guessing, not checking.
"""

import httpx

from app.assets import AssetInfo, AssetType

_SEARCH_URL = "https://api.coingecko.com/api/v3/search"
_COIN_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}"
_DEXSCREENER_TOKENS_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"
_COINGECKO_CONTRACT_URL = "https://api.coingecko.com/api/v3/coins/{platform}/contract/{address}"

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
_CHAIN_ID_TO_COINGECKO_PLATFORM = {chain_id: slug for slug, chain_id in _PLATFORM_CHAIN_IDS.items()}

# DexScreener's own chainId slugs -- a DIFFERENT naming convention than
# CoinGecko's platform slugs above (e.g. "bsc" vs. "binance-smart-chain"),
# confirmed against DexScreener's public API/docs for these chains only.
_DEXSCREENER_CHAIN_IDS = {
    "ethereum": 1,
    "bsc": 56,
    "polygon": 137,
    "arbitrum": 42161,
    "optimism": 10,
    "base": 8453,
    "avalanche": 43114,
    "fantom": 250,
}


def _looks_like_contract_address(query: str) -> bool:
    """A standard EVM address: 0x followed by exactly 40 hex characters
    (case-insensitive -- a pasted address may be all-lowercase, all-caps,
    or EIP-55 mixed-case checksum)."""
    if not query.lower().startswith("0x") or len(query) != 42:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in query[2:])


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


def parse_dexscreener_base_token(pairs: list[dict]) -> dict | None:
    """Pure parse: same 'pick the highest-liquidity pair' logic as
    crypto_safety.py's parse_dexscreener_pairs, but pulls the base token's
    own identity (symbol/name/chain) instead of liquidity numbers -- what's
    needed to resolve an asset directly from a contract address, without
    ever asking CoinGecko whether it knows about the token first."""
    if not pairs:
        return None
    best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0.0)
    base_token = best.get("baseToken") or {}
    symbol = base_token.get("symbol")
    address = base_token.get("address")
    if not symbol or not address:
        return None
    return {
        "symbol": symbol.upper(),
        "name": base_token.get("name") or symbol,
        "address": address,
        "chain_slug": best.get("chainId"),
    }


class AssetResolver:
    async def resolve_crypto(self, query: str) -> AssetInfo | None:
        query = query.strip()
        if not query:
            return None
        if _looks_like_contract_address(query):
            return await self._resolve_by_contract_address(query)
        return await self._resolve_by_symbol(query)

    async def _resolve_by_symbol(self, query: str) -> AssetInfo | None:
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

    async def _resolve_by_contract_address(self, address: str) -> AssetInfo | None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(_DEXSCREENER_TOKENS_URL.format(address=address))
                resp.raise_for_status()
                token = parse_dexscreener_base_token(resp.json().get("pairs") or [])
                if token is None:
                    return None
                chain_id = _DEXSCREENER_CHAIN_IDS.get(token["chain_slug"])

                # Opportunistic enrichment only -- a failure here still
                # lets resolution succeed, just without a coingecko_id
                # (market/technical data for the token stays synthetic;
                # safety/liquidity don't depend on this at all).
                coingecko_id = None
                platform_slug = _CHAIN_ID_TO_COINGECKO_PLATFORM.get(chain_id) if chain_id else None
                if platform_slug:
                    try:
                        cg_resp = await client.get(_COINGECKO_CONTRACT_URL.format(platform=platform_slug, address=address))
                        if cg_resp.status_code == 200:
                            coingecko_id = cg_resp.json().get("id")
                    except (httpx.HTTPError, ValueError):
                        pass
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

        return AssetInfo(
            symbol=f"{token['symbol']}USD",
            display_name=f"{token['name']} / US Dollar",
            asset_type=AssetType.CRYPTO,
            base=token["symbol"],
            quote="USD",
            contract_address=token["address"],
            chain_id=chain_id,
            coingecko_id=coingecko_id,
            is_dynamic=True,
        )
