import pytest

from app import config


@pytest.fixture(autouse=True)
def mock_submissions_path(tmp_path, monkeypatch):
    """Keep tests (including the browser ones, whose submit saves a record) out of the real data/ file."""
    path = tmp_path / "mock_submissions.jsonl"
    monkeypatch.setattr(config, "MOCK_SUBMISSIONS_PATH", path)
    return path
