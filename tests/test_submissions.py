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
        "form_payload": {"rad_problem_location": "Road Surface", "rad_road_pothole_depth": "Greater than 40mm",
                         "txt_find_address_about_the_location": "10 Fargate",
                         "txta_details_about_the_location": "Deep pothole"}}) + "\nnot json\n")
    (tmp_path / "usage.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"ts": "2026-11-13T11:00:00+00:00", "event": "view", "page": "report_tree.html", "user_agent": "HeadlessChrome/1"},
        {"ts": "2026-11-13T11:05:00+00:00", "event": "view", "page": "report_tree.html", "user_agent": "Firefox"},
        # Same reference as the agent's record: not listed twice.
        {"ts": "2026-11-13T12:00:01+00:00", "event": "submit", "page": "report_tree.html", "reference": "123456789"},
        {"ts": "2026-11-13T14:00:00+00:00", "event": "submit", "page": "report_pothole_crack.html", "reference": "987654321"},
    ]) + "\n")
    return tmp_path


def test_saved_record_has_no_personal_details(mock_submissions_path):
    save_submission(MOCK_RECORD)
    [saved] = [json.loads(line) for line in mock_submissions_path.read_text().splitlines()]
    assert saved["reference"] == "123456789"
    assert saved["recorded_at"]
    assert "txt_firstname" not in saved["fields"] and "eml_address" not in saved["fields"]
    assert saved["fields"]["rad_tree_problem"] == "Fallen"


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
    assert (tree["lat"], tree["lon"]) == (53.38, -1.47)
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


def test_report_api_returns_one_report(logs):
    client = TestClient(main.app)
    r = client.get("/api/reports/SCC-20261113-ABCD")
    assert r.status_code == 200
    report = r.json()["report"]
    assert report["source"] == "chat_agent"
    assert report["problem"] == "Road: Greater than 40mm"
    tree = client.get("/api/reports/123456789")
    assert tree.status_code == 200
    assert "Ada" not in tree.text and "ada@example.com" not in tree.text
    assert client.get("/api/reports/nope").status_code == 404


def test_report_page_and_library_are_served(logs):
    client = TestClient(main.app)
    page = client.get("/reports/SCC-20261113-ABCD")
    assert page.status_code == 200
    assert "/static/report-card.js" in page.text
    # Mounted before Gradio, so not shadowed by its catch-all routes.
    js = client.get("/static/report-card.js")
    assert js.status_code == 200 and "ReportCard" in js.text
    assert client.get("/static/report-card.css").status_code == 200


def test_chat_agent_tree_report_keeps_its_form(logs):
    with (logs / "reports.jsonl").open("a") as f:
        f.write(json.dumps({"reference": "SCC-20261113-TREE", "filed_at": "2026-11-13T15:00:00+00:00",
                            "form": "report_tree", "form_payload": {"rad_tree_location": "Highway",
                                                                    "rad_tree_problem": "Fallen"}}) + "\n")
    report = TestClient(main.app).get("/api/reports/SCC-20261113-TREE").json()["report"]
    assert (report["form"], report["title"], report["problem"]) == ("report_tree", "Problem with a tree", "Fallen")


def test_chat_agent_report_with_a_shared_location_goes_on_the_map(logs):
    from app import tools

    tools.file_report("road", "Greater than 40mm", "Chesterfield Road", "Deep pothole", lat=53.346012, lon=-1.479034)
    reports = {i["reference"]: i for i in load_submissions()["submissions"] if i["source"] == "chat_agent"}
    pinned = [i for i in reports.values() if i["lat"] is not None]
    assert [(i["lat"], i["lon"]) for i in pinned] == [(53.346012, -1.479034)]
    assert reports["SCC-20261113-ABCD"]["lat"] is None  # no location shared
