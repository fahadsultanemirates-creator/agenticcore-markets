"""On-chain safety gate for crypto tokens: contract/honeypot checks (GoPlus
Security API) + liquidity depth (DexScreener). Both are free, public, and
keyless -- no API key setting exists for either on purpose.

Only applies to assets with a real contract (AssetInfo.contract_address set)
-- a base-layer native asset like BTC or ETH has nothing to audit, so
callers should treat has_contract=False as "gate not applicable" rather than
a failure.

Fetch (network I/O) and parse (pure function) are kept separate: the parse
functions are fully unit-tested against realistic sample payloads even
though the live fetch calls can't be exercised from every environment (some
sandboxes/CI runners block general outbound internet access). Any fetch
failure -- timeout, non-2xx, blocked egress, malformed response -- degrades
to deterministic synthetic data rather than breaking the pipeline, the same
resilience pattern price_feed.py already uses for TwelveData.
"""

import httpx

from app.assets import AssetInfo
from app.data_sources.mock_utils import rng_for

_GOPLUS_URL = "https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
_DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"


def _to_float(value, default: float = 0.0) -> float:
    """GoPlus returns numeric fields as strings (a documented quirk of the
    API), and some are missing/empty entirely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool_flag(value) -> bool:
    """GoPlus boolean flags are "0"/"1" strings, not real booleans."""
    return str(value) == "1"


def _synthetic_holder_percentiles(rng) -> dict:
    """Builds top1/top5/top10/top20 as increments stacked on each other so
    the result is always monotonically non-decreasing -- four independent
    random draws could otherwise put (e.g.) top5 above top10, which is
    impossible in reality since top10 always includes top5's holders."""
    top1 = rng.uniform(2, 8)
    top5 = top1 + rng.uniform(2, 8)
    top10 = top5 + rng.uniform(1, 6)
    top20 = top10 + rng.uniform(2, 8)
    return {
        "top1_holder_pct": round(top1, 2),
        "top5_holder_pct": round(top5, 2),
        "top10_holder_pct": round(top10, 2),
        "top20_holder_pct": round(top20, 2),
    }


_WHALE_THRESHOLD_PCT = 1.0  # an individual wallet holding >=1% of supply counts as a "whale" for this summary


def parse_goplus_result(raw: dict) -> dict:
    """Pure parse of one GoPlus token_security result entry (the dict keyed
    by contract address inside `result`) into the fields the safety-gate
    agent needs -- including whale/holder-concentration visibility, since
    the full holder list is already being fetched here regardless."""
    holders = raw.get("holders") or []
    # Exclude the LP/router/contract addresses GoPlus already tags as
    # contracts from the "individual whale" concentration check -- an AMM
    # pool holding 40% of supply isn't the same risk as one wallet holding it.
    individual_holders = [h for h in holders if str(h.get("is_contract", 0)) != "1"]
    individual_holders.sort(key=lambda h: _to_float(h.get("percent")), reverse=True)

    def top_n_pct(n: int) -> float:
        return sum(_to_float(h.get("percent")) for h in individual_holders[:n]) * 100

    whale_count = sum(1 for h in individual_holders if _to_float(h.get("percent")) * 100 >= _WHALE_THRESHOLD_PCT)

    return {
        "is_honeypot": _to_bool_flag(raw.get("is_honeypot")),
        "is_mintable": _to_bool_flag(raw.get("is_mintable")),
        "is_blacklistable": _to_bool_flag(raw.get("is_blacklisted")) or _to_bool_flag(raw.get("transfer_pausable")),
        "is_open_source": _to_bool_flag(raw.get("is_open_source")),
        "buy_tax_pct": _to_float(raw.get("buy_tax")) * 100,
        "sell_tax_pct": _to_float(raw.get("sell_tax")) * 100,
        "top1_holder_pct": top_n_pct(1),
        "top5_holder_pct": top_n_pct(5),
        "top10_holder_pct": top_n_pct(10),
        "top20_holder_pct": top_n_pct(20),
        "whale_count_over_1pct": whale_count,
        "holder_count": int(_to_float(raw.get("holder_count"))),
    }


def parse_dexscreener_pairs(pairs: list[dict]) -> dict | None:
    """Pure parse: picks the highest-liquidity pair (a token can be listed
    across multiple DEXes/pools) and pulls liquidity/FDV out of it."""
    if not pairs:
        return None

    best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0.0)
    liquidity_usd = float((best.get("liquidity") or {}).get("usd") or 0.0)
    fdv_usd = float(best.get("fdv") or 0.0)
    market_cap_usd = float(best.get("marketCap") or 0.0)
    volume_24h_usd = float((best.get("volume") or {}).get("h24") or 0.0)

    return {
        "liquidity_usd": liquidity_usd,
        "fdv_usd": fdv_usd,
        "market_cap_usd": market_cap_usd,
        "volume_24h_usd": volume_24h_usd,
        "dex_id": best.get("dexId"),
        "pair_address": best.get("pairAddress"),
    }


class CryptoSafetyClient:
    async def fetch_token_security(self, asset: AssetInfo) -> dict | None:
        """Returns None when there's nothing to check (no contract) or when
        neither a live call nor synthetic fallback makes sense -- callers
        treat None as "gate not applicable", distinct from a failed check."""
        if not asset.contract_address or not asset.chain_id:
            return None

        try:
            url = _GOPLUS_URL.format(chain_id=asset.chain_id)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params={"contract_addresses": asset.contract_address})
                resp.raise_for_status()
                payload = resp.json()
            raw = (payload.get("result") or {}).get(asset.contract_address.lower())
            if not raw:
                return self._synthetic_security(asset)
            return parse_goplus_result(raw)
        except (httpx.HTTPError, ValueError, KeyError):
            return self._synthetic_security(asset)

    async def fetch_liquidity(self, asset: AssetInfo, market_cap_usd_hint: float | None = None) -> dict | None:
        if not asset.contract_address:
            return None

        try:
            url = _DEXSCREENER_URL.format(address=asset.contract_address)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                payload = resp.json()
            parsed = parse_dexscreener_pairs(payload.get("pairs") or [])
            return parsed or self._synthetic_liquidity(asset, market_cap_usd_hint)
        except (httpx.HTTPError, ValueError, KeyError):
            return self._synthetic_liquidity(asset, market_cap_usd_hint)

    def _synthetic_security(self, asset: AssetInfo) -> dict:
        # Deliberately generates a CLEAN-looking token by default (no
        # honeypot/mint/blacklist flags) -- the synthetic fallback exists so
        # the pipeline runs end-to-end, not to manufacture fake danger. A
        # real deployment should never rely on this path for an actual
        # trading decision.
        rng = rng_for(asset.symbol, "safety")
        return {
            "is_honeypot": False,
            "is_mintable": False,
            "is_blacklistable": False,
            "is_open_source": True,
            "buy_tax_pct": round(rng.uniform(0, 3), 2),
            "sell_tax_pct": round(rng.uniform(0, 3), 2),
            # top-N percentiles must be monotonically non-decreasing (top20
            # always includes top10, which always includes top5, etc.) --
            # built as increments on top of each other rather than four
            # independent draws, which could otherwise put a smaller
            # percentile above a larger one.
            **_synthetic_holder_percentiles(rng),
            "whale_count_over_1pct": rng.randint(2, 8),
            "holder_count": rng.randint(500, 50_000),
        }

    def _synthetic_liquidity(self, asset: AssetInfo, market_cap_usd_hint: float | None) -> dict:
        rng = rng_for(asset.symbol, "liquidity")
        # Scale against the REAL market cap already computed elsewhere in
        # the pipeline (crypto_market.py) when available, rather than
        # inventing an unrelated one -- two independently-random synthetic
        # numbers produced a nonsense liquidity/mcap ratio here before this
        # was fixed, since they had no relationship to each other.
        market_cap = market_cap_usd_hint if market_cap_usd_hint and market_cap_usd_hint > 0 else rng.uniform(1_000_000, 50_000_000)
        return {
            "liquidity_usd": market_cap * rng.uniform(0.1, 0.3),
            "fdv_usd": market_cap * rng.uniform(1.0, 3.0),
            "market_cap_usd": market_cap,
            "volume_24h_usd": market_cap * rng.uniform(0.05, 0.4),
            "dex_id": "synthetic",
            "pair_address": None,
        }
