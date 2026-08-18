# AGENTS.md

Guidance for future agents working in this repository.

## Project Overview

This is a Python terminal prototype for **ASCII Wrestling Federation**, a turn-based pro wrestling match simulator. The current priority is making the moment-to-moment gameplay fun and readable before expanding scope.

The prototype lives in `prototype/`.

Important files:

- `prototype/main.py`: match loop, CLI args, player/CPU turn flow.
- `prototype/game.py`: match state, hit probability, move resolution, CPU scoring, pins/submissions.
- `prototype/moves.py`: move definitions, position gates, move validation.
- `prototype/render.py`: renderer protocol and shared UI helpers.
- `prototype/render_fixed.py`: current full-screen terminal UI.
- `prototype/wrestlers.py`: roster data; `list_roster()` controls playable roster.
- `prototype/commentators.py`: commentary booth roster and seeded pair selection.
- `prototype/commentary_events.py`: `MatchEvent` contract for future dual-voice rendering.
- `prototype/config.py` and `prototype/config.json`: hot-reloadable tuning config, currently timing values.
- `prototype/tests/`: unit tests.
- `prototype/playtest/`: headless JSONL playtest mode and evaluation telemetry.
- `todo.md`: backlog.

## Evaluation Frameworks

Two tracks share the playtest transcripts:

- **Gameplay:** `playtest/telemetry.py` + `docs/playtest-rubric.md` + `/awf-playtest-judge`.
- **Narration:** `playtest/dialog_telemetry.py` + `docs/dialog-rubric.md` + `/awf-dialog-judge`.
- **Commentary booth (in progress):** `commentators.py` + `docs/commentary-design.md` — pair at bell today; dual-voice move log after events ship from `apply_move`.

Narration accuracy is deterministic, not judged: `dialog_telemetry.py` compares
numeric and state claims in the `log` text against the `state` snapshots in the
same transcript. If you change narration copy in `game.py`, run:

```bash
cd prototype
python3 playtest/compute_dialog_telemetry.py
python3 playtest/narration_coverage.py
```

Any `error`-severity finding means a line now contradicts match state. Variety
gates are ratchets over today's baseline — tighten them when the baseline
improves, never loosen them to land a change.

`narration_coverage.py` reads every narration line out of `game.py` and reports
which ones a transcript corpus exercised. When you add narration, expect the new
site to show up as uncovered until something exercises it. Design notes:
`docs/dialog-eval-design.md`.

## How To Run

From the repo root:

```bash
cd prototype
python3 main.py
```

Skip title/player selection and start a random playable match:

```bash
cd prototype
python3 main.py --random-match
```

Alias:

```bash
python3 main.py --quick-match
```

## Validation Commands

Run these after gameplay or UI changes:

```bash
cd prototype
python3 -m unittest discover -s tests -q
python3 -m py_compile config.py game.py main.py moves.py render.py render_fixed.py wrestlers.py
```

The test suite is intentionally lightweight and should stay fast.

## Current Design Direction

The game recently became more fun after improving:

- curated, intent-labeled player choices instead of dumping every legal move;
- clearer action log text;
- auto-scrolling move log;
- real setup/payoff states like `GRAPPLED`;
- delayed finish sequences for pins and submissions.

Preserve this direction. Prefer small, playable experiments over large rewrites.

## Gameplay Model Notes

Positions live in `BodyPosition`:

- `STANDING`
- `RUNNING_ROPES`
- `GROUNDED`
- `CORNER`
- `TOP_ROPE`
- `GRAPPLED`

`groggy` is not a position. It is a modifier stored separately in `MatchState.groggy`.

`pending_groggy` applies groggy when a grounded wrestler is brought back up, such as via `get_up` or `pickup`.

Grapple model:

- `Collar-and-elbow tie-up` puts the target into `GRAPPLED`.
- Grapple follow-ups require `target_grappled=True`.
- A grappled actor can use `break_grapple` or `grapple_counter`.
- Make sure any new position/status combination still has at least one legal move; `tests/test_position_coverage.py` checks this.

Pins and submissions:

- Pins use precomputed `PinSequence` steps with delayed count output.
- Submissions first roll to **apply** the hold using normal hit probability.
- If the submission is applied, a delayed `Submission attempt...` sequence resolves escape vs tap-out.
- The displayed submission percentage should mean "chance to apply the hold", not "chance to win".

## UI / Renderer Notes

`render_fixed.py` clears and redraws the full terminal. Avoid partial cursor-control tricks unless clearly necessary.

The middle move-log section keeps one current entry per wrestler. New entries should push old lines upward using the auto-scroll logic.

The player move prompt is curated by `_curate_move_choices()`. It should show a small number of clear tactical options:

- `Finish`
- `Big swing`
- `Grapple control`
- `Set up position`
- `Safe offense`
- `Reset / recover`
- `Pressure`

If a move is legally important, ensure curation does not hide it. Example: `Pin` must always be shown when legal.

## Config

Timing values live in `prototype/config.json` and are hot-reloaded through `prototype/config.py`.

Current timing keys:

- `move_gap_between_turns_sec`
- `move_log_scroll_delay_sec`
- `pin_delay_after_count_1_sec`
- `pin_delay_after_count_2_sec`

`get_config()` checks file modification time and keeps the last good config if JSON is invalid. Read config values at the point of use, not at import time, so hot reload keeps working.

## Roster

The full historical roster data may remain in `ROSTER`, but the currently playable roster is controlled by:

```python
PLAYABLE_ROSTER_IDS = ("bret_hart", "scott_hall")
```

in `prototype/wrestlers.py`.

When changing playable wrestlers, update tests only if they depend on playable roster behavior. Many tests use non-playable wrestlers directly to verify wrestler-specific moves.

## Coding Guidelines

- Keep changes narrowly scoped and preserve existing patterns.
- Prefer adding tests for new rules, edge cases, and state combinations.
- Do not remove old wrestler/move data just because it is not currently playable.
- Avoid broad refactors while gameplay feel is being tuned.
- If a move changes position/state behavior, check CPU valid moves and position coverage.
- Be careful with RNG tests; use deterministic stubs or `random.Random(seed)`.
- Do not commit unless explicitly asked.

## Current Backlog Themes

See `todo.md`. Major future areas include:

- weapons;
- fight on the floor;
- stunned state;
- per-wrestler movesets;
- tag-team matches;
- managers/teams;
- replay saving;
- commentary-team style narration;
- documenting algorithms and module seams.
