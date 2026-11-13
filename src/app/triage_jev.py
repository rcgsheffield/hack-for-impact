"""System One decider: TypeSafe's Jev answers a rubric's questions with calibrated probabilities. Off by default.

Jev (https://docs.typesafe.ai, POST /v1/systemone) takes a `state` and named typed questions and answers them all in
one parallel pass, in well under a second. Each rubric node maps one-to-one to a Choice question: its options become
`criteria` (name -> when it applies, at most 255), and the answer's `probabilities` give a full distribution, so
triage can accept a confident answer and flag a split one for review (triage_deciders.REVIEW_CONFIDENCE).

Turn it on with TRIAGE_DECIDER=jev and JEV_API_KEY in the environment (never in a file). It is off by default
because it is hosted in the US: local compute is a judging criterion and resident reports are personal data. Only
the free text is sent, with emails, phone numbers and postcodes removed; no name, address or coordinates.

Not yet tested against the live service (early access); the request follows the published OpenAPI schema and is
built in build_request() so it is easy to adjust. Never raises: any failure means triage uses the rules only.
"""

from __future__ import annotations

import logging
import re

import httpx

from . import config
from .triage_deciders import Decision, signals_from
from .triage_rubric import Rubric

log = logging.getLogger(__name__)

ENGINE = "jev"
MAX_TEXT_CHARS = 2000

# Personal details stripped before text leaves the machine.
REDACTIONS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"(?:\+44\s?|\b0)\d(?:[\s-]?\d){8,9}\b"), "[phone]"),  # UK numbers, 10-11 digits
    (re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE), "[postcode]"),
]


def redact(text: str) -> str:
    for pattern, mask in REDACTIONS:
        text = pattern.sub(mask, text)
    return text


def build_request(text: str, rubric: Rubric) -> dict:
    """One System One request: every model node of the rubric as a Choice question about the report."""
    return {
        "model": config.JEV_MODEL,
        "state": {"service": rubric.title, "report": redact(text)[:MAX_TEXT_CHARS]},
        "questions": {n.id: {"type": "choice", "instructions": n.question,
                             "criteria": {k: o.description for k, o in n.options.items()}}
                      for n in rubric.model_nodes()},
    }


def parse(body: dict, rubric: Rubric) -> dict[str, Decision]:
    """Choice answers -> Decisions. Keeps a default answer if it still puts weight on a hazard (for review)."""
    answers = body.get("answers") or {}
    out = {}
    for n in rubric.model_nodes():
        a = answers.get(n.id)
        if not isinstance(a, dict) or a.get("choice") not in n.options:
            continue
        probs = {k: float(v) for k, v in (a.get("probabilities") or {}).items() if k in n.options}
        option = a["choice"]
        hazard_mass = sum(p for k, p in probs.items() if n.options[k].hazard)
        if option == n.default and not hazard_mass:
            continue
        out[n.id] = Decision(n.id, option, probs.get(option, float(a.get("confidence") or 0)), ENGINE, probs or None)
    return out


def extract_signals(text: str, rubric: Rubric) -> dict | None:
    """Jev's decisions as a signals dict, or None (no key, nothing found, or any failure)."""
    if not config.JEV_API_KEY or not (text or "").strip():
        return None
    try:
        resp = httpx.post(f"{config.JEV_URL}/v1/systemone", json=build_request(text, rubric),
                          headers={"Authorization": f"Bearer {config.JEV_API_KEY}"}, timeout=config.JEV_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        return signals_from(ENGINE, parse(body, rubric), {"model": body.get("model"), "usage": body.get("usage")})
    except Exception:
        log.warning("Jev triage unavailable; using rules only", exc_info=True)
        return None
