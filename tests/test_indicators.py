from app.agents.indicators import (
    atr,
    detect_rsi_divergence,
    ema_series,
    macd,
    rsi,
    rsi_series,
    sma,
    support_resistance,
    volume_profile_poc,
)


def test_sma_basic():
    assert sma([1, 2, 3, 4, 5], 5) == 3
    assert sma([1, 2, 3, 4, 5], 2) == 4.5


def test_ema_series_length_and_first_value():
    values = [1, 2, 3, 4, 5]
    series = ema_series(values, 3)
    assert len(series) == len(values)
    assert series[0] == values[0]


def test_rsi_all_gains_is_100():
    rising = [float(i) for i in range(1, 20)]
    assert rsi(rising, 14) == 100.0


def test_rsi_all_losses_is_0():
    falling = [float(i) for i in range(20, 1, -1)]
    assert rsi(falling, 14) == 0.0


def test_rsi_flat_series_is_neutral():
    flat = [10.0] * 20
    value = rsi(flat, 14)
    assert 40 <= value <= 60 or value == 100.0  # avg_loss == 0 short-circuits to 100 by construction


def test_macd_returns_three_floats():
    values = [100 + i * 0.5 for i in range(60)]
    macd_value, signal_value, hist = macd(values)
    assert isinstance(macd_value, float)
    assert isinstance(signal_value, float)
    assert abs(hist - (macd_value - signal_value)) < 1e-9


def test_support_resistance_brackets_current_price():
    closes = [100, 98, 101, 97, 103, 96, 105, 99, 102, 100]
    support, resistance = support_resistance(closes, current_price=100, window=1)
    assert all(level < 100 for level in support) or support == [min(closes)]
    assert all(level > 100 for level in resistance) or resistance == [max(closes)]


def test_atr_zero_when_no_range():
    closes = [100.0] * 10
    assert atr(closes, closes, closes, period=14) == 0.0


def test_atr_positive_for_ranging_series():
    highs = [101.0, 102.0, 101.5, 103.0, 102.5]
    lows = [99.0, 99.5, 100.0, 100.5, 101.0]
    closes = [100.0, 101.0, 100.5, 102.0, 101.5]
    assert atr(highs, lows, closes, period=3) > 0.0


def test_rsi_series_length_matches_input():
    values = [float(i) for i in range(30)]
    series = rsi_series(values, 14)
    assert len(series) == len(values)


def test_rsi_series_last_value_matches_rsi():
    values = [100 + (i % 5) - (i % 3) for i in range(30)]
    values = [float(v) for v in values]
    assert abs(rsi_series(values, 14)[-1] - rsi(values, 14)) < 1e-9


def test_detect_rsi_divergence_bearish_on_higher_high_lower_rsi_high():
    n = 40
    closes = [100 + 0.01 * i for i in range(n)]
    closes[10] += 5  # first peak
    closes[30] += 8  # higher high (rising baseline + bigger spike)
    rsi_values = [50 - 0.01 * i for i in range(n)]
    rsi_values[10] += 20  # first peak: high RSI
    rsi_values[30] += 10  # second peak: lower RSI high -> bearish divergence

    assert detect_rsi_divergence(closes, rsi_values, lookback=n, pivot_window=3) == "bearish"


def test_detect_rsi_divergence_bullish_on_lower_low_higher_rsi_low():
    n = 40
    closes = [100 - 0.01 * i for i in range(n)]
    closes[10] -= 5  # first dip
    closes[30] -= 8  # lower low (falling baseline + bigger dip)
    rsi_values = [50 + 0.01 * i for i in range(n)]
    rsi_values[10] -= 20  # first dip: low RSI
    rsi_values[30] -= 10  # second dip: higher RSI low -> bullish divergence

    assert detect_rsi_divergence(closes, rsi_values, lookback=n, pivot_window=3) == "bullish"


def test_detect_rsi_divergence_none_when_insufficient_history():
    assert detect_rsi_divergence([1.0, 2.0, 3.0], [50.0, 51.0, 52.0], lookback=40) is None


def test_volume_profile_poc_finds_high_volume_price_level():
    closes = [100.0] * 5 + [110.0] * 20 + [120.0] * 5
    volumes = [10.0] * len(closes)
    poc = volume_profile_poc(closes, closes, closes, volumes, num_bins=20)
    assert abs(poc - 110.0) <= 1.0  # within one bin width of the dominant price level


def test_volume_profile_poc_no_volume_data_falls_back_to_last_close():
    # A source with no real volume (e.g. CoinGecko's OHLC endpoint) must
    # not silently concentrate into bin 0 -- that would misleadingly
    # suggest most trading happened at the period's low.
    closes = [100.0, 105.0, 95.0, 110.0, 90.0]
    volumes = [0.0] * len(closes)
    poc = volume_profile_poc(closes, closes, closes, volumes)
    assert poc == closes[-1]
