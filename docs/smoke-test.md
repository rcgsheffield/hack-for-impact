# Smoke test (GPU + Ollama)

The Spark's organisers run a shared Ollama container, `spark-hack-ollama`, with `nemotron-3-nano:30b`, `nemotron-3.5-lightning:30b` and `qwen3.6:35b-a3b`. **Use it for all local inference**: don't run our own Ollama, and don't pull or unload models on it, because other teams share it. The runner's user can't use Docker. See [spark-ollama.md](spark-ollama.md) for the models, how to call it and how to stop it. It clashes with the smoke stack's port.

[`src/smoke/smoke_test.sh`](../src/smoke/smoke_test.sh) checks that endpoint end to end with only `curl` and `python3`. It confirms Ollama is reachable, checks that the model is listed, generates a reply and fails if the model isn't resident in VRAM.

The **Smoke test** workflow (`.github/workflows/smoke.yml`) runs it on the Spark for pull requests touching `src/smoke/`, or via **Actions → Smoke test → Run workflow**; it never deploys. Set the endpoint and model with the repository variables `OLLAMA_URL` (default `http://127.0.0.1:11434`) and `OLLAMA_MODEL` (default `nemotron-3-nano:30b`).

Locally:

```bash
OLLAMA_URL=http://<host>:11434 REQUIRE_GPU=0 src/smoke/smoke_test.sh
```
