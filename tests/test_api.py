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


def test_analysis_endpoint_unknown_symbol_returns_404():
    resp = client.get("/api/v1/analysis/DOGEUSD")
    assert resp.status_code == 404
