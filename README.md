<p align="center">
  <img src="docs/logo.svg" alt="Hack for Impact logo: a smiling tree with circuit-trace roots" width="200">
</p>

# Hack for Impact

[![Deploy to DGX Spark](https://github.com/rcgsheffield/hack-for-impact/actions/workflows/deploy.yml/badge.svg)](https://github.com/rcgsheffield/hack-for-impact/actions/workflows/deploy.yml)

> Build autonomous systems that think, act, and run anywhere, whilst also making a positive impact on the world.

Our entry for the NVIDIA [Hack for Impact Sheffield](https://events.nvidia.com/hack-for-impact-sheffield/) hackathon, **Friday 13 November 2026, 09:00 – 20:00**.

## Challenge

We are building an agentic AI solution that runs on local compute and delivers real-world impact in one of three tracks:

| Track | Focus | Goal |
|-------|-------|------|
| **Economic Systems** | How money flows through businesses, workers and markets | Agentic systems that help people and organisations make better economic decisions, unlock opportunities or optimise costs |
| **Public Services** | How people access and interact with public services and resources | Data-driven tools that make public systems easier to navigate, more efficient and more user-friendly |
| **Urban Operations** | How cities run, from large-scale infrastructure to everyday life | Systems that improve how cities function behind the scenes and in real time |

Tracks describe a theme of impact, not the scope of the idea. Any solution that delivers against a theme is eligible.

### Judging criteria

- **Impact**: does the solution address a real problem?
- **Technical execution**: how well does it use agentic AI and local compute?
- **Feasibility**: could it realistically be built or deployed beyond the hackathon?

## Chosen track and idea

**CouncilTriagent**

- **Track:** Public Services
- **Problem:** Reporting a street problem means knowing who owns it (council, National Highways, a private landowner, DVLA or the police), finding the right form and filling it in. Many people phone instead, and council staff then re-key and triage the reports by hand.
- **Who benefits:** Residents, who report in plain words, and council staff, who get complete reports that have already been triaged.
- **Approach:** A local agent (Nemotron on the DGX Spark, through Ollama) talks to the resident and calls tools. It routes the report to whoever owns the problem, assesses severity using the council form's depth bands, and files a completed form payload with a reference number. Routing rules come from [`docs/sheffield-council-services.md`](docs/sheffield-council-services.md). The first version covers road and pavement defects.

## Data sources

Public datasets are available, and none is mandatory:

- [Sheffield City Council Open Data portal](https://data.sheffield.gov.uk/), including Sheffield Local Insight neighbourhood indicators
- [data.gov.uk](https://www.data.gov.uk/)
- [Office for National Statistics (ONS)](https://www.ons.gov.uk/)

Keep downloaded datasets in `data/`. Raw files are git-ignored by default, so record where each came from in [`data/README.md`](data/README.md).

## Repository layout

```
.
├── docs/       Challenge brief, design notes, pitch material
├── data/       Local datasets (not committed) and their provenance
├── src/        Application and agent code (src/app)
├── tests/      Tests (pytest)
├── video/      Pitch video, built with HyperFrames (see video/README.md)
├── LICENSE
└── README.md
```

## Getting started

Stack: **Python, FastAPI and a [Gradio](https://www.gradio.app/) chat UI, with the `openai` SDK** calling the organisers' Ollama on its OpenAI-compatible `/v1` API. That's the same API as NVIDIA NIM, so moving to NIM only means changing `OLLAMA_URL`. Everything runs natively on the Spark's ARM64 CPU, without Docker. Dependencies live in `pyproject.toml` and `uv.lock`.

| Path | What it is |
|---|---|
| `src/app/main.py` | FastAPI app: chat UI at `/`, status at `/health` |
| `src/app/agent.py` | System prompt and tool-calling loop |
| `src/app/tools.py` | Agent tools: `route_report`, `assess_pothole`, `file_report` |
| `src/app/config.py` | Settings from environment variables |
| `src/app/check.sh` | Checks the deployed app's `/health` |
| `tests/` | Tests for the tools and the agent loop (fake model, so no GPU needed) |

Run it locally (needs [uv](https://docs.astral.sh/uv/)):

```bash
uv sync          # creates .venv with the app and dev dependencies
uv run pytest

# Ollama only listens on the Spark's localhost, so tunnel to it:
ssh -N -L 11434:127.0.0.1:11434 <user>@<spark> &
uv run uvicorn app.main:app --app-dir src --reload    # http://127.0.0.1:8000
```

Settings (environment variables):

| Variable | Default | |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama, or any OpenAI-compatible server such as NIM |
| `OLLAMA_MODEL` | `nemotron-3.5-lightning:30b` | Try `qwen3.6:35b-a3b` if Nemotron's tool calls misbehave |
| `REPORTS_PATH` | `data/reports.jsonl` | Where filed reports are recorded |
| `MAX_AGENT_STEPS` | `6` | Model calls allowed per user message |
| `LLM_TIMEOUT` | `180` | Seconds to wait for one model response |

Filed reports go to `data/reports.jsonl` only. Nothing is sent to the council.

**Check the deployed app:** `src/app/check.sh` (or `curl http://spark12.local:8000/health`). It returns `{"ok": true, ...}` with the deployed commit's short SHA, or HTTP 503 if Ollama is unreachable or the model is missing. The chat UI is at <http://spark12.local:8000>.

### Deployment (DGX Spark)

Every push to `main` deploys to the DGX Spark through a GitHub Actions [self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners) on that machine (`.github/workflows/deploy.yml`). The runner connects out to GitHub, so the Spark needs no inbound access. The workflow runs [`deploy.sh`](deploy.sh), which syncs the code to `~/hack-for-impact` on the Spark (its local `data/` is kept) and then starts the app. To redeploy without pushing, use **Actions → Deploy to DGX Spark → Run workflow**.

One-time runner setup, done on the Spark over SSH:

1. In GitHub, go to **Settings → Actions → Runners → New self-hosted runner**, choose **Linux / ARM64**, and follow the download steps it shows.
2. Configure the runner with the `spark` label and install it as a service:
   ```bash
   ./config.sh --url https://github.com/rcgsheffield/hack-for-impact --token <TOKEN> --labels spark --unattended
   sudo ./svc.sh install && sudo ./svc.sh start
   ```
3. Make sure `rsync` and `curl` are installed.

On each deploy, `deploy.sh` does the following:

- Installs [uv](https://docs.astral.sh/uv/) into `~/.local/bin` if it's missing.
- Syncs `uv.lock` into a venv at `~/.local/share/hack-for-impact/venv`.
- Restarts the app on port 8000, logging to `~/hack-for-impact.log` (pid in `~/.local/share/hack-for-impact/app.pid`).
- Fails the deploy if `/health` isn't green within 60 seconds, which includes Ollama being reachable.

The app is a plain background process: the runner has no systemd user session and no sudo. So it doesn't come back after a reboot: rerun the workflow if that happens. To change the model or the Ollama endpoint without a code change, set the repository variables `APP_MODEL` and `OLLAMA_URL`.

### Smoke test (GPU + Ollama)

The Spark's organisers run a shared Ollama container, `spark-hack-ollama`, with `nemotron-3-nano:30b`, `nemotron-3.5-lightning:30b` and `qwen3.6:35b-a3b`. **Use it for all local inference**: don't run our own Ollama, and don't pull or unload models on it, because other teams share it. The runner's user can't use Docker.

[`src/smoke/smoke_test.sh`](src/smoke/smoke_test.sh) checks that endpoint end to end with only `curl` and `python3`. It confirms Ollama is reachable, checks that the model is listed, generates a reply and fails if the model isn't resident in VRAM. The **Smoke test** workflow (`.github/workflows/smoke.yml`) runs it on the Spark for pull requests touching `src/smoke/`, or via **Actions → Smoke test → Run workflow**; it never deploys. Set the endpoint and model with the repository variables `OLLAMA_URL` (default `http://127.0.0.1:11434`) and `OLLAMA_MODEL` (default `nemotron-3-nano:30b`). Locally: `OLLAMA_URL=http://<host>:11434 REQUIRE_GPU=0 src/smoke/smoke_test.sh`.

### Local LLM (Ollama)

The Spark already runs an organiser-provided Ollama container (`spark-hack-ollama`) on `localhost:11434`, with Nemotron and Qwen models downloaded. It clashes with the smoke stack's port. See [`docs/spark-ollama.md`](docs/spark-ollama.md) for the models, how to call it and how to stop it.

## Team

_Add team members here._

## Licence

Released under the [MIT License](LICENSE).
