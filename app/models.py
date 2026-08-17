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


class TechnicalAnalysisResult(BaseModel):
    symbol: str
    as_of: datetime
    latest_close: float
    indicators: TechnicalIndicators
    support_levels: list[float]
    resistance_levels: list[float]
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


class ForexFundamentalsResult(BaseModel):
    symbol: str
    as_of: datetime
    upcoming_events: list[EconomicEvent]
    central_bank_commentary: str
    sentiment: Sentiment
    score: float
    summary: str


# --- crypto_fundamentals_agent ----------------------------------------------

class OnChainMetrics(BaseModel):
    active_addresses_24h: int
    transaction_count_24h: int
    exchange_netflow_24h: float


class CryptoFundamentalsResult(BaseModel):
    symbol: str
    as_of: datetime
    market_cap_usd: float
    volume_24h_usd: float
    circulating_supply: float
    onchain: OnChainMetrics
    ecosystem_notes: list[str]
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
