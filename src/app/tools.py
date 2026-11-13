"""Tools the agent can call: plain functions plus their OpenAI function-calling schemas.

Routing facts come from docs/sheffield-council-services.md. Form field names and depth options come
from the mock council form, src/mock/report_pothole_crack.html. Nothing is sent to any real council system.
"""

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from . import config

COUNCIL_PHONE = "0114 273 4567"
POTHOLE_FORM = "https://forms.sheffield.gov.uk/site/portal/form/report_pothole_crack"

# Roads maintained by National Highways, not the council (docs/sheffield-council-services.md, "Routing").
NATIONAL_HIGHWAYS_PATTERNS = [
    r"\bM1\b", r"\bM18\b", r"\bmotorway\b",
    r"tinsley viaduct", r"\bA631\b.*lower deck",
    r"stocksbridge bypass", r"\bA616\b",
]
# Places the council doesn't maintain.
PRIVATE_PATTERNS = [r"car ?park", r"private road", r"retail park", r"supermarket", r"driveway", r"unadopted"]

# The council form's depth threshold per surface, in mm, and its radio-button labels
# (src/mock/report_pothole_crack.html: rad_road_pothole_depth / rad_path_pothole_depth).
DEPTH_THRESHOLD_MM = {"road": 40, "pavement": 20}
FORM_SURFACE = {"road": "Road Surface", "pavement": "Pavement Surface"}

PROBLEM_TYPES = [
    "pothole", "road_surface", "pavement_surface", "street_light", "fly_tipping",
    "untaxed_vehicle", "abandoned_vehicle", "obstructing_vehicle", "burnt_out_vehicle", "tree", "other",
]
FILEABLE_TYPES = {"pothole", "road_surface", "pavement_surface"}


def _matches(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def route_report(problem_type: str, road_or_place: str) -> dict:
    """Work out who is responsible for a problem and whether this agent can file it."""
    if problem_type not in PROBLEM_TYPES:
        raise ValueError(f"problem_type must be one of {PROBLEM_TYPES}")

    if problem_type == "untaxed_vehicle":
        return {"owner": "DVLA", "can_file": False, "how_to_report": "https://www.gov.uk/report-untaxed-vehicle"}
    if problem_type == "obstructing_vehicle":
        return {"owner": "South Yorkshire Police", "can_file": False, "how_to_report": "Call 101, or 999 if it's an emergency"}
    if problem_type == "burnt_out_vehicle":
        return {"owner": "South Yorkshire Police", "can_file": False, "how_to_report": "Call 101"}

    if _matches(NATIONAL_HIGHWAYS_PATTERNS, road_or_place):
        return {
            "owner": "National Highways",
            "can_file": False,
            "how_to_report": "National Highways: https://nationalhighways.co.uk or 0300 123 5000",
            "reason": "Motorways and some trunk roads in Sheffield are not maintained by the council.",
        }
    if problem_type == "tree":
        # The tree form itself redirects park, housing and private trees, so don't pre-judge the place here.
        return {
            "owner": TREE_OWNER,
            "can_file": True,
            "next_step": "Carry on with the tree steps.",
        }
    if _matches(PRIVATE_PATTERNS, road_or_place):
        return {
            "owner": "The landowner (private)",
            "can_file": False,
            "how_to_report": "Contact the site owner or manager",
            "reason": "Private roads and car parks are not maintained by the council.",
        }

    if problem_type in FILEABLE_TYPES:
        return {
            "owner": "Sheffield City Council (repairs by Amey under the Streets Ahead contract)",
            "can_file": True,
            "form": POTHOLE_FORM,
        }
    return {
        "owner": "Sheffield City Council",
        "can_file": False,
        "how_to_report": f"This prototype only files road and pavement defects. Call {COUNCIL_PHONE} or use sheffield.gov.uk.",
    }


def assess_pothole(surface: str, depth_mm: float) -> dict:
    """Map a depth estimate onto the council form's depth option and suggest a priority."""
    if surface not in DEPTH_THRESHOLD_MM:
        raise ValueError("surface must be 'road' or 'pavement'")
    if depth_mm < 0:
        raise ValueError("depth_mm must be zero or more")
    threshold = DEPTH_THRESHOLD_MM[surface]
    deep = depth_mm > threshold
    return {
        "depth_band": f"{'Greater' if deep else 'Less'} than {threshold}mm",
        "suggested_category": 1 if deep else 2,
        "category_meaning": (
            "Category 1: immediate safety risk, made safe within 24 hours"
            if deep else
            "Category 2: no immediate risk, fixed through planned maintenance"
        ),
        "note": "Suggestion only. The council decides the category after inspection.",
    }


# Exact length units, in mm per unit. Keys are lower-case; plurals and abbreviations are aliases.
EXACT_UNITS_MM = {
    "mm": 1, "millimetre": 1, "millimeter": 1,
    "cm": 10, "centimetre": 10, "centimeter": 10,
    "m": 1000, "metre": 1000, "meter": 1000,
    "in": 25.4, "inch": 25.4, '"': 25.4,
    "ft": 304.8, "foot": 304.8, "feet": 304.8, "'": 304.8,
    "yd": 914.4, "yard": 914.4,
}
# Everyday comparisons people use for depth, as rough mm. Results are flagged as approximate.
APPROX_UNITS_MM = {
    "finger": 20, "finger width": 20,
    "thumb": 25, "thumb width": 25,
    "hand": 100, "hand width": 100, "fist": 100,
    "pound coin": 23, "£1 coin": 23, "coin": 23,
    "golf ball": 43,
    "tennis ball": 67,
    "brick": 65,
    "phone": 150, "mobile phone": 150,
    "pencil": 175,
    "ruler": 300,
    "shoe": 280,
}


def _unit_key(unit: str) -> str:
    key = re.sub(r"\s+", " ", unit.strip().lower().rstrip("."))
    key = re.sub(r"^(a|an|one)\s+", "", key)
    key = re.sub(r"(es|s)?\s*(deep|depth|high|wide|width|long)$", "", key).strip() if key not in APPROX_UNITS_MM else key
    for candidate in (key, key.removesuffix("es"), key.removesuffix("s")):
        if candidate in EXACT_UNITS_MM or candidate in APPROX_UNITS_MM:
            return candidate
    return key


def convert_to_mm(amount: float, unit: str) -> dict:
    """Convert a length in any common unit, or an everyday comparison like 'golf ball', into millimetres."""
    if amount < 0:
        raise ValueError("amount must be zero or more")
    key = _unit_key(unit)
    if key in EXACT_UNITS_MM:
        return {"mm": round(amount * EXACT_UNITS_MM[key], 1), "approximate": False}
    if key in APPROX_UNITS_MM:
        return {
            "mm": round(amount * APPROX_UNITS_MM[key], 1),
            "approximate": True,
            "note": f"Rough estimate: one {key} is about {APPROX_UNITS_MM[key]}mm.",
        }
    known = sorted({*EXACT_UNITS_MM, *APPROX_UNITS_MM} - {'"', "'"})
    raise ValueError(f"Unknown unit {unit!r}. Ask the user for a depth in cm or inches, or use one of: {known}")


def _new_reference() -> str:
    return f"SCC-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(2).upper()}"


def file_report(surface: str, depth_band: str, location: str, description: str, suggested_category: int | None = None) -> dict:
    """Record a completed road or pavement defect report and return its reference number."""
    if surface not in FORM_SURFACE:
        raise ValueError("surface must be 'road' or 'pavement'")
    threshold = DEPTH_THRESHOLD_MM[surface]
    allowed = {f"Less than {threshold}mm", f"Greater than {threshold}mm"}
    if depth_band not in allowed:
        raise ValueError(f"depth_band for {surface} must be one of {sorted(allowed)}; call assess_pothole first")
    if not location.strip():
        raise ValueError("location is required: ask the user where the problem is")
    if not description.strip():
        raise ValueError("description is required")

    reference = _new_reference()
    # Field names match the council form, so this payload could pre-fill it.
    depth_field = "rad_road_pothole_depth" if surface == "road" else "rad_path_pothole_depth"
    record = {
        "reference": reference,
        "filed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "suggested_category": suggested_category,
        "form_payload": {
            "rad_problem_location": FORM_SURFACE[surface],
            depth_field: depth_band,
            "txt_find_address_about_the_location": location.strip(),
            "txta_details_about_the_location": description.strip(),
        },
    }
    return _save_report(record)


def _save_report(record: dict) -> dict:
    path = Path(config.REPORTS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return {"reference": record["reference"], "url": f"/reports/{record['reference']}",
            "status": "recorded (prototype: not sent to the council)"}


# The council's tree form (src/mock/report_tree.html): option values, and the advice it shows instead of
# a Next button when it can't take the report. Kept in step with tree_form_toolkit.py, the browser branch.
TREE_LOCATIONS = ["Highway", "Park", "Housing", "Private"]
TREE_PROBLEMS = ["Fallen", "Dangerous", "Obstruction", "Roots", "Utility", "Nuisance", "Other"]
TREE_OWNER = "Sheffield City Council (street trees are looked after by Amey under the Streets Ahead contract)"
TREE_BLOCKING_PROBLEMS = {"Fallen", "Dangerous", "Obstruction"}
TREE_REDIRECTS = {
    "Park": "Trees in parks and green spaces are looked after by Parks and Countryside. Report it through "
            "Parks and green spaces on sheffield.gov.uk.",
    "Housing": "Trees on council housing land are looked after by Estate Services. Contact Estate Services. "
               "If you rent from a housing association, contact them instead.",
    "Private": "Trees and hedges are the responsibility of the person who owns the land. Speak to the owner first. "
               "If a private tree or hedge is growing over the road or pavement, report it as a tree on or next "
               "to a road or pavement instead.",
    "Utility": "If a tree interferes with a phone line or electricity cable, contact the relevant utility company. "
               "If you are worried the tree itself is unsafe, report it as dangerous instead.",
    "Nuisance": "The council does not remove or prune trees because of falling fruit or bird mess. To report "
                "leaves that are a safety hazard, use 'Report leaves that are a safety hazard' on sheffield.gov.uk.",
}


def assess_tree(tree_location: str, problem: str | None = None, blocking: bool | None = None) -> dict:
    """Check whether the council's tree form takes this report, and whether it is urgent."""
    if tree_location not in TREE_LOCATIONS:
        raise ValueError(f"tree_location must be one of {TREE_LOCATIONS}")
    if tree_location != "Highway":
        return {"can_file": False, "redirect": TREE_REDIRECTS[tree_location],
                "next_step": "Stop. Tell the user this advice in plain words; don't file a report."}
    if problem not in TREE_PROBLEMS:
        raise ValueError(f"problem is required for a tree on or next to a road or pavement: one of {TREE_PROBLEMS}")
    if problem in TREE_REDIRECTS:
        return {"can_file": False, "redirect": TREE_REDIRECTS[problem],
                "next_step": "Stop. Tell the user this advice in plain words; don't file a report."}
    if problem in TREE_BLOCKING_PROBLEMS and blocking is None:
        raise ValueError("blocking is required: ask whether the tree is blocking the road or pavement now")
    result = {"can_file": True, "next_step": "Call file_tree_report with these values, the location and a description."}
    if problem == "Fallen" or (problem == "Dangerous" and blocking):
        result["urgent_advice"] = (f"If the tree is putting people in danger, phone the council now on {COUNCIL_PHONE} "
                                   "(999 if anyone is hurt).")
    return result


def file_tree_report(tree_location: str, problem: str, location: str, description: str,
                     blocking: bool | None = None) -> dict:
    """Record a completed street tree report and return its reference number."""
    assessment = assess_tree(tree_location, problem, blocking)
    if not assessment["can_file"]:
        raise ValueError(f"This can't be filed: {assessment['redirect']}")
    if not location.strip():
        raise ValueError("location is required: ask the user where the tree is")
    if not description.strip():
        raise ValueError("description is required")

    # Field names match the council's tree form, so this payload could pre-fill it.
    payload = {"rad_tree_location": tree_location, "rad_tree_problem": problem}
    if problem in TREE_BLOCKING_PROBLEMS:
        payload["rad_tree_blocking"] = "Yes" if blocking else "No"
    payload |= {"txt_find_address_about_the_location": location.strip(),
                "txta_details_about_the_location": description.strip()}
    result = _save_report({
        "reference": _new_reference(),
        "filed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "form": "report_tree",
        "form_payload": payload,
    })
    result["owner"] = TREE_OWNER
    if "urgent_advice" in assessment:
        result["urgent_advice"] = assessment["urgent_advice"]
    return result


TOOLS = {f.__name__: f for f in (route_report, convert_to_mm, assess_pothole, file_report, assess_tree, file_tree_report)}

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "convert_to_mm",
            "description": (
                "Convert a depth or size the user gave into millimetres: cm, m, inches, feet, or an everyday "
                "comparison such as 'finger', 'golf ball', 'brick' or 'hand'. Use the result as depth_mm."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "How many of the unit, e.g. 2 for 'two inches', 0.5 for 'half a brick'"},
                    "unit": {"type": "string", "description": "The unit or comparison, e.g. 'cm', 'inches', 'golf ball', 'finger'"},
                },
                "required": ["amount", "unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "route_report",
            "description": "Find out who is responsible for a reported problem and whether this service can file it. Always call this first, before file_report or the tree form tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "problem_type": {"type": "string", "enum": PROBLEM_TYPES},
                    "road_or_place": {"type": "string", "description": "Street, road name or place, as the user described it"},
                },
                "required": ["problem_type", "road_or_place"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assess_pothole",
            "description": "Turn an estimated pothole depth into the council form's depth option and a suggested priority category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "surface": {"type": "string", "enum": ["road", "pavement"]},
                    "depth_mm": {"type": "number", "description": "Estimated depth in millimetres (5 cm = 50 mm)"},
                },
                "required": ["surface", "depth_mm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_report",
            "description": "File the road or pavement defect report. Only call after route_report returned can_file=true and assess_pothole gave a depth_band.",
            "parameters": {
                "type": "object",
                "properties": {
                    "surface": {"type": "string", "enum": ["road", "pavement"]},
                    "depth_band": {"type": "string", "description": "Exactly the depth_band returned by assess_pothole"},
                    "location": {"type": "string", "description": "Address or street plus a landmark"},
                    "description": {"type": "string", "description": "Short description of the problem for the inspector"},
                    "suggested_category": {"type": "integer", "enum": [1, 2]},
                },
                "required": ["surface", "depth_band", "location", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assess_tree",
            "description": ("Check whether a street tree problem can be filed, and whether it is urgent. "
                            "If can_file is false, give the user the redirect advice and stop."),
            "parameters": {
                "type": "object",
                "properties": {
                    "tree_location": {"type": "string", "enum": TREE_LOCATIONS, "description": (
                        "Highway: on or next to a road or pavement. Park: park, woodland or green space. "
                        "Housing: council housing estate. Private: private garden or land.")},
                    "problem": {"type": "string", "enum": TREE_PROBLEMS, "description": (
                        "Only for Highway. Fallen: tree or large branch has fallen. Dangerous: leaning, split, "
                        "hanging branch, dead or diseased. Obstruction: overhanging or blocking road, pavement, sign "
                        "or street light. Roots: roots damaging pavement or road. Utility: touching a phone line or "
                        "power cable. Nuisance: fruit, leaves, sap or bird mess. Other: something else.")},
                    "blocking": {"type": "boolean",
                                 "description": "For Fallen, Dangerous or Obstruction: is it blocking the road or pavement now?"},
                },
                "required": ["tree_location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_tree_report",
            "description": "File the street tree report. Only call after assess_tree returned can_file=true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tree_location": {"type": "string", "enum": ["Highway"]},
                    "problem": {"type": "string", "enum": TREE_PROBLEMS},
                    "blocking": {"type": "boolean"},
                    "location": {"type": "string", "description": "Address or street plus a landmark"},
                    "description": {"type": "string", "description": "Short description of the problem for the inspector"},
                },
                "required": ["tree_location", "problem", "location", "description"],
            },
        },
    },
]


def call_tool(name: str, arguments: str | dict | None) -> dict:
    """Run a tool by name. Errors come back as {"error": ...} so the model can correct itself."""
    if name not in TOOLS:
        return {"error": f"Unknown tool {name!r}. Available: {sorted(TOOLS)}"}
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
        return TOOLS[name](**args)
    except json.JSONDecodeError as e:
        return {"error": f"Arguments were not valid JSON: {e}"}
    except (TypeError, ValueError) as e:
        return {"error": str(e)}


def langchain_tools(names: list[str] | None = None) -> list:
    """The same tools as LangChain StructuredTools, for build_agent / create_agent.

    Each returns JSON text, and errors come back as {"error": ...} via call_tool, as in the OpenAI loop.
    """
    from langchain_core.tools import StructuredTool

    def wrap(schema: dict) -> StructuredTool:
        spec = schema["function"]
        name = spec["name"]

        def run(**kwargs) -> str:
            return json.dumps(call_tool(name, kwargs))

        return StructuredTool.from_function(func=run, name=name, description=spec["description"],
                                            args_schema=spec["parameters"])

    return [wrap(s) for s in SCHEMAS if names is None or s["function"]["name"] in names]
