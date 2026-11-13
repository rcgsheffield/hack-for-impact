#!/usr/bin/env python3
"""Generate voiceover clips from script/voiceover.md with the ElevenLabs API.

Each "## <id>" section of the script becomes composition/assets/voice/<id>.mp3.
Lines starting with ">" are direction notes and are not spoken.

Usage:
    export ELEVENLABS_API_KEY=...        # never commit this
    python3 video/tools/tts.py            # generate all clips (skips existing ones)
    python3 video/tools/tts.py s2 s5      # (re)generate only these clips
    python3 video/tools/tts.py --force    # regenerate everything
    python3 video/tools/tts.py --dry-run  # print what would be spoken, no API calls

Optional environment variables:
    ELEVENLABS_VOICE_ID  voice to use (default: DEFAULT_VOICE_ID below)
    ELEVENLABS_MODEL_ID  model to use (default: DEFAULT_MODEL_ID below)
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

VIDEO_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = VIDEO_DIR / "script" / "voiceover.md"
OUTPUT_DIR = VIDEO_DIR / "composition" / "assets" / "voice"

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# "George": a premade British male narrator voice. Swap for any voice ID from
# your ElevenLabs voice library via ELEVENLABS_VOICE_ID.
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
# Highest-quality general-purpose model for narration.
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
# 44.1 kHz, 128 kbps MP3: available on all paid plans.
OUTPUT_FORMAT = "mp3_44100_128"
REQUEST_TIMEOUT_SECONDS = 120

HEADING = re.compile(r"^##\s+(\S+)\s*$")


def parse_script(path: Path) -> dict[str, str]:
    """Return {clip_id: spoken text} from the voiceover markdown."""
    clips: dict[str, list[str]] = {}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADING.match(line)
        if match:
            current = match.group(1)
            if current in clips:
                sys.exit(f"error: duplicate clip id '{current}' in {path}")
            clips[current] = []
        elif current and line.strip() and not line.lstrip().startswith(">"):
            clips[current].append(line.strip())
    result = {cid: " ".join(lines) for cid, lines in clips.items()}
    empty = [cid for cid, text in result.items() if not text]
    if empty:
        sys.exit(f"error: clips with no text: {', '.join(empty)}")
    return result


def synthesise(text: str, api_key: str, voice_id: str, model_id: str) -> bytes:
    url = API_URL.format(voice_id=voice_id) + f"?output_format={OUTPUT_FORMAT}"
    body = json.dumps({"text": text, "model_id": model_id}).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")
        sys.exit(f"error: ElevenLabs returned HTTP {err.code}: {detail}")
    except urllib.error.URLError as err:
        sys.exit(f"error: could not reach ElevenLabs: {err.reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ids", nargs="*", help="clip ids to generate (default: all)")
    parser.add_argument("--force", action="store_true", help="overwrite existing clips")
    parser.add_argument("--dry-run", action="store_true", help="print clips without calling the API")
    args = parser.parse_args()

    if not SCRIPT_PATH.exists():
        sys.exit(f"error: script not found: {SCRIPT_PATH}")
    clips = parse_script(SCRIPT_PATH)

    unknown = [cid for cid in args.ids if cid not in clips]
    if unknown:
        sys.exit(f"error: unknown clip ids: {', '.join(unknown)} (known: {', '.join(clips)})")
    selected = {cid: clips[cid] for cid in (args.ids or clips)}

    if args.dry_run:
        for cid, text in selected.items():
            print(f"{cid}: {text}")
        return

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("error: set ELEVENLABS_API_KEY (see https://elevenlabs.io/app/settings/api-keys)")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID)
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", DEFAULT_MODEL_ID)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for cid, text in selected.items():
        out = OUTPUT_DIR / f"{cid}.mp3"
        if out.exists() and not (args.force or args.ids):
            print(f"skip {cid} (exists; use --force or name it to regenerate)")
            continue
        print(f"generating {cid} ...", flush=True)
        out.write_bytes(synthesise(text, api_key, voice_id, model_id))
        print(f"  wrote {out.relative_to(VIDEO_DIR)}")


if __name__ == "__main__":
    main()
