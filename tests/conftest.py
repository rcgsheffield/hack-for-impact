import pytest

from app import config, geocode


@pytest.fixture(autouse=True)
def mock_submissions_path(tmp_path, monkeypatch):
    """Keep tests (including the browser ones, whose submit saves a record) out of the real data/ file."""
    path = tmp_path / "mock_submissions.jsonl"
    monkeypatch.setattr(config, "MOCK_SUBMISSIONS_PATH", path)
    # Filing now reads every source (duplicate detection), so keep the other data files out of the real data/ too.
    monkeypatch.setattr(config, "REPORTS_PATH", tmp_path / "reports.jsonl")
    monkeypatch.setattr(config, "USAGE_PATH", tmp_path / "usage.jsonl")
    monkeypatch.setattr(config, "UPLOADS_PATH", tmp_path / "uploads")
    return path


@pytest.fixture(autouse=True)
def no_live_geocoding(monkeypatch):
    """Only the built-in sample addresses: tests never call postcodes.io or Photon (test_geocode.py fakes them)."""
    monkeypatch.setattr(config, "GEOCODE_LIVE", False)
    geocode.cache_clear()
    yield
    geocode.cache_clear()


@pytest.fixture(autouse=True)
def no_llm_triage(tmp_path, monkeypatch):
    """No test calls the model in the background; signals are cached in a temporary file."""
    monkeypatch.setattr(config, "TRIAGE_LLM", False)
    monkeypatch.setattr(config, "TRIAGE_SIGNALS_PATH", tmp_path / "triage_signals.jsonl")
