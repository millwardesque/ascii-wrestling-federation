"""Fixed-layout terminal UI: clears and redraws the screen instead of scrolling."""

from __future__ import annotations

import re
import shutil
import sys
import textwrap
import time
from typing import Sequence

from game import MatchState, move_landing_probability_label
from moves import MoveRule
from ring_art import RING_HEADER_LINE, frames_for_move, idle_ring_lines
from render import InputFn, _default_input, colorize_nicknames, health_bar, position_label
from wrestlers import Wrestler


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


class FixedLayoutRenderer:
    """
    Full-screen redraw using ANSI clear + home. Last action shows each wrestler's
    most recent move narrative only.

    Set ``use_color=False`` for dumb terminals; color is auto-disabled when stdout
    is not a TTY.
    """

    def __init__(
        self,
        input_fn: InputFn | None = None,
        *,
        use_color: bool | None = None,
        animations: bool = True,
    ) -> None:
        self._input = input_fn or _default_input
        self._animations = animations
        self._last_player_log: str | None = None
        self._last_cpu_log: str | None = None
        self._state: MatchState | None = None
        self._names: tuple[str, str] | None = None
        self._round_num = 1
        self._player_turn = True
        self._banner = "BELL RINGS — singles match, pinfall only"
        self._header_extra = ""
        self._round_summary: str | None = None
        self._player_nick = ""
        self._cpu_nick = ""
        if use_color is None:
            use_color = sys.stdout.isatty()
        self._c = _Palette(enabled=use_color)

    def _width(self) -> int:
        try:
            return max(40, shutil.get_terminal_size().columns - 1)
        except OSError:
            return 72

    def _clear(self) -> None:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

    def _rule(self, char: str = "─") -> str:
        w = self._width()
        return char * w

    def _redraw_pre_match(self, body: list[str]) -> None:
        self._clear()
        w = self._width()
        title = (
            f"{self._c.bold}{self._c.accent}ASCII Wrestling Federation{self._c.reset}"
        )
        pad = max(0, (w - _strip_ansi(title).__len__()) // 2)
        print(" " * pad + title)
        print(self._c.dim + self._rule("─") + self._c.reset)
        for line in body:
            print(line)
        sys.stdout.flush()

    def _redraw_match(
        self,
        bottom_extra: list[str] | None = None,
        ring_lines: list[str] | None = None,
    ) -> None:
        self._clear()
        c = self._c
        w = self._width()
        hdr = (
            f"{c.bold}{c.accent}AWF{c.reset}  {c.dim}·{c.reset}  "
            f"Round {self._round_num}  {c.dim}·{c.reset}  "
            f"{c.highlight}{'Your turn' if self._player_turn else 'CPU turn'}{c.reset}"
        )
        if self._header_extra:
            hdr += f"\n{c.dim}{self._header_extra}{c.reset}"
        print(hdr)
        print(c.dim + self._rule("─") + c.reset)

        if self._state is not None and self._names is not None:
            st = self._state
            nm = self._names
            use_bar_color = bool(c.player)
            for i in range(2):
                wrestler = st.wrestlers[i]
                col = c.player if i == 0 else c.cpu
                hb = health_bar(
                    st.health[i],
                    wrestler.max_health,
                    bloodied=st.bloodied[i],
                    use_color=use_bar_color,
                )
                blood_note = (
                    f" {c.dim}(bloodied){c.reset}" if st.bloodied[i] and not use_bar_color else ""
                )
                rb = f" {c.warn}[Ropes: hot]{c.reset}" if st.rebound[i] else ""
                line1 = (
                    f"{col}{nm[i]:<18}{c.reset} "
                    f"HP {st.health[i]:3}/{wrestler.max_health:<3} {hb}{blood_note}{rb}"
                )
                line2 = (
                    f"     {c.dim}└─ {position_label(st.position[i])}  ·  "
                    f"momentum {st.momentum[i]}{c.reset}"
                )
                print(line1)
                print(line2)
                if i == 0:
                    print(c.dim + self._rule("·") + c.reset)

        if self._state is not None:
            rl = ring_lines if ring_lines is not None else idle_ring_lines(self._state)
            print(f"{c.bold}Ring{c.reset}")
            for line in rl:
                print(f"{c.dim}{line}{c.reset}")
        print(c.dim + self._rule("─") + c.reset)
        print(f"{c.bold}Last action{c.reset}")
        inner = w - 4
        wrap_w = max(20, inner - 4)
        use_ansi = bool(self._c.player)

        def emit_side(label: str, col: str, block: str | None) -> None:
            print(f"  {col}{label}{c.reset}")
            if not block or not block.strip():
                print(f"    {c.dim}(none yet){c.reset}")
                return
            for raw in block.splitlines():
                if not raw.strip():
                    continue
                for part in textwrap.wrap(raw, width=wrap_w, break_long_words=True):
                    colored = colorize_nicknames(
                        part,
                        self._player_nick,
                        self._cpu_nick,
                        use_ansi=use_ansi,
                    )
                    print(f"    {colored}")

        emit_side("You", c.player, self._last_player_log)
        emit_side("CPU", c.cpu, self._last_cpu_log)
        print(c.dim + self._rule("─") + c.reset)
        print(f"{c.bold}Round recap{c.reset}")
        if self._round_summary:
            inner = w - 4
            for part in textwrap.wrap(self._round_summary, width=inner, break_long_words=True):
                print(f"  {part}")
        else:
            print(f"  {c.dim}(after you and CPU both act){c.reset}")
        print(c.dim + self._rule("─") + c.reset)

        if bottom_extra:
            for line in bottom_extra:
                print(line)
        sys.stdout.flush()

    # --- MatchRenderer API ---

    def show_title(self) -> None:
        self._redraw_pre_match(
            [f"{self._c.dim}Pro-wrestling simulator — pinfall only{self._c.reset}", ""]
        )

    def choose_wrestler(self, roster: Sequence[Wrestler]) -> str:
        c = self._c
        err = ""
        while True:
            lines: list[str] = [
                f"{c.bold}Choose your wrestler{c.reset}",
                "",
            ]
            for idx, w in enumerate(roster, start=1):
                lines.append(f"  {c.accent}{idx}.{c.reset} {w.name}")
                lines.append(
                    f"      STR {w.strength}  AGI {w.agility}  END {w.endurance}  "
                    f"CHA {w.charisma}  (HP {w.max_health})"
                )
            lines.append("")
            if err:
                lines.append(f"{c.warn}{err}{c.reset}")
                lines.append("")
            lines.append(f"{c.dim}Enter number 1–{len(roster)}{c.reset}")
            self._redraw_pre_match(lines)
            raw = self._input(f"{c.bold}Choice:{c.reset} ").strip()
            if raw.isdigit():
                n = int(raw)
                if 1 <= n <= len(roster):
                    return roster[n - 1].id
            err = f"Invalid — pick 1–{len(roster)}."

    def show_opponent_chosen(self, opponent: Wrestler) -> None:
        c = self._c
        self._redraw_pre_match(
            [
                f"{c.bold}Opponent locked in{c.reset}",
                "",
                f"  {c.cpu}{opponent.name}{c.reset}",
                "",
                f"{c.dim}Press Enter to start the match…{c.reset}",
            ]
        )
        self._input("")

    def match_start_banner(self) -> None:
        self._banner = "BELL RINGS — singles match, pinfall only"
        self._header_extra = self._banner
        self._last_player_log = None
        self._last_cpu_log = None
        self._round_summary = None
        self._player_nick = ""
        self._cpu_nick = ""

    def show_status(self, state: MatchState, display_names: tuple[str, str]) -> None:
        self._state = state
        self._names = display_names
        self._redraw_match()

    def round_header(self, round_num: int, is_player_turn: bool) -> None:
        self._round_num = round_num
        self._player_turn = is_player_turn
        if round_num >= 2:
            self._header_extra = ""
        if is_player_turn:
            self._round_summary = None
        if self._state is not None:
            self._redraw_match()

    def show_move_log(
        self,
        text: str,
        *,
        player_nickname: str,
        cpu_nickname: str,
        actor_is_player: bool,
    ) -> None:
        self._player_nick = player_nickname
        self._cpu_nick = cpu_nickname
        if actor_is_player:
            self._last_player_log = text
            self._last_cpu_log = None
        else:
            self._last_cpu_log = text
        self._redraw_match()

    def wait_after_exchange_step(self) -> None:
        c = self._c
        self._redraw_match(bottom_extra=[f"{c.dim}Press Enter to continue…{c.reset}"])
        self._input("")

    def play_move_animation(self, rule: MoveRule, *, actor_is_player: bool) -> None:
        """Short ASCII ring animation after a move resolves (fixed mode only)."""
        if not self._animations or self._state is None:
            return
        for frame_body in frames_for_move(rule.move.id, rule.move, actor_is_player=actor_is_player):
            full = [RING_HEADER_LINE, *frame_body]
            self._redraw_match(ring_lines=full)
            time.sleep(0.14)

    def show_round_summary(self, line: str) -> None:
        self._round_summary = line
        if self._state is not None:
            self._redraw_match()

    def show_match_result_player_wins(self) -> None:
        self._end_screen("You win the match.", win=True)

    def show_match_result_cpu_wins(self) -> None:
        self._end_screen("The CPU wins the match.", win=False)

    def show_double_exhaustion(self) -> None:
        self._end_screen("The referee waves it off — double exhaustion.", win=None)

    def wait_after_match(self) -> None:
        """End screens already block in ``_end_screen``."""
        return

    def _end_screen(self, message: str, win: bool | None) -> None:
        c = self._c
        self._clear()
        w = self._width()
        if win is True:
            banner = f"{c.player}{c.bold}VICTORY{c.reset}"
        elif win is False:
            banner = f"{c.cpu}{c.bold}DEFEAT{c.reset}"
        else:
            banner = f"{c.warn}{c.bold}NO CONTEST{c.reset}"
        pad = max(0, (w - _strip_ansi(banner).__len__()) // 2)
        print(" " * pad + banner)
        print()
        msg_lines = textwrap.wrap(message, width=w - 4)
        for ml in msg_lines:
            pad2 = max(0, (w - len(ml)) // 2)
            print(" " * pad2 + ml)
        print()
        print(f"{c.dim}Press Enter to continue to wrestler select…{c.reset}")
        sys.stdout.flush()
        self._input("")

    def prompt_move_choice(
        self,
        state: MatchState,
        actor_idx: int,
        options: Sequence[tuple[int, MoveRule]],
    ) -> int:
        if not options:
            self.fatal_no_valid_moves()
            raise SystemExit(1)
        c = self._c
        n_opts = len(options)
        err = ""
        while True:
            lines: list[str] = [
                f"{c.bold}Your moves{c.reset}",
                "",
            ]
            for j, (_ix, rule) in enumerate(options, start=1):
                m = rule.move
                hint = f" — {m.description}" if len(m.description) < 60 else ""
                lbl = move_landing_probability_label(state, actor_idx, rule)
                lines.append(
                    f"  {c.accent}{j}.{c.reset} {m.name}{hint}  {c.dim}[{lbl}]{c.reset}"
                )
            lines.append("")
            if err:
                lines.append(f"{c.warn}{err}{c.reset}")
            self._redraw_match(bottom_extra=lines)
            raw = self._input(f"{c.bold}Choose move (1–{n_opts}):{c.reset} ").strip()
            if raw.isdigit():
                n = int(raw)
                if 1 <= n <= n_opts:
                    return options[n - 1][0]
            err = "Invalid choice — try again."

    def fatal_no_valid_moves(self) -> None:
        print("No valid moves (should not happen).", file=sys.stderr)


class _Palette:
    def __init__(self, *, enabled: bool) -> None:
        if enabled:
            self.reset = "\033[0m"
            self.bold = "\033[1m"
            self.dim = "\033[2m"
            self.accent = "\033[96m"
            self.highlight = "\033[97m"
            self.player = "\033[92m"
            self.cpu = "\033[91m"
            self.warn = "\033[93m"
        else:
            self.reset = self.bold = self.dim = ""
            self.accent = self.highlight = self.player = self.cpu = self.warn = ""
