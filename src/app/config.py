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

# Deployed commit, set by deploy.sh and reported by /health.
GIT_SHA = os.environ.get("GIT_SHA", "unknown")

# Maximum model calls per user turn, so a confused model can't loop forever.
MAX_AGENT_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "6"))
# Seconds to wait for one model response. Large models can take a while to load on first request.
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "180"))
