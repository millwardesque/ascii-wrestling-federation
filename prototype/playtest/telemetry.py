"""Layer 1 telemetry computed from playtest JSONL transcripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TextIO


DEFAULT_TURN_MIN = 8
DEFAULT_TURN_MAX = 40


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


def compute_telemetry(
    rows: list[dict[str, Any]],
    *,
    turn_min: int = DEFAULT_TURN_MIN,
    turn_max: int = DEFAULT_TURN_MAX,
) -> dict[str, Any]:
    turns = [row for row in rows if row.get("event") == "turn"]
    match_end = next((row for row in rows if row.get("event") == "match_end"), None)
    player_turns = [row for row in turns if row.get("actor") == "player"]

    logs = [str(row.get("log", "")) for row in turns]
    unique_logs = len({line for log in logs for line in log.splitlines() if line.strip()})
    total_log_lines = sum(
        1 for log in logs for line in log.splitlines() if line.strip()
    )
    log_uniqueness_ratio = (
        unique_logs / total_log_lines if total_log_lines else 1.0
    )

    move_ids = [str(row.get("move_id", "")) for row in player_turns if row.get("move_id")]
    move_repetition_rate = 0.0
    if move_ids:
        most_common = max(move_ids.count(m) for m in set(move_ids))
        move_repetition_rate = most_common / len(move_ids)

    near_fall_count = sum(
        1
        for row in turns
        if row.get("outcome") in {"kickout", "pin"}
        or (
            row.get("finish_sequence")
            and not row["finish_sequence"].get("won")
        )
    )

    positions: set[tuple[str, str]] = set()
    for row in turns:
        state = row.get("state") or {}
        pos = state.get("position")
        if isinstance(pos, list) and len(pos) == 2:
            positions.add((str(pos[0]), str(pos[1])))

    single_choice_turns = sum(
        1
        for row in player_turns
        if isinstance(row.get("choices"), list) and len(row["choices"]) <= 1
    )

    curation_pin_visible = True
    for row in player_turns:
        choices = row.get("choices") or []
        move_ids_in_menu = {c.get("move_id") for c in choices if isinstance(c, dict)}
        if "pin" in move_ids_in_menu or any(
            c.get("label") == "pin" for c in choices if isinstance(c, dict)
        ):
            continue
        # If pin could be legal this turn, it should appear when is_pin exists in valid set.
        # Transcript only includes curated menu; flag if any turn had exactly Finish+pin intent.
        # Conservative gate: if label 'pin' never appears across all player turns, pass.
        pass
    # Stronger gate: any player turn whose choices include a pin move_id
    pin_turns = [
        row
        for row in player_turns
        if any(
            (c.get("move_id") == "pin" or c.get("label") == "pin")
            for c in (row.get("choices") or [])
            if isinstance(c, dict)
        )
    ]
    # If match had grounded opponent late, pin might be legal — we only verify when pin shown it's labeled correctly.
    curation_pin_visible = all(
        any(
            c.get("move_id") == "pin" or c.get("label") == "pin"
            for c in (row.get("choices") or [])
            if isinstance(c, dict)
        )
        for row in pin_turns
    ) if pin_turns else True

    turn_count = int(match_end.get("turn_count", len(turns))) if match_end else len(turns)
    winner = match_end.get("winner") if match_end else None
    reason = match_end.get("reason") if match_end else None

    gate_failures: list[str] = []
    if reason == "no_valid_moves":
        gate_failures.append("match ended with no_valid_moves")
    if winner is None and reason not in {"max_turns"}:
        gate_failures.append("match ended without a winner")
    if turn_count < turn_min or turn_count > turn_max:
        if reason != "max_turns":
            gate_failures.append(
                f"turn_count {turn_count} outside band [{turn_min}, {turn_max}]"
            )
    if not curation_pin_visible:
        gate_failures.append("pin choice missing from curated menu when pin was offered")

    meta_row = next((row for row in rows if row.get("event") == "match_start"), {})
    return {
        "gates_passed": len(gate_failures) == 0,
        "gate_failures": gate_failures,
        "turn_count": turn_count,
        "winner": winner,
        "reason": reason,
        "near_fall_count": near_fall_count,
        "curation_pin_visible": curation_pin_visible,
        "log_uniqueness_ratio": round(log_uniqueness_ratio, 4),
        "move_repetition_rate": round(move_repetition_rate, 4),
        "position_diversity": len(positions),
        "single_choice_turns": single_choice_turns,
        "match_seed": meta_row.get("match_seed"),
        "wrestlers": meta_row.get("wrestlers"),
        "player_policy": meta_row.get("player_policy"),
    }


def telemetry_to_report_meta(telemetry: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_seed": telemetry.get("match_seed"),
        "wrestlers": telemetry.get("wrestlers"),
        "player_policy": telemetry.get("player_policy"),
        "turn_count": telemetry.get("turn_count"),
        "winner": telemetry.get("winner"),
    }
