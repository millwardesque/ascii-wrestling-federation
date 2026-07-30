# AWF Playtest Rubric

`rubric_version: 2026-07-30`

Evaluation criteria for cloud-agent playtesters of the ASCII Wrestling Federation terminal prototype. Agents score from **JSONL transcripts** and **telemetry JSON** only — never from full-screen ANSI output.

## Orchestration rule

> Cloud agents: always use `python3 main.py --playtest --seed N`. Never attach playtest agents to the full-screen TTY UI unless explicitly testing layout or color.

Split roles:

1. **Player agent** — runs `--playtest`, outputs transcript JSONL only (no self-scoring).
2. **Judge agent** — reads transcript + telemetry, outputs report JSON (no code changes).
3. **Aggregator** (optional) — batches reports, flags variance and telemetry failures.

Player policies to rotate: `novice`, `aggressive`, `methodical`, `chaotic`.

---

## Layer 1: Objective telemetry (no LLM judgment)

Computed by [`prototype/playtest/telemetry.py`](../prototype/playtest/telemetry.py). These anchor subjective scores and catch regressions cheaply.

| Metric | Why it matters |
|--------|----------------|
| `turn_count`, `winner`, `match_seed` | Pacing / reproducibility |
| HP/momentum trajectory | Comebacks, snowballing |
| Position/state diversity | Tactical depth |
| `near_fall_count` | Drama / juiciness proxy |
| Submission apply vs escape | Finish tension |
| `move_repetition_rate` | Stale loops |
| `curation_pin_visible` | Pin shown when legal |
| `single_choice_turns` | UX friction |
| `log_uniqueness_ratio` | Narrative freshness |

### Pass/fail gates

- `curation_pin_visible` is true whenever pin is in `valid_rules`.
- Match completes without stuck state (`winner` set or `reason: max_turns`).
- `turn_count` within band (default 8–40 for 2-wrestler matches).
- Position coverage (static test in `tests/test_position_coverage.py`).

---

## Layer 2: Rubric dimensions

Each score requires **evidence** citing `(turn, quote_or_field)`. Use **1–5** scale. Cap score at **3** if confidence is `low`.

### Fun (tactical engagement + emotional arc)

**Definition:** Meaningful trade-offs each turn; match builds toward a satisfying climax.

| Score | Anchor |
|-------|--------|
| 1 | One obvious best move every turn; no comeback windows; anticlimactic finish |
| 3 | Some risk/reward tension; occasional momentum swings; finish has modest buildup |
| 5 | Distinct intents with real trade-offs; clear comeback beats; near-fall before finish |

**Positive signals:** distinct curated intents with different risk; momentum/HP swings; multiple viable strategies.

**Negative signals:** same intent 3+ turns in a row; one-sided snowball; instant pin with no drama.

### Ease of use (readability + decision clarity)

**Definition:** A new player understands status, options, and outcomes without external docs.

| Score | Anchor |
|-------|--------|
| 1 | Hidden critical moves; status changes unexplained; submission % misread as win chance |
| 3 | Curated menu mostly clear; occasional ambiguity in log chronology |
| 5 | Intent + label + outcome align; pin always visible when legal; groggy/position clear |

**Positive signals:** intent labels match move behavior; pin visible when legal; log explains reversals.

**Negative signals:** optimal move hidden from curation; only one block per wrestler causes confusion.

### Stickiness (would you queue another match?)

**Definition:** Session creates curiosity to continue — rematch, other wrestler, new lines.

| Score | Anchor |
|-------|--------|
| 1 | No rematch intent; match felt samey; no discovery |
| 3 | Maybe rematch with generic reason |
| 5 | Clear rematch intent with specific next experiment |

**Required fields:** `rematch_intent` (`yes|maybe|no`), `rematch_reason`, `next_experiment`.

### Juiciness (feedback density + payoff feel)

**Definition:** Important moments feel impactful through text and state feedback.

| Score | Anchor |
|-------|--------|
| 1 | Flat hit/miss with no state shift; repetitive log phrasing |
| 3 | Some big spots change momentum/position; pin text present |
| 5 | Groggy/finisher/pin beats land with clear narrative; state shifts track drama |

**Note:** Judge uses `finish_sequence.delays_sec` metadata for pacing — no TTY replay required.

---

## Judge prompt

```markdown
You are a wrestling-game UX judge for ASCII Wrestling Federation.
Score ONLY from the provided transcript JSONL and telemetry JSON.
Do not invent events. Every score must cite turn numbers and quotes.

Game rules reminders:
- Submission % = chance to APPLY hold, not win.
- Groggy is a modifier, not a position.
- Curated menu may hide legal moves; flag if hidden move is clearly optimal.
- Ignore win/loss unless it reflects fairness or pacing.

Dimensions (1=poor, 5=excellent): fun, ease_of_use, stickiness, juiciness.
Return JSON matching docs/playtest-report.schema.json.
Include rubric_version: "2026-07-30".
```

Agent skills (invoke explicitly):

- Player: [`.cursor/skills/awf-playtest-player/SKILL.md`](../.cursor/skills/awf-playtest-player/SKILL.md) — `/awf-playtest-player`
- Judge: [`.cursor/skills/awf-playtest-judge/SKILL.md`](../.cursor/skills/awf-playtest-judge/SKILL.md) — `/awf-playtest-judge`

---

## Pipe / TTY behavior

| Mode | Delays | Output |
|------|--------|--------|
| `--playtest` | None | Compact JSONL |
| `--random-match` + piped stdin | Skips pin/scroll sleeps | Full ANSI (avoid for agents) |
| TTY + `FixedLayoutRenderer` | Pin + scroll delays active | Full ANSI (human play only) |

For any TTY automation, use [`prototype/config.playtest.json`](../prototype/config.playtest.json) (`AWF_CONFIG_PATH=config.playtest.json`).
