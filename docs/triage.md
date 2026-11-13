# Automatic triage

Every report, from the chat agent, the form agents or a browser, gets a suggested **priority**, plain-English **reasons** and a **response target**, so council staff work from a sorted queue instead of triaging by hand (epic #31). It is always a suggestion: the council sets the category after inspection.

| Priority | Meaning | Council equivalent | Response target |
|---|---|---|---|
| **P1 Emergency** | Immediate risk to people | Category 1 | Made safe within 24 hours; resident told to phone |
| **P2 High** | Likely to become dangerous, busy location or repeat reports | Category 1 or 2, inspector's call | Inspected within a few days |
| **P3 Routine** | No immediate risk | Category 2 | Fixed through planned maintenance |
| **P4 Low** | Nuisance, or not the council's job | none | Redirected or monitored |

## How it works

Each service's triage is **data**: a rubric (`src/app/triage_rubric.py`), a small decision tree of typed questions ("nodes"). Each option of a node has a fixed outcome: points, a reason for staff, whether it is an immediate hazard, and whether it means the problem isn't the council's. **Deciders** answer the questions, in order of trust (`src/app/triage_deciders.py`):

```
report ─▶ rubric for the form (pothole, tree, or generic text questions for any other service)
            │
            ├─ 1. form fields      p = 1.0   what the resident picked on the council form
            ├─ 2. keyword rules    p = 1.0   regexes over the resident's words
            └─ 3. a model          p from the model, only for nodes 1–2 left at "nothing found"
                    local LLM on Ollama (default)  |  System One model, e.g. Jev (optional, off)
            │
            ▼
         score = 30 + points of every answer + map context (road class, repeat reports)
            ├─▶ stored on the record at filing, re-worked when signals arrive (submissions.load_submissions)
            ├─▶ staff: priority-sorted queue with reasons on /dashboard
            └─▶ resident: priority in the agent's reply and on /reports/{ref}; phone advice for P1 (urgency.py)
```

Bands are P1 ≥ 70, P2 ≥ 50, P3 ≥ 25, else P4. **Only an immediate hazard can make P1**: without one the score stops at 69 (top of P2), so children, a bus route and an A road together make a shallow defect High, not Emergency. This is the council's own Category 1 test ("immediate safety risk").

**The rubric decides the points; deciders only pick options.** Triage stays deterministic and testable, and works when no model is reachable. The `engine` field names what changed the result: `rules`, `rules+llm`, `rules+jev`, `rules+context`, `rules+llm+context`… `triage.explain()` returns the same result plus the rubric used and every decision (`{node, option, p, source}`), so any priority can be traced to who answered what.

Some nodes only apply after earlier answers. For example, the tree problem isn't asked for park, housing or private trees, because the form redirects those first. The tree stays explicit and cheap to query: a model is asked only one batch of typed questions per report.

## Criteria basis

Scoring follows the risk-based approach of the national Code of Practice *Well-managed Highway Infrastructure* (UK Roads Liaison Group, 2016), which highway authorities use to set defect categories: **risk = impact × likelihood**. Every node has an axis:

| Axis | Question it answers | Nodes |
|---|---|---|
| **routing** | Is it the council's job? A redirect gives P4 unless a hazard keeps it P1 | tree location; tree nuisance or cables; `can_file = false` from the agent (private land, National Highways) |
| **severity** (impact) | What is it? `hazard` options are Category 1 | defect depth; tree problem; injury; exposed wires or gas; sharps or asbestos; flooding |
| **exposure** (likelihood) | Who meets it, and how often? | blocking; vulnerable users; cyclists; busy road or bus route; reported before; road class and repeat reports (map context) |

## Rules and their sources

| Finding | Node (axis) | Points | Hazard (can make P1) | Source |
|---|---|---|---|---|
| Road pothole deeper than 40mm, pavement deeper than 20mm | `defect_depth` (severity) | 45 | yes | Council form depth options (`src/mock/report_pothole_crack.html`); Category 1 in `docs/sheffield-council-services.md` |
| Depth not given | `defect_depth` | 0 | | Flagged for review |
| Tree or branch fallen; tree touching cables; dangerous tree blocking the way | `tree_problem` (severity) | 50 | yes | Tree form (`src/mock/report_tree.html`) says to phone instead |
| Dangerous tree; obstruction blocking the way | `tree_problem` | 25 | | Tree form |
| Tree in a park, housing or private land; nuisance; cables | `tree_location`, `tree_problem` (routing) | redirect → P4 | | Tree form redirects these (unless already P1) |
| Someone hurt (fell off, tripped, ambulance…) | `injury` (severity) | 30 | yes | "risk to drivers/cyclists/pedestrians" |
| Exposed wires, gas | `wires_gas` (severity) | 40 | yes | |
| Blocking road or pavement | `blocking` (exposure) | 20 | | |
| Needles, sharps, asbestos | `sharps` (severity) | 20 | | |
| Reported before, still not fixed | `reported_before` (exposure) | 20 | | Replaced by the counted cluster when there is one |
| Children, wheelchair, pushchair, elderly… | `vulnerable` (exposure) | 15 | | Vulnerable users |
| Cyclist, motorbike | `cyclists` (exposure) | 15 | | "risk to cyclists" |
| Busy road, bus route, swerving | `traffic` (exposure) | 15 | | "road usage" |
| Flooding | `flooding` (severity) | 15 | | |
| A road (OSM trunk/primary) / B road (secondary) | map context (exposure) | 20 / 15 | | Inspection cadence: A/B roads monthly, residential yearly |
| Link road / cycle path / footpath | map context | 5 / 10 / 5 | | |
| Same problem reported again (`dedup.py` group: same kind within 60 m and 30 days) | map context | 10 per repeat, max 30 | | "Reported 3 times in 8 days"; the same groups the dashboard and residents see |

Points, reasons and patterns live in `src/app/triage_rubric.py`; map context weights in `triage_context.py`; bands in `triage.py`. The rubric refactor kept every weight, so the labelled set gives exactly the same results as before.

## What a model may and may not do

A model reads the resident's free text after filing (a background thread, so nobody waits; cached by reference in `data/triage_signals.jsonl`). It is asked the report's rubric questions: the JSON schema and prompt are **generated from the rubric**, so adding a node adds a question with no other code.

- **May** fill a node the form and keywords left at "nothing found", such as an injury in "went over the handlebars", or the depth when the form didn't give one. The points are the rubric's, and the reason says "(read by local AI)" or "(read by Jev)".
- **May not** set a priority, choose points (anything it sends is ignored), or override or remove a form or keyword answer. Answers with p under 0.5 are not scored.
- **Unsure hazards are shown, not scored.** If a model gives a hazard option 30–50% (or, for System One models, puts that much probability on hazard options), staff see "Possible: Someone has been hurt (read by Jev, 35%): needs review" with no points. Missing a real P1 costs more than an extra look.
- On any failure (timeout, bad JSON, service down) triage falls back to the rules. Signals cached before the rubric refactor still apply.

### Backends (`TRIAGE_DECIDER`)

| | `ollama` (default) | `jev` (optional) |
|---|---|---|
| Model | Nemotron on the organisers' Ollama | TypeSafe Jev, a System One model (`api.typesafe.ai/v1/systemone`) |
| Where | Local (DGX Spark) | Hosted in the US |
| Output | JSON constrained by the generated schema; p is self-reported | One Choice question per node with calibrated `probabilities` over every option |
| Latency | Seconds (20 s timeout) | 70–500 ms claimed (2 s timeout) |
| Data sent | Report text | Report text only, with emails, phone numbers and postcodes removed |

System One models are built for exactly this shape: typed decisions (choice, score, yes/no) over a fixed option set, answered in parallel in one call, with probabilities instead of free text. Each rubric node maps one-to-one to a Jev Choice question (options become `criteria`, at most 255), so swapping backends needs no rubric changes. Jev stays **off by default**: local compute is a judging criterion, and resident reports are personal data that shouldn't leave the UK without a data-processing agreement. To try it: `TRIAGE_DECIDER=jev JEV_API_KEY=… PYTHONPATH=src uv run python -m app.triage_eval --decider jev`. The adapter (`src/app/triage_jev.py`) follows the published OpenAPI schema and is unit-tested with mocked HTTP, but hasn't been run against the live service yet.

If it is adopted, Jev is fast enough to run **at filing** rather than in the background, so the resident's reply would already include the model's reading. That is the next step after the eval shows it is worth it.

## Adding a service

1. Write its nodes in `src/app/triage_rubric.py`: a question, options with a description each (the model reads these), fixed `Outcome`s, and `from_fields` for the form's own answers. Reuse `TEXT_NODES` for the resident's words.
2. Add the `Rubric` to `RUBRICS` under the form name. Until then, any other form uses the generic text questions.
3. Add labelled cases to `tests/data/triage_cases.jsonl`, then run `pytest tests/test_triage_rubric.py` (`validate()` checks every rubric) and the eval.

Two worked examples. These are proposals with sources, **not yet in code**:

**Fly-tipping** (`report_fly_tipping`). Size bands are the national Flycapture categories councils already report to Defra.

| Node (axis) | Options → outcome |
|---|---|
| `land` (routing) | highway, verge or public right of way → council; private land → redirect (owner pays, Environmental Services 0114 203 7411); partly in the road → council (fixes today's one miss) |
| `waste_type` (severity) | asbestos, chemicals, drums, gas cylinders, clinical/sharps → 25 (hazardous: removal by specialists); household, green, white goods, tyres → 0 |
| `size` (severity) | single bag or item → 0; car boot or less → 5; small van → 10; transit van → 15; tipper lorry or multiple loads → 20 |
| `blocking` (exposure) | shared text node: blocking the road or pavement → 20; in the carriageway with traffic → hazard |
| `evidence` | names, addresses or plates in the waste → no points; a flag for enforcement |

**Street lighting** (`report_street_light`).

| Node (axis) | Options → outcome |
|---|---|
| `electrical` (severity) | exposed wiring, door missing on the column, column knocked down or leaning → 45, hazard (emergency) |
| `lights_out` (exposure) | one light → 0; three or more in a row, or one at a junction or crossing → 25; day-burning → redirect-style P4 (wasted energy, not a risk) |
| `attachment` (routing/severity) | offensive flag or banner → 25 (the council aims to remove within 24 hours); other unauthorised attachment → 0 |
| `monitored` (routing) | LED columns are centrally monitored, so a single LED outage may already be known: a note for staff, no points |

## Telling the resident

Filing results carry the priority in plain words ("Emergency: made safe within 24 hours") and, for P1, the urgent advice: phone the council on 0114 273 4567, or 999 if anyone is in danger. Before filing, every message is checked deterministically (`urgency.triage_text`); a P1 makes the agent open with the phone advice, and a backstop appends it if the model's reply leaves it out. Residents never see scores or the engine.

## Evaluation

31 labelled cases in `tests/data/triage_cases.jsonl`: hand-written edge cases (borderline depths, private land, the M1, nuisance trees, injury mentioned in passing) and anonymised FixMyStreet samples. `tests/test_triage_eval.py` requires the `must_pass` cases and zero P1 under-triage. Reproduce:

```bash
PYTHONPATH=src uv run python -m app.triage_eval          # rules only
PYTHONPATH=src uv run python -m app.triage_eval --decider llm   # rules + local LLM (on the Spark)
```

#### Rules only

Agreement 30/31 (97%); over-triage 0; under-triage 1; P1 cases triaged lower: 0

| expected \ got | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| P1 | 10 | 0 | 0 | 0 |
| P2 | 0 | 6 | 0 | 0 |
| P3 | 0 | 0 | 9 | 1 |
| P4 | 0 | 0 | 0 | 5 |

Answered by: form 38, keyword 13

Misses:
- `fms-flytip-pavement`: expected P3, got P4 (Partly in the road: should be routine, not redirected (known gap: rules redirect it); reasons: Not a council highway problem: redirected)

Rules + local LLM: not yet measured since the rubric refactor. Ollama isn't reachable off the Spark; run the `--decider llm` command there and paste the result here, including the model-p table (a rough check of whether the model's p means anything on our cases).

## Demo seed

```bash
PYTHONPATH=src uv run python -m app.demo_seed --reset
```

Files 11 reports through the real filing code: 2× P1 (fallen tree across Rustlings Road; deep pothole on Ecclesall Road a cyclist came off), 5× P2 (including a pothole reported 3 times in 8 days on Sharrow Vale Road), 3× P3 and a P4 redirect. `--reset` removes only seeded reports.

## Known limitations

- Fly-tipping partly in the road is redirected (P4) rather than routine (P3), the one miss in the labelled set.
- Keyword rules are English-only and miss phrasing they don't list; the model covers some of this when Ollama is up.
- A general LLM's p is self-reported, not calibrated; the review band (30–50%) assumes it means something. Check the model-p table before trusting it.
- Road class needs a Photon match on a street. Reports placed by device location or the offline sample geocoder get no road-class points.
- Repeat groups are recomputed on every dashboard read from all reports; fine for a demo, not for a city's volume.
- The labelled set is small and written by the team. It shows the rules do what we intended, not that they match inspectors' decisions.
