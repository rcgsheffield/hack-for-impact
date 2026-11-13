"""Serves the dummy council site (src/mock/) at /mock/ and keeps an access log of when it's used.

Each page load and each form submission is appended to config.USAGE_PATH as one JSON line:
    {"ts": "...", "event": "view" | "submit", "page": "report_pothole_crack.html", "user_agent": "...", "referrer": "...", ...}
No IP addresses or form field values are logged. Agent runs show up with a HeadlessChrome user agent.
"""

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import config

MOCK_DIR = Path(__file__).resolve().parents[1] / "mock"
# Only plain page names, so a request can't reach files outside MOCK_DIR.
PAGE_NAME = re.compile(r"^[\w-]+\.html$")

router = APIRouter(prefix="/mock")
_write_lock = threading.Lock()


def log_event(event: str, page: str, request: Request, **extra) -> dict:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        "page": page,
        "user_agent": request.headers.get("user-agent", ""),
        "referrer": request.headers.get("referer", ""),
        **extra,
    }
    path = Path(config.USAGE_PATH)
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    return record


class SubmitEvent(BaseModel):
    event: Literal["submit"]
    page: str = Field(max_length=100)
    reference: str = Field(default="", max_length=50)


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("report_pothole_crack.html")


@router.post("/events", status_code=204)
def submit_event(body: SubmitEvent, request: Request) -> Response:
    """Called by the mock pages (navigator.sendBeacon) when a form is submitted."""
    log_event(body.event, body.page, request, reference=body.reference)
    return Response(status_code=204)


@router.get("/{name}")
def page(name: str, request: Request) -> FileResponse:
    path = MOCK_DIR / name
    if not PAGE_NAME.match(name) or not path.is_file():
        raise HTTPException(status_code=404)
    log_event("view", name, request)
    return FileResponse(path, media_type="text/html")
