"""Compact JSONL renderer for cloud-agent playtesting.

Records one line per action rather than per round. Because the turn queue lets one
wrestler act several times before the other moves, ``turn`` here is a global action
counter and every record carries the actor plus the timeline position it happened at.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import IO

from game import MatchState, PinSequence, move_landing_probability_label, outcome_label
from moves import MoveRule, move_tempo_cost
from playtest.policies import choose_policy_index
from render_fixed import _curate_move_choices, _MoveChoice
from scheduler import TurnQueue
from wrestlers import Wrestler


def _state_snapshot(state: MatchState) -> dict[str, object]:
    return {
        "health": list(state.health),
        "momentum": list(state.momentum),
        "surge": list(state.surge),
        "position": [state.position[i].name for i in range(2)],
        "groggy": list(state.groggy),
    }


def _choice_payload(
    state: MatchState,
    actor_idx: int,
    choices: Sequence[_MoveChoice],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for menu_index, choice in enumerate(choices, start=1):
        rows.append(
            {
                "index": menu_index,
                "rule_index": choice.rule_index,
                "intent": choice.intent,
                "move": choice.rule.move.name,
                "move_id": choice.rule.move.id,
                "label": move_landing_probability_label(
                    state, actor_idx, choice.rule
                ),
                "note": choice.note,
                "tempo_cost": round(choice.tempo_cost, 3),
                "conceded": choice.conceded,
            }
        )
    return rows


def _finish_sequence_payload(sequence: PinSequence) -> dict[str, object]:
    seq_type = (
        "submission"
        if sequence.heading.startswith("Submission")
        else "pinfall"
    )
    parts: list[str] = []
    if sequence.preamble_lines:
        parts.extend(sequence.preamble_lines)
    steps: list[dict[str, object]] = []
    for step_lines, delay_sec in sequence.steps:
        steps.append({"lines": list(step_lines), "delay_sec": delay_sec})
        parts.extend(step_lines)
    return {
        "type": seq_type,
        "heading": sequence.heading,
        "won": sequence.won,
        "text": "\n".join(parts),
        "steps": steps,
    }


class PlaytestRenderer:
    """Emit one JSON object per line; no full-screen redraws or sleeps."""

    def __init__(
        self,
        *,
        policy: str = "chaotic",
        output: IO[str] | None = None,
        max_actions: int | None = None,
        wrestler_ids: tuple[str, str] | None = None,
        rng: object | None = None,
    ) -> None:
        import random as random_mod

        self._policy = policy
        self._output = output or sys.stdout
        self._max_actions = max_actions
        self._wrestler_ids = wrestler_ids
        self._rng = rng if rng is not None else random_mod
        self._match_seed: int | None = None
        self._action_count = 0
        self._aborted = False
        self._last_player_choices: list[_MoveChoice] = []
        self._last_player_selected_index = 0
        self._win_reason = "pinfall"
        self._sim_time = 0.0

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def action_count(self) -> int:
        return self._action_count

    def _emit(self, payload: dict[str, object]) -> None:
        print(json.dumps(payload, separators=(",", ":")), file=self._output, flush=True)

    def show_title(self) -> None:
        return

    def choose_wrestler(self, roster: Sequence[Wrestler]) -> str:
        if self._wrestler_ids is not None:
            return self._wrestler_ids[0]
        return roster[0].id

    def show_opponent_chosen(self, opponent: Wrestler) -> None:
        return

    def match_start_banner(self, *, match_seed: int | None = None) -> None:
        self._match_seed = match_seed
        self._action_count = 0
        self._sim_time = 0.0
        self._emit(
            {
                "event": "match_start",
                "match_seed": match_seed,
                "wrestlers": list(self._wrestler_ids or ("", "")),
                "player_policy": self._policy,
            }
        )

    def show_status(
        self,
        state: MatchState,
        display_names: tuple[str, str],
        *,
        up_next: Sequence[int] = (),
    ) -> None:
        return

    def record_momentum(self, state: MatchState) -> None:
        return

    def begin_action(self, is_player_turn: bool) -> None:
        return

    def wait_between_moves(self) -> None:
        return

    def wait_after_match(self) -> None:
        return

    def fatal_no_valid_moves(self) -> None:
        self._emit(self._end_payload(winner=None, reason="no_valid_moves"))

    def _end_payload(self, *, winner: str | None, reason: str) -> dict[str, object]:
        return {
            "event": "match_end",
            "match_seed": self._match_seed,
            "action_count": self._action_count,
            "sim_time": round(self._sim_time, 3),
            "winner": winner,
            "reason": reason,
        }

    def record_action(
        self,
        state: MatchState,
        *,
        actor_idx: int,
        rule: MoveRule,
        log: str,
        pin_seq: PinSequence | None,
        sim_time: float,
        speed: float,
    ) -> None:
        self._action_count += 1
        self._sim_time = sim_time
        is_player = actor_idx == 0
        choices = self._last_player_choices if is_player else []
        payload: dict[str, object] = {
            "event": "action",
            "action": self._action_count,
            "actor": "player" if is_player else "cpu",
            "match_seed": self._match_seed,
            "sim_time": round(sim_time, 3),
            "actor_speed": round(speed, 3),
            "tempo_cost": round(move_tempo_cost(rule.move), 3),
            "move": rule.move.name,
            "move_id": rule.move.id,
            "choices": _choice_payload(state, actor_idx, choices),
            "selected_index": self._last_player_selected_index if is_player else 0,
            "log": log,
            "outcome": outcome_label(log),
            "state": _state_snapshot(state),
        }
        if pin_seq is not None:
            finish = _finish_sequence_payload(pin_seq)
            payload["finish_sequence"] = finish
            if pin_seq.won:
                self._win_reason = str(finish["type"])
        elif outcome_label(log) in {"submission", "knockout"}:
            self._win_reason = outcome_label(log)
        self._emit(payload)

        if is_player:
            self._last_player_choices = []
            self._last_player_selected_index = 0
        if self._max_actions is not None and self._action_count >= self._max_actions:
            self._aborted = True

    def show_move_log(
        self,
        text: str,
        *,
        player_nickname: str,
        cpu_nickname: str,
        actor_is_player: bool,
        move_name: str,
    ) -> None:
        return

    def show_pin_sequence(
        self,
        sequence: PinSequence,
        *,
        player_nickname: str,
        cpu_nickname: str,
        actor_is_player: bool,
        move_name: str,
    ) -> None:
        return

    def show_match_result_player_wins(self) -> None:
        self._emit(self._end_payload(winner="player", reason=self._win_reason))

    def show_match_result_cpu_wins(self) -> None:
        self._emit(self._end_payload(winner="cpu", reason=self._win_reason))

    def emit_max_actions_end(self) -> None:
        self._emit(self._end_payload(winner=None, reason="max_actions"))

    def prompt_move_choice(
        self,
        state: MatchState,
        actor_idx: int,
        options: Sequence[tuple[int, MoveRule]],
        queue: TurnQueue,
    ) -> int:
        if not options:
            self.fatal_no_valid_moves()
            raise SystemExit(1)
        choices = _curate_move_choices(state, actor_idx, options, queue=queue)
        menu_index = choose_policy_index(self._policy, choices, self._rng)
        self._last_player_choices = list(choices)
        self._last_player_selected_index = menu_index
        return choices[menu_index - 1].rule_index
