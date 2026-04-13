"""UI rendering — shared helpers and the ``MatchRenderer`` protocol.

Game rules live in `game.py`. The terminal UI is `render_fixed.FixedLayoutRenderer`."""

from __future__ import annotations

import sys
from typing import Callable, Protocol, Sequence, runtime_checkable

from game import MatchState, PinSequence, move_landing_probability_label
from moves import BodyPosition, MoveRule
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
        filled = int(round(width * current / maximum))
        filled = max(0, min(width, filled))
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
    }[p]


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

    def show_status(self, state: MatchState, display_names: tuple[str, str]) -> None:
        """HP, position, momentum, rebound — called each update."""
        ...

    def round_header(self, is_player_turn: bool) -> None:
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
        """Outcome lines from the game layer (no per-turn move selection lines)."""
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
        """Pause after one wrestler's move resolves before the next move in the round."""
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
    ) -> int:
        """Show numbered moves with landing odds; return the chosen `rules` index."""
        ...

    def fatal_no_valid_moves(self) -> None:
        """Called when the engine has no legal moves (bug)."""
        ...
