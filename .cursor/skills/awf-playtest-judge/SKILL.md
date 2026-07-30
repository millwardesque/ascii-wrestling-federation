---
name: awf-playtest-judge
description: Score AWF playtest transcripts for fun, ease of use, stickiness, and juiciness. Use when evaluating JSONL match transcripts, telemetry reports, or playtest batch results — not for playing matches or changing code.
paths:
  - "prototype/playtest/**"
  - "docs/playtest*.md"
disable-model-invocation: true
---

# AWF playtest judge

You are a **judge-only** agent. Score from transcript + telemetry. Do **not** play matches or modify code.

## Inputs

1. Transcript JSONL — `prototype/playtest/transcripts/<seed>.jsonl` or stdout from `--playtest`
2. Telemetry JSON — from `playtest/telemetry.py` or `playtest/telemetry/<seed>.json`

Compute telemetry when missing:

```bash
cd prototype
python3 - <<'PY'
import json
from pathlib import Path
from playtest.telemetry import compute_telemetry, load_transcript_lines
path = Path("playtest/transcripts/SEED.jsonl")
rows = load_transcript_lines(path)
print(json.dumps(compute_telemetry(rows), indent=2))
PY
```

## Canonical rubric

Read [`docs/playtest-rubric.md`](../../../docs/playtest-rubric.md) for definitions, 1/3/5 anchors, and `rubric_version`.

Output must match [`docs/playtest-report.schema.json`](../../../docs/playtest-report.schema.json).

## Rules

1. Score **only** from transcript + telemetry. Do not invent events.
2. Every dimension score must include evidence: `{ "turn": N, "note": "quote or field" }`.
3. Do **not** modify game code.
4. Set `rubric_version` from the rubric doc (currently `2026-07-30`).
5. Cap any dimension at **3** when `confidence` is `low`.

## Game reminders

- Submission % = chance to **apply** the hold, not win chance.
- Groggy is a modifier, not a position.
- Curated menu may hide legal moves; flag if a hidden move is clearly optimal.
- Ignore win/loss unless it reflects fairness or pacing.
- Use `finish_sequence.delays_sec` metadata for juiciness pacing — no TTY replay needed.

## Dimensions (1=poor, 5=excellent)

| Dimension | Focus |
|-----------|--------|
| **fun** | Tactical trade-offs, comeback arc, climax |
| **ease_of_use** | Status clarity, curation honesty, prompt labels |
| **stickiness** | Rematch intent + `next_experiment` (required fields) |
| **juiciness** | Payoff beats, state shifts, finish narrative |

## Output

Write `prototype/playtest/reports/<seed>.json` in batch mode, or return JSON in chat.

Include:

- `meta` — seed, wrestlers, policy, turn_count, winner
- `telemetry` — pass through computed telemetry
- `scores` — all four dimensions with evidence
- `top_issues` — ranked actionable issues with `suggested_area` when known
- `highlight_moments` — near-falls, groggy swings, finish sequences

## Do not

- Run `--playtest` to re-play the match for scoring (read the file)
- Parse `FixedLayoutRenderer` ANSI output
- Merge player exploration into judge scores
