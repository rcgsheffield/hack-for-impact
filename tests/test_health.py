import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, main


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return self

    def json(self):
        return self.payload


def fake_ollama(models):
    def get(url, timeout):
        if url.endswith("/api/version"):
            return FakeResponse({"version": "0.99.0"})
        return FakeResponse({"models": [{"name": m} for m in models]})
    return get


@pytest.fixture
def client():
    return TestClient(main.app)


def test_health_ok(client, monkeypatch):
    monkeypatch.setattr(main.httpx, "get", fake_ollama([config.OLLAMA_MODEL]))
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["ollama"] == "0.99.0"


def test_health_model_missing(client, monkeypatch):
    monkeypatch.setattr(main.httpx, "get", fake_ollama(["other:1b"]))
    r = client.get("/health")
    assert r.status_code == 503
    assert "not found" in r.json()["error"]


def test_health_ollama_down(client, monkeypatch):
    def down(url, timeout):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(main.httpx, "get", down)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["ok"] is False


def test_ui_is_served(client):
    assert client.get("/").status_code == 200
