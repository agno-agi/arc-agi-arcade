"""
Scoreboard
==========
Draws aggregate board score vs output tokens per game (log x) from recorded traces.
Each series is one run directory; the score of a game at token budget T is the RHAE score
of the longest trace prefix whose cumulative tok_out fits in T. Score only
moves at level completions, so every game is a step function.

    python -m arcade.chart runs/player-gpt-5.6:GPT-5.6:COLD::RUNNING -o tmp/scoreboard.html   # or: play gpt chart

A series spec is `dir[:MODEL[:MODE[:SEED[:TAG]]]]`. The legend reads as a leaderboard, ordered by
score: who played, how (COLD / WARM), whose knowledge seeded the run (credit flows back to the model
that wrote the manuals), the board score, the levels won, and a status tag.

One run of one type per model draws: reruns keep their traces, but the board keeps only the best of
them — the highest score first, then the fewest tokens (an equal score bought cheaper is a strictly
better run, and efficiency is this chart's other axis); a VERIFIED (officially minted) run wins what
remains, so it never cedes its row or its status to a rerun that merely matches it.
"""

from argparse import ArgumentParser
from dataclasses import dataclass
from itertools import cycle
from math import exp, log
from pathlib import Path
from typing import Any

from arcade.traces import actions_per_level, game_score, load_trace

COLORS = [
    "#9be24a", "#35d0c5", "#a78bfa", "#f0a35e", "#e2637f", "#d6c94a", "#4aa8e2",
    "#d670e0", "#6fd6a3", "#e05a5a", "#8fa3b8", "#b58a5a", "#7f8fe0", "#5aa87f",
]  # fmt: skip
GRID, WIDTH, HEIGHT, ML, MR, MT, MB = 480, 1500, 900, 110, 40, 90, 90

# The ARC-AGI-3 public demonstration set (matches Player.board_size). A board score divides by the whole
# board, not by the games played so far: a game not yet reached scores zero on the card, and averaging over
# played games only would flatter a lane that has picked off five easy games — the same aggregate the live
# dashboard and a minted scorecard report.
BOARD_GAMES, BOARD_LEVELS = 25, 183
HUMAN_BASELINE = 95.4  # ARC's published expert aggregate for the public set (cited in the README)

# Legend columns, in a monospace grid: dot, name, run mode, seed, score (right-aligned), levels, status
# chip. Columns are hand-placed rather than measured: at 15px with 1px tracking a character advances
# ~11px, and the widest cells are a 17-character name and a 7-character seed. The legend ranks the
# top 10; every series past that keeps its curve but cedes its legend row.
DOT_X, COL_MODEL, COL_MODE, COL_SEED = ML + 26, ML + 46, ML + 250, ML + 346
COL_SCORE, COL_LEVELS, COL_TOK, COL_TAG = ML + 486, ML + 502, ML + 642, ML + 662
# 15px legend text advances ~11px per character; the 13px status chips advance ~8.8px — sizing a chip
# with the wrong advance leaves it trailing dead padding on the right.
CHAR_W, TAG_CHAR_W, LEGEND_ROW, LEGEND_TOP = 11, 8.8, 22, 10

# A tag is a status the traces cannot tell you: (text, chip) colors. Unknown tags render in the neutral chip.
TAGS = {
    "VERIFIED": ("#6fd6a3", "#122a1e"),
    "RUNNING": ("#7fb3d5", "#15242e"),
    "CONTAMINATED": ("#e0a33a", "#2b2210"),
    "CANCELED": ("#c98f8f", "#2a1616"),
}
NEUTRAL_TAG = ("#8b949b", "#1a1e22")


@dataclass
class Series:
    """One curve on the board: where it played, who played it, how it played, whose knowledge seeded
    it (credit flows back to the model that wrote the manuals), and its status."""

    run_dir: Path
    model: str
    mode: str = ""  # COLD · WARM — the run's semantic type (drives one-run-per-type)
    seed: str = ""  # the model whose knowledge seeded the run, e.g. GPT-5.6
    tag: str = ""  # VERIFIED · RUNNING · CONTAMINATED · CANCELED · anything short
    run: str = ""  # the run id shown on the board (warm-2, cold-1, seeded-1); mode shows when unnamed


def game_steps(header: dict[str, Any], steps: list[dict[str, Any]]) -> list[tuple[int, float]]:
    """(cumulative output tokens, board score) at each level completion, plus the run's end point."""
    points, done = [], 0
    for n, step in enumerate(steps, 1):
        if step["levels"] > done:
            done = step["levels"]
            points.append((step["tok_out"], game_score(header["baselines"], actions_per_level(steps[:n]))))
    points.append((steps[-1]["tok_out"], game_score(header["baselines"], actions_per_level(steps))))
    return points


def score_at(points: list[tuple[int, float]], budget: float) -> float:
    best = 0.0
    for tokens, score in points:
        if tokens <= budget:
            best = max(best, score)
    return best


def render(series: list[Series], out: Path, title: str) -> list[str]:
    """Render one HTML chart from a list of Series; returns one summary line per series."""
    drawn: list[dict[str, Any]] = []
    summary: list[str] = []
    for spec, color in zip(series, cycle(COLORS)):
        paths = sorted(spec.run_dir.glob("*/trace.jsonl")) or sorted(spec.run_dir.glob("*.jsonl"))
        games: list[list[tuple[int, float]]] = []
        levels = skipped = 0
        for path in paths:
            header, steps = load_trace(path)
            # A game with no actions yet, or one whose actions carry no token stamps, cannot be placed on
            # a token axis. It is skipped whole: counting its levels while its score goes unmeasured would
            # quietly lower the board.
            if not steps or "tok_out" not in steps[-1]:
                skipped += 1
                continue
            games.append(game_steps(header, steps))
            levels += steps[-1]["levels"]
        if not games:
            summary.append(f"skip {spec.run_dir}: no traces")
            continue
        if skipped:
            summary.append(f"note: {spec.model}: {skipped} trace(s) not charted (no actions, or no token stamps)")
        lo = max(min(min(t for t, _ in g) for g in games), 1)
        hi = max(max(t for t, _ in g) for g in games)
        # The last sample is pinned to hi exactly: float rounding must not drop the final completion.
        grid = [exp(log(lo) + k * (log(hi) - log(lo)) / GRID) for k in range(GRID)] + [hi]
        curve = [(t, sum(score_at(g, t) for g in games) / BOARD_GAMES) for t in grid]
        drawn.append({"spec": spec, "color": color, "curve": curve, "levels": f"{levels}/{BOARD_LEVELS}"})
        who = " · ".join(filter(None, (spec.model, spec.mode, f"seed {spec.seed}" if spec.seed else "", spec.tag)))
        summary.append(f"{who}: {len(games)} games · final {curve[-1][1]:.2f} @ {curve[-1][0]:,.0f} tok/game")

    # One run of one type per model — with two exceptions that ARE the story. The type is (model, mode,
    # seed), contaminated runs standing apart so a negative result never masks a clean one. A VERIFIED
    # run is a minted receipt: permanent, never displaced. Unverified reruns collapse to their best —
    # highest score, then fewest tokens, because matching a score cheaper is beating it — and that
    # challenger earns its own row BESIDE the mints only by beating every one of them: the old curve
    # stays so the new curve's efficiency is visible against it. A RUNNING challenger that hasn't beaten
    # the mints yet still draws, subordinate: the chase is worth watching, and only the chase.
    def run_type(s: dict[str, Any]) -> tuple[str, str, str, bool]:
        return (s["spec"].model, s["spec"].mode, s["spec"].seed, s["spec"].tag == "CONTAMINATED")

    def merit(s: dict[str, Any]) -> tuple[float, float]:
        return (s["curve"][-1][1], -s["curve"][-1][0])

    minted = [s for s in drawn if s["spec"].tag == "VERIFIED"]
    challenger: dict[tuple[str, str, str, bool], dict[str, Any]] = {}
    for s in drawn:
        if s["spec"].tag == "VERIFIED":
            continue
        held = challenger.get(run_type(s))
        if held is None or merit(s) > merit(held):
            challenger[run_type(s)] = s
    board, chasing = list(minted), []
    for key, s in challenger.items():
        receipts = [v for v in minted if run_type(v) == key]
        if all(merit(s) > merit(v) for v in receipts):
            board.append(s)
        elif s["spec"].tag == "RUNNING":
            chasing.append(s)
    kept_ids = {id(s) for s in (*board, *chasing)}
    for s in drawn:
        if id(s) not in kept_ids:
            summary.append(f"one run per type: dropped {s['spec'].model} {s['spec'].mode} at {s['curve'][-1][1]:.2f}")

    # The board draws exactly what it ranks — the top 10 — plus every RUNNING lane: a live lane keeps its
    # curve while it climbs (drawn subordinate until it earns a legend row), but a settled lane below the
    # board disappears entirely, so retired experiments can never silt up the chart. Contaminated lanes
    # are exhibits, not competitors: excluded from claims, they take only the legend slots clean lanes
    # leave open, whatever their score — a negative result must never crowd a clean run off the board.
    ranked = sorted(board, key=lambda s: (s["spec"].tag != "CONTAMINATED", s["curve"][-1][1]), reverse=True)[
        :LEGEND_TOP
    ]
    ranked.sort(key=lambda s: s["curve"][-1][1], reverse=True)  # rows still read purely by score
    ranked_ids = {id(s) for s in ranked}
    for s in board:
        if id(s) not in ranked_ids and s["spec"].tag != "RUNNING":
            summary.append(f"off the board: {s['spec'].model} {s['spec'].mode} at {s['curve'][-1][1]:.2f} (settled)")
    drawn = [s for s in board if id(s) in ranked_ids or s["spec"].tag == "RUNNING"] + chasing
    climbers = [s for s in drawn if id(s) not in ranked_ids]
    for s in chasing:
        summary.append(f"chasing the mint: {s['spec'].model} {s['spec'].mode} at {s['curve'][-1][1]:.2f} (running)")
    for s, color in zip((*ranked, *climbers), cycle(COLORS)):
        s["color"] = color  # rank order claims the palette: the legend reads as the first ten colors
    if not drawn:
        return summary

    # Legend geometry, fixed early: the panel is translucent glass, so curves may ghost beneath it, but a
    # reference line running under the header is noise — the baseline starts clear of the panel instead.
    legend_top = MT + 12
    legend_h = 24 + (len(ranked) + 1) * LEGEND_ROW + 8
    # The panel is only as wide as its widest status chip: with none it stops short of the climbing curves.
    chips = [len(s["spec"].tag) * TAG_CHAR_W + 8 for s in ranked] + [len("STATUS") * 10.0]
    legend_w = COL_TAG + max(chips) + 12 - ML

    x_lo = min(c["curve"][0][0] for c in drawn)
    x_hi = max(c["curve"][-1][0] for c in drawn)
    if log(x_hi) - log(x_lo) <= 0:  # equal, or within float epsilon of it — the axis divides by this gap,
        x_hi = x_lo * 10  # so a single fresh completion must still draw, not divide by zero

    def x(tokens: float) -> float:
        return ML + (log(tokens) - log(x_lo)) / (log(x_hi) - log(x_lo)) * (WIDTH - ML - MR)

    def y(score: float) -> float:
        return MT + (100 - score) / 100 * (HEIGHT - MT - MB)

    svg = []
    for tick in (0, 25, 50, 75, 100):
        svg.append(f'<line x1="{ML}" y1="{y(tick)}" x2="{WIDTH - MR}" y2="{y(tick)}" class="grid"/>')
        svg.append(f'<text x="{ML - 14}" y="{y(tick) + 5}" class="tick" text-anchor="end">{tick}</text>')
    decade = 10 ** int(log(x_lo) / log(10))
    while decade <= x_hi * 10:
        for mult in (1, 3):
            tick = decade * mult
            if x_lo <= tick <= x_hi:
                label = f"{tick / 1e6:g}M" if tick >= 1e6 else f"{tick:,.0f}"
                svg.append(f'<line x1="{x(tick)}" y1="{MT}" x2="{x(tick)}" y2="{HEIGHT - MB}" class="grid"/>')
                svg.append(
                    f'<text x="{x(tick)}" y="{HEIGHT - MB + 32}" class="tick" text-anchor="middle">{label}</text>'
                )
        decade *= 10
    svg.append(f'<line x1="{ML}" y1="{y(100)}" x2="{WIDTH - MR}" y2="{y(100)}" class="cap"/>')
    svg.append(
        f'<text x="{WIDTH - MR}" y="{y(100) - 10}" class="cap-label" text-anchor="end">PERFECT SCORE · 100</text>'
    )
    base_y = y(HUMAN_BASELINE)
    base_x = ML + legend_w + 14 if legend_top <= base_y <= legend_top + legend_h else ML
    svg.append(f'<line x1="{base_x:.0f}" y1="{base_y}" x2="{WIDTH - MR}" y2="{base_y}" class="base"/>')
    svg.append(
        f'<text x="{WIDTH - MR}" y="{base_y + 26}" class="base-label"'
        f' text-anchor="end">HUMAN BASELINE · {HUMAN_BASELINE}</text>'
    )
    chasing_ids = {id(s) for s in chasing}
    for s in drawn:
        # Draw the aggregate as a step path: score holds flat until the next completion lands. A lane
        # chasing a mint draws at full weight with its name on the curve tip — the continual-learning
        # image is a rerun visibly closing on its own receipt. Ordinary lanes still climbing toward the
        # board draw subordinate — thinner and translucent — until they earn a row.
        listed, chase = id(s) in ranked_ids, id(s) in chasing_ids
        d = f"M {x(s['curve'][0][0]):.1f} {y(s['curve'][0][1]):.1f}"
        for (_, v0), (t1, v1) in zip(s["curve"], s["curve"][1:]):
            d += f" L {x(t1):.1f} {y(v0):.1f} L {x(t1):.1f} {y(v1):.1f}"
        weight = (
            'stroke-width="3"'
            if listed
            else ('stroke-width="3" opacity="0.8"' if chase else 'stroke-width="2" opacity="0.55"')
        )
        svg.append(f'<path d="{d}" fill="none" stroke="{s["color"]}" {weight}/>')
        tf, vf = s["curve"][-1]
        dot = 'r="6"' if listed else ('r="5" opacity="0.8"' if chase else 'r="4" opacity="0.55"')
        svg.append(f'<circle cx="{x(tf)}" cy="{y(vf)}" {dot} fill="{s["color"]}"/>')
        if chase:
            tip, anchor = (x(tf) + 12, "start") if x(tf) < WIDTH - MR - 220 else (x(tf) - 12, "end")
            label = f"{s['spec'].model} · CHASING"
            # Painted twice — a background-colored halo first — so the label reads over curve traffic.
            svg.append(
                f'<text x="{tip:.0f}" y="{y(vf) + 5}" class="chase" stroke="#0b0d0e" stroke-width="8"'
                f' text-anchor="{anchor}">{label}</text>'
            )
            svg.append(
                f'<text x="{tip:.0f}" y="{y(vf) + 5}" class="chase" fill="{s["color"]}"'
                f' text-anchor="{anchor}">{label}</text>'
            )

    # The legend is a leaderboard: the top 10 by board score, under a header row, flush with the plot edge.
    top = legend_top
    legend = [f'<rect x="{ML}" y="{top}" width="{legend_w:.0f}" height="{legend_h}" rx="6" class="panel"/>']
    for x_pos, label, anchor in (
        (COL_MODEL, "NAME", "start"),
        (COL_MODE, "RUN", "start"),
        (COL_SEED, "SEED", "start"),
        (COL_SCORE, "RHAE", "end"),
        (COL_LEVELS, "LEVELS", "start"),
        (COL_TOK, "TOKENS", "end"),
        (COL_TAG, "STATUS", "start"),
    ):
        legend.append(f'<text x="{x_pos}" y="{top + 28}" class="head" text-anchor="{anchor}">{label}</text>')
    for i, s in enumerate(ranked):
        row = top + 28 + (i + 1) * LEGEND_ROW
        spec, color = s["spec"], s["color"]
        legend.append(f'<circle cx="{DOT_X}" cy="{row - 5}" r="6" fill="{color}"/>')
        legend.append(f'<text x="{COL_MODEL}" y="{row}" class="model">{spec.model}</text>')
        legend.append(f'<text x="{COL_MODE}" y="{row}" class="mode">{spec.run or spec.mode}</text>')
        legend.append(f'<text x="{COL_SEED}" y="{row}" class="mode">{spec.seed}</text>')
        legend.append(
            f'<text x="{COL_SCORE}" y="{row}" class="score" fill="{color}"'
            f' text-anchor="end">{s["curve"][-1][1]:.2f}</text>'
        )
        legend.append(f'<text x="{COL_LEVELS}" y="{row}" class="levels">{s["levels"]}</text>')
        # The tokens a run's board cost — the number that separates generations of the same run type:
        # two minted 100s differ only here, and the gap between them is the learning made visible.
        tokens = s["curve"][-1][0]
        spent = (
            f"{tokens / 1e6:.1f}M"
            if tokens >= 1e6
            else (f"{tokens / 1e3:.0f}k" if tokens >= 10_000 else f"{tokens:,.0f}")
        )
        legend.append(f'<text x="{COL_TOK}" y="{row}" class="levels" text-anchor="end">{spent}</text>')
        if spec.tag:
            text_color, chip = TAGS.get(spec.tag, NEUTRAL_TAG)
            legend.append(
                f'<rect x="{COL_TAG - 8}" y="{row - 16}" width="{len(spec.tag) * TAG_CHAR_W + 16:.0f}" height="21"'
                f' rx="4" fill="{chip}"/>'
            )
            legend.append(f'<text x="{COL_TAG}" y="{row}" class="tag" fill="{text_color}">{spec.tag}</text>')

    mid_y = (MT + HEIGHT - MB) / 2
    html = f"""<title>{title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap">
<style>
  body {{ background: #0b0d0e; color: #9aa3a9; margin: 0; padding: 3vmin;
         font-family: "JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace; }}
  .frame {{ max-width: 1500px; margin: 0 auto; }}
  svg {{ width: 100%; height: auto; display: block; }}
  .title {{ fill: #e8ecee; font-size: 30px; font-weight: 700; letter-spacing: 2px; }}
  .tick {{ fill: #6b7480; font-size: 19px; }}
  .grid {{ stroke: #1d2226; stroke-width: 1; }}
  .cap {{ stroke: #5b8dd6; stroke-width: 2; stroke-dasharray: 10 7; }}
  .cap-label {{ fill: #5b8dd6; font-size: 18px; letter-spacing: 1px; }}
  .base {{ stroke: #4a5258; stroke-width: 2; stroke-dasharray: 4 7; }}
  .base-label {{ fill: #8b949b; font-size: 18px; letter-spacing: 1px; }}
  .chase {{ font-size: 14px; font-weight: 700; letter-spacing: 1px; }}
  .axis {{ fill: #6b7480; font-size: 19px; letter-spacing: 3px; }}
  .panel {{ fill: #0b0d0e; fill-opacity: 0.78; stroke: #1d2226; stroke-width: 1; }}
  .head {{ fill: #6b7480; font-size: 12px; letter-spacing: 2px; }}
  .model {{ fill: #e8ecee; font-size: 15px; letter-spacing: 1px; }}
  .mode {{ fill: #9aa3a9; font-size: 15px; letter-spacing: 1px; }}
  .score {{ font-size: 15px; font-weight: 700; letter-spacing: 1px; }}
  .levels {{ fill: #8b949b; font-size: 15px; letter-spacing: 1px; }}
  .tag {{ font-size: 13px; letter-spacing: 1px; }}
</style>
<div class="frame">
<svg viewBox="0 0 {WIDTH} {HEIGHT}" xmlns="http://www.w3.org/2000/svg">
  <text x="{ML}" y="48" class="title">{title}</text>
  <text x="{ML - 70}" y="{mid_y}" class="axis" transform="rotate(-90 {ML - 70} {mid_y})"
        text-anchor="middle">SCORE %</text>
  <text x="{(ML + WIDTH - MR) / 2}" y="{HEIGHT - 18}" class="axis"
        text-anchor="middle">OUTPUT TOKENS PER GAME (LOG SCALE)</text>
  {"".join(svg)}
  {"".join(legend)}
</svg>
</div>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    summary.append(f"wrote {out}")
    return summary


def main() -> None:
    parser = ArgumentParser(description="Render score-vs-output-tokens curves from sweep traces.")
    parser.add_argument("series", nargs="+", help="run directory, optionally dir:MODEL:MODE:TAG")
    parser.add_argument("-o", "--out", type=Path, default=Path(__file__).parent.parent / "tmp/scoreboard.html")
    parser.add_argument("--title", default="AGNO · ARC-AGI-3 LEADERBOARD")
    args = parser.parse_args()
    series = []
    for spec in args.series:
        fields = spec.split(":")
        path = Path(fields[0])
        series.append(Series(path, *(fields[1:5] or [path.name])))
    lines = render(series, args.out, args.title)
    for line in lines:
        print(line)
    if not any(line.startswith("wrote ") for line in lines):
        raise SystemExit("nothing to draw")


if __name__ == "__main__":
    main()
