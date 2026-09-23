from enum import Enum

from pydantic import BaseModel


class AssetType(str, Enum):
    FOREX = "forex"
    CRYPTO = "crypto"
    COMMODITY = "commodity"


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
    # CoinGecko coin id (e.g. "bitcoin"), when known -- lets
    # crypto_market.py fetch real market-cap/volume/FDV/supply for any
    # resolved token, not just the two hardcoded majors. None for
    # forex/commodities, and for a crypto asset whose id wasn't resolved
    # (falls back to synthetic market data, same as before this existed).
    coingecko_id: str | None = None
    # True only for an asset built on the fly by asset_resolver.py for an
    # arbitrary "type any token" lookup that isn't in the static registry
    # below -- distinguishes a deliberately curated asset from a resolved
    # one, in case callers ever want to treat them differently (e.g. not
    # caching a bad resolution as long as a curated symbol).
    is_dynamic: bool = False


# The 8 major currencies (per the standard "28 pairs" forex universe: 8
# currencies, all pairwise combinations = C(8,2) = 28) with real display
# names, quoted in conventional FX market order (not alphabetical) --
# e.g. EURUSD not USDEUR, GBPJPY not JPYGBP.
_MAJOR_CURRENCIES = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
_CURRENCY_NAMES = {
    "EUR": "Euro",
    "GBP": "British Pound",
    "AUD": "Australian Dollar",
    "NZD": "New Zealand Dollar",
    "USD": "US Dollar",
    "CAD": "Canadian Dollar",
    "CHF": "Swiss Franc",
    "JPY": "Japanese Yen",
}


def _build_forex_registry() -> dict[str, AssetInfo]:
    registry: dict[str, AssetInfo] = {}
    for i, base in enumerate(_MAJOR_CURRENCIES):
        for quote in _MAJOR_CURRENCIES[i + 1 :]:
            symbol = f"{base}{quote}"
            registry[symbol] = AssetInfo(
                symbol=symbol,
                display_name=f"{_CURRENCY_NAMES[base]} / {_CURRENCY_NAMES[quote]}",
                asset_type=AssetType.FOREX,
                base=base,
                quote=quote,
            )
    return registry


# Seed registry. Forex pairs are quoted as BASEQUOTE (e.g. EURUSD); crypto
# and commodity symbols are quoted against USD (e.g. BTCUSD, XAUUSD). New
# assets can be added here without touching agent or orchestration code --
# for crypto, a symbol NOT in this static registry is also resolvable on
# the fly at request time via asset_resolver.py ("type any token").
_ASSET_REGISTRY: dict[str, AssetInfo] = {
    **_build_forex_registry(),
    "BTCUSD": AssetInfo(
        symbol="BTCUSD", display_name="Bitcoin / US Dollar", asset_type=AssetType.CRYPTO, base="BTC", quote="USD", coingecko_id="bitcoin"
    ),
    "ETHUSD": AssetInfo(
        symbol="ETHUSD", display_name="Ethereum / US Dollar", asset_type=AssetType.CRYPTO, base="ETH", quote="USD", coingecko_id="ethereum"
    ),
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
    # Commodities -- precious metals + energy, per the framework's "gold,
    # silver, oil, gas, etc." scope. Handled by a dedicated
    # commodity_fundamentals_agent (no central bank/currency concepts
    # apply), sharing the same technical/news/signal engine as forex and
    # crypto.
    "XAUUSD": AssetInfo(symbol="XAUUSD", display_name="Gold / US Dollar", asset_type=AssetType.COMMODITY, base="XAU", quote="USD"),
    "XAGUSD": AssetInfo(symbol="XAGUSD", display_name="Silver / US Dollar", asset_type=AssetType.COMMODITY, base="XAG", quote="USD"),
    "USOILUSD": AssetInfo(
        symbol="USOILUSD", display_name="WTI Crude Oil / US Dollar", asset_type=AssetType.COMMODITY, base="USOIL", quote="USD"
    ),
    "UKOILUSD": AssetInfo(
        symbol="UKOILUSD", display_name="Brent Crude Oil / US Dollar", asset_type=AssetType.COMMODITY, base="UKOIL", quote="USD"
    ),
    "NATGASUSD": AssetInfo(
        symbol="NATGASUSD", display_name="Natural Gas / US Dollar", asset_type=AssetType.COMMODITY, base="NATGAS", quote="USD"
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
