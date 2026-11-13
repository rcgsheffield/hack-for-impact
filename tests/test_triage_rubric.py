"""Triage rubrics (src/app/triage_rubric.py) and the decision trace (triage.explain)."""

import pytest

from app import triage_rubric as r
from app.triage import HAZARD_REASONS, combine_signals, explain, triage


@pytest.mark.parametrize("rubric", [*r.RUBRICS.values(), r.GENERIC], ids=lambda x: x.form)
def test_every_rubric_is_valid(rubric):
    r.validate(rubric)


def test_validate_rejects_a_scoring_default():
    bad = r.Node("x", "?", "severity", {"none": r.Outcome(5, "oops", description="d"), "yes": r.Outcome(description="d")})
    with pytest.raises(ValueError, match="default"):
        r.validate(r.Rubric("bad", "Bad", (bad,)))


def test_validate_rejects_too_many_options():
    opts = {f"o{i}": r.Outcome(description="d") for i in range(r.MAX_OPTIONS + 1)} | {"none": r.Outcome(description="d")}
    with pytest.raises(ValueError, match="options"):
        r.validate(r.Rubric("big", "Big", (r.Node("x", "?", "severity", opts),)))


def test_unknown_forms_use_the_shared_text_questions():
    assert r.rubric_for("report_fly_tipping") is r.GENERIC
    assert explain({"form": "report_fly_tipping", "details": "needles everywhere"})["rubric"] == "generic"


def test_hazard_reasons_come_from_the_rubric():
    assert {"Someone has been hurt", "Exposed wires or gas", "Tree or branch has fallen",
            "Road pothole deeper than 40mm"} <= HAZARD_REASONS


def test_trace_names_who_answered():
    item = {"form": "report_pothole_crack", "details": "a cyclist came off on it",
            "fields": {"rad_problem_location": "Road Surface", "rad_road_pothole_depth": "Less than 40mm"}}
    t = explain(item)
    assert t["decisions"] == [{"node": "defect_depth", "option": "shallow", "p": 1.0, "source": "form"},
                              {"node": "injury", "option": "yes", "p": 1.0, "source": "keyword"},
                              {"node": "cyclists", "option": "yes", "p": 1.0, "source": "keyword"}]
    assert {k: v for k, v in t.items() if k not in ("rubric", "decisions")} == triage(item)


def test_tree_edge_skips_the_problem_for_park_trees():
    """The form redirects park trees before asking the problem, so a model's 'fallen' reading is never asked for."""
    model = {"engine": "llm", "decisions": {"tree_problem": {"option": "fallen", "p": 0.95}}}
    park = {"form": "report_tree", "fields": {"rad_tree_location": "Park"}, "details": "big tree down"}
    street = {"form": "report_tree", "fields": {"rad_tree_location": "Highway"}, "details": "big tree down"}
    assert triage(park, combine_signals(model))["priority"] == "P4"
    assert triage(street, combine_signals(model))["priority"] == "P1"


def test_split_probabilities_flag_a_hazard_for_review():
    """A System One answer of 'none' that still puts 35% on a hazard is shown to staff, with no points."""
    jev = {"engine": "jev", "decisions": {"injury": {"option": "none", "p": 0.65, "probs": {"none": 0.65, "yes": 0.35}}}}
    item = {"form": "report_pothole_crack", "details": "she went down on it"}
    t = triage(item, combine_signals(jev))
    assert t["score"] == triage(item)["score"] and t["engine"] == "rules+jev"
    assert "Possible: Someone has been hurt (read by Jev, 35%): needs review" in t["reasons"]


def test_first_model_wins_when_two_answer_the_same_node():
    llm = {"engine": "llm", "decisions": {"blocking": {"option": "yes", "p": 0.9}}}
    jev = {"engine": "jev", "decisions": {"blocking": {"option": "none", "p": 0.9}}}
    merged = combine_signals(llm, jev)
    assert merged["decisions"]["blocking"]["source"] == "llm" and merged["engine"] == "llm+jev"
    t = triage({"form": "report_pothole_crack", "details": "x"}, merged)
    assert t["engine"] == "rules+llm" and "Blocking the road or pavement (read by local AI)" in t["reasons"]
