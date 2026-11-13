<p align="center">
  <img src="docs/logo.svg" alt="Hack for Impact logo: a smiling tree with circuit-trace roots" width="200">
</p>

# Hack for Impact

[![Deploy to DGX Spark](https://github.com/rcgsheffield/hack-for-impact/actions/workflows/deploy.yml/badge.svg)](https://github.com/rcgsheffield/hack-for-impact/actions/workflows/deploy.yml)

> Build autonomous systems that think, act, and run anywhere, whilst also making a positive impact on the world.

Our entry for the NVIDIA [Hack for Impact Sheffield](https://events.nvidia.com/hack-for-impact-sheffield/) hackathon, **Friday 13 November 2026, 09:00 – 20:00**.

## Challenge

We are building an agentic AI solution that runs on local compute and delivers real-world impact in one of three tracks (Economic Systems, Public Services, Urban Operations). Judging is on impact, technical execution and feasibility. See [`docs/challenge.md`](docs/challenge.md) for the full brief.

## Chosen track and idea

**CouncilTriagent**

- **Track:** Public Services
- **Problem:** Reporting a street problem means knowing who owns it (council, National Highways, a private landowner, DVLA or the police), finding the right form and filling it in. Many people phone instead, and council staff then re-key and triage the reports by hand.
- **Who benefits:** Residents, who report in plain words, and council staff, who get complete reports that have already been triaged.
- **Approach:** A local agent (Nemotron on the DGX Spark, through Ollama) talks to the resident and calls tools. It routes the report to whoever owns the problem, assesses severity using the council form's depth bands, and files a completed form payload with a reference number. Routing rules come from [`docs/sheffield-council-services.md`](docs/sheffield-council-services.md). The first version covers road and pavement defects.

### How it works

```mermaid
flowchart TD
    A["Resident describes the problem<br>plus an optional map pin or device location"] --> B["Agent clarifies what and where<br>(one question at most)"]
    B --> C{"Who owns it?<br>route_report"}

    C -->|Untaxed vehicle| D1[DVLA]
    C -->|Blocking or burnt-out vehicle| D2["South Yorkshire Police (101)"]
    C -->|"M1, M18, A616"| D3[National Highways]
    C -->|Car park or private road| D4[Landowner]
    C -->|"Other council service<br>(street light, fly-tipping)"| D5[Council phone or website]
    D1 & D2 & D3 & D4 & D5 --> R["Tell the resident who to contact. Stop."]

    C -->|Pothole, road or pavement defect| P["Pothole form<br>surface and depth vs the form's limit<br>(road 40 mm, pavement 20 mm)"]
    C -->|Street tree| T["Tree form<br>where it is, the problem, is it blocking?"]
    T -.->|"Fallen or blocking"| U0["Phone the council now"]
    T -->|"Park, housing or private tree"| R2["Redirect. Stop."]

    P --> DUP
    T -->|Highway tree| DUP["Duplicate check<br>same kind of problem within 60 m in 30 days?<br>tell the resident, file anyway"]
    DUP --> F["File the report<br>chat mode: tool files it directly<br>form mode: agent fills in the web form in a browser<br>location geocoded to lat/lon"]
    F --> TR["Triage: P1 to P4<br>rules (depth, blocking, keywords)<br>+ local LLM facts (was anyone hurt?)<br>+ context (A road, repeat reports)"]
    TR --> E{P1 Emergency?}
    E -->|Yes| U["Phone the council now on 0114 273 4567, or 999"]
    E -->|No| REP
    U --> REP["Reply to the resident<br>reference, who deals with it, priority, report link"]
    REP --> DASH["Council dashboard<br>duplicates grouped on the map, queue sorted by priority,<br>a group rises as more people report it"]
```

## Getting started

Python, FastAPI and a Gradio chat UI calling the organisers' Ollama on the DGX Spark. Run it locally:

```bash
uv sync
uv run pytest
ssh -N -L 11434:127.0.0.1:11434 <user>@<spark> &    # tunnel to Ollama
uv run uvicorn app.main:app --app-dir src --reload   # http://127.0.0.1:8000
```

Settings, the deployed app and checks are in [`docs/getting-started.md`](docs/getting-started.md).

The live submissions dashboard is at `/dashboard` (<http://spark12.local/dashboard> on the Spark). It shows what the agents have submitted to the mock council forms and refreshes every 5 seconds. See [Submissions dashboard](docs/getting-started.md#submissions-dashboard).

## Documentation

| Doc | Contents |
|---|---|
| [`docs/challenge.md`](docs/challenge.md) | Hackathon brief, tracks and judging criteria |
| [`docs/getting-started.md`](docs/getting-started.md) | Stack, code map, local run, settings, checking the deployed app |
| [`docs/browser-agent.md`](docs/browser-agent.md) | The browser agent at `/browser`: fills in forms by reading the page and clicking |
| [`docs/deployment.md`](docs/deployment.md) | Self-hosted runner, `deploy.sh`, Caddy on ports 80 and 443 |
| [`docs/smoke-test.md`](docs/smoke-test.md) | GPU and Ollama smoke test |
| [`docs/spark-ollama.md`](docs/spark-ollama.md) | The organisers' shared Ollama on the Spark |
| [`docs/data-sources.md`](docs/data-sources.md) | Public datasets and provenance |
| [`docs/sheffield-council-services.md`](docs/sheffield-council-services.md) | Routing rules for the agent |
| [`docs/triage.md`](docs/triage.md) | Automatic triage: priority scale, rules, LLM role, evaluation, demo seed |

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

## Team

Team name: **Dependency Hell's Angels**

_Add team members here._

## Licence

Released under the [MIT License](LICENSE).
