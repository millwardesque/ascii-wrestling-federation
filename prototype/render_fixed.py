"""Fixed-layout terminal UI: clears and redraws the screen instead of scrolling.

On POSIX terminals, ``SIGWINCH`` triggers a redraw at the new width while the UI is
waiting for input. Windows consoles do not provide ``SIGWINCH``; resize takes effect
on the next full redraw after a keypress.
"""

from __future__ import annotations

import re
import shutil
import signal
import sys
import textwrap
from typing import Sequence

from awf_logo import AWF_LOGO_LINES, INTRO_LINES, PROMPT_LINE
from game import MatchState, move_landing_probability_label
from moves import MoveRule
from render import (
    InputFn,
    ReturnToTitle,
    _default_input,
    colorize_nicknames,
    health_bar,
    momentum_stars,
    position_label,
)
from terminal_keys import (
    read_any_key,
    read_digit_1_or_2,
    read_move_choice_line,
    read_title_key,
    wait_enter_or_esc,
)
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
    ) -> None:
        self._input = input_fn or _default_input
        self._last_player_log: str | None = None
        self._last_cpu_log: str | None = None
        self._state: MatchState | None = None
        self._names: tuple[str, str] | None = None
        self._player_turn = True
        self._player_turn_starts = 0
        self._banner = "BELL RINGS — singles match, pinfall only"
        self._header_extra = ""
        self._exchange_summary: str | None = None
        self._player_nick = ""
        self._cpu_nick = ""
        self._match_seed: int | None = None
        self._ui_layer: str = "none"
        self._last_match_bottom_extra: list[str] | None = None
        self._last_pre_match_body: list[str] | None = None
        self._sigwinch_busy = False
        if use_color is None:
            use_color = sys.stdout.isatty()
        self._c = _Palette(enabled=use_color)
        if (
            hasattr(signal, "SIGWINCH")
            and sys.stdin.isatty()
            and sys.stdout.isatty()
        ):
            signal.signal(signal.SIGWINCH, self._on_sigwinch)

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

    def _pad_cell_visible(self, s: str, width: int) -> str:
        plain = _strip_ansi(s)
        if len(plain) > width:
            return plain[: max(0, width - 1)] + "…"
        return s + (" " * (width - len(plain)))

    def _print_wrestler_header_panel(
        self,
        st: MatchState,
        nm: tuple[str, str],
        w: int,
        c: _Palette,
    ) -> None:
        """Boxed two-column header: names, HP bar, momentum stars, status (labels left on both sides)."""
        use_bar_color = bool(c.player)
        inner = w - 3
        a = inner // 2
        b = inner - a

        def row(left: str, right: str) -> None:
            L = self._pad_cell_visible(left, a)
            R = self._pad_cell_visible(right, b)
            print(
                f"{c.dim}│{c.reset}{L}{c.dim}│{c.reset}{R}{c.dim}│{c.reset}"
            )

        top = f"{c.dim}┌{('─' * a)}┬{('─' * b)}┐{c.reset}"
        bottom = f"{c.dim}└{('─' * a)}┴{('─' * b)}┘{c.reset}"
        print(top)

        def cell_line(row_idx: int, i: int) -> str:
            col = c.player if i == 0 else c.cpu
            cell_w = a if i == 0 else b
            if row_idx == 0:
                return f"{col}{nm[i]}{c.reset}"
            if row_idx == 1:
                wrestler = st.wrestlers[i]
                nums = f"{st.health[i]}/{wrestler.max_health}"
                blood_note = (
                    f" {c.dim}(bloodied){c.reset}"
                    if st.bloodied[i] and not use_bar_color
                    else ""
                )
                extra_vis = len(_strip_ansi(blood_note))
                nums_vis = len(nums)
                # "HP: " + sp + [bar] + sp + nums + extras
                reserve = 4 + 1 + 1 + nums_vis + extra_vis + 2
                bw = max(6, min(14, cell_w - reserve))
                hb = health_bar(
                    st.health[i],
                    wrestler.max_health,
                    width=bw,
                    bloodied=st.bloodied[i],
                    use_color=use_bar_color,
                )
                return (
                    f"{c.dim}HP:{c.reset} "
                    f"{hb} "
                    f"{col}{nums}{c.reset}"
                    f"{blood_note}"
                )
            if row_idx == 2:
                ms = momentum_stars(st.momentum[i])
                return f"{c.dim}MOM:{c.reset} {col}{ms}{c.reset}"
            pos = position_label(st.position[i]).title()
            return f"{c.dim}STATUS:{c.reset} {col}{pos}{c.reset}"

        for row_idx in range(4):
            row(cell_line(row_idx, 0), cell_line(row_idx, 1))

        print(bottom)

    def _on_sigwinch(self, signum: int, frame: object | None) -> None:
        """Redraw the current full-screen layout when the terminal is resized (POSIX)."""
        if self._sigwinch_busy:
            return
        self._sigwinch_busy = True
        try:
            if self._ui_layer == "pause":
                self._paint_pause_menu()
            elif self._ui_layer == "title":
                self._paint_awf_title_screen()
            elif self._ui_layer == "match" and self._state is not None:
                self._redraw_match(self._last_match_bottom_extra)
            elif self._ui_layer == "pre_match" and self._last_pre_match_body is not None:
                self._redraw_pre_match(self._last_pre_match_body)
        except Exception:
            pass
        finally:
            self._sigwinch_busy = False

    def _redraw_pre_match(self, body: list[str]) -> None:
        self._last_pre_match_body = list(body)
        self._ui_layer = "pre_match"
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

    def _redraw_match(self, bottom_extra: list[str] | None = None) -> None:
        self._last_match_bottom_extra = bottom_extra
        self._ui_layer = "match"
        self._clear()
        c = self._c
        w = self._width()
        hdr = (
            f"{c.bold}{c.accent}AWF{c.reset}  {c.dim}·{c.reset}  "
            f"{c.highlight}{'Your turn' if self._player_turn else 'CPU turn'}{c.reset}"
        )
        if self._header_extra:
            hdr += f"\n{c.dim}{self._header_extra}{c.reset}"
        if self._match_seed is not None:
            hdr += f"\n{c.dim}Match seed: {self._match_seed}{c.reset}"
        print(hdr)
        print(c.dim + self._rule("─") + c.reset)

        if self._state is not None and self._names is not None:
            self._print_wrestler_header_panel(self._state, self._names, w, c)

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
        print(f"{c.bold}Exchange recap{c.reset}")
        if self._exchange_summary:
            inner = w - 4
            for part in textwrap.wrap(self._exchange_summary, width=inner, break_long_words=True):
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
        self._draw_awf_title_screen()

    def _print_awf_logo(self) -> None:
        """Centered AWF block logo (accent); shared by title and pause screens."""
        c = self._c
        w = self._width()
        for line in AWF_LOGO_LINES:
            pad = max(0, (w - len(line)) // 2)
            print(" " * pad + f"{c.accent}{line}{c.reset}")
        print()

    def _paint_awf_title_screen(self) -> None:
        """Title screen pixels only (no input). Used for initial draw and SIGWINCH."""
        self._clear()
        self._print_awf_logo()
        c = self._c
        w = self._width()
        for line in INTRO_LINES:
            pad = max(0, (w - len(line)) // 2)
            print(" " * pad + f"{c.dim}{line}{c.reset}")
        print()
        pad = max(0, (w - len(PROMPT_LINE)) // 2)
        print(" " * pad + f"{c.bold}{PROMPT_LINE}{c.reset}")
        sys.stdout.flush()

    def _draw_awf_title_screen(self) -> None:
        self._paint_awf_title_screen()
        self._ui_layer = "title"
        if read_title_key() == "quit":
            self._clear()
            self._ui_layer = "none"
            raise SystemExit(0)
        self._ui_layer = "none"

    def _paint_pause_menu(self) -> None:
        """Pause menu pixels only (no input). Used for initial draw and SIGWINCH."""
        c = self._c
        self._clear()
        self._print_awf_logo()
        w = self._width()
        title = "PAUSED"
        pad = max(0, (w - len(title)) // 2)
        print(" " * pad + f"{c.bold}{title}{c.reset}")
        print()
        opt1 = "1. Resume"
        opt2 = "2. Exit to title screen"
        print(" " * max(0, (w - len(opt1)) // 2) + opt1)
        print(" " * max(0, (w - len(opt2)) // 2) + opt2)
        print()
        print(f"{c.dim}Press 1 or 2{c.reset}")
        sys.stdout.flush()

    def _pause_menu(self) -> None:
        self._ui_layer = "pause"
        self._paint_pause_menu()
        choice = read_digit_1_or_2()
        if choice == "2":
            raise ReturnToTitle()

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
            lines.append(
                f"{c.dim}Enter number 1–{len(roster)}  ·  ESC: main menu{c.reset}"
            )
            self._redraw_pre_match(lines)
            sys.stdout.write(f"{c.bold}Choice:{c.reset} ")
            sys.stdout.flush()
            raw = read_move_choice_line()
            if raw == "ESC":
                raise ReturnToTitle()
            raw = raw.strip()
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
                f"{c.dim}Press any key to start the match…{c.reset}",
            ]
        )
        read_any_key()

    def match_start_banner(self, *, match_seed: int | None = None) -> None:
        self._last_pre_match_body = None
        self._banner = "BELL RINGS — singles match, pinfall only"
        self._header_extra = self._banner
        self._match_seed = match_seed
        self._player_turn_starts = 0
        self._last_player_log = None
        self._last_cpu_log = None
        self._exchange_summary = None
        self._player_nick = ""
        self._cpu_nick = ""

    def show_status(self, state: MatchState, display_names: tuple[str, str]) -> None:
        self._state = state
        self._names = display_names
        self._redraw_match()

    def round_header(self, is_player_turn: bool) -> None:
        self._player_turn = is_player_turn
        if is_player_turn:
            self._player_turn_starts += 1
            if self._player_turn_starts >= 2:
                self._header_extra = ""
            self._exchange_summary = None
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
        while True:
            self._redraw_match(
                bottom_extra=[f"{c.dim}Enter: continue  ·  ESC: pause{c.reset}"]
            )
            if wait_enter_or_esc() == "enter":
                return
            self._pause_menu()

    def show_exchange_recap(self, line: str) -> None:
        self._exchange_summary = line
        if self._state is not None:
            self._redraw_match()

    def show_match_result_player_wins(self) -> None:
        self._end_screen("You win the match.", win=True)

    def show_match_result_cpu_wins(self) -> None:
        self._end_screen("The CPU wins the match.", win=False)

    def wait_after_match(self) -> None:
        """End screens already block in ``_end_screen``."""
        return

    def _end_screen(self, message: str, win: bool | None) -> None:
        self._ui_layer = "end"
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
            sys.stdout.write(f"{c.bold}Choose move (1–{n_opts}):{c.reset} ")
            sys.stdout.flush()
            raw = read_move_choice_line()
            if raw == "ESC":
                self._pause_menu()
                continue
            raw = raw.strip()
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
