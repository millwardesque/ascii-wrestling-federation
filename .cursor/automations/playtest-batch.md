# Playtest batch automation

Use this template for Cursor Automations that run parallel cloud-agent playtests.

## Goal

Batch seeded headless matches, compute telemetry, and optionally invoke judge agents — **without** the TTY UI.

## Environment

- Working directory: `prototype/`
- Optional: `AWF_CONFIG_PATH=config.playtest.json` (zero delays if anything hits TTY)

## Step 1 — Record transcripts (deterministic)

```bash
cd prototype
python3 playtest/record_match.py \
  --seeds 101,102,103,104,105,106,107,108,109,110 \
  --policy chaotic \
  --output-dir playtest/transcripts
```

Policies to rotate across runs: `novice`, `aggressive`, `methodical`, `chaotic`.

## Step 2 — Compute telemetry

```bash
cd prototype
python3 playtest/compute_telemetry.py
```

Writes `playtest/telemetry/<seed>.json` for each file in `playtest/transcripts/`.

## Step 3 — Judge agents (parallel)

Launch one cloud agent per seed with [`.cursor/playtest-judge.md`](../playtest-judge.md) instructions.

Each agent receives:

- `playtest/transcripts/<seed>.jsonl`
- `playtest/telemetry/<seed>.json`

Each agent writes:

- `playtest/reports/<seed>.json`

## Step 4 — Aggregate

Parent agent scans `playtest/reports/*.json` for:

- `telemetry.gates_passed == false`
- dimension scores with high variance across seeds
- `confidence: low` scores

Human review only disagreements.

## CLI quick reference

```bash
# Single seeded match to stdout
python3 main.py --playtest --seed 42 --policy methodical

# Capped exploratory run
python3 main.py --playtest --seed 42 --max-turns 12

# Random wrestlers + seed
python3 main.py --playtest --seed 42
```

## Do not

- Parse `FixedLayoutRenderer` ANSI stdout for rubric scoring
- Run playtest agents attached to interactive TTY unless testing layout
