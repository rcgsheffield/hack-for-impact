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


def test_thread_remembers_earlier_turns_including_tool_results(monkeypatch):
    agent = make_agent([
        AIMessage(content="", tool_calls=[call("1", "assess_pothole", {"surface": "road", "depth_mm": 50})]),
        AIMessage(content="Where is it?"),
        AIMessage(content="Thanks."),
    ], monkeypatch)
    thread = llm.new_thread_id()

    list(llm.run_agent_events(agent, USER, thread))
    list(llm.run_agent_events(agent, [{"role": "user", "content": "Fargate"}], thread))

    stored = agent.get_state({"configurable": {"thread_id": thread}}).values["messages"]
    assert [type(m).__name__ for m in stored] == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage",
                                                  "HumanMessage", "AIMessage"]
    assert llm.user_turns(agent, thread) == 2
    assert llm.user_turns(agent, llm.new_thread_id()) == 0


def test_frontend_keeps_one_thread_per_chat_and_resets_on_mismatch(monkeypatch):
    from app import main

    agent = make_agent([AIMessage(content=f"reply {i}") for i in range(4)], monkeypatch)
    monkeypatch.setattr(main, "get_agent", lambda mode="chat": agent)

    def turn(message, history, thread_id):
        shown, thread_id = list(main.respond(message, history, "chat", None, thread_id))[-1]
        return shown[-1].content, thread_id

    reply, thread = turn("hello", [], None)
    assert reply == "reply 0" and thread
    history = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": reply}]

    _, same = turn("Fargate", history, thread)
    assert same == thread and llm.user_turns(agent, thread) == 2

    # A cleared chat (or a retry/undo) no longer matches the stored thread, so a new one starts.
    _, fresh = turn("new problem", [], thread)
    assert fresh != thread and llm.user_turns(agent, fresh) == 1


class FakeSession:
    def __init__(self):
        self.calls, self.closed = 0, False

    def close(self):
        self.closed = True


def counter_tools(session):
    from langchain_core.tools import StructuredTool

    def bump() -> str:
        session.calls += 1
        return str(session.calls)
    return [StructuredTool.from_function(func=bump, name="bump", description="Count calls in this session")]


def test_thread_scoped_tools_keep_one_session_per_thread_and_close_the_oldest():
    scoped = llm.ThreadScopedTools(FakeSession, counter_tools, max_sessions=2)
    (bump,) = scoped.get_tools()
    on = lambda t: {"configurable": {"thread_id": t}}  # noqa: E731

    assert [bump.invoke({}, config=on("a")), bump.invoke({}, config=on("a")), bump.invoke({}, config=on("b"))] == ["1", "2", "1"]
    first = scoped._sessions["a"][0]
    bump.invoke({}, config=on("c"))  # a is least recently used, so it is closed

    assert first.closed and list(scoped._sessions) == ["b", "c"]


def test_agent_has_tree_form_tools():
    names = {t.name for t in llm.tree_form_tools()}
    assert {"start_tree_form", "set_tree_problem", "submit_tree_form"} <= names


def test_each_mode_has_its_own_branch_of_tools():
    chat = {t.name for t in llm.mode_tools("chat")}
    form = {t.name for t in llm.mode_tools("form")}
    assert {"file_report", "assess_tree", "file_tree_report"} <= chat
    assert not any(n.startswith(("start_", "submit_")) for n in chat)
    assert {"start_pothole_form", "submit_pothole_form", "start_tree_form", "submit_tree_form"} <= form
    assert not {"file_report", "file_tree_report"} & form
    assert {"route_report", "convert_to_mm"} <= chat & form


def test_chat_mode_files_a_tree_report(monkeypatch):
    agent = make_agent([
        AIMessage(content="", tool_calls=[call("1", "assess_tree", {"tree_location": "Highway", "problem": "Fallen", "blocking": True})]),
        AIMessage(content="", tool_calls=[call("2", "file_tree_report", {
            "tree_location": "Highway", "problem": "Fallen", "blocking": True,
            "location": "12 Derbyshire Lane", "description": "Branch across the pavement"})]),
        AIMessage(content="Filed."),
    ], monkeypatch)

    events = list(llm.run_agent_events(agent, [{"role": "user", "content": "Branch down on Derbyshire Lane"}]))

    assert events[0].result["urgent_advice"]
    assert events[1].result["reference"].startswith("SCC-")


def test_shared_location_goes_to_the_model_not_the_chat(monkeypatch):
    from app import main

    assert "lat 53.381100, lon -1.470100, accuracy about 12 m" in main.location_note("53.381100, -1.470100 (±12 m)")
    pinned = main.location_note("53.381411, -1.469543 (map pin)")
    assert "dropped a pin on the map where the problem is: lat 53.381411, lon -1.469543" in pinned
    assert "Use it only if they are at the problem now" not in pinned
    assert main.location_note("Not available: permission denied") == ""
    assert main.location_note(None) == ""

    agent = make_agent([AIMessage(content="ok")], monkeypatch)
    monkeypatch.setattr(main, "get_agent", lambda mode="chat": agent)
    _, thread = list(main.respond("pothole right here", [], "chat", "53.38, -1.47 (±9 m)", None))[-1]

    sent = agent.get_state({"configurable": {"thread_id": thread}}).values["messages"][0].content
    assert sent.startswith("pothole right here") and "[Device location shared by the user: lat 53.38, lon -1.47" in sent


def test_location_panel_title_shows_whether_a_location_is_set():
    from app import main

    assert main.location_label("") == "📍 Add a location (optional)"
    assert main.location_label("53.38, -1.47 (map pin)") == "📍 Location: pin on the map ✓"
    assert main.location_label("53.38, -1.47 (±9 m)") == "📍 Location: your current location ✓"
