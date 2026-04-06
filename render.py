"""UI rendering — all terminal output and prompts. Swap implementations for TUI, colors, etc.

Game rules live in `game.py`; this module only presents state and collects input."""

from __future__ import annotations

import sys
from typing import Callable, Protocol, Sequence, runtime_checkable

from game import MatchState
from moves import BodyPosition, MoveRule
from wrestlers import Wrestler


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
    """Contract for match UI. Implement with scrolling output, curses, rich, etc."""

    def show_title(self) -> None:
        """Opening banner before roster selection."""
        ...

    def choose_wrestler(self, roster: Sequence[Wrestler]) -> str:
        """Display roster and return selected wrestler `id`."""
        ...

    def show_opponent_chosen(self, opponent: Wrestler) -> None:
        """Announce CPU opponent after selection."""
        ...

    def match_start_banner(self) -> None:
        """Banner when the bell rings."""
        ...

    def show_status(self, state: MatchState, display_names: tuple[str, str]) -> None:
        """HP, position, momentum, rebound — called each update."""
        ...

    def round_header(self, round_num: int, is_player_turn: bool) -> None:
        ...

    def show_move_log(
        self,
        text: str,
        *,
        player_nickname: str,
        cpu_nickname: str,
    ) -> None:
        """Outcome lines from the game layer (no per-turn move selection lines)."""
        ...

    def show_round_summary(self, line: str) -> None:
        """One line after each full exchange (you + CPU); shown below Last action in fixed UI."""
        ...

    def show_match_result_player_wins(self) -> None:
        ...

    def show_match_result_cpu_wins(self) -> None:
        ...

    def show_double_exhaustion(self) -> None:
        ...

    def wait_after_match(self) -> None:
        """After win/lose/draw; block until user continues (then main returns to wrestler select)."""
        ...

    def prompt_move_choice(self, options: Sequence[tuple[int, MoveRule]]) -> int:
        """Show numbered moves; return the chosen `rules` index (first element of tuple)."""
        ...

    def fatal_no_valid_moves(self) -> None:
        """Called when the engine has no legal moves (bug)."""
        ...


class ScrollRenderer:
    """Default: append-only scrolling output (classic terminal)."""

    def __init__(self, input_fn: InputFn | None = None) -> None:
        self._input = input_fn or _default_input

    def show_title(self) -> None:
        print("\n*** WRESTLETERM — text ring simulator ***\n")

    def choose_wrestler(self, roster: Sequence[Wrestler]) -> str:
        print("\nChoose YOUR wrestler:")
        for idx, w in enumerate(roster, start=1):
            print(f"  {idx}. {w.name}")
            print(
                f"      STR {w.strength}  AGI {w.agility}  END {w.endurance}  "
                f"CHA {w.charisma}  (HP {w.max_health})"
            )
        while True:
            raw = self._input("Enter number (1–4): ").strip()
            if raw.isdigit():
                n = int(raw)
                if 1 <= n <= len(roster):
                    return roster[n - 1].id
            print("  Try again — pick 1, 2, 3, or 4.")

    def show_opponent_chosen(self, opponent: Wrestler) -> None:
        print(f"\nYour opponent: {opponent.name}")

    def match_start_banner(self) -> None:
        print("\n" + "=" * 60)
        print("  BELL RINGS — singles match, pinfall only")
        print("=" * 60)

    def show_status(self, state: MatchState, display_names: tuple[str, str]) -> None:
        w0, w1 = state.wrestlers
        print()
        use_bar_color = sys.stdout.isatty()
        for i, w in enumerate((w0, w1)):
            hb = health_bar(
                state.health[i],
                w.max_health,
                bloodied=state.bloodied[i],
                use_color=use_bar_color,
            )
            blood_note = " (bloodied)" if state.bloodied[i] and not use_bar_color else ""
            rb = " [Ropes: hot]" if state.rebound[i] else ""
            print(f"  {display_names[i]:16} HP {state.health[i]:3}/{w.max_health:<3} {hb}{blood_note}{rb}")
            print(f"    └─ {position_label(state.position[i])}  ·  momentum {state.momentum[i]}")
        print()

    def round_header(self, round_num: int, is_player_turn: bool) -> None:
        who = "Your turn" if is_player_turn else "CPU turn"
        print(f"— Round {round_num} · {who} —")

    def show_move_log(
        self,
        text: str,
        *,
        player_nickname: str,
        cpu_nickname: str,
    ) -> None:
        use = sys.stdout.isatty()
        for line in text.splitlines():
            if line.strip():
                print(colorize_nicknames(line, player_nickname, cpu_nickname, use_ansi=use))

    def show_round_summary(self, line: str) -> None:
        print(f"\n  Round recap · {line}\n")

    def show_match_result_player_wins(self) -> None:
        print("\nYou win the match.\n")

    def show_match_result_cpu_wins(self) -> None:
        print("\nThe CPU wins the match.\n")

    def show_double_exhaustion(self) -> None:
        print("\nThe referee waves it off — double exhaustion.\n")

    def wait_after_match(self) -> None:
        self._input("\nPress Enter to continue to wrestler select… ")

    def prompt_move_choice(self, options: Sequence[tuple[int, MoveRule]]) -> int:
        if not options:
            self.fatal_no_valid_moves()
            raise SystemExit(1)
        print("Your moves:")
        for j, (_rule_idx, rule) in enumerate(options, start=1):
            m = rule.move
            hint = f" — {m.description}" if len(m.description) < 70 else ""
            print(f"  {j}. {m.name}{hint}")
        n_opts = len(options)
        while True:
            raw = self._input(f"Choose move (1–{n_opts}): ").strip()
            if raw.isdigit():
                n = int(raw)
                if 1 <= n <= n_opts:
                    return options[n - 1][0]
            print("  Invalid choice.")

    def fatal_no_valid_moves(self) -> None:
        print("No valid moves (should not happen).", file=sys.stderr)
