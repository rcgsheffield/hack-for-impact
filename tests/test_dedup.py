"""Duplicate detection (app/dedup.py) and where it surfaces: route_report, filing, /api/submissions, tool display."""

from datetime import datetime, timedelta, timezone

import pytest

from app import config, dedup, submissions, tools
from app.tool_display import describe

T0 = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
M_PER_DEG_LAT = 111_195  # metres per degree of latitude
LAT, LON = 53.3631, -1.4876  # 120 Abbeydale Road (a sample address, so tests geocode it offline)


def item(ref, form="report_pothole_crack", minutes=0, north_m=None, location="Abbeydale Road", source="chat_agent",
         problem=""):
    lat = None if north_m is None else LAT + north_m / M_PER_DEG_LAT
    fields = {"rad_tree_problem": problem} if problem else {}
    return {"reference": ref, "form": form, "source": source, "submitted_at": (T0 + timedelta(minutes=minutes)).isoformat(),
            "lat": lat, "lon": None if north_m is None else LON, "location": location, "problem": problem,
            "raw": {"form_payload": fields}}


@pytest.fixture(autouse=True)
def dedup_settings(monkeypatch):
    monkeypatch.setattr(config, "DEDUP_RADIUS_M", 60.0)
    monkeypatch.setattr(config, "DEDUP_WINDOW_DAYS", 30.0)


def test_groups_reports_within_radius_and_annotates_every_item():
    items = [item("A", north_m=0), item("B", minutes=5, north_m=40), item("C", minutes=9, north_m=500)]
    groups = dedup.group(items)
    assert [(g["id"], g["size"]) for g in groups] == [("A", 2)]
    a, b, c = items
    assert a["duplicate"]["is_first"] and a["duplicate"]["group_size"] == 2
    assert b["duplicate"]["first_reference"] == "A" and not b["duplicate"]["is_first"]
    assert b["duplicate"]["distance_m"] == 40 and b["duplicate"]["match"] == "distance"
    assert c["duplicate"]["group_size"] == 1


def test_groups_around_the_first_report_not_by_chaining():
    # 0, 50, 100 m along a road: 100 m is within 60 m of 50 m, but not of the anchor at 0 m.
    groups = dedup.group([item("A", north_m=0), item("B", minutes=1, north_m=50), item("C", minutes=2, north_m=100)])
    assert [g["size"] for g in groups] == [2]
    assert {m["reference"] for m in groups[0]["members"]} == {"A", "B"}


def test_time_window():
    groups = dedup.group([item("A", north_m=0), item("B", minutes=60 * 24 * 31, north_m=10)])
    assert groups == []


def test_kinds_are_kept_apart():
    items = [item("P", north_m=0), item("T1", form="report_tree", minutes=1, north_m=5, problem="Fallen"),
             item("T2", form="report_tree", minutes=2, north_m=8, problem="Roots"),
             item("T3", form="report_tree", minutes=3, north_m=9, problem="Fallen")]
    groups = dedup.group(items)
    assert [sorted(m["reference"] for m in g["members"]) for g in groups] == [["T1", "T3"]]


def test_same_street_only_when_a_report_has_no_coordinates():
    near_no_coords = item("B", minutes=1, location="124 Abbeydale Rd")
    far_with_coords = item("C", minutes=2, north_m=900, location="300 Abbeydale Road")
    groups = dedup.group([item("A", north_m=0, location="120 Abbeydale Road"), near_no_coords, far_with_coords])
    assert [sorted(m["reference"] for m in g["members"]) for g in groups] == [["A", "B"]]
    assert groups[0]["approximate"] is True
    assert near_no_coords["duplicate"]["match"] == "street"


def test_groups_across_sources():
    groups = dedup.group([item("CHAT", source="chat_agent", north_m=0),
                          item("FORM", source="form_agent", minutes=3, north_m=20),
                          item("HAND", source="browser", minutes=4, north_m=-15)])
    assert groups[0]["size"] == 3
    assert groups[0]["sources"] == {"chat_agent": 1, "form_agent": 1, "browser": 1}


@pytest.mark.parametrize("street, expected", [("120 Abbeydale Rd, Sheffield, S7 1FL", "abbeydale road"),
                                              ("outside 3 Division St", "division street"), ("12", "")])
def test_street_key(street, expected):
    assert dedup.street_key(street) == expected


def test_similar_excludes_the_report_and_counts_reports_not_people():
    items = [item("A", north_m=0), item("B", minutes=1, north_m=10), item("ME", minutes=2, north_m=5)]
    result = dedup.similar(items, "report_pothole_crack", LAT, LON, exclude_reference="ME", now=T0 + timedelta(hours=1))
    assert result["count"] == 2 and result["references"] == ["A", "B"]
    assert result["message"].startswith("There are 2 other reports of a similar pothole or crack within about 60 m")
    assert "people" not in result["message"].split(".")[0]
    one = dedup.similar(items[:1], "report_pothole_crack", LAT, LON, now=T0 + timedelta(hours=1))
    assert one["message"].startswith("There is 1 other report")


def test_filing_twice_tells_the_second_reporter_and_route_report_warns_the_third():
    first = tools.file_report("road", "Greater than 40mm", "120 Abbeydale Road", "Deep pothole", 1)
    assert "similar_reports" not in first

    second = tools.file_report("road", "Greater than 40mm", "120 Abbeydale Road", "Pothole in the bus lane", 1)
    assert second["similar_reports"]["count"] == 1
    # A pothole over 40mm is P1, so the urgent phone advice comes first (urgency.py), then the similar reports.
    assert second["tell_user"] == [tools.URGENT_ADVICE, second["similar_reports"]["message"]]

    routed = tools.route_report("pothole", "120 Abbeydale Road", "another pothole")
    assert routed["can_file"] is True and routed["similar_reports"]["count"] == 2
    assert routed["next_step"].startswith("Mention the similar_reports message")
    assert "Still file this one" in routed["similar_reports"]["message"]

    data = submissions.load_submissions()
    assert [g["size"] for g in data["groups"]] == [2]
    assert {i["reference"] for i in data["submissions"] if i["duplicate"]["group_size"] == 2} == \
           {first["reference"], second["reference"]}


def test_route_report_without_earlier_reports_is_unchanged():
    assert "similar_reports" not in tools.route_report("pothole", "Fargate")


def test_tool_display_shows_similar_reports_without_the_emergency_icon():
    result = {"reference": "SCC-1", "status": "recorded", "similar_reports": {"count": 2, "message": "There are 2 other reports."},
              "tell_user": ["There are 2 other reports."]}
    _, body = describe("file_report", {"location": "Fargate"}, result)
    assert "👥 There are 2 other reports." in body
    assert "🚨" not in body
