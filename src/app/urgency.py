"""Telling residents the priority, and escalating emergencies (P1) to the phone instead of the queue.

Used by the tools (so every filing result carries plain-English priority and, for P1, the urgent advice) and by the
agent loop (so urgent advice reaches the resident even if the model forgets it). Deterministic: no model involved.
"""

from __future__ import annotations

import re

from .triage import triage

COUNCIL_PHONE = "0114 273 4567"
URGENT_ADVICE = (f"This sounds urgent: please phone Sheffield City Council now on {COUNCIL_PHONE}, "
                 "or 999 if anyone is in danger. Don't wait for the online report.")
PRIORITY_NOTE = "This is a suggestion only: the council decides the priority after inspection."

# Free-text hints for a street tree that has come down (triage.py scores a fallen tree on the form's own field).
# The tree word comes first, so "I fell over a tree root" doesn't count.
_FALLEN_TREE = re.compile(
    r"\b(trees?|branch(es)?|boughs?|limbs?)\b(\s+down\b|[^.?!]{0,40}?\b(fallen|fell|falling|(come|came|blown|brought|"
    r"is|are|been) down|snapped|uprooted|collapsed)\b)", re.IGNORECASE)
_IN_THE_WAY = re.compile(r"\b(across|block\w*|in the way|over the (road|pavement|path))\b", re.IGNORECASE)


def summary(t: dict) -> dict:
    """The parts of a triage result a resident should hear, for a tool result. No scores or engine."""
    out = {"priority": f"{t['priority']} {t['label']}",
           "label": t["label"],
           "response_target": t["response_target"],
           "priority_plain": f"{t['label']}: {t['response_target'][0].lower()}{t['response_target'][1:]}",
           "priority_note": PRIORITY_NOTE}
    if t["priority"] == "P1":
        out["urgent_advice"] = URGENT_ADVICE
        out["tell_user"] = [URGENT_ADVICE]
    return out


def triage_text(text: str) -> dict:
    """Triage what the resident has said so far, before any form fields exist.

    Keyword rules from triage.py, plus a fallen tree (inferred from the words) scored as the tree form would score it.
    """
    item: dict = {"details": text}
    if _FALLEN_TREE.search(text):
        item = {"form": "report_tree", "details": text,
                "fields": {"rad_tree_location": "Highway", "rad_tree_problem": "Fallen",
                           "rad_tree_blocking": "Yes" if _IN_THE_WAY.search(text) else "No"}}
    return triage(item)


def is_urgent_text(text: str) -> bool:
    return bool(text.strip()) and triage_text(text)["priority"] == "P1"


def urgent_note(text: str) -> str:
    """A note for the model, appended to the user's message, when what they said already looks like a P1."""
    if not is_urgent_text(text):
        return ""
    return ("\n\n[Urgent check: this sounds like an emergency. Start your reply with this advice, word for word: "
            f"\"{URGENT_ADVICE}\" Then carry on with the report if they want to.]")


def is_urgent_result(result: dict) -> bool:
    """True if a tool result says the report is urgent (P1, or explicit urgent advice)."""
    return bool(result.get("urgent_advice")) or str(result.get("priority", "")).startswith("P1")


def ensure_advice(reply: str, urgent: bool) -> str:
    """Append the urgent advice to the reply if it's urgent and the model left out the phone number."""
    if urgent and COUNCIL_PHONE not in reply:
        return f"{reply}\n\n{URGENT_ADVICE}".strip()
    return reply
