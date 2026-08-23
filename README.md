# ARC-AGI Arcade

An arcade of agents playing [ARC-AGI-3](https://arcprize.org/arc-agi/3).

This repo is a live arcade of [agno](https://github.com/agno-agi/agno) agents playing the ARC-AGI-3 25-game public set. One agent, powered by GPT-5.6 Sol, has beaten the full 25-game public set, all 183 levels, and holds a **100.00 RHAE score** minted by ARC's own server in Competition Mode. Check their [official scorecard](https://arcprize.org/scorecards/7690a5a8-dda4-42c5-8554-b5e480245a83).

![Scoreboard](assets/scoreboard.png)

## Disclaimers

1. All scores are on the public demonstration set: 25 games, 183 levels. ARC-AGI-3's primary basis for evaluation is its private sets, which are harder, out-of-distribution, and not publicly playable; a score here says nothing about them. Nobody has beaten ARC-AGI-3 (as far as we know).
2. The agent runs in two modes. Cold: no prior knowledge; the agent starts every game blank and builds learnings as it plays. Warm: the agent reuses the learnings from its previous runs to improve its performance.
3. Agents can be powered by any model: Gemini, GPT, Claude, DeepSeek, Grok, Mistral, etc.
4. Warm runs of one model can be seeded with the manuals of another model. This is how gemini-3.7-flash-seeded scored so well.
5. Agents get a Python kernel (CodeMode) with real filesystem access, and given one, models will eventually use it broadly: we have observed agents reading a game's source code and human baselines, reading other models' manuals mid-run, and building offline copies of a game to search against — unprompted, across five different models. Runs where this happens are tagged CONTAMINATED on the leaderboard and generally excluded from competition claims.

## Notable Scores

| Player | Score (RHAE) | Levels | Actions | Scorecard |
|---|---|---|---|---|
| GPT-5.6 Sol Cold | 96.15 | 180/183 | 9,422 | [`b0aa052c`](https://arcprize.org/scorecards/b0aa052c-0ad5-41c7-92db-ef8d342d4929) |
| GPT-5.6 Sol Warm | 100.00 | 183/183 | 7,846 | [`7690a5a8`](https://arcprize.org/scorecards/7690a5a8-dda4-42c5-8554-b5e480245a83) |
| Human baseline (ARC's published expert aggregate) | 95.4 | 183/183 | — | — |

## Get started

1. Create your virtual environment: `./scripts/venv_setup.sh`
2. Add your model keys: `cp .env.example .env` and fill in the keys for the players you want,
   plus `ARC_API_KEY` (register at [three.arcprize.org](https://three.arcprize.org)).
3. Download the games: `python play.py setup` (once; no model tokens). Everything after this plays
   fully offline against the local cache.
4. Choose your player, name your run, and play:

```bash
python play.py                            # the players, their records, and every command
python play.py opus-max --run day1        # the Opus player plays the whole board, live in your terminal
python play.py gpt lf52 --cold --run lab  # one game, no prior knowledge: write the manual from scratch
python play.py glm --run day1             # a small open-weight model playing on GPT's manuals
python play.py gpt report                 # score the campaign so far
python play.py gpt chart                  # the scoreboard: board score vs output tokens, from the traces
python play.py gpt compete                # the same campaign, replayed into ONE official scorecard
```

A fresh `--run NAME` plays the whole board from the start, an existing run resumes it.

## How it works

1. We create players like [`players/gpt.py`](players/gpt.py) that specify a model, a knowledge policy, and campaign settings.
2. Players can use the base agent composition or bring their own.
3. The base agent composition ([`arcade/agent.py`](arcade/agent.py)) has:
    - **One game toolkit.** `take_action` commits a single action and returns the observation: a
      `state/levels/actions` header, the authoritative hex grid, and an exact cell-level diff of what the
      action changed (plus a small frame image, for models with vision). Committed actions count against a
      budget of 5× the human baseline.
    - **A Python kernel.** A stateful CodeMode session where code is free, preloaded with the full recorded
      board history — `grids()`, `trace()`, `diff()`, `segments()`. The agent mines its own transitions to
      learn mechanics, verifies hypotheses against all recorded evidence before spending actions, and
      searches for minimal action plans in code.
    - **A learning store.** The agent saves verified facts with `save_learning` as it plays, and a distiller
      adds what it didn't think to save at every session end. The session resets at each completed level —
      only the manual survives, injected into the next session. Manuals live in `knowledge/<name>/<game>.md`;
      warm runs start from them, and `--seed` merges another model's manuals in.
4. Above the agent sits the campaign engine: it plays the whole board in parallel lanes, retries crashes, resumes dead runs from their own recorded actions, and draws the run as the live arcade wall.
5. Every committed action is recorded to a trace: one line per action with a settled-frame hash, token counts, and the git revision that played it. `replay.py` re-plays any trace through a fresh copy of ARC's engine. Scorecards are minted by replaying recorded actions through the ARC API, validated server-side action by action. Raw traces are gitignored as a published trace would be replayable as a forged scorecard.

## Knowledge

Each game the agent plays, it writes a manual: verified mechanics, hazards, falsified hypotheses, solution shapes — saved as it plays, and distilled again at every level boundary. Those manuals live in `knowledge/`, one directory per model — and stay private for the same reason traces do: a manual is a worked solution to a live public game. The manuals make two things possible:

- **Warm starts.** Point a player at its knowledge and it plays with prior knowledge. This is how GPT-5.6 Sol Cold became GPT-5.6 Sol Warm.
- **Knowledge transfer between models.** Knowledge is stored in markdown files, so knowledge written by one model can be used by another.

## License

[MIT](LICENSE)
