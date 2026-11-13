"""Drives the mock tree form through the LangChain tools, with no model involved.

Needs a browser: `uv run playwright install chromium`, or FORM_BROWSER_CHANNEL=chrome. Skipped when none is available.
"""

import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from app.tree_form_toolkit import FormStepError, TreeFormSession, TreeFormToolkit  # noqa: E402


@pytest.fixture(scope="module")
def session():
    channels = [os.environ.get("FORM_BROWSER_CHANNEL") or os.environ.get("POTHOLE_FORM_BROWSER_CHANNEL") or None,
                "chrome", "msedge"]
    for channel in dict.fromkeys(channels):
        s = TreeFormSession(headless=True, channel=channel)
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
    return {t.name: t for t in TreeFormToolkit(session=session).get_tools()}


def call(tools, name, **args):
    return json.loads(tools[name].invoke(args))


def test_completes_and_submits_form(tools):
    assert call(tools, "start_tree_form")["page"] == "page_about_the_problem"

    problem = call(tools, "set_tree_problem", tree_location="Highway", problem="Fallen", blocking=True)
    assert problem["page"] == "page_about_the_location"
    assert problem["can_file"] is True
    assert "0114 273 4567" in problem["urgent_advice"]

    location = call(tools, "set_tree_location", location="Somewhere on Derbyshire Lane",
                    details="Branch across the pavement by the bus stop")
    assert location["page"] == "page_about_you"

    assert call(tools, "set_tree_reporter", anonymous=True)["page"] == "page_review"
    answers = call(tools, "review_tree_form")["answers"]
    assert answers["Where is the tree?"] == "On or next to a road or pavement"
    assert answers["Is it blocking the road or pavement now?"] == "Yes"

    result = call(tools, "submit_tree_form")
    assert result["page"] == "page_complete"
    fields = result["record"]["fields"]
    assert (fields["rad_tree_location"], fields["rad_tree_problem"], fields["rad_tree_blocking"]) == ("Highway", "Fallen", "Yes")
    assert result["record"]["form"] == "report_tree"
    # A fallen tree across the way is P1: the resident hears the priority and the phone advice.
    assert result["priority_plain"] == "Emergency: made safe within 24 hours"
    assert any("0114 273 4567" in advice for advice in result["tell_user"])


@pytest.mark.parametrize(
    ("args", "advice"),
    [
        ({"tree_location": "Park"}, "Parks and Countryside"),
        ({"tree_location": "Private"}, "owns the land"),
        ({"tree_location": "Highway", "problem": "Utility"}, "utility company"),
        ({"tree_location": "Highway", "problem": "Nuisance"}, "falling fruit"),
    ],
)
def test_redirects_when_form_cannot_take_report(tools, args, advice):
    call(tools, "start_tree_form")
    result = call(tools, "set_tree_problem", **args)
    assert result["can_file"] is False
    assert result["page"] == "page_about_the_problem"
    assert advice in result["redirect"]


def test_no_blocking_question_for_roots(tools):
    call(tools, "start_tree_form")
    result = call(tools, "set_tree_problem", tree_location="Highway", problem="Roots")
    assert result["page"] == "page_about_the_location"
    assert "urgent_advice" not in result


def test_missing_answers_return_errors(tools):
    call(tools, "start_tree_form")
    assert "blocking" in call(tools, "set_tree_problem", tree_location="Highway", problem="Dangerous")["error"]
    assert "problem" in call(tools, "set_tree_problem", tree_location="Highway")["error"]
    assert "error" in call(tools, "set_tree_problem", tree_location="Moon")
