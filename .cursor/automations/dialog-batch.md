# Dialog batch automation

Template for Cursor Automations that evaluate match narration. Companion to
[`playtest-batch.md`](playtest-batch.md), which evaluates gameplay. Both read the
same transcripts.

## Goal

Check narration accuracy deterministically, report coverage over narration sites,
and spend judge agents only on taste — **without** the TTY UI.

## Environment

- Working directory: `prototype/`
- Optional: `AWF_CONFIG_PATH=config.playtest.json` (zero delays if anything hits TTY)

## Step 1 — Record transcripts (deterministic)

Use the **awf-playtest-player** skill (`/awf-playtest-player`) or run:

```bash
cd prototype
python3 playtest/record_match.py \
  --seeds 101,102,103,104,105,106,107,108,109,110 \
  --policy chaotic \
  --output-dir playtest/transcripts
```

Rotate `novice`, `aggressive`, `methodical`, `chaotic` across runs. Narration
varies with the moves chosen, so a single policy leaves whole line families
untouched.

## Step 2 — Layer 1 accuracy (no LLM)

```bash
cd prototype
python3 playtest/compute_dialog_telemetry.py \
  --output-dir playtest/dialog \
  --summary playtest/dialog-summary.json \
  --fail-on-gate
```

Stop here if the batch gates fail. An `error`-severity finding means a printed
line contradicts the match state, which is a bug in `game.py`, not a matter of
taste — no judge needed, and judging on top of broken copy wastes tokens.

## Step 3 — Narration coverage

```bash
cd prototype
python3 playtest/narration_coverage.py --output playtest/narration-coverage.json
```

Read two fields:

- `uncovered` — narration this batch never exercised. Extend seeds or policies, or
  note it as unaudited in the final summary.
- `unmatched_examples` — lines belonging to no current site, meaning the corpus
  predates the copy. Re-record before trusting any narration verdict.

## Step 4 — Judge agents (parallel)

Launch one cloud agent per seed with the **awf-dialog-judge** skill
(`/awf-dialog-judge`). See [`.cursor/skills/awf-dialog-judge/SKILL.md`](../skills/awf-dialog-judge/SKILL.md).

Each agent receives:

- `playtest/transcripts/<seed>.jsonl`
- `playtest/dialog/<seed>.json`

Each agent writes:

- `playtest/dialog-reports/<seed>.json`

Judges score `clarity`, `fidelity`, `voice`, `freshness`, `escalation` — never
accuracy, which Step 2 already settled.

## Step 5 — Aggregate

Parent agent scans `playtest/dialog-reports/*.json` for:

- any `hallucinated_claims` entry (caps `fidelity` at 2 and needs a copy fix)
- dimension scores with high variance across seeds
- `confidence: low` scores
- repeated `rewrite_suggestions` for the same line

Cross-check against `playtest/dialog-summary.json`: a judge complaining about
freshness while `phrasing_diversity` sits at the batch median is describing the
baseline, not a regression.

Human review only disagreements.

## Do not

- Ask a judge to verify damage numbers or state claims
- Parse `FixedLayoutRenderer` ANSI stdout
- Judge narration from a corpus with `unmatched_examples`
- Loosen a ratchet in `dialog_telemetry.py` to make a batch pass
