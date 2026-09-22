"""Small builders for constructing valid model instances in tests without
repeating every required field."""

from datetime import datetime, timezone

from app.models import (
    CryptoFundamentalsResult,
    DerivativesResult,
    ForexFundamentalsResult,
    OnChainMetrics,
    RiskRegimeResult,
    SafetyGateResult,
    Sentiment,
)


def make_forex_fundamentals(score: float, sentiment: Sentiment) -> ForexFundamentalsResult:
    return ForexFundamentalsResult(
        symbol="EURUSD",
        as_of=datetime.now(timezone.utc),
        upcoming_events=[],
        central_bank_commentary="stub commentary",
        risk_regime=RiskRegimeResult(regime="neutral", equities_trend=Sentiment.NEUTRAL, safe_haven_demand=Sentiment.NEUTRAL),
        positioning=[],
        sentiment=sentiment,
        score=score,
        summary="stub fundamentals summary",
    )


def make_crypto_fundamentals(
    score: float, sentiment: Sentiment, safety_passed: bool = True, red_flags: list[str] | None = None
) -> CryptoFundamentalsResult:
    return CryptoFundamentalsResult(
        symbol="ACUSD",
        as_of=datetime.now(timezone.utc),
        market_cap_usd=10_000_000.0,
        volume_24h_usd=1_000_000.0,
        circulating_supply=700_000_000_000.0,
        fdv_usd=20_000_000.0,
        circulating_to_fdv_pct=50.0,
        onchain=OnChainMetrics(active_addresses_24h=1000, transaction_count_24h=2000, exchange_netflow_24h=0.0),
        ecosystem_notes=["stub ecosystem note"],
        safety=SafetyGateResult(has_contract=True, passed=safety_passed, red_flags=red_flags or []),
        derivatives=DerivativesResult(regime_note="stub derivatives note"),
        btc_dominance_pct=55.0,
        sentiment=sentiment,
        score=score,
        summary="stub crypto fundamentals summary",
    )
