"""Plain-English rendering of the agent's tool calls for the chat UI.

Each tool call becomes a short title (shown on the collapsible bubble) and a few lines of Markdown that a
resident can read, with the raw arguments and result tucked away in a "Technical details" toggle.
"""

from __future__ import annotations

import json
import re
from html import escape

FORM_NAMES = {"pothole": "pothole form", "tree": "tree form"}
TREE_PROBLEMS = {
    "Fallen": "it has fallen, or a large branch has fallen",
    "Dangerous": "it looks dangerous",
    "Obstruction": "it is overhanging or blocking the way",
    "Roots": "its roots are damaging the pavement or road",
    "Utility": "it is touching a phone line or power cable",
    "Nuisance": "falling fruit, leaves, sap or bird mess",
    "Other": "something else",
}
TREE_PLACES = {"Highway": "on or next to a road or pavement", "Park": "in a park or green space",
               "Housing": "on a council housing estate", "Private": "on private land"}


def _args(arguments: str | dict) -> dict:
    if isinstance(arguments, dict):
        return arguments
    try:
        value = json.loads(arguments or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _yes_no(value) -> str:
    return "yes" if value in (True, "true", "True", "Yes", "yes") else "no"


def _link(result: dict) -> str:
    return f" · [View the report]({result['url']})" if result.get("url") else ""


def _location_line(args: dict) -> str:
    return " · 📍 pinned at your shared location" if args.get("lat") is not None else ""


def _technical(name: str, args: dict, result: dict) -> str:
    raw = json.dumps({"tool": name, "arguments": args, "result": result}, indent=2, ensure_ascii=False)
    return f"\n\n<details><summary>Technical details</summary>\n\n```json\n{raw}\n```\n\n</details>"


def _errors(result: dict) -> list[str]:
    errors = []
    if result.get("error"):
        errors.append(str(result["error"]))
    errors += [str(e) for e in result.get("errors") or []]
    return errors


def _form_step(name: str, args: dict, result: dict) -> tuple[str, str] | None:
    """The browser form tools: start_X_form, set_X_problem, set_X_location, set_X_reporter, review/submit_X_form."""
    m = re.fullmatch(r"(start|set|review|submit)_(\w+?)_(form|problem|location|reporter)|(\w+?)_form_status", name)
    if not m:
        return None
    action, noun, part = m.group(1), m.group(2) or m.group(4), m.group(3)
    form = FORM_NAMES.get(noun, f"{noun} form")
    page = result.get("heading")
    now_on = f"The form is now on **{page}**." if page else ""

    if result.get("redirect"):
        return f"↪️ The {form} can't take this report", result["redirect"]
    if action == "start":
        return f"🖥️ Opened the council's {form}", now_on
    if action == "set" and part == "problem":
        if noun == "pothole":
            lines = [f"Surface: **{args.get('surface', '?')}**, depth about **{args.get('depth_mm', '?')} mm**"]
            if result.get("depth_band"):
                lines.append(f"Depth option chosen: {result['depth_band']}")
        else:
            lines = [f"Where: **{TREE_PLACES.get(args.get('tree_location'), args.get('tree_location', '?'))}**"]
            if args.get("problem"):
                lines.append(f"Problem: **{TREE_PROBLEMS.get(args['problem'], args['problem'])}**")
            if args.get("blocking") is not None:
                lines.append(f"Blocking the way: **{_yes_no(args['blocking'])}**")
        return "✏️ Filled in 'About the problem'", "  \n".join(lines + [now_on])
    if action == "set" and part == "location":
        where = result.get("selected_address") or args.get("location", "")
        return "✏️ Filled in 'About the location'", f"Address: **{where}**{_location_line(args)}  \n{now_on}"
    if action == "set" and part == "reporter":
        who = "anonymously (the council can't send updates)" if args.get("anonymous", True) else "with your contact details"
        return "✏️ Filled in 'About you'", f"Submitting {who}.  \n{now_on}"
    if action == "review":
        answers = result.get("answers") or {}
        rows = "\n".join(f"| {escape(q)} | {escape(str(a))} |" for q, a in answers.items())
        table = f"| Question | Answer |\n|---|---|\n{rows}" if rows else ""
        return "📋 Read back the answers for you to check", table
    if action == "submit":
        return "✅ Submitted the form", f"Reference **{result.get('reference', '?')}**{_link(result)}  \nTest form only: nothing was sent to the council."
    return f"🔎 Checked the {form}", now_on


def describe(name: str, arguments: str | dict, result: dict) -> tuple[str, str]:
    """A (title, markdown) pair for one tool call."""
    args = _args(arguments)
    result = result if isinstance(result, dict) else {"output": result}
    errors = _errors(result)

    if errors:
        title, body = "⚠️ That step needs another try", "  \n".join(errors)
    elif (form := _form_step(name, args, result)) is not None:
        title, body = form
    elif name == "convert_to_mm":
        approx = " (rough estimate)" if result.get("approximate") else ""
        title = "📏 Converted the depth to millimetres"
        body = f"{args.get('amount', '?')} {args.get('unit', '')} ≈ **{result.get('mm', '?')} mm**{approx}"
    elif name == "nearest_address":
        title, body = "📍 Looked up the nearest address", f"**{result.get('address', '?')}**  \n{result.get('note', '')}"
    elif name == "route_report":
        if result.get("can_file"):
            title = "🧭 Checked who's responsible"
            body = f"**{result.get('owner', '?')}**: this can be reported here."
        else:
            title = "🧭 This is looked after by someone else"
            body = f"**{result.get('owner', '?')}**  \nHow to report it: {result.get('how_to_report', '')}"
            if result.get("reason"):
                body += f"  \n{result['reason']}"
    elif name == "assess_pothole":
        title = "🕳️ Assessed the pothole"
        body = (f"Depth option: **{result.get('depth_band', '?')}**  \n"
                f"Suggested priority: {result.get('category_meaning', '?')}  \n_{result.get('note', '')}_")
    elif name == "assess_tree":
        if result.get("can_file"):
            title = "🌳 Checked the tree problem"
            problem = TREE_PROBLEMS.get(args.get("problem"), args.get("problem", ""))
            body = f"This can be reported: **{problem}**."
            if result.get("urgent_advice"):
                body += f"  \n🚨 {result['urgent_advice']}"
        else:
            title, body = "↪️ This tree is looked after by someone else", result.get("redirect", "")
    elif name in ("file_report", "file_tree_report"):
        title = "📝 Recorded your report"
        body = f"Reference **{result.get('reference', '?')}**{_link(result)}{_location_line(args)}  \n{result.get('status', '')}"
        if result.get("urgent_advice"):
            body += f"  \n🚨 {result['urgent_advice']}"
    else:
        title, body = f"🔧 {name.replace('_', ' ').capitalize()}", ""

    if result.get("tell_user") and name != "assess_tree":
        body += "".join(f"  \n🚨 {advice}" for advice in result["tell_user"] if advice not in body)
    return title, body.strip() + _technical(name, args, result)
