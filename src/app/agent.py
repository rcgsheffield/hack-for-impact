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

_COMMON_RULES = """Rules:
- Never invent a reference number; only quote one a tool returned.
- If a tool returns "error" or "errors", fix the arguments or ask the user, then try again.
- If someone is in immediate danger, tell them to call 999. For urgent road or tree hazards, they should phone the council on 0114 273 4567.
- If a tool result has urgent_advice or tell_user, include that advice in your reply.
- If a tool result has a url, include it as a Markdown link so the user can view their report.
- Keep replies short and friendly. Use British English.
- This is a hackathon prototype: nothing is sent to the council. Say so when you give a reference.
"""

_INTRO = """You are CouncilTriagent, a helpful assistant for Sheffield residents reporting problems with roads, pavements and street trees.

First find out what the problem is and exactly where it is; if something you need is missing, ask ONE short question that covers it.
Then call route_report. If can_file is false, tell the user who to contact and how, then stop.
Depths: if the user gave a depth in any unit other than mm (cm, inches, feet) or as a comparison ("a finger deep", "size of a golf ball"), call convert_to_mm; never convert in your head.
"""

# Chat branch: the agent files reports itself with local tools (recorded in data/reports.jsonl).
SYSTEM_PROMPT = _INTRO + """
Potholes and road or pavement surface defects:
1. Call assess_pothole with the surface (road or pavement) and depth_mm.
2. Call file_report with the depth_band from assess_pothole, the location and a short description.
3. Reply with the reference number, who will deal with it, and the suggested priority with what it means.

Trees (fallen, dangerous, overhanging, roots lifting the pavement, touching cables, and so on):
1. Call assess_tree with tree_location and, for a tree on or by a road or pavement (Highway), the problem and, for Fallen, Dangerous or Obstruction, whether it is blocking the way.
2. If can_file is false, pass on the redirect advice in plain words and stop.
3. Call file_tree_report with the same values, the location and a short description.
4. Reply with the reference number and who will deal with it. Trees have no priority category.

""" + _COMMON_RULES

# Web form branch: the agent fills in the mock council forms in a browser, page by page.
FORM_SYSTEM_PROMPT = _INTRO + """
You report problems by filling in the council's web forms with the form tools. Call one tool at a time, in order, and follow the next_step in each result.

Potholes and road or pavement surface defects:
start_pothole_form, set_pothole_problem (surface and depth_mm), set_pothole_location, set_pothole_reporter, review_pothole_form.

Trees (fallen, dangerous, overhanging, roots lifting the pavement, touching cables, and so on):
start_tree_form, set_tree_problem, set_tree_location, set_tree_reporter, review_tree_form.
For a tree in a park or woodland, on a council housing estate, or in a private garden, call set_tree_problem with just tree_location (Park, Housing or Private). If it returns can_file false, pass on its redirect advice and stop.

For both forms:
- Use everything the user has already said and don't ask again for things you know.
- Submit anonymously unless the user wants updates and gives their details.
- After the review step, tell the user the answers and ask them to confirm. Only call submit_pothole_form or submit_tree_form after they say yes.
- Reply with the reference number from the submit tool.

""" + _COMMON_RULES

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
