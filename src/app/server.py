#!/usr/bin/env python3
"""Barebones app: /health, a chat page, and /chat -> local Ollama. Stdlib only.

Env: PORT (8000), OLLAMA_URL (http://127.0.0.1:11434), OLLAMA_MODEL, GIT_SHA.
"""
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8000"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.environ.get("OLLAMA_MODEL", "nemotron-3.5-lightning:30b")
SHA = os.environ.get("GIT_SHA", "unknown")

PAGE = b"""<!doctype html><meta charset=utf-8><title>Hack for Impact</title>
<h1>Hack for Impact</h1>
<form id=f><input id=q size=60 placeholder="Say something" autofocus>
<button>Send</button></form><pre id=a></pre>
<script>
f.onsubmit=async e=>{e.preventDefault();a.textContent='...';
const r=await fetch('/chat',{method:'POST',body:JSON.stringify({prompt:q.value})});
a.textContent=(await r.json()).reply||'error';};
</script>"""


def ollama(path, payload=None, timeout=10):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        OLLAMA_URL + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            try:
                version = ollama("/api/version")["version"]
                self._send(200, {"ok": True, "ollama": version, "model": MODEL, "sha": SHA})
            except Exception as e:
                self._send(503, {"ok": False, "error": str(e), "model": MODEL, "sha": SHA})
        elif self.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/chat":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            prompt = json.loads(self.rfile.read(n))["prompt"]
            out = ollama(
                "/v1/chat/completions",
                {
                    "model": MODEL,
                    "think": False,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=600,
            )
            self._send(200, {"reply": out["choices"][0]["message"]["content"]})
        except Exception as e:
            self._send(502, {"error": str(e)})


if __name__ == "__main__":
    print(f"listening on :{PORT}, ollama={OLLAMA_URL}, model={MODEL}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
