#!/usr/bin/env python3
"""Terminal pro-wrestling simulator on a turn queue — no fixed you-then-me alternation.

Whoever sits lowest on the timeline acts next, so a cheap jab can buy a second action
before the opponent moves at all, and a finisher hands them the initiative while you
recover. ``run_match`` owns the queue; ``game`` owns what a move does.
"""

from __future__ import annotations

import argparse
import random
import secrets
from typing import Sequence

from game import MatchState, advance_to, apply_move, cpu_choose_rule
from render import MatchRenderer, ReturnToTitle
from render_fixed import FixedLayoutRenderer
from render_playtest import PlaytestRenderer
from scheduler import (
    TurnQueue,
    actor_speeds,
    project_order,
    projection_costs,
    rule_delay,
)
from config import get_config
from wrestlers import ROSTER, list_roster

PLAYTEST_POLICIES = ("novice", "aggressive", "methodical", "chaotic", "tempo")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ASCII Wrestling Federation — turn-queue prototype"
    )
    parser.add_argument(
        "--random-match",
        "--quick-match",
        action="store_true",
        help="skip title/player selection and start one match with random playable wrestlers",
    )
    parser.add_argument(
        "--playtest",
        action="store_true",
        help="headless JSONL transcript mode for cloud-agent playtesting",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="match RNG seed (playtest / reproducible runs)",
    )
    parser.add_argument(
        "--max-actions",
        "--max-turns",
        type=int,
        default=None,
        dest="max_actions",
        help="stop after N total actions (exploratory playtests)",
    )
    parser.add_argument(
        "--policy",
        choices=PLAYTEST_POLICIES,
        default="chaotic",
        help="automated player policy for --playtest",
    )
    return parser.parse_args(argv)


def _random_match_ids(rng: random.Random | None = None) -> tuple[str, str]:
    roster = list_roster()
    if len(roster) < 2:
        raise SystemExit("Need at least two playable wrestlers for --random-match.")
    source = rng or random
    player, cpu = source.sample(roster, 2)
    return player.id, cpu.id


def upcoming_actors(state: MatchState, queue: TurnQueue) -> list[int]:
    """Projected turn order for the UI strip, assuming default-cost moves from here."""
    depth = get_config().tempo.queue_preview_depth
    return project_order(
        queue.next_act_at, actor_speeds(state), projection_costs(state), depth
    )


def _settle_queue(
    state: MatchState,
    queue: TurnQueue,
    actor_idx: int,
    rule,
    speeds_after: Sequence[float],
) -> None:
    """Push the actor back by their recovery, then drain any extra shoves the move caused.

    Recovery uses post-move speed, so ending an exchange face-down on the canvas makes
    getting back into the match genuinely slower.
    """
    queue.schedule(actor_idx, rule_delay(rule, speeds_after[actor_idx]))
    for i in (0, 1):
        push = state.pending_timeline_push[i]
        if push:
            queue.next_act_at[i] += push
            state.pending_timeline_push[i] = 0.0


def run_match(
    player_id: str,
    cpu_id: str,
    ui: MatchRenderer,
    *,
    match_seed: int | None = None,
    max_actions: int | None = None,
) -> int | None:
    """Run one match. Returns winner index (0 player, 1 CPU) or None if capped."""
    pw = ROSTER[player_id]
    cw = ROSTER[cpu_id]
    if match_seed is None:
        match_seed = secrets.randbits(63)
    random.seed(match_seed)
    state = MatchState(wrestlers=(pw, cw))
    names = ("YOU (" + pw.nickname + ")", "CPU (" + cw.nickname + ")")
    playtest = isinstance(ui, PlaytestRenderer)
    queue = TurnQueue()

    ui.match_start_banner(match_seed=match_seed)
    ui.show_status(state, names, up_next=upcoming_actors(state, queue))

    while True:
        speeds = actor_speeds(state)
        actor_idx = queue.pop_next(speeds)
        advance_to(state, queue.clock)
        is_player = actor_idx == 0

        ui.begin_action(is_player_turn=is_player)
        ui.show_status(state, names, up_next=upcoming_actors(state, queue))

        if is_player:
            options = state.valid_rules(actor_idx)
            chosen_index = ui.prompt_move_choice(state, actor_idx, options, queue)
            rule = state.rules[chosen_index]
        else:
            rule = cpu_choose_rule(state, actor_idx, queue)

        result = apply_move(state, actor_idx, rule)
        log, winner, pin_seq = result
        speeds_after = actor_speeds(state)
        _settle_queue(state, queue, actor_idx, rule, speeds_after)

        ui.show_status(state, names, up_next=upcoming_actors(state, queue))

        if playtest:
            ui.record_action(
                state,
                actor_idx=actor_idx,
                rule=rule,
                log=log,
                pin_seq=pin_seq,
                sim_time=queue.clock,
                speed=speeds[actor_idx],
            )
            if ui.aborted:
                ui.emit_max_actions_end()
                return None
        elif pin_seq is not None:
            ui.show_pin_sequence(
                pin_seq,
                player_nickname=pw.nickname,
                cpu_nickname=cw.nickname,
                actor_is_player=is_player,
                move_name=rule.move.name,
            )
        else:
            ui.show_move_log(
                log,
                player_nickname=pw.nickname,
                cpu_nickname=cw.nickname,
                actor_is_player=is_player,
                move_name=rule.move.name,
            )

        if winner is not None:
            if winner == 0:
                ui.show_match_result_player_wins()
            else:
                ui.show_match_result_cpu_wins()
            return winner

        ui.record_momentum(state)
        ui.wait_between_moves()
        ui.show_status(state, names, up_next=upcoming_actors(state, queue))

        if max_actions is not None and ui.action_count >= max_actions:
            if playtest:
                ui.emit_max_actions_end()
            return None


def main(ui: MatchRenderer | None = None, argv: list[str] | None = None) -> None:
    args = _parse_args([] if ui is not None and argv is None else argv)

    if args.playtest:
        rng = random.Random(args.seed) if args.seed is not None else random.Random()
        if args.seed is not None:
            pid, cid = _random_match_ids(rng)
        else:
            pid, cid = _random_match_ids()
        match_seed = args.seed if args.seed is not None else rng.randrange(1 << 30)
        renderer = PlaytestRenderer(
            policy=args.policy,
            max_actions=args.max_actions,
            wrestler_ids=(pid, cid),
            rng=random.Random(match_seed),
        )
        run_match(
            pid,
            cid,
            renderer,
            match_seed=match_seed,
            max_actions=args.max_actions,
        )
        return

    renderer = ui if ui is not None else FixedLayoutRenderer()
    if args.random_match:
        pid, cid = _random_match_ids()
        run_match(pid, cid, renderer, max_actions=args.max_actions)
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
