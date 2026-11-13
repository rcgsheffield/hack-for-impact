"""Fixes from a live chat on the Spark (13 Nov 2026): a fallen tree on a named street, no browser installed,
the model calling set_tree_problem before start_tree_form, and asking "which category?" again and again."""

import json
import os

import pytest

from app import tools
from app.council_form import FORM_UNAVAILABLE
from app.tree_form_toolkit import FormStepError, TreeFormSession, TreeFormToolkit


@pytest.mark.parametrize("words", ["tree has fallen on summerfield street", "a branch came down", "it's blocking the road",
                                   "tree is leaning and looks dangerous"])
def test_route_report_gives_urgent_tree_advice_first(words):
    result = tools.route_report("tree", "Summerfield Street", words)
    assert "0114 273 4567" in result["urgent_advice"]
    assert result["tell_user"] == [result["urgent_advice"]]
    assert result["next_step"].startswith("First tell the user")


@pytest.mark.parametrize("words", ["roots lifting the pavement", "tree down the road drops sap on my car", ""])
def test_route_report_no_urgent_advice_for_routine_tree_problems(words):
    result = tools.route_report("tree", "Summerfield Street", words)
    assert "urgent_advice" not in result
    assert "Highway" in result["next_step"]


def test_route_report_description_is_optional():
    assert tools.route_report("pothole", "Fargate")["can_file"] is True


def test_missing_browser_gives_plain_message_not_technical_detail():
    s = TreeFormSession(headless=True, channel="no-such-browser-channel")
    try:
        result = json.loads({t.name: t for t in TreeFormToolkit(session=s).get_tools()}["start_tree_form"].invoke({}))
    finally:
        s.close()
    assert result["error"] == FORM_UNAVAILABLE
    for leak in ("playwright", "chromium", "install", "Error:"):
        assert leak.lower() not in result["error"].lower()


@pytest.fixture
def fresh_session():
    pytest.importorskip("playwright.sync_api")
    channels = [os.environ.get("FORM_BROWSER_CHANNEL") or None, "chrome", "msedge"]
    for channel in dict.fromkeys(channels):
        s = TreeFormSession(headless=True, channel=channel)
        try:
            s._run(s._ensure_page)  # browser only; the form is deliberately not started
        except FormStepError:
            s.close()
            continue
        yield s
        s.close()
        return
    pytest.skip("No browser available for Playwright")


def test_problem_step_opens_the_form_if_start_was_skipped(fresh_session):
    by_name = {t.name: t for t in TreeFormToolkit(session=fresh_session).get_tools()}
    result = json.loads(by_name["set_tree_problem"].invoke({"tree_location": "Highway", "problem": "Fallen", "blocking": True}))
    assert result["page"] == "page_about_the_location"
    assert result["can_file"] is True
