"""Tests for stochastic hit resolution and CPU scoring."""

from __future__ import annotations

import random
import unittest

from game import (
    MatchState,
    apply_move,
    cpu_choose_rule,
    format_round_summary,
    hit_probability,
    move_needs_hit_roll,
    outcome_label,
)
from moves import BodyPosition, MoveRule, all_move_rules
from render import health_bar
from wrestlers import ROSTER


def _rule_by_id(move_id: str) -> MoveRule:
    return next(r for r in all_move_rules() if r.move.id == move_id)


class _SeqRng:
    """Minimal RNG stub: only ``random()`` is used by hit / miss paths."""

    def __init__(self, floats: list[float]) -> None:
        self._it = iter(floats)

    def random(self) -> float:
        return next(self._it)


class TestHitRollMetadata(unittest.TestCase):
    def test_pin_skips_offensive_hit_roll(self) -> None:
        pin = _rule_by_id("pin").move
        self.assertFalse(move_needs_hit_roll(pin))

    def test_suplex_needs_hit_roll(self) -> None:
        sup = _rule_by_id("suplex").move
        self.assertTrue(move_needs_hit_roll(sup))

    def test_climb_skips_hit_roll(self) -> None:
        climb = _rule_by_id("climb").move
        self.assertFalse(move_needs_hit_roll(climb))

    def test_get_up_uses_hit_roll(self) -> None:
        gu = _rule_by_id("get_up").move
        self.assertTrue(move_needs_hit_roll(gu))


class TestHitProbability(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))

    def test_hit_probability_in_bounds(self) -> None:
        sup = _rule_by_id("suplex")
        p = hit_probability(self.state, 0, sup)
        self.assertGreaterEqual(p, 0.12)
        self.assertLessEqual(p, 0.94)

    def test_higher_momentum_increases_hit_probability(self) -> None:
        sup = _rule_by_id("suplex")
        low = hit_probability(self.state, 0, sup)
        self.state.momentum[0] = 5
        high = hit_probability(self.state, 0, sup)
        self.assertGreater(high, low)

    def test_higher_difficulty_lowers_hit_probability(self) -> None:
        sup = _rule_by_id("suplex")
        punch = _rule_by_id("punch")
        self.assertLess(hit_probability(self.state, 0, sup), hit_probability(self.state, 0, punch))

    def test_get_up_harder_when_beaten_and_after_finisher(self) -> None:
        gu = _rule_by_id("get_up")
        healthy = hit_probability(self.state, 0, gu)
        self.state.health[0] = max(1, self.state.wrestlers[0].max_health // 5)
        beaten = hit_probability(self.state, 0, gu)
        self.assertLess(beaten, healthy)
        self.state.finisher_shock[0] = 2
        shocked = hit_probability(self.state, 0, gu)
        self.assertLess(shocked, beaten)


class TestApplyMoveStochastic(unittest.TestCase):
    def setUp(self) -> None:
        self.state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))

    def test_get_up_miss_stays_grounded(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GROUNDED
        gu = _rule_by_id("get_up")
        p = hit_probability(st, 0, gu)
        rng = _SeqRng([min(1.0, p + 0.2)])
        apply_move(st, 0, gu, rng)
        self.assertEqual(st.position[0], BodyPosition.GROUNDED)

    def test_irish_whip_miss_does_not_send_opponent_running(self) -> None:
        whip = _rule_by_id("irish_whip")
        p = hit_probability(self.state, 0, whip)
        rng = _SeqRng([min(1.0, p + 0.2), 0.0])
        apply_move(self.state, 0, whip, rng)
        self.assertEqual(self.state.position[1], BodyPosition.STANDING)

    def test_irish_whip_hit_puts_opponent_running_ropes(self) -> None:
        whip = _rule_by_id("irish_whip")
        p = hit_probability(self.state, 0, whip)
        rng = _SeqRng([max(0.0, p - 0.2)])
        apply_move(self.state, 0, whip, rng)
        self.assertEqual(self.state.position[1], BodyPosition.RUNNING_ROPES)
        self.assertFalse(self.state.rebound[0])

    def test_miss_does_not_apply_ground_transition(self) -> None:
        sup = _rule_by_id("suplex")
        p = hit_probability(self.state, 0, sup)
        rng = _SeqRng([min(1.0, p + 0.1), 0.0])
        apply_move(self.state, 0, sup, rng)
        self.assertEqual(self.state.position[1], BodyPosition.STANDING)

    def test_low_momentum_misses_more_often_than_high(self) -> None:
        sup = _rule_by_id("suplex")
        low_misses = 0
        high_misses = 0
        trials = 400
        for i in range(trials):
            st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
            st.momentum[0] = 0
            rng = random.Random(i)
            log, _ = apply_move(st, 0, sup, rng)
            if "reverses" in log or "whiffs" in log:
                low_misses += 1
        for i in range(trials):
            st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
            st.momentum[0] = 5
            rng = random.Random(i + 10_000)
            log, _ = apply_move(st, 0, sup, rng)
            if "reverses" in log or "whiffs" in log:
                high_misses += 1
        self.assertGreater(low_misses, high_misses)

    def test_cpu_last_move_id_set_on_cpu_turn(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        punch = _rule_by_id("punch")
        p = hit_probability(st, 1, punch)
        # Hit roll, then bloodied roll (high value = no blood)
        rng = _SeqRng([max(0.0, p - 0.2), 0.5])
        apply_move(st, 1, punch, rng)
        self.assertEqual(st.cpu_last_move_id, "punch")


class TestPinUnchanged(unittest.TestCase):
    def test_pin_uses_resolve_pin_not_hit_roll(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GROUNDED
        st.position[1] = BodyPosition.STANDING
        pin = _rule_by_id("pin")
        rng = random.Random(12345)
        log, winner = apply_move(st, 1, pin, rng)
        self.assertIn("Referee:", log)
        self.assertTrue(winner is None or winner == 1)


class TestRoundSummary(unittest.TestCase):
    def test_outcome_label_hit_miss_pin(self) -> None:
        self.assertEqual(outcome_label("  Ace deals 10 damage"), "hit")
        self.assertEqual(outcome_label("  Foo whiffs"), "miss")
        self.assertEqual(outcome_label("  *** PINFALL — Ace wins ***"), "pinfall")

    def test_format_round_summary_line(self) -> None:
        s = format_round_summary(
            "Punch",
            "  deals 5",
            "Suplex",
            "  reverses",
        )
        self.assertIn("You: Punch", s)
        self.assertIn("CPU: Suplex", s)
        self.assertIn("hit", s)
        self.assertIn("miss", s)


class TestCpuExpectedValue(unittest.TestCase):
    def test_cpu_choose_rule_returns_valid_rule(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        r = cpu_choose_rule(st, 1)
        self.assertIsInstance(r, MoveRule)


class TestBloodiedEasterEgg(unittest.TestCase):
    def test_match_state_initializes_bloodied(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        self.assertEqual(st.bloodied, [False, False])

    def test_head_hit_can_trigger_bloodied_log(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)
        rng = _SeqRng([max(0.0, p - 0.2), 0.001])
        log, _ = apply_move(st, 0, punch, rng)
        self.assertTrue(st.bloodied[1])
        self.assertIn("busted open", log)

    def test_non_head_move_does_not_consume_blood_roll(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        sup = _rule_by_id("suplex")
        p = hit_probability(st, 0, sup)
        rng = _SeqRng([max(0.0, p - 0.2)])
        apply_move(st, 0, sup, rng)
        self.assertFalse(st.bloodied[1])

    def test_health_bar_red_when_bloodied_and_color(self) -> None:
        s = health_bar(40, 100, bloodied=True, use_color=True)
        self.assertTrue(s.startswith("\033[91m"))
        self.assertIn("]", s)


if __name__ == "__main__":
    unittest.main()
