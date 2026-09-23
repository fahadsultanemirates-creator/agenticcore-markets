from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_list_assets_includes_eurusd_and_btcusd():
    resp = client.get("/api/v1/assets")
    assert resp.status_code == 200
    symbols = {a["symbol"] for a in resp.json()}
    assert "EURUSD" in symbols
    assert "BTCUSD" in symbols


def test_list_assets_covers_28_forex_pairs_and_commodities():
    resp = client.get("/api/v1/assets")
    assert resp.status_code == 200
    assets = resp.json()
    forex_symbols = {a["symbol"] for a in assets if a["asset_type"] == "forex"}
    commodity_symbols = {a["symbol"] for a in assets if a["asset_type"] == "commodity"}
    assert len(forex_symbols) == 28
    assert {"XAUUSD", "XAGUSD", "USOILUSD", "UKOILUSD", "NATGASUSD"} <= commodity_symbols


def test_analysis_endpoint_eurusd():
    resp = client.get("/api/v1/analysis/EURUSD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "EURUSD"
    assert body["signal"]["signal"] in {"BUY", "SELL", "HOLD"}
    assert body["signal"]["reasoning"]


def test_analysis_endpoint_btcusd():
    resp = client.get("/api/v1/analysis/BTCUSD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "BTCUSD"
    assert body["asset_type"] == "crypto"


def test_analysis_endpoint_acusd_includes_safety_gate():
    resp = client.get("/api/v1/analysis/ACUSD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "ACUSD"
    assert body["fundamentals"]["safety"]["has_contract"] is True


def test_analysis_endpoint_commodity_xauusd():
    resp = client.get("/api/v1/analysis/XAUUSD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "XAUUSD"
    assert body["asset_type"] == "commodity"
    assert "rate_backdrop" in body["fundamentals"]


def test_analysis_endpoint_model_param_falls_back_without_keys_configured(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", None)

    resp = client.get("/api/v1/analysis/USDJPY", params={"model": "gemini"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["signal"]["signal"] in {"BUY", "SELL", "HOLD"}


def test_analysis_endpoint_invalid_model_param_returns_422():
    resp = client.get("/api/v1/analysis/EURUSD", params={"model": "gpt4"})
    assert resp.status_code == 422


def test_analysis_endpoint_unknown_symbol_returns_404():
    # A nonsense string, not a real token -- unlike a real symbol
    # (e.g. DOGEUSD), this must 404 even once dynamic crypto resolution
    # (asset_resolver.py) has real internet access, since it genuinely
    # doesn't resolve to anything on CoinGecko. In this sandbox, egress is
    # blocked entirely, so resolution fails and 404s regardless -- but this
    # symbol is chosen so the test's assumption holds in both environments.
    resp = client.get("/api/v1/analysis/NOTAREALTOKENXYZ999")
    assert resp.status_code == 404
