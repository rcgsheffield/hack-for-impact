#!/usr/bin/env bash
# End-to-end check: API up, model pulled, text generated, model resident in VRAM.
# Run from anywhere; set REQUIRE_GPU=0 to skip the GPU assertion (e.g. on a laptop).
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${MODEL:-nemotron-mini}"
API="${API:-http://127.0.0.1:8080}"
REQUIRE_GPU="${REQUIRE_GPU:-1}"

echo "== waiting for API"
for _ in $(seq 1 60); do
  curl -fs "$API/health" >/dev/null && break
  sleep 2
done
curl -fs "$API/health"; echo

echo "== pulling $MODEL"
docker compose exec -T ollama ollama pull "$MODEL"

echo "== generating"
RESP=$(curl -fs -X POST "$API/generate" -H 'Content-Type: application/json' \
  -d '{"prompt":"Reply with one short sentence about Sheffield."}')
echo "$RESP"
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["response"].strip(), "empty response"' "$RESP"

echo "== GPU check"
GPU=$(curl -fs "$API/gpu")
echo "$GPU"
if [ "$REQUIRE_GPU" = "1" ]; then
  python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["on_gpu"], "model not in VRAM (running on CPU?)"' "$GPU"
fi

echo "SMOKE TEST PASSED"
