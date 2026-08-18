"""Tests for narration-site coverage."""

from __future__ import annotations

import io
import json
import random
import unittest

from main import run_match
from playtest.narration_coverage import (
    coverage,
    narration_sites,
    site_pattern,
    transcript_lines,
)
from render_playtest import PlaytestRenderer


class TestNarrationSites(unittest.TestCase):
    def test_catalog_is_non_trivial(self) -> None:
        sites = narration_sites()
        self.assertGreater(len(sites), 25)
        shapes = {site["shape"] for site in sites}
        self.assertIn("{} kicks out!", shapes)
        self.assertIn("The hold is cinched in deeper!", shapes)

    def test_fstring_fragments_are_not_separate_sites(self) -> None:
        shapes = {site["shape"] for site in narration_sites()}
        self.assertIn(
            "The crowd gasps — {} is busted open; blood streams down their face.",
            shapes,
        )
        self.assertNotIn("The crowd gasps —", shapes)

    def test_pattern_matches_only_its_own_rendering(self) -> None:
        pattern = site_pattern("  {} kicks out!".replace("{}", "\x00"))
        self.assertTrue(pattern.match("Hall kicks out!"))
        self.assertFalse(pattern.match("Hall taps out!"))


class TestCoverageReport(unittest.TestCase):
    def test_uncovered_sites_are_listed(self) -> None:
        report = coverage(["Hall kicks out!"])
        self.assertEqual(report["hits"][_site_id("{} kicks out!")], 1)
        self.assertGreater(len(report["uncovered"]), 0)
        self.assertLess(report["coverage_ratio"], 1.0)
        self.assertEqual(report["unmatched_line_count"], 0)

    def test_unknown_line_is_reported_as_unmatched(self) -> None:
        report = coverage(["Hall does something the engine cannot say."])
        self.assertEqual(report["unmatched_line_count"], 1)

    def test_specific_site_wins_over_the_fallback_shape(self) -> None:
        # "{}: {}." would also match, but the knockdown line is more specific.
        report = coverage(["Hall collapses to the canvas — the cover is there for the taking!"])
        self.assertEqual(
            report["hits"][
                _site_id("{} collapses to the canvas — the cover is there for the taking!")
            ],
            1,
        )


class TestLiveMatchCoverage(unittest.TestCase):
    def test_live_matches_only_emit_known_sites(self) -> None:
        lines: list[str] = []
        for seed in (3, 77, 505, 9001):
            buf = io.StringIO()
            renderer = PlaytestRenderer(
                policy="chaotic",
                output=buf,
                max_turns=60,
                wrestler_ids=("bret_hart", "scott_hall"),
                rng=random.Random(seed),
            )
            run_match(
                "bret_hart",
                "scott_hall",
                renderer,
                match_seed=seed,
                max_turns=60,
            )
            rows = [
                json.loads(line)
                for line in buf.getvalue().splitlines()
                if line.strip()
            ]
            lines.extend(transcript_lines(rows))

        report = coverage(lines)
        self.assertEqual(
            report["unmatched_line_count"],
            0,
            msg=f"narration not in the catalog: {report['unmatched_examples']}",
        )
        self.assertGreater(report["covered_count"], 10)


def _site_id(shape: str) -> str:
    return next(site["id"] for site in narration_sites() if site["shape"] == shape)


if __name__ == "__main__":
    unittest.main()
