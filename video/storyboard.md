# Pitch video storyboard

Target: about 4:30 (under 5 minutes), 1920x1080, rendered with HyperFrames. Timings are estimates at about 150 words per minute; adjust them once the voiceover is recorded (the VO length sets the pace). Structure follows `../hackathon-video-guide.md` section 3: problem, what we built, demo, how it works, impact, close.

The story has to prove one point to the judges: **this problem needs an agent, not a single prompt.** Reporting a problem to the council means working out who owns it, what information they need and which form it goes into. Scenes 06–07 show the agent doing that; scenes 09–10 show how.

| # | Scene file | Time | Visual | Voiceover (IDs in `script/voiceover.md`) | Audio |
|---|-----------|------|--------|------------------------------------------|-------|
| 01 | `irene-phone.html` | 0:00–0:15 | Irene at her window, a pothole outside her gate. She picks up the phone; a hold screen shows "You are number 14 in the queue". | `01a`, `01b` (Irene), `01c` (handler) | Music: sombre intro. SFX: phone ringing, hold music. |
| 02 | `form-x.html` | 0:15–0:35 | The handler says "form X". A long, dense web form scrolls past, with questions like "road or pavement?", "depth in mm?" and "who owns the road?". Fields multiply and Irene's face drops. | `02a` (handler), `02b` (Irene), `02c` | SFX: keyboard, error beep. |
| 03 | `council-inbox.html` | 0:35–0:50 | A council worker at a desk. The inbox counter climbs (12 → 340 → 1,204). Email cards pile up, tagged "no location", "no depth" and "M1: not ours". | `03a`, `03b` (worker) | SFX: email pings, speeding up. |
| 04 | `another-way.html` | 0:50–0:54 | Freeze, record scratch, the screen goes dark. Big type: **IF ONLY THERE WAS ANOTHER WAY…** | `04` | Music cuts out, then the upbeat track starts. |
| 05 | `intro.html` (new) | 0:54–1:08 | Title card: **CouncilTriagent**, "Report it in your own words. We'll get it to the right place." Track badge: Public Services. Badge: "Runs locally on NVIDIA DGX Spark". | `05` | Music: upbeat. |
| 06 | `chat.html` | 1:08–2:05 | An animated mock-up of the real Gradio chat. Irene types her message; the agent asks one clarifying question (depth); small "🔧 route_report" and "🔧 assess_pothole" chips flash. The agent confirms with reference **SCC-20261113-A1B2** and an "Urgent: Category 1" badge. On-screen text matches the spoken lines. | `06a`, `06b` (Irene), `06c` (agent), `06d` (Irene), `06e`, `06f` (agent), `06g` | SFX: soft typing, message pops, a "filed" chime. |
| 07 | `chat-routing.html` (new) | 2:05–2:30 | The same chat. Irene reports the Stocksbridge Bypass; a "🔧 route_report" chip flashes to **National Highways**. The agent explains it can't file this one and points her to National Highways. | `07a`, `07b` (Irene), `07c` (agent) | Music continues. |
| 08 | `council-view.html` (new) | 2:30–2:45 | The "after" to scene 03: the worker sees a tidy queue. One report card is open, with its form fields filled (location, surface, depth 100 mm, priority Cat 1, reference). The worker relaxes. | `08` (worker) | Music lifts. |
| 09 | `agent-flow.html` | 2:45–3:15 | Architecture diagram, built up step by step: resident → chat UI (Gradio + FastAPI) → **NVIDIA Nemotron** on Ollama → three tools → council-ready record. A box around the model and app is labelled "NVIDIA DGX Spark: no cloud APIs". | `09` | Music continues, quieter under the narration. |
| 10 | `tool-trace.html` (new) | 3:15–3:50 | Animated tool trace: "🔧 tool" bubbles open one at a time, showing the real arguments and results for `route_report`, `assess_pothole` and `file_report` (copied from a real run of the app). Brief callout: "error → back to the model → retry". | `10` | SFX: subtle ticks as each bubble opens. |
| 11 | `impact.html` (new) | 3:50–4:15 | Two columns, **Residents** and **Council**, with three benefits each. Then a strip with "Today: road and pavement defects, reports recorded locally" and "Next: council case system, more services, FixMyStreet duplicate detection, NVIDIA NIM". | `11` | Music builds. |
| 12 | `close.html` | 4:15–4:30 | Irene smiles at the fixed road. Title card: **CouncilTriagent**, team names, track (Public Services), repo URL. | `12` | Music resolves. |

## Notes

- Keep the characters simple: flat illustrations or emoji-style avatars built in HTML/CSS, not stock photos.
- The demo (scenes 06–07) is an animated mock-up, but it must match what the real app does. Run the app once with Irene's messages and copy the real tool arguments and results into scene 10. If the model's replies differ, adjust the agent lines in `script/voiceover.md`.
- Only claim what is built. The agent does not yet read open data or submit reports to the council; scene 11 says so.
- Scenes 09–10 are where the "technical execution" criterion is scored: show the agentic steps, the open model and the local compute explicitly.
- Team names for scene 12 come from the Team section of the top-level `README.md` (still to be filled in).
