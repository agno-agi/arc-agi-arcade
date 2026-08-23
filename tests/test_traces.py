"""Trace format and official RHAE scoring — pure functions, no engine."""

from numpy import array

from arcade.traces import (
    LEVEL_SCORE_CAP,
    TraceWriter,
    actions_per_level,
    game_score,
    grid_hash,
    level_score,
    load_trace,
)


def test_grid_hash_is_stable_across_dtypes():
    a = array([[1, 2], [3, 4]], dtype="int8")
    b = array([[1, 2], [3, 4]], dtype="int16")
    assert grid_hash(a) == grid_hash(b)
    assert grid_hash(a) != grid_hash(array([[1, 2], [3, 5]], dtype="int8"))
    assert len(grid_hash(a)) == 16


def test_trace_writer_roundtrip(tmp_path):
    path = tmp_path / "trace.jsonl"
    writer = TraceWriter(path, {"game_id": "xx00-abc", "baselines": [3, 4]})
    writer.append({"n": 1, "action": "ACTION1", "levels": 0})
    writer.append({"n": 2, "action": "ACTION2", "levels": 1})
    header, steps = load_trace(path)
    assert header["game_id"] == "xx00-abc" and len(steps) == 2
    assert steps[1]["levels"] == 1


def test_actions_per_level_attribution():
    steps = [
        {"n": 1, "levels": 0},
        {"n": 2, "levels": 1},  # level 1 took 2 actions
        {"n": 3, "levels": 1},
        {"n": 4, "levels": 1},
        {"n": 5, "levels": 2},  # level 2 took 3 actions
        {"n": 6, "levels": 2},  # unfinished tail dropped
    ]
    assert actions_per_level(steps) == [2, 3]


def test_actions_per_level_double_jump():
    steps = [{"n": 1, "levels": 0}, {"n": 2, "levels": 2}]  # one action completes two levels
    assert actions_per_level(steps) == [2, 0]


def test_level_score_cap_and_free_level():
    assert level_score(100, 200) == 25.0
    assert level_score(100, 50) == LEVEL_SCORE_CAP
    assert level_score(100, 0) == LEVEL_SCORE_CAP


def test_game_score_completion_ceiling():
    baselines = [32, 81, 60, 71, 205, 148, 244, 109, 164, 225]
    # 5/10 with every level at cap must clip at the completion ceiling, not the cap-weighted average.
    assert abs(game_score(baselines, [8, 57, 46, 56, 105]) - 27.27) < 0.01
    # Full completion at cap clips at exactly 100.
    assert game_score([10] * 5, [9] * 5) == 100.0
    # The lf52 winning tape computes to exactly 100.0 despite one sub-cap level.
    assert game_score(baselines, [9, 47, 46, 51, 87, 197, 146, 78, 134, 50]) == 100.0
    assert game_score(baselines, []) == 0.0
