"""Duplicate detection: group reports that are probably about the same problem.

Two reports are about the same problem when they are the same kind (see kind()) and were made within
config.DEDUP_WINDOW_DAYS of each other, and either
- both have map coordinates and lie within config.DEDUP_RADIUS_M of the group's first located report, or
- at least one has no coordinates and both name the same street (weaker: flagged as match "street").

Groups are built oldest first around an anchor (the first located report), not by chaining nearest neighbours,
so reports strung along one long road don't merge into a single giant group. The first report is the primary.

Pure functions over the normalised items from submissions.py (dicts with form, reference, submitted_at, source,
lat, lon, location, raw). Nothing here reads files, so submissions.py and tools.py can both use it.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

from . import config

EARTH_RADIUS_M = 6_371_000
FORM_NOUN = {"report_pothole_crack": "pothole or crack", "report_tree": "tree problem"}
STREET_SUFFIXES = {"rd": "road", "st": "street", "ln": "lane", "ave": "avenue", "av": "avenue", "dr": "drive",
                   "cres": "crescent", "cl": "close", "pl": "place", "sq": "square", "gdns": "gardens", "tce": "terrace"}


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _fields(item: dict) -> dict:
    raw = item.get("raw") or {}
    return raw.get("fields") or raw.get("form_payload") or {}


def kind(item: dict) -> tuple[str, str]:
    """(form, sub-kind). Potholes aren't split by surface or depth: those are reporters' judgements.
    Trees are split by problem (a fallen tree and lifting roots at one spot are different jobs); "" matches any."""
    form = item.get("form") or ""
    sub = _fields(item).get("rad_tree_problem", "") if form == "report_tree" else ""
    return form, sub


def _same_kind(a: tuple[str, str], b: tuple[str, str]) -> bool:
    return a[0] == b[0] and (not a[1] or not b[1] or a[1] == b[1])


def street_key(text: str | None) -> str:
    """'120 Abbeydale Rd, Sheffield, S7 1FL' -> 'abbeydale road'. '' if there's no usable street name."""
    first = re.split(r"[,\n]", str(text or "").lower())[0]
    words = re.sub(r"[^a-z0-9' ]", " ", first).split()
    words = [w for w in words if not re.fullmatch(r"\d+[a-z]?", w) and w not in ("outside", "near", "by", "opposite", "the")]
    words = [STREET_SUFFIXES.get(w, w) for w in words]
    key = " ".join(words)
    return key if len(key) >= 4 else ""


def _street_of(item: dict) -> str:
    return street_key(_fields(item).get("txt_street_name_about_the_location") or item.get("location"))


def _located(item: dict) -> bool:
    return isinstance(item.get("lat"), (int, float)) and isinstance(item.get("lon"), (int, float))


def _when(item: dict) -> datetime:
    try:
        t = datetime.fromisoformat(str(item.get("submitted_at")).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def item_key(item: dict) -> str:
    """Same key as the dashboard's keyOf(): source:reference:submitted_at."""
    return f"{item.get('source')}:{item.get('reference')}:{item.get('submitted_at')}"


def _match(item: dict, group: dict, radius_m: float) -> tuple[str, float | None] | None:
    """('distance', metres) or ('street', None) if item belongs in group, else None."""
    if _located(item) and group["anchor"] is not None:
        d = distance_m(item["lat"], item["lon"], *group["anchor"])
        return ("distance", d) if d <= radius_m else None
    street = _street_of(item)
    if street and street in group["streets"]:
        return ("street", None)
    return None


def group(items: list[dict], radius_m: float | None = None, window_days: float | None = None) -> list[dict]:
    """Annotate each item with item["duplicate"] and return the groups with 2 or more reports, biggest first.

    item["duplicate"] = {group_id, group_size, others, is_first, first_reference, first_at, match, distance_m}
    where match is "first", "distance" or "street" (same street, approximate).
    """
    radius_m = config.DEDUP_RADIUS_M if radius_m is None else radius_m
    window = timedelta(days=config.DEDUP_WINDOW_DAYS if window_days is None else window_days)
    groups: list[dict] = []
    for item in sorted(items, key=_when):
        k, t = kind(item), _when(item)
        best = None
        for g in groups:
            if not _same_kind(k, g["kind"]) or t - g["last_at"] > window:
                continue
            m = _match(item, g, radius_m)
            # Nearest distance match wins; a same-street match (weaker evidence) only if there's no distance match.
            score = lambda mm: mm[1] if mm[0] == "distance" else radius_m + 1  # noqa: E731
            if m and (best is None or score(m) < score(best[1])):
                best = (g, m)
        if best is None:
            g = {"kind": k, "members": [], "anchor": None, "streets": set(), "last_at": t}
            groups.append(g)
            match = ("first", None)
        else:
            g, match = best
        if g["anchor"] is None and _located(item):
            g["anchor"] = (item["lat"], item["lon"])
        if (street := _street_of(item)):
            g["streets"].add(street)
        g["last_at"] = max(g["last_at"], t)
        g["members"].append((item, match))

    out = []
    for g in groups:
        first = g["members"][0][0]
        size = len(g["members"])
        for item, (how, d) in g["members"]:
            item["duplicate"] = {
                "group_id": first.get("reference") or item_key(first),
                "group_size": size,
                "others": size - 1,
                "is_first": item is first,
                "first_reference": first.get("reference", ""),
                "first_at": first.get("submitted_at", ""),
                "match": how,
                "distance_m": None if d is None else round(d),
            }
        if size < 2:
            continue
        members = [m for m, _ in g["members"]]
        located = [m for m in members if _located(m)]
        problems = [m.get("problem") for m in members if m.get("problem")]
        out.append({
            "id": first.get("reference") or item_key(first),
            "form": g["kind"][0],
            "problem": max(set(problems), key=problems.count) if problems else "",
            "size": size,
            "approximate": any(how == "street" for _, (how, _) in g["members"]),
            "first_at": first.get("submitted_at", ""),
            "last_at": max((m.get("submitted_at", "") for m in members), default=""),
            "location": next((m.get("location") for m in members if m.get("location")), ""),
            "lat": sum(m["lat"] for m in located) / len(located) if located else None,
            "lon": sum(m["lon"] for m in located) / len(located) if located else None,
            "sources": {s: sum(1 for m in members if m.get("source") == s) for s in {m.get("source") for m in members}},
            "members": [{"key": item_key(m), "reference": m.get("reference", ""), "source": m.get("source", ""),
                         "submitted_at": m.get("submitted_at", "")} for m in reversed(members)],
        })
    out.sort(key=lambda g: (g["size"], g["last_at"]), reverse=True)
    return out


def similar(items: list[dict], form: str, lat: float | None = None, lon: float | None = None, location: str = "",
            problem: str = "", exclude_reference: str = "", now: datetime | None = None) -> dict:
    """Earlier reports like a new one (not yet filed, or just filed as exclude_reference).

    Returns {count, nearest_m, first_at, references, approximate, message}; count 0 means none.
    """
    probe = {"form": form, "lat": lat, "lon": lon, "location": location,
             "raw": {"fields": {"rad_tree_problem": problem} if problem else {}}}
    k, street = kind(probe), _street_of(probe)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=config.DEDUP_WINDOW_DAYS)
    hits = []
    for item in items:
        if exclude_reference and item.get("reference") == exclude_reference:
            continue
        if not _same_kind(k, kind(item)) or _when(item) < cutoff:
            continue
        if lat is not None and lon is not None and _located(item):
            d = distance_m(lat, lon, item["lat"], item["lon"])
            if d <= config.DEDUP_RADIUS_M:
                hits.append((item, d))
        elif street and street == _street_of(item):
            hits.append((item, None))
    hits.sort(key=lambda h: _when(h[0]))
    count = len(hits)
    result = {
        "count": count,
        "nearest_m": min((round(d) for _, d in hits if d is not None), default=None),
        "first_at": hits[0][0].get("submitted_at", "") if hits else "",
        "references": [h[0].get("reference", "") for h in hits][-5:],
        "approximate": any(d is None for _, d in hits),
    }
    result["message"] = similar_message(count, form, result["approximate"]) if count else ""
    return result


def similar_message(count: int, form: str, approximate: bool = False) -> str:
    """What to tell the resident. Counts reports, not people: reports are anonymous and one person may report twice."""
    noun = FORM_NOUN.get(form, "problem")
    where = "on the same street" if approximate else f"within about {round(config.DEDUP_RADIUS_M)} m"
    days = round(config.DEDUP_WINDOW_DAYS)
    reports = "1 other report" if count == 1 else f"{count} other reports"
    return (f"There {'is' if count == 1 else 'are'} {reports} of a similar {noun} {where} in the last {days} days. "
            "Your report is grouped with them, which helps the council see how many people it affects.")
