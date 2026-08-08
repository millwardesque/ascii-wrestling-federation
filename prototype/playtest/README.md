# Playtest mode

Headless JSONL output for cloud-agent playtesting. See [`docs/playtest-rubric.md`](../docs/playtest-rubric.md).

## Quick start

```bash
cd prototype
python3 main.py --playtest --seed 42 --policy methodical
python3 playtest/record_match.py --seeds 1,2,3 --output-dir playtest/transcripts
python3 playtest/compute_telemetry.py
```

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

- Transcript: [`docs/playtest-transcript.schema.json`](../docs/playtest-transcript.schema.json)
- Judge report: [`docs/playtest-report.schema.json`](../docs/playtest-report.schema.json)

## Agent skills

- **Player:** `/awf-playtest-player` — [`.cursor/skills/awf-playtest-player/SKILL.md`](../../.cursor/skills/awf-playtest-player/SKILL.md)
- **Judge:** `/awf-playtest-judge` — [`.cursor/skills/awf-playtest-judge/SKILL.md`](../../.cursor/skills/awf-playtest-judge/SKILL.md)
