"""Shared browser driver and LangChain tools for the mock council forms in src/mock/.

The mocks share one portal shell: Before you start -> About the problem -> About the location -> About you
-> Review your request -> Request submitted. Only "About the problem" differs per form, so each form toolkit
(pothole_form_toolkit.py, tree_form_toolkit.py) subclasses CouncilFormSession, adds its own problem step,
and reuses the common tools from common_tools().

Each tool returns JSON with the page the browser is now on and any validation errors the form showed,
so the model can correct itself. Nothing is sent to the council; the mocks record submissions in the browser.

Browser setup (once per machine):
    uv run playwright install chromium            # or set FORM_BROWSER_CHANNEL=chrome to use installed Chrome
    uv run playwright install-deps chromium       # Linux only, needs sudo
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from .submissions import save_submission
from .triage import safe_triage
from .urgency import COUNCIL_PHONE
from .urgency import summary as triage_summary


def _env(name: str, default: str | None = None) -> str | None:
    """FORM_<name>, falling back to the older POTHOLE_FORM_<name>."""
    return os.environ.get(f"FORM_{name}") or os.environ.get(f"POTHOLE_FORM_{name}") or default


MOCK_DIR = Path(__file__).resolve().parents[1] / "mock"
HEADLESS = _env("HEADLESS", "1") != "0"
# Empty means Playwright's bundled Chromium; "chrome" or "msedge" use a browser already installed.
BROWSER_CHANNEL = _env("BROWSER_CHANNEL")
TIMEOUT_MS = int(_env("TIMEOUT_MS", "20000"))

PAGES = {
    "page_sign_in": "Before you start",
    "page_about_the_problem": "About the problem",
    "page_about_the_location": "About the location",
    "page_about_you": "About you",
    "page_review": "Review your request",
    "page_complete": "Request submitted",
}


log = logging.getLogger(__name__)

# What the model is told when the browser can't start. Written for the user's benefit: the technical detail
# goes to the server log, so the model has nothing to repeat or embellish.
FORM_UNAVAILABLE = (
    "The online form isn't available right now. Don't explain why or mention technical details. "
    "Tell the user they can report it by phoning the council on 0114 273 4567, "
    "or 999 if anyone is in danger or hurt."
)


class FormStepError(Exception):
    """A tool was called on the wrong page or the form rejected the input."""


class CouncilFormSession:
    """One browser tab on a mock council form.

    Playwright's sync API is bound to the thread that started it, and Gradio/LangChain may call tools
    from different worker threads. So every browser call runs on one dedicated thread owned by this session.
    Use one session per conversation.
    """

    default_url: str = ""
    page_titles: dict[str, str] = PAGES
    noun: str = "council"  # tool names are start_<noun>_form, set_<noun>_problem, ...

    def next_step(self, page: str) -> str:
        """A hint for the model on what to call next. Small models follow these far better than the system prompt."""
        n = self.noun
        return {
            "page_about_the_problem": f"Call set_{n}_problem with what the user has already told you.",
            "page_about_the_location": f"Call set_{n}_location with the street or address and a short description.",
            "page_about_you": f"Call set_{n}_reporter. Use anonymous=true unless the user gave their details.",
            "page_review": f"If the user has already confirmed the answers, call submit_{n}_form now. Otherwise call "
                           f"review_{n}_form, tell the user the answers and ask them to confirm. Never make up a "
                           f"reference number: only submit_{n}_form gives one.",
            "page_complete": ("Tell the user the reference number, the suggested priority in plain words (priority_plain) "
                              "and that it is a suggestion only: the council decides after inspection. If there is "
                              "urgent_advice, repeat it. Say this test form sends nothing to the council."),
        }.get(page, "")

    def __init__(self, url: str | None = None, headless: bool = HEADLESS, channel: str | None = BROWSER_CHANNEL,
                 timeout_ms: int = TIMEOUT_MS, slow_mo_ms: int = 0):
        self.url = url or self.default_url
        self.headless, self.channel, self.timeout_ms, self.slow_mo_ms = headless, channel, timeout_ms, slow_mo_ms
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="council-form")
        self._lock = threading.Lock()
        self._pw = self._browser = self._page = None
        # Advice the user must hear (e.g. "phone now"); repeated in every result until the form is finished.
        self.tell_user: list[str] = []

    # ---------- plumbing ----------
    def _run(self, fn: Callable[[], Any]) -> Any:
        with self._lock:
            return self._executor.submit(fn).result()

    def _ensure_page(self):
        if self._page is None:
            try:
                from playwright.sync_api import sync_playwright  # imported lazily so the app boots without it
            except ImportError as e:
                log.error("Form browser unavailable: Playwright is not installed (run `uv sync`).")
                raise FormStepError(FORM_UNAVAILABLE) from e
            self._pw = sync_playwright().start()
            try:
                self._browser = self._pw.chromium.launch(headless=self.headless, channel=self.channel,
                                                         slow_mo=self.slow_mo_ms)
            except Exception as e:
                self._pw.stop()
                self._pw = None
                log.error("Form browser unavailable: could not start Chromium. Run `uv run playwright install "
                          "chromium` (and `playwright install-deps chromium` with sudo on Linux), or set "
                          "FORM_BROWSER_CHANNEL=chrome. %s: %s", type(e).__name__, e)
                raise FormStepError(FORM_UNAVAILABLE) from e
            self._page = self._browser.new_page()
            self._page.set_default_timeout(self.timeout_ms)
        return self._page

    def close(self) -> None:
        def _close():
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
            self._pw = self._browser = self._page = None
        self._run(_close)
        self._executor.shutdown(wait=False)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------- page helpers (run on the browser thread) ----------
    def _current_page(self) -> str:
        return self._page.evaluate(
            "() => (Array.from(document.querySelectorAll('section.dform_page')).find(s => !s.hidden) || {}).id || ''")

    def _errors(self) -> list[str]:
        return self._page.evaluate(
            "() => document.querySelector('#errors').hidden ? [] :"
            " Array.from(document.querySelectorAll('#errors li')).map(li => li.textContent.trim())")

    def _state(self, **extra) -> dict:
        page = self._current_page()
        state = {"page": page, "heading": self.page_titles.get(page, page)}
        errors = self._errors()
        if errors:
            state["errors"] = errors
        state.update(extra)
        if self.tell_user:
            state["tell_user"] = list(self.tell_user)
        if "redirect" not in state:
            state.setdefault("next_step", self.next_step(page))
            # Only where the model replies to the user anyway; mid-form it makes small models stop and chat.
            if self.tell_user and page in ("page_review", "page_complete"):
                state["next_step"] += " In your reply, also tell the user: " + " ".join(self.tell_user)
        return state

    def _expect(self, page_id: str) -> None:
        current = self._current_page() if self._page else ""
        if page_id == "page_about_the_problem" and current in ("", "page_sign_in"):
            # The model skipped (or ran in parallel) the start tool: open the form now rather than fail.
            self._start_on_thread()
            current = self._current_page()
        if current != page_id:
            raise FormStepError(
                f"The form is on {self.page_titles.get(current, current or 'no page')!r}, "
                f"not {self.page_titles[page_id]!r}. "
                + ("Call the start tool first." if not current else "Call the tool for the current page."))

    def _click_next(self, page_id: str, selector: str = "[data-next]") -> dict:
        self._page.click(f"#{page_id} {selector}")
        return self._state()

    def _attach_photo(self, photo_path: str | None) -> None:
        if not photo_path:
            return
        path = Path(photo_path)
        if not path.is_file():
            raise FormStepError(f"Photo not found: {photo_path}")
        self._page.set_input_files("#file_image_of_defect", str(path))
        file_error = self._page.evaluate(
            "() => (document.querySelector('#f_file_image_of_defect .err-msg') || {}).textContent || ''")
        if file_error:
            raise FormStepError(file_error.removeprefix("Error: "))

    # ---------- common form steps ----------
    def _start_on_thread(self) -> dict:
        page = self._ensure_page()
        page.goto(self.url)
        page.wait_for_selector("#page_sign_in:not([hidden])")
        page.check("#page_sign_in input[name=rad_sign_in][value=false]")  # "Submit a request without signing in"
        return self._click_next("page_sign_in")

    def start(self) -> dict:
        self.tell_user = []
        return self._run(self._start_on_thread)

    def set_location(self, location: str, details: str, address_choice: str | None = None,
                     lat: float | None = None, lon: float | None = None) -> dict:
        if not location.strip():
            raise FormStepError("location is required: ask the user where the problem is")
        if not details.strip():
            raise FormStepError("details are required: describe the problem and where exactly it is")

        def step():
            self._expect("page_about_the_location")
            p = self._page
            p.fill("#txt_find_address_about_the_location", location.strip())
            p.click("#but_find_address")
            # The search button is disabled while live lookups run; wait for it to come back.
            p.wait_for_function("() => !document.querySelector('#but_find_address').disabled")
            options = p.eval_on_selector_all(
                "#sel_search_results_about_the_location option",
                "os => os.map(o => ({value: o.value, text: o.textContent.trim()})).filter(o => o.value !== '')")
            matches_only = [o for o in options if o["value"] != "typed"]
            chosen = None
            if address_choice and address_choice.strip():
                wanted = address_choice.strip().lower()
                chosen = next((o for o in matches_only if wanted in o["text"].lower()), None)
            else:
                # No choice given: take a match that starts with exactly what the user said (e.g. "120 Abbeydale Road").
                wanted = location.strip().lower()
                chosen = next((o for o in matches_only if o["text"].lower().startswith(wanted)), None)
            if chosen is None:
                # Fall back to the user's own words, so the step never depends on the live geocoder.
                chosen = next(o for o in options if o["value"] == "typed")
            p.select_option("#sel_search_results_about_the_location", chosen["value"])
            p.click("#but_set_address")
            if lat is not None and lon is not None:
                # Pin the map at the user's device location, keeping the chosen address (mock hook: mockSetPoint).
                p.evaluate("([lat, lon]) => window.mockSetPoint(lat, lon)", [lat, lon])
            p.fill("#txta_details_about_the_location", details.strip())
            selected = (p.text_content("#selected_address span") or "").strip()
            matches = [o["text"] for o in options if o["value"] != "typed"][:8]
            return self._click_next("page_about_the_location") | {"selected_address": selected, "address_matches": matches}

        return self._run(step)

    def set_reporter(self, anonymous: bool = True, title: str = "", first_name: str = "", surname: str = "",
                     date_of_birth: str = "", phone: str = "", email: str = "") -> dict:
        def step():
            self._expect("page_about_you")
            p = self._page
            if anonymous:
                return self._click_next("page_about_you", "[data-anon]")
            dob = re.fullmatch(r"\s*(\d{1,2})[/\s.-](\d{1,2})[/\s.-](\d{4})\s*", date_of_birth or "")
            if not dob:
                raise FormStepError("date_of_birth must be DD/MM/YYYY")
            if title:
                p.select_option("#sel_title", title)
            p.fill("#txt_firstname", first_name)
            p.fill("#txt_surname", surname)
            p.fill("#dob_day", dob.group(1))
            p.fill("#dob_month", dob.group(2))
            p.fill("#dob_year", dob.group(3))
            p.fill("#tel_phone_number", phone)
            p.fill("#eml_address", email)
            return self._click_next("page_about_you")
        return self._run(step)

    def review(self) -> dict:
        def step():
            self._expect("page_review")
            rows = self._page.eval_on_selector_all(
                "#review_list > div",
                "ds => ds.map(d => [d.querySelector('dt').textContent.trim(), d.querySelector('dd').textContent.trim()])")
            return self._state(answers=dict(rows))
        return self._run(step)

    def submit(self) -> dict:
        def step():
            self._expect("page_review")
            p = self._page
            p.click("#but_final_submit")
            p.wait_for_selector("#page_complete:not([hidden])")
            record = p.evaluate("() => window.mockSubmissions[window.mockSubmissions.length - 1]")
            save_submission(record)  # for the dashboard; the browser's own copy is lost when the session closes
            # Same rules as the stored triage, so the resident hears the priority their report page shows.
            t = triage_summary(safe_triage({"form": record.get("form"), "fields": record.get("fields") or {}}))
            for advice in t.pop("tell_user", []):  # P1: phone advice, unless a step already gave it
                if not any(COUNCIL_PHONE in told for told in self.tell_user):
                    self.tell_user.append(advice)
            return self._state(reference=record["reference"], url=f"/reports/{record['reference']}",
                               status="submitted to the mock form (test only: not sent to the council)",
                               record=record, **t)
        return self._run(step)

    def status(self) -> dict:
        return self._run(lambda: self._state() if self._page else {"page": "", "heading": "not started"})

    def wait_until_closed(self) -> None:
        """Block until the user closes the browser tab (for headed demos)."""
        self._run(lambda: self._page and self._page.wait_for_event("close", timeout=0))


# ---------- LangChain tool helpers ----------

class NoArgs(BaseModel):
    pass


class LocationArgs(BaseModel):
    location: str = Field(description="Postcode, street or address as the user described it, e.g. '120 Abbeydale Road'")
    details: str = Field(description="Further information for the inspector: what it looks like and exactly where")
    address_choice: str | None = Field(
        None, description="Optional text to pick one of the address matches. Leave empty to use the location as typed.")
    lat: float | None = Field(None, ge=-90, le=90, description=(
        "The problem's map position. Only use the user's shared device location, and only if they are at the problem now."))
    lon: float | None = Field(None, ge=-180, le=180, description="See lat.")


class ReporterArgs(BaseModel):
    anonymous: bool = Field(True, description="Submit without personal details. The council then can't send updates.")
    title: Literal["", "Mr", "Miss", "Mrs", "Ms", "Mx", "Dr"] = ""
    first_name: str = ""
    surname: str = ""
    date_of_birth: str = Field("", description="DD/MM/YYYY")
    phone: str = ""
    email: str = ""


def as_tool(fn: Callable[..., dict], name: str, description: str, args_schema: type[BaseModel]) -> StructuredTool:
    """Wrap a session method as a tool that returns JSON, with errors as {"error": ...} instead of exceptions."""
    def run(**kwargs) -> str:
        try:
            return json.dumps(fn(**kwargs))
        except (FormStepError, ValueError) as e:
            return json.dumps({"error": str(e)})
        except Exception as e:  # Browser timeouts etc.: report rather than crash the agent loop.
            return json.dumps({"error": f"{type(e).__name__}: {e}"})
    return StructuredTool.from_function(
        func=run, name=name, description=description, args_schema=args_schema,
        # Arguments that fail the schema (e.g. an unknown option) also come back as {"error": ...}.
        handle_validation_error=lambda e: json.dumps({"error": f"Invalid arguments: {e}"}),
    )


def common_tools(s: CouncilFormSession, noun: str, problem_tool: BaseTool) -> list[BaseTool]:
    """The shared tools for one form, named after it (e.g. noun='tree' gives start_tree_form, ...)."""
    return [
        as_tool(lambda: s.start(), f"start_{noun}_form",
                f"Open a fresh {noun} report form and continue without signing in. Call this first.", NoArgs),
        problem_tool,
        as_tool(s.set_location, f"set_{noun}_location",
                "Fill in 'About the location': search for the address and add details. Then go to 'About you'.",
                LocationArgs),
        as_tool(s.set_reporter, f"set_{noun}_reporter",
                "Fill in 'About you', or submit anonymously (the default). Then go to the review page.", ReporterArgs),
        as_tool(s.review, f"review_{noun}_form",
                "Read back the answers on the review page so they can be checked with the user.", NoArgs),
        as_tool(s.submit, f"submit_{noun}_form",
                "Submit the reviewed form and get the reference number. Only call after the user confirms.", NoArgs),
        as_tool(s.status, f"{noun}_form_status",
                "Say which page the form is on and show any validation errors.", NoArgs),
    ]


def make_agent(tools: list[BaseTool], system_prompt: str, model: str | None = None, **llm_kwargs):
    """A LangChain agent on the local Ollama model with the given tools.

    llm_kwargs go to ChatOllama, e.g. reasoning=False to switch off a thinking model's reasoning (faster on CPU).
    """
    from langchain.agents import create_agent
    from langchain_ollama import ChatOllama

    from . import config

    llm = ChatOllama(model=model or config.OLLAMA_MODEL, base_url=config.OLLAMA_URL, temperature=0, **llm_kwargs)
    return create_agent(llm, tools, system_prompt=system_prompt)


REFERENCE_RE = re.compile(r"\b[A-Z]{0,4}-?\d{6,}\b")


def unverified_references(reply: str, tool_results: list[str]) -> list[str]:
    """Reference-like numbers in the model's reply that no submit tool returned (i.e. made up)."""
    real = set()
    for content in tool_results:
        try:
            ref = json.loads(content).get("reference")
        except (ValueError, AttributeError):
            continue
        if ref:
            real.add(str(ref))
    return [r for r in REFERENCE_RE.findall(reply or "") if r not in real]


def run_demo(session: CouncilFormSession, tools: list[BaseTool], steps: list[tuple[str, dict]],
             keep_open: bool = False) -> None:
    """Call tools in a fixed order and print each result. No model involved."""
    with session:
        by_name = {t.name: t for t in tools}
        for name, args in steps:
            print(f"> {name} {json.dumps(args)}\n{by_name[name].invoke(args)}\n", flush=True)
        if not session.headless and keep_open:
            print("Done. Close the browser window to exit.", flush=True)
            session.wait_until_closed()


def demo_arg_parser(description: str):
    import argparse

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--slow-mo", type=int, default=0, metavar="MS", help="pause between browser actions")
    parser.add_argument("--keep-open", action="store_true", help="with --headed, leave the window open at the end")
    return parser
