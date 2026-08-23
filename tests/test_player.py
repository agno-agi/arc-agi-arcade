"""Player campaign logic that must hold without the engine: which traces are allowed to compete."""

from json import dumps

from arcade.player import Player


def make_player(tmp_path, monkeypatch, games):
    player = Player(model="gpt-5.6", board_size=len(games))
    monkeypatch.setattr(Player, "out_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(Player, "board", lambda self: games)
    return player


def bank(tmp_path, game, state, header_game=None, steps=1):
    """A run dir as the sweep leaves it: summary.json plus a trace with a header and recorded steps."""
    game_dir = tmp_path / game
    game_dir.mkdir()
    (game_dir / "summary.json").write_text(dumps({"state": state}))
    lines = [dumps({"game_id": f"{header_game or game}-0123abcd"})]
    lines += [dumps({"n": n + 1, "state": state}) for n in range(steps)]
    (game_dir / "trace.jsonl").write_text("\n".join(lines) + "\n")


def test_compete_takes_only_win_traces(tmp_path, monkeypatch):
    player = make_player(tmp_path, monkeypatch, ["aaaa", "bbbb", "cccc"])
    bank(tmp_path, "aaaa", "WIN")
    bank(tmp_path, "bbbb", "GAME_OVER")  # played but never won: must not reach a scorecard
    paths, missing = player.campaign_traces()
    assert [path.parent.name for path in paths] == ["aaaa"]
    assert missing == ["bbbb", "cccc"]  # cccc was never played at all


def test_win_needs_the_trace_not_just_the_summary(tmp_path, monkeypatch):
    """A truncated or misplaced trace must not compete on the strength of a WIN summary beside it."""
    player = make_player(tmp_path, monkeypatch, ["aaaa", "bbbb"])
    bank(tmp_path, "aaaa", "WIN", steps=0)  # header-only trace: the recorded actions are gone
    bank(tmp_path, "bbbb", "WIN", header_game="zzzz")  # trace records a different game than the dir claims
    paths, missing = player.campaign_traces()
    assert paths == [] and missing == ["aaaa", "bbbb"]


def test_sweep_command_carries_agent_and_effort():
    custom = Player(model="claude-opus-5", agent="players/custom.py:make", effort="medium", run="r1")
    command = custom._sweep_command(["aaaa"], cold=False, seed=None)
    assert command[command.index("--agent") + 1] == "players/custom.py:make"
    assert command[command.index("--effort") + 1] == "medium"
    plain = Player(model="claude-opus-5", run="r1")._sweep_command(["aaaa"], cold=True, seed=None)
    assert "--agent" not in plain and "--effort" not in plain


def test_compete_games_are_deduped_and_normalized(tmp_path, monkeypatch):
    """`compete ls20 ls20-9607627b` must replay one trace once — never the same game twice on the card."""
    player = make_player(tmp_path, monkeypatch, ["aaaa"])
    bank(tmp_path, "aaaa", "WIN")
    paths, missing = player.campaign_traces(["aaaa", "aaaa-0123abcd"])
    assert len(paths) == 1 and missing == []


def test_incomplete_board_refuses_to_compete(tmp_path, monkeypatch):
    player = make_player(tmp_path, monkeypatch, ["aaaa", "bbbb"])
    bank(tmp_path, "aaaa", "WIN")
    assert player.compete() == 1  # refuses before validation: competition is one shot, whole board
    assert player.compete(["aaaa", "bbbb"]) == 1  # a named-but-unwon game refuses too, never silently drops


def test_partial_game_cache_refuses_to_compete(tmp_path, monkeypatch):
    """A pruned environment_files cache must not quietly redefine 'the whole board' as fewer games."""
    player = make_player(tmp_path, monkeypatch, ["aaaa"])
    player.board_size = 25
    bank(tmp_path, "aaaa", "WIN")
    assert player.compete() == 1
