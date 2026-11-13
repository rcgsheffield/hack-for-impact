"""Local-model triage signals (src/app/triage_llm.py): mapping, failures, cache and the dashboard read."""

import json

import httpx
import pytest

from app import config, submissions
from app import triage_llm as tl
from app.triage import combine_signals, triage


def model_reply(**fields) -> dict:
    raw = {"injury_reported": False, "vulnerable_users": [], "blocking": False, "traffic_exposure": "medium",
           "hazard_summary": "pothole", "confidence": 0.9, **fields}
    return {"message": {"role": "assistant", "content": json.dumps(raw)}}


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=httpx.Request("POST", "http://x"), response=None)

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


@pytest.fixture
def ollama(monkeypatch):
    """Replace the HTTP call; set ollama.reply to a body, or to an exception to raise."""
    class Fake:
        reply = model_reply()
        calls = []

    def post(url, json=None, timeout=None):
        Fake.calls.append({"url": url, "json": json, "timeout": timeout})
        if isinstance(Fake.reply, BaseException):
            raise Fake.reply
        return FakeResponse(Fake.reply)

    monkeypatch.setattr(tl.httpx, "post", post)
    Fake.calls = []
    return Fake


def pothole(details):
    return {"form": "report_pothole_crack", "details": details,
            "fields": {"rad_problem_location": "Road Surface", "rad_road_pothole_depth": "Less than 40mm"}}


def test_request_is_structured_at_temperature_zero(ollama):
    tl.extract_signals("big hole")
    body = ollama.calls[0]["json"]
    assert ollama.calls[0]["url"] == f"{config.OLLAMA_URL}/api/chat"
    assert body["format"] == tl.SCHEMA and body["options"]["temperature"] == 0 and body["stream"] is False
    assert ollama.calls[0]["timeout"] == config.TRIAGE_LLM_TIMEOUT


def test_valid_json_maps_to_points_in_code(ollama):
    ollama.reply = model_reply(injury_reported=True, blocking=True, vulnerable_users=["elderly", "pedestrians"],
                               traffic_exposure="high", hazard_summary="woman tripped")
    s = tl.extract_signals("my mum went flying on it last night")
    assert s["engine"] == "llm" and s["raw"]["hazard_summary"] == "woman tripped"
    assert [r["points"] for r in s["reasons"]] == [tl.INJURY_POINTS, tl.BLOCKING_POINTS, tl.VULNERABLE_POINTS,
                                                   tl.HIGH_TRAFFIC_POINTS]


def test_model_points_are_ignored(ollama):
    ollama.reply = model_reply(injury_reported=True, points=999, priority="P1")
    s = tl.extract_signals("someone went flying")
    assert s["reasons"] == [{"points": tl.INJURY_POINTS, "reason": tl.MAPPING["injury"][1], "hazard": True}]


def test_low_confidence_is_ignored(ollama):
    ollama.reply = model_reply(injury_reported=True, confidence=0.2)
    assert tl.extract_signals("hmm") is None


@pytest.mark.parametrize("reply", [
    {"message": {"content": "not json {"}},          # malformed JSON
    {"message": {"content": "[1, 2]"}},             # JSON, wrong shape
    {"nothing": "here"},                             # unexpected envelope
    httpx.ReadTimeout("timed out"),                 # timeout
    httpx.ConnectError("Ollama down"),              # server down
])
def test_failures_fall_back_to_rules(ollama, reply):
    ollama.reply = reply
    assert tl.extract_signals("a man went flying over his handlebars here") is None
    item = pothole("a man went flying over his handlebars here")
    assert triage(item, combine_signals(tl.enrich("REF1", item["details"]))) == triage(item)
    assert tl.cached_signals("REF1") is None


def test_empty_text_makes_no_call(ollama):
    assert tl.extract_signals("   ") is None and ollama.calls == []


def test_llm_finds_injury_rules_miss(ollama):
    """Done-when for #26: the model reads an injury the keyword rules miss, so the priority goes up with its reason."""
    text = "a cyclist went over the handlebars on it"
    ollama.reply = model_reply(injury_reported=True, vulnerable_users=["cyclists"], hazard_summary="cyclist thrown off")
    before = triage(pothole(text))
    after = triage(pothole(text), combine_signals(tl.extract_signals(text)))
    assert before["priority"] == "P3"
    assert after["priority"] == "P1" and after["engine"] == "rules+llm"
    assert tl.MAPPING["injury"][1] in after["reasons"]
    assert tl.MAPPING["cyclists"][1] not in after["reasons"]  # the "cyclist" keyword rule already counted it


def test_cyclist_came_off_is_not_double_counted(ollama):
    """'a cyclist came off on it' already hits the injury and cyclist keyword rules (P1); the model adds no points."""
    text = "a cyclist came off on it"
    ollama.reply = model_reply(injury_reported=True, vulnerable_users=["cyclists"])
    s = tl.extract_signals(text)
    assert s["reasons"] == [] and s["raw"]["injury_reported"] is True
    assert triage(pothole(text), combine_signals(s)) == triage(pothole(text))
    assert triage(pothole(text))["priority"] == "P1"


def test_cache_and_dashboard_use_signals(ollama, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORTS_PATH", tmp_path / "reports.jsonl")
    monkeypatch.setattr(config, "USAGE_PATH", tmp_path / "usage.jsonl")
    from app.tools import file_report
    text = "a man went flying over his handlebars here"
    ref = file_report("road", "Less than 40mm", "Division Street", text)["reference"]
    assert submissions.find_submission(ref)["triage"]["priority"] == "P3"  # TRIAGE_LLM off in tests: no thread

    ollama.reply = model_reply(injury_reported=True)
    assert tl.enrich(ref, text)["reasons"]
    assert tl.cached_signals(ref)["engine"] == "llm"
    t = submissions.find_submission(ref)["triage"]
    assert t["priority"] == "P2" and t["engine"] == "rules+llm" and tl.MAPPING["injury"][1] in t["reasons"]


def test_background_runs_only_when_enabled(ollama, monkeypatch):
    started = []
    monkeypatch.setattr(tl.threading, "Thread", lambda **kw: started.append(kw) or type("T", (), {"start": lambda s: None})())
    tl.enrich_in_background("REF2", "text")
    assert started == []
    monkeypatch.setattr(config, "TRIAGE_LLM", True)
    tl.enrich_in_background("REF2", "text")
    tl.enrich_in_background("REF3", "")
    assert [s["args"] for s in started] == [("REF2", "text")]


def _reachable() -> bool:
    try:
        return httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=2).status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _reachable(), reason="OLLAMA_URL not reachable")
def test_live_model_reads_injury():
    s = tl.extract_signals("my mum went flying over the edge of this hole last night and hurt her wrist")
    assert s is not None and s["raw"]["injury_reported"] is True
