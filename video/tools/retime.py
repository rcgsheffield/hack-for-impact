#!/usr/bin/env python3
"""Retime the scenes to the real voiceover clips.

Each scene file defines `const CUE = { name: seconds, ... }` (seconds from scene
start). The cues were first written against estimated clip lengths; this script
measures the real clips in composition/assets/voice/ with ffprobe and:

  1. rewrites every scene's CUE numbers so each voice clip starts at its anchor
     cue and the beats inside a clip stretch with the real speech,
  2. sets each scene's start and duration in composition/index.html,
  3. writes the voiceover <audio> elements and lays the music under the sections.

The estimated cues are saved once to tools/cue-baseline.json and every run
recomputes from that baseline, so it is safe to rerun after regenerating clips.

Usage:
    python3 video/tools/retime.py            # retime (snapshots the baseline on first run)
    python3 video/tools/retime.py --dry-run  # print the new timings only
"""

import argparse
import os
import json
import re
import subprocess
import sys
from pathlib import Path

VIDEO_DIR = Path(__file__).resolve().parent.parent
COMP_DIR = VIDEO_DIR / "composition"
SCENES_DIR = COMP_DIR / "compositions"
VOICE_DIR = Path(os.environ.get("RETIME_VOICE_DIR", COMP_DIR / "assets" / "voice"))  # override for testing
MUSIC_DIR = COMP_DIR / "assets" / "music"
INDEX = COMP_DIR / "index.html"
BASELINE = Path(__file__).resolve().parent / "cue-baseline.json"
SCRIPT = VIDEO_DIR / "script" / "voiceover.md"

# Speaking rate the scene cues were estimated at (words per second).
EST_WORDS_PER_SECOND = 2.6
# Silence kept after the last clip of a scene before the next scene starts.
MIN_SCENE_TAIL = 1.0
# Some scenes squeezed their beats to fit a short slot: the span (from the
# clip's anchor) that the estimated speech covers in that scene.
EST_SPAN_OVERRIDE = {}
# Scenes whose cues were written against the real clip lengths (measured with
# ffprobe), not estimates: their speech isn't stretched, only shifted.
REAL_TIMED = {"form-x", "intro", "chat", "browser-agent", "council-view", "usp", "agent-flow", "data-workflow", "models", "business"}
# Scenes whose visuals keep building after the narration ends: the gaps between
# post-speech cues are scaled by this factor to keep the video under 5 minutes.
POST_SPEECH_SCALE = {}
# In those scenes, the hold after the last cue is capped at this (s).
COMPRESSED_TAIL = 3.0
# Clip 04 lives in a scene without a CUE object: fixed offset from scene start.
FIXED_ANCHORS = {"another-way": {"04": 1.0}}

# Scene order, baseline duration (s) and {clip id: anchor cue name}.
SCENES = [
    ("irene-phone", 15, {"01a": "c01a", "01b": "c01b", "01c": "c01c"}),
    ("form-x", 18.5, {"02a": "c02a", "02b": "c02b", "02c": "c02c"}),
    ("council-inbox", 15, {"03a": "c03a", "03b": "c03b"}),
    ("another-way", 4, {}),
    ("intro", 20.5, {"05": "c05"}),
    ("chat", 43.5, {"06a": "vo06a", "06b": "vo06b", "06c": "vo06c", "06d": "vo06d", "06f": "vo06f", "06g": "vo06g"}),
    ("browser-agent", 20.5, {"07": "vo07"}),
    ("council-view", 22, {"08": "vo08", "08b": "vo08b"}),
    ("usp", 20.5, {"09": "vo09"}),
    ("agent-flow", 26.5, {"10": "vo10"}),
    ("data-workflow", 24, {"11": "vo11"}),
    ("models", 27.25, {"12": "vo12"}),
    ("business", 26.5, {"13": "vo13"}),
    ("close", 10.2, {"14": "hold"}),
]

# Music: (id, file, section start scene, volume). Each section's tracks are laid
# end to end (1 s crossfades) from the section's first scene, looping the last
# track if needed, until the next section starts.
MUSIC_SECTIONS = [
    ("sad", ["sad.mp3"], "irene-phone", "another-way", 0.3),
    ("demo", ["hopeful.mp3", "quiet-city-pulse.mp3"], "intro", "agent-flow", 0.25),
    ("tech", ["tech.mp3", "local-machine.mp3"], "agent-flow", None, 0.2),
]
CROSSFADE = 1.0
# Don't start another track for less than this (s): a short restart sounds like a glitch.
MIN_MUSIC_PIECE = 8.0

CUE_BLOCK = re.compile(r"(const CUE = \{)(.*?)(\};)", re.S)
CUE_LINE = re.compile(r"^(\s*)(\w+):\s*([0-9.]+)(,.*)$")


def duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return float(out)
    except (subprocess.CalledProcessError, ValueError) as err:
        sys.exit(f"error: could not measure {path}: {err}")


def read_cues(scene: str) -> dict[str, float]:
    text = (SCENES_DIR / f"{scene}.html").read_text(encoding="utf-8")
    block = CUE_BLOCK.search(text)
    if not block:
        return {}
    cues = {}
    for line in block.group(2).splitlines():
        m = CUE_LINE.match(line)
        if m:
            cues[m.group(2)] = float(m.group(3))
    return cues


def write_cues(scene: str, cues: dict[str, float]) -> None:
    path = SCENES_DIR / f"{scene}.html"
    text = path.read_text(encoding="utf-8")
    block = CUE_BLOCK.search(text)
    if not block:
        return
    lines = []
    for line in block.group(2).splitlines():
        m = CUE_LINE.match(line)
        if m and m.group(2) in cues:
            line = f"{m.group(1)}{m.group(2)}: {cues[m.group(2)]:.2f}{m.group(4)}"
        lines.append(line)
    text = text[: block.start(2)] + "\n".join(lines) + text[block.end(2):]
    path.write_text(text, encoding="utf-8")


def word_counts() -> dict[str, int]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tts  # reuse the script parser so clip text matches what was spoken

    clips, _ = tts.parse_script(SCRIPT)
    return {cid: len(text.split()) for cid, text in clips.items()}


def retime_scene(base_cues, base_dur, anchors, actual, words, est_override, post_scale=1.0, real_timed=False):
    """Return (new cues, new anchor times {clip: t}, new duration)."""
    order = sorted(anchors.items(), key=lambda kv: base_cues[kv[1]])
    # Piecewise map: [(old_start, old_end, new_start, new_end)] for each clip's speech.
    segments = []
    shift = 0.0
    for i, (clip, cue) in enumerate(order):
        start = base_cues[cue]
        est = words[clip] / EST_WORDS_PER_SECOND
        if clip in est_override:
            est = est_override[clip]
        if real_timed:
            est = actual[clip]
        if i + 1 < len(order) and not real_timed:
            span = base_cues[order[i + 1][1]] - start
            est = min(est, span - 0.3)
        new_start = start + shift
        segments.append((start, start + est, new_start, new_start + actual[clip]))
        shift = new_start + actual[clip] - (start + est)

    def remap(t):
        for i, (old_s, old_e, new_s, new_e) in enumerate(reversed(segments)):
            if t >= old_e:
                scale = post_scale if i == 0 else 1.0  # i == 0: after the last clip
                return new_e + (t - old_e) * scale
            if t >= old_s:
                return new_s + (t - old_s) * (new_e - new_s) / (old_e - old_s)
        return t

    new_cues = {name: remap(t) for name, t in base_cues.items()}
    new_anchors = {clip: remap(base_cues[cue]) for clip, cue in anchors.items()}
    last_end = segments[-1][3] if segments else 0.0
    last_cue = max(base_cues.values(), default=0.0)
    # Keep the full tail after the last cue so its tweens finish before the cut.
    tail = base_dur - last_cue
    if post_scale != 1.0:
        tail = min(tail, COMPRESSED_TAIL)
    new_dur = max(remap(last_cue) + tail, last_end + MIN_SCENE_TAIL)
    return new_cues, new_anchors, round(new_dur, 2)


def build_audio(scene_starts, scene_ends, vo, total):
    lines = ["      <!-- Voiceover (ElevenLabs, generated by tools/tts.py; placed by tools/retime.py) -->"]
    for clip, (t, d) in vo.items():
        lines.append(
            f'      <audio id="vo-{clip}" class="clip" data-start="{t:.2f}" data-duration="{d:.2f}" '
            f'data-track-index="2" data-volume="1" src="assets/voice/{clip}.mp3"></audio>'
        )
    lines.append("")
    lines.append("      <!-- Music (Suno; placed by tools/retime.py) -->")
    track = 3
    for name, files, first, until, vol in MUSIC_SECTIONS:
        start = scene_starts[first]
        end = scene_starts[until] if until else total
        lengths = [(f, duration(MUSIC_DIR / f)) for f in files]
        t, n, i = start, 0, 0
        while t < end - 0.5:
            f, length = lengths[min(i, len(lengths) - 1)]
            d = min(length, end - t)
            if n > 0 and d < MIN_MUSIC_PIECE:
                break
            fade_in = 0.5 if n == 0 else CROSSFADE
            fade_out = 0.3 if until == "another-way" and t + d >= end - 0.01 else (3 if until is None and t + d >= end - 0.01 else CROSSFADE)
            lines.append(
                f'      <audio id="music-{name}-{n + 1}" class="clip" data-start="{t:.2f}" data-duration="{d:.2f}" '
                f'data-track-index="{track}" data-volume="{vol}" data-fade-in="{fade_in}" data-fade-out="{fade_out}" '
                f'src="assets/music/{f}"></audio>'
            )
            track = 4 if track == 3 else 3
            if t + d >= end - 0.01:
                break
            t += d - CROSSFADE
            n += 1
            i += 1
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not BASELINE.exists():
        baseline = {scene: read_cues(scene) for scene, _, _ in SCENES}
        BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
        print(f"saved estimated cues to {BASELINE.relative_to(VIDEO_DIR)}")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    # Scenes added since the snapshot (or removed from it to be rebuilt): take their cues as written.
    added = [scene for scene, _, _ in SCENES if scene not in baseline]
    for scene in added:
        baseline[scene] = read_cues(scene)
    stale = [scene for scene in baseline if scene not in {name for name, _, _ in SCENES}]
    for scene in stale:
        del baseline[scene]
    if (added or stale) and not args.dry_run:
        BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
        print(f"baseline: added {added or 'none'}, removed {stale or 'none'}")

    words = word_counts()
    actual = {}
    for cid in words:
        clip = VOICE_DIR / f"{cid}.mp3"
        if not clip.exists():
            sys.exit(f"error: missing voice clip {clip}; run tools/tts.py first")
        actual[cid] = duration(clip)

    t = 0.0
    scene_starts, scene_ends, vo, new_scene = {}, {}, {}, {}
    for scene, base_dur, anchors in SCENES:
        if scene in FIXED_ANCHORS:
            fixed = FIXED_ANCHORS[scene]
            cues, anchor_t = {}, dict(fixed)
            dur = max(base_dur, max(o + actual[c] for c, o in fixed.items()) + 0.8)
        else:
            est_override = {c: v for c, v in EST_SPAN_OVERRIDE.items() if c in anchors}
            cues, anchor_t, dur = retime_scene(
                baseline[scene], base_dur, anchors, actual, words, est_override, POST_SPEECH_SCALE.get(scene, 1.0),
                scene in REAL_TIMED,
            )
        scene_starts[scene], scene_ends[scene] = round(t, 2), round(t + dur, 2)
        for clip, at in anchor_t.items():
            vo[clip] = (t + at, actual[clip])
        new_scene[scene] = (cues, dur)
        print(f"{scene:14} start {t:7.2f}  dur {dur:6.2f}  (was {base_dur})")
        t += dur
    total = round(t, 2)
    print(f"total {total:.2f} s ({int(total // 60)}:{total % 60:04.1f})")
    if args.dry_run:
        return

    for scene, (cues, _) in new_scene.items():
        if cues:
            write_cues(scene, cues)

    html = INDEX.read_text(encoding="utf-8")
    html = re.sub(r'(data-composition-id="main"[^>]*?data-duration=")[0-9.]+"', rf'\g<1>{total}"', html, count=1, flags=re.S)
    for scene, _, _ in SCENES:
        pattern = rf'(id="{scene}"[^>]*?data-start=")[0-9.]+("\s+data-duration=")[0-9.]+"'
        html, n = re.subn(pattern, rf'\g<1>{scene_starts[scene]}\g<2>{new_scene[scene][1]}"', html, count=1, flags=re.S)
        if n != 1:
            sys.exit(f"error: could not find scene host '{scene}' in index.html")
    start = html.index("      <!-- Voiceover")
    end = html.index("    </div>\n    <script>")
    html = html[:start] + build_audio(scene_starts, scene_ends, vo, total) + html[end:]
    INDEX.write_text(html, encoding="utf-8")
    print("updated scene CUEs and index.html")


if __name__ == "__main__":
    main()
