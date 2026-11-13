"""Model routing: which model does each job, and where it runs.

Four tiers. Every one runs on the Spark's Ollama by default, and each can be pointed somewhere else by config alone
(an NVIDIA NIM, build.nvidia.com, vLLM, another machine):

    small   fast text jobs: triage signals from report text, text-only chat turns   (default OLLAMA_MODEL, no thinking)
    agent   tool-calling chat that files reports; escalation target for small       (default OLLAMA_MODEL)
    large   the general browser agent, which reads whole web pages                  (default qwen3.6:35b-a3b)
    vision  photos of the problem (photos.py)                                       (default VISION_MODEL / VISION_URL)

Per tier, all optional (TIER is SMALL, AGENT, LARGE or VISION):
    MODEL_<TIER>           model name
    MODEL_<TIER>_URL       server; default OLLAMA_URL. For "openai" use the /v1 base, e.g. http://spark12.local:8000/v1
    MODEL_<TIER>_PROVIDER  "ollama" (default) or "openai" for any OpenAI-compatible server (NIM, build.nvidia.com, vLLM)
    MODEL_<TIER>_API_KEY   key for that server; or MODEL_<TIER>_API_KEY_ENV naming the variable holding it
                           (e.g. NVIDIA_API_KEY), so keys never sit in config files.
    MODEL_<TIER>_THINK      1/0: let the model reason before answering (Ollama); default off for small, on otherwise
MODEL_ROUTING=0 switches routing off: every chat turn uses the agent tier, as before routing existed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from . import config

TIERS = ("small", "agent", "large", "vision")
DEFAULT_MODELS = {
    # Same model as agent but without "thinking". Measured on the Spark (13 Nov): a text-only report filed in 6-8 s
    # and 4 tool calls this way, vs ~30 s with thinking and 41-60 s / 17 calls on nemotron-3-nano:30b.
    "small": None,
    "agent": None,  # config.OLLAMA_MODEL, so existing OLLAMA_MODEL settings keep working
    "large": "qwen3.6:35b-a3b",
    "vision": None,  # config.VISION_MODEL (photos.py), so the existing VISION_MODEL setting keeps working
}
TIER_LABELS = {"small": "small, fast", "agent": "tool-calling", "large": "large", "vision": "vision"}

# A chat message longer than this, or naming more than one problem, goes to the agent tier rather than small.
LONG_MESSAGE_CHARS = 400
# Kinds of problem, so "a branch off a tree on the pavement" counts as one problem, not three.
PROBLEM_KINDS = {
    "road or pavement defect": re.compile(r"\b(pot ?holes?|cracks?|cracked|sunken|uneven (slab|paving)s?)\b", re.I),
    "tree": re.compile(r"\b(trees?|branch(es)?|roots?)\b", re.I),
    "street light": re.compile(r"\bstreet ?lights?|lamp ?posts?\b", re.I),
    "fly-tipping": re.compile(r"\bfly.?tip", re.I),
    "drain": re.compile(r"\b(drains?|gull(e|y|ies)|flood)", re.I),
}


@dataclass(frozen=True)
class ModelSpec:
    tier: str
    model: str
    base_url: str
    provider: str  # "ollama" | "openai"
    api_key: str

    @property
    def where(self) -> str:
        """Where it runs, for people: "DGX Spark (Ollama)", "build.nvidia.com", or the host name."""
        host = urlparse(self.base_url).hostname or self.base_url
        if "nvidia.com" in host:
            return host
        if host.startswith("spark") or host in ("127.0.0.1", "localhost"):
            return f"DGX Spark ({'Ollama' if self.provider == 'ollama' else 'NIM / OpenAI-compatible'})"
        return host


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def spec(tier: str) -> ModelSpec:
    """The configured model for a tier. Read from the environment on every call, so tests and ops can change it."""
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}")
    T = tier.upper()
    default_model = config.VISION_MODEL if tier == "vision" else config.OLLAMA_MODEL
    model = _env(f"MODEL_{T}") or DEFAULT_MODELS[tier] or default_model
    provider = (_env(f"MODEL_{T}_PROVIDER") or "ollama").lower()
    default_url = config.VISION_URL if tier == "vision" else config.OLLAMA_URL
    base_url = (_env(f"MODEL_{T}_URL") or (default_url if provider == "ollama" else "")).rstrip("/")
    if provider not in ("ollama", "openai"):
        raise ValueError(f"MODEL_{T}_PROVIDER must be 'ollama' or 'openai'")
    if provider == "openai" and not base_url:
        raise ValueError(f"MODEL_{T}_URL is required when MODEL_{T}_PROVIDER=openai")
    key_env = _env(f"MODEL_{T}_API_KEY_ENV")
    api_key = _env(f"MODEL_{T}_API_KEY") or (_env(key_env) if key_env else "") or "not-needed"
    return ModelSpec(tier, model, base_url, provider, api_key)


def all_specs() -> dict[str, ModelSpec]:
    return {t: spec(t) for t in TIERS}


def chat_model(tier: str, model: str | None = None, **kwargs):
    """A LangChain chat model for a tier. `model` overrides just the name (e.g. a CLI --model flag).

    kwargs are provider options, e.g. num_ctx or reasoning for Ollama; Ollama-only options are dropped for "openai".
    """
    s = spec(tier)
    name = model or s.model
    if s.provider == "ollama":
        from langchain_ollama import ChatOllama

        # Fast tiers skip "thinking": measured on the Spark it is most of a small model's time per step.
        kwargs.setdefault("reasoning", thinks(tier))

        return ChatOllama(model=name, base_url=s.base_url, temperature=0, **kwargs)
    from langchain_openai import ChatOpenAI

    kwargs = {k: v for k, v in kwargs.items() if k not in ("num_ctx", "reasoning")}
    return ChatOpenAI(model=name, base_url=s.base_url, api_key=s.api_key, temperature=0,
                      timeout=config.LLM_TIMEOUT, **kwargs)


def thinks(tier: str) -> bool:
    """Whether a tier's model should reason before answering. MODEL_<TIER>_THINK=1/0 overrides; small is off."""
    value = _env(f"MODEL_{tier.upper()}_THINK")
    return value.lower() not in ("0", "false", "no", "off") if value else tier != "small"


def routing_enabled() -> bool:
    return (_env("MODEL_ROUTING") or "1").lower() not in ("0", "false", "no", "off")


def route_turn(text: str, mode: str = "chat", has_image: bool = False, escalated: bool = False) -> tuple[str, str]:
    """Pick the tier for one chat turn. Returns (tier, reason in plain English).

    Rules, cheapest first: a photo needs vision; the web-form mode drives a browser through several tool calls, so it
    gets the agent tier; a conversation that already needed the bigger model stays there; a long or multi-problem
    message goes to the agent tier; anything else is a text-only report and the small model handles it.
    """
    if not routing_enabled():
        return "agent", "routing is off (MODEL_ROUTING=0)"
    if has_image:
        # The vision tier describes the photo first (photos.py); the chat model then gets that description as text.
        return "agent", "the message has a photo to take into account"
    if mode == "form":
        return "agent", "web-form mode fills in a form in a browser, which takes several tool calls"
    if escalated:
        return "agent", "the small model needed help earlier in this conversation"
    kinds = [k for k, pattern in PROBLEM_KINDS.items() if pattern.search(text or "")]
    if len(text or "") > LONG_MESSAGE_CHARS or len(kinds) > 1:
        return "agent", "a long message or more than one problem"
    return "small", "a text-only report"
