"""Automatic triage: a priority (P1-P4), plain-English reasons and a response target for any report.

Deterministic rules decide the priority. Optional `signals` (from a local LLM, #26, or map context, #27) can only add
points and reasons; they never set the priority directly.

Only an immediate hazard (HAZARD_REASONS, or a signal reason marked "hazard": true) can make a report P1, matching the
council's Category 1 ("immediate safety risk"). Without one, context and vulnerability add up to P2 at most
(NO_HAZARD_MAX_SCORE), so a shallow defect on a busy road near a school is High, not Emergency. The result is always a suggestion: the council sets the
category after inspection.

Sources (docs/sheffield-council-services.md, "Potholes and road/pavement defects"): Category 1 is an immediate safety
risk, made safe within 24 hours; Category 2 has no immediate risk and is fixed through planned maintenance. The council
prioritises "by size, depth, road usage, risk to drivers/cyclists/pedestrians". Depth thresholds are the council form's
own options (src/mock/report_pothole_crack.html). Tree rules follow the tree form (src/mock/report_tree.html), which
says not to use it for emergencies and redirects park, housing, private, utility and nuisance problems.

Input is a submission item as built by submissions.py (form, details, raw.fields / raw.form_payload) or a plain
{"form", "fields", "details"} dict built at filing time. Set item["can_file"] = False for reports the council
doesn't handle.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

VERSION = 1

# Priority -> (label, response target). P1 = Category 1, P3 = Category 2 (see module docstring).
PRIORITIES = {
    "P1": ("Emergency", "Made safe within 24 hours"),
    "P2": ("High", "Inspected within a few days"),
    "P3": ("Routine", "Fixed through planned maintenance"),
    "P4": ("Low", "Redirected or monitored"),
}
# Lowest score for each priority, checked in order; anything lower is P4.
BANDS = [("P1", 70), ("P2", 50), ("P3", 25)]

BASE_SCORE = 30          # any report the council can act on starts as routine (P3)
REDIRECT_SCORE = 10      # not the council's job: P4, unless a hazard already makes it P1
MAX_SCORE = 100

DEEP_DEFECT_POINTS = 45  # deeper than the form's threshold: Category 1 on its own (30 + 45 = 75, P1)
TREE_POINTS = {
    "Fallen": 50,               # tree or branch down: the form says phone instead
    "Utility": 50,              # touching phone or power cables
    "Dangerous_blocking": 50,   # leaning or split and already in the way
    "Dangerous": 25,            # likely to become dangerous: P2
    "Obstruction_blocking": 25,
}
TREE_REASONS = {
    "Fallen": "Tree or branch has fallen",
    "Utility": "Tree touching phone or power cables",
    "Dangerous_blocking": "Dangerous tree blocking the road or pavement",
    "Dangerous": "Tree may be dangerous (leaning, split or dead)",
    "Obstruction_blocking": "Tree blocking the road or pavement",
}
REDIRECT_TREE_LOCATIONS = {"Park", "Housing", "Private"}
REDIRECT_TREE_PROBLEMS = {"Nuisance"}

# Hazards in the resident's own words: (points, reason, patterns). Each gives at most one reason.
KEYWORD_RULES = [
    (30, "Someone has been hurt", [
        # "fell over" alone is left out: "the tree fell over" is not an injury.
        r"\b(fell|fallen|came|come|knocked) off\b", r"\bknocked (over|down)\b", r"\bfell (on|in|into) (it|the)\b",
        r"\bhad a fall\b", r"\btripped\b", r"\bhurt\b", r"\binjur", r"\bambulance\b",
        r"\bA ?& ?E\b", r"\bbroke (his|her|their|my|a) \w+", r"\bsprained\b", r"\bbleeding\b"]),
    (40, "Exposed wires or gas", [
        r"\b(exposed|live|bare|hanging) (electric(al)? )?(wires?|cables?)\b", r"\bgas (leak|smell)\b",
        r"\bsmell(s|ing)? (of )?gas\b", r"\bsparking\b"]),
    (20, "Blocking the road or pavement", [
        # Not "across the road": a crack can run across a road without blocking it.
        r"\bblock(s|ing|ed)? (the |half the |most of the )?(road|pavement|footpath|path|lane|carriageway)\b"]),
    (20, "Needles, sharps or asbestos", [r"\bneedles?\b", r"\bsyringes?\b", r"\bsharps\b", r"\basbestos\b"]),
    (20, "Reported before", [r"\brepeatedly reported\b", r"\breported (it |this )?(before|again|several times|many times)\b",
                             r"\bstill not (been )?fixed\b"]),
    (15, "Affects children or disabled people", [
        r"\bchild(ren)?\b", r"\bkids?\b", r"\bschool\b", r"\bwheelchairs?\b", r"\bmobility scooter", r"\bblind\b",
        r"\bpartially sighted\b", r"\bpushchairs?\b", r"\bprams?\b", r"\bbuggy\b", r"\belderly\b", r"\bwalking stick\b"]),
    (15, "Risk to cyclists or motorcyclists", [r"\bcycl(ist|ists|ing|e lane)\b", r"\bbikes?\b", r"\bmotorbikes?\b",
                                               r"\bmotorcycl"]),
    (15, "Busy road, bus route or traffic swerving", [r"\bbusy (road|junction|street)\b", r"\bmain road\b", r"\bbus (route|stop)\b",
                                           r"\bswerv", r"\broundabout\b"]),
    (15, "Flooding", [r"\bflood", r"\bstanding water\b"]),
]

# Findings that are an immediate risk on their own: the only ones that can make a report P1.
HAZARD_REASONS = {"Someone has been hurt", "Exposed wires or gas", "Tree or branch has fallen",
                  "Tree touching phone or power cables", "Dangerous tree blocking the road or pavement"}
DEEP_DEFECT_MARK = "deeper than"  # a defect deeper than the form's threshold is Category 1: a hazard
NO_HAZARD_MAX_SCORE = BANDS[0][1] - 1  # highest score without a hazard: top of P2

FEW_DETAILS_REASON = "Few details: needs review"
NO_RISK_REASON = "No immediate risk reported"
REDIRECT_REASON = "Not a council highway problem: redirected"
FAILED_REASON = "Triage failed: needs manual review"


def _fields(item: dict) -> dict:
    raw = item.get("raw") or {}
    return item.get("fields") or raw.get("fields") or raw.get("form_payload") or {}


def _priority(score: int) -> str:
    return next((p for p, low in BANDS if score >= low), "P4")


def _result(priority: str, score: int, reasons: list[str], engine: str) -> dict:
    label, target = PRIORITIES[priority]
    return {"priority": priority, "label": label, "score": score, "reasons": reasons,
            "response_target": target, "engine": engine, "version": VERSION}


def _defect_rules(fields: dict) -> list[tuple[int, str]]:
    """Pothole/crack: the form's depth option, deeper than 40mm (road) or 20mm (pavement) is Category 1."""
    surface = "Pavement" if "Pavement" in str(fields.get("rad_problem_location", "")) else "Road"
    band = str(fields.get("rad_road_pothole_depth") or fields.get("rad_path_pothole_depth") or "")
    if band.startswith("Greater than"):
        return [(DEEP_DEFECT_POINTS, f"{surface} pothole {DEEP_DEFECT_MARK} {band.removeprefix('Greater than ')}")]
    if not band:
        return [(0, "Depth not given: needs review")]
    return []


def _tree_rules(fields: dict) -> tuple[list[tuple[int, str]], bool]:
    """Returns (rules hit, redirected)."""
    problem = fields.get("rad_tree_problem") or ""
    blocking = fields.get("rad_tree_blocking") == "Yes"
    key = f"{problem}_blocking" if blocking and f"{problem}_blocking" in TREE_POINTS else problem
    hits = [(TREE_POINTS[key], TREE_REASONS[key])] if key in TREE_POINTS else []
    redirected = (fields.get("rad_tree_location") in REDIRECT_TREE_LOCATIONS or problem in REDIRECT_TREE_PROBLEMS
                  or problem == "Utility")  # the form sends cable problems to the utility company
    return hits, redirected


def _is_hazard(reason: str) -> bool:
    return reason in HAZARD_REASONS or f"pothole {DEEP_DEFECT_MARK} " in reason


def _keyword_rules(text: str) -> list[tuple[int, str]]:
    return [(points, reason) for points, reason, patterns in KEYWORD_RULES
            if any(re.search(p, text, re.IGNORECASE) for p in patterns)]


def triage(item: dict, signals: dict | None = None) -> dict:
    """Priority, reasons and response target for one report. Deterministic; raises only on a programming error."""
    fields = _fields(item)
    form = item.get("form") or ("report_tree" if "rad_tree_location" in fields else "report_pothole_crack")
    details = str(item.get("details") or fields.get("txta_details_about_the_location") or "")

    hits: list[tuple[int, str]] = []
    redirected = item.get("can_file") is False
    if form == "report_tree":
        if fields:
            tree_hits, tree_redirect = _tree_rules(fields)
            hits += tree_hits
            redirected = redirected or tree_redirect
    elif fields:
        hits += _defect_rules(fields)
    hits += _keyword_rules(details)

    engine = "rules"
    hazard = any(_is_hazard(r) for _, r in hits)
    extra = (signals or {}).get("reasons") or []
    replaced = {str(s["replaces"]) for s in extra if s.get("replaces")}  # e.g. a counted cluster replaces "Reported before"
    hits = [h for h in hits if h[1] not in replaced]
    for s in extra:
        hits.append((int(s.get("points", 0)), str(s["reason"])))
        hazard = hazard or bool(s.get("hazard"))
    if extra:
        engine = "rules+" + str(signals.get("engine") or "signals")

    reasons = list(dict.fromkeys(r for _, r in hits))
    score = min(MAX_SCORE if hazard else NO_HAZARD_MAX_SCORE, BASE_SCORE + sum(p for p, _ in hits))
    if redirected and score < BANDS[0][1]:  # a P1 hazard stays P1 even if the form redirects it
        score = REDIRECT_SCORE
        reasons.append(REDIRECT_REASON)
    if not fields and not details.strip():
        reasons.append(FEW_DETAILS_REASON)
    if not reasons:
        reasons.append(NO_RISK_REASON)
    return _result(_priority(score), score, reasons, engine)


def combine_signals(*sources: dict | None) -> dict | None:
    """Merge signal dicts from several sources (LLM #26, map context #27) into one for triage().

    Each source is {"engine": "llm" | "context" | ..., "reasons": [{"points": int, "reason": str}, ...], ...}.
    Sources with no reasons are dropped; the engines are joined in order, e.g. "llm+context".
    """
    used = [s for s in sources if s and s.get("reasons")]
    if not used:
        return None
    return {"engine": "+".join(str(s.get("engine") or "signals") for s in used),
            "reasons": [r for s in used for r in s["reasons"]]}


def safe_triage(item: dict, signals: dict | None = None) -> dict:
    """triage(), but never raises: a failure gives a P3 that asks for manual review, so filing never stops."""
    try:
        return triage(item, signals)
    except Exception:
        log.exception("triage failed for %s", item.get("reference", "a report"))
        return _result("P3", BASE_SCORE, [FAILED_REASON], "fallback")


def by_priority(items: list[dict]) -> dict[str, int]:
    counts = dict.fromkeys(PRIORITIES, 0)
    for i in items:
        p = (i.get("triage") or {}).get("priority")
        if p in counts:
            counts[p] += 1
    return counts
