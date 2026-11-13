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
| `src/app/triage.py` | Automatic triage: priority, reasons and response target for every report; signals from `triage_llm.py` (local LLM) and `triage_context.py` (road class, repeat reports), resident messaging in `urgency.py`. See [`triage.md`](triage.md) |
| `src/app/triage_eval.py`, `src/app/demo_seed.py` | Triage evaluation on the labelled set; demo queue for the dashboard |
| `src/app/geocode.py` | Turns a typed location into coordinates for the map (sample addresses, postcodes.io, Photon) |
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

The mock council forms are served at `/mock/` (for example `/mock/report_pothole_crack.html`). Every page load and every submission is appended to `data/usage.jsonl` (`USAGE_PATH`), one JSON object per line with a UTC timestamp, the event (`view` or `submit`), the page, the user agent, the referrer and, for submissions, the reference number and location (`location` text, `lat`, `lon`, `geo_source`). No IP addresses or other form answers are logged. Pages opened as local files (`file://`) are not logged.

```bash
tail -f data/usage.jsonl
# Count events by page and type:
jq -r '[.event, .page] | @tsv' data/usage.jsonl | sort | uniq -c
```

To log agent runs too, point the form toolkit at the served copy; they show up with a `HeadlessChrome` user agent:

```bash
POTHOLE_FORM_URL=http://127.0.0.1:8000/mock/report_pothole_crack.html uv run python -m app.pothole_form_toolkit
```

### Location pin

The chat page has an optional map beside the chat. "Use my location" asks the browser for the device's position (GPS on a phone) and drops a pin; people can also tap the map, and drag the pin to the exact spot. The pin becomes a note on the model's copy of the message (`location_note` in `src/app/main.py`), and the model passes its lat/lon to the filing tools. A device fix is sent as `lat, lon (±N m)` ("use it only if they're at the problem"); a tapped or dragged pin as `lat, lon (map pin)` ("this is where the problem is"). Browsers only share location on a secure origin, so the button works at <https://spark12.local> and `localhost` but is disabled at `http://spark12.local:8000`, where tapping the map still works. The map script is `src/app/static/location-pin.js`.

### Submissions dashboard

<http://127.0.0.1:8000/dashboard> (on the Spark: <http://spark12.local/dashboard>) shows every submission to the mock forms and refreshes every 5 seconds. It combines:

- form-agent submissions (`council_form.py` saves each submitted record to `data/mock_submissions.jsonl`, minus name, date of birth, phone and email),
- chat-agent reports from `file_report` (`data/reports.jsonl`),
- forms submitted by hand in a browser at `/mock/` (reference and location, from `data/usage.jsonl`), plus page-view counts split into agent (HeadlessChrome) and person.

A map plots every filtered submission that has coordinates, coloured by form; a row's "map" link zooms to it. The note under the map counts submissions whose location couldn't be found.

#### How each report gets a location

| Path | Coordinates from |
|---|---|
| Mock form, address picked or map clicked | The form's `le_gis` (`geo_source` `form`) |
| Mock form, "use what I typed" (incl. form agents) | `save_submission` or `/mock/events` geocodes the typed address |
| Chat agent `file_report` | Geocodes `location`; saved as `geo` and `form_payload.le_gis`; the tool result's `located_at` says where |
| `road-report-agent.html` prototype | Sends its location text; `/mock/events` geocodes it |

`src/app/geocode.py` tries the mocks' 10 sample addresses first (offline), then postcodes.io for postcodes and Photon (OpenStreetMap) for anything else, keeping only results inside Sheffield. Lookups time out after 3 s and are cached. A report is filed even if it can't be placed; its `lat`/`lon` are then `null`. Popups mark points placed from typed text as approximate. The map loads Leaflet from unpkg.com and Esri tiles, so it needs internet access; the rest of the dashboard doesn't.

Reports are sorted by suggested priority (P1 first) with their reasons; how that's worked out, and how to fill the queue for a demo (`python -m app.demo_seed`), is in [`triage.md`](triage.md).

Expanding a row shows the report as a card (`static/report-card.js`, staff view) with the raw record folded away, and a link to the resident view.

### Viewing one report

`/reports/<reference>` (JSON at `/api/reports/<reference>`) shows a single report to the resident who filed it: reference number, what was recorded, the suggested priority with its response target and reasons (plus the phone advice for P1) and a prototype notice, without agent or source details. `file_report` returns this link as `url` and the chat agent passes it on. To render reports on another page, include `/static/report-card.css` and `/static/report-card.js`, then set `el.innerHTML = ReportCard.render(item, { audience: "resident" })` with an item from either API.

## Settings

Environment variables:

| Variable | Default | |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama, or any OpenAI-compatible server such as NIM |
| `OLLAMA_MODEL` | `nemotron-3.5-lightning:30b` | Try `qwen3.6:35b-a3b` if Nemotron's tool calls misbehave |
| `REPORTS_PATH` | `data/reports.jsonl` | Where filed reports are recorded |
| `MOCK_SUBMISSIONS_PATH` | `data/mock_submissions.jsonl` | Mock-form submissions made by the form agents, without reporter details |
| `GEOCODE_LIVE` | `1` | `0` to geocode only the built-in sample addresses (no calls to postcodes.io or Photon) |
| `MAX_AGENT_STEPS` | `12` | Model calls allowed per user message |
| `LLM_TIMEOUT` | `180` | Seconds to wait for one model response |
| `TRIAGE_LLM` | `1` | `0` to triage with rules and map context only (no Ollama call after filing) |
| `TRIAGE_LLM_TIMEOUT` | `20` | Seconds to wait for the triage model's reading of a report |
| `TRIAGE_SIGNALS_PATH` | `data/triage_signals.jsonl` | Cache of the triage model's readings, by reference |

Filed reports go to `data/reports.jsonl` only. Nothing is sent to the council.

## Check the deployed app

Run `src/app/check.sh` (or `curl http://spark12.local:8000/health`). It returns `{"ok": true, ...}` with the deployed commit's short SHA, or HTTP 503 if Ollama is unreachable or the model is missing. The chat UI is at <http://spark12.local> or <https://spark12.local> (self-signed certificate, so accept the browser warning). Port 8000 still works directly.

See [deployment.md](deployment.md) for how the app gets there.
