"""Tests for headless playtest mode."""

from __future__ import annotations

import io
import json
import random
import unittest

from main import run_match
from moves import MoveRule, all_move_rules
from playtest.policies import choose_policy_index
from playtest.telemetry import compute_telemetry
from render_fixed import _MoveChoice
from render_playtest import PlaytestRenderer


def _rule_by_id(move_id: str) -> MoveRule:
    return next(r for r in all_move_rules() if r.move.id == move_id)


def _choice(move_id: str, intent: str, *, score: float, conceded: int) -> _MoveChoice:
    return _MoveChoice(
        0,
        _rule_by_id(move_id),
        intent,
        "note",
        score,
        False,
        1.5,
        conceded,
    )


def _run(policy: str, seed: int, *, max_actions: int | None = None) -> list[dict]:
    buf = io.StringIO()
    renderer = PlaytestRenderer(
        policy=policy,
        output=buf,
        max_actions=max_actions,
        wrestler_ids=("bret_hart", "scott_hall"),
        rng=random.Random(seed),
    )
    run_match(
        "bret_hart",
        "scott_hall",
        renderer,
        match_seed=seed,
        max_actions=max_actions,
    )
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


class TestPlaytestPolicies(unittest.TestCase):
    def test_novice_picks_low_index(self) -> None:
        choices = [
            _choice("punch", "Safe offense", score=1.0, conceded=0),
            _choice("kick", "Safe offense", score=1.0, conceded=0),
        ]
        self.assertEqual(choose_policy_index("novice", choices, random.Random(0)), 2)

    def test_tempo_policy_refuses_to_concede_the_initiative(self) -> None:
        choices = [
            _choice("stunner", "Finish", score=200.0, conceded=2),
            _choice("punch", "Safe offense", score=10.0, conceded=0),
        ]
        self.assertEqual(choose_policy_index("tempo", choices, random.Random(0)), 2)

    def test_tempo_policy_takes_the_best_move_that_does_not_concede(self) -> None:
        """Ties break on score, or the policy degenerates into picking resets forever."""
        choices = [
            _choice("recover", "Reset / recover", score=5.0, conceded=0),
            _choice("punch", "Safe offense", score=60.0, conceded=0),
            _choice("stunner", "Finish", score=200.0, conceded=3),
        ]
        self.assertEqual(choose_policy_index("tempo", choices, random.Random(0)), 2)


class TestPlaytestRenderer(unittest.TestCase):
    def test_playtest_emits_one_record_per_action(self) -> None:
        lines = _run("novice", 42)
        self.assertEqual(lines[0]["event"], "match_start")
        self.assertEqual(lines[0]["match_seed"], 42)
        self.assertEqual(lines[-1]["event"], "match_end")

        actions = [row for row in lines if row["event"] == "action"]
        self.assertGreater(len(actions), 0)
        self.assertEqual(
            [row["action"] for row in actions],
            list(range(1, len(actions) + 1)),
            "action indices should be a dense global counter",
        )

        player_action = next(row for row in actions if row["actor"] == "player")
        self.assertIn("choices", player_action)
        self.assertIn("surge", player_action["state"])
        self.assertEqual(len(player_action["state"]["surge"]), 2)

    def test_records_carry_timeline_position_and_speed(self) -> None:
        actions = [row for row in _run("novice", 42) if row["event"] == "action"]
        times = [row["sim_time"] for row in actions]
        self.assertEqual(times, sorted(times), "sim_time must never run backwards")
        self.assertGreater(times[-1], 0.0)
        for row in actions:
            self.assertGreater(row["actor_speed"], 0.0)
            self.assertGreater(row["tempo_cost"], 0.0)

    def test_menu_rows_carry_their_tempo_consequence(self) -> None:
        actions = [row for row in _run("novice", 42) if row["event"] == "action"]
        player_action = next(row for row in actions if row["actor"] == "player")
        for choice in player_action["choices"]:
            self.assertIn("tempo_cost", choice)
            self.assertIn("conceded", choice)
            self.assertGreaterEqual(choice["conceded"], 0)

    def test_max_actions_emits_cap_reason(self) -> None:
        lines = _run("chaotic", 7, max_actions=4)
        end = lines[-1]
        self.assertEqual(end["event"], "match_end")
        self.assertEqual(end["reason"], "max_actions")
        self.assertEqual(end["action_count"], 4)


class TestPlaytestTelemetry(unittest.TestCase):
    def test_compute_telemetry_from_transcript(self) -> None:
        telemetry = compute_telemetry(_run("methodical", 99))
        self.assertIn("action_count", telemetry)
        self.assertIn("gates_passed", telemetry)
        self.assertEqual(telemetry["match_seed"], 99)

    def test_telemetry_reports_tempo_metrics(self) -> None:
        telemetry = compute_telemetry(_run("methodical", 99))
        self.assertGreaterEqual(telemetry["consecutive_action_max"], 1)
        self.assertGreaterEqual(telemetry["action_ratio"], 1.0)
        self.assertGreater(telemetry["sim_time_total"], 0.0)
        self.assertEqual(
            telemetry["actions_player"] + telemetry["actions_cpu"],
            telemetry["action_count"],
        )

    def test_gate_flags_a_scheduler_that_never_produces_a_flurry(self) -> None:
        """If nobody ever acts twice in a row, the turn queue is doing nothing."""
        rows = [
            {"event": "match_start", "match_seed": 1},
            *[
                {
                    "event": "action",
                    "action": i + 1,
                    "actor": "player" if i % 2 == 0 else "cpu",
                    "log": "",
                    "outcome": "hit",
                    "state": {},
                }
                for i in range(20)
            ],
            {
                "event": "match_end",
                "action_count": 20,
                "sim_time": 20.0,
                "winner": "player",
                "reason": "pinfall",
            },
        ]
        telemetry = compute_telemetry(rows)
        self.assertEqual(telemetry["consecutive_action_max"], 1)
        self.assertFalse(telemetry["gates_passed"])
        self.assertTrue(
            any("flurry" in failure for failure in telemetry["gate_failures"])
        )

    def test_gate_flags_a_locked_out_wrestler(self) -> None:
        rows = [
            {"event": "match_start", "match_seed": 1},
            *[
                {
                    "event": "action",
                    "action": i + 1,
                    "actor": "player" if i < 18 else "cpu",
                    "log": "",
                    "outcome": "hit",
                    "state": {},
                }
                for i in range(20)
            ],
            {
                "event": "match_end",
                "action_count": 20,
                "sim_time": 20.0,
                "winner": "player",
                "reason": "pinfall",
            },
        ]
        telemetry = compute_telemetry(rows)
        self.assertTrue(
            any("locked out" in failure for failure in telemetry["gate_failures"])
        )


if __name__ == "__main__":
    unittest.main()
