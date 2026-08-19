"""Tests for fixed-layout renderer helpers."""

from __future__ import annotations

import unittest

from game import MatchState
from render_fixed import (
    FixedLayoutRenderer,
    _Palette,
    _curate_move_choices,
    _momentum_chart_lines,
)
from wrestlers import ROSTER


class TestStaleMoveCuration(unittest.TestCase):
    def _menu(self, state: MatchState) -> list[str]:
        choices = _curate_move_choices(state, 0, state.valid_rules(0))
        return [ch.rule.move.id for ch in choices]

    def test_fresh_tie_up_is_offered_first(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))

        self.assertEqual(self._menu(state)[0], "collar_elbow")

    def test_stale_tie_up_loses_its_top_slot(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        state.grapple_loop_pressure = [3, 0]

        menu = self._menu(state)

        self.assertTrue(menu)
        self.assertNotEqual(menu[0], "collar_elbow")

    def test_stale_climb_loses_its_slot(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        state.setup_loop_pressure = [3, 0]

        menu = self._menu(state)
        fresh = _curate_move_choices(
            MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"])),
            0,
            MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"])).valid_rules(0),
        )
        fresh_ids = [ch.rule.move.id for ch in fresh]

        self.assertIn("climb", fresh_ids)
        if "climb" in menu:
            self.assertGreater(menu.index("climb"), fresh_ids.index("climb"))

    def test_stale_move_still_listed_when_nothing_else_is_legal(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        state.grapple_loop_pressure = [3, 0]
        collar = next(
            (i, r) for i, r in state.valid_rules(0) if r.move.id == "collar_elbow"
        )

        choices = _curate_move_choices(state, 0, [collar])

        self.assertEqual([ch.rule.move.id for ch in choices], ["collar_elbow"])

    def test_stale_counter_loses_slot_to_break(self) -> None:
        from moves import BodyPosition

        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        state.position[0] = BodyPosition.GRAPPLED
        state.counter_loop_pressure = [3, 0]

        menu = self._menu(state)

        self.assertEqual(menu[0], "break_grapple")
        self.assertIn("grapple_counter", menu)


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


class TestCommentaryHeader(unittest.TestCase):
    def _renderer(self) -> FixedLayoutRenderer:
        return FixedLayoutRenderer(
            input_fn=lambda _: "",
            use_color=False,
            animate_move_log=False,
        )

    def test_booth_credit_survives_later_player_turns(self) -> None:
        from commentators import CommentatorPair

        renderer = self._renderer()
        renderer._redraw_match = lambda bottom_extra=None: None  # type: ignore[method-assign]
        renderer.match_start_banner(
            match_seed=1, commentary_team=CommentatorPair("gorilla", "ventura")
        )
        self.assertIn("On the call:", renderer._header_extra)
        renderer.round_header(is_player_turn=True)
        renderer.round_header(is_player_turn=False)
        renderer.round_header(is_player_turn=True)
        self.assertIn("On the call:", renderer._header_extra)
        self.assertIn("Gorilla Monsoon", renderer._header_extra)

    def test_empty_log_shows_booth_intro(self) -> None:
        from commentators import CommentatorPair
        from render_fixed import _Palette

        renderer = self._renderer()
        renderer.match_start_banner(
            match_seed=1, commentary_team=CommentatorPair("ross", "lawler")
        )
        lines = renderer._action_log_lines(40, _Palette(enabled=False), False)
        joined = "\n".join(lines)
        self.assertIn("JR:", joined)
        self.assertIn("KING:", joined)
        self.assertNotIn("no actions yet", joined)


if __name__ == "__main__":
    unittest.main()
