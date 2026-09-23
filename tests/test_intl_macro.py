"""Unit tests for the pure parse function in intl_macro.py against the
real World Bank response shape: [metadata, data_array], newest first."""

from app.data_sources.intl_macro import parse_world_bank_latest_value


def test_parse_world_bank_latest_value_returns_first_non_null():
    payload = [
        {"page": 1, "pages": 1, "per_page": 5, "total": 3},
        [
            {"date": "2024", "value": None},
            {"date": "2023", "value": 2.1},
            {"date": "2022", "value": 3.4},
        ],
    ]
    assert parse_world_bank_latest_value(payload) == 2.1


def test_parse_world_bank_latest_value_all_null_returns_none():
    payload = [{"page": 1}, [{"date": "2024", "value": None}, {"date": "2023", "value": None}]]
    assert parse_world_bank_latest_value(payload) is None


def test_parse_world_bank_latest_value_empty_data_returns_none():
    payload = [{"page": 1}, []]
    assert parse_world_bank_latest_value(payload) is None


def test_parse_world_bank_latest_value_malformed_payload_returns_none():
    assert parse_world_bank_latest_value({}) is None
    assert parse_world_bank_latest_value([{"page": 1}]) is None
