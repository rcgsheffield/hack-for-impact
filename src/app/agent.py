"""The agent loop: an OpenAI-compatible chat model plus tool calls, running on local Ollama.

Ollama serves the same /v1 API as NVIDIA NIM, so swapping to a NIM endpoint only means changing OLLAMA_URL.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from openai import OpenAI

from . import config
from .tools import SCHEMAS, call_tool

SYSTEM_PROMPT = f"""You are CouncilTriagent, a helpful assistant for Sheffield residents reporting problems with roads and pavements.

How to work:
1. Find out what the problem is and exactly where it is. If the location or (for potholes) a rough depth is missing, ask ONE short question that covers what's missing.
2. Call route_report to find who is responsible. If can_file is false, tell the user who to contact and how, then stop.
3. For potholes and surface defects, call assess_pothole with the surface (road or pavement) and depth in millimetres.
4. Call file_report with the depth_band from assess_pothole, the location and a short description.
5. Reply in plain English: the reference number, who will deal with it, and the suggested priority with what it means.

Rules:
- Never invent a reference number; only quote one returned by file_report.
- If a tool returns an error, fix the arguments or ask the user, then try again.
- If someone is in immediate danger, tell them to call 999. For urgent road hazards, they should phone the council on 0114 273 4567.
- Keep replies short and friendly. Use British English.
- This is a hackathon prototype: reports are recorded locally and not sent to the council. Say so when you give a reference.
"""

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass
class ToolStep:
    name: str
    arguments: str
    result: dict


@dataclass
class AgentResult:
    reply: str
    steps: list[ToolStep] = field(default_factory=list)


def make_client() -> OpenAI:
    # Ollama ignores the key, but the SDK requires one.
    return OpenAI(base_url=f"{config.OLLAMA_URL}/v1", api_key="ollama", timeout=config.LLM_TIMEOUT)


def clean(text: str | None) -> str:
    """Drop any reasoning block a thinking model leaves in its content."""
    return THINK_RE.sub("", text or "").strip()


def run_agent_events(history: list[dict], client: OpenAI | None = None, model: str | None = None) -> Iterator[ToolStep | str]:
    """Run one user turn. Yields a ToolStep for each tool call, then the final reply as a str.

    `history` is a list of {"role": "user"|"assistant", "content": str} ending with the user's message.
    """
    client = client or make_client()
    model = model or config.OLLAMA_MODEL
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]

    for _ in range(config.MAX_AGENT_STEPS):
        response = client.chat.completions.create(model=model, messages=messages, tools=SCHEMAS)
        msg = response.choices[0].message

        if not msg.tool_calls:
            yield clean(msg.content) or "Sorry, I didn't catch that. Could you describe the problem and where it is?"
            return

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in msg.tool_calls
            ],
        })
        for call in msg.tool_calls:
            result = call_tool(call.function.name, call.function.arguments)
            yield ToolStep(call.function.name, call.function.arguments, result)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})

    yield "Sorry, I couldn't finish that report. Please try again, or phone the council on 0114 273 4567."


def run_agent(history: list[dict], client: OpenAI | None = None, model: str | None = None) -> AgentResult:
    """Run one user turn and collect the reply and the tool steps."""
    result = AgentResult(reply="")
    for event in run_agent_events(history, client, model):
        if isinstance(event, ToolStep):
            result.steps.append(event)
        else:
            result.reply = event
    return result
