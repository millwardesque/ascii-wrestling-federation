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

from playtest.telemetry import compute_telemetry, load_transcript_lines


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
        "--turn-min",
        type=int,
        default=8,
        help="pass/fail gate: minimum turn count",
    )
    parser.add_argument(
        "--turn-max",
        type=int,
        default=40,
        help="pass/fail gate: maximum turn count",
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
            turn_min=args.turn_min,
            turn_max=args.turn_max,
        )
        out_path = args.output_dir / f"{path.stem}.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        status = "PASS" if payload["gates_passed"] else "FAIL"
        failures = payload.get("gate_failures") or []
        print(path.stem, status, failures)


if __name__ == "__main__":
    main()
