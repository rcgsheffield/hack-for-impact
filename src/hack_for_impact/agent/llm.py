#%%
"""LangChain agent wired to the CouncilTriagent tools (src/app/tools.py). Used by the Gradio app in src/app/main.py."""

import json
from collections.abc import Iterator

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from app import config
from app.agent import SYSTEM_PROMPT, ToolStep, clean
from app.tools import langchain_tools

OLLAMA_URL = "http://spark12.local:11434"

FALLBACK_REPLY = "Sorry, I couldn't finish that report. Please try again, or phone the council on 0114 273 4567."


def build_agent(model_name: str = "gemma4:e2b", model_provider: str = "ollama", base_url: str = OLLAMA_URL,
                api_key: str = "not-needed", tools: list | None = None, system_prompt: str = SYSTEM_PROMPT):
    """
    Build a LangChain agent with the council reporting tools (route_report, assess_pothole, file_report).
    Pass `tools` to override them, e.g. PotholeFormToolkit(...).get_tools() to drive the mock form instead.
    """
    model = init_chat_model(
        model_name,
        model_provider=model_provider,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
    )

    agent = create_agent(
        model=model,
        tools=langchain_tools() if tools is None else tools,
        system_prompt=system_prompt,
    )
    return agent


def run_agent_events(agent, history: list[dict]) -> Iterator[ToolStep | str]:
    """Run one user turn. Yields a ToolStep for each tool call, then the final reply as a str.

    Same contract as app.agent.run_agent_events, so the frontend can show each tool call as it happens.
    `history` is a list of {"role": "user"|"assistant", "content": str} ending with the user's message.
    """
    calls: dict[str, dict] = {}  # tool_call_id -> {"name", "args"} from the model's request
    reply = ""
    # Each model call + tool round is two graph steps.
    run_config = {"recursion_limit": 2 * config.MAX_AGENT_STEPS + 1}
    try:
        for update in agent.stream({"messages": history}, config=run_config, stream_mode="updates"):
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
