#!/usr/bin/env python3
"""Terminal pro-wrestling simulator — pick a wrestler, trade moves, win by pinfall."""

from __future__ import annotations

import random
import secrets

from game import (
    MatchState,
    apply_move,
    cpu_choose_rule,
    format_exchange_summary,
    format_exchange_summary_after_player,
)
from render import MatchRenderer
from render_fixed import FixedLayoutRenderer
from wrestlers import ROSTER, list_roster


def run_match(player_id: str, cpu_id: str, ui: MatchRenderer) -> None:
    pw = ROSTER[player_id]
    cw = ROSTER[cpu_id]
    match_seed = secrets.randbits(63)
    random.seed(match_seed)
    state = MatchState(wrestlers=(pw, cw))
    names = ("YOU (" + pw.nickname + ")", "CPU (" + cw.nickname + ")")

    ui.match_start_banner(match_seed=match_seed)
    ui.show_status(state, names)

    while True:
        ui.round_header(is_player_turn=True)
        ui.show_status(state, names)

        opts = state.valid_rules(0)
        idx = ui.prompt_move_choice(state, 0, opts)
        player_rule = state.rules[idx]
        ui.show_status(state, names)

        log, winner = apply_move(state, 0, player_rule)
        player_move = player_rule.move.name
        player_log = log
        ui.show_status(state, names)
        ui.show_move_log(
            log,
            player_nickname=pw.nickname,
            cpu_nickname=cw.nickname,
            actor_is_player=True,
        )
        ui.show_exchange_recap(
            format_exchange_summary_after_player(player_move, player_log)
        )
        ui.wait_after_exchange_step()

        if winner is not None:
            if winner == 0:
                ui.show_match_result_player_wins()
            else:
                ui.show_match_result_cpu_wins()
            return

        cpu_rule = cpu_choose_rule(state, 1)

        ui.round_header(is_player_turn=False)

        log, winner = apply_move(state, 1, cpu_rule)
        cpu_move = cpu_rule.move.name
        cpu_log = log
        ui.show_status(state, names)
        ui.show_move_log(
            log,
            player_nickname=pw.nickname,
            cpu_nickname=cw.nickname,
            actor_is_player=False,
        )
        ui.show_exchange_recap(
            format_exchange_summary(player_move, player_log, cpu_move, cpu_log)
        )
        ui.wait_after_exchange_step()

        if winner is not None:
            if winner == 0:
                ui.show_match_result_player_wins()
            else:
                ui.show_match_result_cpu_wins()
            return

        ui.show_status(state, names)


def main(ui: MatchRenderer | None = None) -> None:
    renderer = ui if ui is not None else FixedLayoutRenderer()
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
    main()
