#!/usr/bin/env python3
"""Terminal pro-wrestling simulator — pick a wrestler, trade moves, win by pinfall."""

from __future__ import annotations

import argparse
import random

from game import MatchState, apply_move, cpu_choose_rule, format_round_summary
from render import MatchRenderer, ScrollRenderer
from render_fixed import FixedLayoutRenderer
from wrestlers import ROSTER, list_roster


def run_match(player_id: str, cpu_id: str, ui: MatchRenderer) -> None:
    pw = ROSTER[player_id]
    cw = ROSTER[cpu_id]
    state = MatchState(wrestlers=(pw, cw))
    names = ("YOU (" + pw.nickname + ")", "CPU (" + cw.nickname + ")")

    ui.match_start_banner()
    ui.show_status(state, names)

    turn = 0  # player first
    round_num = 1
    player_move = ""
    player_log = ""
    cpu_move = ""
    cpu_log = ""

    while True:
        is_player = turn == 0
        ui.round_header(round_num, is_player)

        if is_player:
            opts = state.valid_rules(0)
            idx = ui.prompt_move_choice(opts)
            rule = state.rules[idx]
        else:
            rule = cpu_choose_rule(state, 1)

        log, winner = apply_move(state, turn, rule)
        ui.show_move_log(
            log,
            player_nickname=pw.nickname,
            cpu_nickname=cw.nickname,
            actor_is_player=is_player,
        )

        if is_player:
            player_move = rule.move.name
            player_log = log
        else:
            cpu_move = rule.move.name
            cpu_log = log

        if winner is not None:
            if winner == 0:
                ui.show_match_result_player_wins()
            else:
                ui.show_match_result_cpu_wins()
            return

        if state.health[0] <= 0 or state.health[1] <= 0:
            ui.show_double_exhaustion()
            return

        turn = 1 - turn
        if turn == 0:
            round_num += 1
            ui.show_round_summary(format_round_summary(player_move, player_log, cpu_move, cpu_log))
        ui.show_status(state, names)


def main(ui: MatchRenderer | None = None) -> None:
    renderer = ui or ScrollRenderer()
    while True:
        renderer.show_title()
        roster = list_roster()
        pid = renderer.choose_wrestler(roster)
        cpu_keys = [k for k in ROSTER if k != pid]
        cid = random.choice(cpu_keys)
        renderer.show_opponent_chosen(ROSTER[cid])
        run_match(pid, cid, renderer)
        renderer.wait_after_match()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Wrestleterm — text ring simulator")
    ap.add_argument(
        "-f",
        "--fixed",
        action="store_true",
        help="Fixed layout: full-screen redraw (ANSI), colors when supported",
    )
    args = ap.parse_args()
    main(ui=FixedLayoutRenderer() if args.fixed else None)
