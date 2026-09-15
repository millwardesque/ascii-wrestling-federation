"""Tests for TTY input helpers."""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from terminal_keys import read_move_choice_line


class TestMoveChoiceToggleKey(unittest.TestCase):
    def test_m_key_compare_uses_str_not_bytes(self) -> None:
        ch = "m"
        self.assertTrue(ch.lower() == "m")
        self.assertFalse(ch.lower() == b"m")  # type: ignore[comparison-overlap]

    @patch("terminal_keys.tty_interactive", return_value=False)
    def test_read_move_choice_line_accepts_m_in_line_mode(self, _tty: object) -> None:
        with patch("sys.stdin", io.StringIO("m\n")):
            self.assertEqual(read_move_choice_line(), "M")

    @patch("terminal_keys.tty_interactive", return_value=False)
    def test_read_move_choice_line_accepts_uppercase_m_in_line_mode(
        self, _tty: object
    ) -> None:
        with patch("sys.stdin", io.StringIO("M\n")):
            self.assertEqual(read_move_choice_line(), "M")


if __name__ == "__main__":
    unittest.main()
