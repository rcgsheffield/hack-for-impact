# Voiceover script

Each `## <id>` section is one voiceover clip. `tools/tts.py` sends the text under each heading to ElevenLabs and writes `composition/assets/voice/<id>.mp3`. Lines starting with `>` are direction notes and are not spoken. Add `voice=<name>` to a heading to use a character voice (`irene`, `handler`, `worker`, `agent`, `upbeat`); otherwise the narrator speaks.

Scene numbers match `storyboard.md`. Agent lines must match what the real app does (`src/app/agent.py`, `src/app/tools.py`); check them against a real run before recording.

## 01a
> Irene at her window, pothole outside. Warm, a little weary.
This is Irene. She's lived on the same Sheffield street for forty years, and for three weeks there's been a pothole outside her gate.
> TODO: swap in one real, sourced fact if we find one (e.g. Sheffield pothole reports per year). Don't invent one.

## 01b voice=irene
Right. I'm ringing the council.

## 01c voice=handler
> Recorded hold message, flat.
Thank you for calling. You are… number fourteen… in the queue.

## 02a voice=handler
Potholes? You'll need to report that online, love. It's form X.

## 02b voice=irene
Form X? What's form X?

## 02c
Twenty minutes on hold, then a website. Is it a road or a pavement? How deep is it, in millimetres? Who even owns this road?

## 03a
Meanwhile, at the council, every report lands in the same inbox. Missing details. Wrong department. Hundreds of them, every day.

## 03b voice=worker
> Tired, under breath.
No location. No depth. And this one's on the M1. That's not even ours.

## 04 voice=upbeat
> Slow, dramatic.
If only there was another way.

## 05 voice=upbeat
> Upbeat from here.
Meet CouncilTriagent: an AI agent that takes a resident's report in their own words, works out who should fix it, and hands the council a report that's ready to act on. It's built for the Public Services track and runs entirely on local compute.

## 06a voice=upbeat
Now Irene just tells the agent what's wrong.

## 06b voice=irene
There's a big pothole in the road outside number twelve, Crookes Road. Someone's going to break their ankle.

## 06c voice=agent
Sorry to hear that, Irene. Roughly how deep is it?

## 06d voice=irene
About ten centimetres.

## 06e voice=upbeat
Behind the scenes, the agent checks who's responsible for the road, then measures the depth against the council's own criteria.

## 06f voice=agent
> The real agent quotes the full reference in its reply (see the chat text on screen). The spoken line abbreviates it so the video doesn't read out a long number.
Thanks, Irene. I've reported it to Sheffield City Council. Your reference number is on screen. At a hundred millimetres it's well over the forty millimetre threshold, so I've flagged it as urgent. Hazards like this are usually made safe within twenty-four hours.

## 06g voice=upbeat
No forms. No hold music. Two messages, and the report is filed.

## 07a voice=upbeat
And when it isn't the council's problem, the agent says so, instead of letting it bounce around an inbox.

## 07b voice=irene
There's another one on the Stocksbridge Bypass.

## 07c voice=agent
The Stocksbridge Bypass is run by National Highways, not the council, so I can't file this one for you. You can report it on the National Highways website.

## 08 voice=worker
> The tidy queue: the "after" to scene 03.
Location, depth, priority, all in the right fields. I can actually get on with this.

## 09 voice=upbeat
So how does it work? CouncilTriagent runs an open model, NVIDIA Nemotron, served by Ollama on an NVIDIA DGX Spark. There are no cloud APIs, so residents' reports never leave the machine.

## 10 voice=upbeat
The model decides what to do next and calls three tools. Route report applies Sheffield's responsibility rules: council, National Highways, police, DVLA or a private landowner. Assess pothole checks the depth against the council's thresholds. File report fills in the exact fields of the council's pothole form and issues a reference. If a tool call goes wrong, the error goes back to the model so it can correct itself. Every step is logged, so staff can see why a report was routed the way it was.

## 11 voice=upbeat
For residents, reporting a problem takes a couple of messages, in their own words. For the council, reports arrive complete, in the right place, with urgent hazards flagged first. Today it handles road and pavement defects, and it records reports locally rather than sending them to the council. Next, we'd connect it to the council's case system, add more services, and use FixMyStreet open data to spot duplicate reports. And because it speaks the standard OpenAI API, moving to NVIDIA NIM is a one-line change.

## 12 voice=upbeat
Less time on hold for Irene. Less time triaging for the council. This is CouncilTriagent.
