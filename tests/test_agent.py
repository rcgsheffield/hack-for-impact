"""Agent loop tests with a fake OpenAI client, so no model is needed."""

from types import SimpleNamespace

import pytest

from app import agent, config


def tool_call(id_, name, arguments):
    return SimpleNamespace(id=id_, type="function", function=SimpleNamespace(name=name, arguments=arguments))


def message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


class FakeClient:
    """Returns the scripted messages in order and records what it was sent."""

    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        msg = self.scripted.pop(0) if self.scripted else self.default
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    default = message(tool_calls=[tool_call("x", "assess_pothole", '{"surface": "road", "depth_mm": 1}')])


@pytest.fixture(autouse=True)
def reports_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORTS_PATH", tmp_path / "reports.jsonl")


USER = [{"role": "user", "content": "Pothole on Fargate, 5cm deep"}]


def test_full_flow_routes_assesses_files_then_replies():
    client = FakeClient([
        message(tool_calls=[tool_call("1", "route_report", '{"problem_type": "pothole", "road_or_place": "Fargate"}')]),
        message(tool_calls=[tool_call("2", "assess_pothole", '{"surface": "road", "depth_mm": 50}')]),
        message(tool_calls=[tool_call("3", "file_report",
                                      '{"surface": "road", "depth_band": "Greater than 40mm", "location": "Fargate", "description": "Deep pothole"}')]),
        message(content="<think>done</think>Filed it."),
    ])
    result = agent.run_agent(USER, client=client, model="test")

    assert [s.name for s in result.steps] == ["route_report", "assess_pothole", "file_report"]
    assert result.steps[2].result["reference"].startswith("SCC-")
    assert result.reply == "Filed it."
    # The model saw each tool result, matched to its call id.
    last_messages = client.calls[-1]["messages"]
    assert [m["tool_call_id"] for m in last_messages if m["role"] == "tool"] == ["1", "2", "3"]


def test_bad_arguments_go_back_to_the_model_as_an_error():
    client = FakeClient([
        message(tool_calls=[tool_call("1", "assess_pothole", "{oops")]),
        message(content="Sorry, how deep is it?"),
    ])
    result = agent.run_agent(USER, client=client, model="test")
    assert "error" in result.steps[0].result
    assert result.reply == "Sorry, how deep is it?"


def test_step_cap_stops_a_looping_model(monkeypatch):
    monkeypatch.setattr(config, "MAX_AGENT_STEPS", 3)
    client = FakeClient([])  # Always returns a tool call.
    result = agent.run_agent(USER, client=client, model="test")
    assert len(client.calls) == 3
    assert "couldn't finish" in result.reply


def test_empty_reply_gets_a_fallback():
    result = agent.run_agent(USER, client=FakeClient([message(content="<think>hmm</think>")]), model="test")
    assert result.reply.startswith("Sorry")
