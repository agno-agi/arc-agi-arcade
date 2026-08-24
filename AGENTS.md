# Agno ARC-AGI-3

Minimal ARC-AGI-3 player built on Agno. The engine is the `arcade/` package (installed editable, so no
path hacks anywhere): `agent.py` (the default agent composition — kernel + learning always on — plus
`resolve_agent_factory`, the hook a player uses to bring its own `agent="module:factory"`),
`instructions.py` (the complete system prompt + kernel preload), `models.py` (metered provider models,
`get_model(model_id, meter)` routing, per-provider distillation), `tools.py` (stateful toolkit owning the
ARC environment; the single scored `take_action`), `runner.py` (episode loop + rich console), `traces.py`
(trace format + official RHAE scoring), `learning.py` (file-backed per-model game-knowledge
LearningStore), `knowledge.py` (KNOWLEDGE_ROOT + `knowledge_file`), `sweep.py` (parallel campaign
driver), `replay.py` (fail-closed validation + the YES-gated Competition scorecard mint), `chart.py` (the
scoreboard), `player.py` (Player config + durable campaign engine + arcade wall) and `cli.py` (the play
command: select/commands screens and `setup`). `players/*.py` are ~10-line player configs users copy;
`knowledge/<name>/` holds the agent-written game manuals; `knowledge/`, `runs/`, `traces/`, and
`environment_files/` are all gitignored — a manual is a worked solution to a live public game, so it
stays private for the same reason a trace does. Keep it small — no framework on top of the framework.

## Commands

```bash
./scripts/venv_setup.sh && source .venv/bin/activate    # uv venv + pinned requirements + editable install
python play.py                          # the players, their records, and every command
python play.py setup                    # download the 25 public games (ARC_API_KEY; no model tokens)
python play.py opus --run day1          # the whole board as the Opus player (every outing is named)
python play.py gpt --run day2 --cap 2500    # --cap declares this run's action budget era on the command line
python play.py gpt lf52 --cold --run lab    # one game, no prior knowledge (the agent still learns as it plays)
python play.py opus --seed gpt-5.6 --run x  # warm: own manuals merged with another model's knowledge
python play.py gpt report               # score / draw / mint: report | chart | compete (YES-gated, one shot)
python -m arcade.runner tr87 -n 2       # cheapest smoke test: two actions
python -m arcade.sweep run [games...] -j 6 -n 300       # raw parallel driver
python -m arcade.replay [traces...]     # validate traces offline, fail-closed (--competition mints)
python -m pytest tests/                 # 42 tests with the game cache; engine tests skip without it
./scripts/format.sh && ./scripts/validate.sh            # ruff format + ruff check + mypy (CI runs these)
./scripts/generate_requirements.sh [upgrade|<pkg>]      # regenerate requirements.txt after pyproject edits
```

Model lanes (`models.py::get_model`): `gpt-*` → OpenAI Responses (max reasoning, flex tier), `claude*` →
Anthropic (effort max by default, prompt caching), `accounts/fireworks/*` → Fireworks OpenAI-compatible chat (the
open-weight lanes; aggregator routing is deliberately unsupported). Runs cost provider tokens — always
use `-n` for experiments. Config flows as explicit arguments everywhere — Player fields → sweep flags →
runner flags → `create_agent(game, model, knowledge, warm, seeds, effort)` (or the player's own `--agent`
factory, resolved fail-fast before any token is spent) and `ArcadeTools(images=...)`; the
sole config-bearing env var is ARC_RUN_DIR, which the kernel subprocess genuinely needs.

## How it fits together

- `ArcadeTools.take_action` is the only scored tool. It validates the action against the frame's legal
  set, steps the env, counts actions, and returns the next observation: a `state/levels/actions/legal`
  header, the authoritative hex grid, an exact cell diff, and (unless `images=False`, the text-only lane)
  a PNG of the frame. `stop_after_tool_call` ends the run on WIN and when the budget is spent.
- Budget: `5 * sum(baseline_actions)` committed actions, capped by `-n`/player `cap`; rejected calls are
  free but total calls stop at 2× budget. A run dir whose summary says WIN refuses a new trace writer —
  banked evidence cannot be truncated.
- `runner.play` loops episodes until WIN or budget; each completed level starts a fresh session and only
  saved learnings carry forward. Learnings live in `knowledge/<name>/<game>.md` (`arcade/knowledge.py`);
  the home is `--knowledge NAME`, defaulting to the model id's last path segment. `--warm` seeds from the
  player's own knowledge; `--seed` merges OTHER models' knowledge after it (exact-line dedupe). Cold runs
  read nothing but still write their discoveries — every run contributes, only warm runs consume.
- With ARC_RUN_DIR set, every committed action lands in `trace.jsonl` (header + one hash-stamped line per
  action with cumulative token counts) and `summary.json` tracks progress. Best WIN traces are promoted
  by score, then fewer actions.
- `Player.compete` normalizes game ids to base form, refuses on any missing/invalid WIN trace or a
  partial game cache, validates offline fail-closed, then hands the same traces to
  `replay.py --competition` — whose YES gate reads /dev/tty (one scorecard, whole board, human-only).
  `--dry-run` rehearses into a throwaway NORMAL scorecard. Stopping a campaign kills the whole process
  group; a pidfile prevents two campaigns sharing a run dir.
- `ONLY_RESET_LEVELS=true` (set before env creation) scopes RESET to the current level everywhere,
  including replays.

## Conventions

- ruff (E, F, I, UP; 120 cols) and mypy (`check_untyped_defs`) must pass; `tmp/` and `environment_files/`
  are excluded scratch/cache and gitignored.
- `requirements.txt` is generated — never hand-edit.
- agno is pinned to 3.0.0a3 and arc-agi/arcengine are young: read the installed source in
  `.venv/lib/python3.12/site-packages/{agno,arc_agi,arcengine}` rather than trusting memory.
- Honesty invariants: human baselines are never shown to the agent; no game-specific code or prompts in
  the harness; manuals are agent-written only; raw traces stay private (the scorecard is the public
  receipt); cold and warm results are always labeled as such.
