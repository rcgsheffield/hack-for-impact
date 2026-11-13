"""The triage rules engine (src/app/triage.py): every rule, its reason text and the boundaries."""

import pytest

from app import triage as t
from app.triage import safe_triage, triage


def pothole(surface="Road Surface", band="Less than 40mm", details=""):
    field = "rad_road_pothole_depth" if surface == "Road Surface" else "rad_path_pothole_depth"
    return {"form": "report_pothole_crack", "fields": {"rad_problem_location": surface, field: band}, "details": details}


def tree(location="Highway", problem=None, blocking=None, details=""):
    fields = {"rad_tree_location": location}
    if problem:
        fields["rad_tree_problem"] = problem
    if blocking is not None:
        fields["rad_tree_blocking"] = "Yes" if blocking else "No"
    return {"form": "report_tree", "fields": fields, "details": details}


def test_result_shape():
    r = triage(pothole(band="Greater than 40mm"))
    assert r == {"priority": "P1", "label": "Emergency", "score": 75, "reasons": ["Road pothole deeper than 40mm"],
                 "response_target": "Made safe within 24 hours", "engine": "rules", "version": 1}


@pytest.mark.parametrize("surface, band, priority, reason", [
    ("Road Surface", "Greater than 40mm", "P1", "Road pothole deeper than 40mm"),
    ("Pavement Surface", "Greater than 20mm", "P1", "Pavement pothole deeper than 20mm"),
    ("Road Surface", "Less than 40mm", "P3", t.NO_RISK_REASON),       # exactly 40mm is "Less than 40mm" on the form
    ("Pavement Surface", "Less than 20mm", "P3", t.NO_RISK_REASON),
])
def test_depth_rules(surface, band, priority, reason):
    r = triage(pothole(surface, band))
    assert (r["priority"], r["reasons"]) == (priority, [reason])


def test_missing_depth_asks_for_review():
    r = triage({"form": "report_pothole_crack", "fields": {"rad_problem_location": "Road Surface"}})
    assert (r["priority"], r["reasons"]) == ("P3", ["Depth not given: needs review"])


@pytest.mark.parametrize("problem, blocking, priority, reason", [
    ("Fallen", True, "P1", "Tree or branch has fallen"),
    ("Fallen", False, "P1", "Tree or branch has fallen"),
    ("Dangerous", True, "P1", "Dangerous tree blocking the road or pavement"),
    ("Dangerous", False, "P2", "Tree may be dangerous (leaning, split or dead)"),
    ("Obstruction", True, "P2", "Tree blocking the road or pavement"),
    ("Obstruction", False, "P3", t.NO_RISK_REASON),
    ("Roots", None, "P3", t.NO_RISK_REASON),
    ("Other", None, "P3", t.NO_RISK_REASON),
    ("Nuisance", None, "P4", t.REDIRECT_REASON),
])
def test_tree_rules(problem, blocking, priority, reason):
    r = triage(tree("Highway", problem, blocking))
    assert r["priority"] == priority
    assert r["reasons"] == [reason]


def test_tree_touching_cables_stays_p1_although_the_form_redirects_it():
    r = triage(tree("Highway", "Utility"))
    assert (r["priority"], r["reasons"]) == ("P1", ["Tree touching phone or power cables"])


@pytest.mark.parametrize("location", ["Park", "Housing", "Private"])
def test_trees_off_the_highway_are_redirected(location):
    r = triage(tree(location, details="looks dead"))
    assert (r["priority"], r["reasons"]) == ("P4", [t.REDIRECT_REASON])


@pytest.mark.parametrize("words, reason", [
    ("a cyclist came off on it", "Someone has been hurt"),
    ("my mum tripped on it last night", "Someone has been hurt"),
    ("he was hurt", "Someone has been hurt"),
    ("exposed wires in the hole", "Exposed wires or gas"),
    ("there's a smell of gas", "Exposed wires or gas"),
    ("it's blocking the road", "Blocking the road or pavement"),
    ("needles by the kerb", "Needles, sharps or asbestos"),
    ("looks like asbestos sheets", "Needles, sharps or asbestos"),
    ("I've reported it before", "Reported before"),
    ("despite repeatedly reported by various people", "Reported before"),
    ("children walk past it to school", "Affects children or disabled people"),
    ("wheelchair users can't get past", "Affects children or disabled people"),
    ("a pushchair got stuck", "Affects children or disabled people"),
    ("dangerous for bikes", "Risk to cyclists or motorcyclists"),
    ("motorbikes swerve round it", "Risk to cyclists or motorcyclists"),
    ("on a busy road", "Busy road, bus route or traffic swerving"),
    ("flooding after rain", "Flooding"),
])
def test_keyword_rules_give_their_reason(words, reason):
    assert reason in triage(pothole(details=words))["reasons"]


@pytest.mark.parametrize("words", ["the tree fell over in the wind", "a small crack", ""])
def test_no_injury_without_a_person(words):
    assert "Someone has been hurt" not in triage(pothole(details=words))["reasons"]


def test_each_keyword_rule_gives_one_reason():
    r = triage(pothole(details="tripped and hurt, then fell off a bike, then a cyclist was injured"))
    assert r["reasons"].count("Someone has been hurt") == 1


def test_injury_on_a_shallow_pothole_with_a_cyclist_is_p1():
    r = triage(pothole(details="A cyclist came off on it"))
    assert r["priority"] == "P1"
    assert r["reasons"] == ["Someone has been hurt", "Risk to cyclists or motorcyclists"]


def test_depth_and_keywords_add_up_and_are_capped():
    r = triage(pothole(band="Greater than 40mm", details="cyclist fell off, exposed wires, kids, flooding, busy road"))
    assert r["score"] == t.MAX_SCORE
    assert r["reasons"][0] == "Road pothole deeper than 40mm"


def test_not_the_councils_job_is_p4_unless_already_an_emergency():
    shallow = {**pothole(), "can_file": False}
    deep = {**pothole(band="Greater than 40mm"), "can_file": False}
    assert (triage(shallow)["priority"], triage(shallow)["reasons"][-1]) == ("P4", t.REDIRECT_REASON)
    assert triage(deep)["priority"] == "P1"
    assert t.REDIRECT_REASON not in triage(deep)["reasons"]


def test_browser_submission_with_no_details_needs_review():
    r = triage({"form": "report_pothole_crack", "details": "", "raw": {"event": "submit"}})
    assert (r["priority"], r["reasons"]) == ("P3", [t.FEW_DETAILS_REASON])


def test_reads_fields_from_a_submission_item():
    item = {"form": "report_tree", "details": "", "raw": {"fields": {"rad_tree_location": "Highway",
                                                                     "rad_tree_problem": "Fallen"}}}
    assert triage(item)["priority"] == "P1"
    item = {"form": "report_pothole_crack", "details": "",
            "raw": {"form_payload": {"rad_problem_location": "Road Surface", "rad_road_pothole_depth": "Greater than 40mm"}}}
    assert triage(item)["priority"] == "P1"


def test_details_fall_back_to_the_form_field():
    item = pothole()
    item["fields"]["txta_details_about_the_location"] = "my son tripped"
    del item["details"]
    assert "Someone has been hurt" in triage(item)["reasons"]


def test_signals_add_reasons_and_points_but_rules_still_decide():
    signals = {"engine": "llm", "reasons": [{"points": 30, "reason": "Resident says a car swerved into oncoming traffic"}]}
    r = triage(pothole(), signals)
    assert r["engine"] == "rules+llm"
    assert r["reasons"] == ["Resident says a car swerved into oncoming traffic"]
    assert r["priority"] == "P2"


def test_empty_signals_leave_the_engine_as_rules():
    assert triage(pothole(), {"engine": "llm", "reasons": []})["engine"] == "rules"


def test_safe_triage_falls_back_instead_of_raising(monkeypatch):
    def boom(item, signals=None):
        raise RuntimeError("bug")
    monkeypatch.setattr(t, "triage", boom)
    r = safe_triage(pothole())
    assert (r["priority"], r["reasons"], r["engine"]) == ("P3", [t.FAILED_REASON], "fallback")


def test_by_priority_counts_every_level():
    items = [{"triage": {"priority": "P1"}}, {"triage": {"priority": "P1"}}, {"triage": {"priority": "P4"}}, {}]
    assert t.by_priority(items) == {"P1": 2, "P2": 0, "P3": 0, "P4": 1}


def test_combine_signals_joins_engines_and_reasons():
    from app.triage import combine_signals, triage
    llm = {"engine": "llm", "reasons": [{"points": 30, "reason": "A cyclist came off"}]}
    ctx = {"engine": "context", "reasons": [{"points": 15, "reason": "Primary road"}]}
    assert combine_signals(None, {"engine": "context", "reasons": []}) is None
    merged = combine_signals(llm, None, ctx)
    assert merged["engine"] == "llm+context"
    result = triage({"form": "report_pothole_crack", "details": ""}, merged)
    assert result["engine"] == "rules+llm+context"
    assert result["reasons"][:2] == ["A cyclist came off", "Primary road"]
