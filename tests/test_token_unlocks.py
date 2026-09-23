"""Unit tests for the pure parse function in token_unlocks.py against a
realistic DefiLlama emissions payload shape."""

from datetime import datetime, timedelta, timezone

from app.data_sources.token_unlocks import TokenUnlocksClient, parse_next_unlock


def _future_ts(days: float) -> float:
    return (datetime.now(timezone.utc) + timedelta(days=days)).timestamp()


def test_parse_next_unlock_picks_soonest_future_event():
    payload = {
        "events": [
            {"timestamp": _future_ts(30), "noOfTokens": [1_000_000], "description": "Later tranche"},
            {"timestamp": _future_ts(5), "noOfTokens": [500_000], "description": "Soonest tranche"},
            {"timestamp": _future_ts(-10), "noOfTokens": [9_000_000], "description": "Past event, ignored"},
        ]
    }
    result = parse_next_unlock(payload, circulating_supply=10_000_000)
    assert result is not None
    assert result["description"] == "Soonest tranche"
    assert abs(result["days_until_next_unlock"] - 5.0) < 0.1
    assert abs(result["next_unlock_pct_of_circulating"] - 5.0) < 0.1


def test_parse_next_unlock_sums_list_of_token_amounts():
    payload = {"events": [{"timestamp": _future_ts(10), "noOfTokens": [200_000, 300_000]}]}
    result = parse_next_unlock(payload, circulating_supply=10_000_000)
    assert result is not None
    assert abs(result["next_unlock_pct_of_circulating"] - 5.0) < 0.1


def test_parse_next_unlock_no_future_events_returns_none():
    payload = {"events": [{"timestamp": _future_ts(-5), "noOfTokens": [1_000_000]}]}
    assert parse_next_unlock(payload, circulating_supply=10_000_000) is None


def test_parse_next_unlock_empty_payload_returns_none():
    assert parse_next_unlock({}, circulating_supply=10_000_000) is None


def test_parse_next_unlock_zero_circulating_supply_returns_none():
    payload = {"events": [{"timestamp": _future_ts(5), "noOfTokens": [1_000_000]}]}
    assert parse_next_unlock(payload, circulating_supply=0) is None


def test_synthetic_next_unlock_is_deterministic():
    client = TokenUnlocksClient()
    from app.assets import get_asset

    asset = get_asset("ACUSD")
    first = client.synthetic_next_unlock(asset)
    second = client.synthetic_next_unlock(asset)
    assert first == second
