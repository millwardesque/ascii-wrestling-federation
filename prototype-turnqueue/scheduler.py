"""Turn queue: who acts next, and how far their move pushes them back.

The match runs on a virtual timeline, not a wall clock. Each wrestler holds a
``next_act_at`` position; whoever sits lowest acts next. After acting they are pushed
forward by ``tempo cost / effective speed``, so a cheap jab comes back around fast and a
finisher leaves a long recovery the opponent can act inside.

Everything here is pure float arithmetic over a snapshot, which keeps headless playtests
instant and seed-reproducible. ``MatchState`` is only imported for typing so this module
stays free of a cycle with ``game``.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from config import get_config
from moves import BodyPosition, MoveRule, move_tempo_cost
from wrestlers import Wrestler

if TYPE_CHECKING:
    from game import MatchState

# Delay = cost * _DELAY_SCALE / speed. Scale matches the default speed base so one
# baseline-cost action by an average wrestler advances the timeline by about 1.0.
_DELAY_SCALE = 10.0

# Fallback when an actor has no legal moves to average over.
NEUTRAL_TEMPO_COST = 1.4

# Ceiling on how many opponent actions the UI and CPU will count inside one recovery.
_MAX_COUNTED_CONCESSIONS = 6

_EPSILON = 1e-9


def wrestler_base_speed(wrestler: Wrestler) -> float:
    """Agility compressed into a rate.

    Raw roster agility spans 6-15; used directly as a rate that is a 2.5x action
    advantage, which no amount of damage tuning would survive.
    """
    tempo = get_config().tempo
    return tempo.speed_base + (wrestler.agility - 10) * tempo.speed_per_agility_point


def speed_for(
    wrestler: Wrestler,
    *,
    condition_frac: float,
    position: BodyPosition,
    groggy: bool,
) -> float:
    """Effective speed from agility, condition, position, and groggy."""
    tempo = get_config().tempo
    speed = wrestler_base_speed(wrestler)

    frac = max(0.0, min(1.0, condition_frac))
    speed *= tempo.condition_slow_floor + (1.0 - tempo.condition_slow_floor) * frac

    if position == BodyPosition.GROUNDED:
        speed *= tempo.grounded_speed_mult
    elif position == BodyPosition.CORNER:
        speed *= tempo.corner_speed_mult
    elif position == BodyPosition.GRAPPLED:
        speed *= tempo.grappled_speed_mult

    if groggy:
        speed *= tempo.groggy_speed_mult

    return max(tempo.min_speed, speed)


def effective_speed(state: MatchState, idx: int) -> float:
    wrestler = state.wrestlers[idx]
    condition_frac = state.health[idx] / max(1, wrestler.max_health)
    return speed_for(
        wrestler,
        condition_frac=condition_frac,
        position=state.position[idx],
        groggy=state.groggy[idx],
    )


def actor_speeds(state: MatchState) -> list[float]:
    return [effective_speed(state, i) for i in (0, 1)]


def move_delay(cost: float, speed: float) -> float:
    """Timeline distance one action of ``cost`` costs a wrestler moving at ``speed``."""
    return cost * _DELAY_SCALE / max(speed, _EPSILON)


def rule_delay(rule: MoveRule, speed: float) -> float:
    return move_delay(move_tempo_cost(rule.move), speed)


def projection_cost(state: MatchState, idx: int) -> float:
    """Representative cost for "whatever they do next", used to project the queue.

    Median of the actor's currently legal moves, so the preview reacts to position —
    a grounded wrestler is projected on cheap get-up-ish costs, not on finishers.
    """
    options = state.valid_rules(idx)
    if not options:
        return NEUTRAL_TEMPO_COST
    return statistics.median(move_tempo_cost(rule.move) for _, rule in options)


def projection_costs(state: MatchState) -> list[float]:
    return [projection_cost(state, i) for i in (0, 1)]


def _winner(
    next_act_at: Sequence[float], speeds: Sequence[float], *, exclude: int | None = None
) -> int:
    """Lowest timeline position acts next; ties go to the faster wrestler, then index."""
    best = -1
    for i in range(len(next_act_at)):
        if i == exclude:
            continue
        if best < 0:
            best = i
            continue
        earlier = next_act_at[i] < next_act_at[best] - _EPSILON
        tied_but_faster = (
            abs(next_act_at[i] - next_act_at[best]) <= _EPSILON
            and speeds[i] > speeds[best]
        )
        if earlier or tied_but_faster:
            best = i
    return best


@dataclass
class TurnQueue:
    """Timeline positions for both wrestlers plus the clock of the action in progress."""

    next_act_at: list[float] = field(default_factory=lambda: [0.0, 0.0])
    clock: float = 0.0

    def peek_next(self, speeds: Sequence[float]) -> int:
        return _winner(self.next_act_at, speeds)

    def pop_next(self, speeds: Sequence[float]) -> int:
        """Advance the clock to the next actor and return their index."""
        idx = _winner(self.next_act_at, speeds)
        self.clock = max(self.clock, self.next_act_at[idx])
        return idx

    def schedule(self, idx: int, delay: float) -> None:
        self.next_act_at[idx] = self.clock + max(0.0, delay)

    def schedule_move(self, idx: int, cost: float, speed: float) -> None:
        self.schedule(idx, move_delay(cost, speed))


def project_order(
    next_act_at: Sequence[float],
    speeds: Sequence[float],
    default_costs: Sequence[float],
    depth: int,
) -> list[int]:
    """Forward-simulate ``depth`` upcoming actors assuming each takes a default-cost move."""
    times = list(next_act_at)
    order: list[int] = []
    for _ in range(max(0, depth)):
        idx = _winner(times, speeds)
        order.append(idx)
        times[idx] += move_delay(default_costs[idx], speeds[idx])
    return order


def project_with_choice(
    queue: TurnQueue,
    speeds: Sequence[float],
    default_costs: Sequence[float],
    *,
    actor_idx: int,
    chosen_cost: float,
    depth: int,
) -> list[int]:
    """Projected order if ``actor_idx`` commits to a move of ``chosen_cost`` right now.

    Call while ``actor_idx`` holds the clock (after ``pop_next``, before ``schedule``).
    This is what lets every menu row show its own tempo consequence.
    """
    times = list(queue.next_act_at)
    times[actor_idx] = queue.clock + move_delay(chosen_cost, speeds[actor_idx])
    return project_order(times, speeds, default_costs, depth)


def opponent_actions_conceded(
    queue: TurnQueue,
    speeds: Sequence[float],
    default_costs: Sequence[float],
    *,
    actor_idx: int,
    chosen_cost: float,
) -> int:
    """How many times the opponent acts before ``actor_idx`` comes back around.

    0 means you act again first. 2 means they get a full flurry inside your recovery.
    """
    opponent = 1 - actor_idx
    actor_next = queue.clock + move_delay(chosen_cost, speeds[actor_idx])
    step = move_delay(default_costs[opponent], speeds[opponent])
    at = queue.next_act_at[opponent]
    count = 0
    while at < actor_next - _EPSILON and count < _MAX_COUNTED_CONCESSIONS:
        count += 1
        at += step
    return count
