"""Model readings of the resident's words for triage (issue #26): the model decider.

The questions come from the report's rubric (triage_rubric.py): every node with model=True becomes one typed choice,
an enum of the node's options plus a probability. This is the "System One" shape: the model only picks options, the
rubric holds the points, and adding a node to a rubric adds a question here with no other code. triage.explain()
uses a model's answer only where the form and keyword rules left a node open, and only at p >= MIN_CONFIDENCE.

Two backends, chosen by config.TRIAGE_DECIDER:
- "ollama" (default): the local model on the organisers' Ollama (config.OLLAMA_URL / OLLAMA_MODEL), structured JSON
  via Ollama's `format` schema at temperature 0. A general LLM's p is self-reported, not calibrated.
- "jev": TypeSafe's hosted System One model (triage_jev.py), with calibrated probabilities per option. Off by
  default: it sends report text to a US service.

Results are cached by report reference in config.TRIAGE_SIGNALS_PATH (JSON lines). enrich() runs the reading and
writes the cache; it runs in a background thread after filing (enrich_in_background), so the resident never waits.
cached_signals(reference) is read by submissions.load_submissions. Old cache lines (fixed "reasons" from triage v1's
five questions) still load: triage() applies them as reasons. Nothing here raises; on any failure triage falls back
to the rules.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import config
from .triage_deciders import Decision, signals_from
from .triage_rubric import Rubric, rubric_for

log = logging.getLogger(__name__)

ENGINE = "llm"
MAX_TEXT_CHARS = 2000         # the details box is short; cap what goes to the model

PROMPT_HEAD = """You read a resident's report of a problem to a city council ({title}).
Report only what the text says; do not guess. For each question pick exactly one option and give p, the probability
from 0 to 1 that your option is right. Pick the "nothing reported" option when the text does not say.
Questions:"""


def schema_for(rubric: Rubric) -> dict:
    """Ollama `format` JSON schema: one {option, p} object per model node, plus a short hazard summary."""
    props = {n.id: {"type": "object", "properties": {"option": {"type": "string", "enum": list(n.options)},
                                                     "p": {"type": "number"}},
                    "required": ["option", "p"]} for n in rubric.model_nodes()}
    props["hazard_summary"] = {"type": "string"}
    return {"type": "object", "properties": props, "required": list(props)}


def prompt_for(rubric: Rubric) -> str:
    lines = [PROMPT_HEAD.format(title=rubric.title.lower())]
    for n in rubric.model_nodes():
        lines.append(f"- {n.id}: {n.question}")
        lines += [f"    {k}: {o.description}" for k, o in n.options.items()]
    lines.append("- hazard_summary: the hazard in at most 15 words.\nReply with JSON only.")
    return "\n".join(lines)


SCHEMA = schema_for(rubric_for(None))   # the shared text questions, for reports without a known form


def to_decisions(raw: dict, rubric: Rubric, source: str = ENGINE) -> dict[str, Decision]:
    """The model's answers -> Decisions for options it actually reported. Anything malformed is skipped; any
    points or priority the model sends are ignored (they are not in the schema and nothing reads them)."""
    out = {}
    for n in rubric.model_nodes():
        a = raw.get(n.id)
        if not isinstance(a, dict) or a.get("option") not in n.options or a.get("option") == n.default:
            continue
        try:
            p = min(1.0, max(0.0, float(a.get("p"))))
        except (TypeError, ValueError):
            continue
        out[n.id] = Decision(n.id, a["option"], p, source)
    return out


def _ollama(text: str, rubric: Rubric) -> dict | None:
    resp = httpx.post(f"{config.OLLAMA_URL}/api/chat", timeout=config.TRIAGE_LLM_TIMEOUT, json={
        "model": config.OLLAMA_MODEL,
        "messages": [{"role": "system", "content": prompt_for(rubric)},
                     {"role": "user", "content": text[:MAX_TEXT_CHARS]}],
        "format": schema_for(rubric),
        "stream": False,
        "options": {"temperature": 0},
    })
    resp.raise_for_status()
    raw = json.loads(resp.json()["message"]["content"])
    if not isinstance(raw, dict):
        return None
    return signals_from(ENGINE, to_decisions(raw, rubric), raw)


def extract_signals(text: str, form: str | None = None) -> dict | None:
    """Model decisions for the report text, using the form's rubric. None on empty text, nothing found, or failure."""
    text = (text or "").strip()
    if not text:
        return None
    rubric = rubric_for(form)
    if config.TRIAGE_DECIDER == "jev":
        from . import triage_jev
        return triage_jev.extract_signals(text, rubric)
    try:
        return _ollama(text, rubric)
    except Exception:
        log.warning("LLM triage signals unavailable; using rules only", exc_info=True)
        return None


_lock = threading.Lock()
_cache: dict[str, dict] = {}
_cache_key: tuple | None = None   # (path, mtime_ns, size) the cache was loaded from


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


def enrich(reference: str, text: str, form: str | None = None) -> dict | None:
    """Read one report and append the signals to the cache. Never raises; None if nothing was stored."""
    try:
        if not reference:
            return None
        signals = extract_signals(text, form)
        if signals is None:
            return None
        model = config.JEV_MODEL if config.TRIAGE_DECIDER == "jev" else config.OLLAMA_MODEL
        line = json.dumps({"reference": str(reference), "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "model": model, "form": form, "signals": signals})
        path = Path(config.TRIAGE_SIGNALS_PATH)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return signals
    except Exception:
        log.exception("could not enrich triage for %s", reference)
        return None


def enrich_in_background(reference: str, text: str, form: str | None = None) -> None:
    """Start enrich() on a daemon thread if config.TRIAGE_LLM is on, so filing returns at once. Never raises."""
    try:
        if config.TRIAGE_LLM and reference and (text or "").strip():
            threading.Thread(target=enrich, args=(reference, text, form), daemon=True,
                             name=f"triage-llm-{reference}").start()
    except Exception:
        log.exception("could not start LLM triage for %s", reference)
