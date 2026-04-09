"""Archived append-only scrolling terminal UI. Enable with ``python3 main.py --scroll``."""

from __future__ import annotations

import sys
from typing import Sequence

from game import MatchState, move_landing_probability_label
from moves import MoveRule
from render import (
    InputFn,
    _default_input,
    colorize_nicknames,
    health_bar,
    position_label,
)
from wrestlers import Wrestler


class ScrollRenderer:
    """Legacy: append-only scrolling output (classic terminal)."""

    def __init__(self, input_fn: InputFn | None = None) -> None:
        self._input = input_fn or _default_input

    def show_title(self) -> None:
        print("\n*** ASCII Wrestling Federation — pro-wrestling simulator ***\n")

    def choose_wrestler(self, roster: Sequence[Wrestler]) -> str:
        print("\nChoose YOUR wrestler:")
        for idx, w in enumerate(roster, start=1):
            print(f"  {idx}. {w.name}")
            print(
                f"      STR {w.strength}  AGI {w.agility}  END {w.endurance}  "
                f"CHA {w.charisma}  (HP {w.max_health})"
            )
        while True:
            raw = self._input(f"Enter number (1–{len(roster)}): ").strip()
            if raw.isdigit():
                n = int(raw)
                if 1 <= n <= len(roster):
                    return roster[n - 1].id
            print(f"  Try again — pick 1–{len(roster)}.")

    def show_opponent_chosen(self, opponent: Wrestler) -> None:
        print(f"\nYour opponent: {opponent.name}")

    def match_start_banner(self, *, match_seed: int | None = None) -> None:
        print("\n" + "=" * 60)
        print("  BELL RINGS — singles match, pinfall only")
        if match_seed is not None:
            print(f"  Match seed: {match_seed}")
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
        actor_is_player: bool,
    ) -> None:
        del actor_is_player  # scrolling UI prints full history; actor not needed
        use = sys.stdout.isatty()
        for line in text.splitlines():
            if line.strip():
                print(colorize_nicknames(line, player_nickname, cpu_nickname, use_ansi=use))

    def wait_after_exchange_step(self) -> None:
        self._input("\nPress Enter to continue… ")

    def show_round_summary(self, line: str) -> None:
        print(f"\n  Round recap · {line}\n")

    def show_match_result_player_wins(self) -> None:
        print("\nYou win the match.\n")

    def show_match_result_cpu_wins(self) -> None:
        print("\nThe CPU wins the match.\n")

    def wait_after_match(self) -> None:
        self._input("\nPress Enter to continue to wrestler select… ")

    def prompt_move_choice(
        self,
        state: MatchState,
        actor_idx: int,
        options: Sequence[tuple[int, MoveRule]],
    ) -> int:
        if not options:
            self.fatal_no_valid_moves()
            raise SystemExit(1)
        print("Your moves:")
        for j, (_rule_idx, rule) in enumerate(options, start=1):
            m = rule.move
            hint = f" — {m.description}" if len(m.description) < 70 else ""
            lbl = move_landing_probability_label(state, actor_idx, rule)
            print(f"  {j}. {m.name}{hint}  [{lbl}]")
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
