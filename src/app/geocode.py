"""Turn a typed location ("120 Abbeydale Road", "S7 1FL", "Fargate") into coordinates for a report.

Same lookups, in the same order, as the mock forms' address search (src/mock/report_pothole_crack.html), so a
place resolves to the same point whichever way it was reported:
1. The mocks' built-in sample addresses (works offline, so demos and tests are deterministic).
2. postcodes.io for UK postcodes.
3. Photon (OpenStreetMap) for streets and places, limited to Sheffield.
These are data lookups, not inference. Set GEOCODE_LIVE=0 to use only the sample addresses.

geocode() never raises: a report is filed whether or not its location can be placed.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

import httpx

from . import config

log = logging.getLogger(__name__)

# Sheffield bounding box (west, south, east, north), the same as SHEFFIELD_BBOX in the mocks.
SHEFFIELD_BBOX = (-1.80, 53.30, -1.32, 53.50)
POSTCODE = re.compile(r"^[a-z]{1,2}\d[a-z\d]?\s*\d[a-z]{2}$", re.IGNORECASE)
TIMEOUT_S = 3.0
# Photon wants a place, not a sentence: "Ecclesall Road near the Botanical Gardens" finds nothing, but each side of
# "near" does. Split on these words (and commas) and try the parts, at most MAX_LIVE_TRIES lookups per location.
LANDMARK_SPLIT = re.compile(r",|\b(?:near|outside|opposite|by|next to|behind|in front of|junction with|at|on)\b",
                            re.IGNORECASE)
MAX_LIVE_TRIES = 3
USER_AGENT = "CouncilTriagent-hackathon-prototype"

# The mocks' sample ADDRESSES: (property, street, postcode, lat, lon).
SAMPLE_ADDRESSES = [
    ("120", "Abbeydale Road", "S7 1FL", 53.3631, -1.4876),
    ("124", "Abbeydale Road", "S7 1FL", 53.3627, -1.4879),
    ("45", "Ecclesall Road", "S11 8HU", 53.3700, -1.4890),
    ("210", "Ecclesall Road", "S11 8JA", 53.3668, -1.4985),
    ("12", "Derbyshire Lane", "S8 9EH", 53.3460, -1.4790),
    ("88", "London Road", "S2 4LR", 53.3672, -1.4775),
    ("3", "Division Street", "S1 4GF", 53.3790, -1.4775),
    ("61", "Fulwood Road", "S10 3BA", 53.3818, -1.5020),
    ("17", "Chesterfield Road", "S8 0RL", 53.3505, -1.4720),
    ("250", "Staniforth Road", "S9 3FT", 53.3870, -1.4240),
]


def in_sheffield(lat: float, lon: float) -> bool:
    west, south, east, north = SHEFFIELD_BBOX
    return south <= lat <= north and west <= lon <= east


def _result(lat: float, lon: float, matched: str, source: str, road_class: str | None = None) -> dict | None:
    lat, lon = round(float(lat), 6), round(float(lon), 6)
    if not in_sheffield(lat, lon):
        return None
    out = {"lat": lat, "lon": lon, "matched": matched, "source": source}
    if road_class:
        out["road_class"] = road_class
    return out


def _sample(text: str) -> dict | None:
    q = re.sub(r"\s+", " ", text.lower())
    qn = q.replace(" ", "")
    for prop, street, postcode, lat, lon in SAMPLE_ADDRESSES:
        full = f"{prop} {street}, Sheffield, {postcode}"
        # Whole address or "<number> <street>" somewhere in the text, or the exact postcode.
        if f"{prop} {street}".lower() in q or full.lower() in q or qn == postcode.lower().replace(" ", ""):
            return _result(lat, lon, full, "sample")
    return None


def _postcode(text: str) -> dict | None:
    r = httpx.get(f"https://api.postcodes.io/postcodes/{text.replace(' ', '')}", timeout=TIMEOUT_S,
                  headers={"user-agent": USER_AGENT})
    if r.status_code == 404:
        return None
    p = r.raise_for_status().json()["result"]
    return _result(p["latitude"], p["longitude"], p["postcode"], "postcodes.io")


def _photon(text: str) -> dict | None:
    west, south, east, north = SHEFFIELD_BBOX
    r = httpx.get("https://photon.komoot.io/api/", timeout=TIMEOUT_S, headers={"user-agent": USER_AGENT},
                  params={"q": text, "limit": 1, "lang": "en", "bbox": f"{west},{south},{east},{north}"})
    features = r.raise_for_status().json().get("features") or []
    if not features:
        return None
    p, (lon, lat) = features[0]["properties"], features[0]["geometry"]["coordinates"]
    street = p.get("street") or p.get("name") or ""
    matched = ", ".join(x for x in (p.get("housenumber"), street, p.get("city") or "Sheffield", p.get("postcode")) if x)
    # OSM highway=* value (primary, residential, footway...) when Photon matched a street; triage_context.py uses it.
    road_class = p.get("osm_value") if p.get("osm_key") == "highway" else None
    return _result(lat, lon, matched, "photon", road_class)


def _candidates(text: str) -> list[str]:
    """The whole text, then its parts around landmark words, longest first."""
    parts = sorted({p.strip(" .") for p in LANDMARK_SPLIT.split(text)} - {""}, key=len, reverse=True)
    out = [text] + [p for p in parts if len(p) >= 3 and p != text]
    return out[:MAX_LIVE_TRIES]


@lru_cache(maxsize=512)
def _lookup(text: str, live: bool) -> dict | None:
    found = _sample(text)
    if found or not live:
        return found
    for q in _candidates(text):
        try:
            found = _postcode(q) if POSTCODE.match(q) else _photon(q)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
            log.warning("geocoding %r failed: %s", q, e)
            return None  # the service is down or odd: don't keep trying
        if found:
            return found
    return None


def geocode(text: str | None) -> dict | None:
    """{"lat", "lon", "matched", "source"} (plus "road_class" from Photon street matches) in Sheffield, or None."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) < 2:
        return None
    found = _lookup(text[:200], config.GEOCODE_LIVE)
    return dict(found) if found else None  # a copy, so callers can't change the cached value


def le_gis(geo: dict | None) -> str:
    """The council form's "lat,lon" field for a geocode() result."""
    return f"{geo['lat']},{geo['lon']}" if geo else ""


cache_clear = _lookup.cache_clear
