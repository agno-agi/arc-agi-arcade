"""
Sweep
=====
Plays many games in parallel as arcade.runner subprocesses, reports trace scores, and promotes the best traces.
"""

from argparse import ArgumentParser, Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from json import loads
from os import environ
from pathlib import Path
from shutil import copy2
from subprocess import STDOUT, TimeoutExpired, run
from sys import executable
from typing import Any

from dotenv import load_dotenv

from arcade.tools import ENVIRONMENTS_DIR
from arcade.traces import actions_per_level, game_score, load_trace

REPO = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Game inventory (local cache only; no network)
# ---------------------------------------------------------------------------
def local_games() -> dict[str, dict[str, Any]]:
    """Newest cached metadata per game, keyed by 4-char base id."""
    games: dict[str, dict[str, Any]] = {}
    for metadata_path in Path(ENVIRONMENTS_DIR).glob("*/*/metadata.json"):
        metadata = loads(metadata_path.read_text())
        base = metadata["game_id"].split("-")[0]
        if base not in games or metadata["date_downloaded"] > games[base]["date_downloaded"]:
            games[base] = metadata
    return games


# ---------------------------------------------------------------------------
# Run games in parallel
# ---------------------------------------------------------------------------
def play_one(metadata: dict[str, Any], out: Path, args: Namespace) -> dict[str, Any]:
    """Run one game as a runner.py subprocess; retry from scratch only if it crashed before finishing."""
    base = metadata["game_id"].split("-")[0]
    game_dir = out / base
    game_dir.mkdir(parents=True, exist_ok=True)
    cap = min(5 * sum(metadata["baseline_actions"]), args.max_actions or 10**6)
    command = [
        executable,
        "-m",
        "arcade.runner",
        metadata["game_id"],
        "-n",
        str(cap),
        "-m",
        args.model,
    ]
    if getattr(args, "warm", False):
        command += ["--warm"]
    if getattr(args, "seed", None):
        command += ["--seed", args.seed]
    if getattr(args, "knowledge", None):
        command += ["--knowledge", args.knowledge]
    if getattr(args, "agent", None):
        command += ["--agent", args.agent]
    if getattr(args, "effort", None):
        command += ["--effort", args.effort]
    if getattr(args, "no_images", False):
        command += ["--no-images"]
    # Campaigns are fully local: every game is cached, so the sweep never depends on the ARC API being up.
    child_env = dict(environ, ARC_RUN_DIR=str(game_dir), OPERATION_MODE="offline")
    summary_path, trace_path = game_dir / "summary.json", game_dir / "trace.jsonl"
    if summary_path.exists():
        summary = loads(summary_path.read_text())
        if summary["state"] == "WIN":
            return summary  # this out dir already holds a win; rerunning would overwrite the evidence
    for attempt in range(args.retries + 1):
        # Any recorded progress resumes rather than restarts — a re-launched sweep continues where it died.
        recorded = trace_path.exists() and len(trace_path.read_text().splitlines()) > 1
        resume = ["--resume", str(trace_path)] if recorded else []
        number = 0
        while (log_path := game_dir / f"log{number or ''}.txt").exists():
            number += 1  # never overwrite an earlier launch's log: it holds the token evidence
        with log_path.open("w") as log:
            try:
                run(command + resume, stdout=log, stderr=STDOUT, env=child_env, timeout=args.timeout, check=False)
            except TimeoutExpired:
                log.write("\nsweep: killed by timeout\n")
        if not summary_path.exists():
            continue  # crashed before the first action; retry is safe and cheap
        summary = loads(summary_path.read_text())
        if summary["state"] == "WIN" or summary["actions"] >= summary["budget"] or attempt == args.retries:
            return summary
    return {"game_id": metadata["game_id"], "state": "ERROR", "levels": 0, "actions": 0, "budget": cap}


def sweep(args: Namespace) -> None:
    load_dotenv()
    games = local_games()
    unknown = [name for name in args.games or [] if name.split("-")[0] not in games]
    if unknown:
        raise SystemExit(f"unknown game(s): {', '.join(unknown)} — not in the local cache ({len(games)} games)")
    picked = [games[name.split("-")[0]] for name in args.games] if args.games else list(games.values())
    out = REPO / (args.out or f"runs/{datetime.now(UTC):%Y%m%d-%H%M%S}")
    out.mkdir(parents=True, exist_ok=True)
    print(f"sweep: {len(picked)} games · {args.jobs} parallel · cap {args.max_actions or '5x baseline'} · {out}")
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(play_one, metadata, out, args): metadata for metadata in picked}
        for future in as_completed(futures):
            summary = future.result()
            print(
                f"{summary['game_id']}: {summary['state']} · levels {summary['levels']}"
                f"/{summary.get('win_levels', '?')} · {summary['actions']}/{summary['budget']} actions"
            )
    report(out)


# ---------------------------------------------------------------------------
# Score report and trace promotion
# ---------------------------------------------------------------------------
def scored_runs(out: Path) -> list[dict[str, Any]]:
    rows = []
    for trace_path in sorted(out.glob("*/trace.jsonl")):
        header, steps = load_trace(trace_path)
        rows.append(
            {
                "game_id": header["game_id"],
                "path": trace_path,
                "state": steps[-1]["state"] if steps else header["state"],
                "levels": steps[-1]["levels"] if steps else 0,
                "win_levels": header["win_levels"],
                "actions": len(steps),
                "score": game_score(header["baselines"], actions_per_level(steps)),
            }
        )
    return rows


def report(out: Path) -> None:
    rows = scored_runs(out)
    if not rows:
        print(f"report: no traces under {out}")
        return
    for row in rows:
        print(
            f"{row['game_id']}: {row['state']} · levels {row['levels']}/{row['win_levels']}"
            f" · {row['actions']} actions · score {row['score']:.1f}"
        )
    total = sum(row["score"] for row in rows)
    wins = sum(row["state"] == "WIN" for row in rows)
    print(f"total: {wins}/{len(rows)} wins · mean score {total / len(rows):.2f} (over played games only)")


def promote(out: Path) -> None:
    """Keep the best WIN trace per game in traces/ (higher score, then fewer actions)."""
    best_dir = REPO / "traces"
    best_dir.mkdir(exist_ok=True)
    for row in scored_runs(out):
        if row["state"] != "WIN":
            continue
        base = row["game_id"].split("-")[0]
        target = best_dir / f"{base}.jsonl"
        if target.exists():
            header, steps = load_trace(target)
            held = (game_score(header["baselines"], actions_per_level(steps)), -len(steps))
            if (row["score"], -row["actions"]) <= held:
                continue
        copy2(row["path"], target)
        print(f"promoted {row['game_id']}: score {row['score']:.1f} · {row['actions']} actions -> {target}")


def main() -> None:
    parser = ArgumentParser(description="Run an ARC-AGI-3 sweep, report scores, or promote best traces.")
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("run", help="play games in parallel")
    runner.add_argument("games", nargs="*", help="game ids (default: every locally cached game)")
    runner.add_argument("-j", "--jobs", type=int, default=5, help="parallel games (default: %(default)s)")
    runner.add_argument("-n", "--max-actions", type=int, help="per-game action cap (default: 5 x baseline)")
    runner.add_argument(
        "-m",
        "--model",
        default="gpt-5.6",
        help="model id: gpt-*, claude*, or accounts/fireworks/* (default: %(default)s)",
    )
    runner.add_argument("--warm", action="store_true", help="seed learnings from each model's knowledge")
    runner.add_argument("--seed", metavar="MODEL", help="warm-start every game from another model's knowledge")
    runner.add_argument("--no-images", action="store_true", help="text-only observations (models without vision)")
    runner.add_argument("--knowledge", metavar="NAME", help="knowledge home under knowledge/ (default: the model id)")
    runner.add_argument(
        "--agent",
        metavar="SPEC",
        help="custom agent factory, module:callable or path/to/file.py:callable (default: the arcade agent)",
    )
    runner.add_argument(
        "--effort", metavar="LEVEL", help="reasoning-depth override for the model lane (see arcade.models.get_model)"
    )
    runner.add_argument("--timeout", type=float, default=21600, help="per-game seconds (default: %(default)s)")
    runner.add_argument("--retries", type=int, default=1, help="extra attempts after a crash (default: %(default)s)")
    runner.add_argument("--out", help="output directory (default: runs/<utc timestamp>)")
    for name in ("report", "promote"):
        sub = commands.add_parser(name, help=f"{name} an existing sweep directory")
        sub.add_argument("out", type=Path, help="sweep output directory")
    args = parser.parse_args()
    if args.command == "run" and args.max_actions is not None and args.max_actions < 1:
        parser.error("-n/--max-actions must be positive")
    if args.command == "run":
        sweep(args)
    elif args.command == "report":
        report(args.out)
    else:
        promote(args.out)


if __name__ == "__main__":
    main()
