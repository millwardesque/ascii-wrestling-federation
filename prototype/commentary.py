"""Commentary engine stub — renders ``MatchEvent`` facts into booth lines.

Full template pools and turn choreography live here once ``apply_move`` emits
events. For now only booth intro helpers are wired; move narration still comes
from ``game.py`` f-strings.
"""

from __future__ import annotations

from commentators import CommentatorPair
from commentary_events import CommentaryLine, MatchEvent


class CommentaryEngine:
    def __init__(self, team: CommentatorPair) -> None:
        self._team = team

    @property
    def team(self) -> CommentatorPair:
        return self._team

    def booth_intro_lines(self) -> tuple[CommentaryLine, ...]:
        """Lines shown when the bell rings."""
        pbp = self._team.pbp()
        color = self._team.color()
        return (
            CommentaryLine(
                speaker_id=pbp.id,
                role="pbp",
                text=f"{pbp.name} here with {color.name} — let's get this one underway!",
            ),
            CommentaryLine(
                speaker_id=color.id,
                role="color",
                text="I've got a feeling somebody's walking out unhappy.",
            ),
        )

    def render_turn(self, events: list[MatchEvent]) -> list[CommentaryLine]:
        """Future: map events to alternating PBP/color lines."""
        raise NotImplementedError(
            "CommentaryEngine.render_turn needs apply_move to emit MatchEvent lists"
        )
