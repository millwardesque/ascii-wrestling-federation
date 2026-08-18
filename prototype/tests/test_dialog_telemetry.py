"""Tests for Layer 1 dialog telemetry (narration accuracy checks)."""

from __future__ import annotations

import io
import json
import random
import unittest

from main import run_match
from playtest.dialog_telemetry import (
    aggregate_dialog_telemetry,
    compute_dialog_telemetry,
    phrasing_template,
)
from render_playtest import PlaytestRenderer
from wrestlers import ROSTER


HITMAN = ROSTER["bret_hart"].max_health
HALL = ROSTER["scott_hall"].max_health


def _transcript(*turns: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "event": "match_start",
            "match_seed": 1,
            "wrestlers": ["bret_hart", "scott_hall"],
            "player_policy": "novice",
        }
    ]
    rows.extend(turns)
    rows.append(
        {
            "event": "match_end",
            "match_seed": 1,
            "turn_count": len(turns),
            "winner": "player",
            "reason": "pinfall",
        }
    )
    return rows


def _turn(
    *,
    turn: int = 1,
    log: str,
    health: list[int] | None = None,
    position: list[str] | None = None,
    groggy: list[bool] | None = None,
    move: str = "Straight right",
    actor: str = "player",
) -> dict[str, object]:
    return {
        "event": "turn",
        "turn": turn,
        "actor": actor,
        "match_seed": 1,
        "move": move,
        "move_id": "punch",
        "choices": [],
        "selected_index": 1,
        "log": log,
        "outcome": "hit",
        "state": {
            "health": health if health is not None else [HITMAN, HALL],
            "momentum": [0, 0],
            "position": position or ["STANDING", "STANDING"],
            "groggy": groggy or [False, False],
        },
    }


def _codes(report: dict[str, object]) -> list[str]:
    return [str(f["code"]) for f in report["findings"]]  # type: ignore[index]


class TestDialogAccuracy(unittest.TestCase):
    def test_faithful_line_has_no_findings(self) -> None:
        rows = _transcript(
            _turn(
                log="  Hitman snaps off straight right — Hall takes 6 damage.",
                health=[HITMAN, HALL - 6],
            )
        )
        report = compute_dialog_telemetry(rows)
        self.assertEqual(report["accuracy"]["errors"], 0)
        self.assertEqual(_codes(report), [])
        self.assertTrue(report["gates_passed"])

    def test_wrong_damage_number_is_an_error(self) -> None:
        rows = _transcript(
            _turn(
                log="  Hitman snaps off straight right — Hall takes 6 damage.",
                health=[HITMAN, HALL - 9],
            )
        )
        report = compute_dialog_telemetry(rows)
        self.assertIn("number_mismatch", _codes(report))
        self.assertFalse(report["gates_passed"])

    def test_damage_claimed_but_none_dealt_is_phantom(self) -> None:
        rows = _transcript(
            _turn(log="  Hitman snaps off straight right — Hall takes 6 damage.")
        )
        report = compute_dialog_telemetry(rows)
        self.assertIn("phantom_damage_claim", _codes(report))

    def test_condition_change_with_no_line_is_an_error(self) -> None:
        rows = _transcript(
            _turn(log="  Hitman: Straight right.", health=[HITMAN, HALL - 4])
        )
        report = compute_dialog_telemetry(rows)
        self.assertIn("unnarrated_condition_change", _codes(report))

    def test_clamped_claim_is_only_a_warning(self) -> None:
        rows = _transcript(
            _turn(
                log=f"  Hitman snaps off straight right — Hall takes {HALL - 4} damage.",
                health=[HITMAN, 4],
            ),
            _turn(
                turn=2,
                log="  Hitman snaps off straight right — Hall takes 9 damage.",
                health=[HITMAN, 0],
            ),
        )
        report = compute_dialog_telemetry(rows)
        self.assertIn("clamped_number_claim", _codes(report))
        self.assertEqual(report["accuracy"]["errors"], 0)

    def test_reversal_line_attributes_chip_damage_to_the_reverser(self) -> None:
        rows = _transcript(
            _turn(
                log="  Hall reverses the straight right — only 1 damage, and turns the tables!",
                health=[HITMAN, HALL - 1],
            )
        )
        self.assertEqual(compute_dialog_telemetry(rows)["accuracy"]["errors"], 0)

    def test_groggy_claim_must_match_state(self) -> None:
        good = _transcript(
            _turn(
                log="  Hall is GROGGY — power moves and finishers are live!",
                groggy=[False, True],
            )
        )
        self.assertEqual(compute_dialog_telemetry(good)["accuracy"]["errors"], 0)

        bad = _transcript(
            _turn(log="  Hall is GROGGY — power moves and finishers are live!")
        )
        self.assertIn("groggy_claim_unsupported", _codes(compute_dialog_telemetry(bad)))

    def test_shake_off_claim_must_match_state(self) -> None:
        rows = _transcript(
            _turn(log="  Hall steadies themselves — they're back!", groggy=[False, True])
        )
        self.assertIn("groggy_clear_unsupported", _codes(compute_dialog_telemetry(rows)))

    def test_knockdown_claim_must_match_position(self) -> None:
        rows = _transcript(
            _turn(
                log="  Hall collapses to the canvas — the cover is there for the taking!",
                position=["STANDING", "STANDING"],
            )
        )
        self.assertIn(
            "grounded_claim_unsupported", _codes(compute_dialog_telemetry(rows))
        )

    def test_knockout_claim_requires_zero_condition(self) -> None:
        rows = _transcript(
            _turn(
                log="  Hall crumples and doesn't move — they are out cold!",
                position=["STANDING", "GROUNDED"],
                health=[HITMAN, 12],
            )
        )
        codes = _codes(compute_dialog_telemetry(rows))
        self.assertIn("knockout_claim_unsupported", codes)

    def test_wrestler_from_another_match_is_an_error(self) -> None:
        rows = _transcript(
            _turn(
                log="  Hitman snaps off straight right — Hulkster takes 6 damage.",
                health=[HITMAN, HALL - 6],
            )
        )
        codes = _codes(compute_dialog_telemetry(rows))
        self.assertIn("foreign_wrestler_named", codes)

    def test_placeholder_leak_is_an_error(self) -> None:
        rows = _transcript(_turn(log="  {actor} snaps off None."))
        self.assertIn("template_leak", _codes(compute_dialog_telemetry(rows)))

    def test_ansi_in_narration_is_an_error(self) -> None:
        rows = _transcript(_turn(log="  \x1b[31mHitman\x1b[0m: Straight right."))
        self.assertIn("ansi_in_transcript", _codes(compute_dialog_telemetry(rows)))


class TestDialogQualityMetrics(unittest.TestCase):
    def test_contradictory_line_is_flagged(self) -> None:
        rows = _transcript(
            _turn(
                log=(
                    "  Hall reverses the straight right — only 2 damage; "
                    "Hitman whiffs — Hall shrugs it off."
                ),
                health=[HITMAN, HALL - 2],
            )
        )
        self.assertIn("contradictory_claim", _codes(compute_dialog_telemetry(rows)))

    def test_unnamed_wrestler_with_changed_position_is_flagged(self) -> None:
        rows = _transcript(
            _turn(log="  Hitman: Collar-and-elbow tie-up.", move="Collar-and-elbow tie-up"),
            _turn(
                turn=2,
                log="  Hitman: Collar-and-elbow tie-up.",
                move="Collar-and-elbow tie-up",
                position=["STANDING", "GRAPPLED"],
            ),
        )
        report = compute_dialog_telemetry(rows)
        self.assertIn("silent_state_change", _codes(report))

    def test_flat_fallback_lines_are_counted(self) -> None:
        rows = _transcript(
            _turn(log="  Hitman: Collar-and-elbow tie-up.", move="Collar-and-elbow tie-up"),
            _turn(
                turn=2,
                log="  Hitman snaps off straight right — Hall takes 3 damage.",
                health=[HITMAN, HALL - 3],
            ),
        )
        report = compute_dialog_telemetry(rows)
        self.assertEqual(report["variety"]["flat_line_ratio"], 0.5)

    def test_reserved_vocabulary_is_flagged(self) -> None:
        rows = _transcript(_turn(log="  Hall is stunned and down to 40 HP."))
        codes = _codes(compute_dialog_telemetry(rows))
        self.assertEqual(codes.count("lexicon_violation"), 2)

    def test_phrasing_template_collapses_names_numbers_and_moves(self) -> None:
        first = phrasing_template(
            "Hitman snaps off straight right — Hall takes 6 damage.",
            ("Hitman", "Hall"),
            ("Straight right",),
        )
        second = phrasing_template(
            "Hall snaps off missile dropkick — Hitman takes 11 damage.",
            ("Hitman", "Hall"),
            ("Missile dropkick",),
        )
        self.assertEqual(first, second)

    def test_repeated_phrasing_run_is_measured(self) -> None:
        rows = _transcript(
            *[
                _turn(
                    turn=index + 1,
                    log="  Hitman: Collar-and-elbow tie-up.",
                    move="Collar-and-elbow tie-up",
                )
                for index in range(9)
            ]
        )
        report = compute_dialog_telemetry(rows)
        self.assertEqual(report["variety"]["max_consecutive_repeat"], 9)
        self.assertFalse(report["gates_passed"])

    def test_unverifiable_claims_record_a_schema_gap(self) -> None:
        rows = _transcript(
            _turn(
                log=(
                    "  The crowd gasps — Hall is busted open; blood streams down their face."
                )
            )
        )
        report = compute_dialog_telemetry(rows)
        self.assertEqual(report["accuracy"]["errors"], 0)
        self.assertIn("state.bloodied", report["accuracy"]["schema_gaps"])
        self.assertLess(report["accuracy"]["claim_verifiability_ratio"], 1.0)


class TestDialogBatchAggregate(unittest.TestCase):
    def test_batch_fails_when_any_match_has_accuracy_errors(self) -> None:
        clean = compute_dialog_telemetry(
            _transcript(
                _turn(
                    log="  Hitman snaps off straight right — Hall takes 6 damage.",
                    health=[HITMAN, HALL - 6],
                )
            )
        )
        broken = compute_dialog_telemetry(
            _transcript(
                _turn(
                    log="  Hitman snaps off straight right — Hall takes 6 damage.",
                    health=[HITMAN, HALL - 2],
                )
            )
        )
        summary = aggregate_dialog_telemetry([clean, broken])
        self.assertFalse(summary["gates_passed"])
        self.assertEqual(summary["match_count"], 2)
        self.assertEqual(summary["accuracy_errors_total"], 1)
        self.assertIn("number_mismatch", summary["finding_counts"])

    def test_empty_batch_fails_loudly(self) -> None:
        summary = aggregate_dialog_telemetry([])
        self.assertFalse(summary["gates_passed"])


class TestLiveMatchNarration(unittest.TestCase):
    """Regression guard: real matches must not print unsupported claims."""

    def test_seeded_matches_have_no_accuracy_errors(self) -> None:
        reports = []
        for seed in (11, 202, 4242):
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
            report = compute_dialog_telemetry(rows)
            reports.append(report)
            self.assertEqual(
                report["accuracy"]["errors"],
                0,
                msg=f"seed {seed}: {[f for f in report['findings'] if f['severity'] == 'error']}",
            )
        summary = aggregate_dialog_telemetry(reports)
        self.assertEqual(summary["accuracy_errors_total"], 0)


if __name__ == "__main__":
    unittest.main()
