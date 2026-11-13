"""The LangChain agent (hack_for_impact.agent.llm) with a scripted fake chat model, so no Ollama is needed."""

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app import config
from app.agent import ToolStep
from hack_for_impact.agent import llm


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def call(id_, name, args):
    return {"id": id_, "name": name, "args": args, "type": "tool_call"}


@pytest.fixture(autouse=True)
def reports_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORTS_PATH", tmp_path / "reports.jsonl")


def make_agent(messages, monkeypatch):
    monkeypatch.setattr(llm, "init_chat_model", lambda *a, **k: FakeToolModel(messages=iter(messages)))
    return llm.build_agent()


USER = [{"role": "user", "content": "Pothole on Fargate, 5cm deep"}]


def test_full_flow_streams_tool_steps_then_reply(monkeypatch):
    agent = make_agent([
        AIMessage(content="", tool_calls=[call("1", "route_report", {"problem_type": "pothole", "road_or_place": "Fargate"})]),
        AIMessage(content="", tool_calls=[call("2", "assess_pothole", {"surface": "road", "depth_mm": 50})]),
        AIMessage(content="", tool_calls=[call("3", "file_report", {"surface": "road", "depth_band": "Greater than 40mm",
                                                                    "location": "Fargate", "description": "Deep pothole"})]),
        AIMessage(content="<think>done</think>Filed it."),
    ], monkeypatch)

    events = list(llm.run_agent_events(agent, USER))

    steps = [e for e in events if isinstance(e, ToolStep)]
    assert [s.name for s in steps] == ["route_report", "assess_pothole", "file_report"]
    assert steps[0].result["can_file"] is True
    assert steps[2].result["reference"].startswith("SCC-")
    assert events[-1] == "Filed it."


def test_tool_errors_are_returned_not_raised(monkeypatch):
    agent = make_agent([
        AIMessage(content="", tool_calls=[call("1", "file_report", {"surface": "road", "depth_band": "deep",
                                                                    "location": "Fargate", "description": "x"})]),
        AIMessage(content="How deep is it?"),
    ], monkeypatch)

    events = list(llm.run_agent_events(agent, USER))

    assert "error" in events[0].result
    assert events[-1] == "How deep is it?"


def test_step_limit_gives_fallback_reply(monkeypatch):
    monkeypatch.setattr(config, "MAX_AGENT_STEPS", 2)
    looping = [AIMessage(content="", tool_calls=[call(str(i), "assess_pothole", {"surface": "road", "depth_mm": 1})])
               for i in range(10)]
    agent = make_agent(looping, monkeypatch)

    events = list(llm.run_agent_events(agent, USER))

    assert events[-1] == llm.FALLBACK_REPLY
