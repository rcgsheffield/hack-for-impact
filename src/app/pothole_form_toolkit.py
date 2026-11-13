"""LangChain toolkit that fills in and submits the mock pothole form in a real (headless) browser.

The form is src/mock/report_pothole_crack.html, a copy of the council's report_pothole_crack form.
There is one tool per form page, so a small local model only has to make a few, coarse calls:

    start_pothole_form -> set_pothole_problem -> set_pothole_location -> set_pothole_reporter
    -> review_pothole_form -> submit_pothole_form

Each tool returns JSON with the page the browser is now on and any validation errors the form showed,
so the model can correct itself. Nothing leaves the machine except the mock's own address lookups
(postcodes.io / Photon) and CDN assets; nothing is sent to the council.

Browser setup (once per machine):
    uv run playwright install chromium            # or set POTHOLE_FORM_BROWSER_CHANNEL=chrome to use installed Chrome
    uv run playwright install-deps chromium       # Linux only, needs sudo

Try it without a model:
    uv run python -m app.pothole_form_toolkit --headed
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Literal

from langchain_core.tools import BaseTool, BaseToolkit, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from . import config
from .tools import FORM_SURFACE, assess_pothole

DEFAULT_FORM_URL = (Path(__file__).resolve().parents[1] / "mock" / "report_pothole_crack.html").as_uri()
FORM_URL = os.environ.get("POTHOLE_FORM_URL") or DEFAULT_FORM_URL
HEADLESS = os.environ.get("POTHOLE_FORM_HEADLESS", "1") != "0"
# Empty means Playwright's bundled Chromium; "chrome" or "msedge" use a browser already installed.
BROWSER_CHANNEL = os.environ.get("POTHOLE_FORM_BROWSER_CHANNEL") or None
TIMEOUT_MS = int(os.environ.get("POTHOLE_FORM_TIMEOUT_MS", "20000"))

PAGES = {
    "page_sign_in": "Before you start",
    "page_about_the_problem": "About the problem",
    "page_about_the_location": "About the location",
    "page_about_you": "About you",
    "page_review": "Review your request",
    "page_complete": "Request submitted",
}


class FormStepError(Exception):
    """A tool was called on the wrong page or the form rejected the input."""


class PotholeFormSession:
    """One browser tab on the mock form.

    Playwright's sync API is bound to the thread that started it, and Gradio/LangChain may call tools
    from different worker threads. So every browser call runs on one dedicated thread owned by this session.
    Use one session per conversation.
    """

    def __init__(self, url: str = FORM_URL, headless: bool = HEADLESS, channel: str | None = BROWSER_CHANNEL,
                 timeout_ms: int = TIMEOUT_MS, slow_mo_ms: int = 0):
        self.url, self.headless, self.channel, self.timeout_ms = url, headless, channel, timeout_ms
        self.slow_mo_ms = slow_mo_ms
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pothole-form")
        self._lock = threading.Lock()
        self._pw = self._browser = self._page = None

    # ---------- plumbing ----------
    def _run(self, fn: Callable[[], Any]) -> Any:
        with self._lock:
            return self._executor.submit(fn).result()

    def _ensure_page(self):
        if self._page is None:
            try:
                from playwright.sync_api import sync_playwright  # imported lazily so the app boots without it
            except ImportError as e:
                raise FormStepError("Playwright is not installed: run `uv sync`.") from e
            self._pw = sync_playwright().start()
            try:
                self._browser = self._pw.chromium.launch(headless=self.headless, channel=self.channel,
                                                         slow_mo=self.slow_mo_ms)
            except Exception as e:
                self._pw.stop()
                self._pw = None
                raise FormStepError(
                    "Could not start a browser. Run `uv run playwright install chromium`, "
                    f"or set POTHOLE_FORM_BROWSER_CHANNEL=chrome. ({type(e).__name__}: {e})") from e
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
        state = {"page": page, "heading": PAGES.get(page, page)}
        errors = self._errors()
        if errors:
            state["errors"] = errors
        state.update(extra)
        return state

    def _expect(self, page_id: str) -> None:
        current = self._current_page() if self._page else ""
        if current != page_id:
            raise FormStepError(
                f"The form is on {PAGES.get(current, current or 'no page')!r}, not {PAGES[page_id]!r}. "
                + ("Call start_pothole_form first." if not current else "Call the tool for the current page."))

    def _click_next(self, page_id: str, selector: str = "[data-next]") -> dict:
        self._page.click(f"#{page_id} {selector}")
        return self._state()

    # ---------- form steps ----------
    def start(self) -> dict:
        def step():
            page = self._ensure_page()
            page.goto(self.url)
            page.wait_for_selector("#page_sign_in:not([hidden])")
            page.check("#page_sign_in input[name=rad_sign_in][value=false]")  # "Submit a request without signing in"
            return self._click_next("page_sign_in")
        return self._run(step)

    def set_problem(self, surface: str, depth_mm: float, photo_path: str | None = None) -> dict:
        assessment = assess_pothole(surface, depth_mm)  # validates and gives the form's exact option value

        def step():
            self._expect("page_about_the_problem")
            p = self._page
            p.check(f"input[name=rad_problem_location][value='{FORM_SURFACE[surface]}']")
            field = "rad_road_pothole_depth" if surface == "road" else "rad_path_pothole_depth"
            p.check(f"input[name={field}][value='{assessment['depth_band']}']")
            if photo_path:
                path = Path(photo_path)
                if not path.is_file():
                    raise FormStepError(f"Photo not found: {photo_path}")
                p.set_input_files("#file_image_of_defect", str(path))
                file_error = p.evaluate("() => (document.querySelector('#f_file_image_of_defect .err-msg') || {}).textContent || ''")
                if file_error:
                    raise FormStepError(file_error.removeprefix("Error: "))
            return self._click_next("page_about_the_problem")

        state = self._run(step)
        state["depth_band"] = assessment["depth_band"]
        state["suggested_category"] = assessment["suggested_category"]
        return state

    def set_location(self, location: str, details: str, address_choice: str | None = None) -> dict:
        if not location.strip():
            raise FormStepError("location is required: ask the user where the problem is")
        if not details.strip():
            raise FormStepError("details are required: describe the pothole and where exactly it is")

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
            chosen = None
            if address_choice:
                wanted = address_choice.strip().lower()
                chosen = next((o for o in options if o["value"] != "typed" and wanted in o["text"].lower()), None)
            if chosen is None:
                # Fall back to the user's own words, so the step never depends on the live geocoder.
                chosen = next(o for o in options if o["value"] == "typed")
            p.select_option("#sel_search_results_about_the_location", chosen["value"])
            p.click("#but_set_address")
            p.fill("#txta_details_about_the_location", details.strip())
            selected = p.text_content("#selected_address span") or ""
            matches = [o["text"] for o in options if o["value"] != "typed"][:8]
            return self._click_next("page_about_the_location") | {"selected_address": selected.strip(), "address_matches": matches}

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
            return self._state(reference=record["reference"],
                               status="submitted to the mock form (test only: not sent to the council)",
                               record=record)
        return self._run(step)

    def status(self) -> dict:
        return self._run(lambda: self._state() if self._page else {"page": "", "heading": "not started"})

    def wait_until_closed(self) -> None:
        """Block until the user closes the browser tab (for headed demos)."""
        self._run(lambda: self._page and self._page.wait_for_event("close", timeout=0))


# ---------- LangChain tools ----------

class _NoArgs(BaseModel):
    pass


class ProblemArgs(BaseModel):
    surface: Literal["road", "pavement"] = Field(description="'road', or 'pavement' for a pavement or cycle path")
    depth_mm: float = Field(ge=0, description="Estimated depth in millimetres (4 cm = 40 mm)")
    photo_path: str | None = Field(None, description="Path to a jpg, png or pdf of the problem, if the user gave one")


class LocationArgs(BaseModel):
    location: str = Field(description="Postcode, street or address as the user described it, e.g. '120 Abbeydale Road'")
    details: str = Field(description="Further information for the inspector: what it looks like and exactly where")
    address_choice: str | None = Field(
        None, description="Optional text to pick one of the address matches. Leave empty to use the location as typed.")


class ReporterArgs(BaseModel):
    anonymous: bool = Field(True, description="Submit without personal details. The council then can't send updates.")
    title: Literal["", "Mr", "Miss", "Mrs", "Ms", "Mx", "Dr"] = ""
    first_name: str = ""
    surname: str = ""
    date_of_birth: str = Field("", description="DD/MM/YYYY")
    phone: str = ""
    email: str = ""


def _as_tool(fn: Callable[..., dict], name: str, description: str, args_schema: type[BaseModel]) -> StructuredTool:
    def run(**kwargs) -> str:
        try:
            return json.dumps(fn(**kwargs))
        except (FormStepError, ValueError) as e:
            return json.dumps({"error": str(e)})
        except Exception as e:  # Browser timeouts etc.: report rather than crash the agent loop.
            return json.dumps({"error": f"{type(e).__name__}: {e}"})
    return StructuredTool.from_function(func=run, name=name, description=description, args_schema=args_schema)


class PotholeFormToolkit(BaseToolkit):
    """Tools that complete the mock pothole form page by page in a browser."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    session: PotholeFormSession = Field(default_factory=PotholeFormSession)

    def get_tools(self) -> list[BaseTool]:
        s = self.session
        return [
            _as_tool(lambda: s.start(), "start_pothole_form",
                     "Open a fresh pothole report form and continue without signing in. Call this first.", _NoArgs),
            _as_tool(s.set_problem, "set_pothole_problem",
                     "Fill in 'About the problem': road or pavement, depth, optional photo. Then go to the location page.",
                     ProblemArgs),
            _as_tool(s.set_location, "set_pothole_location",
                     "Fill in 'About the location': search for the address and add details. Then go to 'About you'.",
                     LocationArgs),
            _as_tool(s.set_reporter, "set_pothole_reporter",
                     "Fill in 'About you', or submit anonymously (the default). Then go to the review page.",
                     ReporterArgs),
            _as_tool(s.review, "review_pothole_form",
                     "Read back the answers on the review page so they can be checked with the user.", _NoArgs),
            _as_tool(s.submit, "submit_pothole_form",
                     "Submit the reviewed form and get the reference number. Only call after the user confirms.",
                     _NoArgs),
            _as_tool(s.status, "pothole_form_status",
                     "Say which page the form is on and show any validation errors.", _NoArgs),
        ]


SYSTEM_PROMPT = """You complete Sheffield's 'Report a pothole or crack' form for residents, using the pothole form tools.

Steps: start_pothole_form, set_pothole_problem, set_pothole_location, set_pothole_reporter, review_pothole_form,
then submit_pothole_form once the user agrees the answers are right.
- Ask one short question if the surface (road or pavement), rough depth or location is missing.
- Submit anonymously unless the user wants updates and gives their details.
- If a tool returns "error" or "errors", fix the input or ask the user, then call the tool for the current page again.
- Never invent a reference number; only quote the one from submit_pothole_form.
- This is a test form: say that nothing is sent to the council. Use British English and keep replies short."""


def make_form_agent(session: PotholeFormSession | None = None, model: str | None = None):
    """A LangChain agent on the local Ollama model with the form tools. Returns (agent, session)."""
    from langchain.agents import create_agent
    from langchain_ollama import ChatOllama

    session = session or PotholeFormSession()
    llm = ChatOllama(model=model or config.OLLAMA_MODEL, base_url=config.OLLAMA_URL, temperature=0)
    agent = create_agent(llm, PotholeFormToolkit(session=session).get_tools(), system_prompt=SYSTEM_PROMPT)
    return agent, session


def _demo(headed: bool, slow_mo_ms: int = 0, keep_open: bool = False) -> None:
    """Fill the form with fixed answers, no model involved."""
    with PotholeFormSession(headless=not headed, slow_mo_ms=slow_mo_ms) as s:
        tools = {t.name: t for t in PotholeFormToolkit(session=s).get_tools()}
        steps = [
            ("start_pothole_form", {}),
            ("set_pothole_problem", {"surface": "road", "depth_mm": 60}),
            ("set_pothole_location", {"location": "120 Abbeydale Road", "address_choice": "120 Abbeydale Road",
                                      "details": "Deep pothole in the bus lane outside the chip shop"}),
            ("set_pothole_reporter", {"anonymous": True}),
            ("review_pothole_form", {}),
            ("submit_pothole_form", {}),
        ]
        for name, args in steps:
            print(f"> {name} {json.dumps(args)}\n{tools[name].invoke(args)}\n", flush=True)
        if headed and keep_open:
            print("Done. Close the browser window to exit.", flush=True)
            s.wait_until_closed()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=_demo.__doc__)
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--slow-mo", type=int, default=0, metavar="MS", help="pause between browser actions")
    parser.add_argument("--keep-open", action="store_true", help="with --headed, leave the window open at the end")
    a = parser.parse_args()
    _demo(a.headed, a.slow_mo, a.keep_open)
