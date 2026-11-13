"""Triage against the labelled cases in tests/data/triage_cases.jsonl (first cut of the evaluation set, #30).

Cases with must_pass true must match. Run with -s to see the confusion matrix and the misses.
"""

import json
from pathlib import Path

import pytest

from app.triage import PRIORITIES, triage

CASES = [json.loads(line) for line in (Path(__file__).parent / "data" / "triage_cases.jsonl").read_text().splitlines()
         if line.strip()]


@pytest.mark.parametrize("case", [c for c in CASES if c["must_pass"]], ids=lambda c: c["id"])
def test_must_pass_cases(case):
    got = triage(case)
    assert got["priority"] == case["expected"], f"{case['why']}; got {got['priority']} because {got['reasons']}"


def test_confusion_matrix():
    levels = list(PRIORITIES)
    matrix = {e: dict.fromkeys(levels, 0) for e in levels}
    misses = []
    for c in CASES:
        got = triage(c)["priority"]
        matrix[c["expected"]][got] += 1
        if got != c["expected"]:
            misses.append(f"  {c['id']}: expected {c['expected']}, got {got} ({c['why']})")
    agree = sum(matrix[p][p] for p in levels)
    under_p1 = sum(n for p, n in matrix["P1"].items() if p != "P1")
    print(f"\nTriage agreement {agree}/{len(CASES)}; P1 cases triaged lower: {under_p1}")
    print("expected \\ got  " + "  ".join(levels))
    for e in levels:
        print(f"{e:>14}   " + "  ".join(f"{matrix[e][g]:>2}" for g in levels))
    print("\n".join(misses))
    assert under_p1 == 0, "a P1 case was triaged lower: that is the error that matters for safety"
