"""Tests for stochastic hit resolution and CPU scoring."""

from __future__ import annotations

import random
import unittest

from game import (
    MatchState,
    _cpu_rule_score,
    _softmax_sample_index,
    apply_move,
    cpu_choose_rule,
    format_exchange_summary,
    hit_probability,
    move_landing_probability_label,
    move_needs_hit_roll,
    outcome_label,
)
from moves import BodyPosition, MoveRule, all_move_rules
from render import health_bar
from wrestlers import ROSTER


def _rule_by_id(move_id: str) -> MoveRule:
    return next(r for r in all_move_rules() if r.move.id == move_id)


class _SeqRng:
    """Minimal RNG stub for deterministic float and int rolls."""

    def __init__(self, floats: list[float], ints: list[int] | None = None) -> None:
        self._it = iter(floats)
        self._ints = iter(ints or [])

    def random(self) -> float:
        return next(self._it)

    def randint(self, a: int, b: int) -> int:
        value = next(self._ints)
        return max(a, min(b, value))


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

    def test_shake_groggy_uses_hit_roll(self) -> None:
        sg = _rule_by_id("shake_groggy").move
        self.assertTrue(move_needs_hit_roll(sg))


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

    def test_finisher_lands_more_often_after_match_wear(self) -> None:
        """Finisher-only hit bonus scales with combined damage — not a flat bonus at the bell."""
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.STANDING
        st.position[1] = BodyPosition.STANDING
        st.momentum[0] = 5
        fin = _rule_by_id("razors_edge")
        p_fresh = hit_probability(st, 0, fin)
        w0, w1 = st.wrestlers
        total_max = w0.max_health + w1.max_health
        dmg = int(total_max * 0.34)
        st.health[0] = max(1, w0.max_health - dmg // 2)
        st.health[1] = max(1, w1.max_health - dmg // 2)
        p_worn = hit_probability(st, 0, fin)
        self.assertGreater(p_worn, p_fresh)

    def test_move_landing_probability_label(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        self.assertEqual(move_landing_probability_label(st, 0, _rule_by_id("pin")), "pin")
        self.assertTrue(move_landing_probability_label(st, 0, _rule_by_id("sharp_shooter")).endswith("%"))
        self.assertEqual(move_landing_probability_label(st, 0, _rule_by_id("climb")), "auto")
        self.assertTrue(move_landing_probability_label(st, 0, _rule_by_id("punch")).endswith("%"))


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

    def test_repeated_get_up_misses_build_escape_momentum(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GROUNDED
        gu = _rule_by_id("get_up")

        first_p = hit_probability(st, 0, gu)
        log1, _, _ = apply_move(st, 0, gu, _SeqRng([min(1.0, first_p + 0.2)]))
        second_p = hit_probability(st, 0, gu)
        log2, _, _ = apply_move(st, 0, gu, _SeqRng([min(1.0, second_p + 0.1)]))

        self.assertIn("vulnerable to a cover", log1)
        self.assertIn("Escape momentum builds", log2)
        self.assertEqual(st.get_up_fail_streak[0], 2)
        self.assertEqual(st.momentum[0], 1)
        self.assertGreater(second_p, first_p)

    def test_irish_whip_miss_does_not_send_opponent_running(self) -> None:
        self.state.position[1] = BodyPosition.GRAPPLED
        whip = _rule_by_id("irish_whip")
        p = hit_probability(self.state, 0, whip)
        rng = _SeqRng([min(1.0, p + 0.2), 0.0])
        apply_move(self.state, 0, whip, rng)
        self.assertEqual(self.state.position[1], BodyPosition.GRAPPLED)

    def test_irish_whip_hit_puts_opponent_running_ropes(self) -> None:
        self.state.position[1] = BodyPosition.GRAPPLED
        whip = _rule_by_id("irish_whip")
        p = hit_probability(self.state, 0, whip)
        rng = _SeqRng([max(0.0, p - 0.2)])
        apply_move(self.state, 0, whip, rng)
        self.assertEqual(self.state.position[1], BodyPosition.RUNNING_ROPES)

    def test_miss_does_not_apply_ground_transition(self) -> None:
        self.state.groggy[1] = True
        self.state.groggy_opponent_actions_left[1] = 2
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
            st.groggy[1] = True
            st.groggy_opponent_actions_left[1] = 2
            rng = random.Random(i)
            log, _, _ = apply_move(st, 0, sup, rng)
            if "reverses" in log or "whiffs" in log:
                low_misses += 1
        for i in range(trials):
            st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
            st.momentum[0] = 5
            st.groggy[1] = True
            st.groggy_opponent_actions_left[1] = 2
            rng = random.Random(i + 10_000)
            log, _, _ = apply_move(st, 0, sup, rng)
            if "reverses" in log or "whiffs" in log:
                high_misses += 1
        self.assertGreater(low_misses, high_misses)

    def test_cpu_last_move_id_set_on_cpu_turn(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        punch = _rule_by_id("punch")
        p = hit_probability(st, 1, punch)
        # Hit roll, then bloodied roll (high value = no blood)
        rng = _SeqRng([max(0.0, p - 0.2), 0.5, 0.99])
        apply_move(st, 1, punch, rng)
        self.assertEqual(st.cpu_last_move_id, "punch")

    def test_repeated_grapple_loop_grants_defender_momentum(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.grapple_loop_pressure = 2
        collar = _rule_by_id("collar_elbow")
        p = hit_probability(st, 0, collar)

        log, _, _ = apply_move(st, 0, collar, _SeqRng([max(0.0, p - 0.2)]))

        self.assertEqual(st.position[1], BodyPosition.GRAPPLED)
        self.assertEqual(st.momentum[0], 0)
        self.assertEqual(st.momentum[1], 1)
        self.assertIn("repeated tie-up stalls out", log)

    def test_grapple_payoff_resets_loop_pressure(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GRAPPLED
        st.grapple_loop_pressure = 3
        arm_drag = _rule_by_id("arm_drag")
        p = hit_probability(st, 0, arm_drag)

        apply_move(st, 0, arm_drag, _SeqRng([max(0.0, p - 0.2)]))

        self.assertEqual(st.grapple_loop_pressure, 0)

    def test_grapple_counter_keeps_and_taxes_loop_pressure(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GRAPPLED
        st.grapple_loop_pressure = 2
        st.momentum = [2, 2]
        counter = _rule_by_id("grapple_counter")
        p = hit_probability(st, 0, counter)

        log, _, _ = apply_move(st, 0, counter, _SeqRng([max(0.0, p - 0.2), 0.99]))

        self.assertEqual(st.grapple_loop_pressure, 3)
        self.assertEqual(st.momentum[0], 1)  # taxed -1, no momentum_gain
        self.assertEqual(st.momentum[1], 3)  # defender gains escape momentum
        self.assertIn("counter is getting predictable", log)

    def test_non_grapple_move_soft_decays_loop_pressure(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.grapple_loop_pressure = 3
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)

        apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))

        self.assertEqual(st.grapple_loop_pressure, 2)

    def test_repeated_climb_taxes_setup_loop(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.setup_loop_pressure = 2
        st.momentum = [1, 1]
        climb = _rule_by_id("climb")

        log, _, _ = apply_move(st, 0, climb, None)

        self.assertEqual(st.position[0], BodyPosition.TOP_ROPE)
        self.assertEqual(st.setup_loop_pressure, 3)
        self.assertEqual(st.momentum[0], 1)  # climb momentum_gain cancelled
        self.assertEqual(st.momentum[1], 2)
        self.assertIn("climb looks telegraphed", log)

    def test_top_rope_payoff_preserves_setup_loop_debt(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.TOP_ROPE
        st.position[1] = BodyPosition.GROUNDED
        st.setup_loop_pressure = 3
        splash = _rule_by_id("top_splash")
        p = hit_probability(st, 0, splash)

        apply_move(st, 0, splash, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))

        # Payoff should not wipe setup debt — climb→dive→climb stays taxed.
        self.assertEqual(st.setup_loop_pressure, 3)

    def test_get_up_does_not_erase_setup_loop_debt(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GROUNDED
        st.setup_loop_pressure = 2
        get_up = _rule_by_id("get_up")
        p = hit_probability(st, 0, get_up)

        apply_move(st, 0, get_up, _SeqRng([max(0.0, p - 0.2)]))

        self.assertEqual(st.setup_loop_pressure, 2)
        self.assertEqual(st.position[0], BodyPosition.STANDING)

    def test_standing_offense_decays_setup_loop_debt(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.setup_loop_pressure = 2
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)

        apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))

        self.assertEqual(st.setup_loop_pressure, 1)


class TestKnockoutAndKnockdown(unittest.TestCase):
    def test_damage_can_reach_zero_and_wins_by_knockout(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.health[1] = 1
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)

        log, winner, seq = apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99]))

        self.assertEqual(st.health[1], 0)
        self.assertEqual(winner, 0)
        self.assertIsNone(seq)
        self.assertIn("KNOCKOUT", log)
        self.assertEqual(st.position[1], BodyPosition.GROUNDED)
        self.assertEqual(outcome_label(log), "knockout")

    def test_worn_down_standing_target_is_knocked_down(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        target_max = st.wrestlers[1].max_health
        st.health[1] = int(target_max * 0.2)
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)

        log, winner, _ = apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))

        self.assertIsNone(winner)
        self.assertGreater(st.health[1], 0)
        self.assertEqual(st.position[1], BodyPosition.GROUNDED)
        self.assertTrue(st.pending_groggy[1])
        self.assertIn("collapses to the canvas", log)

    def test_knockdown_makes_pin_legal(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.health[1] = int(st.wrestlers[1].max_health * 0.2)
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)

        apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))

        legal_ids = {rule.move.id for _, rule in st.valid_rules(0)}
        self.assertIn("pin", legal_ids)

    def test_healthy_target_is_not_knocked_down(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)

        apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))

        self.assertEqual(st.position[1], BodyPosition.STANDING)

    def test_reversal_chip_damage_cannot_knock_out(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.health[1] = 1
        suplex = _rule_by_id("suplex")
        p = hit_probability(st, 0, suplex)

        log, winner, _ = apply_move(st, 0, suplex, _SeqRng([min(1.0, p + 0.2), 0.0]))

        self.assertEqual(st.health[1], 1)
        self.assertIsNone(winner)
        self.assertNotIn("KNOCKOUT", log)


class TestPinUnchanged(unittest.TestCase):
    def test_pin_uses_resolve_pin_not_hit_roll(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GROUNDED
        st.position[1] = BodyPosition.STANDING
        pin = _rule_by_id("pin")
        rng = random.Random(12345)
        log, winner, pin_seq = apply_move(st, 1, pin, rng)
        self.assertIsNotNone(pin_seq)
        self.assertIn("Referee:", log)
        self.assertTrue(winner is None or winner == 1)


class TestSubmission(unittest.TestCase):
    def test_submission_uses_timed_sequence_and_can_end_match(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GROUNDED
        st.health[1] = 1
        st.momentum[0] = 5
        p = hit_probability(st, 0, _rule_by_id("sharp_shooter"))
        rng = _SeqRng([max(0.0, p - 0.2)], ints=[10, 1])
        log, winner, seq = apply_move(st, 0, _rule_by_id("sharp_shooter"), rng)
        self.assertIsNotNone(seq)
        self.assertEqual(seq.heading, "Submission attempt…")
        self.assertEqual(winner, 0)
        self.assertIn("SUBMISSION", log)

    def test_submission_can_miss_before_sequence(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GROUNDED
        st.momentum[0] = 5
        p = hit_probability(st, 0, _rule_by_id("sharp_shooter"))
        log, winner, seq = apply_move(
            st, 0, _rule_by_id("sharp_shooter"), _SeqRng([min(1.0, p + 0.2), 0.0])
        )
        self.assertIsNone(seq)
        self.assertIsNone(winner)
        self.assertTrue(
            "reverses" in log or "whiffs" in log or "turns the tables" in log
        )


class TestExchangeSummary(unittest.TestCase):
    def test_outcome_label_hit_miss_pin(self) -> None:
        self.assertEqual(outcome_label("  Ace deals 10 damage"), "hit")
        self.assertEqual(outcome_label("  Foo whiffs"), "miss")
        self.assertEqual(outcome_label("  *** PINFALL — Ace wins ***"), "pinfall")

    def test_format_exchange_summary_line(self) -> None:
        s = format_exchange_summary(
            "Punch",
            "  deals 5",
            "Suplex",
            "  reverses",
        )
        self.assertIn("You: Punch", s)
        self.assertIn("CPU: Suplex", s)
        self.assertIn("hit", s)
        self.assertIn("miss", s)


class TestSoftmaxSample(unittest.TestCase):
    def test_softmax_temperature_zero_is_argmax(self) -> None:
        scores = [1.0, 5.0, 3.0]
        self.assertEqual(_softmax_sample_index(scores, 0.0), 1)

    def test_softmax_single_option(self) -> None:
        self.assertEqual(_softmax_sample_index([42.0], 12.0), 0)


class TestCpuExpectedValue(unittest.TestCase):
    def test_cpu_choose_rule_returns_valid_rule(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        r = cpu_choose_rule(st, 1)
        self.assertIsInstance(r, MoveRule)

    def test_cpu_discourages_healthy_recover(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        recover_score = _cpu_rule_score(st, 1, _rule_by_id("recover"))
        punch_score = _cpu_rule_score(st, 1, _rule_by_id("punch"))

        self.assertLess(recover_score, punch_score)

    def test_cpu_prefers_grapple_counter_over_stale_break(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GRAPPLED
        st.grapple_loop_pressure = 1

        break_score = _cpu_rule_score(st, 1, _rule_by_id("break_grapple"))
        counter_score = _cpu_rule_score(st, 1, _rule_by_id("grapple_counter"))

        self.assertGreater(counter_score, break_score)

    def test_cpu_prefers_break_when_grapple_loop_is_stale(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GRAPPLED
        st.grapple_loop_pressure = 3

        break_score = _cpu_rule_score(st, 1, _rule_by_id("break_grapple"))
        counter_score = _cpu_rule_score(st, 1, _rule_by_id("grapple_counter"))

        self.assertGreaterEqual(break_score, counter_score)

    def test_cpu_discourages_stale_climb(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.setup_loop_pressure = 3
        climb_score = _cpu_rule_score(st, 1, _rule_by_id("climb"))
        punch_score = _cpu_rule_score(st, 1, _rule_by_id("punch"))

        self.assertLess(climb_score, punch_score)


class TestGroggy(unittest.TestCase):
    def test_punch_hit_applies_groggy_to_target(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)
        # hit roll, bloodied roll, groggy proc roll (0.0 → success)
        rng = _SeqRng([max(0.0, p - 0.2), 0.5, 0.0])
        log, _, _ = apply_move(st, 0, punch, rng)
        self.assertTrue(st.groggy[1])
        self.assertEqual(st.groggy_opponent_actions_left[1], 2)
        self.assertIn("GROGGY", log)

    def test_punch_hit_may_not_proc_groggy(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)
        rng = _SeqRng([max(0.0, p - 0.2), 0.5, 0.99])
        apply_move(st, 0, punch, rng)
        self.assertFalse(st.groggy[1])

    def test_offensive_miss_chip_clears_groggy(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.groggy[1] = True
        st.groggy_opponent_actions_left[1] = 2
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)
        rng = _SeqRng([min(1.0, p + 0.2), 0.0])
        apply_move(st, 0, punch, rng)
        self.assertFalse(st.groggy[1])

    def test_groggy_timer_counts_opponent_actions_only(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.groggy[1] = True
        st.groggy_opponent_actions_left[1] = 2
        recover = _rule_by_id("recover")
        apply_move(st, 0, recover, random.Random(0))
        self.assertTrue(st.groggy[1])
        self.assertEqual(st.groggy_opponent_actions_left[1], 1)
        apply_move(st, 0, recover, random.Random(1))
        self.assertFalse(st.groggy[1])

    def test_shake_success_clears_groggy(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.groggy[0] = True
        st.groggy_opponent_actions_left[0] = 2
        shake = _rule_by_id("shake_groggy")
        p = hit_probability(st, 0, shake)
        rng = _SeqRng([max(0.0, p - 0.2)])
        apply_move(st, 0, shake, rng)
        self.assertFalse(st.groggy[0])

    def test_desperation_success_clears_actor_groggy(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.groggy[0] = True
        st.groggy_opponent_actions_left[0] = 2
        des = _rule_by_id("desperation_strike")
        p = hit_probability(st, 0, des)
        rng = _SeqRng([max(0.0, p - 0.2)])
        apply_move(st, 0, des, rng)
        self.assertFalse(st.groggy[0])

    def test_body_slam_pending_groggy_on_stand(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.groggy[1] = True
        st.groggy_opponent_actions_left[1] = 2
        slam = _rule_by_id("body_slam")
        p = hit_probability(st, 0, slam)
        # hit roll, groggy-on-stand proc (0.0 → pending)
        rng = _SeqRng([max(0.0, p - 0.2), 0.0])
        apply_move(st, 0, slam, rng)
        self.assertTrue(st.pending_groggy[1])
        self.assertEqual(st.position[1], BodyPosition.GROUNDED)
        gu = _rule_by_id("get_up")
        p2 = hit_probability(st, 1, gu)
        rng2 = _SeqRng([max(0.0, p2 - 0.2)])
        apply_move(st, 1, gu, rng2)
        self.assertTrue(st.groggy[1])
        self.assertFalse(st.pending_groggy[1])

    def test_groggy_actor_valid_moves_are_shake_and_desperation(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.groggy[0] = True
        ids = {r.move.id for _, r in st.valid_rules(0)}
        self.assertEqual(ids, {"shake_groggy", "desperation_strike"})

    def test_groggy_grappled_actor_can_escape_or_counter(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GRAPPLED
        st.groggy[1] = True
        st.groggy_opponent_actions_left[1] = 2
        ids = {r.move.id for _, r in st.valid_rules(1)}
        self.assertEqual(ids, {"break_grapple", "grapple_counter"})

    def test_body_slam_and_suplex_require_groggy_target(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        ids = {r.move.id for _, r in st.valid_rules(0)}
        self.assertNotIn("body_slam", ids)
        self.assertNotIn("suplex", ids)
        st.groggy[1] = True
        st.groggy_opponent_actions_left[1] = 2
        ids_g = {r.move.id for _, r in st.valid_rules(0)}
        self.assertIn("body_slam", ids_g)
        self.assertIn("suplex", ids_g)

    def test_standing_finisher_requires_groggy_target(self) -> None:
        st = MatchState(wrestlers=(ROSTER["stone_cold"], ROSTER["cm_punk"]))
        st.momentum[0] = 5
        ids = {r.move.id for _, r in st.valid_rules(0)}
        self.assertNotIn("stunner", ids)
        st.groggy[1] = True
        st.groggy_opponent_actions_left[1] = 2
        ids_g = {r.move.id for _, r in st.valid_rules(0)}
        self.assertIn("stunner", ids_g)


class TestBloodiedEasterEgg(unittest.TestCase):
    def test_match_state_initializes_bloodied(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        self.assertEqual(st.bloodied, [False, False])

    def test_head_hit_can_trigger_bloodied_log(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)
        rng = _SeqRng([max(0.0, p - 0.2), 0.001, 0.99])
        log, _, _ = apply_move(st, 0, punch, rng)
        self.assertTrue(st.bloodied[1])
        self.assertIn("busted open", log)

    def test_non_head_move_does_not_consume_blood_roll(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.groggy[1] = True
        st.groggy_opponent_actions_left[1] = 2
        sup = _rule_by_id("suplex")
        p = hit_probability(st, 0, sup)
        rng = _SeqRng([max(0.0, p - 0.2), 0.99])
        apply_move(st, 0, sup, rng)
        self.assertFalse(st.bloodied[1])

    def test_health_bar_red_when_bloodied_and_color(self) -> None:
        s = health_bar(40, 100, bloodied=True, use_color=True)
        self.assertTrue(s.startswith("\033[91m"))
        self.assertIn("]", s)


if __name__ == "__main__":
    unittest.main()
