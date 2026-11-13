"""Submissions dashboard: what the agents (and people) have submitted to the dummy council forms.

Sources, all JSON lines under data/ (git-ignored):
- config.MOCK_SUBMISSIONS_PATH: full mock-form records saved by the form agents (council_form.py), source "form_agent".
- config.REPORTS_PATH: reports filed by the chat agent's file_report tool (tools.py), source "chat_agent".
- config.USAGE_PATH: the /mock/ access log (usage.py). Submit events whose reference isn't in the files above
  (someone filling in the form by hand in a browser) appear with source "browser", with the location the form sent.
  Page views feed the view counts.

GET /dashboard serves static/dashboard.html, which polls GET /api/submissions.
GET /reports/{reference} serves static/report.html, which renders GET /api/reports/{reference} for the resident.
Both pages draw reports with static/report-card.js.
Reporter details (name, date of birth, phone, email) are never written to disk by save_submission.

Every item has a triage dict (triage.py): stored on the record when it was filed, or worked out when read.
Every item has lat/lon (None if the place couldn't be found) and geo_source: "form" when picked on the form's
address search or map, "device" when the chat user shared their device location, otherwise the geocode.py lookup that placed the typed text ("sample", "postcodes.io", "photon").
Every item has road_class (OSM highway=*, or None) and a duplicate group (dedup.py); triage_context.py turns both
into triage signals (an A road, "Reported 3 times in 8 days").
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import config, dedup, triage_context
from .geocode import geocode, le_gis
from .photos import photo_url
from .triage import by_priority, combine_signals, safe_triage
from .triage_llm import cached_signals, enrich_in_background

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
DASHBOARD_HTML = STATIC_DIR / "dashboard.html"
REPORT_HTML = STATIC_DIR / "report.html"
PERSONAL_FIELDS = {"sel_title", "txt_firstname", "txt_surname", "txt_date_of_birth", "dt_date_of_birth",
                   "tel_phone_number", "eml_address"}
FORM_NAMES = {"report_pothole_crack": "Pothole or crack", "report_tree": "Tree problem",
              "road-report-agent": "Road report (prototype)"}
AGENT_UA_MARKERS = ("HeadlessChrome", "Playwright")

router = APIRouter()
_write_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def without_personal_details(record: dict) -> dict:
    fields = {k: v for k, v in (record.get("fields") or {}).items() if k not in PERSONAL_FIELDS}
    return {**record, "fields": fields}


def _typed_location(fields: dict) -> str:
    return fields.get("txt_full_address_about_the_location") or fields.get("txt_find_address_about_the_location") or ""


def save_submission(record: dict) -> None:
    """Append a mock-form record (as read back from the browser) to MOCK_SUBMISSIONS_PATH. Never raises.

    If the form has no coordinates (the agent used the address as typed), the typed address is geocoded.
    """
    try:
        record = without_personal_details(record)
        if not record.get("le_gis"):
            geo = geocode(_typed_location(record["fields"]))
            if geo:
                record = {**record, "le_gis": le_gis(geo), "geo_source": geo["source"]}
                if geo.get("road_class"):
                    record["road_class"] = geo["road_class"]
        record = {**record, "triage": safe_triage({"form": record.get("form"), "fields": record["fields"],
                                                    "reference": record.get("reference")})}
        line = json.dumps({"recorded_at": _now(), **record})
        path = Path(config.MOCK_SUBMISSIONS_PATH)
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        enrich_in_background(record.get("reference"), record["fields"].get("txta_details_about_the_location", ""),
                             record.get("form"))
    except Exception:  # The dashboard is a nice-to-have; it must not break the submit tool.
        log.exception("could not save mock submission")


def _read_jsonl(path: Path) -> list[dict]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _latlon(value) -> tuple[float | None, float | None]:
    try:
        lat, lon = (float(x) for x in str(value).split(","))
        return lat, lon
    except ValueError:
        return None, None


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _problem(fields: dict) -> str:
    if fields.get("rad_tree_problem") or fields.get("rad_tree_location"):
        parts = [fields.get("rad_tree_problem") or fields.get("rad_tree_location")]
        if fields.get("rad_tree_blocking") == "Yes":
            parts.append("blocking")
        return ", ".join(parts)
    surface = (fields.get("rad_problem_location") or "").replace(" Surface", "")
    depth = fields.get("rad_road_pothole_depth") or fields.get("rad_path_pothole_depth") or ""
    return f"{surface}: {depth}" if surface and depth else surface or depth


def _photo_url_of(item: dict) -> str | None:
    """/photos/<id>.jpg if the report has an uploaded photo (photos.py) that still exists, else None."""
    raw = item.get("raw") or {}
    fields = raw.get("fields") or raw.get("form_payload") or {}
    photo_id = (raw.get("photo") or {}).get("photo_id") or str(fields.get("txt_file_name_image_of_defect") or "")
    return photo_url(photo_id) if photo_id else None


def _from_mock(r: dict) -> dict:
    fields = r.get("fields") or {}
    lat, lon = _latlon(r.get("le_gis", ""))
    return {
        "source": "form_agent",
        "form": r.get("form", ""),
        "reference": str(r.get("reference", "")),
        "submitted_at": r.get("txt_finish_date_and_time") or r.get("recorded_at", ""),
        "title": r.get("le_title", ""),
        "location": _typed_location(fields),
        "details": fields.get("txta_details_about_the_location", ""),
        "problem": _problem(fields),
        "anonymous": r.get("anonymous"),
        "lat": lat,
        "lon": lon,
        "geo_source": (r.get("geo_source") or "form") if lat is not None else None,
        "road_class": r.get("road_class"),
        "raw": without_personal_details(r),
    }


def _from_report(r: dict) -> dict:
    payload = r.get("form_payload") or {}
    geo = r.get("geo") or {}
    if not geo and payload.get("le_gis_lat"):  # filed with a shared device location before reports carried geo
        geo = {"lat": payload["le_gis_lat"], "lon": payload.get("le_gis_lon"), "source": "device"}
    lat, lon = _number(geo.get("lat")), _number(geo.get("lon"))
    form = r.get("form") or "report_pothole_crack"  # file_tree_report sets "report_tree"; older records have no form
    return {
        "source": "chat_agent",
        "form": form,
        "reference": str(r.get("reference", "")),
        "submitted_at": r.get("filed_at", ""),
        "title": "Problem with a tree" if form == "report_tree" else "Pothole or crack on the highway",
        "location": payload.get("txt_find_address_about_the_location", ""),
        "details": payload.get("txta_details_about_the_location", ""),
        "problem": _problem(payload),
        "anonymous": None,
        "lat": lat,
        "lon": lon,
        "geo_source": geo.get("source") if lat is not None and lon is not None else None,
        "road_class": geo.get("road_class"),
        "raw": r,
    }


def _from_usage(r: dict) -> dict:
    form = str(r.get("page", "")).removesuffix(".html")
    lat, lon = _number(r.get("lat")), _number(r.get("lon"))
    return {
        "source": "browser",
        "form": form,
        "reference": str(r.get("reference", "")),
        "submitted_at": r.get("ts", ""),
        "title": FORM_NAMES.get(form, form),
        "location": str(r.get("location") or ""),
        "details": "",
        "problem": "",
        "anonymous": None,
        "lat": lat,
        "lon": lon,
        "geo_source": r.get("geo_source") if lat is not None and lon is not None else None,
        "road_class": None,
        "raw": {k: r.get(k) for k in ("ts", "event", "page", "reference", "user_agent", "location", "lat", "lon", "geo_source")},
    }


def _ts(item: dict) -> datetime:
    try:
        t = datetime.fromisoformat(str(item["submitted_at"]).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def load_submissions() -> dict[str, Any]:
    """All submissions, newest first, plus page-view counts from the usage log."""
    items = [_from_mock(r) for r in _read_jsonl(config.MOCK_SUBMISSIONS_PATH)]
    items += [_from_report(r) for r in _read_jsonl(config.REPORTS_PATH)]
    known = {i["reference"] for i in items if i["reference"]}
    views: dict[str, dict[str, int]] = {}
    for r in _read_jsonl(config.USAGE_PATH):
        if r.get("event") == "submit" and str(r.get("reference", "")) not in known:
            items.append(_from_usage(r))
        elif r.get("event") == "view":
            who = "agent" if any(m in str(r.get("user_agent", "")) for m in AGENT_UA_MARKERS) else "person"
            page = views.setdefault(str(r.get("page", "")).removesuffix(".html"), {"agent": 0, "person": 0})
            page[who] += 1
    groups = dedup.group(items)  # annotates every item with item["duplicate"]
    contexts = triage_context.annotate(items, _ts)  # road class and repeat-report signals (uses the dedup groups)
    for i, context in zip(items, contexts):
        # Stored when filed, or worked out now for older records and browser submissions. Re-worked when the local
        # LLM (#26) or the map context (#27) adds signals, since both arrive after the report was filed.
        sig = combine_signals(cached_signals(i["reference"]), context)
        i["triage"] = safe_triage(i, sig) if sig else (i["raw"] or {}).get("triage") or safe_triage(i)
        i["photo_url"] = _photo_url_of(i)
    items.sort(key=_ts, reverse=True)
    return {"generated_at": _now(), "count": len(items), "by_priority": by_priority(items), "forms": FORM_NAMES,
            "views": views, "submissions": items,
            "groups": groups, "dedup": {"radius_m": config.DEDUP_RADIUS_M, "window_days": config.DEDUP_WINDOW_DAYS}}


def similar_reports(form: str, lat: float | None = None, lon: float | None = None, location: str = "",
                    problem: str = "", exclude_reference: str = "") -> dict:
    """Earlier reports like this one (dedup.similar over everything submitted so far). Never raises."""
    try:
        return dedup.similar(load_submissions()["submissions"], form, lat, lon, location, problem, exclude_reference)
    except Exception:  # Duplicate detection is a nice-to-have; it must not break filing.
        log.exception("could not check for similar reports")
        return {"count": 0, "message": ""}


def similar_to_reference(reference: str) -> dict:
    """Similar reports for one just-filed report, found by its reference. Never raises."""
    try:
        item = find_submission(reference)
        if item is None:
            return {"count": 0, "message": ""}
        problem = (dedup._fields(item).get("rad_tree_problem") or "") if item.get("form") == "report_tree" else ""
        return similar_reports(item.get("form", ""), item.get("lat"), item.get("lon"), item.get("location", ""),
                               problem, exclude_reference=reference)
    except Exception:
        log.exception("could not check for similar reports")
        return {"count": 0, "message": ""}


@router.get("/api/submissions")
def api_submissions() -> dict[str, Any]:
    return load_submissions()


@router.get("/dashboard", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_HTML, media_type="text/html")


def find_submission(reference: str) -> dict | None:
    """The newest submission with this reference, or None."""
    return next((i for i in load_submissions()["submissions"] if i["reference"] == reference), None)


@router.get("/api/reports/{reference}")
def api_report(reference: str) -> dict[str, Any]:
    item = find_submission(reference) if reference else None
    if item is None:
        raise HTTPException(status_code=404, detail="report not found")
    return {"report": item, "forms": FORM_NAMES}


@router.get("/reports/{reference}", include_in_schema=False)
def report_page(reference: str) -> FileResponse:
    return FileResponse(REPORT_HTML, media_type="text/html")
