"""
The play command
================
`python play.py` shows the players, their records, and every command; `python play.py <name>` hands the
rest of the line to that player. `python play.py setup` downloads the public games (once, no model tokens).
"""

import sys
from importlib import util
from json import loads
from pathlib import Path

from arcade.player import Player

REPO = Path(__file__).parent.parent
BRAND = "color(208)"
BANNER = r""" █████╗  ██████╗ ███╗   ██╗ ██████╗
██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗
███████║██║  ███╗██╔██╗ ██║██║   ██║
██╔══██║██║   ██║██║╚██╗██║██║   ██║
██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝
╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝"""


def load_player(name: str) -> Player:
    path = REPO / "players" / f"{name}.py"
    if not path.exists():
        raise SystemExit(f"no such player: {name} (looked for {path})")
    spec = util.spec_from_file_location(f"players.{name}", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load player file: {path}")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.player


def outings(player: Player) -> list[str | None]:
    """Every recorded outing of a player: the bare old-world dir, then each named run."""
    runs_root = REPO / "runs"
    found: list[str | None] = [None] if (runs_root / f"player-{player.home}").exists() else []
    found += sorted(p.name.removeprefix(f"player-{player.home}--") for p in runs_root.glob(f"player-{player.home}--*"))
    return found


def record(player: Player) -> str:
    """The player's standing across every outing: wins and actions, or dim dots if unplayed."""
    summaries = []
    for run in outings(player):
        player.run = run
        summaries += sorted(player.out_dir.glob("*/summary.json"))
    player.run = None
    if not summaries:
        return "[dim]· · ·[/]"
    wins = actions = 0
    for path in summaries:
        summary = loads(path.read_text())
        wins += summary["state"] == "WIN"
        actions += summary["actions"]
    return f"[bold green]★ {wins} WINS[/] [dim]· {actions:,} actions[/]"


def select_screen() -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console(highlight=False)
    console.print(f"[{BRAND}]{BANNER}[/]")
    table = Table.grid(padding=(0, 3))
    table.add_column(style="bold green")
    table.add_column()
    table.add_column(style="dim")
    table.add_column()
    for path in sorted((REPO / "players").glob("*.py")):
        player = load_player(path.stem)
        model = player.model.split("/")[-1] + (" · fireworks" if "fireworks" in player.model else "")
        seeds = f"seeds: {', '.join(player.seeds)}" if player.seeds else ""
        table.add_row(path.stem, model, seeds, record(player))
    console.print(
        Panel(
            table,
            title=f"[bold {BRAND}]▶ SELECT YOUR PLAYER[/]",
            subtitle="[dim]play <name>[/]",
            border_style=BRAND,
            expand=False,
        )
    )


def commands_screen() -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    table = Table.grid(padding=(0, 3))
    table.add_column(style=f"bold {BRAND}")
    table.add_column(style="dim")
    for command, what in (
        ("python play.py setup", "download the 25 public games (needs ARC_API_KEY; no model tokens)"),
        ("python play.py <name>", "the player plays the whole board, live in your terminal"),
        ("python play.py <name> <game> --cold", "one game, no prior knowledge"),
        ("python play.py <name> report", "score the campaign so far"),
        ("python play.py <name> chart", "the scoreboard: board score vs output tokens"),
        ("python play.py <name> compete", "replay the campaign into ONE official scorecard"),
    ):
        table.add_row(command, what)
    Console(highlight=False).print(Panel(table, title=f"[bold {BRAND}]▶ COMMANDS[/]", border_style=BRAND, expand=False))


def setup() -> None:
    """Download every public game into environment_files/ — the one online step play needs (no model tokens)."""
    from os import environ

    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    if not environ.get("ARC_API_KEY"):
        raise SystemExit("ARC_API_KEY not set — add it to .env (register at three.arcprize.org)")
    from arc_agi import Arcade
    from arc_agi.base import OperationMode

    from arcade.tools import ENVIRONMENTS_DIR

    arc = Arcade(environments_dir=ENVIRONMENTS_DIR, operation_mode=OperationMode.NORMAL)
    games = sorted(env.game_id for env in arc.available_environments)
    print(f"downloading {len(games)} games into {ENVIRONMENTS_DIR} ...")
    failed = []
    for game_id in games:
        ok = arc.make(game_id) is not None
        print(f"  {game_id}: {'ok' if ok else 'FAILED'}")
        failed += [] if ok else [game_id]
    card = getattr(arc, "_default_scorecard_id", None)
    if card:
        try:
            arc.close_scorecard(card)  # the download session's empty card; not a play
        except Exception:  # noqa: BLE001 — cleanup only, the games are already on disk
            pass
    if failed:
        raise SystemExit(f"failed to download: {', '.join(failed)}")
    print("done — every game now plays fully offline")


def live_players() -> list[Player]:
    """Players whose campaign is running right now — one entry per live outing (a live pid in its run dir)."""
    players = []
    for path in sorted((REPO / "players").glob("*.py")):
        for run in outings(load_player(path.stem)):
            player = load_player(path.stem)
            player.run = run
            if player._campaign_pid() is not None:
                players.append(player)
    return players


def lane_table(players: list[Player]):
    from json import loads

    from rich.table import Table

    from arcade.traces import actions_per_level, game_score, load_trace

    table = Table(
        "PLAYER",
        "SCORE",
        "W",
        "LEVELS",
        "ACTIONS",
        "TOKENS",
        "T+",
        "BOARD",
        box=None,
        header_style=f"dim {BRAND}",
        padding=(0, 2),
    )
    totals = {"wins": 0, "levels": 0, "actions": 0, "tokens": 0, "score": 0.0}
    for player in players:
        wins = levels = actions = tokens = 0
        score = 0.0
        chips = []
        for s in sorted(player.out_dir.glob("*/summary.json")):
            d = loads(s.read_text())
            actions += d["actions"]
            levels += d["levels"]
            key = str(s)
            mtime = s.stat().st_mtime
            cached = _lane_cache.get(key)
            if cached is None or cached[0] != mtime:
                trace = s.parent / "trace.jsonl"
                game_points = game_tokens = 0.0
                if trace.exists():
                    header, steps = load_trace(trace)
                    if steps:
                        game_points = game_score(header["baselines"], actions_per_level(steps))
                        game_tokens = steps[-1].get("tok_total", 0)
                cached = (mtime, game_points, game_tokens)
                _lane_cache[key] = cached
            score += cached[1]
            tokens += int(cached[2])
            if d["state"] == "WIN":
                wins += 1
                chips.append(f"[bold green]{s.parent.name}★[/]")
            elif d["actions"] > 0 and d["actions"] < d["budget"]:
                chips.append(f"[yellow]{s.parent.name}[/] [dim]{d['levels']}/{d['win_levels']}[/]")
        board = score / player.board_size
        pid_path = player.out_dir / "campaign.pid"
        minutes = 0
        if pid_path.exists():
            from time import time

            minutes = int((time() - pid_path.stat().st_mtime) / 60)
        totals["wins"] += wins
        totals["levels"] += levels
        totals["actions"] += actions
        totals["tokens"] += tokens
        table.add_row(
            f"[bold green]{player.handle}[/]" + (f" [dim]{player.run}[/]" if player.run else ""),
            f"[bold]{board:5.1f}[/]",
            f"[bold green]{wins}[/]" if wins else "0",
            str(levels),
            f"{actions:,}",
            f"{tokens / 1e6:.0f}M",
            f"{minutes}m",
            " ".join(chips[-7:]) or "[dim]warming up[/]",
        )
    table.add_section()
    table.add_row(
        f"[dim]{len(players)} CAMPAIGNS[/]",
        "",
        f"[bold green]{totals['wins']}[/]",
        f"[bold]{totals['levels']}[/]",
        f"[bold]{totals['actions']:,}[/]",
        f"[bold]{totals['tokens'] / 1e6:.0f}M[/]",
        "",
        "",
    )
    return table


_lane_cache: dict = {}


def dashboard() -> None:
    from time import sleep

    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel

    console = Console(highlight=False)
    console.print(f"[{BRAND}]{BANNER}[/]")
    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                players = live_players()
                if not players:
                    break
                live.update(
                    Panel(
                        lane_table(players),
                        title=f"[bold {BRAND}]▶ NOW PLAYING · {len(players)} CAMPAIGNS[/]",
                        subtitle="[dim]ctrl-c exits the view, never the campaigns[/]",
                        border_style=BRAND,
                        expand=False,
                    )
                )
                sleep(2)
    except KeyboardInterrupt:
        return
    console.print("[dim]no campaigns running[/]")
    select_screen()
    commands_screen()


def main() -> None:
    if not (REPO / "players").is_dir():
        raise SystemExit(
            f"players/ not found at {REPO} — the arcade must be installed editable from its repo:\n"
            "  ./scripts/venv_setup.sh   (or: uv pip install -e . --no-deps)"
        )
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        if live_players():
            dashboard()
        else:
            select_screen()
            commands_screen()
        return
    if sys.argv[1] == "setup":
        setup()
        return
    name, rest = sys.argv[1], sys.argv[2:]
    player = load_player(name)
    sys.argv = [f"play {name}", *rest]
    player.main()


if __name__ == "__main__":
    main()
