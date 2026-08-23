"""ArcadeTools against the real offline engine — recording, budgets, resume, meter, observations."""

from json import loads

import pytest
from conftest import needs_engine

from arcade.tools import REVISION, ArcadeTools
from arcade.traces import load_trace

pytestmark = needs_engine


def play(game, fc, *actions):
    for action in actions:
        game.take_action(action, fc)


def test_recording_and_header_provenance(run_dir, fc):
    game = ArcadeTools("tr87")
    play(game, fc, "ACTION1", "ACTION2")
    header, steps = load_trace(run_dir / "trace.jsonl")
    assert header["game_id"].startswith("tr87") and header["revision"] == REVISION
    assert [s["n"] for s in steps] == [1, 2]
    assert all(len(s["hash"]) == 16 for s in steps)
    summary = loads((run_dir / "summary.json").read_text())
    assert summary["actions"] == 2 and (run_dir / "grids.npy").exists()


def test_rejected_calls_cost_nothing(run_dir, fc):
    game = ArcadeTools("tr87")
    result = game.take_action("ACTION6", fc, row=10, col=10)  # illegal on tr87's opening frame
    assert "Illegal action" in (result.content or "")
    assert game.actions == 0 and game.tool_calls == 1
    _, steps = load_trace(run_dir / "trace.jsonl")
    assert steps == []  # rejected calls are never recorded


def test_budget_stops_on_committed_actions(run_dir, fc):
    game = ArcadeTools("tr87")
    game.run_budget = 2
    play(game, fc, "ACTION1")
    assert fc.function.stop_after_tool_call is False
    play(game, fc, "ACTION2")
    assert fc.function.stop_after_tool_call is True


def test_diff_line_in_observation(run_dir, fc):
    game = ArcadeTools("tr87")
    result = game.take_action("ACTION1", fc)
    assert "diff:" in result.content


def test_meter_accumulates_and_stamps(run_dir, fc, usage):
    game = ArcadeTools("tr87")
    game.meter(usage(input_tokens=1000, output_tokens=200, cached=100, reasoning=150))
    play(game, fc, "ACTION1")
    game.meter(usage(input_tokens=2000, output_tokens=300, cached=500, reasoning=250))
    play(game, fc, "ACTION2")
    _, steps = load_trace(run_dir / "trace.jsonl")
    assert steps[0]["tok_total"] == 1200 and steps[1]["tok_total"] == 3500
    assert steps[1]["tok_cached"] == 600 and steps[1]["tok_reason"] == 400


def test_resume_restores_progress_tokens_and_heals_torn_tail(run_dir, fc, usage):
    game = ArcadeTools("tr87")
    game.meter(usage())
    play(game, fc, "ACTION1", "ACTION2", "ACTION3")
    trace_path = run_dir / "trace.jsonl"
    with trace_path.open("a") as file:
        file.write('{"n": 4, "action": "ACT')  # torn tail from a killed process

    resumed = ArcadeTools("tr87", resume=trace_path)
    assert resumed.actions == 3
    assert resumed.tokens["total"] == 1200  # stamps continue across restarts
    assert len(trace_path.read_text().splitlines()) == 4  # header + 3 intact actions, tail healed
    assert len(resumed.recent) == 3 and resumed.grids[0].shape == resumed.grids[-1].shape

    result = resumed.take_action("ACTION4", fc)
    assert resumed.actions == 4 and "state=" in result.content


def test_resume_rejects_wrong_game(run_dir, fc):
    game = ArcadeTools("tr87")
    play(game, fc, "ACTION1")
    with pytest.raises(RuntimeError, match="does not match"):
        ArcadeTools("ls20", resume=run_dir / "trace.jsonl")
