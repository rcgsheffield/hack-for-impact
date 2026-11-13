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

from langgraph.checkpoint.memory import InMemorySaver

from hack_for_impact.agent.llm import (FALLBACK_REPLY, build_agent, latest_checkpoint_id, new_thread_id,
                                       run_agent_events, user_turns)

from . import config, models, photos, submissions, usage
from .agent import ToolStep
from .browser_agent import BrowserSession, make_browser_agent, page_heading
from .tool_display import describe as describe_tool

app = FastAPI(title="CouncilTriagent")
app.include_router(usage.router)
app.include_router(submissions.router)
app.include_router(photos.router)
# Our page assets (src/app/static: report-card.js, ...) at /ui. Not /static: that's Gradio's own asset path,
# and mounting over it broke Gradio's fonts. Mounted before Gradio so it isn't shadowed.
app.mount("/ui", StaticFiles(directory=submissions.STATIC_DIR), name="ui")


@app.get("/health")
def health() -> JSONResponse:
    """200 if Ollama is reachable and has the agent-tier model, otherwise 503. Used by deploy.sh and check.sh.

    Also lists every model tier (src/app/models.py) and whether its model is on that Ollama; a missing small or large
    model is a warning, not a failure, because those turns fall back to the agent tier or simply fail on their own.
    """
    agent_model = models.spec("agent").model
    body = {"ok": False, "model": agent_model, "sha": config.GIT_SHA}
    try:
        body["ollama"] = httpx.get(f"{config.OLLAMA_URL}/api/version", timeout=3).raise_for_status().json()["version"]
        tags = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=3).raise_for_status().json()
        have = {m["name"] for m in tags.get("models", [])}
        body["models"] = {t: {"model": s.model, "where": s.where,
                              "available": s.model in have if s.provider == "ollama" and s.base_url == config.OLLAMA_URL
                              else None}
                          for t, s in models.all_specs().items()}
        if agent_model not in have and models.spec("agent").provider == "ollama":
            body["error"] = f"model {agent_model} not found in Ollama"
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


# One checkpointer per mode, shared by that mode's agents on every model tier, so a conversation can move from the
# small model to a bigger one mid-thread (src/app/models.py routes each turn).
_checkpointers: dict[str, InMemorySaver] = {}
# Threads where the small model fumbled: their later turns go straight to the agent tier.
_escalated: set[str] = set()


@cache
def get_agent(mode: str = "chat", tier: str = "agent"):
    """The LangChain agent for one branch ("chat" or "form") on one model tier. Built on first use."""
    return build_agent(model=models.chat_model(tier), mode=mode,
                       checkpointer=_checkpointers.setdefault(mode, InMemorySaver()))


def _route_message(tier: str, reason: str) -> gr.ChatMessage:
    s = models.spec(tier)
    return gr.ChatMessage(
        content=f"Picked the **{models.TIER_LABELS[tier]}** model because this is {reason}. Runs on {s.where}.",
        metadata={"title": f"🧭 {s.model} ({models.TIER_LABELS[tier]})", "status": "done"})


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
<section class="lp" aria-label="Problem location">
  <div class="lp-actions">
    <button type="button" class="lp-use">📍 Use my location</button>
    <button type="button" class="lp-clear" disabled>Clear pin</button>
  </div>
  <div class="lp-map" role="application" aria-label="Map of Sheffield. Click to drop a pin where the problem is."></div>
  <p class="lp-status" role="status" aria-live="polite">Loading map…</p>
</section>""",
    css_template="""
.lp-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.lp button { font: 600 var(--ct-text-md)/1.2 var(--ct-font-sans); min-height: 36px; padding: 0 14px; cursor: pointer;
             border-radius: var(--ct-radius-pill); border: 1px solid var(--ct-border-strong); background: var(--ct-surface);
             color: var(--ct-text); transition: background var(--ct-dur-fast) var(--ct-ease), border-color var(--ct-dur-fast) var(--ct-ease); }
.lp button.lp-use { background: var(--ct-brand); border-color: var(--ct-brand); color: var(--ct-on-brand); }
.lp button.lp-use:hover:not(:disabled) { background: var(--ct-brand-hover); }
.lp button.lp-clear:hover:not(:disabled) { background: var(--ct-surface-2); }
.lp button:disabled { opacity: .5; cursor: not-allowed; }
.lp button:focus-visible { outline: 3px solid var(--ct-focus); outline-offset: 2px; }
.lp-map { height: 300px; border-radius: var(--ct-radius); border: 1px solid var(--ct-border); overflow: hidden; }
.lp-status { margin: 8px 0 0; font-size: var(--ct-text-sm); color: var(--ct-text-2); }
@media (max-width: 720px) { .lp-map { height: 240px; } }""",
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


def _files(message) -> list[str]:
    """Paths of the files attached to a multimodal message ({"text", "files"})."""
    files = message.get("files", []) if isinstance(message, dict) else []
    return [f if isinstance(f, str) else (f.get("path") if isinstance(f, dict) else getattr(f, "path", "")) for f in files]


def photo_notes(message) -> str:
    """Save the message's photos safely (photos.save_upload) and return the note for the model: each photo_id, and
    any GPS position the phone recorded, which the agent must confirm before using. The chat shows the photo itself."""
    notes = []
    for path in _files(message)[:3]:
        try:
            saved = photos.save_upload(path)
        except (photos.PhotoError, OSError) as e:
            notes.append(f"[The user tried to attach a file that can't be used ({e}). Tell them, briefly.]")
            continue
        note = (f"[The user attached a photo: photo_id {saved['photo_id']}. Call analyse_photo with this photo_id "
                "first, and pass photo_id when filing so the photo is attached to the report.")
        if saved["gps"]:
            when = f", taken {saved['taken_at'][:16].replace('T', ' ')}" if saved["taken_at"] else ""
            note += (f" The photo's own GPS position is lat {saved['gps']['lat']}, lon {saved['gps']['lon']}{when}. "
                     "Ask the user to confirm this is where the problem is before using it as the location; you can "
                     "call nearest_address to name the street.")
        notes.append(note + "]")
    return ("\n\n" + "\n".join(notes)) if notes else ""


def respond(message, history: list[dict], mode: str | None, location: str | None,
            thread_id: str | None) -> Iterator[tuple[list[gr.ChatMessage], str]]:
    """One chat turn. Each conversation is a checkpointer thread keyed by a UUID held in the browser session.

    Normally only the new message is sent; the agent remembers earlier turns, tool results included. If the thread
    doesn't match the chat on screen (new chat, or the user retried, undid or edited a message), start a new
    thread seeded with the visible text history.
    """
    mode = mode or "chat"
    has_photo = bool(_files(message))
    text = _text(message) or ("(The user sent a photo without a message.)" if has_photo else "")
    # Model routing (src/app/models.py): text-only turns go to the small model, harder ones to a bigger one.
    tier, reason = models.route_turn(text, mode, has_image=has_photo,
                                     escalated=bool(thread_id) and thread_id in _escalated)
    # Each mode has its own checkpointer, so switching mode mid-chat starts a new thread (seeded below).
    agent = get_agent(mode, tier)
    # The location and photo notes go to the model only; the chat shows what the user typed. Photos are read by the
    # vision tier (photos.py) and reach the chat model as a text note.
    new_message = {"role": "user", "content": text + location_note(location) + photo_notes(message)}
    shown_turns = sum(m.get("role") == "user" for m in history)
    if thread_id and user_turns(agent, thread_id) == shown_turns:
        messages = [new_message]
        before = latest_checkpoint_id(agent, thread_id)
    else:
        thread_id = new_thread_id()
        messages = _to_model_history(history) + [new_message]
        before = None

    trouble = {"errors": 0, "failed": False}

    def watch(events):
        """Pass events through, noting signs that the small model is out of its depth."""
        try:
            for event in events:
                if isinstance(event, ToolStep) and isinstance(event.result, dict) and (
                        event.result.get("error") or event.result.get("errors")):
                    trouble["errors"] += 1
                if event == FALLBACK_REPLY:
                    trouble["failed"] = True
                    if tier == "small":
                        continue  # the bigger model redoes the turn below, so don't show this apology
                yield event
        except Exception:
            if tier != "small":
                raise
            trouble["failed"] = True  # retried on the bigger model below

    started = time.monotonic()
    route = _route_message(tier, reason)
    shown = [route]
    for shown in _show(watch(run_agent_events(agent, messages, thread_id)), shown):
        yield shown, thread_id

    if tier == "small" and (trouble["failed"] or trouble["errors"] >= 2):
        # Escalate: redo this turn on the agent tier from the checkpoint before it (or on a fresh thread).
        _escalated.add(thread_id)
        bigger = models.spec("agent")
        shown = shown + [gr.ChatMessage(
            content="The small model got stuck on this one, so a bigger model is redoing it.",
            metadata={"title": f"↗ Handing over to {bigger.model}", "status": "done"})]
        yield shown, thread_id
        if before is None:
            thread_id = new_thread_id()
            _escalated.add(thread_id)
        retry = run_agent_events(get_agent(mode, "agent"), messages, thread_id, checkpoint_id=before)
        for shown in _show(retry, shown):
            yield shown, thread_id

    route.metadata["duration"] = round(time.monotonic() - started, 1)
    yield shown, thread_id


def _show(events: Iterator[ToolStep | str], shown: list[gr.ChatMessage] | None = None) -> Iterator[list[gr.ChatMessage]]:
    """Turn agent events into chat bubbles: a collapsible one per tool call, then the reply, after any `shown`."""
    shown = list(shown or [])
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
            agent, session = make_browser_agent(tier="large", screenshots=True)
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


def location_label(location: str | None) -> str:
    """The location panel's title, so people can see whether a pin is set while it's collapsed."""
    m = LOCATION_RE.match(location or "")
    if not m:
        return "📍 Add a location (optional)"
    return "📍 Location: " + ("pin on the map ✓" if m.group(4) else "your current location ✓")


EXAMPLES = [
    ("🕳️ Deep pothole on Fargate",
     "There's a really deep pothole outside 10 Fargate, about 5cm deep. A cyclist nearly came off."),
    ("🌳 Branch down on Derbyshire Lane",
     "A big branch has come down across the pavement on Derbyshire Lane outside number 12"),
    ("📍 Pothole where I'm standing", "There's a pothole right here where I'm standing, about two inches deep"),
    ("🛣️ Stocksbridge Bypass pothole", "Huge pothole on the Stocksbridge Bypass heading north"),
    ("🅿️ Supermarket car park", "The supermarket car park on Abbeydale Road is full of potholes"),
]

FIRST_PLACEHOLDER = "Describe the problem and where it is, or add a photo…"
REPLY_PLACEHOLDER = "Reply, or describe another problem…"

WELCOME = """<div class="ct-intro">
<img class="ct-intro__mark" src="/ui/logo-mark.svg" alt="" width="72" height="72">
<h2 class="ct-intro__title">Tell us what's wrong and where</h2>
<p class="ct-intro__lead">Describe a pothole, damaged pavement or street tree problem in your own words. The assistant \
checks who's responsible, asks for anything missing, and files the report. You can add a photo (📎) and a location on \
the map below. Photos are checked by a vision model on this machine, and their location and camera details are \
removed.</p>
</div>"""

# Map Gradio's theme onto the design system's tokens (src/app/static/ui.css). The tokens switch themselves for dark
# mode (OS setting or Gradio's .dark class), so the light and *_dark values are the same var(--ct-*).
_THEME_TOKENS = {
    "body_background_fill": "var(--ct-bg)",
    "body_text_color": "var(--ct-text)",
    "body_text_color_subdued": "var(--ct-muted)",
    "color_accent_soft": "var(--ct-brand-soft)",
    "background_fill_primary": "var(--ct-surface)",
    "background_fill_secondary": "var(--ct-surface-2)",
    "border_color_primary": "var(--ct-border)",
    "border_color_accent": "var(--ct-leaf)",
    "border_color_accent_subdued": "var(--ct-brand-soft-2)",
    "link_text_color": "var(--ct-brand-text)",
    "link_text_color_hover": "var(--ct-brand-text)",
    "link_text_color_visited": "var(--ct-brand-text)",
    "link_text_color_active": "var(--ct-brand-text)",
    "block_background_fill": "var(--ct-surface)",
    "block_border_color": "var(--ct-border)",
    "block_info_text_color": "var(--ct-muted)",
    "block_label_background_fill": "var(--ct-surface)",
    "block_label_text_color": "var(--ct-text-2)",
    "block_title_text_color": "var(--ct-text)",
    "panel_background_fill": "var(--ct-surface-2)",
    "panel_border_color": "var(--ct-border)",
    "accordion_text_color": "var(--ct-text)",
    "code_background_fill": "var(--ct-surface-2)",
    "input_background_fill": "var(--ct-surface)",
    "input_background_fill_focus": "var(--ct-surface)",
    "input_border_color": "var(--ct-input-border)",
    "input_border_color_hover": "var(--ct-brand)",
    "input_border_color_focus": "var(--ct-brand)",
    "input_placeholder_color": "var(--ct-muted)",
    "input_shadow_focus": "0 0 0 3px var(--ct-focus-halo)",
    "button_primary_background_fill": "var(--ct-brand)",
    "button_primary_background_fill_hover": "var(--ct-brand-hover)",
    "button_primary_border_color": "var(--ct-brand)",
    "button_primary_text_color": "var(--ct-on-brand)",
    "button_secondary_background_fill": "var(--ct-surface)",
    "button_secondary_background_fill_hover": "var(--ct-surface-2)",
    "button_secondary_border_color": "var(--ct-border-strong)",
    "button_secondary_text_color": "var(--ct-text)",
    "checkbox_label_background_fill": "var(--ct-surface)",
    "checkbox_label_background_fill_hover": "var(--ct-surface-2)",
    "checkbox_label_background_fill_selected": "var(--ct-brand-soft)",
    "checkbox_label_border_color": "var(--ct-border)",
    "checkbox_label_border_color_hover": "var(--ct-border-strong)",
    "checkbox_label_border_color_selected": "var(--ct-leaf)",
    "checkbox_label_text_color": "var(--ct-text-2)",
    "checkbox_label_text_color_selected": "var(--ct-brand-text)",
    "checkbox_border_color": "var(--ct-input-border)",
    "checkbox_border_color_selected": "var(--ct-brand)",
    "checkbox_border_color_focus": "var(--ct-brand)",
    "table_border_color": "var(--ct-border)",
    "error_background_fill": "var(--ct-danger-soft)",
    "error_border_color": "var(--ct-danger-border)",
    "error_text_color": "var(--ct-danger-text)",
}
THEME = gr.themes.Base(
    primary_hue="green",
    neutral_hue="slate",
    text_size=gr.themes.sizes.text_md,
    radius_size=gr.themes.sizes.radius_lg,
    font=["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
    font_mono=["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
).set(
    color_accent="var(--ct-brand)",
    block_radius="var(--ct-radius-lg)",
    block_shadow="var(--ct-shadow-xs)",
    button_primary_shadow="var(--ct-shadow-sm)",
    **{k: v for key, v in _THEME_TOKENS.items() for k in (key, f"{key}_dark")},
)

# The shared site header from the design system (see /ui/styleguide.html), above the tabs.
SITE_HEADER = f"""<header class="ct-header ct-header--wide">
  <div class="ct-header__inner">
    <a class="ct-brand" href="/" aria-label="CouncilTriagent home">
      <img class="ct-brand__mark" src="/ui/logo-mark.svg" alt="" width="32" height="32">
      <span class="ct-brand__text"><span class="ct-brand__name">Council<b>Triagent</b></span><span class="ct-brand__sub">Report a Sheffield street problem</span></span>
    </a>
    <nav class="ct-nav" aria-label="Main">
      <a href="/" aria-current="page">Chat</a>
      <a href="/dashboard">Dashboard</a>
    </nav>
    <div class="ct-header__meta">
      <span class="ct-badge ct-pill ct-pill--local" title="Models: {' · '.join(f'{t} {s.model}' for t, s in models.all_specs().items() if t != 'vision')}">Runs locally on DGX Spark</span>
      <span class="ct-badge ct-pill ct-pill--prototype">Prototype</span>
    </div>
  </div>
</header>
<div class="ct-strip"><div class="ct-strip__inner"><strong>Unofficial hackathon prototype.</strong> \
Nothing is sent to Sheffield City Council.</div></div>"""

HEAD = '<link rel="stylesheet" href="/ui/ui.css">'

CSS = """
/* Page-specific styling for the chat page; tokens and ct-* components come from /ui/ui.css. */
body, gradio-app { background: var(--ct-bg) !important; }
.gradio-container { max-width: none !important; padding: 0 !important; margin: 0 !important; }
.gradio-container > .main, .gradio-container .main.app { padding: 0 !important; max-width: none !important; margin: 0 !important; }
#ct-site .html-container { padding: 0 !important; }
.ct-brand__text { text-align: left; }
.gradio-container .contain { padding: 0 !important; gap: 0 !important; }
#ct-site { padding: 0 !important; margin: 0 !important; border: 0 !important; background: none !important; }
#ct-site > div, #ct-site .prose { max-width: none !important; }
.ct-header--wide .ct-header__inner, .ct-header--wide + .ct-strip .ct-strip__inner { max-width: 1120px; }
.ct-brand, .ct-brand:hover, .ct-nav a { text-decoration: none !important; }
.ct-brand__name, .ct-nav a { color: inherit; }

/* Tabs: underline style, aligned with the header */
#ct-tabs { max-width: 1120px; margin: 0 auto; padding: 12px 16px 24px !important; width: 100%; box-sizing: border-box;
           background: none !important; border: 0 !important; }
#ct-tabs .tab-wrapper { border-bottom: 1px solid var(--ct-border); margin-bottom: 16px; }
#ct-tabs button[role="tab"] { font-weight: 600; color: var(--ct-text-2); font-size: var(--ct-text-md); }
#ct-tabs button[role="tab"][aria-selected="true"] { color: var(--ct-brand-text); }
#ct-tabs button[role="tab"][aria-selected="true"]::after { background: var(--ct-brand) !important; height: 3px !important; }
#ct-tabs > .tabitem, #ct-tabs .tabitem { padding: 0 !important; border: 0 !important; background: none !important; }
#ct-chat-tab { max-width: var(--ct-container-chat); margin: 0 auto; width: 100%; }

/* Chat */
#ct-chat { border-radius: var(--ct-radius-lg) !important; border: 1px solid var(--ct-border) !important;
           background: var(--ct-surface) !important; box-shadow: var(--ct-shadow-sm) !important; }
#ct-chat .placeholder { max-width: 38rem; margin: 0 auto; padding: 0 1rem; }
#ct-chat .placeholder .ct-intro { padding-bottom: var(--ct-space-2); }
#ct-chat .placeholder .ct-intro__title { border: 0; }
#ct-chat .examples { display: flex !important; flex-wrap: wrap; justify-content: center; gap: 8px !important;
                     padding: 0 1rem 1rem; }
#ct-chat button.example { border: 1px solid var(--ct-border) !important; border-radius: var(--ct-radius-pill) !important;
                          padding: 9px 16px !important; background: var(--ct-surface) !important; color: var(--ct-text) !important;
                          width: auto !important; flex: 0 0 auto; box-shadow: var(--ct-shadow-xs);
                          font-size: var(--ct-text-md) !important; font-weight: 500;
                          transition: border-color var(--ct-dur-fast) var(--ct-ease), background var(--ct-dur-fast) var(--ct-ease); }
#ct-chat button.example:hover { border-color: var(--ct-leaf) !important; background: var(--ct-brand-soft) !important; }
#ct-chat button.example .example-text, #ct-chat button.example span { color: inherit !important; }
#ct-chat .message.user, #ct-chat .user .message { background: var(--ct-brand) !important; color: var(--ct-on-brand) !important;
                          border-color: var(--ct-brand) !important; border-radius: 18px 18px 4px 18px !important; }
#ct-chat .message.user *, #ct-chat .user .message * { color: inherit !important; }
#ct-chat .message.bot, #ct-chat .bot .message { background: var(--ct-surface-2) !important; color: var(--ct-text) !important;
                          border: 1px solid var(--ct-border) !important; border-radius: 18px 18px 18px 4px !important; }
/* Tool steps: compact cards with a gold "local AI" dot */
#ct-chat .thought-group, #ct-chat .message.bot:has(.thought) { background: var(--ct-surface) !important;
                          border: 1px dashed var(--ct-border-strong) !important; border-radius: var(--ct-radius) !important; }
#ct-chat .thought .title, #ct-chat .message-content .title { font-size: var(--ct-text-sm); font-weight: 650; color: var(--ct-text-2); }
#ct-chat pre, #ct-chat code { background: var(--ct-surface-2) !important; font-size: var(--ct-text-sm); }

/* Message box */
.gradio-container textarea { font-size: var(--ct-text-base) !important; }
.gradio-container button.submit-button { background: var(--ct-brand) !important; color: var(--ct-on-brand) !important;
                                         border-radius: var(--ct-radius-pill) !important; }
.gradio-container button.submit-button:hover { background: var(--ct-brand-hover) !important; }

/* Location panel and mode control */
#ct-tools { gap: 12px; align-items: stretch; margin-top: 4px; }
#ct-tools > .column { min-width: 0; }
#ct-location { border-radius: var(--ct-radius-lg) !important; box-shadow: var(--ct-shadow-xs); }
#ct-location > button span, #ct-location .label-wrap span { font-weight: 650; font-size: var(--ct-text-md); }
#ct-mode-box { background: var(--ct-surface); border: 1px solid var(--ct-border); border-radius: var(--ct-radius-lg);
               padding: 12px 14px !important; box-shadow: var(--ct-shadow-xs); gap: 8px !important; }
#ct-mode-box .prose p, #ct-mode-box p { margin: 0; font-size: var(--ct-text-md); }
#ct-mode { padding: 0 0 0 2px !important; background: none !important; border: 0 !important; }
#ct-mode .wrap { gap: 6px; }
#ct-mode label { padding: 6px 12px !important; font-size: var(--ct-text-md); border-radius: var(--ct-radius-pill) !important; }
#ct-mode label.selected { font-weight: 650; }
#ct-mode [data-testid="block-info"], #ct-mode .info { font-size: var(--ct-text-sm); color: var(--ct-muted); }

/* Browser-mode tab */
#ct-browser-intro { font-size: var(--ct-text-md); }
footer { display: none !important; }
@media (max-width: 720px) {
  #ct-tabs { padding: 8px 12px 16px !important; }
  #ct-tabs button[role="tab"] { font-size: var(--ct-text-sm); padding-inline: 8px; }
  #ct-chat .placeholder .ct-intro { padding: var(--ct-space-3) 0 var(--ct-space-1); gap: 4px; }
  #ct-chat .ct-intro__mark { display: none; }
  .ct-intro__title { font-size: var(--ct-text-lg) !important; }
  .ct-intro__lead { font-size: var(--ct-text-md) !important; }
  #ct-chat button.example { padding: 7px 12px !important; font-size: var(--ct-text-sm) !important; }
}
"""

with gr.Blocks(title="CouncilTriagent") as demo:
    thread_state = gr.State(None)
    # The controls go under the chat, but ChatInterface needs its extra inputs to exist already (otherwise it
    # renders them in its own accordion). So build the row now without placing it, and place it after the chat.
    with gr.Row(elem_id="ct-tools", equal_height=False, render=False) as tools_row:
        with gr.Column(scale=3, min_width=300):
            with gr.Accordion(location_label(None), open=False, elem_id="ct-location") as location_panel:
                location_pin.render()
        with gr.Column(scale=2, min_width=240, elem_id="ct-mode-box"):
            gr.Markdown("**How should reports be filed?**")
            mode_radio = gr.Radio(
                [("💬 Chat", "chat"), ("🖥️ Web form", "form")], value="chat", show_label=False, container=False,
                elem_id="ct-mode",
                info="Chat: the assistant records the report itself. Web form: it fills in the council's form in a browser.",
            )

    chat = gr.ChatInterface(
        respond,
        # Fill the screen, leaving room for the header, message box and controls (all visible at 1280x800).
        chatbot=gr.Chatbot(height="calc(100vh - 400px)", min_height=360, show_label=False, placeholder=WELCOME, elem_id="ct-chat",
                           layout="bubble", group_consecutive_messages=True),
        # Text plus photos: the paperclip opens the camera or gallery on a phone. Photos go through photo_notes().
        multimodal=True,
        textbox=gr.MultimodalTextbox(placeholder=FIRST_PLACEHOLDER, show_label=False, lines=1, max_lines=6,
                                     submit_btn=True, autofocus=True, file_types=["image"], file_count="multiple",
                                     sources=["upload"]),
        additional_inputs=[mode_radio, location_pin, thread_state],
        additional_outputs=[thread_state],
        # One column per input: message, mode, location, thread id. None leaves those as they are.
        examples=[[{"text": text, "files": []}, None, None, None] for _, text in EXAMPLES],
        example_labels=[label for label, _ in EXAMPLES],
        run_examples_on_click=True,
        cache_examples=False,
    )

    tools_row.render()
    # ChatInterface blanks the placeholder when a message is sent and never restores it; put it back.
    chat.chatbot.change(lambda history: gr.MultimodalTextbox(placeholder=REPLY_PLACEHOLDER if history else FIRST_PLACEHOLDER),
                        chat.chatbot, chat.textbox, show_progress="hidden", queue=False)
    location_pin.change(lambda v: gr.Accordion(label=location_label(v)), location_pin, location_panel,
                        show_progress="hidden", queue=False)


with gr.Blocks() as browser_mode:
    gr.Markdown(elem_id="ct-browser-intro", value=
        "The agent opens the council's report form in a browser and fills it in itself, page by page, like a "
        f"person would. The browser runs on NVIDIA DGX Spark with the model ({models.spec('large').model}); the picture "
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

# The page: the shared site header, then one tab per mode.
with gr.Blocks(title="CouncilTriagent") as ui:
    gr.HTML(SITE_HEADER, elem_id="ct-site", container=False, padding=False)
    with gr.Tabs(elem_id="ct-tabs"):
        with gr.Tab("Report a problem", elem_id="ct-chat-tab"):
            demo.render()
        with gr.Tab("Watch the agent fill in the form"):
            browser_mode.render()
    ui.unload(_on_tab_closed)  # Close this visitor's browser when they close the page.

# Mount last so /health and /mock/ aren't shadowed by Gradio's routes.
app = gr.mount_gradio_app(app, ui, path="/", theme=THEME, css=CSS, head=HEAD, footer_links=[],
                          favicon_path=submissions.STATIC_DIR / "favicon.svg")
