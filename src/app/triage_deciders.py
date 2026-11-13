"""Deciders: who answers a rubric's questions (triage_rubric.Node), and how sure they are.

Every decider returns {node id: Decision}. A Decision only names an option of the node; points, reasons and hazard
flags come from the rubric. Order of trust, used by triage.explain():

1. form fields (p = 1.0): what the resident picked on the council's form
2. keywords (p = 1.0): regexes over the resident's words
3. models, read from signals["decisions"]: the local LLM (triage_llm.py, default) or a System One model such as
   TypeSafe's Jev (triage_jev.py, off by default). A model may only fill a node the form and keywords left at its
   default ("nothing found"); it never overrides or removes their answers.

Model decisions travel inside a signals dict so they can be cached and merged like the map-context signals:
    {"engine": "llm", "decisions": {"injury": {"option": "yes", "p": 0.9, "probs": {"none": 0.1, "yes": 0.9}}}}
"probs" (the full distribution) is optional; System One models return it, a plain LLM does not.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .triage_rubric import Rubric

MIN_CONFIDENCE = 0.5      # a model's answer counts only with at least this probability
REVIEW_CONFIDENCE = 0.3   # a hazard this likely, but under MIN_CONFIDENCE, is flagged for review (0 points):
                          # under-triage costs more than over-triage


@dataclass(frozen=True)
class Decision:
    node: str
    option: str
    p: float = 1.0
    source: str = "form"            # "form" | "keyword" | a model engine ("llm", "jev")
    probs: dict | None = None       # full distribution over the node's options, if the decider gives one

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def from_fields(rubric: Rubric, fields: dict) -> dict[str, Decision]:
    out = {}
    for n in rubric.nodes:
        option = n.from_fields(fields) if n.from_fields else None
        if option is not None:
            out[n.id] = Decision(n.id, option, 1.0, "form")
    return out


def from_keywords(rubric: Rubric, text: str) -> dict[str, Decision]:
    out = {}
    for n in rubric.nodes:
        for option, patterns in n.keywords.items():
            if any(re.search(p, text or "", re.IGNORECASE) for p in patterns):
                out[n.id] = Decision(n.id, option, 1.0, "keyword")
                break
    return out


def from_signals(signals: dict | None) -> dict[str, Decision]:
    """Model decisions carried in a signals dict (see module docstring). Malformed entries are skipped."""
    out = {}
    for node_id, d in ((signals or {}).get("decisions") or {}).items():
        try:
            probs = d.get("probs")
            out[str(node_id)] = Decision(str(node_id), str(d["option"]), float(d["p"]),
                                         str(d.get("source") or (signals or {}).get("engine") or "model"),
                                         {str(k): float(v) for k, v in probs.items()} if isinstance(probs, dict)
                                         else None)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return out


def signals_from(engine: str, decisions: dict[str, Decision], raw: dict | None = None) -> dict | None:
    """A cacheable signals dict for model decisions, or None if the model found nothing beyond the defaults."""
    if not decisions:
        return None
    out = {"engine": engine, "decisions": {k: {key: v for key, v in d.as_dict().items() if key != "node"}
                                           for k, d in decisions.items()}}
    if raw is not None:
        out["raw"] = raw
    return out
