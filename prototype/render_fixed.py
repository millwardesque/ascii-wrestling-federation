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
import time
from typing import NamedTuple, Sequence

from awf_logo import AWF_LOGO_LINES, INTRO_LINES, PROMPT_LINE
from commentators import CommentatorPair
from commentary import CommentaryEngine
from commentary_events import format_commentary_line
from config import get_config
from game import (
    MatchState,
    PinSequence,
    loop_pressure_for,
    move_is_stale,
    move_landing_probability_label,
)
from moves import BodyPosition, MoveRule
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
)
from wrestlers import Wrestler


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


class _ActionBlock(NamedTuple):
    is_player: bool
    move_name: str
    log_text: str


class _MoveChoice(NamedTuple):
    rule_index: int
    rule: MoveRule
    intent: str
    note: str
    score: float
    # Loop-taxed right now: never gets an intent slot, so the menu stops recommending it.
    stale: bool = False


_MOVE_INTENT_ORDER = (
    "Finish",
    "Big swing",
    "Grapple control",
    "Set up position",
    "Safe offense",
    "Reset / recover",
    "Pressure",
)


def _momentum_chart_lines(
    history: Sequence[tuple[int, int]],
    width: int,
    c: "_Palette",
) -> list[str]:
    lines = [
        f"{c.bold}Momentum trend{c.reset} {c.dim}(end of CPU turns){c.reset}"
    ]
    if not history:
        lines.append(f"  {c.dim}(no full exchanges yet){c.reset}")
        return lines

    max_level = 5
    label_w = 4
    max_cols = max(8, width - label_w - 3)
    samples = list(history[-max_cols:])
    axis = "─" * len(samples)
    for level in range(max_level, 0, -1):
        bars = "".join("█" if player >= level else " " for player, _ in samples)
        lines.append(f"{c.player}{level:>3}{c.reset} │{c.player}{bars}{c.reset}")
    lines.append(f"{c.dim}  0 ┼{axis}{c.reset}")
    for level in range(1, max_level + 1):
        bars = "".join("█" if cpu >= level else " " for _, cpu in samples)
        lines.append(f"{c.cpu}{-level:>3}{c.reset} │{c.cpu}{bars}{c.reset}")
    return lines


def _move_choice_details(
    state: MatchState, actor_idx: int, rule_index: int, rule: MoveRule
) -> _MoveChoice:
    m = rule.move
    target_idx = 1 - actor_idx
    hp_frac = state.health[actor_idx] / max(1, state.wrestlers[actor_idx].max_health)
    target_hp_frac = state.health[target_idx] / max(
        1, state.wrestlers[target_idx].max_health
    )
    score = float(m.base_damage * 2 + m.momentum_gain * 7 - m.difficulty * 2)

    if m.is_pin:
        fin_bonus = state.pin_bonus_next_cover[actor_idx]
        note = "try to end it now; stronger when they're worn down"
        score = 120.0 + (1.0 - target_hp_frac) * 40.0
        if state.cover_heat[target_idx]:
            note = "COVER HEAT — cash the knockdown before they rise"
            score += 25.0
        elif fin_bonus > 0:
            note = "FINISHER — hook the leg; the crowd expects the cover"
            score += 70.0 + float(fin_bonus) * 3.0
        return _MoveChoice(
            rule_index,
            rule,
            "Finish",
            note,
            score,
        )
    if m.is_finisher:
        note = "cash in momentum for a match-ending swing"
        if state.groggy[target_idx]:
            note = "TARGET GROGGY: cash in for a match-ending swing"
        return _MoveChoice(
            rule_index,
            rule,
            "Finish",
            note,
            105.0 + score,
        )

    if m.id in {"shake_groggy", "desperation_strike"}:
        return _MoveChoice(
            rule_index,
            rule,
            "Reset / recover",
            "clear the haze before they punish you",
            100.0,
        )
    if m.id in {"get_up", "escape_corner", "feet_plant", "dismount_top"}:
        note = "get back to a safer ring position"
        if m.id == "get_up":
            note = "stand before they cover you; misses build escape momentum"
            if state.cover_heat[actor_idx]:
                note = "COVER HEAT — rising is harder; they may go for the pin"
        return _MoveChoice(
            rule_index,
            rule,
            "Reset / recover",
            note,
            85.0,
        )
    if m.id == "recover":
        return _MoveChoice(
            rule_index,
            rule,
            "Reset / recover",
            "small stamina recovery; low risk, low tempo",
            20.0 + (1.0 - hp_frac) * 35.0,
        )

    if m.id == "collar_elbow":
        pressure = loop_pressure_for(state, actor_idx, m)
        stale = move_is_stale(state, actor_idx, m)
        note = "enter a tie-up to unlock throws and whips; repeat loops lose steam"
        if stale:
            note = "tie-up is going stale — whip out or mix strikes, don't re-tie"
        return _MoveChoice(
            rule_index,
            rule,
            "Grapple control",
            note,
            78.0 + score - float(pressure) * 12.0,
            stale,
        )
    if m.id == "grapple_counter":
        pressure = loop_pressure_for(state, actor_idx, m)
        stale = move_is_stale(state, actor_idx, m)
        note = "reverse the tie-up — you take the lock and can throw next"
        if stale:
            note = "same counter is getting predictable — break clean instead of taking the lock"
        return _MoveChoice(
            rule_index,
            rule,
            "Grapple control",
            note,
            70.0 + score - float(pressure) * 14.0,
            stale,
        )
    if m.id == "break_grapple":
        return _MoveChoice(
            rule_index,
            rule,
            "Reset / recover",
            "peel the hands and reset without the counter chip",
            68.0 + float(state.counter_loop_pressure[actor_idx]) * 10.0,
        )
    if m.target_grappled:
        note = "pay off the tie-up with a control move"
        if m.id in {"irish_whip", "turnbuckle_whip"}:
            note = "exit the tie-up into a real setup — clears a stale loop"
        elif state.grapple_loop_pressure[actor_idx] >= 2:
            note = "chip throw keeps the loop warm — whip out to break the cycle"
        return _MoveChoice(
            rule_index,
            rule,
            "Grapple control",
            note,
            76.0 + score + float(state.grapple_loop_pressure[actor_idx]) * 6.0,
        )

    if (
        m.target_after in (BodyPosition.CORNER, BodyPosition.RUNNING_ROPES)
        or m.actor_after in (BodyPosition.TOP_ROPE, BodyPosition.RUNNING_ROPES)
        or m.is_climb
        or m.is_hit_ropes
        or m.id in {"pickup", "drag_to_center", "pull_off_top"}
    ):
        setup = loop_pressure_for(state, actor_idx, m)
        stale = move_is_stale(state, actor_idx, m)
        note = "changes ring position to unlock a stronger follow-up"
        score_adj = -float(setup) * 14.0
        if stale and m.is_climb:
            note = "they've seen this climb — mix in mat work or cash a top-rope payoff"
        elif stale and m.id == "dismount_top":
            note = "empty dismounts waste the setup — climb down only when you must"
        return _MoveChoice(
            rule_index,
            rule,
            "Set up position",
            note,
            72.0 + score + score_adj,
            stale,
        )

    if m.requires_target_groggy or m.difficulty >= 5 or m.base_damage >= 17:
        note = "riskier hit, but it can flip the match"
        if m.requires_target_groggy and state.groggy[target_idx]:
            note = "TARGET GROGGY payoff: heavy damage is available now"
        if m.actor_top:
            note = "top-rope payoff: high risk, huge crowd pop"
        elif m.actor_running_ropes_only or m.target_running_ropes:
            note = "rope sprint payoff: capitalize while they're on the ropes"
        return _MoveChoice(
            rule_index,
            rule,
            "Big swing",
            note,
            82.0 + score,
        )

    if m.difficulty <= 3 and m.base_damage <= 10:
        return _MoveChoice(
            rule_index,
            rule,
            "Safe offense",
            "steady damage and momentum without overcommitting",
            55.0 + score,
        )

    return _MoveChoice(
        rule_index,
        rule,
        "Pressure",
        "keep control and build toward a bigger chance",
        45.0 + score,
    )


def _curate_move_choices(
    state: MatchState,
    actor_idx: int,
    options: Sequence[tuple[int, MoveRule]],
    *,
    max_choices: int = 5,
) -> list[_MoveChoice]:
    choices = [
        _move_choice_details(state, actor_idx, rule_index, rule)
        for rule_index, rule in options
    ]

    def _intent_rank(ch: _MoveChoice) -> int:
        if ch.intent in _MOVE_INTENT_ORDER:
            return _MOVE_INTENT_ORDER.index(ch.intent)
        return len(_MOVE_INTENT_ORDER)

    # Stale moves sort last regardless of intent, so a loop-taxed option can never keep
    # the top slot just because its intent ranks high.
    def _menu_key(ch: _MoveChoice) -> tuple[int, int, float]:
        return (1 if ch.stale else 0, _intent_rank(ch), -ch.score)

    choices.sort(key=lambda ch: (1 if ch.stale else 0, -ch.score, _intent_rank(ch)))
    if len(choices) <= max_choices:
        return sorted(choices, key=_menu_key)

    selected: list[_MoveChoice] = []
    selected_ids: set[str] = set()
    pin_choice = next((ch for ch in choices if ch.rule.move.is_pin), None)
    if pin_choice is not None:
        selected.append(pin_choice)
        selected_ids.add(pin_choice.rule.move.id)

    for intent in _MOVE_INTENT_ORDER:
        intent_choices = [
            ch
            for ch in choices
            if ch.intent == intent
            and not ch.stale
            and ch.rule.move.id not in selected_ids
        ]
        if not intent_choices:
            continue
        pick = intent_choices[0]
        selected.append(pick)
        selected_ids.add(pick.rule.move.id)
        if len(selected) >= max_choices:
            break

    for choice in choices:
        if len(selected) >= max_choices:
            break
        if choice.rule.move.id not in selected_ids:
            selected.append(choice)
            selected_ids.add(choice.rule.move.id)

    return sorted(selected, key=_menu_key)


class FixedLayoutRenderer:
    """
    Full-screen redraw using ANSI clear + home. The middle block shows an
    instructional heading plus at most one recent result per wrestler (chronological,
    newest at the bottom).

    Set ``use_color=False`` for dumb terminals; color is auto-disabled when stdout
    is not a TTY.

    When ``animate_move_log`` is True (default), new action-log lines auto-scroll
    upward one line at a time (skipped for non-TTY stdout). Pass False to avoid
    extra redraws and sleeps (e.g. tests or slow links).
    """

    def __init__(
        self,
        input_fn: InputFn | None = None,
        *,
        use_color: bool | None = None,
        animate_move_log: bool = True,
    ) -> None:
        self._input = input_fn or _default_input
        self._animate_move_log = animate_move_log
        self._action_chain: list[_ActionBlock] = []
        self._momentum_history: list[tuple[int, int]] = []
        self._show_momentum_chart = False
        self._instruction_heading = "Choose your move!"
        self._action_log_override_lines: list[str] | None = None
        self._state: MatchState | None = None
        self._names: tuple[str, str] | None = None
        self._player_turn = True
        self._player_turn_starts = 0
        self._banner = "BELL RINGS — singles match, pinfall only"
        self._header_extra = ""
        self._commentary_team: CommentatorPair | None = None
        self._booth_intro_lines: list[str] = []
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
            if st.groggy[i]:
                pos = f"Groggy — {pos.lower()}"
            return f"{c.dim}STATUS:{c.reset} {col}{pos}{c.reset}"

        for row_idx in range(4):
            row(cell_line(row_idx, 0), cell_line(row_idx, 1))

        print(bottom)

    def _push_action_block(
        self, *, is_player: bool, move_name: str, log_text: str
    ) -> None:
        """Keep one block per wrestler; new move for that wrestler replaces their old
        block and is appended at the bottom (older opponent block shifts up)."""
        self._action_chain = [
            b for b in self._action_chain if b.is_player != is_player
        ]
        self._action_chain.append(
            _ActionBlock(is_player=is_player, move_name=move_name, log_text=log_text)
        )

    def _print_instruction_heading(self, c: _Palette) -> None:
        h = self._instruction_heading
        if h in {"Pinfall attempt…", "Submission attempt…"}:
            print(f"{c.dim}{h}{c.reset}")
        elif h.startswith(">"):
            print(f"{c.bold}{c.dim}{h}{c.reset}")
        else:
            print(f"{c.bold}{c.accent}{h}{c.reset}")

    def _action_block_lines(
        self,
        block: _ActionBlock,
        wrap_w: int,
        c: _Palette,
        use_ansi: bool,
    ) -> list[str]:
        col = c.player if block.is_player else c.cpu
        if self._names is not None:
            label = self._names[0] if block.is_player else self._names[1]
        else:
            label = "You" if block.is_player else "CPU"
        lines = [f"  {col}{label} uses {block.move_name}!{c.reset}"]
        if not block.log_text or not block.log_text.strip():
            return lines
        for raw in block.log_text.splitlines():
            if not raw.strip():
                continue
            for part in textwrap.wrap(raw, width=wrap_w, break_long_words=True):
                colored = colorize_nicknames(
                    part,
                    self._player_nick,
                    self._cpu_nick,
                    use_ansi=use_ansi,
                )
                lines.append(f"    {self._style_commentary_line(colored, c)}")
        return lines

    def _action_log_lines(
        self,
        wrap_w: int,
        c: _Palette,
        use_ansi: bool,
        *,
        action_chain: Sequence[_ActionBlock] | None = None,
    ) -> list[str]:
        chain = self._action_chain if action_chain is None else action_chain
        if not chain:
            if self._booth_intro_lines:
                return [
                    self._style_commentary_line(line, c)
                    for line in self._booth_intro_lines
                ]
            return [f"  {c.dim}(no actions yet){c.reset}"]
        lines: list[str] = []
        for block in chain:
            lines.extend(self._action_block_lines(block, wrap_w, c, use_ansi))
            lines.append("")
        return lines

    def _current_action_log_lines(self) -> list[str]:
        c = self._c
        inner = self._width() - 4
        wrap_w = max(20, inner - 4)
        use_ansi = bool(self._c.player)
        return self._action_log_lines(wrap_w, c, use_ansi)

    def _style_commentary_line(self, line: str, c: "_Palette") -> str:
        """Bold play-by-play prefixes; dim color commentary."""
        if self._commentary_team is None or not c.bold:
            return line
        pbp = self._commentary_team.pbp().short
        color = self._commentary_team.color().short
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if stripped.startswith(f"{pbp}:"):
            return f"{indent}{c.bold}{stripped}{c.reset}"
        if stripped.startswith(f"{color}:"):
            return f"{indent}{c.dim}{stripped}{c.reset}"
        return line

    def _print_momentum_chart(
        self,
        history: Sequence[tuple[int, int]],
        w: int,
        c: "_Palette",
    ) -> None:
        for line in _momentum_chart_lines(history, w, c):
            print(line)

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

        if self._show_momentum_chart:
            print(c.dim + self._rule("─") + c.reset)
            self._print_momentum_chart(self._momentum_history, w, c)
        print(c.dim + self._rule("─") + c.reset)
        inner = w - 4
        wrap_w = max(20, inner - 4)
        use_ansi = bool(self._c.player)
        self._print_instruction_heading(c)
        if self._action_log_override_lines is not None:
            for line in self._action_log_override_lines:
                print(line)
        else:
            for line in self._action_log_lines(wrap_w, c, use_ansi):
                print(line)
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

    def match_start_banner(
        self,
        *,
        match_seed: int | None = None,
        commentary_team: CommentatorPair | None = None,
    ) -> None:
        self._last_pre_match_body = None
        self._banner = "BELL RINGS — singles match, pinfall only"
        self._match_seed = match_seed
        self._player_turn_starts = 0
        self._action_chain = []
        self._momentum_history = []
        self._instruction_heading = "Choose your move!"
        self._action_log_override_lines = None
        self._player_nick = ""
        self._cpu_nick = ""
        if commentary_team is not None:
            self._commentary_team = commentary_team
            self._header_extra = commentary_team.intro_line()
            engine = CommentaryEngine(commentary_team)
            self._booth_intro_lines = [
                f"  {format_commentary_line(line, roster_short=engine.speaker_short(line))}"
                for line in engine.booth_intro_lines()
            ]
        else:
            self._commentary_team = None
            self._header_extra = self._banner
            self._booth_intro_lines = []

    def show_status(self, state: MatchState, display_names: tuple[str, str]) -> None:
        self._state = state
        self._names = display_names
        self._redraw_match()

    def record_momentum(self, state: MatchState) -> None:
        self._momentum_history.append((state.momentum[0], state.momentum[1]))

    def _toggle_momentum_chart(self) -> None:
        self._show_momentum_chart = not self._show_momentum_chart
        self._redraw_match()

    def round_header(self, is_player_turn: bool) -> None:
        self._player_turn = is_player_turn
        if is_player_turn:
            self._player_turn_starts += 1
            self._instruction_heading = "Choose your move!"
        else:
            self._instruction_heading = "> CPU TURN..."
        if self._state is not None:
            self._redraw_match()

    def show_move_log(
        self,
        text: str,
        *,
        player_nickname: str,
        cpu_nickname: str,
        actor_is_player: bool,
        move_name: str,
    ) -> None:
        self._player_nick = player_nickname
        self._cpu_nick = cpu_nickname
        old_lines = self._current_action_log_lines()
        self._push_action_block(
            is_player=actor_is_player, move_name=move_name, log_text=text
        )
        self._instruction_heading = (
            "> CPU TURN..." if actor_is_player else "Choose your move!"
        )
        self._play_move_log_scroll(old_lines)

    def _pin_sleep(self, sec: float) -> None:
        if sec > 0 and sys.stdout.isatty():
            time.sleep(sec)

    def show_pin_sequence(
        self,
        sequence: PinSequence,
        *,
        player_nickname: str,
        cpu_nickname: str,
        actor_is_player: bool,
        move_name: str,
    ) -> None:
        """Pre-computed counts; pause after each step's ``delay_after`` before the next."""
        self._player_nick = player_nickname
        self._cpu_nick = cpu_nickname
        acc: list[str] = []
        if sequence.preamble_lines:
            acc.extend(sequence.preamble_lines)
            self._push_action_block(
                is_player=actor_is_player,
                move_name=move_name,
                log_text="\n".join(acc),
            )
            self._instruction_heading = sequence.heading
            self._redraw_match()
        for step_lines, delay_after in sequence.steps:
            acc.extend(step_lines)
            self._push_action_block(
                is_player=actor_is_player,
                move_name=move_name,
                log_text="\n".join(acc),
            )
            self._instruction_heading = sequence.heading
            self._redraw_match()
            self._pin_sleep(delay_after)
        self._instruction_heading = (
            "> CPU TURN..." if actor_is_player else "Choose your move!"
        )
        self._redraw_match()

    def _new_action_log_lines(
        self, old_lines: Sequence[str], new_lines: Sequence[str]
    ) -> list[str]:
        overlap_len = 0
        max_overlap = min(len(old_lines), len(new_lines))
        for n in range(max_overlap, 0, -1):
            if list(old_lines[-n:]) == list(new_lines[:n]):
                overlap_len = n
                break
        return list(new_lines[overlap_len:]) or list(new_lines[-1:])

    def _play_move_log_scroll(self, old_lines: Sequence[str]) -> None:
        """Animate new log lines by shifting the visible log upward one row per line."""
        new_lines = self._current_action_log_lines()
        if not self._animate_move_log or not sys.stdout.isatty():
            self._action_log_override_lines = None
            self._redraw_match()
            return

        frame_lines = list(old_lines)
        viewport_h = max(len(old_lines), len(new_lines))
        # frame_lines += [""] * max(0, viewport_h - len(frame_lines))
        for line in self._new_action_log_lines(old_lines, new_lines):
            frame_lines = (frame_lines + [line])[-viewport_h:]
            self._action_log_override_lines = frame_lines
            self._redraw_match()
            time.sleep(get_config().timing.move_log_scroll_delay_sec)
        self._action_log_override_lines = None
        self._redraw_match()

    def wait_between_moves(self) -> None:
        if sys.stdout.isatty():
            time.sleep(get_config().timing.move_gap_between_turns_sec)

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
        choices = _curate_move_choices(state, actor_idx, options)
        n_opts = len(choices)
        err = ""
        while True:
            lines: list[str] = [
                f"{c.bold}Your plan{c.reset}",
                f"{c.dim}Showing curated options so each choice has a clear job.{c.reset}",
                "",
            ]
            last_intent = ""
            for j, choice in enumerate(choices, start=1):
                rule = choice.rule
                m = rule.move
                if choice.intent != last_intent:
                    if last_intent:
                        lines.append("")
                    lines.append(f"  {c.dim}{choice.intent}{c.reset}")
                    last_intent = choice.intent
                lbl = move_landing_probability_label(state, actor_idx, rule)
                lines.append(
                    f"    {c.accent}{j}.{c.reset} {m.name}  "
                    f"{c.dim}[{lbl}] — {choice.note}{c.reset}"
                )
            lines.append("")
            lines.append(
                f"{c.dim}Press M to "
                f"{'hide' if self._show_momentum_chart else 'show'} momentum trend  ·  "
                f"ESC: pause{c.reset}"
            )
            if err:
                lines.append(f"{c.warn}{err}{c.reset}")
            self._redraw_match(bottom_extra=lines)
            sys.stdout.write(f"{c.bold}Choose move (1–{n_opts}):{c.reset} ")
            sys.stdout.flush()
            raw = read_move_choice_line()
            if raw == "ESC":
                self._pause_menu()
                continue
            if raw == "M":
                self._toggle_momentum_chart()
                continue
            raw = raw.strip()
            if raw.isdigit():
                n = int(raw)
                if 1 <= n <= n_opts:
                    return choices[n - 1].rule_index
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
