#!/usr/bin/env bash
# End-to-end check against the organisers' shared Ollama (container
# `spark-hack-ollama` on the Spark): reachable, model present, text generated,
# model resident in VRAM. Needs only curl and python3 - no Docker.
#
# Env: OLLAMA_URL (default http://127.0.0.1:11434), MODEL (default
# nemotron-3-nano:30b), REQUIRE_GPU=0 to skip the VRAM assertion.
# Never pulls or unloads models: the instance is shared with other teams.
set -euo pipefail

OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
OLLAMA_URL="${OLLAMA_URL%/}"
MODEL="${MODEL:-nemotron-3-nano:30b}"
REQUIRE_GPU="${REQUIRE_GPU:-1}"

json() { python3 -c "import json,sys; d=json.load(sys.stdin); $1"; }

echo "== Ollama at $OLLAMA_URL"
if ! VERSION=$(curl -fsS --max-time 10 "$OLLAMA_URL/api/version"); then
  echo "ERROR: cannot reach Ollama at OLLAMA_URL=$OLLAMA_URL" >&2
  echo "Find the published port on the Spark with: sudo docker port spark-hack-ollama" >&2
  echo "then set the OLLAMA_URL repository variable (Settings -> Secrets and variables -> Actions -> Variables)." >&2
  exit 1
fi
echo "$VERSION"

echo "== checking $MODEL is available"
TAGS=$(curl -fsS --max-time 10 "$OLLAMA_URL/api/tags")
if ! echo "$TAGS" | MODEL="$MODEL" json 'import os; sys.exit(0 if os.environ["MODEL"] in [m["name"] for m in d.get("models", [])] else 1)'; then
  echo "ERROR: model '$MODEL' not found. Available models:" >&2
  echo "$TAGS" | json 'print("\n".join("  " + m["name"] for m in d.get("models", [])))' >&2
  exit 1
fi

echo "== generating (first call may take a while if the model has to load)"
BODY=$(MODEL="$MODEL" python3 -c 'import json,os; print(json.dumps({"model": os.environ["MODEL"], "prompt": "Reply with one short sentence about Sheffield.", "stream": False, "think": False}))')
RESP=$(curl -fsS --max-time 600 -X POST "$OLLAMA_URL/api/generate" \
  -H 'Content-Type: application/json' -d "$BODY")
echo "$RESP" | json '
r = d.get("response", "").strip()
print(r)
print("(%s tokens in %.1fs)" % (d.get("eval_count"), d.get("total_duration", 0) / 1e9))
assert r, "empty response"'

echo "== GPU check"
PS=$(curl -fsS --max-time 10 "$OLLAMA_URL/api/ps")
echo "$PS" | json '
for m in d.get("models", []):
    print("  %s: size=%s size_vram=%s" % (m["name"], m.get("size", 0), m.get("size_vram", 0)))'
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader || true
fi
if [ "$REQUIRE_GPU" = "1" ]; then
  echo "$PS" | MODEL="$MODEL" json '
import os
m = [m for m in d.get("models", []) if m["name"] == os.environ["MODEL"]]
assert m and m[0].get("size_vram", 0) > 0, "model not in VRAM (running on CPU?)"'
fi

echo "SMOKE TEST PASSED"
