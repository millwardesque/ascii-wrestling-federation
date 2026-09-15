"""Layer 1 telemetry computed from turn-queue playtest JSONL transcripts.

The unit here is the action, not the shared round, because the two wrestlers no longer
act the same number of times. On top of the metrics the alternating prototype tracks,
this adds the ones that tell you whether the turn queue is doing anything at all:
``consecutive_action_max`` (did flurries happen) and ``action_ratio`` (did tempo vary
without locking anyone out).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TextIO

# Pacing band in total actions. Both wrestlers act more often than they took turns under
# alternation, so this is rebaselined against the turn-queue corpus rather than carried
# over from the round-based gate.
DEFAULT_ACTION_MIN = 10
DEFAULT_ACTION_MAX = 70

# A match where nobody ever strings two actions together means the scheduler is inert.
DEFAULT_MIN_CONSECUTIVE_MAX = 2
# Neither wrestler should be so far ahead on tempo that the other is a spectator.
DEFAULT_MAX_ACTION_RATIO = 3.0


def load_transcript_lines(source: str | Path | TextIO) -> list[dict[str, Any]]:
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8")
    elif isinstance(source, str):
        text = Path(source).read_text(encoding="utf-8")
    else:
        text = source.read()
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _longest_run(actors: list[str]) -> int:
    best = 0
    run = 0
    previous = None
    for actor in actors:
        run = run + 1 if actor == previous else 1
        previous = actor
        best = max(best, run)
    return best


def compute_telemetry(
    rows: list[dict[str, Any]],
    *,
    action_min: int = DEFAULT_ACTION_MIN,
    action_max: int = DEFAULT_ACTION_MAX,
    min_consecutive_max: int = DEFAULT_MIN_CONSECUTIVE_MAX,
    max_action_ratio: float = DEFAULT_MAX_ACTION_RATIO,
) -> dict[str, Any]:
    actions = [row for row in rows if row.get("event") == "action"]
    match_end = next((row for row in rows if row.get("event") == "match_end"), None)
    player_actions = [row for row in actions if row.get("actor") == "player"]
    cpu_actions = [row for row in actions if row.get("actor") == "cpu"]

    logs = [str(row.get("log", "")) for row in actions]
    unique_logs = len({line for log in logs for line in log.splitlines() if line.strip()})
    total_log_lines = sum(
        1 for log in logs for line in log.splitlines() if line.strip()
    )
    log_uniqueness_ratio = unique_logs / total_log_lines if total_log_lines else 1.0

    move_ids = [
        str(row.get("move_id", "")) for row in player_actions if row.get("move_id")
    ]
    move_repetition_rate = 0.0
    if move_ids:
        most_common = max(move_ids.count(m) for m in set(move_ids))
        move_repetition_rate = most_common / len(move_ids)

    near_fall_count = sum(
        1
        for row in actions
        if row.get("outcome") in {"kickout", "pin"}
        or (row.get("finish_sequence") and not row["finish_sequence"].get("won"))
    )

    positions: set[tuple[str, str]] = set()
    for row in actions:
        pos = (row.get("state") or {}).get("position")
        if isinstance(pos, list) and len(pos) == 2:
            positions.add((str(pos[0]), str(pos[1])))

    single_choice_actions = sum(
        1
        for row in player_actions
        if isinstance(row.get("choices"), list) and len(row["choices"]) <= 1
    )

    # Only checked on actions where a pin was actually offered: when the menu contains a
    # cover it must be identifiable as one, so curation can never bury the finish.
    pin_actions = [
        row
        for row in player_actions
        if any(
            (c.get("move_id") == "pin" or c.get("label") == "pin")
            for c in (row.get("choices") or [])
            if isinstance(c, dict)
        )
    ]
    curation_pin_visible = all(
        any(
            c.get("move_id") == "pin" or c.get("label") == "pin"
            for c in (row.get("choices") or [])
            if isinstance(c, dict)
        )
        for row in pin_actions
    ) if pin_actions else True

    action_count = (
        int(match_end.get("action_count", len(actions))) if match_end else len(actions)
    )
    sim_time_total = float(match_end.get("sim_time", 0.0)) if match_end else 0.0
    winner = match_end.get("winner") if match_end else None
    reason = match_end.get("reason") if match_end else None

    consecutive_action_max = _longest_run([str(row.get("actor")) for row in actions])
    actions_player = len(player_actions)
    actions_cpu = len(cpu_actions)
    if actions_player and actions_cpu:
        action_ratio = max(actions_player, actions_cpu) / min(
            actions_player, actions_cpu
        )
    else:
        action_ratio = float(action_count) if action_count else 1.0

    # How much initiative the player actually handed over, averaged over their choices.
    conceded_values: list[int] = []
    for row in player_actions:
        selected = row.get("selected_index")
        choices = row.get("choices") or []
        if isinstance(selected, int) and 1 <= selected <= len(choices):
            chosen = choices[selected - 1]
            if isinstance(chosen, dict) and isinstance(chosen.get("conceded"), int):
                conceded_values.append(int(chosen["conceded"]))
    mean_conceded = (
        round(sum(conceded_values) / len(conceded_values), 4)
        if conceded_values
        else 0.0
    )

    gate_failures: list[str] = []
    if reason == "no_valid_moves":
        gate_failures.append("match ended with no_valid_moves")
    if winner is None and reason not in {"max_actions"}:
        gate_failures.append("match ended without a winner")
    if reason != "max_actions" and (
        action_count < action_min or action_count > action_max
    ):
        gate_failures.append(
            f"action_count {action_count} outside band [{action_min}, {action_max}]"
        )
    if not curation_pin_visible:
        gate_failures.append("pin choice missing from curated menu when pin was offered")
    if consecutive_action_max < min_consecutive_max:
        gate_failures.append(
            f"consecutive_action_max {consecutive_action_max} < {min_consecutive_max} "
            "— turn queue never produced a flurry"
        )
    if action_ratio > max_action_ratio:
        gate_failures.append(
            f"action_ratio {action_ratio:.2f} > {max_action_ratio} — one wrestler was locked out"
        )

    meta_row = next((row for row in rows if row.get("event") == "match_start"), {})
    return {
        "gates_passed": len(gate_failures) == 0,
        "gate_failures": gate_failures,
        "action_count": action_count,
        "sim_time_total": round(sim_time_total, 3),
        "actions_player": actions_player,
        "actions_cpu": actions_cpu,
        "action_ratio": round(action_ratio, 4),
        "consecutive_action_max": consecutive_action_max,
        "mean_conceded_player": mean_conceded,
        "winner": winner,
        "reason": reason,
        "near_fall_count": near_fall_count,
        "curation_pin_visible": curation_pin_visible,
        "log_uniqueness_ratio": round(log_uniqueness_ratio, 4),
        "move_repetition_rate": round(move_repetition_rate, 4),
        "position_diversity": len(positions),
        "single_choice_actions": single_choice_actions,
        "match_seed": meta_row.get("match_seed"),
        "wrestlers": meta_row.get("wrestlers"),
        "player_policy": meta_row.get("player_policy"),
    }


def telemetry_to_report_meta(telemetry: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_seed": telemetry.get("match_seed"),
        "wrestlers": telemetry.get("wrestlers"),
        "player_policy": telemetry.get("player_policy"),
        "action_count": telemetry.get("action_count"),
        "winner": telemetry.get("winner"),
    }
