"""Triage rubrics: each service's triage as data, a small decision tree of typed questions (nodes).

A Node is one question with a fixed set of options (a typed choice, at most MAX_OPTIONS, the System One limit). Every
option has a fixed Outcome: points, a reason for staff, whether it is an immediate hazard (only hazards can make P1)
and whether it means the problem is not the council's (redirect). Deciders (triage_deciders.py) only pick options;
they never choose points, so the priority stays explainable and testable whoever answers.

Axes follow the risk-based approach of the UK Code of Practice "Well-managed Highway Infrastructure" (UKRLG, 2016),
risk = impact x likelihood:
- routing:  is it the council's job? A redirect gives P4 unless a hazard makes it P1.
- severity: what the defect is (impact). hazard=True is Sheffield's Category 1 test, "immediate safety risk".
- exposure: who meets it and how often (likelihood): vulnerable users, cyclists, traffic, blocking, repeats.

Weights and sources are documented in docs/triage.md ("Criteria basis"); they are the same as triage v1, so the
labelled set gives the same results. To add a service: write its nodes, add a Rubric to RUBRICS, run validate() (the
tests do) and the eval (python -m app.triage_eval).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

MAX_OPTIONS = 255  # System One choice questions take at most 255 options (docs.typesafe.ai, ChoiceQuestion)
NONE = "none"      # default option name for "nothing reported"

Axis = Literal["routing", "severity", "exposure"]


@dataclass(frozen=True)
class Outcome:
    points: int = 0
    reason: str = ""          # shown to staff; empty = no reason line
    hazard: bool = False      # immediate risk: may make the report P1
    redirect: bool = False    # not the council's job: P4 unless a hazard
    description: str = ""     # when this option applies, for model deciders (prompt / System One criteria)


@dataclass(frozen=True)
class Node:
    id: str
    question: str
    axis: Axis
    options: dict[str, Outcome]
    default: str = NONE                                       # the "nothing found" option; models may fill it in
    from_fields: Callable[[dict], str | None] | None = None   # form fields -> option (None: form doesn't say)
    keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)  # option -> regexes in the resident's words
    model: bool = True                                        # may a model decider answer it?
    when: Callable[[dict[str, str]], bool] | None = None      # tree edge: ask only if earlier answers allow it

    def outcome(self, option: str) -> Outcome:
        return self.options[option]


@dataclass(frozen=True)
class Rubric:
    form: str
    title: str
    nodes: tuple[Node, ...]

    def model_nodes(self) -> list[Node]:
        return [n for n in self.nodes if n.model]

    def node(self, node_id: str) -> Node:
        return next(n for n in self.nodes if n.id == node_id)


def _flag(node_id: str, question: str, axis: Axis, points: int, reason: str, description: str,
          patterns: tuple[str, ...], hazard: bool = False) -> Node:
    """A yes/no node: 'none' or 'yes', answered by keywords and (optionally) a model."""
    return Node(node_id, question, axis, {
        NONE: Outcome(description="Not mentioned, or the text does not say so"),
        "yes": Outcome(points, reason, hazard=hazard, description=description),
    }, keywords={"yes": patterns})


# ---------------------------------------------------------------------------------------------------------------
# Shared text nodes: the resident's own words. Same points, reasons and patterns as triage v1's KEYWORD_RULES, in the
# same order (reason order on the dashboard follows node order).
# ---------------------------------------------------------------------------------------------------------------
INJURY = _flag("injury", "Does the text say a person or animal was actually hurt, fell, or came off a bike?",
               "severity", 30, "Someone has been hurt",
               "Someone was actually hurt, fell, tripped or came off a bike or motorbike because of it", (
                   # "fell over" alone is left out: "the tree fell over" is not an injury.
                   r"\b(fell|fallen|came|come|knocked) off\b", r"\bknocked (over|down)\b",
                   r"\bfell (on|in|into) (it|the)\b", r"\bhad a fall\b", r"\btripped\b", r"\bhurt\b", r"\binjur",
                   r"\bambulance\b", r"\bA ?& ?E\b", r"\bbroke (his|her|their|my|a) \w+", r"\bsprained\b",
                   r"\bbleeding\b"), hazard=True)
WIRES_GAS = _flag("wires_gas", "Does the text report exposed electrical wires or a gas leak?",
                  "severity", 40, "Exposed wires or gas",
                  "Exposed, bare or live electrical wires or cables, sparking, or a smell or leak of gas", (
                      r"\b(exposed|live|bare|hanging) (electric(al)? )?(wires?|cables?)\b", r"\bgas (leak|smell)\b",
                      r"\bsmell(s|ing)? (of )?gas\b", r"\bsparking\b"), hazard=True)
BLOCKING = _flag("blocking", "Does the problem block or narrow a road, lane, pavement or path?",
                 "exposure", 20, "Blocking the road or pavement",
                 "It blocks or narrows a road, lane, pavement or path so people must go round it", (
                     # Not "across the road": a crack can run across a road without blocking it.
                     (r"\bblock(s|ing|ed)? (the |half the |most of the )?"
                      r"(road|pavement|footpath|path|lane|carriageway)\b"),))
SHARPS = _flag("sharps", "Does the text mention needles, sharps or asbestos?",
               "severity", 20, "Needles, sharps or asbestos",
               "Needles, syringes, sharps or asbestos are present",
               (r"\bneedles?\b", r"\bsyringes?\b", r"\bsharps\b", r"\basbestos\b"))
REPORTED_BEFORE = _flag("reported_before", "Does the resident say it was reported before and is still not fixed?",
                        "exposure", 20, "Reported before",
                        "The resident says they or others reported it before, or it is still not fixed", (
                            r"\brepeatedly reported\b", r"\breported (it |this )?(before|again|several times|many times)\b",
                            r"\bstill not (been )?fixed\b"))
VULNERABLE = _flag("vulnerable", "Does the text say children, elderly or disabled people are affected?",
                   "exposure", 15, "Affects children or disabled people",
                   "Children, a school, elderly people, wheelchair or mobility scooter users, blind or partially "
                   "sighted people, or pushchairs are affected", (
                       r"\bchild(ren)?\b", r"\bkids?\b", r"\bschool\b", r"\bwheelchairs?\b", r"\bmobility scooter",
                       r"\bblind\b", r"\bpartially sighted\b", r"\bpushchairs?\b", r"\bprams?\b", r"\bbuggy\b",
                       r"\belderly\b", r"\bwalking stick\b"))
CYCLISTS = _flag("cyclists", "Does the text say cyclists or motorcyclists are at risk?",
                 "exposure", 15, "Risk to cyclists or motorcyclists",
                 "Cyclists or motorcyclists use the spot or are at risk", (
                     r"\bcycl(ist|ists|ing|e lane)\b", r"\bbikes?\b", r"\bmotorbikes?\b", r"\bmotorcycl"))
TRAFFIC = _flag("traffic", "Is it on a busy or main road, bus route or junction, or are vehicles swerving?",
                "exposure", 15, "Busy road, bus route or traffic swerving",
                "A busy or main road, bus route or stop, junction or roundabout, or vehicles swerving round it", (
                    r"\bbusy (road|junction|street)\b", r"\bmain road\b", r"\bbus (route|stop)\b", r"\bswerv",
                    r"\broundabout\b"))
FLOODING = _flag("flooding", "Does the text mention flooding or standing water?",
                 "severity", 15, "Flooding", "Flooding or standing water",
                 (r"\bflood", r"\bstanding water\b"))

TEXT_NODES = (INJURY, WIRES_GAS, BLOCKING, SHARPS, REPORTED_BEFORE, VULNERABLE, CYCLISTS, TRAFFIC, FLOODING)


# ---------------------------------------------------------------------------------------------------------------
# Potholes and road/pavement defects (src/mock/report_pothole_crack.html). Category 1 = deeper than the form's
# threshold: 40mm on a road, 20mm on a pavement (docs/sheffield-council-services.md).
# ---------------------------------------------------------------------------------------------------------------
DEEP_DEFECT_POINTS = 45  # 30 + 45 = 75: P1 on its own

def _defect_depth(fields: dict) -> str | None:
    if not fields:
        return None  # the form says nothing: leave it to the text
    surface = "pavement" if "Pavement" in str(fields.get("rad_problem_location", "")) else "road"
    band = str(fields.get("rad_road_pothole_depth") or fields.get("rad_path_pothole_depth") or "")
    if band.startswith("Greater than"):
        return f"{surface}_deep"
    return "shallow" if band else "unknown"


DEFECT_DEPTH = Node("defect_depth", "How deep is the pothole or defect?", "severity", {
    "unknown": Outcome(reason="Depth not given: needs review", description="The depth is not given"),
    "shallow": Outcome(description="Shallower than 40mm on a road or 20mm on a pavement (a crack, small hole)"),
    "road_deep": Outcome(DEEP_DEFECT_POINTS, "Road pothole deeper than 40mm", hazard=True,
                         description="A pothole in the road deeper than 40mm (about 1.5 inches, a deep hole)"),
    "pavement_deep": Outcome(DEEP_DEFECT_POINTS, "Pavement pothole deeper than 20mm", hazard=True,
                             description="A hole or lifted slab in the pavement deeper than 20mm"),
}, default="unknown", from_fields=_defect_depth)

POTHOLE = Rubric("report_pothole_crack", "Pothole or road/pavement defect", (DEFECT_DEPTH, *TEXT_NODES))


# ---------------------------------------------------------------------------------------------------------------
# Street trees (src/mock/report_tree.html). The form says to phone for fallen trees, and redirects park, housing,
# private, utility (cables) and nuisance problems.
# ---------------------------------------------------------------------------------------------------------------
REDIRECT_TREE_LOCATIONS = {"park", "housing", "private"}

def _tree_location(fields: dict) -> str | None:
    loc = str(fields.get("rad_tree_location") or "").lower()
    return loc if loc in TREE_LOCATION.options else (None if not loc else "highway")


TREE_LOCATION = Node("tree_location", "Where is the tree?", "routing", {
    "highway": Outcome(description="On or beside a public road or pavement"),
    "park": Outcome(redirect=True, description="In a park, woodland or green space (Parks and Countryside)"),
    "housing": Outcome(redirect=True, description="On council housing land"),
    "private": Outcome(redirect=True, description="On private land or a garden"),
    "unknown": Outcome(description="The text does not say where the tree is"),
}, default="unknown", from_fields=lambda f: _tree_location(f) if f else None)

TREE_PROBLEM_FORM = {"Fallen": "fallen", "Utility": "utility", "Dangerous": "dangerous",
                     "Obstruction": "obstruction", "Roots": "roots", "Nuisance": "nuisance"}

def _tree_problem(fields: dict) -> str | None:
    if not fields:
        return None
    option = TREE_PROBLEM_FORM.get(str(fields.get("rad_tree_problem") or ""))
    if option is None:
        return NONE
    if fields.get("rad_tree_blocking") == "Yes" and f"{option}_blocking" in TREE_PROBLEM.options:
        return f"{option}_blocking"
    return option


TREE_PROBLEM = Node("tree_problem", "What is wrong with the tree?", "severity", {
    NONE: Outcome(description="The text does not say"),
    "fallen": Outcome(50, "Tree or branch has fallen", hazard=True, description="A tree or branch has fallen"),
    "utility": Outcome(50, "Tree touching phone or power cables", hazard=True, redirect=True,
                       description="The tree is touching phone or power cables"),
    "dangerous_blocking": Outcome(50, "Dangerous tree blocking the road or pavement", hazard=True,
                                  description="A leaning, split or dead tree that is already blocking the way"),
    "dangerous": Outcome(25, "Tree may be dangerous (leaning, split or dead)",
                         description="Leaning, split, cracked or dead, but not blocking the way"),
    "obstruction_blocking": Outcome(25, "Tree blocking the road or pavement",
                                    description="Branches or growth blocking a road or pavement"),
    "obstruction": Outcome(description="Branches covering a sign or light, not blocking the way"),
    "roots": Outcome(description="Roots lifting the pavement or road"),
    "nuisance": Outcome(redirect=True, description="Sap, leaves, birds, shade or blocking a view: a nuisance only"),
}, from_fields=_tree_problem,
    # The form redirects park, housing and private trees before asking the problem; so does the tree.
    when=lambda a: a.get("tree_location") not in REDIRECT_TREE_LOCATIONS)

TREE = Rubric("report_tree", "Street tree", (TREE_LOCATION, TREE_PROBLEM, *TEXT_NODES))

# Any other form (fly-tipping, street lights, ...) until it has its own rubric: the resident's words only.
GENERIC = Rubric("generic", "Other problem", TEXT_NODES)

RUBRICS = {r.form: r for r in (POTHOLE, TREE)}


def rubric_for(form: str | None) -> Rubric:
    return RUBRICS.get(str(form or ""), GENERIC)


def validate(rubric: Rubric) -> None:
    """Raise ValueError if the rubric is malformed. Checked by the tests for every rubric."""
    ids = [n.id for n in rubric.nodes]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{rubric.form}: duplicate node ids")
    for n in rubric.nodes:
        if not 2 <= len(n.options) <= MAX_OPTIONS:
            raise ValueError(f"{rubric.form}.{n.id}: needs 2..{MAX_OPTIONS} options")
        if n.default not in n.options:
            raise ValueError(f"{rubric.form}.{n.id}: default {n.default!r} is not an option")
        if n.options[n.default].points or n.options[n.default].hazard:
            raise ValueError(f"{rubric.form}.{n.id}: the default option must score nothing")
        for option, patterns in n.keywords.items():
            if option not in n.options:
                raise ValueError(f"{rubric.form}.{n.id}: keyword option {option!r} is not an option")
            for p in patterns:
                re.compile(p)
        for option, o in n.options.items():
            if n.model and not o.description:
                raise ValueError(f"{rubric.form}.{n.id}.{option}: model nodes need a description per option")
