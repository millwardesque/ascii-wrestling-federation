#!/usr/bin/env python3
"""Run a headless playtest session for every seed in an inclusive range.

Each seed gets a randomly chosen player policy so a single batch covers a mix of
playstyles. Pass ``--policy-seed`` to reproduce a previous policy assignment.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from playtest.record_match import record_match
from playtest.telemetry import compute_telemetry, load_transcript_lines
from wrestlers import list_roster

POLICIES = ("novice", "aggressive", "methodical", "chaotic")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record playtest transcripts for an inclusive seed range"
    )
    parser.add_argument("start_seed", type=int, help="first seed in the range")
    parser.add_argument("end_seed", type=int, help="last seed in the range (inclusive)")
    parser.add_argument(
        "--policy-seed",
        type=int,
        default=None,
        help="seed the policy picker for a reproducible policy assignment",
    )
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_ROOT / "playtest" / "transcripts",
        help="write <seed>.jsonl transcripts here",
    )
    parser.add_argument(
        "--telemetry-dir",
        type=Path,
        default=_ROOT / "playtest" / "telemetry",
        help="write <seed>.json telemetry here",
    )
    parser.add_argument(
        "--skip-telemetry",
        action="store_true",
        help="record transcripts only",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="write the run summary JSON here",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.end_seed < args.start_seed:
        raise SystemExit(
            f"end_seed {args.end_seed} must be >= start_seed {args.start_seed}"
        )

    roster = list_roster()
    if len(roster) < 2:
        raise SystemExit("Need at least two playable wrestlers.")
    player_id, cpu_id = roster[0].id, roster[1].id

    policy_rng = random.Random(args.policy_seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if not args.skip_telemetry:
        args.telemetry_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, object]] = []
    for seed in range(args.start_seed, args.end_seed + 1):
        policy = policy_rng.choice(POLICIES)
        transcript_path = args.output_dir / f"{seed}.jsonl"
        record_match(
            player_id=player_id,
            cpu_id=cpu_id,
            seed=seed,
            policy=policy,
            max_turns=args.max_turns,
            output=transcript_path,
        )

        row: dict[str, object] = {"seed": seed, "policy": policy}
        if args.skip_telemetry:
            print(f"{seed} {policy}")
        else:
            telemetry = compute_telemetry(load_transcript_lines(transcript_path))
            (args.telemetry_dir / f"{seed}.json").write_text(
                json.dumps(telemetry, indent=2),
                encoding="utf-8",
            )
            row.update(
                {
                    "turn_count": telemetry["turn_count"],
                    "winner": telemetry["winner"],
                    "gates_passed": telemetry["gates_passed"],
                    "gate_failures": telemetry["gate_failures"],
                }
            )
            status = "PASS" if telemetry["gates_passed"] else "FAIL"
            print(
                f"{seed} {policy:<10} turns={telemetry['turn_count']:<4} "
                f"winner={str(telemetry['winner']):<6} {status} "
                f"{telemetry['gate_failures']}"
            )
        summary.append(row)

    if args.summary_output is not None:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
