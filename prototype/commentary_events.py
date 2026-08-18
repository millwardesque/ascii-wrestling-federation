"""Match event contract for commentary rendering.

``apply_move`` will eventually emit these instead of f-string log lines. The
``CommentaryEngine`` turns events into dual-voice booth lines; Layer 1 dialog
telemetry checks commentary against events, not regex against prose in ``game.py``.

See ``docs/commentary-design.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


EventKind = Literal[
    "move_attempt",
    "damage",
    "miss",
    "reversal",
    "position_change",
    "groggy_applied",
    "groggy_cleared",
    "knockdown",
    "knockout",
    "bloodied",
    "momentum_shift",
    "loop_pressure",
    "pin_count",
    "pin_kickout",
    "pinfall",
    "submission_applied",
    "submission_escape",
    "submission_tap",
    "recover",
    "setup",
]


@dataclass(frozen=True)
class MatchEvent:
    """One atomic fact from the engine. Commentary must not contradict these."""

    kind: EventKind
    actor: int | None = None
    target: int | None = None
    move_id: str | None = None
    move_name: str | None = None
    amount: int | None = None
    position: str | None = None
    pin_count: int | None = None
    won: bool | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommentaryLine:
    speaker_id: str
    role: Literal["pbp", "color"]
    text: str


def format_commentary_line(line: CommentaryLine, *, roster_short: str | None = None) -> str:
    """Single line for the move log: ``GORILLA: Roundhouse kick! Hall is rocked!``"""
    prefix = roster_short or line.speaker_id.upper()
    return f"{prefix}: {line.text.strip()}"
