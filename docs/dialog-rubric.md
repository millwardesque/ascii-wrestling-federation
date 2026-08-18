# AWF Dialog Rubric

`rubric_version: 2026-08-18`

Evaluation criteria for match narration — the action-log text today, the
two-man commentary team later. Companion to [`docs/playtest-rubric.md`](playtest-rubric.md),
which scores gameplay. Design rationale lives in
[`docs/dialog-eval-design.md`](dialog-eval-design.md).

Judges score from **JSONL transcripts** plus **dialog telemetry JSON** only —
never from full-screen ANSI output.

## Orchestration rule

> Narration accuracy is decided by [`prototype/playtest/dialog_telemetry.py`](../prototype/playtest/dialog_telemetry.py),
> not by a judge. A judge that disagrees with the state snapshots is wrong.
> Judges score taste: clarity, voice, freshness, escalation.

Split roles, same shape as the playtest framework:

1. **Player agent** — records transcripts (`/awf-playtest-player`). Unchanged.
2. **Layer 1 checker** — `python3 playtest/compute_dialog_telemetry.py`. Deterministic.
3. **Judge agent** — `/awf-dialog-judge`. Reads transcript + dialog telemetry, writes report JSON. No code changes.
4. **Aggregator** — `aggregate_dialog_telemetry()` rolls per-match numbers into the batch verdict that CI gates on.

---

## Layer 1: Deterministic accuracy (no LLM judgment)

Every line the game prints is supposed to describe a state change the engine
recorded, so most narration defects are decidable. Layer 1 cross-checks `log`
text against the `state` snapshots in the same transcript.

### Findings are graded, not pooled

| Severity | Meaning | Effect |
|----------|---------|--------|
| `error` | Text asserts something state contradicts | Hard gate failure |
| `warning` | Text is contradictory, stale, flat, or off-vocabulary | Tracked; drives the backlog |
| `info` | Claim cannot be checked because the transcript lacks the field | Recorded in `accuracy.schema_gaps` |

### Error codes

| Code | Trigger |
|------|---------|
| `number_mismatch` | Claimed damage/healing does not equal the condition delta |
| `phantom_damage_claim` | Damage claimed, no condition lost |
| `unnarrated_condition_change` | Condition changed with no line describing it |
| `groggy_claim_unsupported` | Text says groggy, state says not groggy |
| `groggy_clear_unsupported` | Text says shaken off, state still groggy |
| `grounded_claim_unsupported` | Text puts a wrestler on the mat, position disagrees |
| `knockout_claim_unsupported` | "Out cold" with condition remaining |
| `foreign_wrestler_named` | A roster nickname from outside this match appears |
| `template_leak` | Unsubstituted placeholder or `None` in player-facing text |
| `ansi_in_transcript` | Escape codes leaked into narration |

### Warning codes

| Code | Trigger |
|------|---------|
| `silent_state_change` | A wrestler's position or groggy flag changed and no line names them |
| `clamped_number_claim` | "Takes 9 damage" when only 3 was applied after clamping |
| `contradictory_claim` | One line reports both contact damage and a whiff |
| `stale_groggy_claim` | "Still wobbly" on the turn groggy cleared |
| `lexicon_violation` | Reserved vocabulary from [`CONTEXT.md`](../CONTEXT.md) (`HP`, `stunned`, `star power`, …) |
| `line_too_long` | Wider than the move-log budget |

Ambiguous flavour words are deliberately **not** linted. `heat` and
`confidence` appear in shipped copy on purpose; only unambiguous engine jargon
and competing mechanic names are flagged.

### Quality metrics

| Metric | Why it matters |
|--------|----------------|
| `variety.flat_line_ratio` | Share of lines that are the bare `Nickname: Move name.` fallback — narration that describes nothing |
| `variety.phrasing_diversity` | Distinct sentence shapes / lines, after names, numbers **and move names** are normalised away |
| `variety.top_phrasing_share` | How much of the match one sentence shape carries |
| `variety.max_consecutive_repeat` | Longest run of the same shape; a stuck record |
| `variety.unique_line_ratio` | Surface variety, kept for continuity with playtest telemetry |
| `readability.max_line_chars` | Move-log wrap budget |
| `accuracy.claim_verifiability_ratio` | Share of state claims Layer 1 can actually check; below 1.0 means the transcript schema is behind the copy |

`phrasing_diversity` is the honest variety number. `unique_line_ratio` counts
`… snaps off roundhouse kick …` and `… snaps off missile dropkick …` as two
different lines; `phrasing_diversity` sees one sentence the game can say.

### Gates: ratchets, not aspirations

Per-match numbers swing wildly because a short match can be carried by three
lines. **Gate on the batch medians.** Thresholds sit just outside today's worst
observed match so they catch regressions rather than fail on arrival.

| Metric | Baseline (40 seeds) | Batch gate | Target |
|--------|--------------------|------------|--------|
| accuracy `errors` | 0 | 0 | 0 |
| median `flat_line_ratio` | 0.31 | ≤ 0.35 | ≤ 0.15 |
| median `phrasing_diversity` | 0.27 | ≥ 0.22 | ≥ 0.40 |
| median `max_consecutive_repeat` | 3 | ≤ 4 | ≤ 3 |
| `contradictory_claim` count | 135 | — | 0 |
| `silent_state_change` count | 249 | — | 0 |
| median `claim_verifiability_ratio` | 0.94 | — | 1.0 |

Tighten a ratchet whenever the baseline improves. Never loosen one to make a
change land.

---

## Layer 2: Rubric dimensions

Use **1–5**. Every score needs evidence citing `(turn, quote)`. Cap a score at
**3** when `confidence` is `low`.

Judges score five dimensions. Accuracy is not one of them — Layer 1 owns it.

### Clarity (can a new player reconstruct the match?)

**Definition:** From text alone, the reader knows who did what, to whom, and
what changed.

| Score | Anchor |
|-------|--------|
| 1 | Lines name a move and nothing else; reversals unreadable; who took the damage is ambiguous |
| 3 | Most beats readable; occasional ambiguity about the victim or about what a state change unlocks |
| 5 | Actor, target, outcome and consequence are unambiguous every turn, including reversals and grapple entries |

**Negative signals:** `Nickname: Move name.` lines; a position change nobody
narrates; "reverses … only 2 damage" leaving the victim to inference.

### Fidelity (does the prose imply the right mechanics?)

**Definition:** Beyond arithmetic — the language implies the correct magnitude,
causality and consequence.

| Score | Anchor |
|-------|--------|
| 1 | Chip damage narrated as devastation, or a finisher narrated as a jab; text promises effects the rules do not grant |
| 3 | Magnitude roughly tracks the numbers; a few overclaims |
| 5 | Word choice scales with damage and stakes; every promised consequence is a real rule |

**Hard rule:** a line that introduces a fact the transcript does not support —
a referee warning, a title on the line, a body part that was never targeted —
is a fidelity failure, not colour. List it in `hallucinated_claims` and cap
`fidelity` at 2. Vivid writing does not buy score; unsupported writing loses it.

### Voice (is it wrestling broadcast, consistently?)

**Definition:** Register belongs on a wrestling broadcast, and stays there.

| Score | Anchor |
|-------|--------|
| 1 | Flat engine reporting or wrong register (fantasy, sci-fi, corporate) |
| 3 | Recognisable broadcast voice with tonal wobble |
| 5 | Consistent voice; when two commentators exist, each is distinct and stays in character |

Once a commentary team ships, also check: speakers alternate rather than
monologue, the colour commentator does not restate the play-by-play line, and
neither speaker uses the other's catchphrases.

### Freshness (does the match stop repeating itself?)

**Definition:** Repeated mechanics get varied words.

| Score | Anchor |
|-------|--------|
| 1 | One sentence shape carries the match; the same line lands 4+ turns in a row |
| 3 | Some rotation; the common exchanges still repeat verbatim |
| 5 | Recurring mechanics have several phrasings; repeats read as callbacks, not copies |

Anchor to `variety.phrasing_diversity`, `top_phrasing_share` and
`max_consecutive_repeat` rather than eyeballing.

### Escalation (does the language track the arc?)

**Definition:** Text intensity follows match stakes.

| Score | Anchor |
|-------|--------|
| 1 | A near-fall and a rest hold read identically |
| 3 | Finishes get emphasis; the build to them does not |
| 5 | Resets read calm, comebacks read urgent, near-falls and finishes peak |

**Note:** use `finish_sequence.steps[].delay_sec` for pacing. No TTY replay.

---

## Judge prompt

```markdown
You are a narration judge for ASCII Wrestling Federation.
Score ONLY from the provided transcript JSONL and dialog telemetry JSON.

Layer 1 already decided factual accuracy. Do not re-litigate it: if
dialog telemetry reports zero accuracy errors, treat the numbers and state
claims as correct and score taste instead.

Your job is what regex cannot see:
- claims that are consistent with state but still invented (referee actions,
  titles, injuries, crowd facts) -> hallucinated_claims, cap fidelity at 2
- register drift and voice inconsistency
- whether repeated mechanics get fresh words
- whether intensity tracks the arc

Game rules reminders:
- Submission % = chance to APPLY the hold, not win.
- Groggy is a modifier, not a position.
- Condition is not HP; do not reward "HP" phrasing.
- "Nickname: Move name." lines are the fallback path, not narration.

Dimensions (1=poor, 5=excellent): clarity, fidelity, voice, freshness, escalation.
Every score needs evidence: {"turn": N, "note": "quote"}.
Cap any dimension at 3 when confidence is low.
Return JSON matching docs/dialog-report.schema.json.
Include rubric_version: "2026-08-18".
```

Agent skill: [`.cursor/skills/awf-dialog-judge/SKILL.md`](../.cursor/skills/awf-dialog-judge/SKILL.md) — `/awf-dialog-judge`

---

## Coverage: seeds are not enough

Rare lines are where narration bugs live, and random seeds barely reach them.
Across the 40 committed transcripts, `busted open` appears 8 times and
`KNOCKOUT` once. Judge sampling over random seeds will never audit those lines.

Dialog coverage is therefore measured over **narration sites**, not seeds:
enumerate every line the engine can emit, and require each to be exercised by a
scenario fixture that pins state and RNG — the same idea as
[`tests/test_position_coverage.py`](../prototype/tests/test_position_coverage.py).
Until that harness exists, treat rare-event narration as unaudited and note it
in the report's `top_issues`.
