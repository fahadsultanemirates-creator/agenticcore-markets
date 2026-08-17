import pytest

from app.assets import AssetType
from app.models import CryptoFundamentalsResult, ForexFundamentalsResult, SignalCall
from app.orchestrator import AnalysisOrchestrator


async def test_eurusd_end_to_end_pipeline():
    orch = AnalysisOrchestrator()
    analysis = await orch.get_analysis("EURUSD")

    assert analysis.symbol == "EURUSD"
    assert analysis.asset_type == AssetType.FOREX
    assert isinstance(analysis.fundamentals, ForexFundamentalsResult)
    assert analysis.technical.symbol == "EURUSD"
    assert analysis.news.symbol == "EURUSD"
    assert analysis.signal.signal in SignalCall
    assert analysis.cached is False


async def test_btcusd_reuses_shared_pipeline_with_crypto_fundamentals():
    orch = AnalysisOrchestrator()
    analysis = await orch.get_analysis("BTCUSD")

    assert analysis.symbol == "BTCUSD"
    assert analysis.asset_type == AssetType.CRYPTO
    assert isinstance(analysis.fundamentals, CryptoFundamentalsResult)
    assert analysis.technical.symbol == "BTCUSD"  # same technical_analysis_agent as forex


async def test_second_request_for_same_symbol_is_served_from_cache():
    orch = AnalysisOrchestrator()

    first = await orch.get_analysis("EURUSD")
    second = await orch.get_analysis("EURUSD")

    assert first.cached is False
    assert second.cached is True
    assert first.generated_at == second.generated_at  # same underlying computed result


async def test_unsupported_symbol_raises_key_error():
    orch = AnalysisOrchestrator()
    with pytest.raises(KeyError):
        await orch.get_analysis("DOGEUSD")
