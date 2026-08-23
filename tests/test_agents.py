"""The one agent composition: every feature present, every run — there are no modes to pick."""

import pytest
from conftest import needs_engine

from arcade.agent import create_agent
from arcade.instructions import KERNEL_SETUP
from arcade.models import MeteredResponses, get_model
from arcade.tools import ArcadeTools

pytestmark = needs_engine


@pytest.fixture(scope="module")
def game():
    return ArcadeTools("tr87")


def names(agent):
    return [type(t).__name__ for t in agent.tools]


def test_full_composition(game):
    agent = create_agent(game)
    assert names(agent) == ["ArcadeTools", "CodeMode"]
    assert agent.learning is not None
    assert "save_learning" in str(agent.instructions)  # the knowledge loop is always on
    assert agent.offload_tool_results is True


def test_kernel_setup_carries_helpers():
    for helper in ("def grids", "def trace", "def diff", "def segments"):
        assert helper in KERNEL_SETUP


def test_get_model_routes_by_id(game):
    gpt = get_model("gpt-5.6", game.meter)
    assert isinstance(gpt, MeteredResponses)
    assert gpt.service_tier == "flex" and gpt.truncation == "auto"
    claude = get_model("claude-opus-5", game.meter)
    assert type(claude).__name__ == "MeteredClaude"
    assert claude.cache_system_prompt and claude.cache_tools
    gemini = get_model("gemini-3.7-flash", game.meter)
    assert type(gemini).__name__ == "MeteredGemini"
    assert gemini.thinking_level == "high"
    for mid, cls in (
        ("deepseek-v4-flash", "MeteredDeepSeek"),
        ("grok-4-1-latest", "MeteredXAI"),
        ("mistral-large-latest", "MeteredMistral"),
    ):
        assert type(get_model(mid, game.meter)).__name__ == cls
    oss = get_model("accounts/fireworks/models/glm-5p2", game.meter)
    assert type(oss).__name__ == "MeteredFireworks"
    assert oss.request_params == {"parallel_tool_calls": False}


def test_get_model_effort_overrides(game):
    assert get_model("claude-opus-5", game.meter).output_config == {"effort": "max"}  # the lane's default depth
    assert get_model("claude-opus-5", game.meter, effort="medium").output_config == {"effort": "medium"}
    assert get_model("gpt-5.6", game.meter).reasoning_effort == "max"
    assert get_model("gpt-5.6", game.meter, effort="low").reasoning_effort == "low"
    assert get_model("gemini-3.7-flash", game.meter, effort="low").thinking_level == "low"
    with pytest.raises(RuntimeError, match="effort"):
        get_model("deepseek-v4-flash", game.meter, effort="low")  # lanes without the knob refuse it loudly


def test_metered_model_reports_usage(game):
    from types import SimpleNamespace

    model = MeteredResponses(id="gpt-5.6", meter=game.meter)
    before = dict(game.tokens)
    provider_usage = SimpleNamespace(  # the OpenAI ResponseUsage shape the parent parser reads
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        input_tokens_details=SimpleNamespace(cached_tokens=2),
        output_tokens_details=SimpleNamespace(reasoning_tokens=3),
    )
    model._get_metrics(provider_usage)
    assert game.tokens["total"] == before["total"] + 15
    assert game.tokens["cached"] == before["cached"] + 2
    assert game.tokens["reason"] == before["reason"] + 3
