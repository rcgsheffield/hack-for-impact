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

# ---- Browser agent (src/app/browser_agent.py, the /browser chat) ----
# Where the agent finds the forms. The app serves the mock pages at /mock/, so this is the app itself by default.
BROWSER_FORMS_URL = os.environ.get("BROWSER_FORMS_URL") or "http://127.0.0.1:8000/mock/"
# Playwright MCP server, run with npx. Keep the version in step with deploy.sh, which installs its browser.
BROWSER_MCP_PACKAGE = os.environ.get("BROWSER_MCP_PACKAGE") or "@playwright/mcp@0.0.83"
BROWSER_MCP_COMMAND = os.environ.get("BROWSER_MCP_COMMAND") or f"npx -y {BROWSER_MCP_PACKAGE}"
# Firefox: Playwright builds it for Linux on ARM (the Spark), and it was the browser we tested with.
BROWSER_NAME = os.environ.get("BROWSER_NAME") or "firefox"
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "1") != "0"
# Browser window size; the chat UI's live view shows screenshots of it beside the chat.
BROWSER_VIEWPORT = os.environ.get("BROWSER_VIEWPORT") or "1000x800"
# A form takes ~15 browser actions plus retries, far more than the form toolkits' ~6 coarse calls.
BROWSER_MAX_AGENT_STEPS = int(os.environ.get("BROWSER_MAX_AGENT_STEPS", "40"))
# Every action returns the page (~1-2k tokens), so the conversation grows fast.
BROWSER_NUM_CTX = int(os.environ.get("BROWSER_NUM_CTX", "65536"))
# Each /browser conversation runs its own Node process and browser: cap them and close idle ones.
BROWSER_MAX_SESSIONS = int(os.environ.get("BROWSER_MAX_SESSIONS", "3"))
BROWSER_IDLE_SECONDS = int(os.environ.get("BROWSER_IDLE_SECONDS", "900"))
