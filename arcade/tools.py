"""
Environment Toolkit
===================
Turns ARC frames and actions into one stateful Agno tool loop.
"""

from io import BytesIO
from json import JSONDecodeError, loads
from os import environ
from pathlib import Path
from subprocess import DEVNULL, check_output
from typing import Any, Literal

from agno.media import Image
from agno.tools import Toolkit
from agno.tools.function import FunctionCall, ToolResult
from arc_agi import Arcade
from arc_agi.rendering import frame_to_rgb_array
from arcengine import GameAction, GameState
from numpy import ndarray, nonzero, save, stack
from PIL import Image as PILImage

from arcade.traces import TraceWriter, grid_hash, write_json

# Keep RESET scoped to the current level so completed progress is preserved. Side effect: arc_agi's in-process
# scorecard never opens a card under this flag (Arcade.get_scorecard() stays empty); the toolkit counts actions itself.
environ["ONLY_RESET_LEVELS"] = "true"
# arc_agi resolves its game cache against the CWD; anchor it to the repo root unless ENVIRONMENTS_DIR says otherwise.
ENVIRONMENTS_DIR = environ.get("ENVIRONMENTS_DIR", str(Path(__file__).parent.parent / "environment_files"))

Action = Literal["RESET", "ACTION1", "ACTION2", "ACTION3", "ACTION4", "ACTION5", "ACTION6", "ACTION7"]


def _revision() -> str:
    """The harness git revision, stamped into every trace header so each run self-documents its code."""
    try:
        repo = Path(__file__).parent.parent
        return check_output(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], text=True, stderr=DEVNULL).strip()
    except Exception:  # noqa: BLE001 — provenance must never block play (e.g. a non-git checkout)
        return "unknown"


REVISION = _revision()


class ArcadeTools(Toolkit):
    """Owns the ARC environment: one scored take_action tool, observations, budgets, and the trace."""

    def __init__(self, game_id: str, resume: Path | None = None, images: bool = True) -> None:
        self.env = Arcade(environments_dir=ENVIRONMENTS_DIR).make(game_id)
        if self.env is None:
            raise RuntimeError(f"Could not load ARC game {game_id!r}")
        self.frame = self.env.observation_space
        if self.frame is None:
            raise RuntimeError(f"ARC game {game_id!r} did not start")
        baselines = self.env.info.baseline_actions
        if not baselines:
            raise RuntimeError(f"ARC game {game_id!r} has no action baselines")
        self.action_budget = 5 * sum(baselines)
        self.run_budget = self.action_budget  # committed actions allowed this run; the runner may lower it
        self.actions = 0  # committed actions
        self.tool_calls = 0  # every call, including rejected ones; capped at 2x the action budget
        self.recent: list[str] = []  # compact per-action recap, for resuming a run with fresh model context
        # Cumulative across every model call, fed by the meter. "cached" is the billing question: input
        # billed at the cache-read discount vs full price; "reason" splits thinking out of output.
        self.tokens = {"in": 0, "out": 0, "total": 0, "cached": 0, "reason": 0}
        self.episode_per_level = False  # end the episode when a level completes (fresh context per level)
        header = {
            "game_id": self.env.info.game_id,
            "revision": REVISION,
            "win_levels": self.frame.win_levels,
            "baselines": list(baselines),
            "state": self.frame.state.value,
            "levels": self.frame.levels_completed,
            "hash": grid_hash(self.grid),
        }
        self.grids = [self.grid.copy()]  # every settled board; index i = board after action i (0 = initial)
        steps = self._resume(resume) if resume is not None else []
        # With ARC_RUN_DIR set, every committed action is recorded to trace.jsonl (the replayable evidence),
        # summary.json tracks live progress, and grids.npy mirrors the board history for the code kernel.
        # File-only: the console belongs to the runner.
        self.images = images  # False: text-only observations for models without vision
        self.run_dir = Path(environ["ARC_RUN_DIR"]) if "ARC_RUN_DIR" in environ else None
        self.trace: TraceWriter | None = None
        if self.run_dir is not None:
            summary_path = self.run_dir / "summary.json"
            if resume is None and summary_path.exists() and loads(summary_path.read_text()).get("state") == "WIN":
                # A banked WIN trace is evidence bought with tokens; opening the writer would truncate it.
                raise RuntimeError(f"{self.run_dir} already holds a WIN; refusing to overwrite (use a fresh dir)")
            self.trace = TraceWriter(self.run_dir / "trace.jsonl", header)  # rewrites: self-heals a torn tail
            for step in steps:
                self.trace.append(step)
            self._save_grids()
        super().__init__(name="arcade", tools=[self.take_action])

    def _save_grids(self) -> None:
        if self.run_dir is None:
            return
        temp = self.run_dir / "grids.npy.tmp"
        with temp.open("wb") as file:
            save(file, stack(self.grids))
        temp.replace(self.run_dir / "grids.npy")

    def _resume(self, path: Path) -> list[dict[str, Any]]:
        """Replay a recorded trace through the fresh environment, fail-closed, and adopt its progress."""
        records: list[dict[str, Any]] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                records.append(loads(line))
            except JSONDecodeError:
                break  # torn tail from a killed process; resume from the last intact action
        if not records or records[0].get("game_id") != self.env.info.game_id:
            raise RuntimeError(f"resume trace {path} does not match game {self.env.info.game_id!r}")
        steps = records[1:]
        if steps and "tok_total" in steps[-1]:  # token stamps continue across process restarts
            # Update in place: older traces predate some keys, and meter() addresses every key.
            self.tokens["out"] = steps[-1]["tok_out"]
            self.tokens["total"] = steps[-1]["tok_total"]
            self.tokens["cached"] = steps[-1].get("tok_cached", 0)
            self.tokens["reason"] = steps[-1].get("tok_reason", 0)
        for step in steps:
            move = GameAction[step["action"]]
            data = {"x": step["col"], "y": step["row"]} if move == GameAction.ACTION6 else None
            frame = self.env.step(move, data=data)
            if frame is None or not frame.frame:
                raise RuntimeError(f"resume replay lost the frame at action {step['n']}")
            self.frame = frame
            if grid_hash(self.grid) != step["hash"]:
                raise RuntimeError(f"resume replay diverged at action {step['n']}")
            self.actions += 1
            self.recent.append(self._recent_entry(move, step["row"], step["col"]))
            self.grids.append(self.grid.copy())
        return steps

    def meter(self, metrics: Any) -> None:
        """Accumulate one model response's usage; called by the model layer for every provider call."""
        self.tokens["in"] += metrics.input_tokens or 0
        self.tokens["out"] += metrics.output_tokens or 0
        self.tokens["total"] += metrics.total_tokens or 0
        self.tokens["cached"] += getattr(metrics, "cache_read_tokens", 0) or 0
        self.tokens["reason"] += getattr(metrics, "reasoning_tokens", 0) or 0

    def _recent_entry(self, action: GameAction, row: int | None, col: int | None) -> str:
        entry = f"{self.actions}:{action.name}"
        if action == GameAction.ACTION6:
            entry += f"(r{row},c{col})"
        if self.frame.state == GameState.GAME_OVER:
            entry += ":DEAD"
        return entry + f":L{self.frame.levels_completed}"

    def recap(self, last: int = 30) -> str:
        """Recent committed actions as 'n:ACTION[:DEAD]:Llevels', oldest first."""
        return " ".join(self.recent[-last:]) or "none yet"

    def _record(self, action: GameAction, row: int | None, col: int | None) -> None:
        if self.trace is None or self.run_dir is None:
            return
        coords = (row, col) if action == GameAction.ACTION6 else (None, None)
        self.trace.append(
            {
                "n": self.actions,
                "action": action.name,
                "row": coords[0],
                "col": coords[1],
                "state": self.frame.state.value,
                "levels": self.frame.levels_completed,
                "hash": grid_hash(self.grid),
                "tok_out": self.tokens["out"],
                "tok_total": self.tokens["total"],
                "tok_cached": self.tokens["cached"],
                "tok_reason": self.tokens["reason"],
            }
        )
        write_json(
            self.run_dir / "summary.json",
            {
                "game_id": self.env.info.game_id,
                "state": self.frame.state.value,
                "levels": self.frame.levels_completed,
                "win_levels": self.frame.win_levels,
                "actions": self.actions,
                "budget": self.run_budget,
            },
        )

    def _legal_actions(self) -> list[GameAction]:
        if self.frame.state == GameState.WIN:
            return []
        if self.frame.state == GameState.GAME_OVER:
            return [GameAction.RESET]
        return [GameAction.RESET] + [
            GameAction.from_id(action_id) for action_id in self.frame.available_actions if action_id != 0
        ]

    @property
    def grid(self) -> ndarray:
        if not self.frame.frame:
            raise RuntimeError("ARC returned no frame")
        # Frames are chronological (animation steps); the last one is the settled board, in terminal states too.
        return self.frame.frame[-1]

    @staticmethod
    def _diff(before: ndarray, after: ndarray) -> str:
        """Exact cell changes between settled frames: the model's strongest mechanics signal."""
        if before.shape != after.shape:
            return "diff: full frame replaced"
        changes = list(zip(*nonzero(before != after)))
        if not changes:
            return "diff: no cells changed"
        shown = " ".join(f"r{r:02d}c{c:02d}:{int(before[r, c]):x}>{int(after[r, c]):x}" for r, c in changes[:48])
        extra = f" +{len(changes) - 48} more" if len(changes) > 48 else ""
        return f"diff: {len(changes)} cells changed · {shown}{extra}"

    def observation(self, diff: str = "") -> ToolResult:
        grid = self.grid
        rows = "\n".join(
            f"r{r:02d} "
            + " ".join("".join(f"{int(cell):x}" for cell in row[c : c + 8]) for c in range(0, grid.shape[1], 8))
            for r, row in enumerate(grid)
        )
        image = None
        if self.images:
            output = BytesIO()
            PILImage.fromarray(frame_to_rgb_array(self.actions, grid, scale=6)).save(output, "PNG")
            image = [Image(content=output.getvalue(), mime_type="image/png", detail="low")]
        legal = ", ".join(action.name for action in self._legal_actions()) or "none; stop"
        if self.actions >= self.run_budget and self.frame.state == GameState.NOT_FINISHED:
            legal = "none; action budget exhausted, stop"
        return ToolResult(
            content=(
                f"state={self.frame.state.value}; levels={self.frame.levels_completed}/{self.frame.win_levels}; "
                f"actions={self.actions}/{self.run_budget}; legal={legal}\n"
                + (f"{diff}\n" if diff else "")
                + "Rows and columns are zero-indexed. Columns are grouped as "
                "00-07 08-15 16-23 24-31 32-39 40-47 48-55 56-63. Cells are hex colors 0-f.\n"
                f"{rows}"
            ),
            # The text grid is authoritative; the image is a cheap layout aid (detail low keeps
            # context small). Text-only models play from the hex grid alone.
            images=image,
        )

    def take_action(
        self,
        action: Action,
        fc: FunctionCall,
        row: int | None = None,
        col: int | None = None,
    ) -> ToolResult:
        """Commit one scored action. Row and col are used only by ACTION6 and must be between 0 and 63."""
        self.tool_calls += 1
        if self.tool_calls >= 2 * self.run_budget:
            fc.function.stop_after_tool_call = True
        if self.frame.state == GameState.WIN:
            fc.function.stop_after_tool_call = True
            return ToolResult(content="state=WIN; the game is complete; stop calling tools")
        move = GameAction.__members__.get(action.upper())
        legal = self._legal_actions()
        if move not in legal:
            return ToolResult(content=f"Illegal action. Legal actions: {', '.join(a.name for a in legal)}")
        if move == GameAction.ACTION6 and (row is None or col is None or not (0 <= row <= 63 and 0 <= col <= 63)):
            return ToolResult(content="ACTION6 requires row and col between 0 and 63")
        # ARC uses x=column and y=row.
        previous, levels_before = self.grid, self.frame.levels_completed
        frame = self.env.step(move, data={"x": col, "y": row} if move == GameAction.ACTION6 else None)
        if frame is None or not frame.frame:
            fc.function.stop_after_tool_call = True
            return ToolResult(
                content=f"ARC returned no observation after {move.name}; stop because commit status is unknown"
            )
        self.actions += 1
        self.frame = frame
        self.recent.append(self._recent_entry(move, row, col))
        self.grids.append(self.grid.copy())
        self._save_grids()
        self._record(move, row, col)
        if frame.state == GameState.WIN or self.actions >= self.run_budget:
            fc.function.stop_after_tool_call = True
        if frame.levels_completed > levels_before and self.episode_per_level:
            fc.function.stop_after_tool_call = True  # the runner starts the next level as a fresh episode
        return self.observation(diff=self._diff(previous, self.grid))
