"""Map context signals for triage (#27): what kind of road a report is on and how many people have reported it.

The council prioritises potholes "by size, depth, road usage, risk to drivers/cyclists/pedestrians"
(docs/sheffield-council-services.md, "Potholes and road/pavement defects"). Its inspection cadence shows how it weighs
road usage: A/B roads are inspected monthly, link roads every 3 months, residential streets yearly. So a defect on a
busier road class gets more points; a residential street or service road gets none.

Road class is OpenStreetMap's highway=* value, kept from Photon by geocode.py (geo["road_class"]).

Repeat reports: reports of the same form within CLUSTER_RADIUS_M and CLUSTER_WINDOW of each other are one cluster
(single-link: A near B and B near C puts A, B and C together). Every report in a cluster gets the same cluster_id,
report_count and repeat-report points, so the whole cluster rises in the queue.

The output is a signals dict for triage.triage(): {"engine": "context", "reasons": [{"points", "reason"}, ...]}.
Signals only add points; the rules engine still decides the priority.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

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

CLUSTER_RADIUS_M = 25                 # same spot: typical spread of phone GPS and of where people pin a pothole
CLUSTER_WINDOW = timedelta(days=30)   # older reports are probably a new defect, or already fixed
REPEAT_POINTS_PER_REPORT = 10         # each report after the first...
MAX_REPEAT_POINTS = 30                # ...up to this: repeats alone lift a routine report (30) to P2, never P1
EARTH_RADIUS_M = 6_371_000


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle (haversine) distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def road_class_reason(road_class: str | None) -> dict | None:
    hit = ROAD_CLASS_POINTS.get(str(road_class or "").lower())
    return {"points": hit[0], "reason": hit[1]} if hit else None


def _span(days: int) -> str:
    return "today" if days < 1 else "in 1 day" if days == 1 else f"in {days} days"


def repeat_reason(count: int, first: datetime, last: datetime) -> dict | None:
    if count < 2:
        return None
    points = min(MAX_REPEAT_POINTS, REPEAT_POINTS_PER_REPORT * (count - 1))
    return {"points": points, "reason": f"Reported {count} times {_span((last - first).days)}"}


def cluster(items: list[dict], ts) -> None:
    """Set cluster_id and report_count on every item. ts(item) -> aware datetime, or datetime.min if unknown.

    Items without coordinates or a time are their own cluster of one (cluster_id None).
    """
    placed = [i for i in items if i.get("lat") is not None and i.get("lon") is not None and ts(i).year > 1]
    parent = list(range(len(placed)))

    def root(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for a in range(len(placed)):  # O(n^2): fine for a dashboard's worth of reports
        for b in range(a + 1, len(placed)):
            x, y = placed[a], placed[b]
            if (x.get("form") == y.get("form") and abs(ts(x) - ts(y)) <= CLUSTER_WINDOW
                    and distance_m(x["lat"], x["lon"], y["lat"], y["lon"]) <= CLUSTER_RADIUS_M):
                parent[root(a)] = root(b)

    groups: dict[int, list[dict]] = {}
    for k, item in enumerate(placed):
        groups.setdefault(root(k), []).append(item)
    for i in items:
        i["cluster_id"], i["report_count"] = None, 1
    for members in groups.values():
        members.sort(key=ts)
        first = members[0]
        cid = f"C-{first.get('reference') or id(first)}"
        for m in members:
            m["cluster_id"], m["report_count"] = cid, len(members)
            m["_cluster_span"] = (ts(first), ts(members[-1]))


def annotate(items: list[dict], ts) -> list[dict | None]:
    """Cluster the items (in place) and return each one's context signals, aligned with items (None if none)."""
    cluster(items, ts)
    out = []
    for i in items:
        reasons = [r for r in (road_class_reason(i.get("road_class")),
                               repeat_reason(i["report_count"], *i.pop("_cluster_span", (None, None))))
                   if r]
        out.append({"engine": ENGINE, "reasons": reasons} if reasons else None)
    return out
