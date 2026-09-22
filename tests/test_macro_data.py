"""Unit tests for the pure parse functions in macro_data.py against
realistic FRED observation payloads (newest-first, monthly)."""

from app.data_sources.macro_data import MacroDataClient, parse_cpi_yoy, parse_payrolls_change


def _obs(value: str) -> dict:
    return {"date": "2026-01-01", "value": value}


def test_parse_cpi_yoy_computes_percent_change():
    # 13 consecutive monthly observations, newest-first: index 0 = latest
    # (310.0), index 12 = 12 months prior (300.0).
    values = [300.0 + i * (10.0 / 12) for i in range(13)]
    values.reverse()
    observations = [_obs(str(v)) for v in values]
    yoy = parse_cpi_yoy(observations)
    assert yoy is not None
    assert abs(yoy - ((values[0] - values[12]) / values[12] * 100)) < 1e-6


def test_parse_cpi_yoy_insufficient_history_returns_none():
    assert parse_cpi_yoy([_obs("300.0")] * 5) is None


def test_parse_payrolls_change():
    observations = [_obs("158200.0"), _obs("158000.0")]
    change = parse_payrolls_change(observations)
    assert abs(change - 200.0) < 1e-9


def test_parse_payrolls_change_insufficient_history_returns_none():
    assert parse_payrolls_change([_obs("158200.0")]) is None


def test_macro_data_client_unavailable_without_key():
    client = MacroDataClient()
    assert client.is_available() is False
