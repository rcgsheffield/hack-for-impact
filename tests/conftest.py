import pytest

from app import config, geocode


@pytest.fixture(autouse=True)
def mock_submissions_path(tmp_path, monkeypatch):
    """Keep tests (including the browser ones, whose submit saves a record) out of the real data/ file."""
    path = tmp_path / "mock_submissions.jsonl"
    monkeypatch.setattr(config, "MOCK_SUBMISSIONS_PATH", path)
    return path


@pytest.fixture(autouse=True)
def no_live_geocoding(monkeypatch):
    """Only the built-in sample addresses: tests never call postcodes.io or Photon (test_geocode.py fakes them)."""
    monkeypatch.setattr(config, "GEOCODE_LIVE", False)
    geocode.cache_clear()
    yield
    geocode.cache_clear()
