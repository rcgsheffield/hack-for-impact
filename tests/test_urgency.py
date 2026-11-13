"""Pre-filing escalation and the plain-English priority given to residents (src/app/urgency.py)."""

import pytest

from app import urgency
from app.triage import triage


@pytest.mark.parametrize("text", [
    "A tree has fallen across the road on Ecclesall Road",
    "A big branch has come down across the pavement on Derbyshire Lane outside number 12",
    "Branch down on Derbyshire Lane",
    "Pothole on Abbeydale Road, my son came off his bike and is hurt",
])
def test_emergencies_are_p1_before_filing(text):
    assert urgency.is_urgent_text(text)
    assert urgency.URGENT_ADVICE in urgency.urgent_note(text)


@pytest.mark.parametrize("text", ["I fell over a tree root", "Pothole on Fargate, 5cm deep", "tree is leaning a bit", ""])
def test_routine_messages_are_not_escalated(text):
    assert not urgency.is_urgent_text(text)
    assert urgency.urgent_note(text) == ""


def test_fallen_tree_across_the_road_summary():
    t = triage({"form": "report_tree", "fields": {"rad_tree_location": "Highway", "rad_tree_problem": "Fallen",
                                                  "rad_tree_blocking": "Yes"}})
    s = urgency.summary(t)
    assert s["priority_plain"] == "Emergency: made safe within 24 hours"
    assert "0114 273 4567" in s["urgent_advice"] and "999" in s["urgent_advice"]
    assert "score" not in s and "engine" not in s


def test_routine_summary_has_no_urgent_advice():
    s = urgency.summary(triage({"form": "report_tree", "fields": {"rad_tree_location": "Highway", "rad_tree_problem": "Roots"}}))
    assert s["priority_plain"] == "Routine: fixed through planned maintenance"
    assert "urgent_advice" not in s


def test_ensure_advice_only_adds_when_missing():
    assert urgency.ensure_advice("Done.", False) == "Done."
    assert urgency.ensure_advice("Phone 0114 273 4567 now.", True) == "Phone 0114 273 4567 now."
    assert urgency.ensure_advice("Done.", True).endswith(urgency.URGENT_ADVICE)
