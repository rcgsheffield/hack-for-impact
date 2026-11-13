"""Local-model triage signals (src/app/triage_llm.py): mapping, failures, cache and the dashboard read."""

import json

import httpx
import pytest

from app import config, submissions
from app import triage_llm as tl
from app.triage import combine_signals, explain, triage
from app.triage_rubric import GENERIC, POTHOLE, TEXT_NODES


def model_reply(p: float = 0.9, **answers) -> dict:
    """An Ollama reply answering every shared text node: "none" unless given, e.g. injury="yes"."""
    raw = {n.id: {"option": answers.get(n.id, "none"), "p": p} for n in TEXT_NODES}
    raw["hazard_summary"] = answers.get("hazard_summary", "pothole")
    raw.update({k: v for k, v in answers.items() if k not in raw})
    return {"message": {"role": "assistant", "content": json.dumps(raw)}}


def reason(node_id: str) -> str:
    return f"{GENERIC.node(node_id).options['yes'].reason} (read by local AI)"


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


def test_schema_and_prompt_come_from_the_rubric(ollama):
    """Every model node of the form's rubric is one typed question: adding a node needs no code here."""
    tl.extract_signals("big hole", "report_pothole_crack")
    body = ollama.calls[0]["json"]
    props = body["format"]["properties"]
    assert set(props) == {n.id for n in POTHOLE.model_nodes()} | {"hazard_summary"}
    assert props["defect_depth"]["properties"]["option"]["enum"] == list(POTHOLE.node("defect_depth").options)
    assert all(n.question in body["messages"][0]["content"] for n in POTHOLE.model_nodes())


def test_valid_json_maps_to_rubric_points(ollama):
    ollama.reply = model_reply(injury="yes", blocking="yes", vulnerable="yes", traffic="yes",
                               hazard_summary="woman tripped")
    text = "my mum went flying on it last night"
    s = tl.extract_signals(text)
    assert s["engine"] == "llm" and s["raw"]["hazard_summary"] == "woman tripped"
    assert set(s["decisions"]) == {"injury", "blocking", "vulnerable", "traffic"}
    t = triage({"form": "report_pothole_crack", "details": text}, combine_signals(s))
    assert t["score"] == min(100, 30 + 30 + 20 + 15 + 15) and t["priority"] == "P1"   # rubric points, capped
    assert reason("injury") in t["reasons"]


def test_model_points_are_ignored(ollama):
    ollama.reply = model_reply(injury="yes", points=999, priority="P1")
    s = tl.extract_signals("someone went flying")
    assert s["decisions"] == {"injury": {"option": "yes", "p": 0.9, "source": "llm"}}
    t = triage({"form": "report_pothole_crack", "details": "someone went flying"}, combine_signals(s))
    assert t["score"] == 30 + 30 and t["priority"] == "P2"


def test_low_confidence_is_ignored(ollama):
    ollama.reply = model_reply(p=0.2, blocking="yes")
    item = {"form": "report_pothole_crack", "details": "hmm"}
    assert triage(item, combine_signals(tl.extract_signals("hmm"))) == triage(item)


def test_unsure_hazard_is_flagged_for_review_without_points(ollama):
    """A hazard at 0.3 <= p < 0.5 is not scored, but staff see it: under-triage costs more than over-triage."""
    ollama.reply = model_reply(p=0.4, injury="yes")
    item = {"form": "report_pothole_crack", "details": "he went down hard"}
    t = triage(item, combine_signals(tl.extract_signals(item["details"])))
    assert t["score"] == triage(item)["score"] and t["engine"] == "rules+llm"
    assert "Possible: Someone has been hurt (read by local AI, 40%): needs review" in t["reasons"]


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
    ollama.reply = model_reply(injury="yes", cyclists="yes", hazard_summary="cyclist thrown off")
    before = triage(pothole(text))
    after = triage(pothole(text), combine_signals(tl.extract_signals(text)))
    assert before["priority"] == "P3"
    assert after["priority"] == "P1" and after["engine"] == "rules+llm"
    assert reason("injury") in after["reasons"]
    assert reason("cyclists") not in after["reasons"]  # the "cyclist" keyword rule already counted it


def test_cyclist_came_off_is_not_double_counted(ollama):
    """'a cyclist came off on it' already hits the injury and cyclist keyword rules (P1); the model adds no points."""
    text = "a cyclist came off on it"
    ollama.reply = model_reply(injury="yes", cyclists="yes")
    s = tl.extract_signals(text)
    assert set(s["decisions"]) == {"injury", "cyclists"}
    assert triage(pothole(text), combine_signals(s)) == triage(pothole(text))
    assert triage(pothole(text))["priority"] == "P1"


def test_cache_and_dashboard_use_signals(ollama, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORTS_PATH", tmp_path / "reports.jsonl")
    monkeypatch.setattr(config, "USAGE_PATH", tmp_path / "usage.jsonl")
    from app.tools import file_report
    text = "a man went flying over his handlebars here"
    ref = file_report("road", "Less than 40mm", "Division Street", text)["reference"]
    assert submissions.find_submission(ref)["triage"]["priority"] == "P3"  # TRIAGE_LLM off in tests: no thread

    ollama.reply = model_reply(injury="yes")
    assert tl.enrich(ref, text, "report_pothole_crack")["decisions"]
    assert tl.cached_signals(ref)["engine"] == "llm"
    t = submissions.find_submission(ref)["triage"]
    assert t["priority"] == "P2" and t["engine"] == "rules+llm" and reason("injury") in t["reasons"]


def test_old_cache_lines_still_apply(tmp_path, monkeypatch):
    """Signals cached by triage v1 (fixed reasons, no decisions) keep working after the rubric refactor."""
    path = tmp_path / "signals.jsonl"
    old = {"engine": "llm", "reasons": [{"points": 30, "reason": "Someone has been hurt (read by local AI)",
                                         "hazard": True}], "raw": {"injury_reported": True}}
    path.write_text(json.dumps({"reference": "OLD1", "signals": old}) + "\n")
    monkeypatch.setattr(config, "TRIAGE_SIGNALS_PATH", path)
    t = triage(pothole("went flying"), combine_signals(tl.cached_signals("OLD1")))
    assert t["engine"] == "rules+llm" and t["score"] == 60


def test_model_cannot_override_the_form(ollama):
    """The form says shallow: a model reading 'deep' cannot change it (no points, no hazard)."""
    ollama.reply = model_reply(defect_depth={"option": "road_deep", "p": 0.95})
    s = tl.extract_signals("about 4cm deep", "report_pothole_crack")
    assert s["decisions"]["defect_depth"]["option"] == "road_deep"
    t = explain(pothole("about 4cm deep"), combine_signals(s))
    assert t["priority"] == "P3" and {"node": "defect_depth", "option": "shallow", "p": 1.0, "source": "form"} in t["decisions"]


def test_model_fills_what_the_form_left_open(ollama):
    """No depth on the form: the model's confident 'deep' reading is used, labelled, and can make P1."""
    ollama.reply = model_reply(defect_depth={"option": "road_deep", "p": 0.9})
    item = {"form": "report_pothole_crack", "fields": {"rad_problem_location": "Road Surface"},
            "details": "a hole you could lose a wheel in"}
    t = triage(item, combine_signals(tl.extract_signals(item["details"], item["form"])))
    assert t["priority"] == "P1" and "Road pothole deeper than 40mm (read by local AI)" in t["reasons"]
    assert "Depth not given: needs review" not in t["reasons"]


def test_background_runs_only_when_enabled(ollama, monkeypatch):
    started = []
    monkeypatch.setattr(tl.threading, "Thread", lambda **kw: started.append(kw) or type("T", (), {"start": lambda s: None})())
    tl.enrich_in_background("REF2", "text")
    assert started == []
    monkeypatch.setattr(config, "TRIAGE_LLM", True)
    tl.enrich_in_background("REF2", "text")
    tl.enrich_in_background("REF3", "")
    assert [s["args"] for s in started] == [("REF2", "text", None)]


def _reachable() -> bool:
    try:
        return httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=2).status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _reachable(), reason="OLLAMA_URL not reachable")
def test_live_model_reads_injury():
    s = tl.extract_signals("my mum went flying over the edge of this hole last night and hurt her wrist")
    assert s is not None and s["decisions"]["injury"]["option"] == "yes"
