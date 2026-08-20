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
                "{actor} cracks him right in the jaw!",
                "{actor} with a stiff shot to the breadbasket",
            ),
            failed=(
                "{actor} goes for a {move} and finds nothing but air",
            ),
        ),
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} lands a stiff punch to the jaw",
            ),
            failed=(
                "{target} dodges {actor}'s {move}",
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
                "{move} from {actor}, they're both grappling for control",
            ),
            failed=(
                "{actor} tries to lock up, but {target} slips out",
            ),
        ),
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} locks up with {target}",
            ),
            failed=(
                "{target} manages to sidestep the lock-up",
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
    "get_up": {
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} shakes the cobwebs out and gets back up to his feet",
            ),
            failed=(
                "{actor} can't quite shake the cobwebs",
            ),
        ),
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} digs deep and pushes himself back to his feet",
            ),
            failed=(
                "{actor} can't summon the strength to get up",
            ),
        ),
    },
    "grapple_counter": {
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} breaks free from the tie-up",
            ),
            failed=(
                "{actor}'s trying to break free, but {target} has a vice-like grip locked in",
            ),
        ),
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} manages to escape that tie-up",
            ),
            failed=(
                "{actor} tries to get away, but {target} won't let him",
            ),
        ),
    },
    "climb": {
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} climbs the turnbuckle, maybe looking for a high-risk maneuver",
            ),
        ),
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} climbs to the top rope, he's looking to inflict more damage here",
            ),
        ),
    },
    "break_grapple": {
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} manages to slip free from the lockup",
            ),
            failed=(
                "{actor} can't manage to break the hold",
            ),
        ),
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} peels those fingers about and escapes",
            ),
            failed=(
                "{target} has too strong of a grip, {actor} can't get free",
            ),
        ),
    },
    "hit_the_ropes": {
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} hits the ropes",
            ),
        ),
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} bounces off the ropes with a head of steam",
            ),
        ),
    },
    "kick": {
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} with a {move} to the head",
            ),
            failed=(
                "{target} ducks out of the way of that {move}",
            ),
        ),
        "ross": CommentatorMoveTemplates(
            success=(
                "{target} eats a big {move}",
            ),
            failed=(
                "{actor} goes for a big {move}, but {target} gets out of the way",
            ),
        ),
    },
    "feet_plant": {
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} grabs a rope and gets back to the center of the ring",
            ),
            failed=(
                "{actor} can't slow down, he's got too much momentum",
            ),
        ),
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} grabs a rope and gets back to the center of the ring",
            ),
            failed=(
                "{actor} can't slow down, he's got too much momentum",
            ),
        ),
    },
    "shake_groggy": {
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} shakes the cobwebs loose!",
            ),
            failed=(
                "{actor} looks out on his feet",
            ),
        ),
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} clears his head and looks ready to go again!",
            ),
            failed=(
                "{actor} still looks like he's been knocked loopy",
            ),
        ),
    },
    "recover": {
        "ross": CommentatorMoveTemplates(
            success=(
                "{actor} takes a quick breather",
            ),
        ),
        "gorilla": CommentatorMoveTemplates(
            success=(
                "{actor} takes a break to collect himself",
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
