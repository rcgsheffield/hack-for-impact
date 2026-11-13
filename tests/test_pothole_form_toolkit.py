"""Drives the mock pothole form through the LangChain tools, with no model involved.

Needs a browser: `uv run playwright install chromium`, or POTHOLE_FORM_BROWSER_CHANNEL=chrome.
Skipped when neither is available. The location step may call the mock's live address lookups;
it still passes offline because the tools fall back to the location as typed.
"""

import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from app.pothole_form_toolkit import FormStepError, PotholeFormSession, PotholeFormToolkit  # noqa: E402


@pytest.fixture(scope="module")
def session():
    channels = [os.environ.get("POTHOLE_FORM_BROWSER_CHANNEL") or None, "chrome", "msedge"]
    for channel in dict.fromkeys(channels):
        s = PotholeFormSession(headless=True, channel=channel)
        try:
            s.start()
        except FormStepError:
            s.close()
            continue
        yield s
        s.close()
        return
    pytest.skip("No browser available for Playwright")


@pytest.fixture
def tools(session):
    return {t.name: t for t in PotholeFormToolkit(session=session).get_tools()}


def call(tools, name, **args):
    return json.loads(tools[name].invoke(args))


def test_completes_and_submits_form(tools):
    assert call(tools, "start_pothole_form")["page"] == "page_about_the_problem"

    problem = call(tools, "set_pothole_problem", surface="pavement", depth_mm=30)
    assert problem["page"] == "page_about_the_location"
    assert problem["depth_band"] == "Greater than 20mm"

    location = call(tools, "set_pothole_location", location="Somewhere off Fargate",
                    details="Lifted paving slab by the bench")
    assert location["page"] == "page_about_you"
    assert "as typed" in location["selected_address"]

    assert call(tools, "set_pothole_reporter", anonymous=True)["page"] == "page_review"
    answers = call(tools, "review_pothole_form")["answers"]
    assert answers["Where is the problem?"] == "Pavement or cycle path"
    assert answers["About you"] == "Submitted anonymously"

    result = call(tools, "submit_pothole_form")
    assert result["page"] == "page_complete"
    assert result["reference"].isdigit()
    fields = result["record"]["fields"]
    assert fields["rad_problem_location"] == "Pavement Surface"
    assert fields["rad_path_pothole_depth"] == "Greater than 20mm"
    assert fields["txt_full_address_about_the_location"] == "Somewhere off Fargate"
    assert result["record"]["submitted_to_council"] is False


def test_wrong_page_returns_error(tools):
    call(tools, "start_pothole_form")
    result = call(tools, "submit_pothole_form")
    assert "error" in result
    assert "About the problem" in result["error"]


def test_form_validation_errors_are_returned(tools):
    call(tools, "start_pothole_form")
    call(tools, "set_pothole_problem", surface="road", depth_mm=10)
    call(tools, "set_pothole_location", location="Ecclesall Road", details="Crack near the crossing")
    result = call(tools, "set_pothole_reporter", anonymous=False, title="Dr", first_name="Test", surname="User",
                  date_of_birth="01/01/1990", phone="0114 123 4567", email="not-an-email")
    assert result["page"] == "page_about_you"
    assert result["errors"] == ["Enter a valid email address"]


def test_bad_arguments_return_errors(tools):
    call(tools, "start_pothole_form")
    assert "error" in call(tools, "set_pothole_problem", surface="road", depth_mm=40, photo_path="missing.jpg")
    assert "error" in call(tools, "set_pothole_reporter", anonymous=False, date_of_birth="1990")
