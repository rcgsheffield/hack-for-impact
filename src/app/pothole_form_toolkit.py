"""LangChain toolkit that fills in and submits the mock pothole form in a real (headless) browser.

The form is src/mock/report_pothole_crack.html, a copy of the council's report_pothole_crack form.
One tool per form page, so a small local model only has to make a few, coarse calls:

    start_pothole_form -> set_pothole_problem -> set_pothole_location -> set_pothole_reporter
    -> review_pothole_form -> submit_pothole_form

The browser driver and the shared steps live in council_form.py (see there for browser setup).

Try it without a model:
    uv run python -m app.pothole_form_toolkit --headed --slow-mo 400 --keep-open
"""

from __future__ import annotations

import os
from typing import Literal

from langchain_core.tools import BaseTool, BaseToolkit
from pydantic import BaseModel, ConfigDict, Field

from .council_form import (  # noqa: F401  (FormStepError re-exported for callers and tests)
    MOCK_DIR, CouncilFormSession, FormStepError, as_tool, common_tools, demo_arg_parser, make_agent, run_demo,
)
from .tools import FORM_SURFACE, assess_pothole

FORM_URL = os.environ.get("POTHOLE_FORM_URL") or (MOCK_DIR / "report_pothole_crack.html").as_uri()


class PotholeFormSession(CouncilFormSession):
    default_url = FORM_URL

    def set_problem(self, surface: str, depth_mm: float, photo_path: str | None = None) -> dict:
        assessment = assess_pothole(surface, depth_mm)  # validates and gives the form's exact option value

        def step():
            self._expect("page_about_the_problem")
            p = self._page
            p.check(f"input[name=rad_problem_location][value='{FORM_SURFACE[surface]}']")
            field = "rad_road_pothole_depth" if surface == "road" else "rad_path_pothole_depth"
            p.check(f"input[name={field}][value='{assessment['depth_band']}']")
            self._attach_photo(photo_path)
            return self._click_next("page_about_the_problem")

        state = self._run(step)
        state["depth_band"] = assessment["depth_band"]
        state["suggested_category"] = assessment["suggested_category"]
        return state


class ProblemArgs(BaseModel):
    surface: Literal["road", "pavement"] = Field(description="'road', or 'pavement' for a pavement or cycle path")
    depth_mm: float = Field(ge=0, description="Estimated depth in millimetres (4 cm = 40 mm)")
    photo_path: str | None = Field(None, description="Path to a jpg, png or pdf of the problem, if the user gave one")


class PotholeFormToolkit(BaseToolkit):
    """Tools that complete the mock pothole form page by page in a browser."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    session: PotholeFormSession = Field(default_factory=PotholeFormSession)

    def get_tools(self) -> list[BaseTool]:
        problem = as_tool(self.session.set_problem, "set_pothole_problem",
                          "Fill in 'About the problem': road or pavement, depth, optional photo. "
                          "Then go to the location page.", ProblemArgs)
        return common_tools(self.session, "pothole", problem)


SYSTEM_PROMPT = """You complete Sheffield's 'Report a pothole or crack' form for residents, using the pothole form tools.

Steps: start_pothole_form, set_pothole_problem, set_pothole_location, set_pothole_reporter, review_pothole_form,
then submit_pothole_form once the user agrees the answers are right.
- Ask one short question if the surface (road or pavement), rough depth or location is missing.
- Submit anonymously unless the user wants updates and gives their details.
- If a tool returns "error" or "errors", fix the input or ask the user, then call the tool for the current page again.
- Never invent a reference number; only quote the one from submit_pothole_form.
- This is a test form: say that nothing is sent to the council. Use British English and keep replies short."""


def make_form_agent(session: PotholeFormSession | None = None, model: str | None = None):
    """A LangChain agent on the local Ollama model with the pothole form tools. Returns (agent, session)."""
    session = session or PotholeFormSession()
    return make_agent(PotholeFormToolkit(session=session).get_tools(), SYSTEM_PROMPT, model), session


DEMO_STEPS = [
    ("start_pothole_form", {}),
    ("set_pothole_problem", {"surface": "road", "depth_mm": 60}),
    ("set_pothole_location", {"location": "120 Abbeydale Road", "address_choice": "120 Abbeydale Road",
                              "details": "Deep pothole in the bus lane outside the chip shop"}),
    ("set_pothole_reporter", {"anonymous": True}),
    ("review_pothole_form", {}),
    ("submit_pothole_form", {}),
]

if __name__ == "__main__":
    a = demo_arg_parser("Fill the mock pothole form with fixed answers, no model involved.").parse_args()
    s = PotholeFormSession(headless=not a.headed, slow_mo_ms=a.slow_mo)
    run_demo(s, PotholeFormToolkit(session=s).get_tools(), DEMO_STEPS, a.keep_open)
