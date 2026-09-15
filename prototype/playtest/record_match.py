#!/usr/bin/env python3
"""Run one or more headless playtest matches and optionally write telemetry."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from main import run_match
from playtest.telemetry import compute_telemetry
from render_playtest import PlaytestRenderer
from wrestlers import list_roster


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record AWF playtest JSONL transcripts")
    parser.add_argument("--seed", type=int, action="append", help="match seed (repeatable)")
    parser.add_argument(
        "--seeds",
        type=str,
        default="",
        help="comma-separated seed list, e.g. 1,2,3",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="number of random seeds when --seed not given",
    )
    parser.add_argument(
        "--policy",
        choices=("novice", "aggressive", "methodical", "chaotic"),
        default="chaotic",
    )
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="write <seed>.jsonl files here",
    )
    parser.add_argument(
        "--telemetry",
        action="store_true",
        help="print telemetry JSON after each match",
    )
    return parser.parse_args(argv)


def _seed_list(args: argparse.Namespace) -> list[int]:
    seeds: list[int] = []
    if args.seed:
        seeds.extend(args.seed)
    if args.seeds:
        for part in args.seeds.split(","):
            part = part.strip()
            if part:
                seeds.append(int(part))
    if seeds:
        return seeds
    rng = random.Random()
    return [rng.randrange(1 << 30) for _ in range(args.count)]


def record_match(
    *,
    player_id: str,
    cpu_id: str,
    seed: int,
    policy: str,
    max_turns: int | None,
    output: Path | None,
) -> str:
    import io

    buf = io.StringIO()
    renderer = PlaytestRenderer(
        policy=policy,
        output=buf,
        max_turns=max_turns,
        wrestler_ids=(player_id, cpu_id),
        rng=random.Random(seed),
    )
    run_match(
        player_id,
        cpu_id,
        renderer,
        match_seed=seed,
        max_turns=max_turns,
    )
    transcript = buf.getvalue()
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(transcript, encoding="utf-8")
    return transcript


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    roster = list_roster()
    if len(roster) < 2:
        raise SystemExit("Need at least two playable wrestlers.")
    player_id, cpu_id = roster[0].id, roster[1].id

    for seed in _seed_list(args):
        out_path = None
        if args.output_dir is not None:
            out_path = args.output_dir / f"{seed}.jsonl"
        transcript = record_match(
            player_id=player_id,
            cpu_id=cpu_id,
            seed=seed,
            policy=args.policy,
            max_turns=args.max_turns,
            output=out_path,
        )
        if args.telemetry:
            rows = [
                json.loads(line)
                for line in transcript.splitlines()
                if line.strip()
            ]
            print(json.dumps(compute_telemetry(rows), indent=2))


if __name__ == "__main__":
    main()
