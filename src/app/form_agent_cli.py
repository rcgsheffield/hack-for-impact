"""Chat with a form agent (LangChain + local Ollama) in the terminal, and watch it fill in the mock form.

    uv run python -m app.form_agent_cli pothole --headed
    uv run python -m app.form_agent_cli tree -m "A tree has fallen across the pavement on Derbyshire Lane"
    uv run python -m app.form_agent_cli browser --headed     # general browser agent, any of the mock forms

The browser agent (browser_agent.py) opens the forms at BROWSER_FORMS_URL, the running app's /mock/ by default.
Model and server come from OLLAMA_MODEL and OLLAMA_URL (see config.py), or --model.
Each tool call and its result is printed, so you can see what the agent did.
"""

from __future__ import annotations

import argparse
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from . import config
from .browser_agent import BrowserSession, make_browser_agent
from .council_form import unverified_references
from .pothole_form_toolkit import PotholeFormSession
from .pothole_form_toolkit import make_form_agent as make_pothole_agent
from .tree_form_toolkit import TreeFormSession
from .tree_form_toolkit import make_form_agent as make_tree_agent

FORMS = {"pothole": (PotholeFormSession, make_pothole_agent), "tree": (TreeFormSession, make_tree_agent),
         "browser": (BrowserSession, make_browser_agent)}


def _short(text: str, limit: int = 400) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def chat_turn(agent, messages: list, user_text: str) -> list:
    """Send one user message, print the tool calls and the reply, and return the updated message list."""
    messages = messages + [HumanMessage(user_text)]
    try:
        return _stream_turn(agent, messages)
    except GraphRecursionError:  # The step limit (MAX_AGENT_STEPS / BROWSER_MAX_AGENT_STEPS) stopped a looping model.
        print("\nAgent: (stopped: too many steps for one message)\n", flush=True)
        return messages


def _stream_turn(agent, messages: list) -> list:
    seen = len(messages)
    for update in agent.stream({"messages": messages}, stream_mode="values"):
        new = update["messages"][seen:]
        seen = len(update["messages"])
        for m in new:
            if isinstance(m, AIMessage):
                for call in m.tool_calls:
                    print(f"  🔧 {call['name']}({json.dumps(call['args'])})", flush=True)
                if m.content and not m.tool_calls:
                    print(f"\nAgent: {m.content}\n", flush=True)
                    tool_results = [str(t.content) for t in messages if isinstance(t, ToolMessage)]
                    tool_results += [str(t.content) for t in update["messages"] if isinstance(t, ToolMessage)]
                    fake = unverified_references(str(m.content), tool_results)
                    if fake:
                        print(f"  ⚠️ GUARD: reference {', '.join(fake)} was not returned by any submit tool "
                              "(made up by the model; nothing was submitted).\n", flush=True)
            elif isinstance(m, ToolMessage):
                print(f"     -> {_short(str(m.content))}", flush=True)
        messages = update["messages"]
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("form", choices=FORMS)
    parser.add_argument("--model", default=None, help=f"Ollama model (default: {config.OLLAMA_MODEL})")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--slow-mo", type=int, default=0, metavar="MS")
    parser.add_argument("--think", action="store_true", help="let a reasoning model think (slower)")
    parser.add_argument("--num-ctx", type=int, default=None,
                        help=f"model context window in tokens (default 16384; {config.BROWSER_NUM_CTX} for browser)")
    parser.add_argument("-m", "--message", action="append", help="send this message instead of prompting (repeatable)")
    args = parser.parse_args()

    session_cls, make = FORMS[args.form]
    session = session_cls(headless=not args.headed, slow_mo_ms=args.slow_mo)
    # Ollama's default 4096-token context truncates the tool schemas plus a few form steps; 16k fits a whole report.
    # The browser agent gets a whole page back from every action, so it needs much more.
    num_ctx = args.num_ctx or (config.BROWSER_NUM_CTX if args.form == "browser" else 16384)
    agent, session = make(session=session, model=args.model, reasoning=args.think, num_ctx=num_ctx)
    print(f"{args.form} form agent on {args.model or config.OLLAMA_MODEL} at {config.OLLAMA_URL}. Ctrl+C to quit.\n")

    messages: list = []
    try:
        if args.message:
            for text in args.message:
                print(f"You: {text}")
                messages = chat_turn(agent, messages, text)
        else:
            while True:
                text = input("You: ").strip()
                if text:
                    messages = chat_turn(agent, messages, text)
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        session.close()


if __name__ == "__main__":
    main()
