"""
Replay
======
Validates recorded traces against a fresh engine and, when explicitly requested, replays them into a
Competition Mode scorecard — the step that mints the official score.
"""

from argparse import ArgumentParser
from os import environ
from pathlib import Path

from arc_agi import Arcade
from arc_agi.base import OperationMode
from arcengine import GameAction, GameState
from dotenv import load_dotenv

from arcade.tools import ENVIRONMENTS_DIR
from arcade.traces import actions_per_level, game_score, grid_hash, load_trace

# The engine reads this at reset time; replay must match the play-time semantics (level-scoped RESET).
environ["ONLY_RESET_LEVELS"] = "true"


def replay_trace(arc: Arcade, path: Path, scorecard_id: str | None) -> str:
    """Step one recorded trace through a fresh environment, fail-closed on any divergence."""
    header, steps = load_trace(path)
    game_id = header["game_id"]
    env = arc.make(game_id, scorecard_id=scorecard_id)
    if env is None:
        return f"{game_id}: FAIL could not create environment"
    frame = env.observation_space
    if frame is None:
        frame = env.reset()
    if frame is None or not frame.frame:
        return f"{game_id}: FAIL no initial frame"
    if grid_hash(frame.frame[-1]) != header["hash"]:
        return f"{game_id}: FAIL initial frame differs from the recording (game version drift?)"
    for step in steps:
        move = GameAction[step["action"]]
        data = {"x": step["col"], "y": step["row"]} if move == GameAction.ACTION6 else None
        frame = env.step(move, data=data)
        if frame is None or not frame.frame:
            return f"{game_id}: FAIL no frame after action {step['n']}"
        settled = [frame.state.value, frame.levels_completed, grid_hash(frame.frame[-1])]
        recorded = [step["state"], step["levels"], step["hash"]]
        if settled != recorded:
            return f"{game_id}: FAIL diverged at action {step['n']}: {settled} != {recorded}"
    verdict = "WIN" if frame.state == GameState.WIN else frame.state.value
    score = game_score(header["baselines"], actions_per_level(steps))
    return f"{game_id}: {verdict} · {len(steps)} actions · score {score:.1f}"


def main() -> None:
    parser = ArgumentParser(description="Validate ARC traces locally, or replay them into a Competition scorecard.")
    parser.add_argument("traces", nargs="*", type=Path, help="trace files (default: traces/*.jsonl)")
    parser.add_argument("--competition", action="store_true", help="replay online into one Competition Mode scorecard")
    parser.add_argument(
        "--online", action="store_true", help="dry run: replay online into a throwaway NORMAL scorecard"
    )
    args = parser.parse_args()
    load_dotenv()
    environ["ONLY_RESET_LEVELS"] = "true"  # again: load_dotenv must not override the replay semantics
    paths = args.traces or sorted((Path(__file__).parent.parent / "traces").glob("*.jsonl"))
    if not paths:
        raise SystemExit("no traces found")

    failed = False
    if args.competition:
        # The gate reads the controlling terminal, not stdin: `echo YES | ...` must never mint a scorecard.
        prompt = f"Open a COMPETITION scorecard and replay {len(paths)} trace(s) online? Type YES to proceed: "
        try:
            with open("/dev/tty") as tty:
                print(prompt, end="", flush=True)
                answer = tty.readline()
        except OSError:
            raise SystemExit("refused: --competition needs an interactive terminal (a human must type YES)") from None
        if answer.strip() != "YES":
            raise SystemExit("aborted")
        arc = Arcade(environments_dir=ENVIRONMENTS_DIR, operation_mode=OperationMode.COMPETITION)
        card_id = arc.open_scorecard(tags=["agno"])
        try:
            for path in paths:
                line = replay_trace(arc, path, card_id)
                failed = failed or ": FAIL" in line
                print(line)
        finally:
            arc.close_scorecard(card_id)
            print(f"scorecard closed: https://arcprize.org/scorecards/{card_id}")
    elif args.online:
        arc = Arcade(environments_dir=ENVIRONMENTS_DIR, operation_mode=OperationMode.ONLINE)
        card_id = arc.open_scorecard(tags=["agno-dryrun"])
        print(f"dry-run scorecard open: {card_id}")
        try:
            for path in paths:
                line = replay_trace(arc, path, card_id)
                failed = failed or ": FAIL" in line
                print(line)
        finally:
            scorecard = arc.close_scorecard(card_id)
            print(f"dry-run closed: {card_id} · server score: {getattr(scorecard, 'score', scorecard)}")
    else:
        arc = Arcade(environments_dir=ENVIRONMENTS_DIR, operation_mode=OperationMode.OFFLINE)
        for path in paths:
            line = replay_trace(arc, path, None)
            failed = failed or ": FAIL" in line
            print(line)
    if failed:
        raise SystemExit(1)  # scripts (player compete) must see divergence as failure, not just read it


if __name__ == "__main__":
    main()
