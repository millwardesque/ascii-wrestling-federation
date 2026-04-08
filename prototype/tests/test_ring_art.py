"""Ring ASCII: idle layout and animation key resolution."""

from __future__ import annotations

import unittest

from game import MatchState
from moves import all_move_rules
from ring_art import (
    animation_for_move,
    frames_for_key,
    idle_ring_lines,
)
from wrestlers import ROSTER


class TestRingArt(unittest.TestCase):
    def test_idle_ring_line_count(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        lines = idle_ring_lines(st)
        self.assertEqual(len(lines), 6)
        self.assertIn("YOU", lines[0])
        self.assertIn("CPU", lines[0])

    def test_pin_maps_to_pin_attempt(self) -> None:
        pin = next(r for r in all_move_rules() if r.move.id == "pin")
        self.assertEqual(animation_for_move("pin", pin.move), "pin_attempt")

    def test_stunner_override(self) -> None:
        st = next(r for r in all_move_rules() if r.move.id == "stunner")
        self.assertEqual(animation_for_move("stunner", st.move), "stunner")

    def test_cpu_attacker_frames_differ_from_player(self) -> None:
        f1 = frames_for_key("strike", actor_is_player=True)[1]
        g1 = frames_for_key("strike", actor_is_player=False)[1]
        self.assertNotEqual(f1, g1)


if __name__ == "__main__":
    unittest.main()
