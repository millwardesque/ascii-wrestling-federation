"""UI rendering — shared helpers and the ``MatchRenderer`` protocol.

Game rules live in `game.py`, scheduling in `scheduler.py`. The terminal UI is
`render_fixed.FixedLayoutRenderer`.

The protocol differs from a strictly alternating game in three places: there is no round
header because there are no rounds, ``show_status`` carries the projected turn order, and
``prompt_move_choice`` gets the live queue so each option can show its tempo cost.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

from game import MatchState, PinSequence
from moves import BodyPosition, MoveRule
from scheduler import TurnQueue
from wrestlers import Wrestler


class ReturnToTitle(Exception):
    """User left the match (pause menu) to return to the title screen."""


InputFn = Callable[[str], str]


def _default_input(prompt: str) -> str:
    return input(prompt)


_ANSI_BLOOD = "\033[91m"
_ANSI_BAR_RESET = "\033[0m"


def health_bar(
    current: int,
    maximum: int,
    width: int = 20,
    *,
    bloodied: bool = False,
    use_color: bool = False,
) -> str:
    """Plain text bar; when ``bloodied`` and ``use_color``, render the bar in red (TTY easter egg)."""
    if maximum <= 0:
        bar = "[" + "?" * width + "]"
    else:
        filled = max(0, min(width, round(width * current / maximum)))
        bar = "[" + "█" * filled + "·" * (width - filled) + "]"
    if bloodied and use_color:
        return f"{_ANSI_BLOOD}{bar}{_ANSI_BAR_RESET}"
    return bar


def momentum_stars(level: int, *, width: int = 5) -> str:
    """Bracketed star row for momentum (0–width), e.g. ``[★★☆☆☆]``."""
    m = max(0, min(width, int(level)))
    return f"[{'★' * m}{'☆' * (width - m)}]"


def position_label(p: BodyPosition) -> str:
    return {
        BodyPosition.STANDING: "standing",
        BodyPosition.RUNNING_ROPES: "running the ropes",
        BodyPosition.GROUNDED: "on the mat",
        BodyPosition.CORNER: "in the corner",
        BodyPosition.TOP_ROPE: "on the TOP ROPE",
        BodyPosition.GRAPPLED: "locked up",
    }[p]


def turn_queue_strip(up_next: Sequence[int], labels: tuple[str, str]) -> str:
    """Projected turn order as a single readable line.

    The first entry is whoever is acting now, so a player seeing ``YOU · YOU · Hall`` can
    read a flurry off the strip before committing to it.
    """
    if not up_next:
        return "(queue empty)"
    return "  ·  ".join(labels[i] for i in up_next)


def tempo_label(conceded: int) -> str:
    """Short menu tag for what a move costs in initiative."""
    if conceded <= 0:
        return "fast — you go again"
    if conceded == 1:
        return "even — they answer once"
    return f"slow — they get {conceded}"


# Match FixedLayoutRenderer header: green player, red CPU (when use_ansi=True)
_ANSI_PLAYER = "\033[92m"
_ANSI_CPU = "\033[91m"
_ANSI_RESET = "\033[0m"


def colorize_nicknames(
    line: str,
    player_nickname: str,
    cpu_nickname: str,
    *,
    use_ansi: bool = True,
) -> str:
    """Highlight wrestler nicknames in log text (longest first to reduce partial matches)."""
    if not use_ansi:
        return line
    if not sys.stdout.isatty():
        return line
    pairs: list[tuple[str, str]] = [
        (player_nickname, _ANSI_PLAYER),
        (cpu_nickname, _ANSI_CPU),
    ]
    pairs = [(n, c) for n, c in pairs if n]
    pairs.sort(key=lambda x: -len(x[0]))
    out = line
    for name, code in pairs:
        if name in out:
            out = out.replace(name, f"{code}{name}{_ANSI_RESET}")
    return out


@runtime_checkable
class MatchRenderer(Protocol):
    """Contract for match UI. Implement with fixed layout, curses, rich, etc."""

    @property
    def action_count(self) -> int:
        """Total actions resolved so far, both wrestlers combined."""
        ...

    def show_title(self) -> None:
        """Opening banner before roster selection."""
        ...

    def choose_wrestler(self, roster: Sequence[Wrestler]) -> str:
        """Display roster and return selected wrestler `id`."""
        ...

    def show_opponent_chosen(self, opponent: Wrestler) -> None:
        """Announce CPU opponent after selection."""
        ...

    def match_start_banner(self, *, match_seed: int | None = None) -> None:
        """Banner when the bell rings; ``match_seed`` is set for replay/debug when applicable."""
        ...

    def show_status(
        self,
        state: MatchState,
        display_names: tuple[str, str],
        *,
        up_next: Sequence[int] = (),
    ) -> None:
        """HP, position, momentum, and the projected turn order — called each update."""
        ...

    def record_momentum(self, state: MatchState) -> None:
        """Record one momentum chart sample after an action resolves."""
        ...

    def begin_action(self, is_player_turn: bool) -> None:
        """Announce whose action is starting. Replaces the round header; there are no rounds."""
        ...

    def show_move_log(
        self,
        text: str,
        *,
        player_nickname: str,
        cpu_nickname: str,
        actor_is_player: bool,
        move_name: str,
    ) -> None:
        """Outcome lines from the game layer (no per-action move selection lines)."""
        ...

    def show_pin_sequence(
        self,
        sequence: PinSequence,
        *,
        player_nickname: str,
        cpu_nickname: str,
        actor_is_player: bool,
        move_name: str,
    ) -> None:
        """Display a pinfall attempt with pauses between referee counts (see ``PinSequence``)."""
        ...

    def wait_between_moves(self) -> None:
        """Pause after an action resolves before the next wrestler comes up the queue."""
        ...

    def show_match_result_player_wins(self) -> None:
        ...

    def show_match_result_cpu_wins(self) -> None:
        ...

    def wait_after_match(self) -> None:
        """After win/lose/draw; block until user continues (then main returns to wrestler select)."""
        ...

    def prompt_move_choice(
        self,
        state: MatchState,
        actor_idx: int,
        options: Sequence[tuple[int, MoveRule]],
        queue: TurnQueue,
    ) -> int:
        """Show numbered moves with landing odds and tempo cost; return the chosen `rules` index."""
        ...

    def fatal_no_valid_moves(self) -> None:
        """Called when the engine has no legal moves (bug)."""
        ...
