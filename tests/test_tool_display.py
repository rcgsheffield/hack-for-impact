"""Tool calls are shown to residents in plain English, with the raw JSON tucked away."""

from app.tool_display import describe


def test_known_tools_read_as_plain_english():
    title, body = describe("convert_to_mm", '{"amount": 2, "unit": "inches"}', {"mm": 50.8, "approximate": False})
    assert title == "📏 Converted the depth to millimetres"
    assert body.startswith("2 inches ≈ **50.8 mm**")


def test_raw_json_is_only_in_the_collapsed_details():
    _, body = describe("assess_pothole", {"surface": "road", "depth_mm": 50},
                       {"depth_band": "Greater than 40mm", "category_meaning": "Category 1", "note": "Suggestion only."})
    readable, technical = body.split("<details>")
    assert "{" not in readable and '"depth_band"' in technical


def test_filed_report_links_to_the_report_card_and_passes_on_urgent_advice():
    _, body = describe("file_tree_report", {"lat": 53.3, "lon": -1.4},
                       {"reference": "SCC-1", "url": "/reports/SCC-1", "status": "recorded", "urgent_advice": "Phone now"})
    assert "[View the report](/reports/SCC-1)" in body and "📍" in body and "🚨 Phone now" in body


def test_form_steps_and_review_table():
    title, _ = describe("start_pothole_form", "{}", {"heading": "About the problem"})
    assert title == "🖥️ Opened the council's pothole form"
    title, body = describe("review_tree_form", "{}", {"answers": {"Where is the tree?": "On a road"}})
    assert title.startswith("📋") and "| Where is the tree? | On a road |" in body


def test_errors_and_redirects():
    assert describe("set_tree_location", "{}", {"error": "Call the start tool first."})[0].startswith("⚠️")
    assert describe("set_tree_problem", {"tree_location": "Park"}, {"redirect": "Parks and Countryside"})[0].startswith("↪️")
    assert describe("some_new_tool", "not json", {"x": 1})[0] == "🔧 Some new tool"
