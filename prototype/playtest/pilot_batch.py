#!/usr/bin/env python3
"""Run pilot playtest batch: transcripts, telemetry, baseline reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from playtest.record_match import record_match
from playtest.telemetry import compute_telemetry, load_transcript_lines, telemetry_to_report_meta

PILOT_SEEDS = (101, 102, 103, 104, 105, 106, 107, 108, 109, 110)
POLICIES = ("novice", "aggressive", "methodical", "chaotic")


def _baseline_scores(telemetry: dict[str, object]) -> dict[str, object]:
    """Heuristic anchor scores from telemetry for pilot calibration."""
    turn_count = int(telemetry.get("turn_count", 0))
    gates = bool(telemetry.get("gates_passed"))
    repetition = float(telemetry.get("move_repetition_rate", 0))
    diversity = int(telemetry.get("position_diversity", 0))
    near_falls = int(telemetry.get("near_fall_count", 0))

    fun = 3
    if turn_count >= 12 and near_falls >= 1 and repetition < 0.35:
        fun = 4
    if repetition >= 0.5 or turn_count < 8:
        fun = 2

    ease = 4 if gates else 2
    if int(telemetry.get("single_choice_turns", 0)) >= 3:
        ease = 3

    stickiness = 3 if diversity >= 3 else 2
    if turn_count >= 15 and near_falls >= 1:
        stickiness = 4

    juicy = 3 if near_falls >= 1 else 2
    if near_falls >= 2:
        juicy = 4

    def dim(value: int, note: str) -> dict[str, object]:
        return {
            "value": value,
            "confidence": "medium",
            "evidence": [{"turn": 1, "note": note}],
        }

    stickiness_score = dim(
        stickiness,
        f"position_diversity={diversity}, turn_count={turn_count}",
    )
    stickiness_score.update(
        {
            "rematch_intent": "yes" if stickiness >= 4 else "maybe",
            "rematch_reason": "Pilot heuristic from telemetry anchors.",
            "next_experiment": "Try aggressive policy on same seed.",
        }
    )

    return {
        "fun": dim(fun, f"repetition={repetition}, near_falls={near_falls}"),
        "ease_of_use": dim(ease, f"gates_passed={gates}"),
        "stickiness": stickiness_score,
        "juiciness": dim(juicy, f"near_fall_count={near_falls}"),
    }


def main() -> None:
    transcript_dir = _ROOT / "playtest" / "transcripts"
    telemetry_dir = _ROOT / "playtest" / "telemetry"
    report_dir = _ROOT / "playtest" / "reports"
    for path in (transcript_dir, telemetry_dir, report_dir):
        path.mkdir(parents=True, exist_ok=True)

    player_id, cpu_id = "bret_hart", "scott_hall"
    summary: list[dict[str, object]] = []

    for i, seed in enumerate(PILOT_SEEDS):
        policy = POLICIES[i % len(POLICIES)]
        transcript_path = transcript_dir / f"{seed}.jsonl"
        record_match(
            player_id=player_id,
            cpu_id=cpu_id,
            seed=seed,
            policy=policy,
            max_turns=None,
            output=transcript_path,
        )
        rows = load_transcript_lines(transcript_path)
        telemetry = compute_telemetry(rows)
        telemetry["player_policy"] = policy
        (telemetry_dir / f"{seed}.json").write_text(
            json.dumps(telemetry, indent=2),
            encoding="utf-8",
        )
        report = {
            "rubric_version": "2026-07-30",
            "meta": telemetry_to_report_meta(telemetry),
            "telemetry": telemetry,
            "scores": _baseline_scores(telemetry),
            "top_issues": [],
            "highlight_moments": [],
        }
        (report_dir / f"{seed}.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
        summary.append(
            {
                "seed": seed,
                "policy": policy,
                "turn_count": telemetry["turn_count"],
                "winner": telemetry["winner"],
                "gates_passed": telemetry["gates_passed"],
            }
        )

    (_ROOT / "playtest" / "pilot-summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
