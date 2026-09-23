"""Token unlock/vesting schedule via DefiLlama's free, public, keyless
unlocks tracker -- no TOKEN_UNLOCKS_API_KEY setting exists on purpose.

CONFIDENCE NOTE: unlike GoPlus/DexScreener/Binance/CoinGecko (extremely
well-documented, high-confidence schemas), the exact response shape of
DefiLlama's emissions/unlocks endpoint is lower-confidence here -- it
wasn't verified against a live response before this was written (this
sandbox's egress policy blocks reaching it). Parsing is deliberately
defensive (broad except, treats any missing/unexpected field as "no data")
so a wrong guess about field names degrades to synthetic rather than
crashing or silently returning wrong numbers. Confirm the real shape
against a live response before trusting this for an actual trading
decision, same as price_feed.py's TwelveData path.

Only meaningful for tokens DefiLlama actually tracks -- a small or
brand-new token (like AgenticCore's own AC) legitimately isn't listed
there, and that 404/empty response is expected, not a bug.
"""

from datetime import datetime, timezone

import httpx

from app.assets import AssetInfo
from app.data_sources.mock_utils import rng_for

_EMISSIONS_URL = "https://api.llama.fi/emission/{protocol_slug}"

# Days-ahead window that counts as "imminent" for the "large unlock in the
# next 7-14 days creates front-running pressure" criterion.
_IMMINENT_WINDOW_DAYS = 14


def parse_next_unlock(payload: dict, circulating_supply: float) -> dict | None:
    """Pure parse: finds the soonest future unlock event and expresses its
    size as a percentage of current circulating supply. Returns None if the
    payload doesn't have the expected shape -- treated as "no unlock data
    available" by the caller, not an error."""
    events = payload.get("events") or []
    now_ts = datetime.now(timezone.utc).timestamp()

    future_events = [e for e in events if isinstance(e.get("timestamp"), (int, float)) and e["timestamp"] > now_ts]
    if not future_events:
        return None

    next_event = min(future_events, key=lambda e: e["timestamp"])
    tokens = next_event.get("noOfTokens")
    token_amount = sum(tokens) if isinstance(tokens, list) else tokens
    if not isinstance(token_amount, (int, float)) or circulating_supply <= 0:
        return None

    days_until = (next_event["timestamp"] - now_ts) / 86400
    pct_of_circulating = token_amount / circulating_supply * 100

    return {
        "days_until_next_unlock": round(days_until, 1),
        "next_unlock_pct_of_circulating": round(pct_of_circulating, 2),
        "description": next_event.get("description") or "Scheduled token unlock",
    }


class TokenUnlocksClient:
    async def fetch_next_unlock(self, asset: AssetInfo, circulating_supply: float) -> dict | None:
        slug = asset.base.lower()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(_EMISSIONS_URL.format(protocol_slug=slug))
                if resp.status_code == 404:
                    return None  # not tracked by DefiLlama -- expected for most tokens, not an error
                resp.raise_for_status()
                payload = resp.json()
            return parse_next_unlock(payload, circulating_supply)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

    def synthetic_next_unlock(self, asset: AssetInfo) -> dict | None:
        """Not called automatically -- unlike other data sources, "no
        unlock data" is a perfectly valid real answer (most tokens have no
        vesting schedule at all), so there's no default synthetic fallback
        wired into fetch_next_unlock. Exposed only for callers that
        explicitly want a demo value."""
        rng = rng_for(asset.symbol, "unlocks")
        if rng.random() < 0.4:  # ~40% of tokens have no imminent unlock, even in the demo
            return None
        return {
            "days_until_next_unlock": round(rng.uniform(1, 60), 1),
            "next_unlock_pct_of_circulating": round(rng.uniform(0.5, 8.0), 2),
            "description": "Team/investor vesting tranche (demo data)",
        }
