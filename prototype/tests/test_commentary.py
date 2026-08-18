"""Tests for commentary engine stub."""

from __future__ import annotations

import unittest

from commentators import CommentatorPair
from commentary import CommentaryEngine


class TestCommentaryEngine(unittest.TestCase):
    def test_booth_intro_has_pbp_and_color(self) -> None:
        engine = CommentaryEngine(CommentatorPair("gorilla", "heenan"))
        lines = engine.booth_intro_lines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].role, "pbp")
        self.assertEqual(lines[1].role, "color")
        self.assertIn("Gorilla Monsoon", lines[0].text)
        self.assertIn("Bobby Heenan", lines[0].text)


if __name__ == "__main__":
    unittest.main()
