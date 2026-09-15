#!/usr/bin/env python3
"""Compute Layer 1 dialog telemetry from playtest transcript JSONL files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from playtest.dialog_telemetry import (
    aggregate_dialog_telemetry,
    compute_dialog_telemetry,
    load_transcript_lines,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check match narration against match state and write dialog telemetry"
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
        default=Path("playtest/dialog"),
        help="directory to write <seed>.json dialog telemetry files",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="write the batch aggregate to this path",
    )
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="exit non-zero when the batch gates fail (use in CI)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    paths = sorted(args.input_dir.glob("*.jsonl"))
    if not paths:
        raise SystemExit(f"No .jsonl files found in {args.input_dir}")

    reports = []
    for path in paths:
        payload = compute_dialog_telemetry(load_transcript_lines(path))
        reports.append(payload)
        out_path = args.output_dir / f"{path.stem}.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        accuracy = payload["accuracy"]
        status = "PASS" if payload["gates_passed"] else "FAIL"
        print(
            f"{path.stem} {status} "
            f"errors={accuracy['errors']} warnings={accuracy['warnings']} "
            f"flat={payload['variety']['flat_line_ratio']} "
            f"{payload['gate_failures']}"
        )

    summary = aggregate_dialog_telemetry(reports)
    if args.summary is not None:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print()
    print("BATCH", "PASS" if summary["gates_passed"] else "FAIL")
    print(json.dumps(summary["medians"], indent=2))
    print(json.dumps(summary["finding_counts"], indent=2))
    if summary["gate_failures"]:
        print("gate failures:")
        for failure in summary["gate_failures"]:
            print(" -", failure)
    if args.fail_on_gate and not summary["gates_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
