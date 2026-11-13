"""The dummy council site is served at /mock/ and its page loads and submissions are logged."""

import json

import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "USAGE_PATH", path)
    return path


@pytest.fixture
def client():
    return TestClient(main.app)


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_page_view_is_served_and_logged(client, log):
    r = client.get("/mock/report_pothole_crack.html", headers={"user-agent": "HeadlessChrome/1"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    [record] = lines(log)
    assert record["event"] == "view"
    assert record["page"] == "report_pothole_crack.html"
    assert record["user_agent"] == "HeadlessChrome/1"
    assert record["ts"]


def test_submit_is_logged(client, log):
    r = client.post("/mock/events", json={"event": "submit", "page": "report_tree.html", "reference": "123456789"})
    assert r.status_code == 204
    [record] = lines(log)
    assert record["event"] == "submit"
    assert record["reference"] == "123456789"


@pytest.mark.parametrize("name", ["missing.html", "..%2Fapp%2Fconfig.py", "%2E%2E%2Fapp%2Fconfig.py", "README"])
def test_unknown_pages_are_404_and_not_logged(client, log, name):
    assert client.get(f"/mock/{name}").status_code == 404
    assert lines(log) == []


def test_bad_event_is_rejected(client, log):
    assert client.post("/mock/events", json={"event": "delete", "page": "x"}).status_code == 422
    assert lines(log) == []
