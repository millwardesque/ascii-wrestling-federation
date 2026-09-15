"""Tests for fixed-layout renderer helpers."""

from __future__ import annotations

import unittest

from game import MatchState
from render import tempo_label, turn_queue_strip
from render_fixed import (
    FixedLayoutRenderer,
    _Palette,
    _curate_move_choices,
    _momentum_chart_lines,
    _move_choice_details,
    _status_display,
)
from scheduler import TurnQueue
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


class TestFinisherCoverCuration(unittest.TestCase):
    def test_finisher_echo_boosts_pin_over_follow_up_offense(self) -> None:
        from moves import BodyPosition

        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        state.position[1] = BodyPosition.GROUNDED
        state.health[1] = int(state.wrestlers[1].max_health * 0.6)
        state.pin_bonus_next_cover[0] = 12

        pin = next(
            ch
            for _, rule in state.valid_rules(0)
            if rule.move.id == "pin"
            for ch in [_move_choice_details(state, 0, 0, rule)]
        )
        stomp = next(
            ch
            for idx, rule in state.valid_rules(0)
            if rule.move.id == "leg_drop"
            for ch in [_move_choice_details(state, 0, idx, rule)]
        )

        self.assertIn("FINISHER", pin.note)
        self.assertGreater(pin.score, stomp.score)

    def test_finisher_echo_pin_is_top_finish_choice(self) -> None:
        from moves import BodyPosition

        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        state.position[1] = BodyPosition.GROUNDED
        state.health[1] = int(state.wrestlers[1].max_health * 0.6)
        state.pin_bonus_next_cover[0] = 12

        choices = _curate_move_choices(state, 0, state.valid_rules(0))
        finish_ids = [ch.rule.move.id for ch in choices if ch.intent == "Finish"]

        self.assertEqual(finish_ids[0], "pin")


class TestMomentumChart(unittest.TestCase):
    def test_chart_hidden_by_default(self) -> None:
        renderer = FixedLayoutRenderer(
            input_fn=lambda _: "",
            use_color=False,
            animate_move_log=False,
        )
        self.assertFalse(renderer._show_momentum_chart)

    def test_toggle_momentum_chart(self) -> None:
        renderer = FixedLayoutRenderer(
            input_fn=lambda _: "",
            use_color=False,
            animate_move_log=False,
        )
        renderer._toggle_momentum_chart()
        self.assertTrue(renderer._show_momentum_chart)
        renderer._toggle_momentum_chart()
        self.assertFalse(renderer._show_momentum_chart)

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


class TestStatusDisplay(unittest.TestCase):
    def test_status_shows_on_a_roll_only_when_surge_is_live(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        self.assertEqual(_status_display(state, 0), "Standing")
        state.surge[0] = 2
        self.assertEqual(_status_display(state, 0), "On a roll — Standing")
        state.groggy[0] = True
        self.assertEqual(_status_display(state, 0), "On a roll — Groggy — standing")
        state.surge[0] = 0
        self.assertEqual(_status_display(state, 0), "Groggy — standing")


class TestTempoAnnotatedMenu(unittest.TestCase):
    def _choices(self, state: MatchState, queue: TurnQueue | None):
        return _curate_move_choices(state, 0, state.valid_rules(0), queue=queue)

    def test_every_option_carries_its_recovery_cost(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        for choice in self._choices(state, TurnQueue()):
            self.assertGreater(choice.tempo_cost, 0.0)

    def test_expensive_options_report_conceding_more(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        queue = TurnQueue(next_act_at=[0.0, 1.0])
        queue.pop_next([10.0, 10.0])
        choices = self._choices(state, queue)

        by_cost = sorted(choices, key=lambda ch: ch.tempo_cost)
        self.assertLessEqual(by_cost[0].conceded, by_cost[-1].conceded)

    def test_curation_works_without_a_queue(self) -> None:
        """Static curation checks and unit tests must not have to fabricate a queue."""
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        choices = self._choices(state, None)
        self.assertTrue(choices)
        self.assertTrue(all(ch.conceded == 0 for ch in choices))
        self.assertTrue(all(ch.tempo_cost > 0 for ch in choices))

    def test_pin_is_still_offered_when_it_is_legal(self) -> None:
        """Tempo ranking must never bury the finish."""
        from moves import BodyPosition

        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        state.position[1] = BodyPosition.GROUNDED
        legal = {rule.move.id for _, rule in state.valid_rules(0)}
        self.assertIn("pin", legal)
        self.assertIn("pin", {ch.rule.move.id for ch in self._choices(state, TurnQueue())})


class TestTurnQueueStrip(unittest.TestCase):
    def test_strip_reads_as_an_order_not_an_alternation(self) -> None:
        line = turn_queue_strip([0, 0, 1, 0], ("YOU", "Hall"))
        self.assertEqual(line, "YOU  ·  YOU  ·  Hall  ·  YOU")

    def test_empty_queue_does_not_crash_the_strip(self) -> None:
        self.assertIn("empty", turn_queue_strip([], ("YOU", "Hall")))

    def test_tempo_label_distinguishes_the_three_cases(self) -> None:
        self.assertIn("go again", tempo_label(0))
        self.assertIn("once", tempo_label(1))
        self.assertIn("2", tempo_label(2))


class TestTurnQueueRenderer(unittest.TestCase):
    def _renderer(self) -> FixedLayoutRenderer:
        renderer = FixedLayoutRenderer(
            input_fn=lambda _: "",
            use_color=False,
            animate_move_log=False,
        )
        renderer._redraw_match = lambda bottom_extra=None: None  # type: ignore[method-assign]
        return renderer

    def test_action_count_advances_per_action_not_per_round(self) -> None:
        renderer = self._renderer()
        renderer.match_start_banner(match_seed=1)
        self.assertEqual(renderer.action_count, 0)
        renderer.begin_action(is_player_turn=True)
        renderer.begin_action(is_player_turn=True)
        renderer.begin_action(is_player_turn=False)
        self.assertEqual(renderer.action_count, 3)

    def test_heading_follows_the_queue_rather_than_whoever_just_went(self) -> None:
        """After the player acts they may be up again, so the prompt must stay open."""
        renderer = self._renderer()
        renderer.match_start_banner(match_seed=1)
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))

        renderer.show_status(state, ("YOU", "CPU"), up_next=[0, 1])
        renderer.show_move_log(
            "  something happened",
            player_nickname="Hart",
            cpu_nickname="Punk",
            actor_is_player=True,
            move_name="Straight right",
        )
        self.assertEqual(renderer._instruction_heading, "Choose your move!")

        renderer.show_status(state, ("YOU", "CPU"), up_next=[1, 0])
        renderer.show_move_log(
            "  something else happened",
            player_nickname="Hart",
            cpu_nickname="Punk",
            actor_is_player=True,
            move_name="Straight right",
        )
        self.assertEqual(renderer._instruction_heading, "> OPPONENT ACTS...")


if __name__ == "__main__":
    unittest.main()
