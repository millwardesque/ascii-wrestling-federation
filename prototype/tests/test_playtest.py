"""Tests for headless playtest mode."""

from __future__ import annotations

import io
import json
import unittest

from main import run_match
from playtest.policies import choose_policy_index
from playtest.telemetry import compute_telemetry
from render_fixed import _MoveChoice
from render_playtest import PlaytestRenderer
from moves import MoveRule, all_move_rules


def _rule_by_id(move_id: str) -> MoveRule:
    return next(r for r in all_move_rules() if r.move.id == move_id)


class TestPlaytestPolicies(unittest.TestCase):
    def test_novice_picks_low_index(self) -> None:
        choices = [
            _MoveChoice(0, _rule_by_id("punch"), "Safe offense", "note", 1.0),
            _MoveChoice(1, _rule_by_id("kick"), "Safe offense", "note", 1.0),
        ]
        idx = choose_policy_index("novice", choices, __import__("random").Random(0))
        self.assertEqual(idx, 2)


class TestPlaytestRenderer(unittest.TestCase):
    def test_playtest_emits_jsonl(self) -> None:
        buf = io.StringIO()
        renderer = PlaytestRenderer(
            policy="novice",
            output=buf,
            wrestler_ids=("bret_hart", "scott_hall"),
            rng=__import__("random").Random(42),
        )
        run_match(
            "bret_hart",
            "scott_hall",
            renderer,
            match_seed=42,
        )
        lines = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
        self.assertEqual(lines[0]["event"], "match_start")
        self.assertEqual(lines[0]["match_seed"], 42)
        self.assertIn("commentary_team", lines[0])
        self.assertEqual(len(lines[0]["commentary_team"]), 2)
        self.assertIn("commentary_team_label", lines[0])
        self.assertEqual(lines[-1]["event"], "match_end")
        turns = [row for row in lines if row["event"] == "turn"]
        self.assertGreater(len(turns), 0)
        player_turn = next(row for row in turns if row["actor"] == "player")
        self.assertIn("choices", player_turn)
        self.assertIn("state", player_turn)

    def test_max_turns_emits_cap_reason(self) -> None:
        buf = io.StringIO()
        renderer = PlaytestRenderer(
            policy="chaotic",
            output=buf,
            max_turns=4,
            wrestler_ids=("bret_hart", "scott_hall"),
            rng=__import__("random").Random(7),
        )
        run_match(
            "bret_hart",
            "scott_hall",
            renderer,
            match_seed=7,
            max_turns=4,
        )
        end = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertEqual(end["event"], "match_end")
        self.assertEqual(end["reason"], "max_turns")
        self.assertEqual(end["turn_count"], 4)


class TestPlaytestTelemetry(unittest.TestCase):
    def test_compute_telemetry_from_transcript(self) -> None:
        buf = io.StringIO()
        renderer = PlaytestRenderer(
            policy="methodical",
            output=buf,
            wrestler_ids=("bret_hart", "scott_hall"),
            rng=__import__("random").Random(99),
        )
        run_match("bret_hart", "scott_hall", renderer, match_seed=99)
        rows = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
        telemetry = compute_telemetry(rows)
        self.assertIn("turn_count", telemetry)
        self.assertIn("gates_passed", telemetry)
        self.assertEqual(telemetry["match_seed"], 99)


if __name__ == "__main__":
    unittest.main()
