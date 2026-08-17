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


# Seed registry. Forex pairs are quoted as BASEQUOTE (e.g. EURUSD); crypto
# symbols are quoted against USD (e.g. BTCUSD). New assets can be added here
# without touching agent or orchestration code.
_ASSET_REGISTRY: dict[str, AssetInfo] = {
    "EURUSD": AssetInfo(symbol="EURUSD", display_name="Euro / US Dollar", asset_type=AssetType.FOREX, base="EUR", quote="USD"),
    "GBPUSD": AssetInfo(symbol="GBPUSD", display_name="British Pound / US Dollar", asset_type=AssetType.FOREX, base="GBP", quote="USD"),
    "USDJPY": AssetInfo(symbol="USDJPY", display_name="US Dollar / Japanese Yen", asset_type=AssetType.FOREX, base="USD", quote="JPY"),
    "BTCUSD": AssetInfo(symbol="BTCUSD", display_name="Bitcoin / US Dollar", asset_type=AssetType.CRYPTO, base="BTC", quote="USD"),
    "ETHUSD": AssetInfo(symbol="ETHUSD", display_name="Ethereum / US Dollar", asset_type=AssetType.CRYPTO, base="ETH", quote="USD"),
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
