# Playtest mode

Headless JSONL output for cloud-agent playtesting. Gameplay is scored against
[`docs/playtest-rubric.md`](../../docs/playtest-rubric.md); match narration is
scored against [`docs/dialog-rubric.md`](../../docs/dialog-rubric.md).

## Quick start

```bash
cd prototype
python3 main.py --playtest --seed 42 --policy methodical
python3 playtest/record_match.py --seeds 1,2,3 --output-dir playtest/transcripts
python3 playtest/compute_telemetry.py
python3 playtest/compute_dialog_telemetry.py
```

## Two evaluation tracks

| Track | Layer 1 | Judge | Question |
|-------|---------|-------|----------|
| Gameplay | `playtest/telemetry.py` | `/awf-playtest-judge` | Is the match fun, clear, sticky, juicy? |
| Narration | `playtest/dialog_telemetry.py` | `/awf-dialog-judge` | Is the text accurate, clear, fresh, in voice? |

Narration accuracy is decided deterministically: `dialog_telemetry.py` compares
every numeric and state claim in the `log` text against the `state` snapshots in
the same transcript. Judges score taste only.

```bash
cd prototype
# per-seed reports + batch verdict; non-zero exit when batch gates fail
python3 playtest/compute_dialog_telemetry.py \
  --output-dir playtest/dialog \
  --summary playtest/dialog-summary.json \
  --fail-on-gate

# which narration lines has any evaluation ever read?
python3 playtest/narration_coverage.py --output playtest/narration-coverage.json
```

Coverage is measured over narration sites read out of `game.py`, not over seeds:
rare copy (`KNOCKOUT` fires once in 40 matches) is where narration bugs survive.
Lines reported in `unmatched_examples` mean the corpus predates the current copy.

## CLI flags

| Flag | Purpose |
|------|---------|
| `--playtest` | Emit compact JSONL instead of full-screen UI |
| `--seed N` | Reproducible match RNG |
| `--max-turns N` | Stop after N actor moves (`reason: max_turns`) |
| `--policy NAME` | `novice`, `aggressive`, `methodical`, `chaotic` |

## Pipe / TTY behavior

| Mode | Sleeps | Output |
|------|--------|--------|
| `--playtest` | None | JSONL only |
| `--random-match` + piped stdin | Skips pin/scroll sleeps | Full ANSI (avoid for agents) |
| TTY + default renderer | Pin + scroll delays | Full ANSI (human play) |

For TTY automation that is not `--playtest`, set:

```bash
export AWF_CONFIG_PATH=config.playtest.json
```

All timing keys in that file are `0.0`.

## Schemas

- Transcript: [`docs/playtest-transcript.schema.json`](../../docs/playtest-transcript.schema.json)
- Playtest judge report: [`docs/playtest-report.schema.json`](../../docs/playtest-report.schema.json)
- Dialog judge report: [`docs/dialog-report.schema.json`](../../docs/dialog-report.schema.json)

## Agent skills

- **Player:** `/awf-playtest-player` — [`.cursor/skills/awf-playtest-player/SKILL.md`](../../.cursor/skills/awf-playtest-player/SKILL.md)
- **Gameplay judge:** `/awf-playtest-judge` — [`.cursor/skills/awf-playtest-judge/SKILL.md`](../../.cursor/skills/awf-playtest-judge/SKILL.md)
- **Dialog judge:** `/awf-dialog-judge` — [`.cursor/skills/awf-dialog-judge/SKILL.md`](../../.cursor/skills/awf-dialog-judge/SKILL.md)

## Artifact layout

| Path | Written by |
|------|------------|
| `playtest/transcripts/<seed>.jsonl` | `record_match.py` |
| `playtest/telemetry/<seed>.json` | `compute_telemetry.py` |
| `playtest/reports/<seed>.json` | `/awf-playtest-judge` |
| `playtest/dialog/<seed>.json` | `compute_dialog_telemetry.py` |
| `playtest/dialog-summary.json` | `compute_dialog_telemetry.py --summary` |
| `playtest/narration-coverage.json` | `narration_coverage.py --output` |
| `playtest/dialog-reports/<seed>.json` | `/awf-dialog-judge` |
