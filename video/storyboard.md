# Pitch video storyboard

Target: under 5 minutes, 1920x1080, rendered with HyperFrames. `tools/retime.py` sets every scene's start and length from the real voiceover clips, so the times below are approximate.

The story has to prove two points to the judges. First, **this problem needs an agent, not a single prompt**: reporting a problem means working out who owns it, what information they need and which form it goes into (scenes 06–07). Second, **this isn't another council chatbot**: the value is the back-office work (routing, de-duplication, triage, filling in the council's own forms) on hardware the council owns, interoperable through Open311 (scenes 08–11).

| # | Scene file | ≈ Time | Visual | Voiceover (IDs in `script/voiceover.md`) | Audio |
|---|-----------|------|--------|------------------------------------------|-------|
| 01 | `irene-phone.html` | 0:00–0:21 | Irene at her window, a pothole outside her gate. She picks up the phone; a hold screen shows "You are number 14 in the queue". | `01a`, `01b` (Irene), `01c` (handler) | Music: sombre intro. |
| 02 | `form-x.html` | 0:21–0:36 | The handler says "form X". A long, dense web form scrolls past ("road or pavement?", "depth in mm?", "who owns this road?"). | `02a` (handler), `02b` (Irene) | |
| 03 | `council-inbox.html` | 0:36–0:50 | A council worker; the inbox counter climbs; email cards tagged "no location", "no depth", "M1: not ours". | `03a`, `03b` (worker) | |
| 04 | `another-way.html` | 0:50–0:54 | Record scratch. **IF ONLY THERE WAS ANOTHER WAY…** | `04` | Music cuts, upbeat track starts. |
| 05 | `intro.html` | 0:54–1:15 | Title card **CouncilTriagent**: "Report it in your own words. We'll do the paperwork." Badges: "Routes · de-duplicates · prioritises · files", "Runs locally on NVIDIA DGX Spark". | `05` | Music: upbeat. |
| 06 | `chat.html` | 1:15–1:58 | Mock-up of the real chat. Irene reports the pothole; the agent asks the depth; `route_report`, `assess_pothole` and `file_report` chips; the reply carries the reference and a **P1 Emergency** badge with the phone advice. | `06a`, `06b` (Irene), `06c` (agent), `06d` (Irene), `06f` (agent), `06g` | |
| 07 | `browser-agent.html` | 1:58–2:19 | Split screen: chat on the left, a browser on the right where the agent fills in the council's form field by field (`read_page`, `click`, `type_text`, `select_option`), recovers from a validation error and waits for "yes" before submitting. | `07` | |
| 08 | `council-view.html` | 2:19–2:41 | The council dashboard: queue sorted P1→P4 with plain-English reasons; three pins on the map merge into one "×3" group, which rises in the queue. | `08` (worker), `08b` | |
| 09 | `usp.html` | 2:41–3:01 | "Not another chatbot": a typical council chatbot vs CouncilTriagent, ticked off point by point. | `09` | |
| 10 | `agent-flow.html` | 3:01–3:28 | Architecture inside the DGX Spark boundary, "Cloud APIs" struck through, data never leaves the machine; Open311 interoperability strip. | `10` | Music: tech. |
| 11 | `data-workflow.html` | 3:28–3:52 | Simplified version of the README "How it works" flowchart: describe → who owns it? → duplicates → file → triage → dashboard. | `11` | |
| 12 | `models.html` | 3:52–4:19 | Three model cards (Nemotron 3.5 Lightning chosen, Qwen 3.6 fallback, Nemotron Nano smoke tests): qualitative comparison only. | `12` | |
| 13 | `business.html` | 4:19–4:46 | Open source + services business model; next steps roadmap. | `13` | |
| 14 | `close.html` | 4:46–4:58 | Irene smiles at the fixed road. **CouncilTriagent**, team, track, repo. | `14` | Music resolves. |

## Notes

- Keep the characters simple: flat illustrations or emoji-style avatars built in HTML/CSS, not stock photos.
- The demo (scenes 06–07) is an animated mock-up, but it must match what the real app does. Run the app once with Irene's messages and check the chips and reply in scene 06 against it. If the model's replies differ, adjust the agent lines in `script/voiceover.md`.
- Only claim what is built. Reports are recorded locally, not sent to the council; the browser agent is tested on copies of Sheffield's forms (`src/mock/`); Open311 is used to read FixMyStreet data, and sending reports over Open311 is a next step. The model comparison (scene 12) is qualitative: no benchmarks were run.
- Scenes 07 and 10–12 are where the "technical execution" criterion is scored: show the agentic steps, the open models and the local compute explicitly.
- Team name for scene 14: Dependency Hell's Angels.
