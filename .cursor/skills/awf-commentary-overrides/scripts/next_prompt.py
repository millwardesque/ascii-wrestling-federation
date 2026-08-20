#!/usr/bin/env python3
"""Pick a random move × primary (PBP) commentator for override authoring.

Run from anywhere:

    python3 .cursor/skills/awf-commentary-overrides/scripts/next_prompt.py

Prints a prompt card to stdout. Exit 2 when every PBP×move cell already has
both success and failed pools (unless --rewrite).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PROTOTYPE = _REPO_ROOT / "prototype"
if str(_PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(_PROTOTYPE))

from commentators import ROSTER, Commentator  # noqa: E402
from commentary import _ID_TEMPLATES, _ROLE_TEMPLATES  # noqa: E402
from commentary_templates import MOVE_COMMENTARY, CommentatorMoveTemplates  # noqa: E402
from moves import Move, all_move_rules  # noqa: E402

# Achievable authoring set — not the full PBP roster.
AUTHORING_PBP_IDS: tuple[str, ...] = ("gorilla", "ross")


def _pbp() -> list[Commentator]:
    return [ROSTER[cid] for cid in AUTHORING_PBP_IDS]


def _pool(commentator: Commentator, kind: str) -> tuple[str, ...]:
    return _ID_TEMPLATES.get((commentator.id, kind)) or _ROLE_TEMPLATES.get(
        (commentator.role, kind)
    ) or ()


def _success_kind(move: Move) -> str:
    if move.is_submission:
        return "submission_applied"
    if move.base_damage > 0:
        return "damage"
    return "setup"


def _existing(move_id: str, commentator_id: str) -> CommentatorMoveTemplates | None:
    by_commentator = MOVE_COMMENTARY.get(move_id)
    if not by_commentator:
        return None
    return by_commentator.get(commentator_id)


def _cells(*, rewrite: bool) -> list[tuple[Move, Commentator, bool, bool]]:
    out: list[tuple[Move, Commentator, bool, bool]] = []
    for rule in all_move_rules():
        for commentator in _pbp():
            templates = _existing(rule.move.id, commentator.id)
            missing_success = templates is None or not templates.success
            missing_failed = templates is None or not templates.failed
            if rewrite or missing_success or missing_failed:
                out.append((rule.move, commentator, missing_success, missing_failed))
    return out


def _card(move: Move, commentator: Commentator, missing_success: bool, missing_failed: bool) -> dict:
    success_kind = _success_kind(move)
    templates = _existing(move.id, commentator.id)
    return {
        "move_id": move.id,
        "move_name": move.name,
        "description": move.description,
        "success_kind": success_kind,
        "can_miss": not move.skip_hit_roll,
        "skip_hit_roll": move.skip_hit_roll,
        "is_finisher": move.is_finisher,
        "is_pin": move.is_pin,
        "is_submission": move.is_submission,
        "commentator_id": commentator.id,
        "commentator_name": commentator.name,
        "short": commentator.short,
        "role": commentator.role,
        "register": commentator.register,
        "bias": commentator.bias,
        "catchphrases": list(commentator.catchphrases),
        "vocab": sorted(commentator.vocab),
        "avoid": sorted(commentator.avoid),
        "missing_success": missing_success,
        "missing_failed": missing_failed,
        "existing_success": list(templates.success) if templates else [],
        "existing_failed": list(templates.failed) if templates else [],
        "default_success": list(_pool(commentator, success_kind)),
        "default_reversal": list(_pool(commentator, "reversal")),
    }


def _render(card: dict, remaining: int, total: int) -> str:
    flags = []
    if card["is_finisher"]:
        flags.append("finisher")
    if card["is_pin"]:
        flags.append("pin")
    if card["is_submission"]:
        flags.append("submission")
    if card["skip_hit_roll"]:
        flags.append("always-connects (no reversal/miss)")
    flag_txt = f" — {', '.join(flags)}" if flags else ""

    def _lines(title: str, items: list[str], *, empty: str) -> str:
        if not items:
            return f"{title}\n  ({empty})"
        body = "\n".join(f"  {i}. {line}" for i, line in enumerate(items, start=1))
        return f"{title}\n{body}"

    need = []
    if card["missing_success"]:
        need.append("success")
    if card["missing_failed"]:
        need.append("failed/reversal")
    need_txt = " and ".join(need) if need else "rewrite"

    return "\n".join(
        [
            f"Coverage: {total - remaining}/{total} PBP×move cells have both pools. "
            f"{remaining} still open including this one.",
            "",
            f"Move: {card['move_name']} (`{card['move_id']}`){flag_txt}",
            f"  {card['description']}",
            f"  Success kind this card uses: {card['success_kind']}",
            "",
            f"Primary commentator: {card['commentator_name']} "
            f"(`{card['commentator_id']}` / {card['short']})",
            f"  role={card['role']}  register={card['register']}  bias={card['bias']}",
            f"  vocab: {', '.join(card['vocab']) or '—'}",
            f"  avoid: {', '.join(card['avoid']) or '—'}",
            f"  catchphrases (garnish, not every line): "
            + ("; ".join(card["catchphrases"]) or "—"),
            "",
            _lines(
                "Default success (generic pool this override would replace):",
                card["default_success"],
                empty="no generic pool",
            ),
            "",
            _lines(
                "Default reversal (generic pool this override would replace):",
                card["default_reversal"],
                empty="no generic pool",
            ),
            "",
            _lines(
                "Existing success override:",
                card["existing_success"],
                empty="none — needs bespoke copy" if card["missing_success"] else "none",
            ),
            "",
            _lines(
                "Existing failed/reversal override:",
                card["existing_failed"],
                empty="none — needs bespoke copy" if card["missing_failed"] else "none",
            ),
            "",
            f"Needed this round: {need_txt}",
            "",
            "Reply with:",
            "  success: <one or more template lines>",
            "  failed: <one or more template lines>",
            "Use {actor} {target} {actor_name} {target_name} {move}.",
            "Or: keep (skip one side) / skip (next card) / stop.",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--move", dest="move_id", default=None)
    parser.add_argument("--commentator", dest="commentator_id", default=None)
    parser.add_argument(
        "--rewrite",
        action="store_true",
        help="Include cells that already have both pools.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    cells = _cells(rewrite=args.rewrite)
    total_cells = len(_pbp()) * len(all_move_rules())
    filled = total_cells - len(_cells(rewrite=False))

    if args.move_id or args.commentator_id:
        wanted = []
        for move, commentator, missing_success, missing_failed in _cells(rewrite=True):
            if args.move_id and move.id != args.move_id:
                continue
            if args.commentator_id and commentator.id != args.commentator_id:
                continue
            wanted.append((move, commentator, missing_success, missing_failed))
        if not wanted:
            print("No matching move/commentator cell.", file=sys.stderr)
            return 1
        move, commentator, missing_success, missing_failed = rng.choice(wanted)
    else:
        if not cells:
            print(
                "Every primary commentator already has success and failed "
                "pools for every move. Re-run with --rewrite to revisit.",
                file=sys.stderr,
            )
            return 2
        move, commentator, missing_success, missing_failed = rng.choice(cells)

    card = _card(move, commentator, missing_success, missing_failed)
    remaining = len(_cells(rewrite=False))
    if args.json:
        payload = dict(card)
        payload["remaining_open"] = remaining
        payload["filled"] = filled
        payload["total"] = total_cells
        print(json.dumps(payload, indent=2))
    else:
        print(_render(card, remaining=remaining, total=total_cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
