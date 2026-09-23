from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.assets import AssetType


class Sentiment(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SignalCall(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OHLCVBar(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


# --- technical_analysis_agent ---------------------------------------------

class TechnicalIndicators(BaseModel):
    rsi_14: float
    macd: float
    macd_signal: float
    macd_histogram: float
    sma_20: float
    sma_50: float
    ema_12: float
    ema_26: float
    ema_50: float
    ema_200: float
    atr_14: float


class TechnicalAnalysisResult(BaseModel):
    symbol: str
    as_of: datetime
    latest_close: float
    indicators: TechnicalIndicators
    support_levels: list[float]
    resistance_levels: list[float]
    volume_poc: float  # point of control: the high-volume-node price level
    rsi_divergence: str | None  # "bullish" | "bearish" | None
    trend: Sentiment
    sentiment: Sentiment
    score: float  # -1.0 (max bearish) .. +1.0 (max bullish)
    summary: str


# --- forex_fundamentals_agent ----------------------------------------------

class EconomicEvent(BaseModel):
    event: str
    country: str
    scheduled_at: datetime
    impact: str  # low | medium | high
    forecast: str | None = None
    previous: str | None = None


class RiskRegimeResult(BaseModel):
    """Global risk-on/risk-off backdrop -- proxied off equities/gold/oil
    price action pulled through the same price feed as everything else,
    rather than a dedicated (and mostly paid) risk-sentiment provider."""

    regime: str  # "risk_on" | "risk_off" | "neutral"
    equities_trend: Sentiment
    safe_haven_demand: Sentiment  # gold trend as a safe-haven proxy


class PositioningResult(BaseModel):
    """CFTC Commitments of Traders snapshot for one currency's futures."""

    currency: str
    as_of_report_date: datetime | None
    net_speculative_position: float | None  # non-commercial longs minus shorts, contracts
    is_crowded_extreme: bool  # net position near a multi-period high/low -- overextension risk
    note: str


class ForexFundamentalsResult(BaseModel):
    symbol: str
    as_of: datetime
    upcoming_events: list[EconomicEvent]
    central_bank_commentary: str
    risk_regime: RiskRegimeResult
    positioning: list[PositioningResult]  # one per currency in the pair
    sentiment: Sentiment
    score: float
    summary: str


# --- crypto_fundamentals_agent ----------------------------------------------

class OnChainMetrics(BaseModel):
    active_addresses_24h: int
    transaction_count_24h: int
    exchange_netflow_24h: float


class SafetyGateResult(BaseModel):
    """On-chain safety gate: contract/honeypot checks + liquidity depth +
    holder concentration. Only meaningful for an actual token contract
    (has_contract=True) -- a base-layer asset like BTC/ETH has nothing to
    audit. `passed=False` is a hard "skip this trade" per the safety-gate
    framework, enforced as an override in signal_synthesis_agent, not just
    one more weighted vote."""

    has_contract: bool
    is_honeypot: bool | None = None
    is_mintable: bool | None = None
    is_blacklistable: bool | None = None
    is_open_source: bool | None = None
    buy_tax_pct: float | None = None
    sell_tax_pct: float | None = None
    top10_holder_pct: float | None = None
    liquidity_usd: float | None = None
    liquidity_to_mcap_pct: float | None = None
    # Weaker proxy, not true lock verification -- None means "not checked"
    # (no BSCSCAN_API_KEY set), not "assumed safe". See
    # lp_lock_heuristic.py for exactly what this does and doesn't prove.
    lp_holder_is_contract: bool | None = None
    passed: bool
    red_flags: list[str]


class DerivativesResult(BaseModel):
    """Futures positioning -- open interest, funding rate -- plus taker
    buy/sell volume delta on BOTH spot and perp (Binance), so a spot-led
    move (higher conviction) can be told apart from a perp-only one
    (speculative, unwinds fast once liquidations stall)."""

    open_interest_usd: float | None = None
    funding_rate_pct: float | None = None
    perp_taker_delta_pct: float | None = None  # net taker-buy volume, % of total taker volume
    spot_taker_delta_pct: float | None = None
    regime_note: str


class UnlockResult(BaseModel):
    """Next scheduled token unlock, when known. None fields mean "no
    unlock data available" -- a legitimate answer for most tokens (either
    genuinely no vesting schedule, or not tracked by the data source), not
    a failure."""

    days_until_next_unlock: float | None = None
    next_unlock_pct_of_circulating: float | None = None
    description: str | None = None
    is_imminent_large_unlock: bool = False


class CryptoFundamentalsResult(BaseModel):
    symbol: str
    as_of: datetime
    market_cap_usd: float
    volume_24h_usd: float
    circulating_supply: float
    fdv_usd: float
    circulating_to_fdv_pct: float
    onchain: OnChainMetrics
    ecosystem_notes: list[str]
    safety: SafetyGateResult
    derivatives: DerivativesResult
    next_unlock: UnlockResult
    btc_dominance_pct: float | None = None
    sentiment: Sentiment
    score: float
    summary: str


FundamentalsResult = ForexFundamentalsResult | CryptoFundamentalsResult


# --- news_aggregation_agent --------------------------------------------------

class NewsItem(BaseModel):
    headline: str
    source: str
    published_at: datetime
    url: str
    sentiment: Sentiment


class NewsAggregationResult(BaseModel):
    symbol: str
    as_of: datetime
    items: list[NewsItem]
    sentiment: Sentiment
    score: float
    summary: str


# --- signal_synthesis_agent --------------------------------------------------

class ComponentScores(BaseModel):
    technical: float
    fundamental: float
    news: float


class SynthesizedSignal(BaseModel):
    symbol: str
    asset_type: AssetType
    as_of: datetime
    signal: SignalCall
    confidence: float  # 0.0 .. 1.0
    component_scores: ComponentScores
    reasoning: str


# --- top-level analysis bundle returned by the API --------------------------

class AssetAnalysis(BaseModel):
    symbol: str
    asset_type: AssetType
    generated_at: datetime
    cached: bool
    technical: TechnicalAnalysisResult
    fundamentals: FundamentalsResult
    news: NewsAggregationResult
    signal: SynthesizedSignal
