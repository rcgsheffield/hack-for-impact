"""LangChain toolkit that fills in and submits the mock tree form in a real (headless) browser.

The form is src/mock/report_tree.html, a mock of the council's report_tree form. Its "About the tree"
questions are UNVERIFIED against the live form (see the comment at the top of the mock).
One tool per form page:

    start_tree_form -> set_tree_problem -> set_tree_location -> set_tree_reporter
    -> review_tree_form -> submit_tree_form

set_tree_problem may end the journey: for trees in parks, on housing land or on private land, and for
utility-cable or nuisance problems, the form shows advice instead of a Next button. The tool returns
that advice as "redirect" so the agent can tell the user where to go instead.

The browser driver and the shared steps live in council_form.py (see there for browser setup).

Try it without a model:
    uv run python -m app.tree_form_toolkit --headed --slow-mo 400 --keep-open
"""

from __future__ import annotations

import os
from typing import Literal

from langchain_core.tools import BaseTool, BaseToolkit
from pydantic import BaseModel, ConfigDict, Field

from .council_form import (  # noqa: F401  (FormStepError re-exported for callers and tests)
    MOCK_DIR, CouncilFormSession, FormStepError, as_tool, common_tools, demo_arg_parser, make_agent, run_demo,
)

FORM_URL = os.environ.get("TREE_FORM_URL") or (MOCK_DIR / "report_tree.html").as_uri()

# Option values on the mock's "About the tree" page (rad_tree_location, rad_tree_problem).
TreeLocation = Literal["Highway", "Park", "Housing", "Private"]
TreeProblem = Literal["Fallen", "Dangerous", "Obstruction", "Roots", "Utility", "Nuisance", "Other"]
# Problems for which the form asks "Is it blocking the road or pavement now?"
BLOCKING_PROBLEMS = {"Fallen", "Dangerous", "Obstruction"}
COUNCIL_PHONE = "0114 273 4567"


class TreeFormSession(CouncilFormSession):
    default_url = FORM_URL
    page_titles = {**CouncilFormSession.page_titles, "page_about_the_problem": "About the tree"}
    noun = "tree"

    def next_step(self, page: str) -> str:
        if page == "page_about_the_problem":
            return ("Call set_tree_problem now; don't ask the user to pick a category. Use tree_location Highway "
                    "unless the user clearly said park or woodland (Park), council housing estate (Housing) or a "
                    "private or neighbour's garden (Private); a named street or road, or 'don't know', means Highway. "
                    "For Park, Housing or Private pass only tree_location. For Highway pass the problem (fallen means "
                    "Fallen) and, for Fallen, Dangerous or Obstruction, blocking: true unless the user said it isn't "
                    "in the way.")
        return super().next_step(page)

    def set_problem(self, tree_location: str, problem: str | None = None, blocking: bool | None = None,
                    photo_id: str | None = None) -> dict:
        if tree_location == "Highway" and not problem:
            raise FormStepError("problem is required for a tree on or next to a road or pavement")
        if tree_location == "Highway" and problem in BLOCKING_PROBLEMS and blocking is None:
            raise FormStepError("blocking is required: ask whether the tree is blocking the road or pavement now")

        def step():
            self._expect("page_about_the_problem")
            p = self._page
            p.check(f"input[name=rad_tree_location][value='{tree_location}']")
            if tree_location == "Highway":
                p.check(f"input[name=rad_tree_problem][value='{problem}']")
            # A visible exit panel means this form can't take the report: return its advice, don't press Next.
            redirect = p.evaluate(
                "() => { const e = Array.from(document.querySelectorAll('.exit-panel')).find(x => !x.hidden);"
                " return e ? e.textContent.replace(/\\s+/g, ' ').trim() : ''; }")
            if redirect:
                return self._state(can_file=False, redirect=redirect,
                                   next_step="Stop here. Tell the user this advice in plain words; don't continue the form.")
            if problem in BLOCKING_PROBLEMS:
                p.check(f"input[name=rad_tree_blocking][value='{'Yes' if blocking else 'No'}']")
            self._attach_photo(photo_id)
            return self._click_next("page_about_the_problem") | {"can_file": True}

        state = self._run(step)
        if state.get("can_file") and (problem == "Fallen" or (problem == "Dangerous" and blocking)):
            advice = (f"If the tree is putting people in danger, phone the council now on {COUNCIL_PHONE} "
                      "(999 if anyone is hurt). The form says not to use it for emergencies.")
            state["urgent_advice"] = advice
            if advice not in self.tell_user:
                self.tell_user.append(advice)
            state["tell_user"] = list(self.tell_user)
        return state


class TreeProblemArgs(BaseModel):
    tree_location: TreeLocation = Field(description=(
        "Highway: on or next to a road, street or pavement; also use Highway if the user named a street or "
        "doesn't know. Park: park, woodland or green space. Housing: council housing estate. "
        "Private: private or neighbour's garden or land."))
    problem: TreeProblem | None = Field(None, description=(
        "Only for Highway. Fallen: tree or large branch has fallen. Dangerous: leaning, split, hanging branch, "
        "dead or diseased. Obstruction: overhanging or blocking road, pavement, sign or street light. "
        "Roots: roots damaging pavement or road. Utility: touching a phone line or power cable. "
        "Nuisance: fruit, leaves, sap or bird mess. Other: something else."))
    blocking: bool | None = Field(None, description="For Fallen, Dangerous or Obstruction: is it blocking the road or pavement now?")
    photo_id: str | None = Field(None, description="The photo_id from the user's photo upload note, if they sent a photo. "
                                                    "Never a file path.")


class TreeFormToolkit(BaseToolkit):
    """Tools that complete the mock tree form page by page in a browser."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    session: TreeFormSession = Field(default_factory=TreeFormSession)

    def get_tools(self) -> list[BaseTool]:
        problem = as_tool(self.session.set_problem, "set_tree_problem",
                          "Fill in 'About the tree': where it is, what the problem is, whether it is blocking, "
                          "optional photo. If can_file is false, stop and give the user the redirect advice.",
                          TreeProblemArgs)
        return common_tools(self.session, "tree", problem)


SYSTEM_PROMPT = f"""You complete Sheffield's 'Report a problem with a tree' form for residents, using the tree form tools.

Steps: start_tree_form, set_tree_problem, set_tree_location, set_tree_reporter, review_tree_form,
then submit_tree_form once the user agrees the answers are right.
- Call one tool at a time, in that order, and wait for its result before the next.
- If a tree has fallen or is about to fall and someone is in danger, tell them to phone {COUNCIL_PHONE} now
  (999 if anyone is hurt) before anything else.
- Use everything the user has already said: a tree on or by a road, pavement or street is tree_location Highway,
  "has fallen" or "branch came down" is problem Fallen, "across the pavement" means blocking true, and any street
  or address is the location. Keep going through the steps without asking again for things you already know.
- Use tree_location Highway unless the user clearly said park, housing estate or private garden; a named street
  or "don't know" means Highway. Never make the user pick a category.
- Only ask one short question if the problem or the location is really missing. If the user says they don't know,
  don't ask again: use the defaults and carry on.
- If a tool says the online form isn't available, don't mention technical details: give the council phone number.
- Before submitting, tell the user the answers from review_tree_form and ask them to confirm.
- For a tree in a park or woodland, on a council housing estate, or in a private or neighbour's garden, call
  set_tree_problem with just tree_location (Park, Housing or Private). Don't ask what the problem is first.
- If set_tree_problem returns can_file false, don't continue the form: pass on its redirect advice in plain words.
- If a tool result has tell_user, include that advice in your reply to the user.
- Follow the next_step in each tool result.
- Submit anonymously unless the user wants updates and gives their details.
- If a tool returns "error" or "errors", fix the input or ask the user, then call the tool for the current page again.
- After submitting, give the reference number and the suggested priority in plain words from priority_plain
  (e.g. "Emergency: made safe within 24 hours"), and say it is a suggestion only: the council decides after inspection.
  If the result has urgent_advice, repeat it: phone {COUNCIL_PHONE} now, or 999 if anyone is in danger.
- Never invent a reference number; only quote the one from submit_tree_form.
- This is a test form: say that nothing is sent to the council. Use British English and keep replies short."""


def make_form_agent(session: TreeFormSession | None = None, model: str | None = None, **llm_kwargs):
    """A LangChain agent on the local Ollama model with the tree form tools. Returns (agent, session)."""
    session = session or TreeFormSession()
    return make_agent(TreeFormToolkit(session=session).get_tools(), SYSTEM_PROMPT, model, **llm_kwargs), session


DEMO_STEPS = [
    ("start_tree_form", {}),
    ("set_tree_problem", {"tree_location": "Highway", "problem": "Fallen", "blocking": True}),
    ("set_tree_location", {"location": "Derbyshire Lane", "address_choice": "12 Derbyshire Lane",
                           "details": "Large branch down across the pavement outside number 12, near the bus stop"}),
    ("set_tree_reporter", {"anonymous": True}),
    ("review_tree_form", {}),
    ("submit_tree_form", {}),
]

if __name__ == "__main__":
    a = demo_arg_parser("Fill the mock tree form with fixed answers, no model involved.").parse_args()
    s = TreeFormSession(headless=not a.headed, slow_mo_ms=a.slow_mo)
    run_demo(s, TreeFormToolkit(session=s).get_tools(), DEMO_STEPS, a.keep_open)
