# Pitch video storyboard

Target: about 75 seconds, 1920x1080, rendered with HyperFrames. Timings are a first guess; adjust them once the voiceover is recorded (the VO length sets the pace).

The story has to prove one point to the judges: **this problem needs an agent, not a single prompt.** Reporting a problem to the council means working out which service owns it, what information they need, which form or system it goes into, and following up. Scene 06 is where we show that.

| # | Scene file | Time | Visual | Voiceover (ID in `script/voiceover.md`) | Audio |
|---|-----------|------|--------|------------------------------------------|-------|
| 01 | `irene-phone.html` | 0–10 s | Irene at home, unhappy, looking at a pothole in her street. She picks up the phone. | `s1` | Music: sombre intro. SFX: phone ringing, hold music. |
| 02 | `form-x.html` | 10–20 s | Phone call ends: "Please fill in form X." A long, dense web form scrolls past; fields multiply; Irene's face drops. | `s2` | SFX: keyboard, error beep. |
| 03 | `council-inbox.html` | 20–30 s | Council worker at a desk. Inbox counter climbs (12 → 340 → 1,204). Email cards pile up and overflow the screen. | `s3` | SFX: rapid email pings speeding up. |
| 04 | `another-way.html` | 30–34 s | Freeze, record scratch, screen goes dark. Big type: **IF ONLY THERE WAS ANOTHER WAY…** | `s4` | Music cuts out, then the upbeat track starts. |
| 05 | `chat.html` | 34–50 s | A chat window slides in. Irene types her problem in plain words (and attaches a photo). The agent replies, asks one clarifying question, then confirms the report is filed with a reference number. | `s5` | Music: upbeat. SFX: soft typing, message pops. |
| 06 | `agent-flow.html` | 50–68 s | Animated infographic of the agent flow. Each step lights up in turn: understand the report → classify and route to the right service → check open data / duplicates → fill in the council's form or system → notify Irene and track progress. Badge: "Running locally on NVIDIA DGX Spark." **Fill in the real steps once the architecture is settled.** | `s6` | Music continues. |
| 07 | `close.html` | 68–75 s | Council worker now sees a tidy, triaged queue; Irene smiles. Title card: **CouncilTriagent**, team, track (Public Services), repo URL. | `s7` | Music resolves. |

## Notes

- Keep the characters simple: flat illustrations or emoji-style avatars built in HTML/CSS, not stock photos.
- Use screenshots or a screen recording of the real app in scene 05 if it is ready in time (put them in `composition/assets/images/`). Otherwise build the chat window in HTML.
- Scene 06 is the one the judges' "technical execution" criterion rests on: make the agentic steps and the local compute explicit.
