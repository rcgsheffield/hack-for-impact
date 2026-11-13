"""Browser-free checks for the shared form helpers."""

import json

from app.council_form import unverified_references
from app.pothole_form_toolkit import PotholeFormSession
from app.tree_form_toolkit import TreeFormSession


def test_flags_reference_the_model_made_up():
    results = [json.dumps({"page": "page_review"})]
    assert unverified_references("Your reference number is TRE-789234.", results) == ["TRE-789234"]


def test_accepts_reference_returned_by_submit():
    results = [json.dumps({"page": "page_complete", "reference": "989144199"}), "not json"]
    assert unverified_references("Reference number: 989144199", results) == []


def test_next_step_hints_name_each_forms_tools():
    pothole, tree = PotholeFormSession(), TreeFormSession()
    try:
        assert "set_pothole_location" in pothole.next_step("page_about_the_location")
        assert "submit_tree_form" in tree.next_step("page_review")
        assert "Private" in tree.next_step("page_about_the_problem")
    finally:
        pothole.close()
        tree.close()
