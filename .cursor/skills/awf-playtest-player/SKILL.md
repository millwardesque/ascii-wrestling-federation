---
name: awf-playtest-player
description: Run headless AWF playtest matches and record JSONL transcripts. Use when playtesting, recording match sessions, or generating seeds for evaluation — not for scoring or code changes.
paths:
  - "prototype/**"
  - "docs/playtest*.md"
disable-model-invocation: true
---

# AWF playtest player

You are a **player-only** agent. Run matches and capture transcripts. Do **not** score rubrics or modify gameplay code unless explicitly asked.

## Setup

```bash
cd prototype
```

Read repo context in [`AGENTS.md`](../../../AGENTS.md) if unfamiliar with positions, groggy, or curation.

## Run a match

Preferred (compact JSONL):

```bash
python3 main.py --playtest --seed SEED --policy POLICY
```

| Flag | Values |
|------|--------|
| `--seed` | Integer for reproducible RNG |
| `--policy` | `novice`, `aggressive`, `methodical`, `chaotic` |
| `--max-turns` | Optional cap for exploratory runs |

Batch to files:

```bash
python3 playtest/record_match.py \
  --seeds 101,102,103 \
  --policy chaotic \
  --output-dir playtest/transcripts
```

## Policies

Rotate across runs for coverage:

- **novice** — mostly picks options 1–2 (tests default curation)
- **aggressive** — prefers Finish / Big swing intents
- **methodical** — prefers Set up position / Grapple control
- **pressure** — prefers Pressure / safe buildup
- **chaotic** — random curated choice

## Rules

1. **Always** use `--playtest`. Never parse or drive the full-screen TTY UI unless the task explicitly tests layout/color.
2. **Never** self-score fun, juiciness, or other rubric dimensions.
3. **Never** edit game code during a playtest run.
4. Use fixed seeds when asked for reproducibility or batch comparison.

## Output

- Single run: JSONL on stdout (`match_start`, `turn`, `match_end` events).
- Batch: write `prototype/playtest/transcripts/<seed>.jsonl`.

Optional telemetry (separate step, not player scoring):

```bash
python3 playtest/record_match.py --seeds SEED --output-dir playtest/transcripts --telemetry
```

## Do not

- Run `python3 main.py` without `--playtest` for agent evaluation
- Attach to interactive TTY for rubric workflows
- Combine player and judge roles in one session

Hand off transcripts to the **awf-playtest-judge** skill or a judge agent.
