"""Per-move, per-commentator templated booth lines.

Each move may define optional ``success`` and ``failed`` template pools for any
commentator. When present, ``CommentaryEngine`` prefers these over the generic
event-kind pools in ``commentary.py``.

Interpolation keys (all optional in a template — unused keys are fine):

- ``{actor}``, ``{target}`` — nicknames
- ``{actor_name}``, ``{target_name}`` — full ring names
- ``{move}`` — lowercased move name from the event
- ``{move_id}`` — engine move id
- ``{count_word}`` — pin counts only

``failed`` covers both chip reversals (``reversal`` events) and clean whiffs
(``miss`` events).

See ``docs/commentary-design.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from commentary_events import EventKind


CommentaryOutcome = Literal["success", "failed"]

_SUCCESS_KINDS: frozenset[EventKind] = frozenset(
    {"damage", "setup", "submission_applied", "recover"}
)
_FAILED_KINDS: frozenset[EventKind] = frozenset({"reversal", "miss"})


@dataclass(frozen=True)
class CommentatorMoveTemplates:
    """Optional lines for one move × one commentator."""

    success: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()


# move_id → commentator_id → templates. Every move and commentator is optional.
MOVE_COMMENTARY: dict[str, dict[str, CommentatorMoveTemplates]] = {
    "punch": {
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} snaps a straight right — {target} eats it!",
                "Right hand from {actor}! {target} is rocked!",
            ),
        ),
        "heenan": CommentatorMoveTemplates(
            failed=(
                "{target} slipped it — {actor} couldn't hit the side of a barn!",
                "Give me a break! {actor} whiffed that punch!",
            ),
        ),
    },
    "collar_elbow": {
        "gorilla": CommentatorMoveTemplates(
            success=(
                "Collar-and-elbow from {actor} — they're tied up!",
                "{actor} and {target} lock up!",
            ),
        ),
        "ventura": CommentatorMoveTemplates(
            failed=(
                "{target} shoves {actor} off — no tie-up tonight!",
            ),
        ),
    },
    "pull_off_top": {
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} yanks {target} off the top rope — down to the canvas!",
                "Off the buckle! {target} hits the mat!",
            ),
        ),
        "heenan": CommentatorMoveTemplates(
            failed=(
                "{target} fights off the pull — {actor} gets nothing!",
            ),
        ),
    },
    "suplex": {
        "ross": CommentatorMoveTemplates(
            success=(
                "SUPLEX! {actor} arches {target} over — what a maneuver!",
                "Vertical suplex by {actor}! {target} is planted!",
            ),
        ),
        "cornette": CommentatorMoveTemplates(
            failed=(
                "Oh come on — {target} blocked the suplex!",
            ),
        ),
    },
    "sharp_shooter": {
        "ross": CommentatorMoveTemplates(
            success=(
                "Sharpshooter! {actor} has it locked on {target}!",
            ),
        ),
        "lawler": CommentatorMoveTemplates(
            failed=(
                "{target} scrambled out before the hold hooked in!",
            ),
        ),
    },
    "desperation_strike": {
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} makes a last-ditch effort there and hits the jackpot!",
            ),
            failed=(
                "{actor} swings wildly but can't quite make contact.",
            ),
        ),
    },
    "hurricanrana": {
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} with a {move}, and a beauty!",
            ),
            failed=(
                "{target} dodges the {move} and {actor} looks hurt.",
            ),
        ),
    },
    "atomic_leg_drop": {
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} drops the big leg on him, this one could be over!",
            ),
            failed=(
                "{target} rolls out of the way at the last second.",
            ),
        ),
    },
    "stomp": {
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} stomps a big ol' boot right into {target}'s chest",
            ),
            failed=(
                "{target} barely manages to get out of the way of that vicious {move}",
            ),
        ),
    },
}


def outcome_for_event_kind(kind: EventKind) -> CommentaryOutcome | None:
    """Map an event kind to a move-outcome bucket, if move-specific copy applies."""
    if kind in _SUCCESS_KINDS:
        return "success"
    if kind in _FAILED_KINDS:
        return "failed"
    return None


def move_commentary_pool(
    move_id: str | None,
    commentator_id: str,
    outcome: CommentaryOutcome,
) -> tuple[str, ...] | None:
    """Return a template pool for this move/commentator/outcome, or ``None``."""
    if not move_id:
        return None
    by_commentator = MOVE_COMMENTARY.get(move_id)
    if by_commentator is None:
        return None
    templates = by_commentator.get(commentator_id)
    if templates is None:
        return None
    pool = templates.success if outcome == "success" else templates.failed
    return pool if pool else None


def validate_move_commentary(valid_move_ids: frozenset[str]) -> None:
    """Raise ``ValueError`` if any registry key references an unknown move id."""
    for move_id, by_commentator in MOVE_COMMENTARY.items():
        if move_id not in valid_move_ids:
            raise ValueError(f"unknown move_id in MOVE_COMMENTARY: {move_id}")
        for commentator_id, templates in by_commentator.items():
            if not templates.success and not templates.failed:
                raise ValueError(
                    f"empty templates for {move_id}/{commentator_id}"
                )
