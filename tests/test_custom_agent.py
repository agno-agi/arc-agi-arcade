"""A player may bring its own agent: the factory spec resolves to a callable, loudly or not at all."""

import pytest

from arcade.agent import create_agent, resolve_agent_factory


def test_default_factory_is_the_arcade_agent():
    assert resolve_agent_factory(None) is create_agent
    assert resolve_agent_factory("") is create_agent


def test_file_spec_loads_the_named_factory(tmp_path):
    agent_file = tmp_path / "custom.py"
    agent_file.write_text("def make(game, *args, **config):\n    return ('custom', config.get('model'))\n")
    factory = resolve_agent_factory(f"{agent_file}:make")
    assert factory(None, model="gpt-5.6") == ("custom", "gpt-5.6")


def test_file_spec_defaults_to_create_agent(tmp_path):
    agent_file = tmp_path / "custom.py"
    agent_file.write_text("def create_agent(game, *args, **config):\n    return 'made'\n")
    assert resolve_agent_factory(str(agent_file))(None) == "made"


def test_module_spec_resolves():
    assert resolve_agent_factory("arcade.agent:create_agent") is create_agent


def test_factory_must_accept_the_full_contract(tmp_path):
    """A factory missing the effort kwarg would TypeError only after the env opens — refuse it at resolve time."""
    agent_file = tmp_path / "old.py"
    agent_file.write_text("def create_agent(game, model, knowledge, warm, seeds):\n    return 'old'\n")
    with pytest.raises(RuntimeError, match="signature"):
        resolve_agent_factory(str(agent_file))


def test_broken_specs_fail_loudly_before_any_game_opens(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        resolve_agent_factory(str(tmp_path / "missing.py"))
    agent_file = tmp_path / "empty.py"
    agent_file.write_text("")
    with pytest.raises(RuntimeError, match="factory"):
        resolve_agent_factory(f"{agent_file}:nope")
