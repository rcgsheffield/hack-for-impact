"""System One (Jev) decider (src/app/triage_jev.py): request shape, redaction, parsing, failures. No live calls."""

import httpx
import pytest

from app import config
from app import triage_jev as jev
from app import triage_llm as tl
from app.triage import combine_signals, triage
from app.triage_rubric import GENERIC, POTHOLE


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=httpx.Request("POST", "http://x"), response=None)

    def json(self):
        return self.body


@pytest.fixture
def api(monkeypatch):
    class Fake:
        reply: object = {"model": "jev-1", "answers": {}, "usage": {"input_tokens": 1, "output_tokens": 1}}
        calls = []

    def post(url, json=None, headers=None, timeout=None):
        Fake.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if isinstance(Fake.reply, BaseException):
            raise Fake.reply
        return FakeResponse(Fake.reply)

    monkeypatch.setattr(jev.httpx, "post", post)
    monkeypatch.setattr(config, "JEV_API_KEY", "test-key")
    monkeypatch.setattr(config, "TRIAGE_DECIDER", "jev")
    Fake.calls = []
    return Fake


def choice(option, probs):
    return {"type": "choice", "choice": option, "confidence": max(probs.values()), "probabilities": probs}


def test_request_follows_the_system_one_schema(api):
    tl.extract_signals("Deep hole, call me on 07700 900123 or a@b.com, S1 2SH", "report_pothole_crack")
    call = api.calls[0]
    assert call["url"] == f"{config.JEV_URL}/v1/systemone" and call["headers"]["Authorization"] == "Bearer test-key"
    assert call["timeout"] == config.JEV_TIMEOUT
    body = call["json"]
    assert body["model"] == config.JEV_MODEL
    assert set(body["questions"]) == {n.id for n in POTHOLE.model_nodes()}
    q = body["questions"]["defect_depth"]
    assert q["type"] == "choice" and set(q["criteria"]) == set(POTHOLE.node("defect_depth").options)
    assert body["state"]["report"] == "Deep hole, call me on [phone] or [email], [postcode]"


def test_probabilities_become_decisions(api):
    api.reply = {"model": "jev-1", "usage": {}, "answers": {
        "injury": choice("yes", {"none": 0.1, "yes": 0.9}),
        "blocking": choice("none", {"none": 0.97, "yes": 0.03}),       # default, no hazard weight: dropped
    }}
    s = tl.extract_signals("a man went flying over his handlebars here")
    assert s["engine"] == "jev" and set(s["decisions"]) == {"injury"}
    assert s["decisions"]["injury"]["p"] == 0.9 and s["decisions"]["injury"]["probs"]["none"] == 0.1
    item = {"form": "report_pothole_crack", "details": "a man went flying over his handlebars here",
            "fields": {"rad_problem_location": "Road Surface", "rad_road_pothole_depth": "Less than 40mm"}}
    t = triage(item, combine_signals(s))
    assert t["engine"] == "rules+jev" and "Someone has been hurt (read by Jev)" in t["reasons"]


def test_unknown_options_are_ignored(api):
    api.reply = {"model": "jev-1", "usage": {}, "answers": {"injury": choice("P1", {"P1": 1.0})}}
    assert tl.extract_signals("x") is None


@pytest.mark.parametrize("reply", [httpx.ReadTimeout("slow"), httpx.ConnectError("down"), {"answers": "nope"}])
def test_failures_fall_back_to_rules(api, reply):
    api.reply = reply
    assert tl.extract_signals("someone went flying") is None


def test_no_key_makes_no_call(api, monkeypatch):
    monkeypatch.setattr(config, "JEV_API_KEY", "")
    assert jev.extract_signals("someone went flying", GENERIC) is None and api.calls == []


def test_ollama_is_the_default():
    assert config.TRIAGE_DECIDER == "ollama"
