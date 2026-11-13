"""Smoke-test API: proves Ollama generates text and is using the NVIDIA GPU."""
import os
import shutil
import subprocess

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("MODEL", "nemotron-mini")

app = FastAPI(title="spark-smoke")


class GenerateRequest(BaseModel):
    prompt: str
    model: str | None = None


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL}


@app.get("/gpu")
def gpu():
    """Report VRAM used by loaded models (size_vram > 0 means GPU inference)."""
    try:
        ps = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=10).json()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"ollama unreachable: {e}")
    models = [
        {"name": m["name"], "size": m.get("size", 0), "size_vram": m.get("size_vram", 0)}
        for m in ps.get("models", [])
    ]
    smi = None
    if shutil.which("nvidia-smi"):
        smi = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    return {
        "models": models,
        "on_gpu": any(m["size_vram"] > 0 for m in models),
        "nvidia_smi": smi,
    }


@app.post("/generate")
def generate(req: GenerateRequest):
    try:
        r = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": req.model or MODEL, "prompt": req.prompt, "stream": False},
            timeout=600,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"ollama error: {e}")
    d = r.json()
    return {
        "model": d.get("model"),
        "response": d.get("response", ""),
        "eval_count": d.get("eval_count"),
        "total_duration_s": round(d.get("total_duration", 0) / 1e9, 2),
    }
