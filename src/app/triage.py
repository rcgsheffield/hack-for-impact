"""Automatic triage: a priority (P1-P4), plain-English reasons and a response target for any report.

Each service's triage is data: a rubric of typed questions (triage_rubric.py) with fixed points and reasons. Deciders
(triage_deciders.py) answer the questions: form fields first, then keyword rules on the resident's words, then a
model (the local LLM by default, #26; a System One model such as Jev optionally), which may only fill in what the
form and keywords left open. Map context (#27) adds reasons as signals. Nothing but the rubric chooses points, so
triage stays deterministic and testable, and works when no model is available.

Only an immediate hazard (an option marked hazard=True, or a signal reason marked "hazard": true) can make a report
P1, matching the council's Category 1 ("immediate safety risk"). Without one, context and vulnerability add up to P2
at most (NO_HAZARD_MAX_SCORE), so a shallow defect on a busy road near a school is High, not Emergency. The result is
always a suggestion: the council sets the category after inspection.

Sources (docs/sheffield-council-services.md, "Potholes and road/pavement defects"; docs/triage.md, "Criteria
basis"): Category 1 is an immediate safety risk, made safe within 24 hours; Category 2 has no immediate risk and is
fixed through planned maintenance. The council prioritises "by size, depth, road usage, risk to
drivers/cyclists/pedestrians".

Input is a submission item as built by submissions.py (form, details, raw.fields / raw.form_payload) or a plain
{"form", "fields", "details"} dict built at filing time. Set item["can_file"] = False for reports the council
doesn't handle.
"""

from __future__ import annotations

import logging

from . import triage_deciders as deciders
from .triage_rubric import RUBRICS, TEXT_NODES, Rubric, rubric_for

log = logging.getLogger(__name__)

VERSION = 1  # output shape and scoring; the rubric refactor kept both unchanged

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
NO_HAZARD_MAX_SCORE = BANDS[0][1] - 1  # highest score without a hazard: top of P2

# Kept for callers that read the keyword rules: (points, reason, patterns), from the shared text nodes.
KEYWORD_RULES = [(n.options["yes"].points, n.options["yes"].reason, list(n.keywords["yes"])) for n in TEXT_NODES]
HAZARD_REASONS = {o.reason for r in RUBRICS.values() for n in r.nodes for o in n.options.values() if o.hazard}

# How a model's reading is labelled for staff.
MODEL_LABELS = {"llm": "read by local AI", "jev": "read by Jev"}

FEW_DETAILS_REASON = "Few details: needs review"
NO_RISK_REASON = "No immediate risk reported"
REDIRECT_REASON = "Not a council highway problem: redirected"
FAILED_REASON = "Triage failed: needs manual review"

_TEXT_RUBRIC = Rubric("text", "Resident's words", TEXT_NODES)


def _fields(item: dict) -> dict:
    raw = item.get("raw") or {}
    return item.get("fields") or raw.get("fields") or raw.get("form_payload") or {}


def _priority(score: int) -> str:
    return next((p for p, low in BANDS if score >= low), "P4")


def _result(priority: str, score: int, reasons: list[str], engine: str) -> dict:
    label, target = PRIORITIES[priority]
    return {"priority": priority, "label": label, "score": score, "reasons": reasons,
            "response_target": target, "engine": engine, "version": VERSION}


def _keyword_rules(text: str) -> list[tuple[int, str]]:
    """(points, reason) for each shared text node the keyword rules find in the text."""
    found = deciders.from_keywords(_TEXT_RUBRIC, text)
    return [(n.options[found[n.id].option].points, n.options[found[n.id].option].reason)
            for n in TEXT_NODES if n.id in found]


def _label(source: str) -> str:
    return MODEL_LABELS.get(source, f"read by {source}")


def _hazard_review(node, m: deciders.Decision) -> str | None:
    """A review note when a model gives a hazard option at least REVIEW_CONFIDENCE that was not accepted."""
    hazards = {k for k, o in node.options.items() if o.hazard}
    probs = m.probs or {m.option: m.p}
    mass = sum(p for k, p in probs.items() if k in hazards)
    if mass < deciders.REVIEW_CONFIDENCE:
        return None
    worst = max(hazards, key=lambda k: probs.get(k, 0.0))
    return f"Possible: {node.options[worst].reason} ({_label(m.source)}, {mass:.0%}): needs review"


def explain(item: dict, signals: dict | None = None) -> dict:
    """triage() plus the trace: the rubric used and every decision taken. Deterministic; raises only on a bug."""
    fields = _fields(item)
    form = item.get("form") or ("report_tree" if "rad_tree_location" in fields else "report_pothole_crack")
    details = str(item.get("details") or fields.get("txta_details_about_the_location") or "")
    rubric = rubric_for(form)

    rules = {**deciders.from_fields(rubric, fields), **deciders.from_keywords(rubric, details)}
    models = deciders.from_signals(signals)
    hits: list[tuple[int, str, bool]] = []   # (points, reason, hazard)
    review: list[str] = []
    used: set[str] = set()                   # signal engines that changed the result
    answers: dict[str, str] = {}
    trace: list[dict] = []
    redirected = item.get("can_file") is False

    for node in rubric.nodes:
        if node.when and not node.when(answers):
            continue
        d, m = rules.get(node.id), models.get(node.id)
        from_model = False
        if node.model and m and m.option in node.options:
            open_ = d is None or d.option == node.default        # the form and keywords left it open
            if open_ and m.option != node.default and m.p >= deciders.MIN_CONFIDENCE:
                d, from_model = m, True
            elif not (d and node.options[d.option].hazard) and (note := _hazard_review(node, m)):
                review.append(note)
                used.add(m.source)
        if d is None:
            continue
        answers[node.id] = d.option
        trace.append(d.as_dict())
        o = node.options[d.option]
        if o.reason or o.points:
            hits.append((o.points, f"{o.reason} ({_label(d.source)})" if from_model else o.reason, o.hazard))
        if from_model:
            used.add(d.source)
        redirected = redirected or o.redirect

    extra = (signals or {}).get("reasons") or []
    replaced = {str(s["replaces"]) for s in extra if s.get("replaces")}  # e.g. a counted cluster replaces "Reported before"
    hits = [h for h in hits if h[1] not in replaced]
    for s in extra:
        hits.append((int(s.get("points", 0)), str(s["reason"]), bool(s.get("hazard"))))
        used.add(str(s.get("source") or (signals or {}).get("engine") or "signals"))
    hazard = any(h[2] for h in hits)

    order = str((signals or {}).get("engine") or "").split("+")
    engine = "+".join(["rules", *sorted(used, key=lambda e: order.index(e) if e in order else len(order))])
    reasons = list(dict.fromkeys([*(r for _, r, _ in hits if r), *review]))
    score = min(MAX_SCORE if hazard else NO_HAZARD_MAX_SCORE, BASE_SCORE + sum(p for p, _, _ in hits))
    if redirected and score < BANDS[0][1]:  # a P1 hazard stays P1 even if the form redirects it
        score = REDIRECT_SCORE
        reasons.append(REDIRECT_REASON)
    if not fields and not details.strip():
        reasons.append(FEW_DETAILS_REASON)
    if not reasons:
        reasons.append(NO_RISK_REASON)
    return {**_result(_priority(score), score, reasons, engine), "rubric": rubric.form, "decisions": trace}


def triage(item: dict, signals: dict | None = None) -> dict:
    """Priority, reasons and response target for one report. Deterministic; raises only on a programming error."""
    out = explain(item, signals)
    del out["rubric"], out["decisions"]
    return out


def combine_signals(*sources: dict | None) -> dict | None:
    """Merge signal dicts from several sources (LLM #26, Jev, map context #27) into one for triage().

    Each source is {"engine": "llm" | "jev" | "context" | ..., "reasons": [{"points": int, "reason": str}, ...],
    "decisions": {node id: {"option", "p", "probs"?}}}. Sources with neither are dropped; the engines are joined in
    order, e.g. "llm+context". Each reason and decision keeps its source, so triage() names only the engines that
    changed the result. For a node answered by two models, the first source wins.
    """
    used = [s for s in sources if s and (s.get("reasons") or s.get("decisions"))]
    if not used:
        return None
    out = {"engine": "+".join(str(s.get("engine") or "signals") for s in used),
           "reasons": [{**r, "source": r.get("source") or s.get("engine") or "signals"}
                       for s in used for r in s.get("reasons") or []]}
    decisions = {}
    for s in used:
        for node, d in (s.get("decisions") or {}).items():
            if isinstance(d, dict):
                decisions.setdefault(node, {**d, "source": d.get("source") or s.get("engine") or "model"})
    if decisions:
        out["decisions"] = decisions
    return out


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
