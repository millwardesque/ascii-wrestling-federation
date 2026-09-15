# Turn-Queue (CTB) Prototype

A self-contained experiment: what happens to AWF if you delete fixed you-then-me
alternation and replace it with an FFX-style conditional turn queue?

This is a sibling to [`prototype/`](../prototype/), not a replacement. Nothing in that
directory changes. The two are not comparable by telemetry and are not meant to be
merged; this one exists to answer whether variable turn order makes the moment-to-moment
game better before anybody commits to it.

## How to run

```bash
cd prototype-turnqueue
python3 main.py                  # title screen and wrestler select
python3 main.py --random-match   # skip straight into a match
```

Validation:

```bash
python3 -m unittest discover -s tests -q
python3 -m py_compile config.py game.py main.py moves.py render.py \
    render_fixed.py render_playtest.py scheduler.py wrestlers.py
python3 playtest/run_seed_range.py 1 20 --policy-seed 42
```

## The model

Each wrestler holds a position on a virtual timeline. Whoever sits lowest acts next.
After acting they are pushed forward by `tempo cost / effective speed`:

```
delay = move.tempo_cost * 10 / effective_speed
```

There is no wall clock. The timeline is a float counter, so headless playtests stay
instant and fully seed-reproducible, and the input model is unchanged — CTB is entirely
discrete, so `terminal_keys.py` is copied verbatim and input still blocks.

Three things feed `effective_speed`, all tunable:

- **Agility**, compressed. Raw roster agility spans 6-15. Used directly as a rate that is
  a 2.5x action advantage, which no amount of damage tuning survives, so it becomes
  `base + (agility - 10) * per_point` — about a 1.37x spread across the roster.
- **Condition**, so a worn-down wrestler acts less often. This is the structural fix for
  the failure mode where somebody sits at single-digit HP and the match cannot end.
- **Position**, so `GROUNDED` is genuinely slow. This is what creates the cover window.

`scheduler.py` is the only genuinely new module and the only one with no dependency on
the rest of the game. It holds `TurnQueue`, the speed calculation, and two projections:
`project_order` for the UI strip and `project_with_choice` for "what happens if I commit
to *this* move", which is what makes the system legible rather than mysterious.

## What the timeline let us delete

Two mechanics in `prototype/game.py` exist only to paper over fixed alternation, and both
are gone here.

**`cover_heat_lock`.** Its own comment admitted the hack: *"First rise attempt after cover
heat always fails so the pin window isn't a coin flip."* Under alternation a downed
wrestler was guaranteed to act next, so the only way to have a pin window at all was to
rig the first get-up. Now a knockdown shoves the victim down the timeline
(`_KNOCKDOWN_HEAD_START`) and being grounded slows them, so the window is earned. The
`_COVER_HEAT_GET_UP_PENALTY` and the `p = min(p, 0.08)` clamp in `hit_probability` went
with it, and rising is an honest roll again.

**`groggy_skip_turn`**, along with the `valid_rules()` early return of `[]`. Losing a turn
outright is the bluntest possible stun and it produced dead player turns. Groggy now costs
speed (`groggy_speed_mult`) and restricts the menu to escapes, so a wobbly wrestler still
gets to act — just worse, and later.

Everything else with a duration moved from counting actions to holding a deadline:

| Was | Is |
| --- | --- |
| `groggy_opponent_actions_left` (starts at 2) | `groggy_until` |
| `pin_bonus_next_cover` meaning "your next action" | `finisher_echo_until`, a window you have to win the race to |
| `finisher_shock` decaying per action | decays per `_FINISHER_SHOCK_DECAY_INTERVAL` of timeline |
| `get_up_fail_streak` decaying per action | decays per `_GET_UP_FAIL_DECAY_INTERVAL` |
| loop debt decaying per action | decays per `_LOOP_PRESSURE_DECAY_INTERVAL` |

`advance_to(state, clock)` expires all of it, once per action, after the queue picks an
actor and before their menu is built — so what the menu says and what resolution does
cannot disagree.

## Making tempo legible

A turn queue the player cannot see is just unexplained randomness. Two additions carry it:

A **NEXT UP strip** under the wrestler panel, fed by `project_order`, so a flurry is
visible before you cause it:

```
NEXT UP  ▸ Hall  ·  Hall  ·  YOU  ·  Hall  ·  YOU
```

A **tempo tag on every menu row**, next to the landing odds. Line-based terminals have no
highlight state, so annotating each row is the way to put the cost-versus-payoff tradeoff
at the point of decision:

```
  Big swing
    3. Vertical suplex  [64%] · slow — they get 2
       TARGET GROGGY payoff: heavy damage is available now
```

Across a 40-seed sweep, 62% of player decision points show more than one distinct tempo
tag, so the annotation is usually carrying real information rather than decoration.

The CPU scores **per unit of recovery** rather than per action, and pays an explicit
penalty per opponent action conceded while it recovers. Without that it would be blind to
exactly the decision the whole system is about.

## Tuning knobs

Hot-reloadable, in [`config.json`](config.json) under `tempo`:

| Key | Default | Effect |
| --- | --- | --- |
| `speed_base` | `10.0` | Speed of an average (agility 10) wrestler. |
| `speed_per_agility_point` | `0.35` | How much agility matters. Raising this toward 1.0 recreates the degenerate spread. |
| `condition_slow_floor` | `0.55` | Speed multiplier at zero condition. Lower ends matches faster. |
| `grounded_speed_mult` | `0.60` | Size of the cover window. |
| `corner_speed_mult` | `0.85` | |
| `grappled_speed_mult` | `0.90` | |
| `groggy_speed_mult` | `0.70` | How much groggy costs now that it no longer deletes a turn. |
| `min_speed` | `2.0` | Floor so stacked penalties cannot strand a wrestler. |
| `queue_preview_depth` | `5` | Length of the NEXT UP strip. |

Not hot-reloadable, and the ones most worth touching first:

- `moves.py`: `_TEMPO_PER_DIFFICULTY`, `_TEMPO_PER_DAMAGE`, and the `TEMPO_COST_MIN` /
  `TEMPO_COST_MAX` clamp derive a cost for every move that does not set `tempo_cost`
  itself. Finishers, top-rope dives, `climb`, `pin`, strikes, and resets set theirs
  explicitly, because those are the ones where tempo is the point.
- `game.py`: `_GROGGY_DURATION`, `_FINISHER_ECHO_DURATION`, `_KNOCKDOWN_HEAD_START`, and
  the three decay intervals.
- `game.py`: `_CPU_CONCESSION_PENALTY` controls how tempo-averse the CPU is;
  `_CPU_TEMPO_REFERENCE_COST` renormalises score-per-tempo so the existing softmax
  temperature keeps meaning what it meant.
- `render_fixed.py`: `_MENU_CONCESSION_PENALTY` is the same idea for menu ordering.
- `scheduler.py`: `_DELAY_SCALE` sets the unit of the timeline. At the default, one
  baseline-cost action by an average wrestler advances the clock by about 1.0.

## Playtest and telemetry

Same shape as the alternating prototype, with the action as the unit instead of the round,
since the two wrestlers no longer act the same number of times. Each transcript record
carries `sim_time`, `actor_speed`, and `tempo_cost`, and each menu row carries its own
`tempo_cost` and `conceded`.

```bash
python3 playtest/record_match.py --seed 101 --telemetry
python3 playtest/run_seed_range.py 1 20 --policy-seed 42
python3 playtest/compute_telemetry.py
```

The metrics that are the actual point of the experiment:

- **`consecutive_action_max`** — did flurries happen? A run where this never exceeds 1
  means the scheduler is doing nothing and the whole prototype is a no-op.
- **`actions_player` / `actions_cpu` / `action_ratio`** — is tempo varying without anyone
  being locked out?
- **`sim_time_total`** alongside the action count.
- **`mean_conceded_player`** — how much initiative the player actually gave away.

The `[8, 40]` pacing gate from `prototype/` is in shared turns and has no meaning here, so
it is rebaselined to `[10, 70]` actions against this corpus rather than carried over.
Existing transcripts and reports in `prototype/playtest/` are untouched and
non-comparable by design.

There is a `tempo` player policy alongside the ported four: always take the best move that
does not concede the initiative. It exists so at least one policy exercises the queue
rather than the intent labels.

## Known risks and open questions

Things a follow-up should look at, in rough order of how much they matter:

1. **Loop debt is still earned per event.** It now *decays* on elapsed timeline, so a fast
   wrestler no longer sheds staleness twice as fast — but they still accrue it twice as
   fast for the same span of match time. Making the increments time-weighted is the
   obvious next step and was deliberately deferred.
2. **The `tempo` policy is close to a turtle strategy.** It produces the longest matches
   in the corpus and owns the one seed (17, at 77 actions) that fails the pacing band.
   That gate is left failing rather than widened, because a player who never commits to
   anything probably *should* be punished by the design and currently is not.
3. **Tempo tags are flat at 38% of decision points.** Usually because the opponent is
   imminently due no matter what you pick, which is true information but reads as noise.
   Worth revisiting if the strip and the per-row tag turn out to be redundant in practice.
4. **Speed is read post-move for recovery.** Ending an exchange face-down makes getting
   back into the match slower, which is thematically right but stacks with the grounded
   penalty on the next action. Watch for it being too punishing.

## Deliberately out of scope

The commentary engine (`commentary.py`, `commentary_templates.py`, `commentators.py`),
dialog telemetry, narration coverage, and both LLM judge rubrics are not ported. The
renderer uses the plain `result.log` text.

`commentary_events.py` and the existing `emit()` calls in `apply_move` are kept: they cost
nothing, avoid a pile of risky edits in ported code, and the event stream is useful for
flurry detection.
