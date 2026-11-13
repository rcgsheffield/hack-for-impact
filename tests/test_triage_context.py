"""Map context for triage (#27): road class and repeat-report clusters, offline with fixed coordinates."""

import json

import pytest

from app import config, triage_context
from app.submissions import load_submissions

LAT, LON = 53.3631, -1.4876  # 120 Abbeydale Road
PAYLOAD_30MM = {"rad_problem_location": "Road Surface", "rad_road_pothole_depth": "20mm to 40mm",
                "txt_find_address_about_the_location": "Somewhere", "txta_details_about_the_location": "30mm pothole"}


def report(ref, filed_at, road_class=None, lat=LAT, lon=LON, form=None):
    geo = {"lat": lat, "lon": lon, "matched": "x", "source": "photon"}
    if road_class:
        geo["road_class"] = road_class
    r = {"reference": ref, "filed_at": filed_at, "geo": geo, "form_payload": dict(PAYLOAD_30MM)}
    if form:
        r["form"] = form
    return r


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORTS_PATH", tmp_path / "reports.jsonl")
    monkeypatch.setattr(config, "USAGE_PATH", tmp_path / "usage.jsonl")

    def write(*records):
        (tmp_path / "reports.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        return {i["reference"]: i for i in load_submissions()["submissions"]}
    return write


def test_same_pothole_scores_higher_on_a_primary_road(reports):
    far = 0.01  # about 1 km apart: not a cluster
    items = reports(report("A", "2026-11-01T10:00:00+00:00", "primary"),
                    report("R", "2026-11-01T10:00:00+00:00", "residential", lat=LAT + far))
    a, r = items["A"]["triage"], items["R"]["triage"]
    assert a["score"] > r["score"]
    assert any("A road" in reason for reason in a["reasons"])
    assert a["engine"] == "rules+context" and r["engine"] == "rules"


def test_third_report_at_the_same_spot_raises_the_cluster(reports):
    one = reports(report("1", "2026-11-01T10:00:00+00:00"))["1"]
    assert one["report_count"] == 1 and one["triage"]["priority"] == "P3"

    # About 10 m apart, within 10 days; plus a tree report at the same spot, which is a different problem.
    items = reports(report("1", "2026-11-01T10:00:00+00:00"),
                    report("2", "2026-11-05T10:00:00+00:00", lat=LAT + 0.00009),
                    report("3", "2026-11-11T10:00:00+00:00", lon=LON + 0.0001),
                    report("T", "2026-11-11T10:00:00+00:00", form="report_tree"))
    cluster = [items[k] for k in "123"]
    assert {i["cluster_id"] for i in cluster} == {"C-1"}
    assert all(i["report_count"] == 3 for i in cluster)
    assert all("Reported 3 times in 10 days" in i["triage"]["reasons"] for i in cluster)
    assert all(i["triage"]["score"] > one["triage"]["score"] for i in cluster)
    assert items["1"]["triage"]["priority"] == "P2"
    assert items["T"]["report_count"] == 1 and items["T"]["cluster_id"] != "C-1"


def test_far_apart_or_old_reports_are_not_clustered(reports):
    items = reports(report("1", "2026-09-01T10:00:00+00:00"),            # 70 days earlier
                    report("2", "2026-11-10T10:00:00+00:00"),
                    report("3", "2026-11-10T10:00:00+00:00", lat=LAT + 0.0005))  # about 55 m away
    assert [items[k]["report_count"] for k in "123"] == [1, 1, 1]


def test_api_exposes_clusters(reports):
    from fastapi.testclient import TestClient
    from app import main

    reports(report("1", "2026-11-01T10:00:00+00:00"), report("2", "2026-11-02T10:00:00+00:00"))
    data = TestClient(main.app).get("/api/submissions").json()
    assert data["repeat_clusters"] == 1
    assert {(i["cluster_id"], i["report_count"]) for i in data["submissions"]} == {("C-1", 2)}


@pytest.mark.parametrize("road_class, points", [("trunk", 20), ("primary_link", 20), ("secondary", 15),
                                                ("cycleway", 10), ("residential", None), ("service", None), (None, None)])
def test_road_class_points(road_class, points):
    hit = triage_context.road_class_reason(road_class)
    assert (hit["points"] if hit else None) == points


def test_distance():
    assert triage_context.distance_m(LAT, LON, LAT + 0.0001, LON) == pytest.approx(11.1, abs=0.2)
