# Getting started

Stack: **Python, FastAPI and a [Gradio](https://www.gradio.app/) chat UI, with the `openai` SDK** calling the organisers' Ollama on its OpenAI-compatible `/v1` API. That's the same API as NVIDIA NIM, so moving to NIM only means changing `OLLAMA_URL`. Everything runs natively on the Spark's ARM64 CPU, without Docker. Dependencies live in `pyproject.toml` and `uv.lock`.

| Path | What it is |
|---|---|
| `src/app/main.py` | FastAPI app: chat UI at `/`, status at `/health` |
| `src/app/usage.py` | Serves the dummy council site (`src/mock/`) at `/mock/` and logs page loads and submissions to `data/usage.jsonl` |
| `src/app/submissions.py` | Submissions dashboard at `/dashboard` (JSON at `/api/submissions`): what the agents have submitted to the mock forms |
| `src/app/static/report-card.js` | Front-end library: `ReportCard.render(item, {audience: "staff" | "resident"})` draws one report as a card (styles in `report-card.css`) |
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

### Dummy council site usage log

The mock council forms are served at `/mock/` (for example `/mock/report_pothole_crack.html`). Every page load and every submission is appended to `data/usage.jsonl` (`USAGE_PATH`), one JSON object per line with a UTC timestamp, the event (`view` or `submit`), the page, the user agent, the referrer and, for submissions, the reference number. No IP addresses or form answers are logged. Pages opened as local files (`file://`) are not logged.

```bash
tail -f data/usage.jsonl
# Count events by page and type:
jq -r '[.event, .page] | @tsv' data/usage.jsonl | sort | uniq -c
```

To log agent runs too, point the form toolkit at the served copy; they show up with a `HeadlessChrome` user agent:

```bash
POTHOLE_FORM_URL=http://127.0.0.1:8000/mock/report_pothole_crack.html uv run python -m app.pothole_form_toolkit
```

### Submissions dashboard

<http://127.0.0.1:8000/dashboard> (on the Spark: <http://spark12.local/dashboard>) shows every submission to the mock forms and refreshes every 5 seconds. It combines:

- form-agent submissions (`council_form.py` saves each submitted record to `data/mock_submissions.jsonl`, minus name, date of birth, phone and email),
- chat-agent reports from `file_report` (`data/reports.jsonl`),
- forms submitted by hand in a browser at `/mock/` (reference only, from `data/usage.jsonl`), plus page-view counts split into agent (HeadlessChrome) and person.

A map plots every filtered submission that has coordinates (the mock forms' `le_gis`), coloured by form; a row's "map" link zooms to it. Chat-agent and by-hand submissions have no coordinates, so the note under the map counts them instead. The map loads Leaflet from unpkg.com and Esri tiles, so it needs internet access; the rest of the dashboard doesn't.

Expanding a row shows the report as a card (`static/report-card.js`, staff view) with the raw record folded away, and a link to the resident view.

### Viewing one report

`/reports/<reference>` (JSON at `/api/reports/<reference>`) shows a single report to the resident who filed it: reference number, what was recorded, severity and a prototype notice, without agent or source details. `file_report` returns this link as `url` and the chat agent passes it on. To render reports on another page, include `/static/report-card.css` and `/static/report-card.js`, then set `el.innerHTML = ReportCard.render(item, { audience: "resident" })` with an item from either API.

## Settings

Environment variables:

| Variable | Default | |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama, or any OpenAI-compatible server such as NIM |
| `OLLAMA_MODEL` | `nemotron-3.5-lightning:30b` | Try `qwen3.6:35b-a3b` if Nemotron's tool calls misbehave |
| `REPORTS_PATH` | `data/reports.jsonl` | Where filed reports are recorded |
| `MOCK_SUBMISSIONS_PATH` | `data/mock_submissions.jsonl` | Mock-form submissions made by the form agents, without reporter details |
| `MAX_AGENT_STEPS` | `12` | Model calls allowed per user message |
| `LLM_TIMEOUT` | `180` | Seconds to wait for one model response |

Filed reports go to `data/reports.jsonl` only. Nothing is sent to the council.

## Check the deployed app

Run `src/app/check.sh` (or `curl http://spark12.local:8000/health`). It returns `{"ok": true, ...}` with the deployed commit's short SHA, or HTTP 503 if Ollama is unreachable or the model is missing. The chat UI is at <http://spark12.local> or <https://spark12.local> (self-signed certificate, so accept the browser warning). Port 8000 still works directly.

See [deployment.md](deployment.md) for how the app gets there.
