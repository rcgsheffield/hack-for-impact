"""Triage signals from the resident's own words, read by the local model (issue #26).

extract_signals(text) asks Ollama (config.OLLAMA_URL / OLLAMA_MODEL) for structured JSON at temperature 0 and turns
the model's fields into a signals dict for triage.triage(). The model only reports facts (was someone hurt, who is
at risk, is it blocking); the points come from the fixed mapping below, so the rules engine still decides the
priority. A hazard the keyword rules already found in the same text is not counted twice.

Results are cached by report reference in config.TRIAGE_SIGNALS_PATH (JSON lines). enrich(reference, text) runs the
extraction and writes the cache; it runs in a background thread after filing (enrich_in_background), so the resident
never waits. cached_signals(reference) is read by submissions.load_submissions. Nothing here raises: on any failure
triage falls back to the rules only.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import config
from .triage import _keyword_rules

log = logging.getLogger(__name__)

ENGINE = "llm"
MIN_CONFIDENCE = 0.5          # below this the model's reading is ignored
MAX_TEXT_CHARS = 2000         # the details box is short; cap what goes to the model

# Points for each fact the model reports. Same weights as the matching keyword rule in triage.KEYWORD_RULES,
# so the model finds hazards the regexes miss without counting more than a rule would.
INJURY_POINTS = 30
HAZARD_FACTS = {"injury"}  # an immediate risk on its own: may make a report P1 (triage.HAZARD_REASONS)
BLOCKING_POINTS = 20
VULNERABLE_POINTS = 15
CYCLIST_POINTS = 15
HIGH_TRAFFIC_POINTS = 15

# Model fact -> (points, reason shown on the dashboard, keyword rule reason that already covers it).
MAPPING = {
    "injury": (INJURY_POINTS, "Someone has been hurt (read by local AI)", "Someone has been hurt"),
    "blocking": (BLOCKING_POINTS, "Blocking the road or pavement (read by local AI)", "Blocking the road or pavement"),
    "vulnerable": (VULNERABLE_POINTS, "Affects children, elderly or disabled people (read by local AI)",
                   "Affects children or disabled people"),
    "cyclists": (CYCLIST_POINTS, "Risk to cyclists or motorcyclists (read by local AI)",
                 "Risk to cyclists or motorcyclists"),
    "traffic": (HIGH_TRAFFIC_POINTS, "Busy road or heavy traffic (read by local AI)",
                "Busy road, bus route or traffic swerving"),
}
VULNERABLE_GROUPS = {"children", "elderly", "disabled"}
CYCLIST_GROUPS = {"cyclists", "motorcyclists"}

SCHEMA = {
    "type": "object",
    "properties": {
        "injury_reported": {"type": "boolean"},
        "vulnerable_users": {"type": "array", "items": {
            "type": "string", "enum": ["children", "elderly", "disabled", "cyclists", "motorcyclists", "pedestrians"]}},
        "blocking": {"type": "boolean"},
        "traffic_exposure": {"type": "string", "enum": ["low", "medium", "high"]},
        "hazard_summary": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["injury_reported", "vulnerable_users", "blocking", "traffic_exposure", "hazard_summary", "confidence"],
}

PROMPT = """You read a resident's report of a road, pavement or tree problem to a city council.
Report only what the text says; do not guess. Fields:
- injury_reported: true only if the text says a person or animal was actually hurt, fell or came off a bike.
- vulnerable_users: groups the text says are affected or at risk (children, elderly, disabled, cyclists,
  motorcyclists, pedestrians). Empty if none are mentioned.
- blocking: true if the problem blocks or narrows a road, lane, pavement or path.
- traffic_exposure: "high" for a busy or main road, bus route, junction or cars swerving; "low" for a quiet street
  or path; otherwise "medium".
- hazard_summary: the hazard in at most 15 words.
- confidence: 0 to 1, how clearly the text supports these answers.
Reply with JSON only."""

_lock = threading.Lock()
_cache: dict[str, dict] = {}
_cache_key: tuple | None = None   # (path, mtime_ns, size) the cache was loaded from


def to_signals(raw: dict, text: str = "") -> dict | None:
    """The model's fields -> {"engine": "llm", "reasons": [...], "raw": {...}}; None if unusable or low confidence."""
    try:
        confidence = float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        return None
    if confidence < MIN_CONFIDENCE:
        return None
    groups = {str(g).lower() for g in raw.get("vulnerable_users") or [] if isinstance(g, str)}
    facts = []
    if raw.get("injury_reported") is True:
        facts.append("injury")
    if raw.get("blocking") is True:
        facts.append("blocking")
    if groups & VULNERABLE_GROUPS:
        facts.append("vulnerable")
    if groups & CYCLIST_GROUPS:
        facts.append("cyclists")
    if raw.get("traffic_exposure") == "high":
        facts.append("traffic")
    already = {reason for _, reason in _keyword_rules(text)}
    reasons = [{"points": MAPPING[f][0], "reason": MAPPING[f][1], "hazard": f in HAZARD_FACTS}
               for f in facts if MAPPING[f][2] not in already]
    return {"engine": ENGINE, "reasons": reasons, "raw": raw}


def extract_signals(text: str) -> dict | None:
    """Ask the local model for hazard signals in the report text. None on empty text or any failure."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        resp = httpx.post(f"{config.OLLAMA_URL}/api/chat", timeout=config.TRIAGE_LLM_TIMEOUT, json={
            "model": config.OLLAMA_MODEL,
            "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": text[:MAX_TEXT_CHARS]}],
            "format": SCHEMA,
            "stream": False,
            "options": {"temperature": 0},
        })
        resp.raise_for_status()
        raw = json.loads(resp.json()["message"]["content"])
        if not isinstance(raw, dict):
            return None
        return to_signals(raw, text)
    except Exception:
        log.warning("LLM triage signals unavailable; using rules only", exc_info=True)
        return None


def _load() -> dict[str, dict]:
    """Latest signals per reference, reloaded only when the file changes."""
    global _cache, _cache_key
    path = Path(config.TRIAGE_SIGNALS_PATH)
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if key != _cache_key:
            cache = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                    cache[str(rec["reference"])] = rec["signals"]
                except (ValueError, KeyError, TypeError):
                    continue
            _cache, _cache_key = cache, key
        return _cache


def cached_signals(reference: str) -> dict | None:
    """Stored signals for this report, or None. Never raises."""
    try:
        return _load().get(str(reference)) if reference else None
    except Exception:
        log.exception("could not read triage signals")
        return None


def enrich(reference: str, text: str) -> dict | None:
    """Extract signals for one report and append them to the cache. Never raises; None if nothing was stored."""
    try:
        if not reference:
            return None
        signals = extract_signals(text)
        if signals is None:
            return None
        line = json.dumps({"reference": str(reference), "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "model": config.OLLAMA_MODEL, "signals": signals})
        path = Path(config.TRIAGE_SIGNALS_PATH)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return signals
    except Exception:
        log.exception("could not enrich triage for %s", reference)
        return None


def enrich_in_background(reference: str, text: str) -> None:
    """Start enrich() on a daemon thread if config.TRIAGE_LLM is on, so filing returns at once. Never raises."""
    try:
        if config.TRIAGE_LLM and reference and (text or "").strip():
            threading.Thread(target=enrich, args=(reference, text), daemon=True, name=f"triage-llm-{reference}").start()
    except Exception:
        log.exception("could not start LLM triage for %s", reference)
