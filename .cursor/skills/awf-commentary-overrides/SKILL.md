---
name: awf-commentary-overrides
description: >-
  Repeatedly prompt for bespoke per-move commentary overrides. Shows a move's
  default success and reversal strings for a random primary (play-by-play)
  commentator, then waits for the user to supply copy. Use when authoring or
  filling MOVE_COMMENTARY, writing booth lines, or when the user asks to
  override generic commentary templates.
paths:
  - "prototype/commentary_templates.py"
  - "prototype/commentary.py"
  - "prototype/commentators.py"
  - "docs/commentary-design.md"
disable-model-invocation: true
---

# AWF commentary overrides

You run a **prompt loop**. Each turn you show one move's generic success and
reversal lines in a random primary commentator's voice, then **wait** for the
user to write bespoke overrides. Do not invent the copy.

Overrides live in [`prototype/commentary_templates.py`](../../../prototype/commentary_templates.py)
as `MOVE_COMMENTARY[move_id][commentator_id]`. `success` covers damage / setup /
submission_applied / recover. `failed` covers reversal and miss.

Design notes: [`docs/commentary-design.md`](../../../docs/commentary-design.md).

## Setup

From the repo root:

```bash
python3 .cursor/skills/awf-commentary-overrides/scripts/next_prompt.py
```

That script picks a random **PBP** commentator (`gorilla`, `ross`) and a
random move that still needs `success` and/or `failed`. Print the card to the
user verbatim (or lightly formatted — do not rewrite the default lines).

Optional flags: `--seed N`, `--move MOVE_ID`, `--commentator ID`, `--rewrite`,
`--json`.

## Loop

1. Run `next_prompt.py`. If it exits 2, every PBP×move cell is filled — stop
   and say so (offer `--rewrite` only if they ask).
2. Show the card. **End your turn.** Do not draft overrides, do not skip ahead.
3. After the user replies, handle it:

   | Reply | Action |
   |-------|--------|
   | `success:` / `failed:` lines | Merge into `MOVE_COMMENTARY` (keep any pool they did not mention) |
   | `keep` on one side | Leave that pool unchanged |
   | `skip` | Do not write; draw the next card |
   | `stop` / `done` / `quit` | End the session; summarize what you wrote |
   | Freeform lines without labels | Treat as `success` if only `success` is missing, `failed` if only `failed` is missing; if both are missing, ask which is which instead of guessing |

4. After a write: merge, keep existing tuple items the user did not replace,
   run `python3 -m unittest tests.test_commentary -q` from `prototype/`, then
   immediately run `next_prompt.py` again and show the next card.

One card per turn. Do not batch several moves in one message.

## Writing rules

When merging into `commentary_templates.py`:

- Add or edit only that `(move_id, commentator_id)` entry.
- Store lines as a tuple of strings. One or two lines per pool is enough.
- Preserve other commentators on the same move.
- Templates may use `{actor}`, `{target}`, `{actor_name}`, `{target_name}`,
  `{move}`. `{move}` is the lowercased move name.
- Match the commentator's `register`, `bias`, and `vocab`. Never use words in
  `avoid`. Catchphrases are rare garnish, not every line.
- Do not invent championships, injuries, referee warnings, or arena facts.
- If `skip_hit_roll` is true, `failed` will almost never play — still accept a
  line if they give one, but do not pester for it.
- Do not paraphrase, "improve," or expand the user's copy. Store it verbatim.

## Do not

- Generate override copy yourself
- Pick color commentators (authoring PBP is Gorilla and JR only)
- Rewrite generic pools in `commentary.py`
- Commit unless the user asks
