from app.assets import AssetType, get_asset, is_supported, list_assets


def test_registry_has_28_forex_pairs():
    forex = [a for a in list_assets() if a.asset_type == AssetType.FOREX]
    assert len(forex) == 28
    symbols = {a.symbol for a in forex}
    assert symbols == {a.symbol for a in forex}  # no duplicates by construction
    assert "EURUSD" in symbols
    assert "GBPJPY" in symbols
    assert "AUDNZD" in symbols


def test_registry_forex_pairs_have_distinct_base_and_quote():
    for asset in list_assets():
        if asset.asset_type == AssetType.FOREX:
            assert asset.base != asset.quote
            assert asset.symbol == f"{asset.base}{asset.quote}"


def test_registry_has_five_commodities():
    commodities = {a.symbol for a in list_assets() if a.asset_type == AssetType.COMMODITY}
    assert commodities == {"XAUUSD", "XAGUSD", "USOILUSD", "UKOILUSD", "NATGASUSD"}


def test_registry_still_has_curated_crypto_assets():
    crypto = {a.symbol for a in list_assets() if a.asset_type == AssetType.CRYPTO}
    assert crypto == {"BTCUSD", "ETHUSD", "ACUSD"}


def test_get_asset_unknown_symbol_raises_key_error():
    import pytest

    with pytest.raises(KeyError):
        get_asset("NOTAREALSYMBOL")


def test_is_supported():
    assert is_supported("eurusd") is True  # case-insensitive
    assert is_supported("NOTAREALSYMBOL") is False


def test_btc_eth_have_coingecko_ids():
    assert get_asset("BTCUSD").coingecko_id == "bitcoin"
    assert get_asset("ETHUSD").coingecko_id == "ethereum"


def test_dynamic_flag_defaults_false_for_curated_assets():
    assert get_asset("EURUSD").is_dynamic is False
    assert get_asset("ACUSD").is_dynamic is False
