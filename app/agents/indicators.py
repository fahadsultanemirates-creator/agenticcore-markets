"""Pure indicator math shared by technical_analysis_agent. No provider or
asset-class knowledge here — just numbers in, numbers out — so it's trivial
to unit test in isolation.
"""


def sma(values: list[float], period: int) -> float:
    window = values[-period:]
    return sum(window) / len(window)


def ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) < period + 1:
        period = len(values) - 1
    if period <= 0:
        return 50.0

    gains = []
    losses = []
    for i in range(-period, 0):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values: list[float], fast: int = 12, slow: int = 26, signal_period: int = 9) -> tuple[float, float, float]:
    ema_fast = ema_series(values, fast)
    ema_slow = ema_series(values, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema_series(macd_line, signal_period)
    macd_value = macd_line[-1]
    signal_value = signal_line[-1]
    return macd_value, signal_value, macd_value - signal_value


def rsi_series(values: list[float], period: int = 14) -> list[float]:
    """Rolling RSI at every index from `period` onward (index < period holds
    the neutral placeholder 50.0, since there isn't enough history yet).
    Separate from rsi() -- which only needs the latest value -- because
    divergence detection needs to compare RSI's own local extrema against
    price's, at matching points in time."""
    if len(values) < period + 1:
        return [50.0] * len(values)

    out = [50.0] * period
    for end in range(period, len(values)):
        window = values[end - period : end + 1]
        gains = [max(window[i] - window[i - 1], 0.0) for i in range(1, len(window))]
        losses = [max(window[i - 1] - window[i], 0.0) for i in range(1, len(window))]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            out.append(100.0)
        else:
            rs = avg_gain / avg_loss
            out.append(100 - (100 / (1 + rs)))
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """Average True Range -- volatility measure used for stop sizing and
    gauging whether a move is significant relative to normal noise."""
    if len(closes) < 2:
        return 0.0

    true_ranges = []
    for i in range(1, len(closes)):
        high_low = highs[i] - lows[i]
        high_prev_close = abs(highs[i] - closes[i - 1])
        low_prev_close = abs(lows[i] - closes[i - 1])
        true_ranges.append(max(high_low, high_prev_close, low_prev_close))

    window = true_ranges[-period:] if len(true_ranges) >= period else true_ranges
    return sum(window) / len(window)


def detect_rsi_divergence(closes: list[float], rsi_values: list[float], lookback: int = 40, pivot_window: int = 3) -> str | None:
    """Regular divergence between price and RSI over the recent lookback
    window: bearish = price makes a higher high while RSI makes a lower
    high (momentum fading into new highs); bullish = price makes a lower
    low while RSI makes a higher low (selling pressure fading into new
    lows). Returns "bullish", "bearish", or None if neither pivot pattern
    is present or there isn't enough history."""
    n = len(closes)
    if n < lookback or n != len(rsi_values):
        return None

    recent_closes = closes[-lookback:]
    recent_rsi = rsi_values[-lookback:]

    def pivots(series: list[float], find_highs: bool) -> list[int]:
        idxs = []
        for i in range(pivot_window, len(series) - pivot_window):
            segment = series[i - pivot_window : i + pivot_window + 1]
            if find_highs and series[i] == max(segment):
                idxs.append(i)
            if not find_highs and series[i] == min(segment):
                idxs.append(i)
        return idxs

    high_idxs = pivots(recent_closes, find_highs=True)
    if len(high_idxs) >= 2:
        i1, i2 = high_idxs[-2], high_idxs[-1]
        if recent_closes[i2] > recent_closes[i1] and recent_rsi[i2] < recent_rsi[i1]:
            return "bearish"

    low_idxs = pivots(recent_closes, find_highs=False)
    if len(low_idxs) >= 2:
        i1, i2 = low_idxs[-2], low_idxs[-1]
        if recent_closes[i2] < recent_closes[i1] and recent_rsi[i2] > recent_rsi[i1]:
            return "bullish"

    return None


def volume_profile_poc(highs: list[float], lows: list[float], closes: list[float], volumes: list[float], num_bins: int = 20) -> float:
    """Point of Control: the price level that traded the most volume over
    the window, using each bar's typical price ((H+L+C)/3) weighted by its
    volume, binned across the period's price range. This is the "fair
    value"/high-volume-node reference point for entries -- distinct from a
    simple pivot, since it reflects where the most trading actually
    happened, not just the extremes."""
    if not closes:
        return 0.0
    if sum(volumes) <= 0:
        # No real volume data for this bar set (e.g. CoinGecko's OHLC
        # endpoint, used for broad crypto coverage in price_feed.py,
        # doesn't return volume) -- a volume-weighted POC is meaningless
        # here. The current price is a more honest neutral fallback than
        # silently concentrating everything into bin 0, which an all-zero
        # volumes list would otherwise do.
        return closes[-1]

    typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    lo, hi = min(typical_prices), max(typical_prices)
    if hi == lo:
        return closes[-1]

    bin_width = (hi - lo) / num_bins
    bin_volumes = [0.0] * num_bins
    for price, vol in zip(typical_prices, volumes):
        bin_index = min(int((price - lo) / bin_width), num_bins - 1)
        bin_volumes[bin_index] += vol

    poc_bin = max(range(num_bins), key=lambda i: bin_volumes[i])
    return lo + (poc_bin + 0.5) * bin_width


def support_resistance(closes: list[float], current_price: float, window: int = 3, max_levels: int = 2) -> tuple[list[float], list[float]]:
    """Find local swing highs/lows (pivots) in recent closes and split them
    into support (below current price) and resistance (above), closest
    first."""
    pivots_low: list[float] = []
    pivots_high: list[float] = []

    for i in range(window, len(closes) - window):
        segment = closes[i - window : i + window + 1]
        center = closes[i]
        if center == min(segment):
            pivots_low.append(center)
        if center == max(segment):
            pivots_high.append(center)

    support = sorted({p for p in pivots_low if p < current_price}, reverse=True)[:max_levels]
    resistance = sorted({p for p in pivots_high if p > current_price})[:max_levels]

    if not support:
        support = [min(closes)]
    if not resistance:
        resistance = [max(closes)]

    return support, resistance
