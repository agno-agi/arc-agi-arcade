"""Replay validation, engine-backed: a trace recorded here must replay fail-closed, byte for byte."""

from json import dumps, loads

import pytest
from conftest import needs_engine

from arcade.replay import replay_trace
from arcade.tools import ArcadeTools

pytestmark = needs_engine


def make_arcade():
    from arc_agi import Arcade
    from arc_agi.base import OperationMode

    from arcade.tools import ENVIRONMENTS_DIR

    return Arcade(environments_dir=ENVIRONMENTS_DIR, operation_mode=OperationMode.OFFLINE)


@pytest.fixture
def recorded(run_dir, fc):
    """A real trace: a few actions driven straight through the engine, no model involved."""
    game = ArcadeTools("tr87")
    for action in ("ACTION1", "ACTION2", "ACTION3"):
        game.take_action(action, fc)
    return run_dir / "trace.jsonl"


def test_recorded_trace_replays_clean(recorded):
    verdict = replay_trace(make_arcade(), recorded, None)
    assert "FAIL" not in verdict and "3 actions" in verdict


def test_tampered_hash_fails_closed(recorded, tmp_path):
    lines = recorded.read_text().splitlines()
    step = loads(lines[2])
    step["hash"] = "0" * 16
    lines[2] = dumps(step)
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_text("\n".join(lines) + "\n")
    assert "FAIL diverged" in replay_trace(make_arcade(), tampered, None)


def test_tampered_action_fails_closed(recorded, tmp_path):
    lines = recorded.read_text().splitlines()
    step = loads(lines[2])
    step["action"] = "ACTION4"  # a different move must not reproduce the recorded frame hash
    lines[2] = dumps(step)
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_text("\n".join(lines) + "\n")
    assert "FAIL" in replay_trace(make_arcade(), tampered, None)
