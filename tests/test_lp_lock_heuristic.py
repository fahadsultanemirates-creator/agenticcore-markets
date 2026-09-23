"""Unit tests for lp_lock_heuristic.py's no-key/no-input guard paths --
the parts reachable without a live BscScan call or a configured API key.

These explicitly force settings.bscscan_api_key to None via monkeypatch
rather than relying on it being unset in the environment -- a real
deployment (or a dev .env with a real key configured) must not make these
"no key" guard-path tests start failing."""

from app.config import settings
from app.data_sources.lp_lock_heuristic import LpLockHeuristicClient


def test_unavailable_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "bscscan_api_key", None)
    client = LpLockHeuristicClient()
    assert client.is_available() is False


async def test_check_top_holder_type_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "bscscan_api_key", None)
    client = LpLockHeuristicClient()
    result = await client.check_top_holder_type("0x1234567890123456789012345678901234567890")
    assert result is None


async def test_check_top_holder_type_returns_none_without_pair_address():
    client = LpLockHeuristicClient()
    result = await client.check_top_holder_type(None)
    assert result is None
