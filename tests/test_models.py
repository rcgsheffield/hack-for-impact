"""Model routing (src/app/models.py): tiers from config, per-turn routing, and escalation from the small model."""

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app import config, main, models
from hack_for_impact.agent import llm


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for t in models.TIERS:
        for suffix in ("", "_URL", "_PROVIDER", "_API_KEY", "_API_KEY_ENV"):
            monkeypatch.delenv(f"MODEL_{t.upper()}{suffix}", raising=False)
    monkeypatch.delenv("MODEL_ROUTING", raising=False)
    monkeypatch.setattr(config, "REPORTS_PATH", tmp_path / "reports.jsonl")


def test_every_tier_defaults_to_the_spark():
    s = models.all_specs()
    assert s["small"].model == s["agent"].model == config.OLLAMA_MODEL
    assert not models.thinks("small") and models.thinks("agent")
    assert s["large"].model == "qwen3.6:35b-a3b" and s["vision"].model == config.VISION_MODEL
    assert {s[t].base_url for t in ("small", "agent", "large")} == {config.OLLAMA_URL}
    assert s["vision"].base_url == config.VISION_URL
    assert {x.provider for x in s.values()} == {"ollama"}


def test_a_tier_can_point_at_an_nvidia_endpoint_by_config(monkeypatch):
    monkeypatch.setenv("MODEL_LARGE", "nvidia/nemotron-super")
    monkeypatch.setenv("MODEL_LARGE_PROVIDER", "openai")
    monkeypatch.setenv("MODEL_LARGE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setenv("MODEL_LARGE_API_KEY_ENV", "NVIDIA_API_KEY")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    s = models.spec("large")
    assert (s.model, s.provider, s.api_key, s.where) == (
        "nvidia/nemotron-super", "openai", "nvapi-test", "integrate.api.nvidia.com")
    chat = models.chat_model("large", num_ctx=8192)  # Ollama-only option is dropped
    assert type(chat).__name__ == "ChatOpenAI" and chat.model_name == "nvidia/nemotron-super"
    assert models.spec("small").provider == "ollama"  # other tiers are unaffected


def test_openai_provider_needs_a_url(monkeypatch):
    monkeypatch.setenv("MODEL_SMALL_PROVIDER", "openai")
    with pytest.raises(ValueError, match="MODEL_SMALL_URL"):
        models.spec("small")


@pytest.mark.parametrize(("text", "mode", "kw", "tier"), [
    ("Big pothole outside 10 Fargate, about 5cm deep", "chat", {}, "small"),
    ("A big branch has come off a tree across the pavement", "chat", {}, "small"),
    ("Pothole on Fargate and a street light out on London Road", "chat", {}, "agent"),
    ("x" * 500, "chat", {}, "agent"),
    ("Pothole on Fargate", "form", {}, "agent"),
    ("Pothole on Fargate", "chat", {"escalated": True}, "agent"),
    ("Pothole on Fargate", "chat", {"has_image": True}, "agent"),
])
def test_route_turn(text, mode, kw, tier):
    assert models.route_turn(text, mode, **kw)[0] == tier


def test_routing_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTING", "0")
    assert models.route_turn("Pothole on Fargate")[0] == "agent"


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def test_a_stuck_small_model_hands_the_turn_to_the_agent_tier(monkeypatch):
    monkeypatch.setattr(config, "MAX_AGENT_STEPS", 2)
    loop = [AIMessage(content="", tool_calls=[{"id": str(i), "name": "assess_pothole", "type": "tool_call",
                                               "args": {"surface": "road", "depth_mm": 1}}]) for i in range(10)]
    saver = InMemorySaver()
    agents = {
        "small": llm.build_agent(model=FakeToolModel(messages=iter(loop)), checkpointer=saver),
        "agent": llm.build_agent(model=FakeToolModel(messages=iter([AIMessage(content="Filed it.")] * 3)),
                                 checkpointer=saver),
    }
    monkeypatch.setattr(main, "get_agent", lambda mode="chat", tier="agent": agents[tier])

    shown, thread = list(main.respond("Pothole on Fargate", [], "chat", None, None))[-1]

    titles = [(m.metadata or {}).get("title", "") for m in shown]
    assert titles[0].startswith(f"🧭 {config.OLLAMA_MODEL} (small")
    assert any(t.startswith("↗ Handing over") for t in titles)
    assert shown[-1].content == "Filed it."
    assert llm.FALLBACK_REPLY not in [m.content for m in shown]
    assert thread in main._escalated  # later turns in this conversation skip the small model
