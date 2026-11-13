"""Web app: FastAPI with a Gradio chat UI at /, a health check at /health, the dummy council site at /mock/
a dashboard of submissions to it at /dashboard
and a resident's view of one report at /reports/{reference}.

Run: uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8000
"""

import re
from collections.abc import Iterator
from functools import cache

import gradio as gr
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from hack_for_impact.agent.llm import build_agent, new_thread_id, run_agent_events, user_turns

from . import config, submissions, usage
from .agent import ToolStep
from .tool_display import describe as describe_tool

app = FastAPI(title="CouncilTriagent")
app.include_router(usage.router)
app.include_router(submissions.router)
# Report-card library and page assets (static/report-card.js); mounted before Gradio so it isn't shadowed.
app.mount("/static", StaticFiles(directory=submissions.STATIC_DIR), name="static")


@app.get("/health")
def health() -> JSONResponse:
    """200 if Ollama is reachable and has the configured model, otherwise 503. Used by deploy.sh and check.sh."""
    body = {"ok": False, "model": config.OLLAMA_MODEL, "sha": config.GIT_SHA}
    try:
        body["ollama"] = httpx.get(f"{config.OLLAMA_URL}/api/version", timeout=3).raise_for_status().json()["version"]
        tags = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=3).raise_for_status().json()
        if config.OLLAMA_MODEL not in [m["name"] for m in tags.get("models", [])]:
            body["error"] = f"model {config.OLLAMA_MODEL} not found in Ollama"
        else:
            body["ok"] = True
    except (httpx.HTTPError, ValueError, KeyError) as e:
        body["error"] = f"Ollama unreachable at {config.OLLAMA_URL}: {e}"
    return JSONResponse(body, status_code=200 if body["ok"] else 503)


def _text(content) -> str:
    """Gradio message content may be a string or a list of parts; keep the text."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return content.get("text", "") if content.get("type", "text") == "text" else ""
    if isinstance(content, (list, tuple)):
        return "\n".join(filter(None, (_text(part) for part in content)))
    return ""


def _to_model_history(history: list[dict]) -> list[dict]:
    """Keep user and assistant text, dropping the tool-step bubbles shown in the UI."""
    out = []
    for m in history:
        if (m.get("metadata") or {}).get("title"):
            continue
        text = _text(m.get("content"))
        if m.get("role") in ("user", "assistant") and text:
            out.append({"role": m["role"], "content": text})
    return out


MODE_CHOICES = [
    ("Chat: the agent files the report itself", "chat"),
    ("Web form: the agent fills in the council form in a browser", "form"),
]


@cache
def get_agent(mode: str = "chat"):
    """The LangChain agent for one branch ("chat" or "form"), on the configured local Ollama model. Built on first use."""
    return build_agent(model_name=config.OLLAMA_MODEL, base_url=config.OLLAMA_URL, mode=mode)


# Runs in the browser: asks for location permission and returns "lat, lon (±N m)" or a message saying why not.
# Browsers only allow geolocation on secure origins: https://..., or http://localhost / 127.0.0.1.
GEOLOCATE_JS = """
async () => {
  if (!window.isSecureContext) return "Not available: location needs HTTPS or localhost (this page is " + location.origin + ")";
  if (!navigator.geolocation) return "Not available: this browser has no location support";
  try {
    const p = await new Promise((ok, fail) =>
      navigator.geolocation.getCurrentPosition(ok, fail, {enableHighAccuracy: true, timeout: 15000, maximumAge: 60000}));
    return `${p.coords.latitude.toFixed(6)}, ${p.coords.longitude.toFixed(6)} (±${Math.round(p.coords.accuracy)} m)`;
  } catch (e) {
    return "Not available: " + (e.code === 1 ? "permission denied" : e.message);
  }
}
"""
LOCATION_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)(?:\s*\(±(\d+) m\))?")


def location_note(location: str | None) -> str:
    """The context note added to the user's message when they have shared their device location."""
    m = LOCATION_RE.match(location or "")
    if not m:
        return ""
    lat, lon, accuracy = m.groups()
    acc = f", accuracy about {accuracy} m" if accuracy else ""
    return (f"\n\n[Device location shared by the user: lat {lat}, lon {lon}{acc}. "
            "Use it only if they are at the problem now.]")


def respond(message, history: list[dict], mode: str | None, location: str | None,
            thread_id: str | None) -> Iterator[tuple[list[gr.ChatMessage], str]]:
    """One chat turn. Each conversation is a checkpointer thread keyed by a UUID held in the browser session.

    Normally only the new message is sent; the agent remembers earlier turns, tool results included. If the thread
    doesn't match the chat on screen (new chat, or the user retried, undid or edited a message), start a new
    thread seeded with the visible text history.
    """
    # Each mode has its own agent and checkpointer, so switching mode mid-chat starts a new thread (seeded below).
    agent = get_agent(mode or "chat")
    # The location note goes to the model only; the chat shows what the user typed.
    new_message = {"role": "user", "content": _text(message) + location_note(location)}
    shown_turns = sum(m.get("role") == "user" for m in history)
    if thread_id and user_turns(agent, thread_id) == shown_turns:
        messages = [new_message]
    else:
        thread_id = new_thread_id()
        messages = _to_model_history(history) + [new_message]

    shown: list[gr.ChatMessage] = []
    try:
        for event in run_agent_events(agent, messages, thread_id):
            if isinstance(event, ToolStep):
                title, body = describe_tool(event.name, event.arguments, event.result)
                shown.append(gr.ChatMessage(content=body, metadata={"title": title, "status": "done"}))
            else:
                shown.append(gr.ChatMessage(content=event))
            yield shown, thread_id
    except Exception as e:  # Show model/connection failures in the chat rather than a blank error.
        shown.append(gr.ChatMessage(content=f"⚠️ The local model isn't responding ({type(e).__name__}). Please try again shortly."))
        yield shown, thread_id


with gr.Blocks(title="CouncilTriagent") as demo:
    gr.Markdown(
        "# CouncilTriagent\n"
        "Report a problem with a road, pavement or street tree in Sheffield in your own words. "
        f"Running locally on NVIDIA DGX Spark ({config.OLLAMA_MODEL}). "
        "**Unofficial hackathon prototype: nothing is sent to the council.** "
        "[Submissions dashboard](/dashboard)"
    )
    thread_state = gr.State(None)
    with gr.Row(equal_height=True):
        mode_radio = gr.Radio(MODE_CHOICES, value="chat", label="How should the agent file reports?", scale=3)
        with gr.Column(scale=2):
            location_box = gr.Textbox(label="Your location (optional)", interactive=False,
                                      placeholder="Share it if you're standing at the problem")
            with gr.Row():
                locate_btn = gr.Button("📍 Share my location", size="sm")
                forget_btn = gr.Button("Forget", size="sm", variant="secondary")
    # fn=None: runs only in the browser, where the permission prompt appears; the result fills the textbox.
    locate_btn.click(fn=None, inputs=None, outputs=location_box, js=GEOLOCATE_JS)
    forget_btn.click(fn=lambda: "", inputs=None, outputs=location_box)

    gr.ChatInterface(
        respond,
        additional_inputs=[mode_radio, location_box, thread_state],
        additional_outputs=[thread_state],
        # One column per input: message, mode, location, thread id. None leaves those as they are.
        examples=[[ex, None, None, None] for ex in [
            "There's a really deep pothole outside 10 Fargate, about 5cm deep. A cyclist nearly came off.",
            "A big branch has come down across the pavement on Derbyshire Lane outside number 12",
            "There's a pothole right here where I'm standing, about two inches deep",
            "Huge pothole on the Stocksbridge Bypass heading north",
            "The supermarket car park on Abbeydale Road is full of potholes",
        ]],
        run_examples_on_click=True,
        cache_examples=False,
    )

# Mount last so /health and /mock/ aren't shadowed by Gradio's routes.
app = gr.mount_gradio_app(app, demo, path="/")
