from app.agents.crypto_fundamentals_agent import CryptoFundamentalsAgent, _build_safety_gate
from app.agents.forex_fundamentals_agent import ForexFundamentalsAgent
from app.assets import get_asset
from app.models import Sentiment


async def test_forex_fundamentals_agent_produces_valid_result():
    agent = ForexFundamentalsAgent()
    result = await agent.analyze(get_asset("EURUSD"))

    assert result.symbol == "EURUSD"
    assert result.upcoming_events
    assert all(e.impact in {"low", "medium", "high"} for e in result.upcoming_events)
    assert "EUR" in result.central_bank_commentary
    assert "USD" in result.central_bank_commentary
    assert result.risk_regime.regime in {"risk_on", "risk_off", "neutral"}
    assert len(result.positioning) == 2  # one per currency in the pair
    assert {p.currency for p in result.positioning} == {"EUR", "USD"}
    assert result.sentiment in Sentiment
    assert -1.0 <= result.score <= 1.0
    assert result.summary


async def test_crypto_fundamentals_agent_produces_valid_result_for_native_asset():
    agent = CryptoFundamentalsAgent()
    result = await agent.analyze(get_asset("BTCUSD"))

    assert result.symbol == "BTCUSD"
    assert result.market_cap_usd > 0
    assert result.volume_24h_usd > 0
    assert result.circulating_supply > 0
    assert result.fdv_usd > 0
    assert 0 <= result.circulating_to_fdv_pct <= 100
    assert result.onchain.active_addresses_24h > 0
    assert result.ecosystem_notes
    # BTC is a native asset -- no contract, so the safety gate is N/A, not failing.
    assert result.safety.has_contract is False
    assert result.safety.passed is True
    assert result.derivatives.funding_rate_pct is not None
    assert result.btc_dominance_pct is not None
    assert result.sentiment in Sentiment
    assert -1.0 <= result.score <= 1.0
    assert result.summary


async def test_crypto_fundamentals_agent_runs_safety_gate_for_real_token_contract():
    """ACUSD (AgenticCore's own BEP-20 token) has a real contract_address --
    this is the actual token the safety-gate framework is meant to check,
    unlike BTC/ETH which have nothing to audit."""
    agent = CryptoFundamentalsAgent()
    result = await agent.analyze(get_asset("ACUSD"))

    assert result.symbol == "ACUSD"
    assert result.safety.has_contract is True
    assert result.safety.liquidity_to_mcap_pct is not None
    assert result.safety.top10_holder_pct is not None
    assert isinstance(result.safety.passed, bool)
    assert result.sentiment in Sentiment
    assert -1.0 <= result.score <= 1.0


def _clean_security_liquidity() -> tuple[dict, dict]:
    security = {
        "is_honeypot": False,
        "is_mintable": False,
        "is_blacklistable": False,
        "buy_tax_pct": 1.0,
        "sell_tax_pct": 1.0,
        "top10_holder_pct": 15.0,
    }
    liquidity = {"liquidity_usd": 5_000_000.0}
    return security, liquidity


def test_safety_gate_lp_holder_wallet_adds_soft_red_flag_but_does_not_fail_gate():
    security, liquidity = _clean_security_liquidity()
    result, score = _build_safety_gate(
        security, liquidity, market_cap_usd=10_000_000.0, lp_lock={"top_holder_is_contract": False}
    )
    assert result.lp_holder_is_contract is False
    assert any("personal wallet" in flag for flag in result.red_flags)
    # A soft signal only -- doesn't flip an otherwise-clean gate to failed.
    assert result.passed is True


def test_safety_gate_lp_holder_contract_adds_no_red_flag():
    security, liquidity = _clean_security_liquidity()
    result, score = _build_safety_gate(
        security, liquidity, market_cap_usd=10_000_000.0, lp_lock={"top_holder_is_contract": True}
    )
    assert result.lp_holder_is_contract is True
    assert result.red_flags == []
    assert result.passed is True


def test_safety_gate_lp_lock_none_leaves_field_unset():
    security, liquidity = _clean_security_liquidity()
    result, score = _build_safety_gate(security, liquidity, market_cap_usd=10_000_000.0, lp_lock=None)
    assert result.lp_holder_is_contract is None
    assert result.red_flags == []
