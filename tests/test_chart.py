"""The board's one-run-per-type rule: reruns never stack the board, a verified run keeps its row."""

from json import dumps

from arcade.chart import Series, render


def bank(tmp_path, name, actions):
    """One run dir holding a 1-level game solved in `actions` actions against a baseline of 10:
    level score min((10/actions)^2, 1.15)*100, board score that divided by the 25-game board."""
    run = tmp_path / name
    (run / "aaaa").mkdir(parents=True)
    lines = [dumps({"game_id": "aaaa-1", "win_levels": 1, "baselines": [10]})]
    for n in range(1, actions + 1):
        done = n == actions
        lines.append(
            dumps(
                {
                    "n": n,
                    "state": "WIN" if done else "NOT_FINISHED",
                    "levels": 1 if done else 0,
                    "tok_out": 100 * n,
                    "tok_total": 100 * n,
                }
            )
        )
    (run / "aaaa" / "trace.jsonl").write_text("\n".join(lines) + "\n")
    return run


def test_best_run_of_a_type_keeps_the_row(tmp_path):
    strong, weak = bank(tmp_path, "strong", 10), bank(tmp_path, "weak", 20)
    out = tmp_path / "chart.html"
    summary = render([Series(weak, "GPT", "COLD"), Series(strong, "GPT", "COLD")], out, "T")
    html = out.read_text()
    assert html.count('class="model"') == 1  # one GPT COLD row, never two
    assert ">4.00<" in html and ">1.00<" not in html  # the 10-action clear (4.00) beats the 20-action (1.00)
    assert any("dropped GPT COLD at 1.00" in line for line in summary)


def test_verified_run_keeps_its_row_on_a_tie(tmp_path):
    minted, rerun = bank(tmp_path, "minted", 10), bank(tmp_path, "rerun", 10)
    out = tmp_path / "chart.html"
    for series in (  # whichever side of the tie the verified run is given on, it keeps the row
        [Series(minted, "GPT", "WARM", tag="VERIFIED"), Series(rerun, "GPT", "WARM", tag="RUNNING")],
        [Series(rerun, "GPT", "WARM", tag="RUNNING"), Series(minted, "GPT", "WARM", tag="VERIFIED")],
    ):
        render(series, out, "T")
        html = out.read_text()
        assert html.count('class="model"') == 1
        assert "VERIFIED" in html and "RUNNING" not in html


def test_contaminated_run_never_masks_a_clean_one(tmp_path):
    clean, tainted = bank(tmp_path, "clean", 20), bank(tmp_path, "tainted", 10)
    out = tmp_path / "chart.html"
    render([Series(clean, "KIMI", "COLD"), Series(tainted, "KIMI", "COLD", tag="CONTAMINATED")], out, "T")
    html = out.read_text()
    assert html.count('class="model"') == 2  # the higher-scoring negative result stands apart, both draw
    assert "CONTAMINATED" in html


def test_settled_lanes_below_the_board_vanish_but_climbers_still_draw(tmp_path):
    """The chart draws its top 10 plus every RUNNING lane: a retired experiment can't silt up the board,
    but a live lane keeps its (subordinate) curve while it climbs toward a legend row."""
    series = [Series(bank(tmp_path, f"run{i}", 10 + i), f"M{i}", "COLD") for i in range(10)]
    series.append(Series(bank(tmp_path, "retired", 200), "RETIRED", "COLD", tag="CANCELED"))
    series.append(Series(bank(tmp_path, "climber", 200), "CLIMBER", "COLD", tag="RUNNING"))
    out = tmp_path / "chart.html"
    summary = render(series, out, "T")
    html = out.read_text()
    assert html.count('class="model"') == 10  # the legend holds exactly the board
    assert html.count('<path d="M') == 11  # ten ranked curves plus the live climber; the retired lane is gone
    assert 'opacity="0.55"' in html  # the climber draws subordinate until it earns a row
    assert any("off the board: RETIRED" in line for line in summary)


def test_a_seeded_run_is_its_own_type_and_credits_the_seed(tmp_path):
    plain, seeded = bank(tmp_path, "plain", 10), bank(tmp_path, "seeded", 20)
    out = tmp_path / "chart.html"
    render([Series(plain, "GEMINI", "WARM"), Series(seeded, "GEMINI", "WARM", seed="GPT-5.6")], out, "T")
    html = out.read_text()
    assert html.count('class="model"') == 2  # warm and warm-on-a-seed are different types: both rows draw
    assert ">GPT-5.6</text>" in html  # the seed column gives the credit back to the model that wrote the manuals
