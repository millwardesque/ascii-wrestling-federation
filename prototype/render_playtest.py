"""Compact JSONL renderer for cloud-agent playtesting."""

from __future__ import annotations

import json
import sys
from typing import IO, Sequence

from game import MatchState, PinSequence, move_landing_probability_label, outcome_label
from commentators import CommentatorPair
from moves import BodyPosition, MoveRule
from playtest.policies import choose_policy_index
from render_fixed import _MoveChoice, _curate_move_choices
from wrestlers import Wrestler


def _state_snapshot(state: MatchState) -> dict[str, object]:
    return {
        "health": list(state.health),
        "momentum": list(state.momentum),
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
        max_turns: int | None = None,
        wrestler_ids: tuple[str, str] | None = None,
        rng: object | None = None,
    ) -> None:
        import random as random_mod

        self._policy = policy
        self._output = output or sys.stdout
        self._max_turns = max_turns
        self._wrestler_ids = wrestler_ids
        self._rng = rng if rng is not None else random_mod
        self._match_seed: int | None = None
        self._turn_count = 0
        self._aborted = False
        self._last_player_choices: list[_MoveChoice] = []
        self._last_player_selected_index = 0
        self._win_reason = "pinfall"

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def turn_count(self) -> int:
        return self._turn_count

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

    def match_start_banner(
        self,
        *,
        match_seed: int | None = None,
        commentary_team: CommentatorPair | None = None,
    ) -> None:
        self._match_seed = match_seed
        self._turn_count = 0
        wrestlers = list(self._wrestler_ids or ("", ""))
        payload: dict[str, object] = {
            "event": "match_start",
            "match_seed": match_seed,
            "wrestlers": wrestlers,
            "player_policy": self._policy,
        }
        if commentary_team is not None:
            payload["commentary_team"] = list(commentary_team.ids)
            payload["commentary_team_label"] = commentary_team.label()
        self._emit(payload)

    def show_status(self, state: MatchState, display_names: tuple[str, str]) -> None:
        return

    def record_momentum(self, state: MatchState) -> None:
        return

    def round_header(self, is_player_turn: bool) -> None:
        return

    def wait_between_moves(self) -> None:
        return

    def wait_after_match(self) -> None:
        return

    def fatal_no_valid_moves(self) -> None:
        self._emit(
            {
                "event": "match_end",
                "match_seed": self._match_seed,
                "turn_count": self._turn_count,
                "winner": None,
                "reason": "no_valid_moves",
            }
        )

    def _record_turn(
        self,
        *,
        actor: str,
        actor_idx: int,
        state: MatchState,
        rule: MoveRule,
        log: str,
        pin_seq: PinSequence | None,
        choices: Sequence[_MoveChoice] | None,
        selected_index: int,
    ) -> None:
        self._turn_count += 1
        payload: dict[str, object] = {
            "event": "turn",
            "turn": self._turn_count,
            "actor": actor,
            "match_seed": self._match_seed,
            "move": rule.move.name,
            "move_id": rule.move.id,
            "choices": _choice_payload(state, actor_idx, choices or []),
            "selected_index": selected_index,
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

        if self._max_turns is not None and self._turn_count >= self._max_turns:
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
        self._emit(
            {
                "event": "match_end",
                "match_seed": self._match_seed,
                "turn_count": self._turn_count,
                "winner": "player",
                "reason": self._win_reason,
            }
        )

    def show_match_result_cpu_wins(self) -> None:
        self._emit(
            {
                "event": "match_end",
                "match_seed": self._match_seed,
                "turn_count": self._turn_count,
                "winner": "cpu",
                "reason": self._win_reason,
            }
        )

    def emit_max_turns_end(self) -> None:
        self._emit(
            {
                "event": "match_end",
                "match_seed": self._match_seed,
                "turn_count": self._turn_count,
                "winner": None,
                "reason": "max_turns",
            }
        )

    def prompt_move_choice(
        self,
        state: MatchState,
        actor_idx: int,
        options: Sequence[tuple[int, MoveRule]],
    ) -> int:
        if not options:
            self.fatal_no_valid_moves()
            raise SystemExit(1)
        choices = _curate_move_choices(state, actor_idx, options)
        menu_index = choose_policy_index(self._policy, choices, self._rng)
        self._last_player_choices = list(choices)
        self._last_player_selected_index = menu_index
        return choices[menu_index - 1].rule_index

    def record_player_turn(
        self,
        state: MatchState,
        rule: MoveRule,
        log: str,
        pin_seq: PinSequence | None,
    ) -> None:
        self._record_turn(
            actor="player",
            actor_idx=0,
            state=state,
            rule=rule,
            log=log,
            pin_seq=pin_seq,
            choices=self._last_player_choices,
            selected_index=self._last_player_selected_index,
        )

    def record_cpu_turn(
        self,
        state: MatchState,
        rule: MoveRule,
        log: str,
        pin_seq: PinSequence | None,
    ) -> None:
        self._record_turn(
            actor="cpu",
            actor_idx=1,
            state=state,
            rule=rule,
            log=log,
            pin_seq=pin_seq,
            choices=None,
            selected_index=0,
        )
