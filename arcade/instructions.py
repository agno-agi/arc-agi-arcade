"""
Agent Instructions
==================
"""

PLAY_PART = """\
Play this unfamiliar ARC-AGI-3 game until state=WIN. You are scored on action
efficiency: every committed action counts against you, thinking is free. Think
hard, act rarely — every action must either test one clear hypothesis or
execute a step of a verified plan; never wander. The hex text grid is
authoritative (the image is a lossy aid), and the diff line names exactly which
cells changed — "no cells changed" means the action did nothing, which is
strong evidence.\
"""

KERNEL_PART = """\
Between actions, use the stateful Python kernel (execute): imports, variables,
and functions persist across calls, and code is free. Preloaded helpers:
grids() -> int8 array (N+1, 64, 64) of every settled board, where index 0 is
the initial board and index i follows action i; trace() -> the committed
actions with state and levels; diff(a, b) -> changed cells between two boards;
segments(board) -> connected same-color components. Mine your own transitions
to learn mechanics, verify a hypothesis against ALL recorded evidence before
spending actions on it, and once the mechanic is coded, search for a minimal
action plan (e.g. BFS over your transition model) and execute it with
take_action one step at a time, checking each returned frame against the
plan's prediction.\
"""

LEARN_PART = """\
Your conversation resets at every completed level; only saved learnings follow
you. Whenever you establish a durable fact about THIS game — what an action
does, what kills you, how a level's goal is recognized, a verified mechanic —
record it with save_learning immediately, and consult your recalled learnings
before re-deriving anything. Some recalled entries may come from a previous
run of this game: trust them, but cheaply re-verify any that surprise you
before betting many actions on them. Also save falsified hypotheses ("X does NOT do
Y") — negative results prevent your future sessions repeating dead ends — and,
when you complete a level, the solution shape that worked. An automatic
distiller adds entries marked [auto] at each session end; treat them as
first-draft notes and correct any that your own evidence contradicts.\
"""

ENDING_PART = """\
After GAME_OVER, RESET and replay the path you know works, corrected for what
killed you. ACTION1-4 often mean up, down, left, right; ACTION5 often
interacts; ACTION6 clicks a zero-indexed row and column; ACTION7 often undoes —
semantics differ per game, so verify them with cheap probes at each new level.
Never stop to answer while the state is unfinished.\
"""

# Preloaded into the kernel at start; the kernel inherits ARC_RUN_DIR from this process.
KERNEL_SETUP = """\
import json, os
import numpy as np

RUN_DIR = os.environ.get("ARC_RUN_DIR", "")


def grids():
    "All settled boards: (N+1, 64, 64) int8; index 0 = initial, index i = board after action i."
    return np.load(f"{RUN_DIR}/grids.npy")


def trace():
    "Committed actions: dicts of n, action, row, col, state, levels (levels = completed count after the action)."
    lines = open(f"{RUN_DIR}/trace.jsonl").read().splitlines()
    return [json.loads(line) for line in lines[1:] if line.strip()]


def diff(a, b):
    "Changed cells between two boards: list of (row, col, before, after)."
    rows, cols = np.nonzero(a != b)
    return [(int(r), int(c), int(a[r, c]), int(b[r, c])) for r, c in zip(rows, cols)]


def segments(board, background=None):
    "Connected same-color components (4-neighbour): dicts of color, size, bbox (r0, c0, r1, c1), cells."
    seen = np.zeros(board.shape, dtype=bool)
    found = []
    for r0 in range(board.shape[0]):
        for c0 in range(board.shape[1]):
            if seen[r0, c0] or (background is not None and board[r0, c0] == background):
                continue
            color, todo, cells = int(board[r0, c0]), [(r0, c0)], []
            seen[r0, c0] = True
            while todo:
                r, c = todo.pop()
                cells.append((r, c))
                for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if 0 <= nr < board.shape[0] and 0 <= nc < board.shape[1]:
                        if not seen[nr, nc] and board[nr, nc] == color:
                            seen[nr, nc] = True
                            todo.append((nr, nc))
            rows = [r for r, _ in cells]
            cols = [c for _, c in cells]
            found.append({"color": color, "size": len(cells),
                          "bbox": (min(rows), min(cols), max(rows), max(cols)), "cells": cells})
    return found
"""

EXTRACT_PROMPT = """\
From this transcript of an agent playing an unfamiliar ARC-AGI-3 game, extract durable VERIFIED facts
about the game that are NOT already in the manual below: mechanics, action semantics, hazards, how level
goals are recognized, solution shapes that worked, and falsified hypotheses (state them as "X does NOT
do Y"). Output ONLY new one-line bullets in the exact form "- Title: fact (evidence)". No commentary,
no duplicates of the manual, at most 8 bullets; output nothing if there is nothing new and verified.

MANUAL SO FAR:
{manual}

TRANSCRIPT:
{transcript}\
"""
