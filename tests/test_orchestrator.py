import pytest

from app.agents.crypto_fundamentals_agent import CryptoFundamentalsAgent
from app.agents.news_aggregation_agent import NewsAggregationAgent
from app.agents.signal_synthesis_agent import SignalSynthesisAgent
from app.agents.technical_analysis_agent import TechnicalAnalysisAgent
from app.assets import AssetInfo, AssetType
from app.models import CommodityFundamentalsResult, CryptoFundamentalsResult, ForexFundamentalsResult, SignalCall
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


async def test_acusd_full_pipeline_runs_safety_gate_for_real_contract():
    """ACUSD has a real contract_address (AgenticCore's own BEP-20 token) --
    proves the full pipeline, including the safety gate and its potential
    signal override, runs end-to-end for an actual token contract, not just
    the two native assets (BTC/ETH) the earlier tests cover."""
    orch = AnalysisOrchestrator()
    analysis = await orch.get_analysis("ACUSD")

    assert analysis.symbol == "ACUSD"
    assert analysis.asset_type == AssetType.CRYPTO
    assert isinstance(analysis.fundamentals, CryptoFundamentalsResult)
    assert analysis.fundamentals.safety.has_contract is True
    assert analysis.signal.signal in SignalCall


async def test_xauusd_full_pipeline_uses_commodity_fundamentals():
    orch = AnalysisOrchestrator()
    analysis = await orch.get_analysis("XAUUSD")

    assert analysis.symbol == "XAUUSD"
    assert analysis.asset_type == AssetType.COMMODITY
    assert isinstance(analysis.fundamentals, CommodityFundamentalsResult)
    assert analysis.technical.symbol == "XAUUSD"  # same shared technical engine
    assert analysis.signal.signal in SignalCall


async def test_unsupported_symbol_raises_key_error():
    # A nonsense string, not a real token -- unlike a real symbol
    # (e.g. DOGEUSD, which asset_resolver.py could genuinely resolve once
    # it has real internet access), this must 404-equivalent (KeyError)
    # regardless of environment.
    orch = AnalysisOrchestrator()
    with pytest.raises(KeyError):
        await orch.get_analysis("NOTAREALTOKENXYZ999")


async def test_dynamically_resolved_asset_runs_full_pipeline():
    """A token not in the curated static registry -- the shape
    asset_resolver.py builds for an arbitrary 'type any token' lookup --
    must flow through the exact same technical/fundamentals/news/signal
    pipeline as a curated asset. Exercised directly against a manually
    built AssetInfo rather than through live resolution, since this
    sandbox can't reach CoinGecko to resolve one for real."""
    dynamic_asset = AssetInfo(
        symbol="PEPEUSD",
        display_name="Pepe / US Dollar",
        asset_type=AssetType.CRYPTO,
        base="PEPE",
        quote="USD",
        contract_address="0x6982508145454ce325ddbe47a25d4ec3d2311933",
        chain_id=1,
        coingecko_id="pepe",
        is_dynamic=True,
    )
    technical = await TechnicalAnalysisAgent().analyze(dynamic_asset)
    fundamentals = await CryptoFundamentalsAgent().analyze(dynamic_asset)
    news = await NewsAggregationAgent().analyze(dynamic_asset)
    signal = SignalSynthesisAgent().synthesize(dynamic_asset, technical, fundamentals, news)

    assert technical.symbol == "PEPEUSD"
    assert isinstance(fundamentals, CryptoFundamentalsResult)
    assert fundamentals.safety.has_contract is True  # has a mapped contract -- the gate actually runs, not skipped
    assert signal.signal in SignalCall
    assert signal.reasoning
