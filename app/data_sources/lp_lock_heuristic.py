"""LP-holder-type check: is the liquidity-pool token held by a contract
(consistent with being locked in a locker service, or held by the AMM
itself) or by a plain wallet (the deployer could pull it any time)?

This is DELIBERATELY NOT true lock verification. Confirming a specific
locker service (Unicrypt/PinkLock/Team Finance) requires knowing that
service's exact vault contract addresses, and those weren't confirmed
against a live response before this was written -- guessing at specific
addresses and silently trusting them would be worse than not checking at
all. What this DOES check, with high confidence, is a much narrower fact:
whether the top LP holder address has contract bytecode at all
(`eth_getCode` returning something other than "0x" is unambiguous). A
wallet holding the majority of LP tokens is a real red flag regardless of
which locker (if any) exists; a contract holding it is consistent with
either a real lock or just the AMM pool itself -- softer evidence, not proof.

Requires BSCSCAN_API_KEY (free, but needs signup at bscscan.com/apis) --
unlike the other Tier 2 sources, there is deliberately no synthetic
fallback here: "is this a contract or a wallet" is a yes/no fact, and
manufacturing a fake answer would be actively misleading rather than
merely illustrative. When the key isn't set, or the check fails for any
reason, this returns None -- "not checked", not "assumed safe."
"""

import httpx

from app.config import settings

_BSCSCAN_API_URL = "https://api.bscscan.com/api"
_BURN_ADDRESSES = {"0x0000000000000000000000000000000000dead", "0x0000000000000000000000000000000000000000"}


class LpLockHeuristicClient:
    def is_available(self) -> bool:
        return bool(settings.bscscan_api_key)

    async def check_top_holder_type(self, pair_address: str | None) -> dict | None:
        if not self.is_available() or not pair_address:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                holder_resp = await client.get(
                    _BSCSCAN_API_URL,
                    params={
                        "module": "token",
                        "action": "tokenholderlist",
                        "contractaddress": pair_address,
                        "page": 1,
                        "offset": 5,
                        "apikey": settings.bscscan_api_key,
                    },
                )
                holder_resp.raise_for_status()
                holders = holder_resp.json().get("result")
                if not isinstance(holders, list) or not holders:
                    return None

                top_holder = next(
                    (h for h in holders if h.get("TokenHolderAddress", "").lower() not in _BURN_ADDRESSES), None
                )
                if not top_holder:
                    return None
                top_holder_address = top_holder["TokenHolderAddress"]

                code_resp = await client.get(
                    _BSCSCAN_API_URL,
                    params={
                        "module": "proxy",
                        "action": "eth_getCode",
                        "address": top_holder_address,
                        "tag": "latest",
                        "apikey": settings.bscscan_api_key,
                    },
                )
                code_resp.raise_for_status()
                code = code_resp.json().get("result", "0x")

            return {
                "top_holder_address": top_holder_address,
                "top_holder_is_contract": code not in ("0x", "0x0", None),
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
