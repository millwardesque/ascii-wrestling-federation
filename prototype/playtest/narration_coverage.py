#!/usr/bin/env python3
"""Narration-site coverage: which lines the game can print have we ever audited?

Dialog defects hide in rare copy. Random seeds barely reach it — across the
committed transcripts ``KNOCKOUT`` fires once — so sampling matches tells you
nothing about whether the rare lines are correct.

This module enumerates every narration site in ``game.py`` straight from the
source (every string literal that starts with the two-space narration indent),
then reports which sites a transcript corpus actually exercised. Uncovered sites
are copy no evaluation has ever looked at.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from playtest.dialog_telemetry import load_transcript_lines


NARRATION_INDENT = "  "
DEFAULT_SOURCE = Path(__file__).resolve().parent.parent / "game.py"
_SLOT = "\x00"


def _shape(node: ast.AST) -> str | None:
    """Render a string node as literal text with ``{}`` for interpolations."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if not isinstance(node, ast.JoinedStr):
        return None
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        else:
            parts.append(_SLOT)
    return "".join(parts)


def _string_nodes(tree: ast.AST) -> list[ast.AST]:
    """String nodes, without descending into f-strings and re-reporting their parts."""
    out: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        if _shape(node) is not None:
            out.append(node)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return out


def site_pattern(shape: str) -> re.Pattern[str]:
    """Regex that matches a rendered line for ``shape`` (``{}`` becomes a wildcard)."""
    body = "".join(
        ".+?" if piece == _SLOT else re.escape(piece)
        for piece in re.split(f"({_SLOT})", shape.strip())
    )
    return re.compile(f"^{body}$")


def narration_sites(source: Path | str = DEFAULT_SOURCE) -> list[dict[str, Any]]:
    """Every distinct narration line ``game.py`` can emit, keyed by shape."""
    tree = ast.parse(Path(source).read_text(encoding="utf-8"))
    found: dict[str, dict[str, Any]] = {}
    for node in _string_nodes(tree):
        raw = _shape(node) or ""
        if not raw.startswith(NARRATION_INDENT) or not raw.strip(f" {_SLOT}"):
            continue
        entry = found.setdefault(
            raw.strip(),
            {
                "shape": raw.strip().replace(_SLOT, "{}"),
                "pattern": site_pattern(raw),
                "source_lines": [],
            },
        )
        entry["source_lines"].append(getattr(node, "lineno", 0))
    sites = sorted(found.values(), key=lambda s: min(s["source_lines"]))
    for index, site in enumerate(sites):
        site["id"] = f"site_{index:03d}"
        site["source_lines"] = sorted(set(site["source_lines"]))
    return sites


def _matches(site: dict[str, Any], line: str) -> bool:
    return site["pattern"].match(line) is not None


def transcript_lines(rows: Iterable[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for row in rows:
        if row.get("event") != "turn":
            continue
        for line in str(row.get("log") or "").splitlines():
            if line.strip():
                out.append(line.strip())
    return out


def coverage(
    lines: Iterable[str],
    *,
    sites: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Which narration sites the given lines exercised, and how often."""
    catalog = sites if sites is not None else narration_sites()
    hits = {site["id"]: 0 for site in catalog}
    unmatched: list[str] = []
    for line in lines:
        # Wildcards let several shapes match one line; credit the most specific.
        candidates = [site for site in catalog if _matches(site, line)]
        if not candidates:
            unmatched.append(line)
            continue
        best = max(candidates, key=lambda site: len(site["shape"].replace("{}", "")))
        hits[best["id"]] += 1

    covered = [site for site in catalog if hits[site["id"]] > 0]
    uncovered = [site for site in catalog if hits[site["id"]] == 0]
    rare = sorted(
        (
            {"id": site["id"], "shape": site["shape"], "hits": hits[site["id"]]}
            for site in covered
        ),
        key=lambda entry: entry["hits"],
    )[:10]
    return {
        "site_count": len(catalog),
        "covered_count": len(covered),
        "coverage_ratio": round(len(covered) / len(catalog), 4) if catalog else 0.0,
        "uncovered": [
            {"id": site["id"], "shape": site["shape"], "source_lines": site["source_lines"]}
            for site in uncovered
        ],
        "rarest_covered": rare,
        "unmatched_line_count": len(unmatched),
        "unmatched_examples": sorted(set(unmatched))[:10],
        "hits": hits,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report which narration sites a transcript corpus exercised"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("playtest/transcripts"),
        help="directory containing <seed>.jsonl transcripts",
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write the coverage JSON here",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=None,
        help="exit non-zero when coverage_ratio falls below this",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    paths = sorted(args.input_dir.glob("*.jsonl"))
    if not paths:
        raise SystemExit(f"No .jsonl files found in {args.input_dir}")

    lines: list[str] = []
    for path in paths:
        lines.extend(transcript_lines(load_transcript_lines(path)))

    report = coverage(lines, sites=narration_sites(args.source))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        f"{report['covered_count']}/{report['site_count']} narration sites covered "
        f"({report['coverage_ratio']:.0%}) over {len(paths)} transcripts"
    )
    if report["uncovered"]:
        print("\nnever exercised:")
        for site in report["uncovered"]:
            print(f"  {site['id']} game.py:{site['source_lines'][0]}  {site['shape']}")
    if report["rarest_covered"]:
        print("\nthinnest evidence:")
        for entry in report["rarest_covered"]:
            print(f"  {entry['hits']:4d}x  {entry['shape']}")
    if report["unmatched_examples"]:
        print("\nlines matching no known site (renderer or stale copy):")
        for line in report["unmatched_examples"]:
            print(f"  {line}")
    if args.min_coverage is not None and report["coverage_ratio"] < args.min_coverage:
        raise SystemExit(
            f"coverage_ratio {report['coverage_ratio']} below {args.min_coverage}"
        )


if __name__ == "__main__":
    main()
