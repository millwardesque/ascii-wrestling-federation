#!/usr/bin/env python3
"""Terminal pro-wrestling simulator — pick a wrestler, trade moves, win by pinfall."""

from __future__ import annotations

import argparse
import random
import secrets

from game import MatchState, apply_move, cpu_choose_rule
from render import MatchRenderer, ReturnToTitle
from render_fixed import FixedLayoutRenderer
from wrestlers import ROSTER, list_roster


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ASCII Wrestling Federation terminal prototype"
    )
    parser.add_argument(
        "--random-match",
        "--quick-match",
        action="store_true",
        help="skip title/player selection and start one match with random playable wrestlers",
    )
    return parser.parse_args(argv)


def _random_match_ids() -> tuple[str, str]:
    roster = list_roster()
    if len(roster) < 2:
        raise SystemExit("Need at least two playable wrestlers for --random-match.")
    player, cpu = random.sample(roster, 2)
    return player.id, cpu.id


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

        log, winner, pin_seq = apply_move(state, 0, player_rule)
        ui.show_status(state, names)
        if pin_seq is not None:
            ui.show_pin_sequence(
                pin_seq,
                player_nickname=pw.nickname,
                cpu_nickname=cw.nickname,
                actor_is_player=True,
                move_name=player_rule.move.name,
            )
        else:
            ui.show_move_log(
                log,
                player_nickname=pw.nickname,
                cpu_nickname=cw.nickname,
                actor_is_player=True,
                move_name=player_rule.move.name,
            )

        if winner is not None:
            if winner == 0:
                ui.show_match_result_player_wins()
            else:
                ui.show_match_result_cpu_wins()
            return

        ui.wait_between_moves()

        cpu_rule = cpu_choose_rule(state, 1)

        ui.round_header(is_player_turn=False)

        log, winner, pin_seq = apply_move(state, 1, cpu_rule)
        ui.show_status(state, names)
        if pin_seq is not None:
            ui.show_pin_sequence(
                pin_seq,
                player_nickname=pw.nickname,
                cpu_nickname=cw.nickname,
                actor_is_player=False,
                move_name=cpu_rule.move.name,
            )
        else:
            ui.show_move_log(
                log,
                player_nickname=pw.nickname,
                cpu_nickname=cw.nickname,
                actor_is_player=False,
                move_name=cpu_rule.move.name,
            )

        ui.record_momentum(state)

        if winner is not None:
            if winner == 0:
                ui.show_match_result_player_wins()
            else:
                ui.show_match_result_cpu_wins()
            return

        ui.wait_between_moves()

        ui.show_status(state, names)


def main(ui: MatchRenderer | None = None, argv: list[str] | None = None) -> None:
    args = _parse_args([] if ui is not None and argv is None else argv)
    renderer = ui if ui is not None else FixedLayoutRenderer()
    if args.random_match:
        pid, cid = _random_match_ids()
        run_match(pid, cid, renderer)
        renderer.wait_after_match()
        return

    while True:
        renderer.show_title()
        try:
            roster = list_roster()
            pid = renderer.choose_wrestler(roster)
            cpu_keys = [w.id for w in roster if w.id != pid]
            cid = random.choice(cpu_keys)
            renderer.show_opponent_chosen(ROSTER[cid])
            run_match(pid, cid, renderer)
        except ReturnToTitle:
            continue
        renderer.wait_after_match()


if __name__ == "__main__":
    main()
