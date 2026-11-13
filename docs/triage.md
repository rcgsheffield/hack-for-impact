# Automatic triage

Every report, from the chat agent, the form agents or a browser, gets a suggested **priority**, plain-English **reasons** and a **response target**, so council staff work from a sorted queue instead of triaging by hand (epic #31). It is always a suggestion: the council sets the category after inspection.

| Priority | Meaning | Council equivalent | Response target |
|---|---|---|---|
| **P1 Emergency** | Immediate risk to people | Category 1 | Made safe within 24 hours; resident told to phone |
| **P2 High** | Likely to become dangerous, busy location or repeat reports | Category 1 or 2, inspector's call | Inspected within a few days |
| **P3 Routine** | No immediate risk | Category 2 | Fixed through planned maintenance |
| **P4 Low** | Nuisance, or not the council's job | none | Redirected or monitored |

## How it works

```
report ─▶ triage.triage(item, signals) ◀── rules: form fields and keywords (triage.py)
                       ▲
                       └── signals, combined by triage.combine_signals():
                             local LLM: hazards in the resident's words (triage_llm.py)
                             map context: road class and repeat reports (triage_context.py)
      ├─▶ stored on the record at filing, re-worked when signals arrive (submissions.load_submissions)
      ├─▶ staff: priority-sorted queue with reasons on /dashboard
      └─▶ resident: priority in the agent's reply and on /reports/{ref}; phone advice for P1 (urgency.py)
```

A report starts at 30 points (P3). Each finding adds points; bands are P1 ≥ 70, P2 ≥ 50, P3 ≥ 25, else P4. **Only an immediate hazard can make P1**: without one the score stops at 69 (top of P2), so children, a bus route and an A road together make a shallow defect High, not Emergency. This is the council's own Category 1 test ("immediate safety risk").

**The rules decide the priority; signals only add findings.** Triage stays deterministic and testable, and works when the shared Ollama is slow or down. The `engine` field says what contributed: `rules`, `rules+llm`, `rules+context` or `rules+llm+context`.

## Rules and their sources

| Finding | Points | Hazard (can make P1) | Source |
|---|---|---|---|
| Road pothole deeper than 40mm, pavement deeper than 20mm | 45 | yes | Council form depth options (`src/mock/report_pothole_crack.html`); Category 1 in `docs/sheffield-council-services.md` |
| Depth not given | 0 | | Flagged for review |
| Tree or branch fallen; tree touching cables; dangerous tree blocking the way | 50 | yes | Tree form (`src/mock/report_tree.html`) says to phone instead |
| Dangerous tree; obstruction blocking the way | 25 | | Tree form |
| Tree in a park, housing or private land; nuisance; cables | redirect → P4 | | Tree form redirects these (unless already P1) |
| Words: someone hurt (fell off, tripped, ambulance…) | 30 | yes | "risk to drivers/cyclists/pedestrians" |
| Words: exposed wires, gas | 40 | yes | |
| Words: blocking road or pavement | 20 | | |
| Words: needles, sharps, asbestos | 20 | | |
| Words: reported before, still not fixed | 20 | | Replaced by the counted cluster when there is one |
| Words: children, wheelchair, pushchair, elderly… | 15 | | Vulnerable users |
| Words: cyclist, motorbike | 15 | | "risk to cyclists" |
| Words: busy road, bus route, swerving | 15 | | "road usage" |
| Words: flooding | 15 | | |
| A road (OSM trunk/primary) / B road (secondary) | 20 / 15 | | Inspection cadence: A/B roads monthly, residential yearly |
| Link road / cycle path / footpath | 5 / 10 / 5 | | |
| Same problem reported again within 25 m and 30 days | 10 per repeat, max 30 | | "Reported 3 times in 8 days" |

All weights are named constants in `src/app/triage.py`, `triage_context.py` and `triage_llm.py`.

## What the local LLM may and may not do

Nemotron on the organisers' Ollama reads the resident's free text after filing (a background thread, so nobody waits; 20 s timeout; cached by reference in `data/triage_signals.jsonl`). It returns structured JSON (Ollama `format` schema, temperature 0): injury reported, vulnerable users, blocking, traffic exposure, a short hazard summary and a confidence.

- **May** add findings the keyword rules miss, such as "went over the handlebars". Each fact maps to the same fixed points as the matching keyword rule, and the reason says "(read by local AI)".
- **May not** set a priority, choose points (anything it sends is ignored), or count a hazard a keyword rule already found. Readings with confidence under 0.5 are dropped. Only a reported injury counts as a hazard.
- On any failure (timeout, bad JSON, Ollama down) triage falls back to rules only.

## Telling the resident

Filing results carry the priority in plain words ("Emergency: made safe within 24 hours") and, for P1, the urgent advice: phone the council on 0114 273 4567, or 999 if anyone is in danger. Before filing, every message is checked deterministically (`urgency.triage_text`); a P1 makes the agent open with the phone advice, and a backstop appends it if the model's reply leaves it out. Residents never see scores or the engine.

## Evaluation

31 labelled cases in `tests/data/triage_cases.jsonl`: hand-written edge cases (borderline depths, private land, the M1, nuisance trees, injury mentioned in passing) and anonymised FixMyStreet samples. `tests/test_triage_eval.py` requires the `must_pass` cases and zero P1 under-triage. Reproduce:

```bash
PYTHONPATH=src uv run python -m app.triage_eval          # rules only
PYTHONPATH=src uv run python -m app.triage_eval --llm    # rules + local LLM (on the Spark)
```

#### Rules only

Agreement 30/31 (97%); over-triage 0; under-triage 1; P1 cases triaged lower: 0

| expected \ got | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| P1 | 10 | 0 | 0 | 0 |
| P2 | 0 | 6 | 0 | 0 |
| P3 | 0 | 0 | 9 | 1 |
| P4 | 0 | 0 | 0 | 5 |

Misses:
- `fms-flytip-pavement`: expected P3, got P4 (Partly in the road: should be routine, not redirected (known gap: rules redirect it); reasons: Not a council highway problem: redirected)

Rules + local LLM: not yet measured. Ollama isn't reachable off the Spark; run the `--llm` command there and paste the result here.

## Demo seed

```bash
PYTHONPATH=src uv run python -m app.demo_seed --reset
```

Files 11 reports through the real filing code: 2× P1 (fallen tree across Rustlings Road; deep pothole on Ecclesall Road a cyclist came off), 5× P2 (including a pothole reported 3 times in 8 days on Sharrow Vale Road), 3× P3 and a P4 redirect. `--reset` removes only seeded reports.

## Known limitations

- Fly-tipping partly in the road is redirected (P4) rather than routine (P3), the one miss in the labelled set.
- Keyword rules are English-only and miss phrasing they don't list; the LLM covers some of this when Ollama is up.
- Road class needs a Photon match on a street. Reports placed by device location or the offline sample geocoder get no road-class points.
- Repeat clusters are recomputed on every dashboard read from all reports; fine for a demo, not for a city's volume.
- The labelled set is small and written by the team. It shows the rules do what we intended, not that they match inspectors' decisions.
