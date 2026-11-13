# Voiceover script

Each `## <id>` section is one voiceover clip. `tools/tts.py` sends the text under each heading to ElevenLabs and writes `composition/assets/voice/<id>.mp3`. Lines starting with `>` are direction notes and are not spoken. Add `voice=<name>` to a heading to use a character voice (`irene`, `handler`, `worker`, `agent`, `upbeat`); otherwise the narrator speaks.

Scene numbers match `storyboard.md`. Agent lines must match what the real app does (`src/app/agent.py`, `src/app/tools.py`); check them against a real run before recording. Only claim what is built: see the "Known limitations" in `docs/triage.md` and `docs/browser-agent.md`.

## 01a
> Irene at her window, pothole outside. Warm, a little weary.
This is Irene. She's lived on the same Sheffield street for forty years, and for three weeks there's been a pothole outside her gate.

## 01b voice=irene
Right. I'm ringing the council.

## 01c voice=handler
> Recorded hold message, flat.
Thank you for calling. You are… number fourteen… in the queue.

## 02a voice=handler
Potholes? You'll need to report that online, love. It's form X.

## 02b voice=irene
Form X? What's form X?

## 02c voice=irene
> Squinting at her phone, scene 02. Both link names are real (sheffield.gov.uk/roads-pavements, 13 Nov 2026).
Report a problem with a road… or report road and pavement problems? Which one's form X?

## 03a
Meanwhile, at the council, every report lands in the same inbox. Missing details. Wrong department. Hundreds of them, every day.

## 03b voice=worker
> Tired, under breath.
No location. No depth. And this one's on the M1. That's not even ours.

## 04 voice=upbeat
> Slow, dramatic.
If only there was another way.

## 05 voice=upbeat
> Upbeat from here. Scene 05, intro.
Meet CouncilTriagent. It isn't another council chatbot. It's an AI agent that takes a report in the resident's own words, works out who should fix it, and does the council's paperwork: routing, de-duplicating, prioritising and filing. And it runs entirely on local NVIDIA hardware.

## 06a voice=upbeat
Now Irene just tells the agent what's wrong.

## 06b voice=irene
There's a big pothole in the road outside number twelve, Crookes Road. Someone's going to break their ankle.

## 06c voice=agent
Sorry to hear that, Irene. Roughly how deep is it?

## 06d voice=irene
About ten centimetres.

## 06f voice=agent
> A road pothole over 40 mm is a hazard, so triage makes it P1 Emergency and the agent adds the phone advice (docs/triage.md). The spoken line doesn't read out the reference.
Thanks, Irene. I've reported it to Sheffield City Council, and your reference is on screen. At a hundred millimetres it's over the forty millimetre limit, so it's marked as an emergency. If anyone's in danger, phone the council, or 999.

## 06g voice=upbeat
No forms. No hold music. Two messages, and the report is filed.

## 07 voice=upbeat
> Scene 07, browser agent. Tested on copies of Sheffield's forms (src/mock/), not yet on the live site.
And where the council only has a web form, the agent fills it in the way a person would. It opens the form in a browser, reads the page, then clicks, types and picks from the dropdowns, and fixes its own mistakes when the form complains. No integration project. It works with the forms councils already have.

## 08 voice=worker
> The tidy queue: the "after" to scene 03.
Location, depth, priority, all in the right fields. I can actually get on with this.

## 08b voice=upbeat
Every report arrives triaged, from Emergency to Low, with the reasons in plain English. Reports of the same problem are grouped on the map, so three people reporting one pothole means one job that moves up the queue, not three emails.

## 09 voice=upbeat
> Scene 09, what makes us different.
That's what sets us apart. Most council chatbots answer questions and forward an email, and staff still triage everything by hand. CouncilTriagent does the back-office work. It routes, de-duplicates, prioritises and files, on hardware the council owns, using the Open311 standard.

## 10 voice=upbeat
> Scene 10, architecture and data sovereignty.
Under the hood, a LangChain agent runs NVIDIA Nemotron, served by Ollama on an NVIDIA DGX Spark. Its tools route reports, fill in forms and drive a browser. There are no cloud APIs, so residents' personal data never leaves the machine. And it's built on Open311, the open standard behind FixMyStreet, so it's designed to plug into council systems without a custom build each time.

## 11 voice=upbeat
> Scene 11, data workflow (Edwin's flowchart in the README, simplified).
Here's the journey of one report. First, who owns it? If it's National Highways, the police or the DVLA, the agent tells the resident and stops. If it's the council's, it checks for duplicates within sixty metres and thirty days, files the report, then triages it. Emergencies get phone advice straight away, and everything lands on the council's dashboard.

## 12 voice=upbeat
> Scene 12, models. Qualitative only: team to confirm before recording.
We tried three open models on the Spark. We chose Nemotron three point five Lightning, an NVIDIA model: with a few guards in code, it fills in a council form in about a dozen steps. Qwen three point six activates only three billion parameters at a time, so it's fast, and it's our fallback. The older Nemotron Nano runs our smoke tests. And because rules set the priority, triage keeps working even if the model is down.

## 13 voice=upbeat
> Scene 13, business model and next steps.
Our business model is open source plus services. The core is open, so any council can inspect it and run it on its own hardware. We earn from deploying it, connecting it to council case systems through Open311, adding new services like bins, street lights and fly-tipping, and support. Next, a pilot with Sheffield City Council, live reports into its case system, and NVIDIA NIM for production.

## 14 voice=upbeat
Less time on hold for Irene. Less time triaging for the council. This is CouncilTriagent.
