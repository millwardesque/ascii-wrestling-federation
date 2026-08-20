"""Tests for stochastic hit resolution and CPU scoring."""

from __future__ import annotations

import random
import unittest

from game import (
    MatchState,
    _cpu_rule_score,
    _softmax_sample_index,
    apply_move,
    consume_groggy_skip_turn,
    cpu_choose_rule,
    format_exchange_summary,
    hit_probability,
    move_is_stale,
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

    def test_missed_flying_splash_dumps_attacker_to_the_mat(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.TOP_ROPE
        st.position[1] = BodyPosition.GROUNDED
        splash = _rule_by_id("top_splash")
        p = hit_probability(st, 0, splash)
        result = apply_move(st, 0, splash, _SeqRng([min(1.0, p + 0.2), 0.99]))

        self.assertEqual(st.position[0], BodyPosition.GROUNDED)
        self.assertEqual(st.position[1], BodyPosition.GROUNDED)
        self.assertIn("crashes off the top rope", result.log)
        self.assertTrue(
            any(
                event.kind == "position_change" and event.position == "GROUNDED"
                for event in result.events
            )
        )

    def test_missed_diving_crossbody_dumps_attacker_defender_stays_up(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.TOP_ROPE
        st.position[1] = BodyPosition.STANDING
        crossbody = _rule_by_id("top_crossbody")
        p = hit_probability(st, 0, crossbody)
        result = apply_move(st, 0, crossbody, _SeqRng([min(1.0, p + 0.2), 0.99]))

        self.assertEqual(st.position[0], BodyPosition.GROUNDED)
        self.assertEqual(st.position[1], BodyPosition.STANDING)
        self.assertIsNone(result.pin_sequence)

    def test_successful_diving_crossbody_goes_for_the_cover(self) -> None:
        for move_id, target_pos in (
            ("top_crossbody", BodyPosition.STANDING),
            ("top_crossbody_running", BodyPosition.RUNNING_ROPES),
        ):
            with self.subTest(move_id=move_id):
                st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
                st.position[0] = BodyPosition.TOP_ROPE
                st.position[1] = target_pos
                crossbody = _rule_by_id(move_id)
                p = hit_probability(st, 0, crossbody)
                result = apply_move(
                    st,
                    0,
                    crossbody,
                    _SeqRng([max(0.0, p - 0.2)], [10, 1, 10, 1, 10, 1]),
                )

                self.assertIsNotNone(result.pin_sequence)
                self.assertIn("Referee:", result.log)
                self.assertEqual(st.position[1], BodyPosition.GROUNDED)
                self.assertEqual(st.pins_attempted, 1)

    def test_missed_superplex_dumps_attacker_defender_keeps_the_buckle(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.TOP_ROPE
        st.position[1] = BodyPosition.TOP_ROPE
        superplex = _rule_by_id("top_rope_superplex")
        p = hit_probability(st, 0, superplex)
        apply_move(st, 0, superplex, _SeqRng([min(1.0, p + 0.2), 0.99]))

        self.assertEqual(st.position[0], BodyPosition.GROUNDED)
        self.assertEqual(st.position[1], BodyPosition.TOP_ROPE)

    def test_missed_top_rope_brawl_shot_stays_on_the_buckle(self) -> None:
        """A punch traded on the top rope is not a dive — miss doesn't dump anyone."""
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.TOP_ROPE
        st.position[1] = BodyPosition.TOP_ROPE
        shot = _rule_by_id("top_rope_punch")
        p = hit_probability(st, 0, shot)
        apply_move(st, 0, shot, _SeqRng([min(1.0, p + 0.2), 0.99]))

        self.assertEqual(st.position[0], BodyPosition.TOP_ROPE)
        self.assertEqual(st.position[1], BodyPosition.TOP_ROPE)

    def test_every_whiffed_top_rope_dive_dumps_the_attacker(self) -> None:
        for rule in all_move_rules():
            m = rule.move
            if not m.actor_top or m.skip_hit_roll:
                continue
            if m.actor_after is None or m.actor_after == BodyPosition.TOP_ROPE:
                continue
            actor = (
                ROSTER["macho_man"]
                if m.id == "flying_elbow_finisher"
                else ROSTER["bret_hart"]
            )
            st = MatchState(wrestlers=(actor, ROSTER["cm_punk"]))
            st.position[0] = BodyPosition.TOP_ROPE
            if m.target_grounded:
                st.position[1] = BodyPosition.GROUNDED
            elif m.target_standing:
                st.position[1] = BodyPosition.STANDING
            elif m.target_running_ropes:
                st.position[1] = BodyPosition.RUNNING_ROPES
            elif m.target_top:
                st.position[1] = BodyPosition.TOP_ROPE
            if m.min_momentum:
                st.momentum[0] = m.min_momentum
            p = hit_probability(st, 0, rule)
            apply_move(st, 0, rule, _SeqRng([min(1.0, p + 0.2), 0.99]))
            self.assertEqual(
                st.position[0],
                BodyPosition.GROUNDED,
                f"{m.id} miss left attacker on {st.position[0]!r}",
            )

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
        st.grapple_loop_pressure = [2, 0]
        collar = _rule_by_id("collar_elbow")
        p = hit_probability(st, 0, collar)

        log, _, _ = apply_move(st, 0, collar, _SeqRng([max(0.0, p - 0.2)]))

        self.assertEqual(st.position[1], BodyPosition.GRAPPLED)
        self.assertEqual(st.momentum[0], 0)
        self.assertEqual(st.momentum[1], 1)
        self.assertIn("repeated tie-up stalls out", log)

    def test_light_grapple_payoff_keeps_loop_pressure(self) -> None:
        """Chip throws are the treadmill — they must not wipe collar debt."""
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GRAPPLED
        st.grapple_loop_pressure = [3, 0]
        arm_drag = _rule_by_id("arm_drag")
        p = hit_probability(st, 0, arm_drag)

        apply_move(st, 0, arm_drag, _SeqRng([max(0.0, p - 0.2)]))

        self.assertEqual(st.grapple_loop_pressure[0], 3)

    def test_real_grapple_exit_clears_loop_pressure(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GRAPPLED
        st.grapple_loop_pressure = [3, 0]
        whip = _rule_by_id("irish_whip")
        p = hit_probability(st, 0, whip)

        apply_move(st, 0, whip, _SeqRng([max(0.0, p - 0.2)]))

        self.assertEqual(st.grapple_loop_pressure[0], 0)

    def test_collar_throw_cycle_accumulates_pressure(self) -> None:
        """collar → arm_drag → get_up → collar must still go stale."""
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        collar = _rule_by_id("collar_elbow")
        arm_drag = _rule_by_id("arm_drag")
        get_up = _rule_by_id("get_up")
        rng = _SeqRng([0.0] * 20)

        logs = []
        for _ in range(3):
            st.position = [BodyPosition.STANDING, BodyPosition.STANDING]
            logs.append(apply_move(st, 0, collar, rng)[0])
            apply_move(st, 0, arm_drag, rng)
            apply_move(st, 1, get_up, rng)

        self.assertGreaterEqual(st.grapple_loop_pressure[0], 2)
        self.assertTrue(any("repeated tie-up stalls out" in log for log in logs))

    def test_missed_collar_still_builds_loop_pressure(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        collar = _rule_by_id("collar_elbow")
        p = hit_probability(st, 0, collar)

        apply_move(st, 0, collar, _SeqRng([min(0.999, p + 0.2), 0.99]))

        self.assertEqual(st.grapple_loop_pressure[0], 1)

    def test_alternating_turns_do_not_erase_tie_up_pressure(self) -> None:
        """The opponent's turn must not launder the initiator's loop debt."""
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        collar = _rule_by_id("collar_elbow")
        counter = _rule_by_id("grapple_counter")
        rng = _SeqRng([0.0] * 10)  # every roll lands

        logs = []
        for _ in range(4):
            st.position[1] = BodyPosition.STANDING
            logs.append(apply_move(st, 0, collar, rng)[0])
            st.position[1] = BodyPosition.GRAPPLED
            apply_move(st, 1, counter, rng)

        self.assertGreaterEqual(st.grapple_loop_pressure[0], 2)
        self.assertTrue(any("repeated tie-up stalls out" in log for log in logs))

    def test_escaping_a_tie_up_does_not_build_escaper_grapple_pressure(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GRAPPLED
        counter = _rule_by_id("grapple_counter")
        p = hit_probability(st, 0, counter)

        apply_move(st, 0, counter, _SeqRng([max(0.0, p - 0.2), 0.99]))

        self.assertEqual(st.grapple_loop_pressure[0], 0)
        self.assertEqual(st.counter_loop_pressure[0], 1)

    def test_successful_grapple_counter_takes_the_tie_up(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GRAPPLED
        st.position[1] = BodyPosition.STANDING
        counter = _rule_by_id("grapple_counter")
        p = hit_probability(st, 0, counter)

        apply_move(st, 0, counter, _SeqRng([max(0.0, p - 0.2), 0.99]))

        self.assertEqual(st.position[0], BodyPosition.STANDING)
        self.assertEqual(st.position[1], BodyPosition.GRAPPLED)

    def test_missed_grapple_counter_leaves_the_lock_in_place(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GRAPPLED
        st.position[1] = BodyPosition.STANDING
        counter = _rule_by_id("grapple_counter")
        p = hit_probability(st, 0, counter)

        apply_move(st, 0, counter, _SeqRng([min(1.0, p + 0.2), 0.99]))

        self.assertEqual(st.position[0], BodyPosition.GRAPPLED)
        self.assertEqual(st.position[1], BodyPosition.STANDING)

    def test_repeated_grapple_counter_gets_predictable(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        counter = _rule_by_id("grapple_counter")
        rng = _SeqRng([0.0] * 12)
        logs = []
        for _ in range(3):
            st.position[1] = BodyPosition.GRAPPLED
            logs.append(apply_move(st, 1, counter, rng)[0])

        self.assertGreaterEqual(st.counter_loop_pressure[1], 2)
        self.assertTrue(any("counter is getting predictable" in log for log in logs))

    def test_stale_grapple_counter_deals_less_damage(self) -> None:
        fresh = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        stale = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        fresh.position[1] = BodyPosition.GRAPPLED
        stale.position[1] = BodyPosition.GRAPPLED
        stale.counter_loop_pressure = [0, 3]
        counter = _rule_by_id("grapple_counter")
        p_fresh = hit_probability(fresh, 1, counter)
        p_stale = hit_probability(stale, 1, counter)
        apply_move(fresh, 1, counter, _SeqRng([max(0.0, p_fresh - 0.2), 0.99]))
        apply_move(stale, 1, counter, _SeqRng([max(0.0, p_stale - 0.2), 0.99]))

        self.assertLess(stale.health[0], 132)
        self.assertGreater(stale.health[0], fresh.health[0])
        self.assertLess(p_stale, p_fresh)

    def test_non_grapple_move_soft_decays_loop_pressure(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.grapple_loop_pressure = [3, 0]
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)

        apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))

        self.assertEqual(st.grapple_loop_pressure[0], 2)

    def test_get_up_does_not_launder_grapple_loop_debt(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GROUNDED
        st.grapple_loop_pressure = [2, 0]
        get_up = _rule_by_id("get_up")
        p = hit_probability(st, 0, get_up)

        apply_move(st, 0, get_up, _SeqRng([max(0.0, p - 0.2)]))

        self.assertEqual(st.grapple_loop_pressure[0], 2)

    def test_stale_tie_up_loses_hit_probability(self) -> None:
        fresh = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        stale = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        stale.grapple_loop_pressure = [3, 0]
        collar = _rule_by_id("collar_elbow")

        self.assertLess(
            hit_probability(stale, 0, collar), hit_probability(fresh, 0, collar)
        )

    def test_repeated_climb_taxes_setup_loop(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.setup_loop_pressure = [2, 0]
        st.momentum = [1, 1]
        climb = _rule_by_id("climb")

        log, _, _ = apply_move(st, 0, climb, None)

        self.assertEqual(st.position[0], BodyPosition.TOP_ROPE)
        self.assertEqual(st.setup_loop_pressure[0], 3)
        self.assertEqual(st.momentum[0], 1)  # climb momentum_gain cancelled
        self.assertEqual(st.momentum[1], 2)
        self.assertIn("climb looks telegraphed", log)

    def test_alternating_turns_do_not_erase_climb_pressure(self) -> None:
        """Regression: a shared counter was zeroed by the opponent's turn every time."""
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        climb = _rule_by_id("climb")
        punch = _rule_by_id("punch")
        # climb is automatic; each punch consumes hit / blood / groggy rolls.
        rng = _SeqRng([0.0, 0.99, 0.99] * 4)

        logs = []
        for _ in range(4):
            st.position[0] = BodyPosition.STANDING
            logs.append(apply_move(st, 0, climb, rng)[0])
            apply_move(st, 1, punch, rng)

        self.assertGreaterEqual(st.setup_loop_pressure[0], 2)
        self.assertTrue(any("climb looks telegraphed" in log for log in logs))

    def test_top_rope_payoff_pays_down_setup_debt(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.TOP_ROPE
        st.position[1] = BodyPosition.GROUNDED
        st.setup_loop_pressure = [3, 0]
        splash = _rule_by_id("top_splash")
        p = hit_probability(st, 0, splash)

        apply_move(st, 0, splash, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))

        # Cashing the setup pays debt down, but doesn't wipe a long climb habit.
        self.assertEqual(st.setup_loop_pressure[0], 2)

    def test_get_up_does_not_erase_setup_loop_debt(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GROUNDED
        st.setup_loop_pressure = [2, 0]
        get_up = _rule_by_id("get_up")
        p = hit_probability(st, 0, get_up)

        apply_move(st, 0, get_up, _SeqRng([max(0.0, p - 0.2)]))

        self.assertEqual(st.setup_loop_pressure[0], 2)
        self.assertEqual(st.position[0], BodyPosition.STANDING)

    def test_standing_offense_decays_setup_loop_debt(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.setup_loop_pressure = [2, 0]
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)

        apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))

        self.assertEqual(st.setup_loop_pressure[0], 1)

    def test_one_actor_loop_does_not_tax_the_other(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.setup_loop_pressure = [3, 0]

        self.assertTrue(move_is_stale(st, 0, _rule_by_id("climb").move))
        self.assertFalse(move_is_stale(st, 1, _rule_by_id("climb").move))


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

    def test_knockdown_sets_cover_heat(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.health[1] = int(st.wrestlers[1].max_health * 0.2)
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)

        apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))

        self.assertTrue(st.cover_heat[1])
        self.assertGreaterEqual(st.pin_bonus_next_cover[0], 3)

    def test_cover_heat_makes_get_up_harder(self) -> None:
        cold = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        hot = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        cold.position[0] = BodyPosition.GROUNDED
        hot.position[0] = BodyPosition.GROUNDED
        hot.cover_heat[0] = True
        hot.cover_heat_lock[0] = True
        get_up = _rule_by_id("get_up")

        self.assertEqual(hit_probability(hot, 0, get_up), 0.0)
        self.assertGreater(hit_probability(cold, 0, get_up), 0.0)

    def test_first_rise_after_knockdown_always_fails(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.health[1] = int(st.wrestlers[1].max_health * 0.2)
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)
        apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))
        self.assertTrue(st.cover_heat_lock[1])

        get_up = _rule_by_id("get_up")
        log, _, _ = apply_move(st, 1, get_up, _SeqRng([0.0]))  # would normally hit

        self.assertEqual(st.position[1], BodyPosition.GROUNDED)
        self.assertFalse(st.cover_heat_lock[1])
        self.assertTrue(st.cover_heat[1])
        self.assertIn("vulnerable to a cover", log)

    def test_successful_get_up_clears_cover_heat(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.GROUNDED
        st.cover_heat[0] = True
        get_up = _rule_by_id("get_up")
        p = hit_probability(st, 0, get_up)

        apply_move(st, 0, get_up, _SeqRng([max(0.0, p - 0.2)]))

        self.assertFalse(st.cover_heat[0])
        self.assertEqual(st.position[0], BodyPosition.STANDING)

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

    def test_first_pin_seeds_a_near_fall_when_defender_not_critical(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GROUNDED
        st.health[1] = int(st.wrestlers[1].max_health * 0.40)
        pin = _rule_by_id("pin")

        log, winner, seq = apply_move(st, 0, pin, _SeqRng([], [9, 1, 9, 1, 9, 1]))

        self.assertIsNone(winner)
        self.assertIsNotNone(seq)
        self.assertFalse(seq.won)
        self.assertIn("kicks out", log)
        self.assertEqual(st.pins_attempted, 1)
        self.assertIn("Referee: 2…", log)

    def test_first_pin_can_finish_when_critically_down(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GROUNDED
        st.health[1] = int(st.wrestlers[1].max_health * 0.05)
        st.momentum[0] = 5
        pin = _rule_by_id("pin")
        # Huge attacker rolls, tiny defender rolls → clean fall if allowed.
        log, winner, seq = apply_move(st, 0, pin, _SeqRng([], [10, 1, 10, 1, 10, 1]))

        self.assertEqual(winner, 0)
        self.assertTrue(seq.won)
        self.assertIn("PINFALL", log)
        self.assertNotIn("kicks out", log)

    def test_first_pin_after_knockdown_hp_near_falls(self) -> None:
        """Knockdown-band HP (~15%) must still seed a near-fall on the first cover."""
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GROUNDED
        st.health[1] = int(st.wrestlers[1].max_health * 0.15)
        pin = _rule_by_id("pin")

        log, winner, seq = apply_move(st, 0, pin, _SeqRng([], [10, 1, 10, 1, 10, 1]))

        self.assertIsNone(winner)
        self.assertFalse(seq.won)
        self.assertIn("kicks out", log)

    def test_second_pin_can_finish_after_near_fall(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GROUNDED
        st.health[1] = int(st.wrestlers[1].max_health * 0.40)
        pin = _rule_by_id("pin")
        apply_move(st, 0, pin, _SeqRng([], [9, 1, 9, 1, 9, 1]))
        self.assertEqual(st.pins_attempted, 1)

        log, winner, seq = apply_move(st, 0, pin, _SeqRng([], [10, 1, 10, 1, 10, 1]))

        self.assertEqual(winner, 0)
        self.assertTrue(seq.won)
        self.assertIn("PINFALL", log)

    def test_cpu_prefers_pin_over_finisher_during_cover_heat(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        st.position[0] = BodyPosition.GROUNDED
        st.health[0] = int(st.wrestlers[0].max_health * 0.18)
        st.cover_heat[0] = True
        st.pin_bonus_next_cover[1] = 3

        pin_score = _cpu_rule_score(st, 1, _rule_by_id("pin"))
        heavy = _rule_by_id("leg_drop")
        self.assertGreater(pin_score, _cpu_rule_score(st, 1, heavy))

    def test_cpu_prefers_pin_after_finisher_echo_on_healthy_target(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        st.position[0] = BodyPosition.GROUNDED
        st.health[0] = int(st.wrestlers[0].max_health * 0.55)
        st.pin_bonus_next_cover[1] = 12

        pin_score = _cpu_rule_score(st, 1, _rule_by_id("pin"))
        stomp = _rule_by_id("leg_drop")
        self.assertGreater(pin_score, _cpu_rule_score(st, 1, stomp))

    def test_underdog_gets_hit_bonus_when_far_behind(self) -> None:
        even = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        behind = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        behind.health[0] = int(behind.wrestlers[0].max_health * 0.25)
        punch = _rule_by_id("punch")

        self.assertGreater(hit_probability(behind, 0, punch), hit_probability(even, 0, punch))



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

        break_score = _cpu_rule_score(st, 1, _rule_by_id("break_grapple"))
        counter_score = _cpu_rule_score(st, 1, _rule_by_id("grapple_counter"))

        self.assertGreater(counter_score, break_score)

    def test_cpu_demotes_stale_grapple_counter(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GRAPPLED
        st.counter_loop_pressure = [0, 3]

        break_score = _cpu_rule_score(st, 1, _rule_by_id("break_grapple"))
        counter_score = _cpu_rule_score(st, 1, _rule_by_id("grapple_counter"))

        self.assertGreater(break_score, counter_score)

    def test_cpu_discourages_its_own_stale_tie_up(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.grapple_loop_pressure = [0, 3]
        collar_score = _cpu_rule_score(st, 1, _rule_by_id("collar_elbow"))
        punch_score = _cpu_rule_score(st, 1, _rule_by_id("punch"))

        self.assertLess(collar_score, punch_score)

    def test_cpu_discourages_stale_climb(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.setup_loop_pressure = [0, 3]
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
        self.assertTrue(st.groggy_skip_turn[1])
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
        st.groggy_skip_turn[0] = False
        shake = _rule_by_id("shake_groggy")
        p = hit_probability(st, 0, shake)
        rng = _SeqRng([max(0.0, p - 0.2)])
        apply_move(st, 0, shake, rng)
        self.assertFalse(st.groggy[0])

    def test_desperation_success_clears_actor_groggy(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.groggy[0] = True
        st.groggy_opponent_actions_left[0] = 2
        st.groggy_skip_turn[0] = False
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
        st.groggy_skip_turn[0] = False
        ids = {r.move.id for _, r in st.valid_rules(0)}
        self.assertEqual(ids, {"shake_groggy", "desperation_strike"})

    def test_groggy_skip_turn_blocks_immediate_shake(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.groggy[0] = True
        st.groggy_skip_turn[0] = True
        self.assertEqual(st.valid_rules(0), [])
        log = consume_groggy_skip_turn(st, 0)
        self.assertIsNotNone(log)
        self.assertFalse(st.groggy_skip_turn[0])
        ids = {r.move.id for _, r in st.valid_rules(0)}
        self.assertEqual(ids, {"shake_groggy", "desperation_strike"})

    def test_groggy_grappled_actor_can_escape_or_counter(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GRAPPLED
        st.groggy[1] = True
        st.groggy_opponent_actions_left[1] = 2
        st.groggy_skip_turn[1] = False
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


class TestPullOffTop(unittest.TestCase):
    def test_pull_off_top_dumps_target_to_the_mat(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[0] = BodyPosition.STANDING
        st.position[1] = BodyPosition.TOP_ROPE
        pull = _rule_by_id("pull_off_top")
        p = hit_probability(st, 0, pull)
        apply_move(st, 0, pull, _SeqRng([max(0.0, p - 0.2)]))

        self.assertEqual(st.position[0], BodyPosition.STANDING)
        self.assertEqual(st.position[1], BodyPosition.GROUNDED)


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


class TestMatchEvents(unittest.TestCase):
    def test_result_unpacks_as_legacy_triple(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)
        result = apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))
        log, winner, seq = result
        self.assertIsInstance(log, str)
        self.assertIsNone(winner)
        self.assertIsNone(seq)
        self.assertEqual(result[0], log)

    def test_clean_hit_emits_damage_matching_health(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        before = st.health[1]
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)
        result = apply_move(st, 0, punch, _SeqRng([max(0.0, p - 0.2), 0.99, 0.99]))
        dealt = before - st.health[1]
        damage = next(event for event in result.events if event.kind == "damage")
        self.assertEqual(damage.amount, dealt)
        self.assertEqual(damage.move_id, "punch")
        self.assertEqual(damage.actor, 0)
        self.assertEqual(damage.target, 1)

    def test_whiff_emits_reversal_or_miss(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        punch = _rule_by_id("punch")
        p = hit_probability(st, 0, punch)
        result = apply_move(st, 0, punch, _SeqRng([min(1.0, p + 0.2), 0.99]))
        kinds = {event.kind for event in result.events}
        self.assertTrue(kinds & {"reversal", "miss"})
        self.assertNotIn("damage", kinds)

    def test_pin_sequence_carries_step_events(self) -> None:
        st = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["cm_punk"]))
        st.position[1] = BodyPosition.GROUNDED
        st.health[1] = 1
        result = apply_move(st, 0, _rule_by_id("pin"), _SeqRng([], [10, 1, 10, 1, 10, 1]))
        self.assertIsNotNone(result.pin_sequence)
        assert result.pin_sequence is not None
        self.assertEqual(len(result.pin_sequence.steps), len(result.pin_sequence.step_events))
        kinds = [event.kind for event in result.events]
        self.assertTrue(
            "pinfall" in kinds or "pin_kickout" in kinds or "pin_count" in kinds
        )


if __name__ == "__main__":
    unittest.main()
