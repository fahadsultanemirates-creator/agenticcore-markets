"""Fundamentals for crypto assets: the on-chain safety gate (contract/
honeypot/liquidity/holder concentration), tokenomics (circulating vs FDV),
derivatives positioning (OI/funding/taker flow), on-chain activity, BTC
macro backdrop, and ecosystem notes -- the crypto side of the two 10-point
frameworks, minus what's already covered by the shared technical engine
(HTF structure, volume profile) and the news agent.

The safety gate is treated as a hard override, not just one more weighted
input: a failed gate (honeypot, unlocked/thin liquidity, extreme holder
concentration) forces the score sharply bearish here AND overrides the
final signal in signal_synthesis_agent, per the "skip the trade regardless
of chart patterns" rule the framework was built against.
"""

from datetime import datetime, timezone

from app.agents.scoring import clamp, sentiment_from_score
from app.assets import AssetInfo
from app.data_sources.crypto_market import CryptoMarketClient
from app.data_sources.crypto_safety import CryptoSafetyClient
from app.data_sources.derivatives import DerivativesClient
from app.models import CryptoFundamentalsResult, DerivativesResult, OnChainMetrics, SafetyGateResult

_POSITIVE_WORDS = ("inflow", "accumulat", "record", "grow", "high demand", "reduc", "tightening")
_NEGATIVE_WORDS = ("outflow", "pressure", "decline", "uncertainty", "compress", "weigh")

# Thresholds straight from the safety-gate framework: LP/liquidity below
# 10% of market cap is "insufficient" (healthy is 10-25%+); top-10
# individual holders above 30% is past the stated 20-30% danger band.
_MIN_HEALTHY_LIQUIDITY_TO_MCAP_PCT = 10.0
_MAX_HEALTHY_TOP10_HOLDER_PCT = 30.0
_FUNDING_EXTREME_PCT = 0.05


class CryptoFundamentalsAgent:
    def __init__(
        self,
        crypto_market: CryptoMarketClient | None = None,
        safety: CryptoSafetyClient | None = None,
        derivatives: DerivativesClient | None = None,
    ) -> None:
        self._crypto_market = crypto_market or CryptoMarketClient()
        self._safety = safety or CryptoSafetyClient()
        self._derivatives = derivatives or DerivativesClient()

    async def analyze(self, asset: AssetInfo) -> CryptoFundamentalsResult:
        snapshot = await self._crypto_market.fetch_market_snapshot(asset)
        onchain = self._crypto_market.fetch_onchain_metrics(asset)
        ecosystem_notes = self._crypto_market.fetch_ecosystem_notes(asset)
        btc_dominance_pct = await self._crypto_market.fetch_btc_dominance()

        security_raw = await self._safety.fetch_token_security(asset)
        liquidity_raw = await self._safety.fetch_liquidity(asset, market_cap_usd_hint=snapshot["market_cap_usd"])
        safety, safety_score = _build_safety_gate(security_raw, liquidity_raw, snapshot["market_cap_usd"])

        derivatives_raw = await self._derivatives.fetch_snapshot(asset)
        derivatives, derivatives_score = _build_derivatives(derivatives_raw)

        circulating_to_fdv_pct = (
            (snapshot["market_cap_usd"] / snapshot["fdv_usd"]) * 100 if snapshot["fdv_usd"] > 0 else 100.0
        )

        netflow_score = _netflow_score(onchain)
        turnover_score = _turnover_score(snapshot["volume_24h_usd"], snapshot["market_cap_usd"])
        ecosystem_score = _ecosystem_score(ecosystem_notes)
        fdv_score = _fdv_score(circulating_to_fdv_pct)
        btc_macro_score = _btc_macro_score(asset, btc_dominance_pct)

        score = clamp(
            (netflow_score + turnover_score + ecosystem_score + fdv_score + derivatives_score + btc_macro_score) / 6
        )
        if not safety.passed:
            # Hard override: a failed safety gate dominates regardless of
            # how bullish everything else looks -- this IS the point of a
            # gate, not a fifth vote among equals.
            score = min(score, -0.85)
        sentiment = sentiment_from_score(score)

        summary = _build_summary(
            asset, snapshot, onchain, ecosystem_notes, safety, derivatives, circulating_to_fdv_pct, btc_dominance_pct
        )

        return CryptoFundamentalsResult(
            symbol=asset.symbol,
            as_of=datetime.now(timezone.utc),
            market_cap_usd=snapshot["market_cap_usd"],
            volume_24h_usd=snapshot["volume_24h_usd"],
            circulating_supply=snapshot["circulating_supply"],
            fdv_usd=snapshot["fdv_usd"],
            circulating_to_fdv_pct=circulating_to_fdv_pct,
            onchain=onchain,
            ecosystem_notes=ecosystem_notes,
            safety=safety,
            derivatives=derivatives,
            btc_dominance_pct=btc_dominance_pct,
            sentiment=sentiment,
            score=score,
            summary=summary,
        )


def _build_safety_gate(security: dict | None, liquidity: dict | None, market_cap_usd: float) -> tuple[SafetyGateResult, float]:
    if security is None and liquidity is None:
        # No contract on this asset (e.g. BTC/ETH) -- gate doesn't apply.
        return SafetyGateResult(has_contract=False, passed=True, red_flags=[]), 0.0

    security = security or {}
    liquidity = liquidity or {}
    liquidity_usd = liquidity.get("liquidity_usd")
    liquidity_to_mcap_pct = (liquidity_usd / market_cap_usd * 100) if liquidity_usd and market_cap_usd > 0 else None

    red_flags: list[str] = []
    if security.get("is_honeypot"):
        red_flags.append("Contract is flagged as a honeypot -- tokens can be bought but not sold.")
    if security.get("is_mintable"):
        red_flags.append("Owner retains an active mint function -- supply can be arbitrarily inflated.")
    if security.get("is_blacklistable"):
        red_flags.append("Contract can blacklist or pause individual wallets.")
    if security.get("buy_tax_pct", 0) and security["buy_tax_pct"] > 10:
        red_flags.append(f"Buy tax of {security['buy_tax_pct']:.1f}% is unusually high.")
    if security.get("sell_tax_pct", 0) and security["sell_tax_pct"] > 10:
        red_flags.append(f"Sell tax of {security['sell_tax_pct']:.1f}% is high enough to trap value on exit.")
    if liquidity_to_mcap_pct is not None and liquidity_to_mcap_pct < _MIN_HEALTHY_LIQUIDITY_TO_MCAP_PCT:
        red_flags.append(f"Liquidity is only {liquidity_to_mcap_pct:.1f}% of market cap -- thin, high slippage risk.")
    top10_pct = security.get("top10_holder_pct")
    if top10_pct is not None and top10_pct > _MAX_HEALTHY_TOP10_HOLDER_PCT:
        red_flags.append(f"Top 10 individual wallets control {top10_pct:.1f}% of supply -- coordinated sell-off risk.")

    passed = not (
        security.get("is_honeypot")
        or security.get("is_mintable")
        or (liquidity_to_mcap_pct is not None and liquidity_to_mcap_pct < _MIN_HEALTHY_LIQUIDITY_TO_MCAP_PCT)
        or (top10_pct is not None and top10_pct > _MAX_HEALTHY_TOP10_HOLDER_PCT)
    )

    result = SafetyGateResult(
        has_contract=True,
        is_honeypot=security.get("is_honeypot"),
        is_mintable=security.get("is_mintable"),
        is_blacklistable=security.get("is_blacklistable"),
        is_open_source=security.get("is_open_source"),
        buy_tax_pct=security.get("buy_tax_pct"),
        sell_tax_pct=security.get("sell_tax_pct"),
        top10_holder_pct=top10_pct,
        liquidity_usd=liquidity_usd,
        liquidity_to_mcap_pct=liquidity_to_mcap_pct,
        passed=passed,
        red_flags=red_flags,
    )
    score = -1.0 if not passed else clamp(0.15 - 0.15 * len(red_flags))
    return result, score


def _build_derivatives(raw: dict) -> tuple[DerivativesResult, float]:
    funding = raw["funding_rate_pct"]
    taker_delta = raw["perp_taker_delta_pct"]

    if funding > _FUNDING_EXTREME_PCT and taker_delta > 0:
        note = (
            "Funding is richly positive with net-aggressive buying -- overleveraged longs, "
            "vulnerable to a squeeze lower if momentum stalls."
        )
        score = clamp(taker_delta / 25) - 0.25
    elif funding < -_FUNDING_EXTREME_PCT and taker_delta < 0:
        note = (
            "Funding is deeply negative with net-aggressive selling -- crowded short positioning, "
            "prime for a sharp short-squeeze rally if price stabilizes."
        )
        score = clamp(taker_delta / 25) + 0.25
    elif taker_delta > 5:
        note = "Taker flow skews net-buy, consistent with fresh long demand rather than short-covering."
        score = clamp(taker_delta / 25)
    elif taker_delta < -5:
        note = "Taker flow skews net-sell, consistent with active distribution."
        score = clamp(taker_delta / 25)
    else:
        note = "Funding and taker flow are both roughly balanced, with no strong positioning skew either way."
        score = 0.0

    result = DerivativesResult(
        open_interest_usd=raw["open_interest_usd"],
        funding_rate_pct=funding,
        perp_taker_delta_pct=taker_delta,
        regime_note=note,
    )
    return result, clamp(score, -0.4, 0.4)


def _netflow_score(onchain: OnChainMetrics) -> float:
    # Net outflow from exchanges (negative netflow) is typically read as
    # accumulation/bullish; net inflow suggests potential sell pressure.
    return clamp(-onchain.exchange_netflow_24h / 5000, -0.5, 0.5)


def _turnover_score(volume_24h: float, market_cap: float) -> float:
    if market_cap <= 0:
        return 0.0
    turnover = volume_24h / market_cap
    # Healthy turnover (~3-8%) is mildly bullish (liquid, active market);
    # very low turnover suggests waning interest.
    return clamp((turnover - 0.03) * 3, -0.3, 0.3)


def _ecosystem_score(notes: list[str]) -> float:
    text = " ".join(notes).lower()
    positive_hits = sum(word in text for word in _POSITIVE_WORDS)
    negative_hits = sum(word in text for word in _NEGATIVE_WORDS)
    return clamp((positive_hits - negative_hits) * 0.15, -0.3, 0.3)


def _fdv_score(circulating_to_fdv_pct: float) -> float:
    # Low circulating/FDV ratio = heavy future dilution overhang (structural
    # headwind); high ratio = little supply left to unlock, mildly
    # supportive but never a strong bullish signal on its own.
    return clamp((circulating_to_fdv_pct - 50) / 125, -0.4, 0.2)


def _btc_macro_score(asset: AssetInfo, btc_dominance_pct: float) -> float:
    if asset.base == "BTC":
        return 0.0
    # Crude altseason proxy: rising BTC dominance means capital is
    # concentrating in BTC at alts' expense, and vice versa.
    return clamp(-(btc_dominance_pct - 52) / 40, -0.2, 0.2)


def _build_summary(
    asset: AssetInfo,
    snapshot: dict,
    onchain: OnChainMetrics,
    notes: list[str],
    safety: SafetyGateResult,
    derivatives: DerivativesResult,
    circulating_to_fdv_pct: float,
    btc_dominance_pct: float,
) -> str:
    flow_note = (
        "net outflow from exchanges (accumulation signal)"
        if onchain.exchange_netflow_24h < 0
        else "net inflow to exchanges (potential sell pressure)"
    )
    safety_note = (
        f"SAFETY GATE FAILED -- {' '.join(safety.red_flags)} Per the safety-gate framework this trade should be "
        "skipped regardless of how the rest of the setup looks."
        if safety.has_contract and not safety.passed
        else (
            f"Safety gate passed (liquidity {safety.liquidity_to_mcap_pct:.1f}% of market cap, "
            f"top-10 holders at {safety.top10_holder_pct:.1f}%)."
            if safety.has_contract
            else "No contract to audit (native asset)."
        )
    )

    return (
        f"{safety_note} "
        f"Market cap ${snapshot['market_cap_usd']:,.0f} with 24h volume ${snapshot['volume_24h_usd']:,.0f}. "
        f"Circulating supply is {circulating_to_fdv_pct:.0f}% of fully diluted valuation "
        f"(${snapshot['fdv_usd']:,.0f} FDV). "
        f"On-chain data shows {onchain.active_addresses_24h:,} active addresses and {flow_note}. "
        f"Derivatives: {derivatives.regime_note} "
        f"BTC dominance is {btc_dominance_pct:.1f}%. "
        f"Ecosystem: {' '.join(notes)}"
    )
