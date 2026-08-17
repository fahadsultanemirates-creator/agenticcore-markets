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
