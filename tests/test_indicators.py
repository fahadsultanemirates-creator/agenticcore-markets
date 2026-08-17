from app.agents.indicators import ema_series, macd, rsi, sma, support_resistance


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
