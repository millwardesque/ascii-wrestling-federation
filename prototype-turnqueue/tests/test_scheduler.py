import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game import MatchState, advance_to, apply_move
from main import _settle_queue, run_match
from moves import BodyPosition, move_tempo_cost
from render_playtest import PlaytestRenderer
from scheduler import (
    TurnQueue,
    actor_speeds,
    effective_speed,
    move_delay,
    opponent_actions_conceded,
    project_order,
    project_with_choice,
    projection_costs,
    rule_delay,
    speed_for,
    wrestler_base_speed,
)
from wrestlers import ROSTER


def _rule(state: MatchState, move_id: str):
    return next(r for r in state.rules if r.move.id == move_id)


class _AlwaysHits(random.Random):
    """Every roll succeeds, so move-resolution tests do not depend on a lucky seed."""

    def random(self) -> float:
        return 0.0


class TestSpeed(unittest.TestCase):
    def test_agility_is_compressed_not_used_raw(self) -> None:
        """A 9-point agility gap must not become a 2.5x action advantage."""
        slow = wrestler_base_speed(ROSTER["andre"])  # agility 6
        fast = wrestler_base_speed(ROSTER["mr_perfect"])  # agility 15
        self.assertLess(fast / slow, 1.6)
        self.assertGreater(fast / slow, 1.1)

    def test_condition_slows_a_worn_down_wrestler(self) -> None:
        w = ROSTER["bret_hart"]
        healthy = speed_for(
            w, condition_frac=1.0, position=BodyPosition.STANDING, groggy=False
        )
        spent = speed_for(
            w, condition_frac=0.0, position=BodyPosition.STANDING, groggy=False
        )
        self.assertLess(spent, healthy)

    def test_grounded_and_groggy_both_cost_speed(self) -> None:
        w = ROSTER["bret_hart"]
        standing = speed_for(
            w, condition_frac=1.0, position=BodyPosition.STANDING, groggy=False
        )
        grounded = speed_for(
            w, condition_frac=1.0, position=BodyPosition.GROUNDED, groggy=False
        )
        groggy = speed_for(
            w, condition_frac=1.0, position=BodyPosition.STANDING, groggy=True
        )
        self.assertLess(grounded, standing)
        self.assertLess(groggy, standing)

    def test_speed_never_drops_to_zero(self) -> None:
        """Every penalty stacked at once must still leave a wrestler able to act."""
        floor = speed_for(
            ROSTER["andre"],
            condition_frac=0.0,
            position=BodyPosition.GROUNDED,
            groggy=True,
        )
        self.assertGreater(floor, 0.0)


class TestTurnQueueOrdering(unittest.TestCase):
    def test_lowest_timeline_position_acts_next(self) -> None:
        queue = TurnQueue(next_act_at=[3.0, 1.0])
        self.assertEqual(queue.pop_next([10.0, 10.0]), 1)
        self.assertEqual(queue.clock, 1.0)

    def test_ties_go_to_the_faster_wrestler(self) -> None:
        queue = TurnQueue(next_act_at=[0.0, 0.0])
        self.assertEqual(queue.pop_next([9.0, 11.0]), 1)
        self.assertEqual(queue.pop_next([11.0, 9.0]), 0)

    def test_schedule_is_relative_to_the_clock_not_the_old_position(self) -> None:
        queue = TurnQueue(next_act_at=[2.0, 5.0])
        queue.pop_next([10.0, 10.0])
        queue.schedule(0, 1.5)
        self.assertAlmostEqual(queue.next_act_at[0], 3.5)

    def test_cheaper_move_comes_back_around_sooner(self) -> None:
        self.assertLess(move_delay(0.9, 10.0), move_delay(2.7, 10.0))

    def test_faster_wrestler_recovers_sooner_from_the_same_move(self) -> None:
        self.assertLess(move_delay(1.5, 12.0), move_delay(1.5, 9.0))


class TestProjection(unittest.TestCase):
    def test_projection_alternates_when_both_sides_are_identical(self) -> None:
        order = project_order([0.0, 0.0], [10.0, 10.0], [1.5, 1.5], 4)
        self.assertEqual(len(order), 4)
        self.assertEqual(sorted(order[:2]), [0, 1])

    def test_a_slow_move_concedes_a_projected_action(self) -> None:
        """The headline promise of the queue: expensive moves hand over the initiative."""
        # Actor 0 is on the clock with the opponent due one unit later, so whether the
        # actor moves again first is decided purely by what the chosen move costs.
        queue = TurnQueue(next_act_at=[0.0, 1.0])
        self.assertEqual(queue.pop_next([10.0, 10.0]), 0)
        speeds = [10.0, 10.0]
        defaults = [1.5, 1.5]

        cheap = project_with_choice(
            queue, speeds, defaults, actor_idx=0, chosen_cost=0.8, depth=3
        )
        expensive = project_with_choice(
            queue, speeds, defaults, actor_idx=0, chosen_cost=2.9, depth=3
        )

        self.assertEqual(cheap[0], 0, "a cheap move should get you back on the clock first")
        self.assertEqual(expensive[0], 1, "an expensive move should let them in")
        self.assertGreater(expensive.count(1), cheap.count(1))

    def test_conceded_count_matches_the_projection(self) -> None:
        queue = TurnQueue(next_act_at=[0.0, 1.0])
        queue.pop_next([10.0, 10.0])
        speeds = [10.0, 10.0]
        defaults = [1.5, 1.5]
        for cost in (0.7, 1.5, 2.9):
            conceded = opponent_actions_conceded(
                queue, speeds, defaults, actor_idx=0, chosen_cost=cost
            )
            projected = project_with_choice(
                queue, speeds, defaults, actor_idx=0, chosen_cost=cost, depth=6
            )
            opponent_before_me = projected.index(0) if 0 in projected else len(projected)
            self.assertEqual(conceded, opponent_before_me)

    def test_projection_agrees_with_what_actually_happens(self) -> None:
        """Projecting default-cost moves must match running those same moves."""
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        queue = TurnQueue()
        speeds = actor_speeds(state)
        cost = 1.5
        predicted = project_order(queue.next_act_at, speeds, [cost, cost], 5)

        actual: list[int] = []
        sim = TurnQueue()
        for _ in range(5):
            idx = sim.pop_next(speeds)
            actual.append(idx)
            sim.schedule(idx, move_delay(cost, speeds[idx]))
        self.assertEqual(predicted, actual)


class TestTimelineStateExpiry(unittest.TestCase):
    def test_groggy_lifts_once_its_deadline_passes(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        state.groggy[1] = True
        state.groggy_until[1] = 2.0

        advance_to(state, 1.5)
        self.assertTrue(state.groggy[1])
        advance_to(state, 2.5)
        self.assertFalse(state.groggy[1])

    def test_groggy_does_not_delete_a_turn(self) -> None:
        """Replaces the old skip-turn stun: a groggy wrestler still has legal moves."""
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        state.groggy[0] = True
        state.groggy_until[0] = 5.0
        self.assertTrue(state.valid_rules(0))

    def test_finisher_echo_expires_on_the_timeline(self) -> None:
        from game import finisher_echo

        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        state.pin_bonus_next_cover[0] = 12
        state.finisher_echo_until[0] = 3.0

        advance_to(state, 2.0)
        self.assertEqual(finisher_echo(state, 0), 12)
        advance_to(state, 4.0)
        self.assertEqual(finisher_echo(state, 0), 0)

    def test_loop_debt_sheds_with_elapsed_timeline(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        state.grapple_loop_pressure[0] = 3
        advance_to(state, 50.0)
        self.assertEqual(state.grapple_loop_pressure[0], 0)


class TestCoverWindow(unittest.TestCase):
    def test_knockdown_pushes_the_victim_down_the_queue(self) -> None:
        """The cover window is earned from the timeline, not a forced get-up failure."""
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        # Worn down enough to be floored by a jab, healthy enough to survive it.
        state.health[1] = 24
        queue = TurnQueue()
        speeds = actor_speeds(state)
        queue.pop_next(speeds)

        rule = _rule(state, "punch")
        apply_move(state, 0, rule, rng=_AlwaysHits())
        self.assertEqual(state.position[1], BodyPosition.GROUNDED)
        self.assertGreater(state.pending_timeline_push[1], 0.0)

        before = queue.next_act_at[1]
        _settle_queue(state, queue, 0, rule, actor_speeds(state))
        self.assertGreater(queue.next_act_at[1], before)
        self.assertEqual(state.pending_timeline_push[1], 0.0)

    def test_rising_is_no_longer_clamped_to_an_impossible_chance(self) -> None:
        from game import hit_probability

        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        state.position[0] = BodyPosition.GROUNDED
        state.cover_heat[0] = True
        p = hit_probability(state, 0, _rule(state, "get_up"))
        self.assertGreater(p, 0.15)


class TestMatchTermination(unittest.TestCase):
    def test_low_condition_wrestler_falls_behind_on_tempo(self) -> None:
        """Health-to-speed coupling is what stops a near-dead wrestler stalling forever."""
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        state.health[1] = 1
        speeds = actor_speeds(state)
        self.assertLess(speeds[1], speeds[0])

    def test_matches_finish_within_the_pacing_band(self) -> None:
        import io

        for seed in (1, 2, 3, 4, 5):
            with self.subTest(seed=seed):
                buf = io.StringIO()
                renderer = PlaytestRenderer(
                    policy="chaotic",
                    output=buf,
                    max_actions=400,
                    wrestler_ids=("bret_hart", "scott_hall"),
                    rng=random.Random(seed),
                )
                winner = run_match(
                    "bret_hart",
                    "scott_hall",
                    renderer,
                    match_seed=seed,
                    max_actions=400,
                )
                self.assertIsNotNone(winner, "match never resolved")
                self.assertLess(renderer.action_count, 400)


class TestTempoCosts(unittest.TestCase):
    def test_finishers_cost_more_than_jabs(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        jab = move_tempo_cost(_rule(state, "punch").move)
        finisher = move_tempo_cost(_rule(state, "sharp_shooter").move)
        self.assertGreater(finisher, jab * 2)

    def test_every_move_has_a_cost_in_the_clamped_band(self) -> None:
        from moves import TEMPO_COST_MAX, TEMPO_COST_MIN, all_move_rules

        for rule in all_move_rules():
            cost = move_tempo_cost(rule.move)
            self.assertGreaterEqual(cost, TEMPO_COST_MIN, rule.move.id)
            self.assertLessEqual(cost, TEMPO_COST_MAX, rule.move.id)

    def test_rule_delay_tracks_move_cost(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        speed = effective_speed(state, 0)
        self.assertLess(
            rule_delay(_rule(state, "punch"), speed),
            rule_delay(_rule(state, "climb"), speed),
        )

    def test_projection_cost_reacts_to_position(self) -> None:
        state = MatchState(wrestlers=(ROSTER["bret_hart"], ROSTER["scott_hall"]))
        standing = projection_costs(state)[0]
        state.position[0] = BodyPosition.GROUNDED
        grounded = projection_costs(state)[0]
        self.assertNotEqual(standing, grounded)


if __name__ == "__main__":
    unittest.main()
