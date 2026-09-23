"""Global risk-on/risk-off regime, shared by forex_fundamentals_agent (its
overlay on currency pairs) and commodity_fundamentals_agent (precious
metals react to safe-haven demand, energy to growth expectations) --
proxied off equities/gold price action pulled through the same price feed
as everything else, rather than a dedicated (and mostly paid)
risk-sentiment provider.
"""

from app.agents.indicators import sma
from app.assets import AssetInfo, AssetType
from app.data_sources.price_feed import PriceFeedClient
from app.models import RiskRegimeResult, Sentiment

# Internal-only price-feed proxies -- not real tradable symbols, so
# deliberately not in the asset registry.
_GOLD_PROXY = AssetInfo(symbol="XAUUSD", display_name="Gold / US Dollar", asset_type=AssetType.COMMODITY, base="XAU", quote="USD")
_EQUITIES_PROXY = AssetInfo(
    symbol="US500USD", display_name="S&P 500 / US Dollar", asset_type=AssetType.FOREX, base="US500", quote="USD"
)


async def fetch_risk_regime(price_feed: PriceFeedClient) -> RiskRegimeResult:
    gold_bars = await price_feed.fetch_ohlcv(_GOLD_PROXY, bars=60)
    equities_bars = await price_feed.fetch_ohlcv(_EQUITIES_PROXY, bars=60)
    gold_trend = _trend_from_closes([b.close for b in gold_bars])
    equities_trend = _trend_from_closes([b.close for b in equities_bars])

    if equities_trend == Sentiment.BULLISH and gold_trend != Sentiment.BULLISH:
        regime = "risk_on"
    elif equities_trend == Sentiment.BEARISH and gold_trend == Sentiment.BULLISH:
        regime = "risk_off"
    else:
        regime = "neutral"

    return RiskRegimeResult(regime=regime, equities_trend=equities_trend, safe_haven_demand=gold_trend)


def _trend_from_closes(closes: list[float]) -> Sentiment:
    if len(closes) < 50:
        return Sentiment.NEUTRAL
    s20, s50, current = sma(closes, 20), sma(closes, 50), closes[-1]
    if current > s20 > s50:
        return Sentiment.BULLISH
    if current < s20 < s50:
        return Sentiment.BEARISH
    return Sentiment.NEUTRAL
