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
    "untaxed_vehicle", "abandoned_vehicle", "obstructing_vehicle", "burnt_out_vehicle", "other",
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
    path = Path(config.REPORTS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return {"reference": reference, "status": "recorded (prototype: not sent to the council)"}


TOOLS = {f.__name__: f for f in (route_report, assess_pothole, file_report)}

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "route_report",
            "description": "Find out who is responsible for a reported problem and whether this service can file it. Always call this before file_report.",
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


def langchain_tools() -> list:
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

    return [wrap(s) for s in SCHEMAS]
