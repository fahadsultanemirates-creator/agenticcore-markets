from enum import Enum

from pydantic import BaseModel


class AssetType(str, Enum):
    FOREX = "forex"
    CRYPTO = "crypto"


class AssetInfo(BaseModel):
    symbol: str
    display_name: str
    asset_type: AssetType
    base: str
    quote: str
    # Only set for crypto assets that are actual token contracts (not a
    # base-layer native asset like BTC/ETH, which have nothing to audit).
    # This is what the safety-gate agent needs to run a real honeypot/
    # liquidity check -- a symbol alone isn't enough to identify a token
    # on-chain, since GoPlus/DexScreener key off (chain_id, contract).
    contract_address: str | None = None
    chain_id: int | None = None  # e.g. 56 = BNB Smart Chain, 1 = Ethereum


# Seed registry. Forex pairs are quoted as BASEQUOTE (e.g. EURUSD); crypto
# symbols are quoted against USD (e.g. BTCUSD). New assets can be added here
# without touching agent or orchestration code.
_ASSET_REGISTRY: dict[str, AssetInfo] = {
    "EURUSD": AssetInfo(symbol="EURUSD", display_name="Euro / US Dollar", asset_type=AssetType.FOREX, base="EUR", quote="USD"),
    "GBPUSD": AssetInfo(symbol="GBPUSD", display_name="British Pound / US Dollar", asset_type=AssetType.FOREX, base="GBP", quote="USD"),
    "USDJPY": AssetInfo(symbol="USDJPY", display_name="US Dollar / Japanese Yen", asset_type=AssetType.FOREX, base="USD", quote="JPY"),
    "BTCUSD": AssetInfo(symbol="BTCUSD", display_name="Bitcoin / US Dollar", asset_type=AssetType.CRYPTO, base="BTC", quote="USD"),
    "ETHUSD": AssetInfo(symbol="ETHUSD", display_name="Ethereum / US Dollar", asset_type=AssetType.CRYPTO, base="ETH", quote="USD"),
    # AgenticCore's own token -- a real BEP-20 contract, live on BSC mainnet
    # (see the agenticcore-token- repo). A concrete real test case for the
    # safety-gate agent, since BTC/ETH above are native assets with no
    # contract to audit.
    "ACUSD": AssetInfo(
        symbol="ACUSD",
        display_name="AgenticCore / US Dollar",
        asset_type=AssetType.CRYPTO,
        base="AC",
        quote="USD",
        contract_address="0xe9568888a0bc317519957047cf736e134B097768",
        chain_id=56,
    ),
}


def get_asset(symbol: str) -> AssetInfo:
    key = symbol.upper()
    if key not in _ASSET_REGISTRY:
        raise KeyError(f"Unknown or unsupported symbol: {symbol}")
    return _ASSET_REGISTRY[key]


def list_assets() -> list[AssetInfo]:
    return list(_ASSET_REGISTRY.values())


def is_supported(symbol: str) -> bool:
    return symbol.upper() in _ASSET_REGISTRY
