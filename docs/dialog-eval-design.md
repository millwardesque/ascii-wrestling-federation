# Designing a dialog evaluation framework

How to test narration quality and accuracy the way
[`docs/playtest-rubric.md`](playtest-rubric.md) tests fun. The scoring criteria
live in [`docs/dialog-rubric.md`](dialog-rubric.md); this document explains the
shape of the framework and what it costs to build.

"Dialog" here means every line of match text: the action log today, and the
two-man commentary team on the backlog.

## What carries over from the fun framework

Four things made the playtest framework work, and all four apply unchanged.

**Role separation.** A player agent records, a judge agent scores, an aggregator
batches. The player never self-scores and the judge never touches code. For
dialog we add one role — the deterministic checker — and keep the rest.

**Artifacts, not chat.** JSONL in, schema-validated JSON out, one file per seed.
Findings are diffable, reviewable, and can be regenerated from a seed.

**Two layers.** Cheap deterministic metrics anchor expensive subjective scores.

**Evidence discipline.** Every score cites `(turn, quote)`; low confidence caps
the score at 3. This is what stops a judge from producing vibes.

## What has to change, and why

### 1. Dialog has ground truth, so invert the layer weighting

Fun has no ground truth. No amount of engine instrumentation tells you whether
a match was fun, so Layer 1 is only an anchor and the judge does the real work.

Narration is the opposite. Every line is supposed to describe a state change the
engine already recorded, so most defects are *decidable*: if the text says
"takes 9 damage" and condition fell by 3, the text is wrong. That makes the
deterministic layer the primary instrument and demotes the judge to taste.

This is already built: [`prototype/playtest/dialog_telemetry.py`](../prototype/playtest/dialog_telemetry.py)
cross-checks damage numbers, groggy claims, knockdowns, knockouts, wrestler
identity and placeholder leaks against the `state` snapshots in the same
transcript. Over the 40 committed transcripts it reports **zero accuracy errors**
— the hand-written copy is faithful — and surfaces three real narration debts as
warnings:

| Finding | Count | Example |
|---------|-------|---------|
| `silent_state_change` | 249 | Turn 15 prints `Hitman: Collar-and-elbow tie-up.` while Hall moves `STANDING -> GRAPPLED` and is never mentioned |
| `clamped_number_claim` | 214 | `Hitman takes 5 damage` when condition went 4 → 1 |
| `contradictory_claim` | 135 | `Hall reverses the rebound clothesline — only 2 damage; Hitman whiffs — Hall shrugs it off.` reports contact and a whiff in one line |

None of these need a judge, an API key, or a human. They are the kind of defect
that a rubric-only framework finds slowly and inconsistently.

### 2. The judge must be pointed at what regex cannot see

If you hand an LLM judge the same job the checker does, it will confidently
disagree with arithmetic and burn tokens re-deriving facts. Worse, a naive
narration judge rewards vivid prose — which is exactly the failure mode we care
about, because vivid prose is where hallucination enters.

So the judge charter is narrow: clarity, voice, freshness, escalation, plus one
accuracy-adjacent job that regex genuinely cannot do — **claims that are
consistent with state but were never modelled**. "The referee warns him about the
ropes", "he's going for the title here", "that's the bad shoulder" are all
compatible with any state snapshot and all invented. Those go in
`hallucinated_claims` and cap `fidelity` at 2. Vivid writing earns nothing on
its own; unsupported writing loses points.

### 3. Coverage is over narration sites, not seeds

The fun framework samples by rotating four policies across random seeds, which
works because fun is a property of whole matches. Narration is a property of
individual *lines*, and rare lines are where bugs hide. Across 40 transcripts,
`busted open` appears 8 times and `KNOCKOUT` once — a judge sampling seeds will
essentially never audit them, and a copy change to a rare line can ship broken.

Dialog coverage therefore needs a scenario harness that pins `MatchState` and
the RNG and forces each narration site to fire, then reports which sites were
never exercised. This is the same shape as
[`tests/test_position_coverage.py`](../prototype/tests/test_position_coverage.py),
which already guarantees every position/status combination has a legal move.

### 4. Golden snapshots are possible here

Narration is deterministic given a seed, so a committed corpus of seed → lines
turns any copy change into a reviewable text diff. Fun scores drift and cannot
be snapshotted; narration can. `prototype/playtest/dialog/<seed>.json` plus
`dialog-summary.json` are that baseline today.

## Where gates live

Per-match numbers are noisy: a short match can be carried by three lines. So
`aggregate_dialog_telemetry()` rolls seeds into one verdict, and CI gates on the
batch:

```bash
cd prototype
python3 playtest/record_match.py --seeds 101,102,103,104,105 --output-dir playtest/transcripts
python3 playtest/compute_dialog_telemetry.py --fail-on-gate
```

Two classes of gate, and the distinction matters:

- **Hard gates** — accuracy errors, placeholder leaks, ANSI leaks, foreign
  wrestlers. Zero tolerance, and they pass on `main` today.
- **Ratchets** — flat-line ratio, phrasing diversity, repeat runs. Set just
  outside today's worst observed match so they catch regressions instead of
  failing on arrival. Tighten when the baseline improves; never loosen to land a
  change.

A gate that fails 60% of the time on `main` teaches everyone to ignore it. The
aspirational numbers live in the rubric's target column instead.

## The engine seam this wants

The checker currently reverse-engineers facts out of prose with regexes, because
narration is built from f-strings inside `apply_move` — text and mechanics are
entangled at the point of mutation. That works, and it will keep working as an
independent cross-check, but it has a ceiling: three claim families
(`state.bloodied`, `state.pending_groggy`, `state.pin_bonus_next_cover`) cannot
be verified at all because the transcript never exposes those fields, which is
why `claim_verifiability_ratio` sits at 0.94 rather than 1.0.

The structural fix is for `apply_move` to return **events** alongside its text —
`{"kind": "damage", "actor": 0, "target": 1, "amount": 6}`,
`{"kind": "groggy_applied", "target": 1}` — and for a narration layer to render
those events into lines. Three payoffs:

1. Accuracy checking becomes exact instead of pattern-matched, and the
   `silent_state_change` class of bug disappears by construction: an event with
   no rendered line is a hole the renderer can be made to fail on.
2. The commentary team becomes a rendering choice over a stable event stream
   rather than a rewrite of `apply_move`, which is what the backlog item needs.
3. Per-wrestler and per-commentator voices become data, testable per event kind.

This is the one invasive change in the plan: it touches `apply_move`'s return
contract, `render_fixed.py`, `render_playtest.py` and the transcript schema. It
is worth sequencing after the cheap layers are paying off, not before.

## Build order

1. **Layer 1 checker + baseline** — done. `dialog_telemetry.py`,
   `compute_dialog_telemetry.py`, 23 tests, committed baseline over 40 seeds.
2. **Rubric, report schema, judge skill** — done. `docs/dialog-rubric.md`,
   `docs/dialog-report.schema.json`, `/awf-dialog-judge`.
3. **Scenario coverage harness** — pin state and RNG, force every narration site,
   report unexercised sites. Extends the existing test-only pattern; no engine
   changes.
4. **Fix the three surfaced debts** — replace `Nickname: Move name.` fallbacks
   with real lines, stop claiming clamped damage, split the reverse-and-whiff
   line. Each is a copy change with a metric that moves.
5. **Batch automation** — a `.cursor/automations/dialog-batch.md` mirroring the
   playtest batch template: record, check, judge in parallel, aggregate.
6. **Structured events in `apply_move`** — the seam above, once 1–5 are earning
   their keep.
7. **Commentary team on top of events** — the backlog feature, now with a
   framework that can tell whether it is any good.

## How we know the framework itself works

The same question a judge asks of the game: what is the evidence?

- **False positives:** zero accuracy errors across 40 baseline transcripts. A
  checker that cried wolf on faithful copy would be unusable.
- **True positives:** every error and warning code has a unit test that injects
  the defect into a synthetic transcript and asserts it is caught
  ([`tests/test_dialog_telemetry.py`](../prototype/tests/test_dialog_telemetry.py)).
  That suite is the checker's mutation testing.
- **Regression value:** `TestLiveMatchNarration` plays three seeded matches and
  fails if any line contradicts state, so narration edits to `game.py` are
  checked by `python3 -m unittest discover -s tests -q` with no extra step.
- **Manual spot checks:** the two loudest findings were verified by hand against
  the raw transcripts before the thresholds were set.
