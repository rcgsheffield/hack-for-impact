# Getting started

Stack: **Python, FastAPI and a [Gradio](https://www.gradio.app/) chat UI, with the `openai` SDK** calling the organisers' Ollama on its OpenAI-compatible `/v1` API. That's the same API as NVIDIA NIM, so moving to NIM only means changing `OLLAMA_URL`. Everything runs natively on the Spark's ARM64 CPU, without Docker. Dependencies live in `pyproject.toml` and `uv.lock`.

| Path | What it is |
|---|---|
| `src/app/main.py` | FastAPI app: chat UI at `/`, status at `/health` |
| `src/app/agent.py` | System prompt and tool-calling loop |
| `src/app/tools.py` | Agent tools: `route_report`, `assess_pothole`, `file_report` |
| `src/app/config.py` | Settings from environment variables |
| `src/app/check.sh` | Checks the deployed app's `/health` |
| `tests/` | Tests for the tools and the agent loop (fake model, so no GPU needed) |

## Run it locally

Needs [uv](https://docs.astral.sh/uv/).

```bash
uv sync          # creates .venv with the app and dev dependencies
uv run pytest

# Ollama only listens on the Spark's localhost, so tunnel to it:
ssh -N -L 11434:127.0.0.1:11434 <user>@<spark> &
uv run uvicorn app.main:app --app-dir src --reload    # http://127.0.0.1:8000
```

## Settings

Environment variables:

| Variable | Default | |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama, or any OpenAI-compatible server such as NIM |
| `OLLAMA_MODEL` | `nemotron-3.5-lightning:30b` | Try `qwen3.6:35b-a3b` if Nemotron's tool calls misbehave |
| `REPORTS_PATH` | `data/reports.jsonl` | Where filed reports are recorded |
| `MAX_AGENT_STEPS` | `12` | Model calls allowed per user message |
| `LLM_TIMEOUT` | `180` | Seconds to wait for one model response |

Filed reports go to `data/reports.jsonl` only. Nothing is sent to the council.

## Check the deployed app

Run `src/app/check.sh` (or `curl http://spark12.local:8000/health`). It returns `{"ok": true, ...}` with the deployed commit's short SHA, or HTTP 503 if Ollama is unreachable or the model is missing. The chat UI is at <http://spark12.local> or <https://spark12.local> (self-signed certificate, so accept the browser warning). Port 8000 still works directly.

See [deployment.md](deployment.md) for how the app gets there.
