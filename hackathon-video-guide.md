# Hack for Impact: five-minute demo video guide

A synthesis of advice from hackathon organisers, judges and demo-video practitioners, adapted for our submission. Sources are listed at the end. Where a point is our own inference rather than something the sources say, it is marked **(our inference)**.

## 1. The short version

1. **Proof first, polish second.** Judges score the product and the pitch, not the editing. A clear narrative with a working demo beats a slick video of something half-finished.
2. **Open with the problem, not the technology.** Make the judges feel the problem before you show anything.
3. **Show one flow, end to end, that actually works.** Cut features rather than rush.
4. **Show a working result early** (about 90 seconds in, at the latest).
5. **Script it, time it, rehearse it out loud.** Then record.
6. **Finish recording and uploading with hours to spare.** Check that the judges can actually open the link.

## 2. What the advice says

### Judges want the product, not the production

- Production quality does not affect the score; judges look for impressive working demos and innovative solutions.
- A typical judging checklist: does it work, would real people use it, is the interface intuitive, is the technology interesting, can it scale. Code quality and lines of code are not on it.
- A strong project with a confusing demo loses to a simpler project that the judges understand.
- Hackathon judges care less about the future of the project than about what you built and why you built it that way. This is not an investment pitch, so do not ask for money.

### The problem comes first

- Open with the problem and make the judges feel it before showing a solution. Skipping the problem statement because the tech feels self-explanatory is a common mistake.
- Be insanely specific about who has the problem. A good test: the viewer thinks "that's my problem" before they think "that's your product".
- Build the whole video around one main takeaway, usually the problem and how you solve it.
- Frame things in terms of the viewer ("you") rather than what you built.

### Show it working

- Show a working result within roughly 90 seconds.
- Focus on one clear flow that works end to end, rather than several half-finished features. Do not demo half-built features or talk around ones that do not exist.
- Contrast the old, frustrating process with the new one, to give the "this is now possible" moment.
- Walk the judges through the experience as if they were the user.
- Use realistic test data, not placeholder text. Showing what happens when a user makes a mistake is a plus.
- Be honest about what works, what does not and how it could be extended. Honesty reads as confidence.
- Keep the code editor and terminal out of the demo; one source calls them debugging, not presenting. The exception is a separate "how it works" section if the brief asks for one (see section 3).

### Pace and length

- Five minutes is more generous than the usual slot. Most demos run two to five minutes, with three the most common, so this is a ceiling, not a target.
- Introduce the project in the first few seconds. Do not cram in too much information, and do not speed up the audio to fit the time limit.
- If the demo is too long, cut features rather than rush.
- Cut dead time by pre-loading or caching slow steps (agent responses, long queries, builds) without breaking the flow.
- Hold the "how it works" for later. One source suggests ending with a link to a post or video explaining how it was built.

### Delivery

- Write the script yourself; generic AI-generated text may not capture your project. Write for the ear and do not simply read it out: reading from a script shows.
- Rehearse out loud at least once and time the whole thing. Teams that practised look like it.
- Speak slowly and clearly. Do not open with "Hi judges, my name is…", and do not end with "and… yeah, that's it".
- Enthusiasm does more work than people expect.
- Judges may see 30 or more presentations. What they remember is rarely the most polished one; it is the one that was fun and memorable.

### Technical quality

- Judges must be able to see, hear and access the video. Use the best microphone on the team, and record in a quiet space.
- Audio matters more than people expect: poor audio is a key reason viewers stop watching. Monitor levels as you record, keeping them in the green to light orange range.
- Record a short sample first and play it back.
- Zoom in on what matters so text is readable. Silence notifications, close irrelevant tabs, and bookmark URLs so nothing is typed live.
- Use tools you already know (OBS Studio, PowerPoint, Google Slides). Do not learn a new editor during the event.
- Upload early. Upload time varies from minutes to hours. On YouTube you can get the link before the upload finishes. Check privacy settings, and on YouTube mark the video "not made for kids" so judges can view it; "unlisted" is a sensible choice.
- Also record a backup video of the live demo, in case something breaks on the day.

## 3. A suggested structure for our five minutes

Adapted from the timed three-minute structure in the sources, stretched to fit five minutes. Treat the timings as starting points and aim to finish at around 4:30, leaving headroom.

| Time | Segment | What it does |
|---|---|---|
| 0:00–0:20 | **Hook** | One concrete, human problem, ideally with one striking fact. Who is affected? Which challenge track does it fall under (Economic Systems, Public Services or Urban Operations)? |
| 0:20–0:45 | **What we built** | One sentence on what it is and who it is for. No "how" yet. |
| 0:45–3:15 | **Live demo** | The core flow, end to end, narrated as if the viewer were the user. A working result by about 1:30. Realistic data. Include one "this is now possible" before-and-after moment. |
| 3:15–4:00 | **How it works** | A single simple architecture picture. The agentic parts: what the agents do, what open models are used, and that it runs locally on the DGX Spark. **(our inference: this is where the hackathon theme earns points, so name it explicitly.)** |
| 4:00–4:30 | **Impact and what next** | Who benefits and how (time, money, access). What is working today, what is not, and what we would do next. |
| 4:30–4:50 | **Close** | Team names, project name, a clear call to action (repo, contact, QR code). Then stop talking. |

Notes on the structure:

- Keep slides to a minimum. One at the start to frame the problem and one for architecture is plenty; the rest should be the product.
- Two voices are fine, for example one person for the problem and another for the demo, as long as the handoff is smooth. One narrator is simpler and usually sounds more coherent.
- The sources disagree slightly on whether to show how it was built: some say hold it back, others (for technical-demo videos) say walk through the stack and prioritisation decisions. A short, clear "how it works" segment after the demo satisfies both.

## 4. Process and timeline

The hackathon is a single day, so the video needs protected time. Suggested plan (adjust to the actual schedule):

1. **Now:** confirm the submission requirements (see section 6). Decide the one-sentence problem and the "wow" moment.
2. **Start of build:** draft the script outline. It will shape what you build.
3. **Mid-build:** agree a feature freeze. Pick the single flow the demo will show and make sure it works reliably.
4. **At least 90 minutes before the deadline:** lock the demo path. Pre-fill data, cache slow agent steps, test the screen layout and audio.
5. **About an hour before:** rehearse once out loud with a timer. Record the screen demo and the voiceover (some people record the voiceover first, then match the screen to it).
6. **Final stretch:** cut to length, check audio, export, upload, and test the link from another account or a private window.
7. **Always:** keep a raw backup recording of the demo.

The Devpost advice is to finish recording and uploading with two to three hours to spare. On a one-day event that may not be possible, so aim to have the upload done as early as you can.

## 5. Pre-flight checklist

**Content**
- [ ] Opens with a specific problem, not our technology
- [ ] One main message that everything else supports
- [ ] Working result visible by around 1:30
- [ ] One end-to-end flow, nothing half-built on screen
- [ ] Realistic data; no real personal data
- [ ] Names the track, the open models used and local deployment on the DGX Spark
- [ ] Honest about limitations and next steps
- [ ] Clear close with team and call to action; under five minutes

**Delivery**
- [ ] Script written by us, rehearsed out loud and timed
- [ ] Calm, clear pace; no apologies about how rough it is

**Technical**
- [ ] Audio tested and played back; quiet room; levels not clipping
- [ ] Screen zoomed and readable; notifications off; tabs tidied
- [ ] No code editor or terminal on screen unless intended
- [ ] Backup recording saved separately
- [ ] Uploaded, link tested while logged out, privacy settings correct

## 6. Open questions for the team

The Hack for Impact participation page in our project does not state the judging criteria, the video length limit or the submission format. Before we finalise the plan, we should confirm with the organisers:

- Is five minutes a maximum, and is the video live-presented, played from a file, or uploaded?
- What are the judging criteria and weights?
- Are there requirements to show the use of the DGX Spark, or of particular open models?
- Where and by when is the video submitted?

## Sources

- [Video Production Guide for Hackathons (AI Tinkerers)](https://aitinkerers.org/docs/public/video_production_guide.md?markdown=1)
- [6 tips for making a hackathon demo video (Devpost)](https://info.devpost.com/blog/6-tips-for-making-a-hackathon-demo-video)
- [How to win a hackathon: notes from the judging table (JetBrains)](https://blog.jetbrains.com/ai/2026/06/how-to-win-a-hackathon-notes-from-the-judging-table/)
- [Hackathon Demo and Presentation Tips: How to Pitch in 3 Minutes and Win (Reskilll)](https://blogs.reskilll.com/hackathon-demo-presentation-tips-pitch-3-minutes-win-2026/)
- [24 tips for giving S-tier demos (PostHog)](https://posthog.com/newsletter/how-to-demo.md)
- [Perfecting Your Hackathon Submission (Colosseum)](https://blog.colosseum.com/perfecting-your-hackathon-submission/)
- [What Hackathon Judges Look For (Bird)](https://bird.com/blog/present-project-hackathon-judges)
- [Playbook: Hackathon Pitches (TKS Ottawa)](https://tkslife.super.site/copy-of-playbooks/playbook-hackathon-pitches)
- [Hackathon Demo Tips (AngelHack)](https://angelhack.com/blog/10-tips-to-help-you-rock-your-next-hackathon-demo/)
- [Crafting a Demo That Lands (Builderbase)](https://intercom.help/builderbase/en/articles/14836128-builder-s-guide-ch-14-crafting-a-demo-that-lands)
- [Product demo script frameworks (Demio)](https://www.demio.com/blog/compelling-product-demo-script)
- [Recording Voice-overs for Screencasts: Best Practices (IBM)](https://www.ibm.com/support/pages/node/1133727)
- [Screen Recording Basics: Recording Audio & Camera (TechSmith)](https://www.techsmith.com/learn/tutorials/academy/screen-recording-basics-recording-audio-camera/)
- [How to win Shipaton part 4: pitching your app (RevenueCat)](https://www.revenuecat.com/blog/engineering/how-to-win-shipaton-part-4-pitching-your-app)
