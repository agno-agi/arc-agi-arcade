"""
Player
======
A player is a named configuration plus a durable campaign engine: it plays the whole board over hours,
survives crashes and provider outages, banks wins as replay-validated traces, and draws the campaign as a
live arcade wall in the terminal.
"""

from argparse import ArgumentParser
from dataclasses import dataclass, field
from json import loads
from os import getpid, kill
from pathlib import Path
from signal import SIGINT, SIGTERM, signal
from subprocess import STDOUT
from sys import executable
from time import monotonic, sleep
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from arcade.sweep import local_games
from arcade.traces import actions_per_level, game_score, load_trace

REPO = Path(__file__).parent.parent
console = Console(highlight=False)


@dataclass
class Player:
    """One playable persona: a model, its knowledge policy, and campaign settings."""

    model: str  # model id routed by arcade.models.get_model ("gpt-5.6", "claude-opus-5", ...)
    name: str | None = None  # display name on the chart and the wall (default: the knowledge home)
    knowledge: str | None = None  # knowledge home under knowledge/ (defaults to the model id)
    seeds: list[str] = field(default_factory=list)  # other models' knowledge, merged read-only under its own
    agent: str | None = None  # custom agent factory, "module:callable" or "players/foo.py:callable"
    effort: str | None = None  # reasoning-depth override for the model lane (see arcade.models.get_model)
    vision: bool = True  # False: text-only observations (the hex grid is authoritative anyway)
    jobs: int = 4
    cap: int = 800
    retries: int = 2
    timeout: float = 28_800
    cycles: int = 6  # relaunch-until-done bound: a run that keeps dying stops burning money eventually
    board_size: int = 25  # the ARC-AGI-3 public set; compete refuses a smaller local cache (partial board)
    run: str | None = None  # names this outing: a second run of the same board is a separate event, not a resume

    @property
    def home(self) -> str:
        """The player's identity on disk: the knowledge home, or the model id's last path segment.
        Run dirs are keyed by this, never by the display name — renaming a player must not orphan its runs."""
        return self.knowledge or self.model.split("/")[-1]

    @property
    def handle(self) -> str:
        return (self.name or self.home).upper()

    @property
    def out_dir(self) -> Path:
        """Where this run records itself: runs/player-<name>--<run>. A player who won the board last time
        plays it again from scratch under a new `--run` name: won games are only skipped within one run,
        never across runs, and a previous run's banked traces are never resumed or overwritten. The double
        dash keeps run names out of the player namespace (player-glm-5.2-seeded is a player, not a run)."""
        return REPO / "runs" / f"player-{self.home}{f'--{self.run}' if self.run else ''}"

    def _resolve_run(self, playing: bool) -> None:
        """Every run is named. A bare player-<name> dir is the unnamed old-world run and still resolves,
        so an in-flight campaign relaunches unchanged. Otherwise playing demands a name up front, and the
        read verbs take the only run there is — or list the choices instead of guessing."""
        if self.run or (REPO / "runs" / f"player-{self.home}").exists():
            return
        prefix = f"player-{self.home}--"
        runs_root = REPO / "runs"
        found = sorted(p.name.removeprefix(prefix) for p in runs_root.glob(f"{prefix}*")) if runs_root.exists() else []
        if playing:
            raise SystemExit(
                f"name this run: --run NAME (a fresh name plays the whole board; an existing one resumes it)."
                f" existing: {', '.join(found) or 'none'}"
            )
        if len(found) == 1:
            self.run = found[0]
        elif found:
            raise SystemExit(f"{self.handle} has runs {', '.join(found)} — pick one with --run NAME")
        else:
            raise SystemExit(f"no runs for {self.handle} yet — start one with --run NAME")

    # ------------------------------------------------------------------
    # Campaign engine
    # ------------------------------------------------------------------
    def board(self) -> list[str]:
        return sorted(local_games())

    @staticmethod
    def _bases(games: list[str] | None) -> list[str] | None:
        """Game names normalized to base ids: run dirs, tiles, and reports are keyed by base id."""
        return [game.split("-")[0] for game in games] if games else None

    def open_games(self, games: list[str]) -> list[str]:
        remaining = []
        for game in games:
            path = self.out_dir / game / "summary.json"
            if not path.exists():
                remaining.append(game)
                continue
            summary = loads(path.read_text())
            if summary["state"] != "WIN" and summary["actions"] < summary["budget"]:
                remaining.append(game)
        return remaining

    def _sweep_command(self, games: list[str], cold: bool, seed: str | None) -> list[str]:
        command = [executable, "-m", "arcade.sweep", "run", *games]
        command += ["-j", str(self.jobs), "-n", str(self.cap), "-m", self.model]
        command += ["--retries", str(self.retries), "--timeout", str(self.timeout)]
        if not self.vision:
            command += ["--no-images"]
        if self.knowledge:
            command += ["--knowledge", self.knowledge]
        if self.agent:
            command += ["--agent", self.agent]
        if self.effort:
            command += ["--effort", self.effort]
        command += ["--out", str(self.out_dir.relative_to(REPO))]
        if not cold:
            command += ["--warm"]
            sources = [seed] if seed else self.seeds
            if sources:
                command += ["--seed", ",".join(sources)]
        return command

    def play(self, games: list[str] | None = None, cold: bool = False, seed: str | None = None) -> int:
        """Run the campaign to completion under the live arcade wall; returns 0 when every game is won."""
        chosen = self._bases(games) or self.board()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if (running := self._campaign_pid()) is not None:
            console.print(f"[red]a campaign is already playing {self.handle} (pid {running})[/]")
            return 1  # two writers on one run dir truncate each other's traces — never allow it
        stop = {"asked": False}

        def request_stop(_signo: int, _frame: Any) -> None:
            stop["asked"] = True  # traces are crash-safe; finish the current write and exit

        signal(SIGINT, request_stop)
        signal(SIGTERM, request_stop)

        log_path = self.out_dir / "campaign.log"
        pid_path = self.out_dir / "campaign.pid"
        pid_path.write_text(str(getpid()))
        started = monotonic()
        try:
            for cycle in range(1, self.cycles + 1):
                remaining = self.open_games(chosen)
                if not remaining:
                    break
                with log_path.open("a") as log:
                    log.write(f"cycle {cycle}: {len(remaining)} games open\n")
                    process = run_background(self._sweep_command(remaining, cold, seed), log)
                    self._watch(process, chosen, started, stop)
                if stop["asked"]:
                    break
        finally:
            pid_path.unlink(missing_ok=True)
        self.report(chosen)
        _, missing = self.campaign_traces(chosen)
        return 0 if not missing else 1

    def _campaign_pid(self) -> int | None:
        """The pid of a live campaign on this player's run dir, or None (stale pidfiles are ignored)."""
        pid_path = self.out_dir / "campaign.pid"
        try:
            pid = int(pid_path.read_text().strip())
            kill(pid, 0)
            return pid
        except (OSError, ValueError):
            return None

    def _watch(self, process: Any, games: list[str], started: float, stop: dict[str, bool]) -> None:
        with Live(self._wall(games, started), console=console, refresh_per_second=0.5) as live:
            while process.poll() is None:
                if stop["asked"]:
                    from os import getpgid, killpg

                    try:
                        killpg(getpgid(process.pid), SIGTERM)  # the sweep AND its runners
                    except (OSError, ProcessLookupError):
                        process.terminate()
                sleep(2)
                live.update(self._wall(games, started))
            live.update(self._wall(games, started))

    # ------------------------------------------------------------------
    # The arcade wall
    # ------------------------------------------------------------------
    def _tile(self, game: str) -> Text:
        path = self.out_dir / game / "summary.json"
        if not path.exists():
            return Text(f"{game}\n· · ·", style="dim")
        summary = loads(path.read_text())
        if summary["state"] == "WIN":
            return Text(f"{game}\n★ WIN", style="bold green")
        levels = f"{summary['levels']}/{summary['win_levels']}"
        return Text(f"{game}\nL{levels} a{summary['actions']}", style="yellow")

    def _wall(self, games: list[str], started: float) -> Panel:
        grid = Table.grid(padding=(0, 2))
        for _ in range(5):
            grid.add_column(justify="center")
        for row_start in range(0, len(games), 5):
            grid.add_row(*(self._tile(game) for game in games[row_start : row_start + 5]))
        wins, actions, tokens = self._totals(games)
        score_line = Text.assemble(
            ("  WINS ", "bold"),
            (f"{wins}/{len(games)}", "bold green"),
            ("   ACTIONS ", "bold"),
            (f"{actions:,}", "cyan"),
            ("   TOKENS ", "bold"),
            (f"{tokens / 1e6:.0f}M", "cyan"),
            ("   T+", "bold"),
            (f"{(monotonic() - started) / 60:.0f}m", "magenta"),
        )
        return Panel(
            Group(grid, Text(), score_line),
            title=f"[bold magenta]▶ NOW PLAYING · {self.handle}[/]",
            subtitle="[dim]one credit · whole board[/]",
            border_style="magenta",
        )

    def _totals(self, games: list[str]) -> tuple[int, int, int]:
        wins = actions = tokens = 0
        for game in games:
            path = self.out_dir / game / "summary.json"
            if not path.exists():
                continue
            summary = loads(path.read_text())
            wins += summary["state"] == "WIN"
            actions += summary["actions"]
            trace = self.out_dir / game / "trace.jsonl"
            if trace.exists():
                lines = trace.read_text().splitlines()[1:]
                if lines:
                    tokens += loads(lines[-1]).get("tok_total", 0)
        return wins, actions, tokens

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    def report(self, games: list[str] | None = None) -> None:
        table = Table("game", "state", "levels", "actions", "score", header_style="bold", box=None)
        total, wins = 0.0, 0
        chosen = self._bases(games) or self.board()
        if not chosen:
            console.print("no games in the local cache; nothing to report")
            return
        for game in chosen:
            trace_path = self.out_dir / game / "trace.jsonl"
            if not trace_path.exists():
                table.add_row(game, "[dim]not played[/]", "-", "-", "-")
                continue
            header, steps = load_trace(trace_path)
            state = steps[-1]["state"] if steps else "-"
            score = game_score(header["baselines"], actions_per_level(steps))
            total += score
            wins += state == "WIN"
            style = "green" if state == "WIN" else "yellow"
            table.add_row(
                game,
                f"[{style}]{state}[/]",
                f"{steps[-1]['levels'] if steps else 0}/{header['win_levels']}",
                str(len(steps)),
                f"{score:.1f}",
            )
        console.print(table)
        console.print(f"[bold]{self.handle}[/] · {wins}/{len(chosen)} wins · board score {total / len(chosen):.2f}")

    # ------------------------------------------------------------------
    # Compete
    # ------------------------------------------------------------------
    def campaign_traces(self, games: list[str] | None = None) -> tuple[list[Path], list[str]]:
        """The campaign's WIN traces, one per game (deduped, full ids normalized), plus the games that
        don't hold a valid one yet. WIN-ness is asserted on the trace itself — its last recorded step and
        its header's game id — never on summary.json alone: a truncated or misplaced trace must not reach
        a scorecard just because the summary next to it says WIN."""
        paths, missing = [], []
        for game in dict.fromkeys(self._bases(games) or self.board()):
            trace = self.out_dir / game / "trace.jsonl"
            if self._won(game, trace):
                paths.append(trace)
            else:
                missing.append(game)
        return paths, missing

    def _won(self, game: str, trace: Path) -> bool:
        summary_path = trace.parent / "summary.json"
        if not (trace.exists() and summary_path.exists() and loads(summary_path.read_text())["state"] == "WIN"):
            return False
        lines = [line for line in trace.read_text().splitlines() if line.strip()]
        if len(lines) < 2:
            return False  # header-only: the recorded actions are gone
        header, last = loads(lines[0]), loads(lines[-1])
        return header["game_id"].split("-")[0] == game and last["state"] == "WIN"

    def compete(self, games: list[str] | None = None, dry_run: bool = False) -> int:
        """Mint the official score from this campaign: validate its WIN traces offline (fail-closed), then
        replay them into ONE Competition Mode scorecard (or, with dry_run, a throwaway NORMAL scorecard —
        the online rehearsal that catches server-side game version drift the offline pass cannot see).
        The YES gate stays in replay.py — nothing opens a competition scorecard until a human at a real
        terminal types YES."""
        from subprocess import call

        if games is None and len(self.board()) != self.board_size:
            # "Whole board" is defined by the local game cache; a partial cache must never quietly
            # become a smaller board on the one scorecard that counts.
            console.print(f"[red]local game cache holds {len(self.board())} games; expected {self.board_size}[/]")
            console.print("refusing: re-download the game cache, or name games explicitly")
            return 1
        paths, missing = self.campaign_traces(games)
        if missing:
            # Refuse loudly rather than silently minting a smaller board than asked for — one shot.
            console.print(f"[red]no valid WIN trace yet for: {', '.join(missing)}[/]")
            if games is None:
                from sys import argv  # argv[0] is the invoked form, e.g. "play gpt" — a runnable hint

                console.print("competition is one scorecard for the whole board; finish the campaign first,")
                console.print(f"or name games explicitly: {argv[0]} compete <games>")
            return 1
        if not paths:
            console.print("[red]no WIN traces to replay[/]")
            return 1
        self.report(games)
        replay_module = [executable, "-m", "arcade.replay"]
        console.print(f"\nvalidating {len(paths)} trace(s) offline, fail-closed ...")
        if call([*replay_module, *map(str, paths)], cwd=str(REPO)) != 0:
            console.print("[red]offline validation failed — not opening a scorecard[/]")
            return 1
        mode = "--online" if dry_run else "--competition"
        return call([*replay_module, *map(str, paths), mode], cwd=str(REPO))

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------
    def chart(self) -> None:
        """The score screen: this campaign's aggregate score vs output tokens, written next to its runs."""
        from arcade.chart import Series, render

        out = self.out_dir / "chart.html"
        live = self._campaign_pid() is not None
        series = Series(
            self.out_dir,
            self.handle,
            seed=", ".join(self.seeds).upper(),
            tag="RUNNING" if live else "",
            run=self.run or "",
        )
        for line in render([series], out, f"AGNO · {self.handle} · SCOREBOARD"):
            console.print(line)

    # ------------------------------------------------------------------
    # CLI
    # ------------------------------------------------------------------
    def main(self) -> None:
        parser = ArgumentParser(description=f"Play ARC-AGI-3 as {self.handle}.")
        commands = parser.add_subparsers(dest="command", required=True)
        play = commands.add_parser("play", help="run the campaign (default: the whole board)")
        play.add_argument("games", nargs="*", help="subset of games (default: all)")
        play.add_argument(
            "--cold", action="store_true", help="start with no prior knowledge (the agent still learns as it plays)"
        )
        play.add_argument("--seed", metavar="KNOWLEDGE", help="also warm-start from this knowledge dir")
        play.add_argument(
            "--run", metavar="NAME", help="name this outing: plays the whole board again into runs/player-<n>-NAME"
        )
        report = commands.add_parser("report", help="score the campaign so far")
        report.add_argument("games", nargs="*", help="subset of games (default: all)")
        compete = commands.add_parser(
            "compete", help="replay this campaign's WIN traces into ONE Competition scorecard"
        )
        compete.add_argument(
            "games", nargs="*", help="subset of games (default: the whole board, which must be complete)"
        )
        compete.add_argument("--dry-run", action="store_true", help="rehearse online into a throwaway NORMAL scorecard")
        chart = commands.add_parser("chart", help="draw the campaign's score-vs-compute curve")
        for verb in (report, compete, chart):  # score, mint and draw the outing you name, not just the default one
            verb.add_argument("--run", metavar="NAME", help="the outing to read (default: the player's own run dir)")
        # `play` is the implicit verb: `play glm lf52 --cold` means `play glm play lf52 --cold`.
        from sys import argv as current_argv  # at call time: the play command rebinds sys.argv wholesale

        argv = current_argv[1:]
        if not argv or argv[0] not in ("play", "report", "compete", "chart", "-h", "--help"):
            argv = ["play", *argv]
        args = parser.parse_args(argv)
        if getattr(args, "cold", False) and getattr(args, "seed", None):
            parser.error("--cold and --seed contradict each other: cold means no knowledge at all")
        self.run = getattr(args, "run", None) or self.run  # every verb reads the same run
        self._resolve_run(playing=args.command == "play")
        if args.command == "report":
            self.report(args.games or None)
        elif args.command == "chart":
            self.chart()
        elif args.command == "compete":
            raise SystemExit(self.compete(args.games or None, dry_run=args.dry_run))
        else:
            raise SystemExit(self.play(args.games or None, cold=args.cold, seed=args.seed))


def run_background(command: list[str], log: Any) -> Any:
    from subprocess import Popen

    # Its own process group: stopping the campaign must stop the runner grandchildren too, or they
    # keep burning provider tokens unattended after the wall goes down.
    return Popen(command, stdout=log, stderr=STDOUT, cwd=str(REPO), start_new_session=True)


__all__ = ["Player"]
