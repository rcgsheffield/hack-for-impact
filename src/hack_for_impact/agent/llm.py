#%%
"""LangChain agent wired to the CouncilTriagent tools (src/app/tools.py). Used by the Gradio app in src/app/main.py."""

import json
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from app import config
from app.agent import FORM_SYSTEM_PROMPT, SYSTEM_PROMPT, ToolStep, clean
from app.pothole_form_toolkit import PotholeFormSession, PotholeFormToolkit
from app.tools import langchain_tools
from app.tree_form_toolkit import TreeFormSession, TreeFormToolkit

OLLAMA_URL = "http://spark12.local:11434"

FALLBACK_REPLY = "Sorry, I couldn't finish that report. Please try again, or phone the council on 0114 273 4567."


class ThreadScopedTools:
    """Tools whose state lives in a per-conversation session, such as a browser tab on a mock council form.

    The agent (and its tool list) is shared by every chat, so each tool looks up the session for the
    run's thread_id and calls the real tool on it. Sessions are created on first use, and the least
    recently used are closed once there are more than max_sessions.
    """

    def __init__(self, make_session: Callable[[], object], make_tools: Callable[[object], list[BaseTool]],
                 max_sessions: int = 8):
        self.make_session, self.make_tools, self.max_sessions = make_session, make_tools, max_sessions
        self._sessions: OrderedDict[str, tuple[object, dict[str, BaseTool]]] = OrderedDict()
        self._lock = threading.Lock()

    def tools_for(self, thread_id: str) -> dict[str, BaseTool]:
        with self._lock:
            if thread_id in self._sessions:
                self._sessions.move_to_end(thread_id)
                return self._sessions[thread_id][1]
            session = self.make_session()
            tools = {t.name: t for t in self.make_tools(session)}
            self._sessions[thread_id] = (session, tools)
            while len(self._sessions) > self.max_sessions:
                _, (old, _) = self._sessions.popitem(last=False)
                try:
                    old.close()
                except Exception:  # A dead browser shouldn't break someone else's chat.
                    pass
            return tools

    def get_tools(self) -> list[BaseTool]:
        # Sessions open their browser lazily, so a template session only costs an idle worker thread.
        return [self._wrap(t) for t in self.make_tools(self.make_session())]

    def _wrap(self, template: BaseTool) -> StructuredTool:
        name = template.name

        def run(config: RunnableConfig, **kwargs) -> str:
            thread_id = (config or {}).get("configurable", {}).get("thread_id") or "default"
            return self.tools_for(thread_id)[name].invoke(kwargs)

        return StructuredTool.from_function(func=run, name=name, description=template.description,
                                            args_schema=template.args_schema,
                                            handle_validation_error=template.handle_validation_error)


def tree_form_tools(max_sessions: int = 8) -> list[BaseTool]:
    """The tree form tools (src/app/tree_form_toolkit.py), with one browser session per chat thread."""
    return ThreadScopedTools(TreeFormSession, lambda s: TreeFormToolkit(session=s).get_tools(), max_sessions).get_tools()


def pothole_form_tools(max_sessions: int = 8) -> list[BaseTool]:
    """The pothole form tools (src/app/pothole_form_toolkit.py), with one browser session per chat thread."""
    return ThreadScopedTools(PotholeFormSession, lambda s: PotholeFormToolkit(session=s).get_tools(),
                             max_sessions).get_tools()


# The two branches. "chat": the agent files reports itself with local tools (data/reports.jsonl).
# "form": the agent fills in the mock council web forms in a browser, page by page (shown on /dashboard).
MODES = ("chat", "form")


def mode_tools(mode: str) -> list[BaseTool]:
    if mode == "chat":
        return langchain_tools(["route_report", "convert_to_mm", "nearest_address", "assess_pothole", "file_report",
                                "assess_tree", "file_tree_report"])
    if mode == "form":
        return (langchain_tools(["route_report", "convert_to_mm", "nearest_address"])
                + pothole_form_tools() + tree_form_tools())
    raise ValueError(f"mode must be one of {MODES}")


def build_agent(model_name: str = "gemma4:e2b", model_provider: str = "ollama", base_url: str = OLLAMA_URL,
                api_key: str = "not-needed", mode: str = "chat", tools: list | None = None,
                system_prompt: str | None = None, checkpointer: BaseCheckpointSaver | None = None):
    """
    Build a LangChain agent for one branch (see MODES):
    - mode="chat": route_report, convert_to_mm, assess_pothole/file_report and assess_tree/file_tree_report.
    - mode="form": route_report, convert_to_mm, and the pothole and tree web form tools (one browser tab per thread).
    Pass `tools` or `system_prompt` to override the mode's defaults.

    Each agent gets its own in-memory checkpointer unless one is passed, so conversations are threads:
    invoke/stream with config=thread_config(thread_id) and send only the new message.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    model = init_chat_model(
        model_name,
        model_provider=model_provider,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
    )

    agent = create_agent(
        model=model,
        tools=mode_tools(mode) if tools is None else tools,
        system_prompt=system_prompt or (SYSTEM_PROMPT if mode == "chat" else FORM_SYSTEM_PROMPT),
        checkpointer=checkpointer or InMemorySaver(),
    )
    return agent


def new_thread_id() -> str:
    return str(uuid.uuid4())


def thread_config(thread_id: str, max_steps: int | None = None) -> dict:
    # Each model call + tool round is two graph steps.
    return {"configurable": {"thread_id": thread_id},
            "recursion_limit": 2 * (max_steps or config.MAX_AGENT_STEPS) + 1}


def user_turns(agent, thread_id: str) -> int:
    """How many user messages the agent has stored for this thread (0 for a new thread)."""
    state = agent.get_state({"configurable": {"thread_id": thread_id}})
    return sum(isinstance(m, HumanMessage) for m in state.values.get("messages", []))


def run_agent_events(agent, messages: list[dict], thread_id: str | None = None,
                     max_steps: int | None = None) -> Iterator[ToolStep | str]:
    """Run one user turn. Yields a ToolStep for each tool call, then the final reply as a str.

    Same contract as app.agent.run_agent_events, so the frontend can show each tool call as it happens.
    `messages` are {"role": "user"|"assistant", "content": str} dicts to add to the thread, ending with the
    user's message. With a thread_id, earlier turns (including tool calls and results) come from the checkpointer,
    so pass only the new message. Without one, a fresh thread is used.
    `max_steps` caps model calls for this turn (default config.MAX_AGENT_STEPS); the browser agent needs more.
    """
    calls: dict[str, dict] = {}  # tool_call_id -> {"name", "args"} from the model's request
    reply = ""
    run_config = thread_config(thread_id or new_thread_id(), max_steps)
    try:
        for update in agent.stream({"messages": messages}, config=run_config, stream_mode="updates"):
            for node_update in update.values():
                for msg in (node_update or {}).get("messages", []):
                    if isinstance(msg, AIMessage):
                        for call in msg.tool_calls:
                            calls[call["id"]] = call
                        if not msg.tool_calls:
                            reply = clean(str(msg.text))
                    elif isinstance(msg, ToolMessage):
                        call = calls.get(msg.tool_call_id, {})
                        try:
                            result = json.loads(msg.content)
                        except (TypeError, ValueError):
                            result = {"output": msg.content}
                        yield ToolStep(call.get("name", msg.name or "tool"), json.dumps(call.get("args", {})), result)
    except GraphRecursionError:
        yield FALLBACK_REPLY
        return
    yield reply or "Sorry, I didn't catch that. Could you describe the problem and where it is?"
# %%
