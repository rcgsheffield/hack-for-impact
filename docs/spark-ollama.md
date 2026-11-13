# Ollama on the DGX Spark

The Spark (`spark12`, login `user12`) came with a local LLM server already running: a Docker container set up by the hackathon organisers. Use it for the agent's local inference instead of downloading models again.

Checked on 13 Nov 2026.

## What's running

| | |
|---|---|
| Container | `spark-hack-ollama` (image `spark-hack-ollama:prepared`), created before the event |
| Command | `/bin/ollama serve`. It shows up in host `ps` as a root process, but `ollama` isn't installed on the host. |
| Port | `127.0.0.1:11434`, so only reachable from the Spark itself |
| Restart | Starts with the machine |
| Footprint when idle | About 34 MB of RAM and no GPU use. Models load on first request and unload after about 5 minutes idle. |

Models already downloaded (about 71 GB, so don't re-download them on venue Wi-Fi):

| Model | Size | Notes |
|---|---|---|
| `nemotron-3.5-lightning:30b` | 25 GB | NVIDIA model, good for the pitch at an NVIDIA event. First choice to try for the agent. |
| `qwen3.6:35b-a3b` | 22 GB | Mixture-of-experts with about 3B parameters active per token, so it's fast. Fallback if Nemotron's tool calling is unreliable. |
| `nemotron-3-nano:30b` | 24 GB | Older Nemotron |

Tool-calling quality is untested for all three models. The Spark's 128 GB of memory is shared between CPU and GPU, so two of these fit at once. Because the memory is shared, `nvidia-smi` shows "Memory-Usage: Not Supported"; use `free -h` instead.

## Using it

The app must run on the Spark, which the deploy setup already does. Point it at the OpenAI-compatible API at `http://localhost:11434/v1` (no API key needed).

Test tool calling (the response should contain a `tool_calls` field):

```bash
curl -s localhost:11434/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "nemotron-3.5-lightning:30b",
  "messages": [{"role":"user","content":"What is the weather in Sheffield?"}],
  "tools": [{"type":"function","function":{"name":"get_weather","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}]
}' | python3 -m json.tool
```

The `ollama` command isn't on the host, so run it through Docker:

```bash
sudo docker exec spark-hack-ollama ollama list   # downloaded models
sudo docker exec spark-hack-ollama ollama ps     # models currently loaded
sudo docker exec spark-hack-ollama ollama stop <model>   # free memory without stopping the server
```

## Port clash with the smoke test

[`src/smoke/docker-compose.yml`](../src/smoke/docker-compose.yml) starts its own Ollama on `127.0.0.1:11434`. While `spark-hack-ollama` is running, the smoke stack will fail with "port is already allocated". Either stop the organiser container for the smoke test, or change the smoke stack to use the existing server instead of starting its own.

## Stopping it

There's no need to stop it: it's idle and frees almost nothing. If it gets in the way:

```bash
sudo docker update --restart=no spark-hack-ollama   # keep it off after a reboot
sudo docker stop spark-hack-ollama                  # undo with: sudo docker start spark-hack-ollama
```

Don't `docker rm` the container or delete the image: you'd lose the downloaded models. Plain `kill` on the process doesn't work either, because Docker restarts it.
