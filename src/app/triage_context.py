"""Map context signals for triage (#27): what kind of road a report is on and how many people have reported it.

The council prioritises potholes "by size, depth, road usage, risk to drivers/cyclists/pedestrians"
(docs/sheffield-council-services.md, "Potholes and road/pavement defects"). Its inspection cadence shows how it weighs
road usage: A/B roads are inspected monthly, link roads every 3 months, residential streets yearly. So a defect on a
busier road class gets more points; a residential street or service road gets none.

Road class is OpenStreetMap's highway=* value, kept from Photon by geocode.py (geo["road_class"]).

Repeat reports: dedup.py groups reports of the same problem (same kind, within config.DEDUP_RADIUS_M and
config.DEDUP_WINDOW_DAYS). Every report in a group gets the same repeat-report points, so the whole group rises in
the queue.

The output is a signals dict for triage.triage(): {"engine": "context", "reasons": [{"points", "reason"}, ...]}.
Signals only add points; the rules engine still decides the priority.
"""

from __future__ import annotations

from datetime import datetime

ENGINE = "context"

# OSM highway=* -> (points, reason). A/B roads (trunk/primary/secondary) are inspected monthly, so they score most.
ROAD_CLASS_POINTS = {
    "motorway": (20, "On a major road (heavy traffic)"),
    "trunk": (20, "On an A road (heavy traffic, inspected monthly)"),
    "primary": (20, "On an A road (heavy traffic, inspected monthly)"),
    "secondary": (15, "On a B road (busy, inspected monthly)"),
    "tertiary": (5, "On a link road (inspected every 3 months)"),
    "cycleway": (10, "On a cycle path: risk to cyclists"),
    "footway": (5, "On a footpath: risk to pedestrians"),
    "pedestrian": (5, "On a pedestrian street: risk to pedestrians"),
    # residential, service, unclassified, living_street, track: no extra points (inspected yearly at most).
}
for _link in ("motorway", "trunk", "primary", "secondary", "tertiary"):  # slip roads count as their road
    ROAD_CLASS_POINTS[f"{_link}_link"] = ROAD_CLASS_POINTS[_link]

REPEAT_POINTS_PER_REPORT = 10         # each report after the first...
MAX_REPEAT_POINTS = 30                # ...up to this: repeats alone lift a routine report (30) to P2, never P1


def road_class_reason(road_class: str | None) -> dict | None:
    hit = ROAD_CLASS_POINTS.get(str(road_class or "").lower())
    return {"points": hit[0], "reason": hit[1]} if hit else None


def _span(days: int) -> str:
    return "today" if days < 1 else "in 1 day" if days == 1 else f"in {days} days"


def repeat_reason(count: int, first: datetime, last: datetime) -> dict | None:
    if count < 2:
        return None
    points = min(MAX_REPEAT_POINTS, REPEAT_POINTS_PER_REPORT * (count - 1))
    # Counted from the map, so it replaces the keyword rule for "reported before" in the resident's words.
    return {"points": points, "reason": f"Reported {count} times {_span((last - first).days)}",
            "replaces": "Reported before"}


def annotate(items: list[dict], ts) -> list[dict | None]:
    """Each item's context signals, aligned with items (None if none). ts(item) -> aware datetime.

    Repeat reports come from dedup.group(), which must already have set item["duplicate"] (one grouping for the
    dashboard, the resident messages and triage, so they always agree).
    """
    spans: dict[str, list] = {}
    for i in items:
        g = (i.get("duplicate") or {}).get("group_id")
        if g:
            spans.setdefault(g, []).append(ts(i))
    out = []
    for i in items:
        dup = i.get("duplicate") or {}
        times = spans.get(dup.get("group_id"), [])
        repeat = repeat_reason(dup.get("group_size", 1), min(times), max(times)) if times else None
        reasons = [r for r in (road_class_reason(i.get("road_class")), repeat) if r]
        out.append({"engine": ENGINE, "reasons": reasons} if reasons else None)
    return out
