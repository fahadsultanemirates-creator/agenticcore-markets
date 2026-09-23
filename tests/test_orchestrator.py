from datetime import datetime, timezone

import pytest

from app.agents.crypto_fundamentals_agent import CryptoFundamentalsAgent
from app.agents.news_aggregation_agent import NewsAggregationAgent
from app.agents.signal_synthesis_agent import SignalSynthesisAgent
from app.agents.technical_analysis_agent import TechnicalAnalysisAgent
from app.assets import AssetInfo, AssetType
from app.models import (
    ComponentScores,
    CommodityFundamentalsResult,
    CryptoFundamentalsResult,
    ForexFundamentalsResult,
    Sentiment,
    SignalCall,
    SynthesizedSignal,
)
from app.orchestrator import AnalysisOrchestrator, _apply_safety_gate_override
from tests.factories import make_crypto_fundamentals


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


async def test_model_param_falls_back_to_formula_without_keys_configured(monkeypatch):
    """No LLM keys configured in this sandbox -- requesting a specialist
    model must still produce a valid signal via the deterministic formula
    fallback, never raise or return an incomplete result."""
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", None)
    orch = AnalysisOrchestrator()

    analysis = await orch.get_analysis("EURUSD", model="claude")
    assert analysis.signal.signal in SignalCall
    assert analysis.signal.reasoning


async def test_different_model_choices_do_not_share_a_cache_entry(monkeypatch):
    """A 'claude' request and a plain formula request for the same symbol
    within the same TTL window must not collide in the cache -- each
    model choice gets its own cache key. Tests cache-key isolation, not
    live LLM behavior, so keys are forced off regardless of what's in the
    environment -- this must stay fast and free of real API calls."""
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", None)
    orch = AnalysisOrchestrator()

    plain = await orch.get_analysis("GBPUSD")
    claude = await orch.get_analysis("GBPUSD", model="claude")

    assert plain.cached is False
    assert claude.cached is False  # different cache key -- not served from the plain request's entry

    plain_again = await orch.get_analysis("GBPUSD")
    assert plain_again.cached is True
    assert plain_again.generated_at == plain.generated_at


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


def _fake_specialist_signal(call: SignalCall) -> SynthesizedSignal:
    return SynthesizedSignal(
        symbol="ACUSD",
        asset_type=AssetType.CRYPTO,
        as_of=datetime.now(timezone.utc),
        signal=call,
        confidence=0.8,
        component_scores=ComponentScores(technical=0.5, fundamental=0.5, news=0.0),
        reasoning="A specialist LLM said this looked bullish enough to buy.",
    )


def test_safety_gate_override_forces_hold_even_when_specialist_says_buy():
    """The core gap this closes: an LLM only ever SEES a failed safety
    gate as prose in the fundamentals summary -- nothing stops it from
    still calling BUY if it judges the rest of the evidence bullish
    enough. This must be forced back to HOLD regardless."""
    failed_gate_fundamentals = make_crypto_fundamentals(
        0.5, Sentiment.BULLISH, safety_passed=False, red_flags=["Contract is flagged as a honeypot."]
    )
    specialist_signal = _fake_specialist_signal(SignalCall.BUY)

    result = _apply_safety_gate_override(failed_gate_fundamentals, specialist_signal)

    assert result.signal == SignalCall.HOLD
    assert result.confidence >= 0.95
    assert "SAFETY GATE OVERRIDE" in result.reasoning
    assert "honeypot" in result.reasoning
    assert "A specialist LLM said this looked bullish enough to buy." in result.reasoning  # original reasoning preserved


def test_safety_gate_override_is_noop_when_gate_passed():
    passed_gate_fundamentals = make_crypto_fundamentals(0.5, Sentiment.BULLISH, safety_passed=True)
    specialist_signal = _fake_specialist_signal(SignalCall.BUY)

    result = _apply_safety_gate_override(passed_gate_fundamentals, specialist_signal)

    assert result is specialist_signal  # untouched, not even a copy


def test_safety_gate_override_is_noop_when_specialist_already_said_hold():
    failed_gate_fundamentals = make_crypto_fundamentals(0.5, Sentiment.BULLISH, safety_passed=False)
    specialist_signal = _fake_specialist_signal(SignalCall.HOLD)

    result = _apply_safety_gate_override(failed_gate_fundamentals, specialist_signal)

    assert result is specialist_signal  # already HOLD -- no redundant override note appended
