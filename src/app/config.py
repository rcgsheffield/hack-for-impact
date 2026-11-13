"""Settings, read from environment variables."""

import os
from pathlib import Path

# The organisers' shared Ollama on the Spark (see docs/spark-ollama.md). Same variable names as src/smoke/.
# Empty values count as unset, so an unset GitHub repository variable falls back to the default.
OLLAMA_URL = (os.environ.get("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
# Fallback if Nemotron's tool calling misbehaves: qwen3.6:35b-a3b
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL") or "nemotron-3.5-lightning:30b"

# Filed reports are appended here as JSON lines. data/ is git-ignored and kept by deploy.sh's rsync.
REPORTS_PATH = Path(os.environ.get("REPORTS_PATH", "data/reports.jsonl"))
# Dummy council site page loads and submissions, one JSON object per line (src/app/usage.py).
USAGE_PATH = Path(os.environ.get("USAGE_PATH", "data/usage.jsonl"))
# Full records of mock-form submissions made by the form agents (council_form.py), minus reporter details.
# Read by the submissions dashboard at /dashboard (src/app/submissions.py).
MOCK_SUBMISSIONS_PATH = Path(os.environ.get("MOCK_SUBMISSIONS_PATH", "data/mock_submissions.jsonl"))

# Duplicate detection (dedup.py): reports of the same kind of problem within this distance and time window are
# grouped, so the council sees one problem with N reports and residents hear that others have reported it too.
DEDUP_RADIUS_M = float(os.environ.get("DEDUP_RADIUS_M", "60"))
DEDUP_WINDOW_DAYS = float(os.environ.get("DEDUP_WINDOW_DAYS", "30"))

# Look up typed locations with postcodes.io and Photon (OpenStreetMap) to put reports on the map (src/app/geocode.py).
# "0" keeps to the built-in sample addresses, e.g. offline or in tests.
GEOCODE_LIVE = (os.environ.get("GEOCODE_LIVE") or "1").lower() not in ("0", "false", "no")

# Deployed commit, set by deploy.sh and reported by /health.
GIT_SHA = os.environ.get("GIT_SHA", "unknown")

# Maximum model calls (tool rounds) per user turn, so a confused model can't loop forever.
# 12 leaves room for a whole form-toolkit run (start, problem, location, reporter, review) plus a retry or two;
# the LangChain agent turns this into a graph recursion limit of 2 * MAX_AGENT_STEPS + 1.
MAX_AGENT_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "12"))
# Seconds to wait for one model response. Large models can take a while to load on first request.
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "180"))

# Local-model triage signals (src/app/triage_llm.py, issue #26): read the report text after filing and add reasons.
# "0" turns it off (tests, or Ollama down); triage then uses the rules only.
TRIAGE_LLM = (os.environ.get("TRIAGE_LLM") or "1").lower() not in ("0", "false", "no")
# Seconds to wait for the model's reading of one report; on timeout triage falls back to the rules.
TRIAGE_LLM_TIMEOUT = float(os.environ.get("TRIAGE_LLM_TIMEOUT") or "20")
# Which model answers the rubric's open questions (src/app/triage_llm.py): "ollama" (local, default) or "jev"
# (TypeSafe's hosted System One model, src/app/triage_jev.py; sends redacted report text to a US service).
TRIAGE_DECIDER = (os.environ.get("TRIAGE_DECIDER") or "ollama").lower()
JEV_URL = (os.environ.get("JEV_URL") or "https://api.typesafe.ai").rstrip("/")
JEV_MODEL = os.environ.get("JEV_MODEL") or "jev-latest"
JEV_API_KEY = os.environ.get("JEV_API_KEY") or ""   # environment only; never write it to a file
JEV_TIMEOUT = float(os.environ.get("JEV_TIMEOUT") or "2")
# Cached model signals by report reference, one JSON object per line.
TRIAGE_SIGNALS_PATH = Path(os.environ.get("TRIAGE_SIGNALS_PATH") or "data/triage_signals.jsonl")
