"""Tests for dual-voice commentary rendering."""

from __future__ import annotations

import unittest

from commentators import CommentatorPair
from commentary import CommentaryEngine
from commentary_events import MatchEvent
from commentary_templates import validate_move_commentary
from moves import all_move_rules
from wrestlers import ROSTER


def _hart_hall():
    return (ROSTER["bret_hart"], ROSTER["scott_hall"])


class TestCommentaryEngine(unittest.TestCase):
    def test_booth_intro_has_pbp_and_color(self) -> None:
        engine = CommentaryEngine(CommentatorPair("gorilla", "heenan"))
        lines = engine.booth_intro_lines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].role, "pbp")
        self.assertEqual(lines[1].role, "color")
        self.assertIn("Gorilla Monsoon", lines[0].text)
        self.assertIn("Bobby Heenan", lines[0].text)

    def test_hit_then_groggy_names_the_move(self) -> None:
        engine = CommentaryEngine(CommentatorPair("gorilla", "ventura"), seed=1)
        events = [
            MatchEvent(
                kind="damage",
                actor=0,
                target=1,
                move_id="punch",
                move_name="Punch",
                amount=6,
            ),
            MatchEvent(
                kind="groggy_applied",
                actor=0,
                target=1,
                move_id="punch",
                move_name="Punch",
            ),
        ]
        lines = engine.render_turn(events, wrestlers=_hart_hall())
        joined = " ".join(line.text.lower() for line in lines)
        self.assertTrue(
            "punch" in joined or "straight right" in joined or "right hand" in joined,
            msg=joined,
        )
        self.assertTrue(
            any(
                "feet" in line.text.lower()
                or "wobbly" in line.text.lower()
                or "where they are" in line.text.lower()
                for line in lines
            )
        )

    def test_render_turn_always_has_play_by_play(self) -> None:
        engine = CommentaryEngine(CommentatorPair("gorilla", "ventura"), seed=1)
        events = [
            MatchEvent(
                kind="damage",
                actor=0,
                target=1,
                move_id="punch",
                move_name="Punch",
                amount=6,
            )
        ]
        lines = engine.render_turn(events, wrestlers=_hart_hall())
        self.assertGreaterEqual(len(lines), 1)
        self.assertEqual(lines[0].role, "pbp")
        self.assertEqual(lines[0].speaker_id, "gorilla")
        joined = " ".join(line.text for line in lines)
        self.assertIn("Hitman", joined)
        self.assertNotRegex(joined, r"\b6\b")

    def test_format_turn_uses_speaker_shorts(self) -> None:
        engine = CommentaryEngine(CommentatorPair("ross", "lawler"), seed=2)
        events = [
            MatchEvent(
                kind="setup",
                actor=0,
                target=1,
                move_id="collar_elbow",
                move_name="Collar-and-elbow tie-up",
            )
        ]
        text = engine.format_turn(events, wrestlers=_hart_hall())
        self.assertIn("JR:", text)
        self.assertTrue(text.strip().startswith("JR:"))

    def test_pin_count_is_pbp_only(self) -> None:
        engine = CommentaryEngine(CommentatorPair("gorilla", "ventura"), seed=0)
        events = [
            MatchEvent(kind="pin_count", actor=0, target=1, pin_count=1)
        ]
        lines = engine.render_turn(events, wrestlers=_hart_hall())
        self.assertEqual([line.role for line in lines], ["pbp"])
        self.assertIn("one", lines[0].text.lower())

    def test_top_rope_whiff_mentions_the_crash(self) -> None:
        engine = CommentaryEngine(CommentatorPair("gorilla", "ventura"), seed=4)
        events = [
            MatchEvent(
                kind="reversal",
                actor=0,
                target=1,
                move_id="top_splash",
                move_name="Flying splash",
                amount=2,
            ),
            MatchEvent(
                kind="position_change",
                actor=0,
                move_id="top_splash",
                move_name="Flying splash",
                position="GROUNDED",
            ),
        ]
        lines = engine.render_turn(events, wrestlers=_hart_hall())
        joined = " ".join(line.text.lower() for line in lines)
        self.assertTrue("crash" in joined or "buckle" in joined)

    def test_kickout_brings_color(self) -> None:
        engine = CommentaryEngine(CommentatorPair("gorilla", "heenan"), seed=3)
        events = [
            MatchEvent(kind="pin_kickout", actor=0, target=1, pin_count=2, won=False)
        ]
        lines = engine.render_turn(events, wrestlers=_hart_hall())
        roles = [line.role for line in lines]
        self.assertIn("pbp", roles)
        self.assertIn("color", roles)

    def test_same_seed_same_lines(self) -> None:
        events = [
            MatchEvent(
                kind="damage",
                actor=1,
                target=0,
                move_id="kick",
                move_name="Kick",
                amount=4,
            )
        ]
        a = CommentaryEngine(CommentatorPair("solie", "cornette"), seed=99)
        b = CommentaryEngine(CommentatorPair("solie", "cornette"), seed=99)
        self.assertEqual(
            a.format_turn(events, wrestlers=_hart_hall()),
            b.format_turn(events, wrestlers=_hart_hall()),
        )

    def test_move_specific_success_overrides_generic(self) -> None:
        engine = CommentaryEngine(CommentatorPair("gorilla", "heenan"), seed=0)
        events = [
            MatchEvent(
                kind="damage",
                actor=0,
                target=1,
                move_id="punch",
                move_name="Punch",
                amount=6,
            )
        ]
        lines = engine.render_turn(events, wrestlers=_hart_hall())
        pbp = next(line for line in lines if line.role == "pbp")
        lowered = pbp.text.lower()
        self.assertTrue(
            "straight right" in lowered or "right hand" in lowered,
            msg=pbp.text,
        )

    def test_move_specific_failed_overrides_reversal(self) -> None:
        engine = CommentaryEngine(CommentatorPair("gorilla", "heenan"), seed=0)
        events = [
            MatchEvent(
                kind="reversal",
                actor=0,
                target=1,
                move_id="punch",
                move_name="Punch",
                amount=1,
            )
        ]
        lines = engine.render_turn(events, wrestlers=_hart_hall())
        color = next((line for line in lines if line.role == "color"), None)
        self.assertIsNotNone(color)
        assert color is not None
        lowered = color.text.lower()
        self.assertTrue(
            "barn" in lowered or "whiffed" in lowered or "give me a break" in lowered,
            msg=color.text,
        )

    def test_move_without_templates_falls_back_to_role_pool(self) -> None:
        engine = CommentaryEngine(CommentatorPair("gorilla", "heenan"), seed=1)
        events = [
            MatchEvent(
                kind="damage",
                actor=0,
                target=1,
                move_id="kick",
                move_name="Kick",
                amount=4,
            )
        ]
        lines = engine.render_turn(events, wrestlers=_hart_hall())
        joined = " ".join(line.text for line in lines)
        self.assertIn("Hitman", joined)


class TestMoveCommentaryRegistry(unittest.TestCase):
    def test_registry_move_ids_exist(self) -> None:
        valid = frozenset(rule.move.id for rule in all_move_rules())
        validate_move_commentary(valid)


if __name__ == "__main__":
    unittest.main()
