"""Typed locations become coordinates: sample addresses offline, postcodes.io and Photon when live (faked here)."""

import httpx
import pytest

from app import config, geocode


@pytest.fixture
def live(monkeypatch):
    """Live lookups on, with httpx.get answered by the test's handler instead of the internet."""
    monkeypatch.setattr(config, "GEOCODE_LIVE", True)
    calls = []

    def fake(handler):
        def get(url, **kwargs):
            calls.append((url, kwargs.get("params")))
            status, body = handler(url)
            return httpx.Response(status, json=body, request=httpx.Request("GET", url))
        monkeypatch.setattr(httpx, "get", get)
        return calls
    return fake


@pytest.mark.parametrize("text", ["120 Abbeydale Road", "pothole outside 120  abbeydale road", "s71fl", "S7 1FL"])
def test_sample_addresses_work_offline(text):
    geo = geocode.geocode(text)
    assert (geo["lat"], geo["lon"], geo["source"]) == (53.3631, -1.4876, "sample")


@pytest.mark.parametrize("text", ["", " ", "Fargate", None])
def test_unknown_or_empty_offline_is_none(text):
    assert geocode.geocode(text) is None


def test_postcode_uses_postcodes_io(live):
    calls = live(lambda url: (200, {"result": {"postcode": "S1 2HE", "latitude": 53.3811, "longitude": -1.4701}}))
    assert geocode.geocode("S1 2HE") == {"lat": 53.3811, "lon": -1.4701, "matched": "S1 2HE", "source": "postcodes.io"}
    assert calls[0][0].endswith("/postcodes/S12HE")


def test_place_uses_photon_within_sheffield(live):
    calls = live(lambda url: (200, {"features": [{"geometry": {"coordinates": [-1.4694, 53.3814]},
                                                  "properties": {"name": "Fargate", "city": "Sheffield"}}]}))
    geo = geocode.geocode("Fargate")
    assert (geo["lat"], geo["lon"], geo["matched"], geo["source"]) == (53.3814, -1.4694, "Fargate, Sheffield", "photon")
    assert calls[0][1]["bbox"] == "-1.8,53.3,-1.32,53.5"
    geocode.geocode("Fargate")
    assert len(calls) == 1  # cached


def test_landmark_phrasing_tries_the_parts(live):
    def handler(url):
        q = calls[-1][1]["q"]
        hit = q == "Ecclesall Road"
        return 200, {"features": [{"geometry": {"coordinates": [-1.4985, 53.3668]},
                                   "properties": {"name": "Ecclesall Road"}}] if hit else []}
    calls = live(handler)
    geo = geocode.geocode("Ecclesall Road near the Botanical Gardens")
    assert (geo["lat"], geo["lon"]) == (53.3668, -1.4985)
    assert [c[1]["q"] for c in calls] == ["Ecclesall Road near the Botanical Gardens", "the Botanical Gardens",
                                         "Ecclesall Road"]


def test_results_outside_sheffield_are_dropped(live):
    live(lambda url: (200, {"features": [{"geometry": {"coordinates": [-0.1276, 51.5072]},
                                          "properties": {"name": "London"}}]}))
    assert geocode.geocode("London") is None


@pytest.mark.parametrize("handler", [lambda url: (500, {}), lambda url: (200, {"unexpected": True}),
                                     lambda url: (404, {"error": "Invalid postcode"})])
def test_failures_return_none(live, handler):
    live(handler)
    assert geocode.geocode("Nowhere Street") is None
    assert geocode.geocode("ZZ1 1ZZ") is None


def test_network_error_returns_none(live, monkeypatch):
    live(lambda url: (200, {}))

    def boom(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "get", boom)
    assert geocode.geocode("Fargate") is None


def test_result_is_a_copy():
    geocode.geocode("3 Division Street")["lat"] = 0
    assert geocode.geocode("3 Division Street")["lat"] == 53.379


def test_photon_street_keeps_its_road_class(live):
    live(lambda url: (200, {"features": [{"geometry": {"coordinates": [-1.4876, 53.3631]},
                                          "properties": {"name": "Abbeydale Road", "osm_key": "highway",
                                                         "osm_value": "primary"}}]}))
    assert geocode.geocode("Abbeydale Road")["road_class"] == "primary"


def test_photon_non_street_has_no_road_class(live):
    live(lambda url: (200, {"features": [{"geometry": {"coordinates": [-1.4694, 53.3814]},
                                          "properties": {"name": "Fargate", "osm_key": "place", "osm_value": "square"}}]}))
    assert "road_class" not in geocode.geocode("Fargate")
