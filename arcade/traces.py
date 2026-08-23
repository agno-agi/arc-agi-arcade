"""
Traces
======
Records committed actions as append-only JSONL and scores traces with the official RHAE formula.
"""

from hashlib import sha256
from json import dumps, loads
from os import replace
from pathlib import Path
from typing import Any, TextIO

from numpy import ascontiguousarray, ndarray

LEVEL_SCORE_CAP = 115.0  # per-level ceiling: min((baseline/actions)^2, 1.15) as a percentage


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------
def grid_hash(grid: ndarray) -> str:
    """Digest of a settled frame, stable across dtypes and processes."""
    cells = ascontiguousarray(grid).astype("int16")
    return sha256(repr(cells.shape).encode() + cells.tobytes()).hexdigest()[:16]


class TraceWriter:
    """One JSONL file per run: a header line, then one line per committed action."""

    def __init__(self, path: Path, header: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO = path.open("w")
        self.append(header)

    def append(self, record: dict[str, Any]) -> None:
        self._file.write(dumps(record) + "\n")
        self._file.flush()


def write_json(path: Path, record: dict[str, Any]) -> None:
    """Crash-safe JSON snapshot (temp file, then atomic rename)."""
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(dumps(record, indent=1))
    replace(temp, path)


# ---------------------------------------------------------------------------
# Scoring (mirrors https://docs.arcprize.org/methodology)
# ---------------------------------------------------------------------------
def load_trace(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    header, *steps = [loads(line) for line in path.read_text().splitlines() if line.strip()]
    return header, steps


def actions_per_level(steps: list[dict[str, Any]]) -> list[int]:
    """Actions charged to each completed level in order; the unfinished tail level is dropped."""
    completed: list[int] = []
    count = 0
    for step in steps:
        count += 1
        while step["levels"] > len(completed):
            completed.append(count)
            count = 0
    return completed


def level_score(baseline: int, actions: int) -> float:
    """Official per-level score; a level completed as a side effect (0 own actions) earns the cap."""
    if actions <= 0:
        return LEVEL_SCORE_CAP
    return min((baseline / actions) ** 2 * 100.0, LEVEL_SCORE_CAP)


def game_score(baselines: list[int], per_level: list[int]) -> float:
    """Weighted by 1-indexed level number over ALL levels; incomplete levels score zero. Capped at the
    completion ceiling (100 x weight share of completed levels, so 5/10 levels can never exceed 27.27)
    and at 100 — matching the official scorecard's "max achievable from completed levels" rule."""
    weights = range(1, len(baselines) + 1)
    weighted = sum(w * level_score(b, a) for w, (b, a) in zip(weights, zip(baselines, per_level)))
    ceiling = 100.0 * sum(range(1, len(per_level) + 1))
    return min(weighted, ceiling) / sum(weights)
