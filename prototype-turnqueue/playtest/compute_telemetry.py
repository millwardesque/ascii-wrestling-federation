#!/usr/bin/env python3
"""Compute Layer 1 telemetry from playtest transcript JSONL files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from playtest.telemetry import (
    DEFAULT_ACTION_MAX,
    DEFAULT_ACTION_MIN,
    DEFAULT_MAX_ACTION_RATIO,
    DEFAULT_MIN_CONSECUTIVE_MAX,
    compute_telemetry,
    load_transcript_lines,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute telemetry JSON from playtest transcript JSONL files"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("playtest/transcripts"),
        help="directory containing <seed>.jsonl transcripts",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("playtest/telemetry"),
        help="directory to write <seed>.json telemetry files",
    )
    parser.add_argument(
        "--action-min",
        type=int,
        default=DEFAULT_ACTION_MIN,
        help="pass/fail gate: minimum total actions",
    )
    parser.add_argument(
        "--action-max",
        type=int,
        default=DEFAULT_ACTION_MAX,
        help="pass/fail gate: maximum total actions",
    )
    parser.add_argument(
        "--min-consecutive-max",
        type=int,
        default=DEFAULT_MIN_CONSECUTIVE_MAX,
        help="pass/fail gate: longest same-wrestler run must reach this",
    )
    parser.add_argument(
        "--max-action-ratio",
        type=float,
        default=DEFAULT_MAX_ACTION_RATIO,
        help="pass/fail gate: cap on the action-count ratio between wrestlers",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    paths = sorted(args.input_dir.glob("*.jsonl"))
    if not paths:
        raise SystemExit(f"No .jsonl files found in {args.input_dir}")

    for path in paths:
        rows = load_transcript_lines(path)
        payload = compute_telemetry(
            rows,
            action_min=args.action_min,
            action_max=args.action_max,
            min_consecutive_max=args.min_consecutive_max,
            max_action_ratio=args.max_action_ratio,
        )
        out_path = args.output_dir / f"{path.stem}.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        status = "PASS" if payload["gates_passed"] else "FAIL"
        print(path.stem, status, payload.get("gate_failures") or [])


if __name__ == "__main__":
    main()
