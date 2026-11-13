"""A general browser agent: the model reads each page and clicks, types and selects its way through a council form.

Unlike the form toolkits (pothole_form_toolkit.py, tree_form_toolkit.py), nothing here knows any form's fields.
The browser is driven by the Playwright MCP server (https://github.com/microsoft/playwright-mcp), run with npx.
Its tools are wrapped as a few LangChain tools that each return the page afterwards, trimmed to the <main> part,
so a small model sees the effect of every action and always has fresh element refs (e57, ...) to act on.

Needs Node.js (for npx) and Playwright's browser build, once per machine:
    npx -y @playwright/mcp@0.0.83 install-browser firefox     # version: config.BROWSER_MCP_PACKAGE

Try it in the terminal (serve the mock pages first, e.g. by running the app, which serves them at /mock/):
    uv run python -m app.form_agent_cli browser --headed
"""

from __future__ import annotations

import asyncio
import re
import shlex
import shutil
import tempfile
import textwrap
import threading
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from . import config

# Forms the agent may open, relative to config.BROWSER_FORMS_URL.
FORMS = {
    "a pothole or crack in a road, pavement or cycle path": "report_pothole_crack.html",
    "a problem with a tree": "report_tree.html",
}
MAX_PAGE_CHARS = 12000  # A form page is ~2-5k characters once trimmed; this only guards against runaway pages.
STARTUP_TIMEOUT_S = 120  # The first npx run may download the package.
CALL_TIMEOUT_S = 60


class BrowserError(Exception):
    """The browser couldn't start, or a browser action failed (bad ref, element not found, ...)."""


class BrowserSession:
    """One Playwright MCP server, and so one browser, for one conversation. Started on first use.

    The MCP client is async and must stay in the event loop that opened it, so it lives on its own thread
    and the sync methods here hand calls to that loop. This keeps the agent and the Gradio app synchronous.
    """

    def __init__(self, headless: bool = config.BROWSER_HEADLESS, browser: str = config.BROWSER_NAME,
                 command: str = config.BROWSER_MCP_COMMAND, slow_mo_ms: int = 0):
        # slow_mo_ms is accepted for the same constructor as the form sessions; Playwright MCP has no slow-mo.
        self.headless, self.browser, self.command = headless, browser, command
        self.workdir: Path | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._session: Any = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    def _server_args(self) -> list[str]:
        args = shlex.split(self.command) + ["--browser", self.browser, "--isolated",
                                            # Actions return a short note; we fetch the page ourselves, inline.
                                            "--snapshot-mode", "none", "--image-responses", "omit",
                                            "--output-dir", str(self.workdir),
                                            "--viewport-size", config.BROWSER_VIEWPORT,
                                            # Give the address search time to fetch results after a click.
                                            "--timeout-settle", "1500"]
        return args + (["--headless"] if self.headless else [])

    def _start(self) -> None:
        if self._thread is not None:
            if self._error is not None:
                raise BrowserError(f"The browser stopped: {self._error}")
            return
        # The server's working directory: its output files go here, and uploads must come from here.
        self.workdir = Path(tempfile.mkdtemp(prefix="browser-agent-"))
        self._thread = threading.Thread(target=self._thread_main, name="browser-agent", daemon=True)
        self._thread.start()
        if not self._ready.wait(STARTUP_TIMEOUT_S):
            raise BrowserError("Timed out starting the browser.")
        if self._error is not None:
            raise BrowserError(f"Could not start the browser ({self.command}): {self._error}. Is Node.js installed, "
                               f"and has `npx -y {config.BROWSER_MCP_PACKAGE} install-browser {self.browser}` been run?")

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as e:  # noqa: BLE001  (reported to the caller via _start/call)
            self._error = self._error or e
        finally:
            self._ready.set()

    async def _serve(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        cmd, *args = self._server_args()
        params = StdioServerParameters(command=cmd, args=args, cwd=str(self.workdir))
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            self._session = session
            self._ready.set()
            await self._stop.wait()

    def call(self, tool: str, args: dict | None = None) -> str:
        """Run a Playwright MCP tool and return its text. Raises BrowserError if it failed."""
        with self._lock:
            self._start()
            future = asyncio.run_coroutine_threadsafe(self._session.call_tool(tool, args or {}), self._loop)
            try:
                result = future.result(CALL_TIMEOUT_S)
            except Exception as e:  # noqa: BLE001
                raise BrowserError(f"{tool} failed: {type(e).__name__}: {e}") from e
        text = "\n".join(c.text for c in getattr(result, "content", []) if getattr(c, "type", "") == "text")
        if getattr(result, "is_error", False) or text.lstrip().startswith("### Error"):
            raise BrowserError(error_message(text))
        return text

    def close(self) -> None:
        with self._lock:
            if self._loop is not None and self._stop is not None and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._stop.set)
            if self._thread is not None:
                self._thread.join(timeout=15)
            if self.workdir is not None:
                shutil.rmtree(self.workdir, ignore_errors=True)
            self._thread = self._loop = self._stop = self._session = self.workdir = None
            self._ready.clear()
            self._error = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def error_message(text: str) -> str:
    """'### Error\\nError: Ref e9 not found...' -> 'Ref e9 not found...'"""
    text = re.sub(r"^\s*### Error\s*", "", text)
    return re.sub(r"^Error:\s*", "", text).strip() or "unknown error"


def trim_snapshot(text: str, max_chars: int = MAX_PAGE_CHARS) -> str:
    """Cut a browser_snapshot result down to what a model needs: title, URL and the <main> part of the page.

    Drops the header, navigation and footer (identical on every page) and link targets, which roughly halves it.
    """
    url = re.search(r"- Page URL: (.*)", text)
    title = re.search(r"- Page Title: (.*)", text)
    block = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
    lines = (block.group(1) if block else text).splitlines()

    start = next((i for i, line in enumerate(lines) if re.match(r"\s*- main\b", line)), None)
    if start is not None:
        indent = len(lines[start]) - len(lines[start].lstrip())
        end = next((j for j in range(start + 1, len(lines))
                    if lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) <= indent), len(lines))
        lines = lines[start:end]
    lines = [line for line in lines if not line.strip().startswith("- /url:")]
    body = textwrap.dedent("\n".join(lines)).strip()
    if len(body) > max_chars:
        body = body[:max_chars] + "\n... (rest of page cut)"
    head = [f"Page: {title.group(1).strip()}" if title else "", f"URL: {url.group(1).strip()}" if url else ""]
    return "\n".join(filter(None, head + [body]))


def clean_ref(ref: str) -> str:
    """Accept what small models tend to send: 'e57', '[ref=e57]', 'ref=e57'."""
    ref = ref.strip().strip("[]").strip()
    return ref.split("=", 1)[1].strip() if ref.startswith("ref=") else ref


REVIEW_HEADING = re.compile(r"review|check your answers|confirm", re.IGNORECASE)
FINAL_SUBMIT = re.compile(r"^(submit|send)\b", re.IGNORECASE)
NOT_CONFIRMED = ("NOT CLICKED: this button sends the form. First tell the user the answers on this page and ask "
                 "them to confirm. Then stop and wait for their reply. Click it only after they agree.")


def page_heading(page: str) -> str:
    m = re.search(r'heading "([^"]+)"[^\n]*\[level=1\]', page)  # May have [active] etc. before [level=1].
    return m.group(1) if m else ""


def form_errors(page: str) -> list[str]:
    """Validation messages shown by GOV.UK-style forms, e.g. 'Error: Enter a valid email address'."""
    return list(dict.fromkeys(m.strip() for m in re.findall(r'Error: ([^"\n]+)', page)))


def element_at(page: str, ref: str) -> tuple[str, str]:
    """(role, name) of the element with this ref on the page, e.g. ('button', 'Submit'), or ('', '') if absent."""
    m = re.search(rf'- \'?(\w+)(?: "([^"]*)")?[^\n]*\[ref={re.escape(ref)}\]', page)
    return (m.group(1), m.group(2) or "") if m else ("", "")


CLICKABLE = {"button", "link", "radio", "checkbox", "textbox", "tab", "menuitem", "switch", "option"}


def clickable_inside(page: str, ref: str) -> list[str]:
    """'button "Next" [ref=e31]'-style descriptions of the clickable elements inside a container."""
    lines = page.splitlines()
    start = next((i for i, line in enumerate(lines) if f"[ref={ref}]" in line), None)
    if start is None:
        return []
    indent = len(lines[start]) - len(lines[start].lstrip())
    found = []
    for line in lines[start + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        m = re.search(r'- \'?(\w+) "([^"]*)"[^\n]*\[ref=(\w+)\]', line)
        if m and m.group(1) in CLICKABLE:
            found.append(f'{m.group(1)} "{m.group(2)}" [ref={m.group(3)}]')
    return found


class BrowserTools:
    """The actions the agent can take. Each returns a status line and then the page as it is now.

    Two guards don't rely on the model following its prompt:
    - The final Submit on a review page is refused until the user has replied in a later turn, so the agent
      has to show the answers and ask before it sends anything. start_turn() marks each new user message.
    - After an action, any validation errors are repeated in the status line, and an unchanged page is pointed
      out, because small models miss them in the page and retry the same click.
    """

    def __init__(self, session: BrowserSession, forms_url: str = config.BROWSER_FORMS_URL, screenshots: bool = False):
        self.session = session
        self.forms_url = forms_url if forms_url.endswith("/") else forms_url + "/"
        self.last_page = ""
        self.turn = 0
        self.confirm_asked_turn: int | None = None
        # For the chat UI's live view: a screenshot after every action, in the server's working directory.
        self.screenshots = screenshots
        self.last_screenshot: Path | None = None
        self._shots = 0

    def start_turn(self) -> None:
        self.turn += 1

    def _screenshot(self) -> None:
        if not self.screenshots or self.session.workdir is None:
            return
        self._shots += 1
        name = f"shot-{self._shots}.png"  # A new name each time, so viewers never get a cached image.
        try:
            self.session.call("browser_take_screenshot", {"filename": name, "type": "png", "scale": "css"})
        except BrowserError:
            return  # The live view just keeps the previous picture.
        previous, self.last_screenshot = self.last_screenshot, self.session.workdir / name
        if previous is not None:
            previous.unlink(missing_ok=True)

    def page(self) -> str:
        try:
            self.last_page = trim_snapshot(self.session.call("browser_snapshot"))
        except BrowserError as e:
            return f"(Could not read the page: {e})"
        return self.last_page

    def _act(self, tool: str, args: dict, done: str) -> str:
        before = self.last_page
        try:
            self.session.call(tool, args)
            status = f"Done: {done}."
        except BrowserError as e:
            status = f"ERROR: {e}"
        page = self.page()
        self._screenshot()
        # Only after clicks: a form re-checks its answers when a button is pressed, so after typing the old
        # error messages are still on the page and repeating them would send the model round in circles.
        if tool == "browser_click" and status.startswith("Done"):
            if page == before:
                status += " Nothing changed on the page."
            if errors := form_errors(page):
                status += " The form shows these errors, fix them and then click the button again: " + \
                          "; ".join(errors) + "."
        return f"{status}\n\nThe page now:\n{page}"

    def open_page(self, url: str) -> str:
        url = url.strip()
        if "://" not in url:  # Allow just the file name, e.g. "report_tree.html".
            url = self.forms_url + url.lstrip("/")
        if not url.startswith(self.forms_url):
            forms = ", ".join(self.forms_url + f for f in FORMS.values())
            return f"ERROR: You can only open the council forms: {forms}"
        return self._act("browser_navigate", {"url": url}, f"opened {url}")

    def read_page(self) -> str:
        return self.page()

    def click(self, ref: str, element: str = "") -> str:
        ref = clean_ref(ref)
        role, name = element_at(self.last_page, ref)
        label = name or element or ref
        if role == "combobox":
            return f"ERROR: {ref} is a dropdown. Use select_option with the option's text.\n\nThe page now:\n{self.last_page}"
        if role and role not in CLICKABLE:  # e.g. a 'generic' box around the buttons: clicking it does nothing.
            inside = clickable_inside(self.last_page, ref)
            hint = f" Inside it: {', '.join(inside)}." if inside else ""
            return (f"ERROR: {ref} is a {role}, not a button, link or radio button, so clicking it does nothing."
                    f"{hint} Use the ref of the element itself.\n\nThe page now:\n{self.last_page}")
        if role == "button" and FINAL_SUBMIT.match(name) and REVIEW_HEADING.search(page_heading(self.last_page)):
            if self.confirm_asked_turn is None or self.confirm_asked_turn == self.turn:
                self.confirm_asked_turn = self.turn
                return f"{NOT_CONFIRMED}\n\nThe page now:\n{self.last_page}"
            self.confirm_asked_turn = None
        return self._act("browser_click", {"target": ref, "element": label}, f"clicked {label}")

    def type_text(self, ref: str, text: str, element: str = "") -> str:
        return self._act("browser_type", {"target": clean_ref(ref), "text": text, "element": element or ref},
                         f"typed into {element or ref}")

    def select_option(self, ref: str, option: str, element: str = "") -> str:
        return self._act("browser_select_option",
                         {"target": clean_ref(ref), "values": [option], "element": element or ref},
                         f"selected {option!r}")

    def wait_for_text(self, text: str) -> str:
        return self._act("browser_wait_for", {"text": text, "time": 15}, f"{text!r} is on the page")

    def upload_file(self, ref: str, path: str, element: str = "") -> str:
        src = Path(path).expanduser()
        if not src.is_file():
            return f"ERROR: No file at {path}.\n\nThe page now:\n{self.page()}"
        try:
            self.session.call("browser_click", {"target": clean_ref(ref), "element": element or ref})
            # The MCP server only reads files from its own working directory.
            copy = self.session.workdir / src.name
            shutil.copyfile(src, copy)
            return self._act("browser_file_upload", {"paths": [str(copy)]}, f"uploaded {src.name}")
        except BrowserError as e:
            return f"ERROR: {e}\n\nThe page now:\n{self.page()}"


class UrlArgs(BaseModel):
    url: str = Field(description="Full URL of the form, or just its file name, e.g. report_tree.html")


class NoArgs(BaseModel):
    pass


class RefArgs(BaseModel):
    ref: str = Field(description="The element's ref from the latest page, e.g. e57")
    element: str = Field("", description="What the element is, e.g. 'Road radio button'")


class TypeArgs(RefArgs):
    text: str = Field(description="Text to type. Replaces what is in the box.")


class SelectArgs(RefArgs):
    option: str = Field(description="The option's text exactly as it appears on the page")


class WaitArgs(BaseModel):
    text: str = Field(description="Text to wait for, e.g. 'Select the address'")


class UploadArgs(RefArgs):
    path: str = Field(description="Path of the photo or file the user gave")


def browser_tools(t: BrowserTools) -> list[BaseTool]:
    def tool(fn, description: str, args_schema: type[BaseModel]) -> StructuredTool:
        return StructuredTool.from_function(func=fn, name=fn.__name__, description=description, args_schema=args_schema)

    return [
        tool(t.open_page, "Open a council form in the browser. Returns the page.", UrlArgs),
        tool(t.read_page, "Read the current page again.", NoArgs),
        tool(t.click, "Click a button, link, radio button or checkbox. Returns the page afterwards.", RefArgs),
        tool(t.type_text, "Type into a text box. Returns the page afterwards.", TypeArgs),
        tool(t.select_option, "Choose an option in a dropdown (combobox). Returns the page afterwards.", SelectArgs),
        tool(t.wait_for_text, "Wait until some text appears on the page, e.g. search results. Returns the page.",
             WaitArgs),
        tool(t.upload_file, "Upload a file using an upload button. Returns the page afterwards.", UploadArgs),
    ]


SYSTEM_PROMPT = f"""You fill in Sheffield City Council web forms for residents by using a web browser.

Forms (open the one that fits):
{chr(10).join(f"- {what}: {name}" for what, name in FORMS.items())}

How the browser works:
- Every tool returns the page as a list of elements. Each element has a ref like [ref=e57].
- Act on ONE element at a time, using a ref from the MOST RECENT page. Old refs stop working.
- Radio buttons and buttons: click. Text boxes: type_text. Dropdowns: select_option with the option's text.
- If a tool returns ERROR, read the page it returns and try again.
- If the browser is already open on a form, carry on from that page. Only open a form again for a new report.

How to fill in a form:
1. Make sure you know what the problem is and where it is. Ask ONE short question only if something needed is missing.
2. Open the form. Choose "Submit a request without signing in", then click Next.
3. Answer each question with what the user told you. Questions can appear after you answer another one.
4. Location: type the street name or postcode into the search box and click "Find address". Then use
   select_option to choose the address from the list that matches (only choose "Use what I typed" if none match),
   and after that click "Use this address". Do not click the map.
5. Submit anonymously unless the user wants updates and has given their name and contact details.
6. On "Review your request", tell the user the answers and ask them to confirm. Click Submit only after they agree.
7. On "Request submitted", give the user the reference number shown on the page. Never make up a reference number.

This is a test copy of the council's forms: say that nothing is sent to the council. Use British English and keep
replies short."""


BROWSER_STATE_NOTE = ("\n\n(System note: the browser is still open where you left it. Carry on from this page; "
                      "only open a form again for a new report.)\nThe page now:\n")


class BrowserAgent:
    """The LangChain agent, plus two things at the start of each user message:

    - marks the new turn, for the confirm-before-submit guard;
    - adds the page the browser is on to the user's message. The chat UI only sends the visible chat text, not
      earlier tool calls, so without this the model doesn't know the form is already open (and starts again).

    Supports the two calls our runners make: stream() (app and CLI) and invoke().
    """

    def __init__(self, agent, tools: BrowserTools):
        self.agent, self.tools = agent, tools

    def _prepare(self, input: dict) -> dict:
        self.tools.start_turn()
        messages = list(input.get("messages") or [])
        if not self.tools.last_page or not messages:
            return input
        last, note = messages[-1], BROWSER_STATE_NOTE + self.tools.last_page
        if isinstance(last, dict) and last.get("role") == "user":
            messages[-1] = {**last, "content": f"{last.get('content', '')}{note}"}
        elif isinstance(last, HumanMessage):
            messages[-1] = HumanMessage(content=f"{last.content}{note}")
        else:
            return input
        return {**input, "messages": messages}

    def stream(self, input: dict, *args, **kwargs):
        return self.agent.stream(self._prepare(input), *args, **kwargs)

    def invoke(self, input: dict, *args, **kwargs):
        return self.agent.invoke(self._prepare(input), *args, **kwargs)


def make_browser_agent(session: BrowserSession | None = None, model: str | None = None, tier: str = "large",
                       max_steps: int = config.BROWSER_MAX_AGENT_STEPS, forms_url: str = config.BROWSER_FORMS_URL,
                       screenshots: bool = False, **llm_kwargs):
    """A LangChain agent on the `tier` model (src/app/models.py; "large" by default, since it reads whole web pages)
    with the browser tools. Returns (agent, session). `model` overrides just the model name.

    screenshots=True keeps agent.tools.last_screenshot up to date after every action (the chat UI's live view).
    llm_kwargs go to ChatOllama; num_ctx defaults to config.BROWSER_NUM_CTX because every step adds a page.
    """
    from .council_form import make_agent

    session = session or BrowserSession()
    tools = BrowserTools(session, forms_url, screenshots=screenshots)
    llm_kwargs.setdefault("num_ctx", config.BROWSER_NUM_CTX)
    agent = make_agent(browser_tools(tools), SYSTEM_PROMPT, model, tier=tier, **llm_kwargs)
    # Each model call plus its tool round is two graph steps.
    return BrowserAgent(agent.with_config({"recursion_limit": 2 * max_steps + 1}), tools), session
