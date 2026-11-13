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
