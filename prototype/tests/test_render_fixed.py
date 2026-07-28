"""Tests for fixed-layout renderer helpers."""

from __future__ import annotations

import unittest

from game import MatchState
from render_fixed import FixedLayoutRenderer, _Palette, _momentum_chart_lines
from wrestlers import ROSTER


class TestMomentumChart(unittest.TestCase):
    def test_chart_draws_player_above_and_cpu_below_axis(self) -> None:
        palette = _Palette(enabled=False)
        lines = _momentum_chart_lines([(1, 2), (3, 0)], 40, palette)

        self.assertIn("  3 │ █", lines)
        self.assertIn("  0 ┼──", lines)
        self.assertIn(" -2 │█ ", lines)

    def test_record_momentum_samples_and_match_start_resets(self) -> None:
        renderer = FixedLayoutRenderer(
            input_fn=lambda _: "",
            use_color=False,
            animate_move_log=False,
        )
        renderer._redraw_match = lambda bottom_extra=None: None  # type: ignore[method-assign]
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        state.momentum = [2, 4]

        renderer.record_momentum(state)
        self.assertEqual(renderer._momentum_history, [(2, 4)])

        renderer.match_start_banner(match_seed=123)
        self.assertEqual(renderer._momentum_history, [])


if __name__ == "__main__":
    unittest.main()
