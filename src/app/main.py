"""Web app: FastAPI with a Gradio chat UI at /, a health check at /health, the dummy council site at /mock/
a dashboard of submissions to it at /dashboard
and a resident's view of one report at /reports/{reference}.

The UI has two tabs: the chat, and "Watch the agent fill in the form", where the agent fills in the mock forms itself
in a browser (src/app/browser_agent.py) with a live view of that browser beside the chat.

Run: uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8000
"""

import atexit
import re
import threading
import time
from collections.abc import Iterator
from functools import cache

import gradio as gr
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from hack_for_impact.agent.llm import build_agent, new_thread_id, run_agent_events, user_turns

from . import config, submissions, usage
from .agent import ToolStep
from .browser_agent import BrowserSession, make_browser_agent, page_heading
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
# Optional map for pointing at the problem (static/location-pin.js). Its value is the location string that
# location_note() reads: "lat, lon (±N m)" from the device, or "lat, lon (map pin)" once tapped or dragged.
# The template doesn't use ${value}, so setting the value from JS doesn't redraw (and lose) the map.
LEAFLET = "https://unpkg.com/leaflet@1.9.4/dist/"  # same version as /dashboard and the mock forms
location_pin = gr.HTML(
    value="",
    render=False,  # rendered beside the chat below
    html_template="""
<section class="lp" aria-labelledby="lp-heading">
  <h2 id="lp-heading">Where is the problem? <span class="lp-optional">(optional)</span></h2>
  <div class="lp-actions">
    <button type="button" class="lp-use">📍 Use my location</button>
    <button type="button" class="lp-clear" disabled>Clear pin</button>
  </div>
  <div class="lp-map" role="application" aria-label="Map of Sheffield. Click to drop a pin where the problem is."></div>
  <p class="lp-status" role="status" aria-live="polite">Loading map…</p>
</section>""",
    css_template="""
.lp h2 { font-size: 1rem; margin: 0 0 .5rem; }
.lp-optional { font-weight: normal; opacity: .75; }
.lp-actions { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: .5rem; }
.lp button { font: inherit; padding: .4rem .8rem; border-radius: 6px; cursor: pointer;
             border: 1px solid var(--border-color-primary); background: var(--button-secondary-background-fill);
             color: var(--button-secondary-text-color); }
.lp button:disabled { opacity: .5; cursor: not-allowed; }
.lp button:focus-visible { outline: 3px solid var(--color-accent); outline-offset: 2px; }
.lp-map { height: 320px; border-radius: 8px; border: 1px solid var(--border-color-primary); }
.lp-status { margin: .5rem 0 0; font-size: .9rem; }""",
    js_on_load=(submissions.STATIC_DIR / "location-pin.js").read_text(encoding="utf-8"),
    head=f'<link rel="stylesheet" href="{LEAFLET}leaflet.css"><script src="{LEAFLET}leaflet.js"></script>',
)

LOCATION_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)(?:\s*\((?:±(\d+) m|(map pin))\))?")


def location_note(location: str | None) -> str:
    """The context note added to the user's message when they have shared their device location or dropped a pin."""
    m = LOCATION_RE.match(location or "")
    if not m:
        return ""
    lat, lon, accuracy, pinned = m.groups()
    if pinned:
        return (f"\n\n[The user dropped a pin on the map where the problem is: lat {lat}, lon {lon}. "
                "Use it as the problem's location; you don't need to ask where it is.]")
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

    for shown in _show(run_agent_events(agent, messages, thread_id)):
        yield shown, thread_id


def _show(events: Iterator[ToolStep | str]) -> Iterator[list[gr.ChatMessage]]:
    """Turn agent events into chat bubbles: a collapsible one per tool call, then the reply."""
    shown: list[gr.ChatMessage] = []
    try:
        for event in events:
            if isinstance(event, ToolStep):
                title, body = describe_tool(event.name, event.arguments, event.result)
                if set(event.result) == {"output"}:
                    # Plain-text result, e.g. a browser page: show it as text, not as escaped JSON.
                    body = (f"**Arguments**\n```json\n{event.arguments}\n```\n"
                            f"**Result**\n```\n{event.result['output']}\n```")
                shown.append(gr.ChatMessage(content=body, metadata={"title": title, "status": "done"}))
            else:
                shown.append(gr.ChatMessage(content=event))
            yield shown
    except Exception as e:  # Show model/connection failures in the chat rather than a blank error.
        shown.append(gr.ChatMessage(content=f"⚠️ The local model isn't responding ({type(e).__name__}). Please try again shortly."))
        yield shown


# ---- Browser mode: one browser per visitor, keyed by Gradio's session hash ----
_browser_lock = threading.Lock()
_browser_agents: dict[str, tuple] = {}  # session hash -> (agent, BrowserSession, last used)


def _browser_agent(key: str):
    """This conversation's browser agent. Closes idle browsers, and the oldest one if too many are open."""
    now = time.monotonic()
    to_close: list[BrowserSession] = []
    with _browser_lock:
        for k, (_, session, used) in list(_browser_agents.items()):
            if now - used > config.BROWSER_IDLE_SECONDS:
                to_close.append(_browser_agents.pop(k)[1])
        if key in _browser_agents:
            agent, session, _ = _browser_agents[key]
        else:
            while len(_browser_agents) >= config.BROWSER_MAX_SESSIONS:
                oldest = min(_browser_agents, key=lambda k: _browser_agents[k][2])
                to_close.append(_browser_agents.pop(oldest)[1])
            agent, session = make_browser_agent(model=config.OLLAMA_MODEL, screenshots=True)
        _browser_agents[key] = (agent, session, now)
    for session in to_close:  # Outside the lock: closing a browser takes a moment.
        session.close()
    return agent


def _close_browser(key: str | None) -> None:
    with _browser_lock:
        entry = _browser_agents.pop(key, None) if key else None
    if entry:
        entry[1].close()


@atexit.register
def _close_all_browsers() -> None:
    for key in list(_browser_agents):
        _close_browser(key)


def _live_view(agent) -> dict:
    """The newest screenshot of this conversation's browser, captioned with the page it's on."""
    path = agent.tools.last_screenshot
    if path is None or not path.exists():
        return gr.skip()
    with Image.open(path) as im:
        picture = im.copy()
    heading = page_heading(agent.tools.last_page)
    return gr.update(value=picture, label=f"The agent's browser: {heading}" if heading else "The agent's browser")


def respond_browser(message, history: list[dict], request: gr.Request):
    """Like respond, plus the live view: yields (chat bubbles, screenshot) after every step."""
    turn = _to_model_history(history) + [{"role": "user", "content": _text(message)}]
    agent = _browser_agent(getattr(request, "session_hash", None) or "default")
    for shown in _show(run_agent_events(agent, turn, max_steps=config.BROWSER_MAX_AGENT_STEPS)):
        yield shown, _live_view(agent)


def _on_tab_closed(request: gr.Request) -> None:
    _close_browser(getattr(request, "session_hash", None))


with gr.Blocks(title="CouncilTriagent") as demo:
    gr.Markdown(
        "# CouncilTriagent\n"
        "Report a problem with a road, pavement or street tree in Sheffield in your own words, and drop a pin "
        "on the map if you can. "
        f"Running locally on NVIDIA DGX Spark ({config.OLLAMA_MODEL}). "
        "**Unofficial hackathon prototype: nothing is sent to the council.** "
        "[Submissions dashboard](/dashboard). "
        "To watch the agent fill in the council's own form, open the *Watch the agent fill in the form* tab."
    )
    thread_state = gr.State(None)
    with gr.Row(equal_height=False):
        with gr.Column(scale=2, min_width=280):
            location_pin.render()
        with gr.Column(scale=3, min_width=320):
            mode_radio = gr.Radio(MODE_CHOICES, value="chat", label="How should the agent file reports?")
            gr.ChatInterface(
                respond,
                additional_inputs=[mode_radio, location_pin, thread_state],
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

with gr.Blocks() as browser_mode:
    gr.Markdown(
        "The agent opens the council's report form in a browser and fills it in itself, page by page, like a "
        f"person would. The browser runs on NVIDIA DGX Spark with the model ({config.OLLAMA_MODEL}); the picture "
        "on the right updates after every step. It asks you to confirm before it submits. "
        "**Unofficial hackathon prototype: it uses a test copy of the form and nothing is sent to the council.**"
    )
    live = gr.Image(label="The agent's browser", type="pil", format="png", interactive=False, render=False,
                    buttons=["fullscreen"], height=640)
    with gr.Row():
        with gr.Column(scale=5):
            gr.ChatInterface(
                respond_browser,
                additional_outputs=[live],
                examples=[
                    "There's a pothole about 6cm deep in the road on Western Bank, S10 2TN. Please report it anonymously.",
                    "A branch is hanging low over the pavement on Fargate. It isn't blocking it yet. Report it anonymously.",
                ],
                run_examples_on_click=True,
                cache_examples=False,
            )
        with gr.Column(scale=6):
            live.render()

ui = gr.TabbedInterface([demo, browser_mode], ["Report a problem", "Watch the agent fill in the form"],
                        title="CouncilTriagent")
with ui:
    ui.unload(_on_tab_closed)  # Close this visitor's browser when they close the page.

# Mount last so /health and /mock/ aren't shadowed by Gradio's routes.
app = gr.mount_gradio_app(app, ui, path="/")
