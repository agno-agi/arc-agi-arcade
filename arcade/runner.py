"""
Runner
======
Loads configuration, composes the Agno agent and ARC toolkit, and plays a game in the terminal.
"""

from argparse import ArgumentParser
from collections.abc import Callable
from functools import cache
from itertools import groupby
from logging import WARNING, getLogger
from os import environ
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from agno.run.agent import RunContentEvent, RunErrorEvent, RunOutput, ToolCallCompletedEvent
from agno.tools.function import ToolResult
from arc_agi import Arcade
from arc_agi.rendering import COLOR_MAP
from arcengine import FrameDataRaw, GameState
from dotenv import load_dotenv
from numpy import ndarray
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.style import Style
from rich.table import Table
from rich.text import Text

from arcade.agent import create_agent, resolve_agent_factory
from arcade.tools import ENVIRONMENTS_DIR, ArcadeTools

console = Console(highlight=False)
STATE_STYLE = {GameState.WIN: "green", GameState.GAME_OVER: "red"}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
@cache
def _cell(top: int, bottom: int) -> Style:
    # Same palette and fallback as arc_agi.rendering.frame_to_rgb_array ("#RRGGBBAA" -> "#RRGGBB").
    return Style(color=COLOR_MAP.get(top, "#000000FF")[:7], bgcolor=COLOR_MAP.get(bottom, "#000000FF")[:7])


def grid_panel(grid: ndarray, title: str, subtitle: str = "", style: str = "dim") -> Panel:
    """Render a frame two rows per line: '▀' paints the top cell in the foreground and the bottom cell behind it."""
    text = Text(no_wrap=True, overflow="crop")
    for top, bottom in zip(grid[0::2].tolist(), grid[1::2].tolist()):
        for (t, b), run in groupby(zip(top, bottom)):
            text.append("▀" * len(list(run)), _cell(t, b))
        text.append("\n")
    text.rstrip()
    return Panel(
        text,
        title=title,
        subtitle=subtitle,
        title_align="left",
        subtitle_align="right",
        border_style=style,
        expand=False,
    )


def state_text(frame: FrameDataRaw) -> str:
    style = STATE_STYLE.get(frame.state, "yellow")
    return f"[{style}]{frame.state.value}[/] · {frame.levels_completed}/{frame.win_levels} levels"


def list_games() -> None:
    table = Table("game", "title", "levels", "baseline", "tags", box=None, header_style="bold")
    for env in sorted(Arcade(environments_dir=ENVIRONMENTS_DIR).available_environments, key=lambda env: env.game_id):
        baseline = env.baseline_actions
        table.add_row(
            env.game_id,
            env.title or "",
            str(len(baseline)) if baseline else "",
            f"{sum(baseline):,}" if baseline else "",
            ", ".join(env.tags or []),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
def play(
    game: ArcadeTools,
    model: str,
    knowledge: str | None,
    warm: bool,
    seeds: list[str],
    effort: str | None = None,
    factory: Callable[..., Any] = create_agent,
) -> RunOutput | None:
    """Run episodes until WIN or the budget is spent; a fresh episode (fresh model context, live env)
    survives a mid-game model stop or transport error, and each completed level starts a fresh session."""
    output, episode, levels_seen, stalls = None, 0, game.frame.levels_completed, 0
    while game.frame.state != GameState.WIN and game.actions < game.run_budget:
        episode += 1
        seen, opening = game.actions, game.observation()
        if episode > 1:
            leveled = game.frame.levels_completed > levels_seen
            reason = "level complete, fresh session" if leveled else "previous run ended mid-game; continuing"
            console.print(f"episode {episode}: {reason}", style="yellow")
            note = (
                (
                    "New session for the next level of a game you are already playing. "
                    if leveled
                    else "You are RESUMING this game mid-run; the previous session ended unexpectedly. "
                )
                + f"Progress: {game.frame.levels_completed}/{game.frame.win_levels} levels, "
                f"{game.actions}/{game.run_budget} actions used. Recent actions (n:ACTION[:DEAD]:Llevels): "
                f"{game.recap()}. Study the board, re-derive the mechanics, and continue playing.\n"
            )
            opening = ToolResult(content=note + (opening.content or ""), images=opening.images)
        levels_seen = game.frame.levels_completed
        output = play_episode(game, model, opening, knowledge, warm, seeds, effort, factory)
        if game.actions == seen and game.frame.levels_completed == levels_seen:
            stalls += 1
            if stalls > 4:
                break  # five episodes committed nothing; stop burning calls
            wait = 60 * 2 ** (stalls - 1)
            console.print(f"episode committed nothing ({stalls}/4); retrying in {wait}s", style="yellow")
            sleep(wait)  # rides out provider queue bursts (flex 429s) instead of abandoning the run
        else:
            stalls = 0
    return output


def play_episode(
    game: ArcadeTools,
    model: str,
    first: ToolResult,
    knowledge: str | None,
    warm: bool,
    seeds: list[str],
    effort: str | None = None,
    factory: Callable[..., Any] = create_agent,
) -> RunOutput | None:
    """Stream one agent run, printing the agent's words and a coloured frame after every committed action."""
    agent = factory(game, model, knowledge=knowledge, warm=warm, seeds=seeds, effort=effort)
    said, output, seen, last = "", None, game.actions, monotonic()
    spinner = Progress(
        SpinnerColumn(), TextColumn("[dim]thinking"), TimeElapsedColumn(), console=console, transient=True
    )
    with spinner:
        task = spinner.add_task("", total=None)
        for event in agent.run(
            first.content, images=first.images, stream=True, stream_events=True, yield_run_output=True
        ):
            if isinstance(event, RunContentEvent):
                said += (event.reasoning_content or "") + (event.content if isinstance(event.content, str) else "")
            elif isinstance(event, ToolCallCompletedEvent) and event.tool is not None:
                if said.strip():
                    console.print(Markdown(said.strip()), style="dim")
                args = event.tool.tool_args or {}
                call = escape(" ".join(str(v) if k == "action" else f"{k}={v}" for k, v in args.items()))
                if game.actions > seen:  # committed: ARC accepted the move and returned a frame
                    console.print(
                        grid_panel(
                            game.grid,
                            f"[bold]{call}[/] · {state_text(game.frame)}",
                            f"{game.actions}/{game.run_budget} actions · {monotonic() - last:.0f}s",
                        )
                    )
                else:
                    console.print(f"[bold]{call}[/] · [red]{escape(event.tool.result or '')}[/]")
                said, seen, last = "", game.actions, monotonic()
                spinner.reset(task)
            elif isinstance(event, RunErrorEvent):
                console.print(f"error: {escape(str(event.content))}", style="bold red")
            elif isinstance(event, RunOutput):
                output = event
    if said.strip():
        console.print(Markdown(said.strip()))
    return output


def main() -> None:
    parser = ArgumentParser(description="Play an ARC-AGI-3 game with an Agno agent.")
    parser.add_argument("game", nargs="?", help="game id, e.g. ls20 or ls20-9607627b")
    parser.add_argument("-n", "--max-actions", type=int, help="cap the action budget (default: 5 x baseline)")
    parser.add_argument(
        "-m",
        "--model",
        default="gpt-5.6",
        help="model id: gpt-*, claude*, or accounts/fireworks/* (default: %(default)s)",
    )
    parser.add_argument("--resume", type=Path, help="replay this trace.jsonl through the env first, then continue")
    parser.add_argument("--warm", action="store_true", help="seed learnings from this model's knowledge")
    parser.add_argument(
        "--seed", metavar="MODELS", help="warm-start from other models' knowledge, comma-separated (implies --warm)"
    )
    parser.add_argument("--knowledge", metavar="NAME", help="knowledge home under knowledge/ (default: the model id)")
    parser.add_argument(
        "--agent",
        metavar="SPEC",
        help="custom agent factory, module:callable or path/to/file.py:callable (default: the arcade agent)",
    )
    parser.add_argument(
        "--effort", metavar="LEVEL", help="reasoning-depth override for the model lane (see arcade.models.get_model)"
    )
    parser.add_argument("--no-images", action="store_true", help="text-only observations (models without vision)")
    parser.add_argument("--list", action="store_true", help="list the available games and exit")
    args = parser.parse_args()
    if args.max_actions is not None and args.max_actions < 1:
        parser.error("--max-actions must be positive")
    load_dotenv()
    # arc_agi installs its own INFO handlers on stdout; keep warnings and errors, drop the chatter.
    for name in ("arc_agi.base", "arc_agi.scorecard"):
        getLogger(name).addFilter(lambda record: record.levelno >= WARNING)

    if args.list:
        list_games()
        return
    if args.game is None:
        parser.error("game is required (or pass --list)")
    factory = resolve_agent_factory(args.agent)  # a broken spec must fail here, before any token is spent
    from arcade.models import get_model

    get_model(args.model, lambda _metrics: None, args.effort)  # the lane/effort gate too: fail before the env opens
    # Circuit breaker for long campaigns: list game ids in a SKIP file next to the run dirs and
    # already-launched sweeps will refuse them without being restarted.
    run_dir = environ.get("ARC_RUN_DIR")
    skip_file = Path(run_dir).parent / "SKIP" if run_dir else None
    if skip_file is not None and skip_file.exists() and args.game.split("-")[0] in skip_file.read_text().split():
        console.print(f"skipped: {args.game} is listed in {skip_file}", style="yellow")
        return

    # The kernel and trace machinery want a run dir; interactive runs get one under tmp/.
    environ.setdefault("ARC_RUN_DIR", str(Path(__file__).parent.parent / "tmp" / f"run-{args.game}"))
    game = ArcadeTools(args.game, resume=args.resume, images=not args.no_images)
    game.run_budget = min(game.action_budget, args.max_actions or game.action_budget)
    game.episode_per_level = True  # a completed level ends the session; only the manual carries forward
    seeds = [source.strip() for source in (args.seed or "").split(",") if source.strip()]
    warm = args.warm or bool(seeds)
    from arcade.knowledge import knowledge_file

    for source in seeds:
        if not knowledge_file(source, game.env.info.game_id).exists():
            console.print(f"seed knowledge not found: {knowledge_file(source, game.env.info.game_id)}", style="yellow")
    if warm:
        console.print(
            f"warm start: knowledge seeded from {', '.join(seeds) or args.knowledge or args.model}", style="yellow"
        )
    if args.resume:
        console.print(f"resumed {game.actions} recorded actions from {args.resume}", style="yellow")
    info = game.env.info
    console.print(
        grid_panel(
            game.grid,
            f"[bold]{info.title or args.game}[/] [dim]{info.game_id}[/]",
            f"{game.frame.win_levels} levels · {game.run_budget} actions · {args.model}",
            "cyan",
        )
    )
    started, output = monotonic(), None
    try:
        output = play(game, args.model, args.knowledge, warm, seeds, args.effort, factory)
    except KeyboardInterrupt:
        console.print("interrupted", style="yellow")
    tokens = f" · {output.metrics.total_tokens:,} tokens" if output and output.metrics else ""
    console.print(
        grid_panel(
            game.grid,
            state_text(game.frame),
            f"{game.actions}/{game.run_budget} actions · {monotonic() - started:.0f}s{tokens}",
            STATE_STYLE.get(game.frame.state, "yellow"),
        )
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(f"error: {error}")
    except OSError as error:  # requests errors subclass OSError: the ARC API was needed and unreachable
        raise SystemExit(
            f"error: {error}\nSet ARC_API_KEY in .env, or OPERATION_MODE=offline to play cached games only."
        )
