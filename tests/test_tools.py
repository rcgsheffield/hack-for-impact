import json
import re

import pytest

from app import config, tools


@pytest.fixture(autouse=True)
def reports_path(tmp_path, monkeypatch):
    path = tmp_path / "reports.jsonl"
    monkeypatch.setattr(config, "REPORTS_PATH", path)
    return path


@pytest.mark.parametrize(
    ("problem", "place", "owner", "can_file"),
    [
        ("pothole", "Fargate", "Sheffield City Council", True),
        ("pavement_surface", "Ecclesall Road", "Sheffield City Council", True),
        ("pothole", "Stocksbridge Bypass", "National Highways", False),
        ("pothole", "A631 Tinsley Viaduct lower deck", "National Highways", False),
        ("pothole", "M1 junction 34", "National Highways", False),
        ("pothole", "supermarket car park, Abbeydale Road", "The landowner", False),
        ("untaxed_vehicle", "Fargate", "DVLA", False),
        ("obstructing_vehicle", "Fargate", "South Yorkshire Police", False),
        ("street_light", "Fargate", "Sheffield City Council", False),
    ],
)
def test_route_report(problem, place, owner, can_file):
    result = tools.route_report(problem, place)
    assert result["owner"].startswith(owner)
    assert result["can_file"] is can_file


def test_route_report_rejects_unknown_type():
    with pytest.raises(ValueError):
        tools.route_report("dragon", "Fargate")


@pytest.mark.parametrize(
    ("surface", "depth", "band", "category"),
    [
        ("road", 50, "Greater than 40mm", 1),
        ("road", 40, "Less than 40mm", 2),
        ("pavement", 25, "Greater than 20mm", 1),
        ("pavement", 10, "Less than 20mm", 2),
    ],
)
def test_assess_pothole(surface, depth, band, category):
    result = tools.assess_pothole(surface, depth)
    assert result["depth_band"] == band
    assert result["suggested_category"] == category


def test_file_report_writes_form_payload(reports_path):
    result = tools.file_report("road", "Greater than 40mm", "10 Fargate", "Deep pothole", 1)
    assert re.fullmatch(r"SCC-\d{8}-[0-9A-F]{4}", result["reference"])
    assert result["url"] == f"/reports/{result['reference']}"
    record = json.loads(reports_path.read_text().strip())
    assert record["reference"] == result["reference"]
    assert record["form_payload"] == {
        "rad_problem_location": "Road Surface",
        "rad_road_pothole_depth": "Greater than 40mm",
        "txt_find_address_about_the_location": "10 Fargate",
        "txta_details_about_the_location": "Deep pothole",
    }


def test_file_report_rejects_band_for_wrong_surface(reports_path):
    with pytest.raises(ValueError):
        tools.file_report("pavement", "Greater than 40mm", "Fargate", "Crack")
    assert not reports_path.exists()


def test_call_tool_returns_errors_instead_of_raising():
    assert "error" in tools.call_tool("nope", "{}")
    assert "error" in tools.call_tool("assess_pothole", "{not json")
    assert "error" in tools.call_tool("assess_pothole", '{"surface": "road"}')
    assert "error" in tools.call_tool("assess_pothole", '{"surface": "sky", "depth_mm": 3}')
    assert tools.call_tool("assess_pothole", '{"surface": "road", "depth_mm": 50}')["suggested_category"] == 1


@pytest.mark.parametrize(
    ("amount", "unit", "mm", "approximate"),
    [
        (5, "cm", 50, False),
        (2, "inches", 50.8, False),
        (1, "Inch", 25.4, False),
        (0.5, "ft", 152.4, False),
        (40, "mm", 40, False),
        (1, "golf ball", 43, True),
        (2, "fingers deep", 40, True),
        (0.5, "a brick", 32.5, True),
    ],
)
def test_convert_to_mm(amount, unit, mm, approximate):
    result = tools.convert_to_mm(amount, unit)
    assert result["mm"] == mm
    assert result["approximate"] is approximate


def test_convert_to_mm_unknown_unit_is_an_error_for_the_model():
    assert "Unknown unit" in tools.call_tool("convert_to_mm", {"amount": 3, "unit": "smoots"})["error"]


def test_trees_route_to_the_tree_form():
    result = tools.route_report("tree", "Derbyshire Lane")
    assert result["can_file"] is True and "tree steps" in result["next_step"]
    assert tools.route_report("tree", "M1 junction 34")["owner"] == "National Highways"


@pytest.mark.parametrize(("where", "problem"), [("Park", None), ("Housing", None), ("Private", None),
                                                 ("Highway", "Utility"), ("Highway", "Nuisance")])
def test_assess_tree_redirects_what_the_form_cannot_take(where, problem):
    result = tools.assess_tree(where, problem)
    assert result["can_file"] is False and result["redirect"]


def test_assess_tree_needs_blocking_for_blocking_problems_and_flags_urgent_ones():
    assert "blocking" in tools.call_tool("assess_tree", {"tree_location": "Highway", "problem": "Obstruction"})["error"]
    assert "urgent_advice" in tools.assess_tree("Highway", "Fallen", blocking=False)
    assert "urgent_advice" not in tools.assess_tree("Highway", "Roots")


def test_file_tree_report_records_the_form_fields(reports_path):
    result = tools.file_tree_report("Highway", "Dangerous", "12 Derbyshire Lane", "Split trunk, leaning", blocking=True)
    assert result["reference"].startswith("SCC-") and "urgent_advice" in result
    record = json.loads(reports_path.read_text().splitlines()[-1])
    assert record["form"] == "report_tree"
    assert record["form_payload"]["rad_tree_blocking"] == "Yes"


def test_file_tree_report_refuses_redirected_trees():
    assert "can't be filed" in tools.call_tool("file_tree_report", {
        "tree_location": "Highway", "problem": "Nuisance", "location": "x", "description": "y"})["error"]


def test_filing_tools_record_the_map_point(reports_path):
    tools.file_report("road", "Greater than 40mm", "Fargate", "Deep pothole", lat=53.3811, lon=-1.4701)
    tools.file_tree_report("Highway", "Roots", "Derbyshire Lane", "Roots lifting slabs", lat=53.346, lon=-1.479)
    pothole, tree = (json.loads(line)["form_payload"] for line in reports_path.read_text().splitlines())
    assert (pothole["le_gis_lat"], pothole["le_gis_lon"]) == ("53.381100", "-1.470100")
    assert tree["le_gis_lat"] == "53.346000"


def test_map_point_is_optional_but_must_be_complete_and_valid(reports_path):
    tools.file_report("road", "Less than 40mm", "Fargate", "Small pothole")
    assert "le_gis_lat" not in json.loads(reports_path.read_text())["form_payload"]
    assert "both" in tools.call_tool("file_report", {"surface": "road", "depth_band": "Less than 40mm",
                                                     "location": "x", "description": "y", "lat": 53.4})["error"]
    assert "error" in tools.call_tool("nearest_address", {"lat": 200, "lon": 0})


def test_nearest_address_reads_photon(monkeypatch):
    class Response:
        def raise_for_status(self):
            return self

        def json(self):
            return {"features": [{"properties": {"housenumber": "12", "street": "Derbyshire Lane",
                                                 "city": "Sheffield", "postcode": "S8 9EH"}}]}

    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: Response())
    assert tools.nearest_address(53.346, -1.479)["address"] == "12 Derbyshire Lane, Sheffield, S8 9EH"


def test_nearest_address_failure_is_an_error_for_the_model(monkeypatch):
    def offline(*a, **k):
        raise tools.httpx.ConnectError("offline")
    monkeypatch.setattr(tools.httpx, "get", offline)
    assert "unavailable" in tools.nearest_address(53.346, -1.479)["error"]
