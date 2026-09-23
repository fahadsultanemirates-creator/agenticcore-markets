from app.agents.commodity_fundamentals_agent import (
    CommodityFundamentalsAgent,
    _build_rate_backdrop,
    _cot_score,
    _risk_regime_score,
)
from app.assets import get_asset
from app.models import PositioningResult, Sentiment


async def test_commodity_fundamentals_agent_produces_valid_result_for_gold():
    agent = CommodityFundamentalsAgent()
    result = await agent.analyze(get_asset("XAUUSD"))

    assert result.symbol == "XAUUSD"
    assert result.upcoming_events
    assert result.risk_regime.regime in {"risk_on", "risk_off", "neutral"}
    assert result.positioning.currency == "XAU"
    assert result.sentiment in Sentiment
    assert -1.0 <= result.score <= 1.0
    assert result.summary


async def test_commodity_fundamentals_agent_produces_valid_result_for_oil():
    agent = CommodityFundamentalsAgent()
    result = await agent.analyze(get_asset("USOILUSD"))

    assert result.symbol == "USOILUSD"
    assert result.positioning.currency == "USOIL"
    assert result.sentiment in Sentiment
    assert -1.0 <= result.score <= 1.0


def test_rate_backdrop_no_fred_data_returns_zero_score():
    backdrop, score = _build_rate_backdrop(get_asset("XAUUSD"), None)
    assert score == 0.0
    assert backdrop.fed_funds_rate_pct is None


def test_rate_backdrop_high_yield_is_bearish_for_gold():
    us_macro = {"fed_funds_rate_pct": 5.5, "ust_10y_yield_pct": 5.0}
    backdrop, score = _build_rate_backdrop(get_asset("XAUUSD"), us_macro)
    assert score < 0
    assert backdrop.ust_10y_yield_pct == 5.0


def test_rate_backdrop_low_yield_is_bullish_for_gold():
    us_macro = {"fed_funds_rate_pct": 1.0, "ust_10y_yield_pct": 1.5}
    backdrop, score = _build_rate_backdrop(get_asset("XAUUSD"), us_macro)
    assert score > 0


def test_rate_backdrop_not_weighted_for_energy():
    us_macro = {"fed_funds_rate_pct": 5.5, "ust_10y_yield_pct": 5.0}
    _, score = _build_rate_backdrop(get_asset("USOILUSD"), us_macro)
    assert score == 0.0


def test_risk_regime_score_risk_off_is_bullish_for_gold():
    assert _risk_regime_score(get_asset("XAUUSD"), "risk_off") > 0
    assert _risk_regime_score(get_asset("XAUUSD"), "risk_on") < 0


def test_risk_regime_score_risk_on_is_bullish_for_oil():
    assert _risk_regime_score(get_asset("USOILUSD"), "risk_on") > 0
    assert _risk_regime_score(get_asset("USOILUSD"), "risk_off") < 0


def test_risk_regime_score_neutral_is_zero():
    assert _risk_regime_score(get_asset("XAUUSD"), "neutral") == 0.0


def test_cot_score_crowded_long_is_contrarian_bearish():
    pos = PositioningResult(currency="XAU", as_of_report_date=None, net_speculative_position=100_000, is_crowded_extreme=True, note="")
    assert _cot_score(pos) < 0


def test_cot_score_not_crowded_is_zero():
    pos = PositioningResult(currency="XAU", as_of_report_date=None, net_speculative_position=10_000, is_crowded_extreme=False, note="")
    assert _cot_score(pos) == 0.0
