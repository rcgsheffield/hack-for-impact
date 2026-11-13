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
