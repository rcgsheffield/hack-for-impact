"""The submissions dashboard: records saved by the form agents, normalised with the other logs and served."""

import json

import pytest
from fastapi.testclient import TestClient

from app import config, main
from app.submissions import load_submissions, save_submission

MOCK_RECORD = {
    "form": "report_tree", "mock": True, "submitted_to_council": False, "reference": "123456789", "anonymous": False,
    "txt_finish_date_and_time": "2026-11-13T12:00:00.000Z", "le_title": "Problem with a tree", "le_gis": "53.38,-1.47",
    "fields": {"rad_tree_location": "Highway", "rad_tree_problem": "Fallen", "rad_tree_blocking": "Yes",
               "txt_find_address_about_the_location": "Derbyshire Lane", "txta_details_about_the_location": "Branch down",
               "txt_firstname": "Ada", "eml_address": "ada@example.com", "tel_phone_number": "0114 000 0000"},
}


@pytest.fixture
def logs(tmp_path, monkeypatch, mock_submissions_path):
    monkeypatch.setattr(config, "REPORTS_PATH", tmp_path / "reports.jsonl")
    monkeypatch.setattr(config, "USAGE_PATH", tmp_path / "usage.jsonl")
    save_submission(MOCK_RECORD)
    (tmp_path / "reports.jsonl").write_text(json.dumps({
        "reference": "SCC-20261113-ABCD", "filed_at": "2026-11-13T13:00:00+00:00", "suggested_category": 1,
        "geo": {"lat": 53.3814, "lon": -1.4694, "matched": "Fargate, Sheffield", "source": "photon"},
        "form_payload": {"rad_problem_location": "Road Surface", "rad_road_pothole_depth": "Greater than 40mm",
                         "txt_find_address_about_the_location": "10 Fargate",
                         "txta_details_about_the_location": "Deep pothole"}}) + "\nnot json\n")
    (tmp_path / "usage.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"ts": "2026-11-13T11:00:00+00:00", "event": "view", "page": "report_tree.html", "user_agent": "HeadlessChrome/1"},
        {"ts": "2026-11-13T11:05:00+00:00", "event": "view", "page": "report_tree.html", "user_agent": "Firefox"},
        # Same reference as the agent's record: not listed twice.
        {"ts": "2026-11-13T12:00:01+00:00", "event": "submit", "page": "report_tree.html", "reference": "123456789"},
        {"ts": "2026-11-13T14:00:00+00:00", "event": "submit", "page": "report_pothole_crack.html", "reference": "987654321",
         "location": "88 London Road", "lat": 53.3672, "lon": -1.4775, "geo_source": "form"},
    ]) + "\n")
    return tmp_path


def test_saved_record_has_no_personal_details(mock_submissions_path):
    save_submission(MOCK_RECORD)
    [saved] = [json.loads(line) for line in mock_submissions_path.read_text().splitlines()]
    assert saved["reference"] == "123456789"
    assert saved["recorded_at"]
    assert "txt_firstname" not in saved["fields"] and "eml_address" not in saved["fields"]
    assert saved["fields"]["rad_tree_problem"] == "Fallen"


def test_save_geocodes_a_typed_address(mock_submissions_path):
    """The form agent fell back to "use what I typed", so the form has no coordinates."""
    typed = {**MOCK_RECORD, "le_gis": "",
             "fields": {**MOCK_RECORD["fields"], "txt_full_address_about_the_location": "12 Derbyshire Lane"}}
    save_submission(typed)
    [saved] = [json.loads(line) for line in mock_submissions_path.read_text().splitlines()]
    assert (saved["le_gis"], saved["geo_source"]) == ("53.346,-1.479", "sample")
    [item] = load_submissions()["submissions"]
    assert (item["lat"], item["lon"], item["geo_source"]) == (53.346, -1.479, "sample")


def test_save_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MOCK_SUBMISSIONS_PATH", tmp_path)  # a directory: the write fails
    save_submission(MOCK_RECORD)


def test_loads_all_sources_newest_first(logs):
    data = load_submissions()
    assert [(s["source"], s["reference"]) for s in data["submissions"]] == [
        ("browser", "987654321"), ("chat_agent", "SCC-20261113-ABCD"), ("form_agent", "123456789")]
    browser, chat, tree = data["submissions"]
    assert tree["problem"] == "Fallen, blocking"
    assert tree["location"] == "Derbyshire Lane"
    assert (tree["lat"], tree["lon"], tree["geo_source"]) == (53.38, -1.47, "form")
    assert (chat["lat"], chat["lon"], chat["geo_source"]) == (53.3814, -1.4694, "photon")
    assert (browser["lat"], browser["lon"], browser["location"]) == (53.3672, -1.4775, "88 London Road")
    assert chat["problem"] == "Road: Greater than 40mm"
    assert browser["form"] == "report_pothole_crack"
    assert data["views"] == {"report_tree": {"agent": 1, "person": 1}}


def test_api_and_page_are_served(logs):
    client = TestClient(main.app)
    r = client.get("/api/submissions")
    assert r.status_code == 200
    assert r.json()["count"] == 3
    assert "Ada" not in r.text
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Submissions dashboard" in page.text
