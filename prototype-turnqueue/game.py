"""Match flow: positions, damage, and pinfall resolution.

Timing runs on the turn-queue timeline in ``MatchState.clock``, not on action counts.
Anything with a duration (groggy, the finisher echo, finisher shock, loop debt) holds a
deadline and is expired by ``advance_to`` before the acting wrestler sees their options.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from commentary_events import MatchEvent
from config import get_config
from moves import BodyPosition, Move, MoveRule, all_move_rules, move_tempo_cost, move_valid
from scheduler import (
    TurnQueue,
    actor_speeds,
    opponent_actions_conceded,
    projection_costs,
)
from wrestlers import Wrestler

# Hit probability: p = clamp(BASE + k_surge*surge - k_diff*difficulty + ... , P_MIN, P_MAX)
# Surge (0–3) is this-flurry reliability. Match momentum gates finishers and pin/sub contests
# but does not feed the land chance. Tuned so surge 3 ≈ the old momentum-5 swing (~0.32).
_HIT_BASE = 0.66
_HIT_K_SURGE = 0.10
_SURGE_MAX = 3
_HIT_K_DIFFICULTY = 0.052
_HIT_K_ATTACKER_HP = 0.055
_HIT_K_DEFENDER_HP = 0.058
_HIT_K_AGILITY_GAP = 0.09  # scales (defender.agility - actor.agility) / 10
_HIT_P_MIN = 0.20
_HIT_P_MAX = 0.95

# Finisher-only bonus (on top of the shared hit formula): scales from 0 at the bell to
# _FINISHER_HIT_BONUS_MAX once combined damage reaches this fraction of combined max HP.
_FINISHER_HIT_BONUS_MAX = 0.05
_FINISHER_WEAR_FULL_AT_DAMAGE_FRAC = 0.32  # e.g. ~32% of combined pool lost → full bonus

# "Fight to your feet" — extra modifiers on top of the global hit formula (get_up only)
_GET_UP_BASE_BONUS = 0.12  # slightly easier than strikes; still scary when hurt or rocked
_GET_UP_BEATDOWN_PENALTY = 0.30  # multiplied by (1 - HP fraction); worse when badly hurt
_GET_UP_FINISH_SHOCK_K = 0.072  # per stack; stacks when you eat a finisher's damage
_GET_UP_FAIL_RELIEF_BONUS = 0.18  # repeated misses build escape momentum instead of dead turns

# Timeline durations, in the same units as TurnQueue delays (one baseline action ~= 1.0).
# Groggy no longer eats a turn: it slows the victim's speed and cuts their menu down to
# escapes for this long, so a wobbly wrestler still gets to act, just worse and later.
_GROGGY_DURATION = 2.2
# A landed finisher only pays off if you win the race back to the cover.
_FINISHER_ECHO_DURATION = 2.6
# Lingering-state decay: one stack falls off per interval of timeline elapsed.
_FINISHER_SHOCK_DECAY_INTERVAL = 3.0
_GET_UP_FAIL_DECAY_INTERVAL = 4.0
# Loop debt decays on elapsed timeline rather than per action, so a fast wrestler does not
# accrue staleness twice as fast as a slow one for the same behaviour.
_LOOP_PRESSURE_DECAY_INTERVAL = 3.5

# Rare easter egg: successful head-targeting hit may blood the defender for the rest of the match
_BLOODIED_CHANCE = 0.018

# Groggy procs on qualifying hits (separate rolls for strikes vs. slams / pending-on-stand)
_GROGGY_STANDING_CHANCE = 0.42  # punch / kick — immediate standing groggy
_GROGGY_ON_STAND_CHANCE = 0.48  # slams & finishers — pending until they stand

# A worn-down wrestler gets dumped to the mat by any clean damaging hit, which is what
# makes pins/submissions legal again. Without this, a standing opponent stuck near zero
# HP can never be finished and the match stalls.
_KNOCKDOWN_HP_FRAC = 0.20
# Knocking a worn-down wrestler flat buys a head start on the timeline on top of the
# grounded speed penalty. This is the cover window, and it is now earned rather than
# manufactured by forcing the first rise attempt to fail.
_KNOCKDOWN_HEAD_START = 0.9
# Below this, the first cover of the match may still go clean 1-2-3.
# Keep under the knockdown floor (~20%) so the first post-collapse cover near-falls.
_PIN_NEAR_FALL_FLOOR_HP_FRAC = 0.08
# Trailing wrestlers get a small hit bounce so snowballs can crack.
_UNDERDOG_HIT_GAP = 0.30
_UNDERDOG_HIT_BONUS_MAX = 0.14
# Cover heat after a knockdown: the CPU strongly prefers the pin. The window itself comes
# from the timeline now, so there is no hit-probability clamp on rising.
_COVER_HEAT_PIN_BONUS = 3
_COVER_HEAT_CPU_PIN_BIAS = 0.85
# After a non-bridge finisher: hook the leg even when a kickout is likely.
_FINISHER_COVER_CPU_PIN_BIAS = 0.78
_FINISHER_COVER_PIN_SCORE_BONUS = 95.0
# Loop taxes. Pressure is tracked per actor and only moves on that actor's own turns:
# a single shared counter is cancelled out by the opponent's turn, so an every-other-turn
# loop never accumulates.
_LOOP_STALE_THRESHOLD = 2
_LOOP_STALE_HIT_PENALTY = 0.09  # per stack past the threshold, so the menu % tells the truth
# Light tie-up throws keep the mat cycle alive — they neither build nor clear debt.
_GRAPPLE_LIGHT_PAYOFF_IDS = frozenset({"arm_drag", "hip_toss", "side_headlock"})
# Whips leave the standing/mat treadmill for a real setup.
_GRAPPLE_REAL_EXIT_IDS = frozenset({"irish_whip", "turnbuckle_whip"})


@dataclass
class PinSequence:
    """Pre-computed timed finish attempt: optional ``preamble_lines`` (e.g. damage + bridge text),
    then each step adds lines and a ``delay_after_sec`` pause before the next step."""

    won: bool
    preamble_lines: list[str]
    steps: list[tuple[list[str], float]]
    heading: str = "Pinfall attempt…"
    preamble_events: list[MatchEvent] = field(default_factory=list)
    step_events: list[list[MatchEvent]] = field(default_factory=list)


@dataclass
class MoveResult:
    """``apply_move`` return: legacy log plus structured events for commentary.

    Unpacks as ``(log, winner, pin_sequence)`` so existing callers keep working.
    """

    log: str
    winner: int | None
    pin_sequence: PinSequence | None
    events: list[MatchEvent] = field(default_factory=list)

    def __iter__(self):
        yield self.log
        yield self.winner
        yield self.pin_sequence

    def __getitem__(self, index: int):
        return (self.log, self.winner, self.pin_sequence)[index]


def pin_sequence_as_text(seq: PinSequence) -> str:
    parts: list[str] = []
    if seq.preamble_lines:
        parts.extend(seq.preamble_lines)
    for step_lines, _ in seq.steps:
        parts.extend(step_lines)
    return "\n".join(parts)


@dataclass
class MatchState:
    wrestlers: tuple[Wrestler, Wrestler]
    health: list[int] = field(default_factory=list)
    position: list[BodyPosition] = field(default_factory=list)
    momentum: list[int] = field(default_factory=list)
    # Short-lived sequence control (0–3). Feeds hit chance; dies when the flurry breaks.
    surge: list[int] = field(default_factory=list)
    bloodied: list[bool] = field(default_factory=list)
    rules: list[MoveRule] = field(default_factory=all_move_rules)
    cpu_last_move_id: str | None = None
    # Turn-queue timeline position of the action being resolved. Every deadline below is
    # measured against this; ``advance_to`` moves it and expires what has run out.
    clock: float = 0.0
    # Set when a finisher lands; added to each pin count while the echo window is open.
    pin_bonus_next_cover: list[int] = field(default_factory=list)
    # Timeline deadline for the finisher echo above. Past it, the bonus is dead.
    finisher_echo_until: list[float] = field(default_factory=list)
    # Taking finisher damage adds stacks; makes get_up harder until you shake it off (successful stand).
    finisher_shock: list[int] = field(default_factory=list)
    finisher_shock_decay_at: list[float] = field(default_factory=list)
    # Standing wobbly — cleared by opponent damage, the timer, a shake-off, or desperation strike.
    groggy: list[bool] = field(default_factory=list)
    # Timeline deadline at which groggy lifts on its own.
    groggy_until: list[float] = field(default_factory=list)
    # After certain slams/finishers while grounded; applies groggy when victim next stands (get_up or pickup).
    pending_groggy: list[bool] = field(default_factory=list)
    # Failed get-up attempts increase the next get-up chance and can grant escape momentum.
    get_up_fail_streak: list[int] = field(default_factory=list)
    get_up_fail_decay_at: list[float] = field(default_factory=list)
    # Per-actor loop debt. Grapple: raised by re-entering the tie-up (hit or miss);
    # light throws soft-decay it, whips / real exits clear it.
    grapple_loop_pressure: list[int] = field(default_factory=list)
    # Per-actor loop debt for climb / empty dismount spam; top-rope payoffs pay it down.
    setup_loop_pressure: list[int] = field(default_factory=list)
    # Per-actor debt for answering every tie-up with the same counter chip.
    counter_loop_pressure: list[int] = field(default_factory=list)
    # Next timeline point at which accumulated loop debt sheds a stack.
    loop_pressure_decay_at: list[float] = field(default_factory=list)
    # After a worn-down knockdown: defender is hot for a cover until they rise or get pinned.
    cover_heat: list[bool] = field(default_factory=list)
    # Extra timeline distance an action wants to shove a wrestler back by, on top of their
    # own recovery. The match loop drains this into the turn queue after each action.
    pending_timeline_push: list[float] = field(default_factory=list)
    # First pin of the match seeds a near-fall when the defender isn't critically down.
    pins_attempted: int = 0

    def __post_init__(self) -> None:
        if not self.health:
            self.health = [w.max_health for w in self.wrestlers]
        if not self.position:
            self.position = [BodyPosition.STANDING, BodyPosition.STANDING]
        if not self.momentum:
            self.momentum = [0, 0]
        if not self.surge:
            self.surge = [0, 0]
        if not self.bloodied:
            self.bloodied = [False, False]
        if not self.pin_bonus_next_cover:
            self.pin_bonus_next_cover = [0, 0]
        if not self.finisher_echo_until:
            self.finisher_echo_until = [0.0, 0.0]
        if not self.finisher_shock:
            self.finisher_shock = [0, 0]
        if not self.finisher_shock_decay_at:
            self.finisher_shock_decay_at = [0.0, 0.0]
        if not self.groggy:
            self.groggy = [False, False]
        if not self.groggy_until:
            self.groggy_until = [0.0, 0.0]
        if not self.pending_groggy:
            self.pending_groggy = [False, False]
        if not self.get_up_fail_streak:
            self.get_up_fail_streak = [0, 0]
        if not self.get_up_fail_decay_at:
            self.get_up_fail_decay_at = [0.0, 0.0]
        if not self.grapple_loop_pressure:
            self.grapple_loop_pressure = [0, 0]
        if not self.setup_loop_pressure:
            self.setup_loop_pressure = [0, 0]
        if not self.counter_loop_pressure:
            self.counter_loop_pressure = [0, 0]
        if not self.loop_pressure_decay_at:
            self.loop_pressure_decay_at = [0.0, 0.0]
        if not self.cover_heat:
            self.cover_heat = [False, False]
        if not self.pending_timeline_push:
            self.pending_timeline_push = [0.0, 0.0]

    def valid_rules(self, actor_idx: int) -> list[tuple[int, MoveRule]]:
        actor = self.wrestlers[actor_idx]
        target = self.wrestlers[1 - actor_idx]
        out: list[tuple[int, MoveRule]] = []
        for i, rule in enumerate(self.rules):
            if move_valid(
                rule,
                actor,
                target,
                self.position[actor_idx],
                self.position[1 - actor_idx],
                self.momentum[actor_idx],
                actor_groggy=self.groggy[actor_idx],
                target_groggy=self.groggy[1 - actor_idx],
            ):
                out.append((i, rule))
        return out


def finisher_echo(state: MatchState, actor_idx: int) -> int:
    """Pin bonus still owed from a recent finisher, or 0 once the window has closed."""
    if state.clock > state.finisher_echo_until[actor_idx]:
        return 0
    return state.pin_bonus_next_cover[actor_idx]


def _clear_finisher_echo(state: MatchState, actor_idx: int) -> None:
    state.pin_bonus_next_cover[actor_idx] = 0
    state.finisher_echo_until[actor_idx] = 0.0


def advance_to(state: MatchState, clock: float) -> None:
    """Move the match clock and expire everything whose deadline has passed.

    Call once per action, after the turn queue picks an actor and before their options
    are built, so the menu and the resolution agree about what is still live.
    """
    state.clock = clock
    for i in (0, 1):
        if state.groggy[i] and clock > state.groggy_until[i]:
            state.groggy[i] = False
            state.groggy_until[i] = 0.0
        if state.pin_bonus_next_cover[i] and clock > state.finisher_echo_until[i]:
            _clear_finisher_echo(state, i)
        while state.finisher_shock[i] > 0 and clock >= state.finisher_shock_decay_at[i]:
            state.finisher_shock[i] -= 1
            state.finisher_shock_decay_at[i] = clock + _FINISHER_SHOCK_DECAY_INTERVAL
        while state.get_up_fail_streak[i] > 0 and clock >= state.get_up_fail_decay_at[i]:
            state.get_up_fail_streak[i] -= 1
            state.get_up_fail_decay_at[i] = clock + _GET_UP_FAIL_DECAY_INTERVAL
        while clock >= state.loop_pressure_decay_at[i] and (
            state.grapple_loop_pressure[i]
            or state.counter_loop_pressure[i]
            or state.setup_loop_pressure[i]
        ):
            state.grapple_loop_pressure[i] = max(0, state.grapple_loop_pressure[i] - 1)
            state.counter_loop_pressure[i] = max(0, state.counter_loop_pressure[i] - 1)
            state.setup_loop_pressure[i] = max(0, state.setup_loop_pressure[i] - 1)
            state.loop_pressure_decay_at[i] = clock + _LOOP_PRESSURE_DECAY_INTERVAL


def _finisher_wear_fraction(state: MatchState) -> float:
    """0 at full health both sides → 1 once enough total damage has been dealt (match has worn on)."""
    w0, w1 = state.wrestlers
    h0, h1 = state.health
    total_max = max(1, w0.max_health + w1.max_health)
    damage_dealt = max(0, (w0.max_health - h0) + (w1.max_health - h1))
    cap = total_max * _FINISHER_WEAR_FULL_AT_DAMAGE_FRAC
    return min(1.0, damage_dealt / max(1e-9, cap))


def move_needs_hit_roll(m: Move) -> bool:
    """Pins use _resolve_pin; utility moves skip the offensive roll."""
    if m.is_pin:
        return False
    return not m.skip_hit_roll


def move_landing_probability_label(state: MatchState, actor_idx: int, rule: MoveRule) -> str:
    """Short UI label: P(land) for moves that use the hit roll; ``pin`` / ``auto`` otherwise."""
    m = rule.move
    if m.is_pin:
        return "pin"
    if not move_needs_hit_roll(m):
        return "auto"
    p = hit_probability(state, actor_idx, rule)
    return f"{p * 100:.0f}%"


def loop_pressure_for(state: MatchState, actor_idx: int, m: Move) -> int:
    """This actor's accumulated debt for the loop family ``m`` belongs to (0 if none)."""
    if m.id == "collar_elbow":
        return state.grapple_loop_pressure[actor_idx]
    if m.id == "grapple_counter":
        return state.counter_loop_pressure[actor_idx]
    if m.id in {"climb", "dismount_top"}:
        return state.setup_loop_pressure[actor_idx]
    return 0


def move_is_stale(state: MatchState, actor_idx: int, m: Move) -> bool:
    """True once this actor has leaned on the move's loop enough to be taxed for it."""
    return loop_pressure_for(state, actor_idx, m) >= _LOOP_STALE_THRESHOLD


def hit_probability(state: MatchState, actor_idx: int, rule: MoveRule) -> float:
    """Deterministic P(land) for the current snapshot — shared by runtime roll and CPU EV."""
    m = rule.move
    tgt = 1 - actor_idx
    actor = state.wrestlers[actor_idx]
    target = state.wrestlers[tgt]
    surge = state.surge[actor_idx]
    att_hp = state.health[actor_idx] / max(1, actor.max_health)
    def_hp = state.health[tgt] / max(1, target.max_health)
    diff = m.difficulty
    agi_gap = (target.agility - actor.agility) / 10.0
    p = (
        _HIT_BASE
        + _HIT_K_SURGE * surge
        - _HIT_K_DIFFICULTY * diff
        + _HIT_K_ATTACKER_HP * att_hp
        - _HIT_K_DEFENDER_HP * def_hp
        - _HIT_K_AGILITY_GAP * agi_gap
    )
    if m.id == "get_up" or m.id == "shake_groggy":
        p += _GET_UP_BASE_BONUS
        p -= _GET_UP_BEATDOWN_PENALTY * (1.0 - att_hp)
        p -= _GET_UP_FINISH_SHOCK_K * float(state.finisher_shock[actor_idx])
        if m.id == "get_up":
            p += _GET_UP_FAIL_RELIEF_BONUS * min(2, state.get_up_fail_streak[actor_idx])
    if m.is_finisher:
        p += _FINISHER_HIT_BONUS_MAX * _finisher_wear_fraction(state)
    pressure = loop_pressure_for(state, actor_idx, m)
    if pressure >= _LOOP_STALE_THRESHOLD:
        p -= _LOOP_STALE_HIT_PENALTY * float(pressure - _LOOP_STALE_THRESHOLD + 1)
    # Underdog bounce: when far behind on health, offense connects a bit more often.
    if m.base_damage > 0 and m.id not in {"grapple_counter", "desperation_strike"}:
        gap = def_hp - att_hp
        if gap > _UNDERDOG_HIT_GAP:
            p += min(_UNDERDOG_HIT_BONUS_MAX, (gap - _UNDERDOG_HIT_GAP) * 0.35)
    return max(_HIT_P_MIN, min(_HIT_P_MAX, p))


def _set_surge(state: MatchState, idx: int, value: int) -> tuple[int, int]:
    """Clamp surge to 0–``_SURGE_MAX``. Returns ``(old, new)``."""
    old = state.surge[idx]
    new = max(0, min(_SURGE_MAX, int(value)))
    state.surge[idx] = new
    return old, new


def _emit_surge_shift(
    events: list[MatchEvent] | None,
    *,
    actor: int,
    amount: int,
    target: int | None = None,
) -> None:
    if events is None or amount == 0:
        return
    events.append(
        MatchEvent(kind="surge_shift", actor=actor, target=target, amount=amount)
    )


def _apply_offensive_hit_surge(
    state: MatchState,
    actor_idx: int,
    m: Move,
    lines: list[str],
    events: list[MatchEvent],
) -> None:
    """Landed damage: attacker builds surge; defender's roll is broken."""
    tgt = 1 - actor_idx
    actor = state.wrestlers[actor_idx]
    target = state.wrestlers[tgt]
    victim_old, victim_new = _set_surge(state, tgt, 0)
    gained = False
    skip_gain = m.id == "grapple_counter" and move_is_stale(state, actor_idx, m)
    if not skip_gain:
        old, new = _set_surge(state, actor_idx, state.surge[actor_idx] + 1)
        gained = new != old
        _emit_surge_shift(events, actor=actor_idx, target=tgt, amount=new - old)
    _emit_surge_shift(events, actor=tgt, amount=victim_new - victim_old)
    if gained:
        lines.append(f"  The roll is building for {actor.nickname}.")
    elif victim_old != victim_new:
        lines.append(f"  {target.nickname} loses the roll.")


def _apply_offensive_miss_surge(
    state: MatchState,
    actor_idx: int,
    lines: list[str],
    events: list[MatchEvent],
) -> None:
    """Whiff or reversal: actor's roll dies; opponent seizes the moment."""
    tgt = 1 - actor_idx
    target = state.wrestlers[tgt]
    actor_old, actor_new = _set_surge(state, actor_idx, 0)
    opp_old, opp_new = _set_surge(state, tgt, state.surge[tgt] + 1)
    _emit_surge_shift(events, actor=actor_idx, amount=actor_new - actor_old)
    _emit_surge_shift(events, actor=tgt, amount=opp_new - opp_old)
    if actor_old == actor_new and opp_old == opp_new:
        return
    if opp_old != opp_new:
        lines.append(
            f"  The sequence snaps — {target.nickname} seizes the moment."
        )
    else:
        lines.append("  The sequence snaps.")


def _stall_actor_surge(
    state: MatchState, actor_idx: int, events: list[MatchEvent] | None
) -> None:
    """Stale loop: the chain stalled. Stars stay put."""
    old, new = _set_surge(state, actor_idx, 0)
    _emit_surge_shift(events, actor=actor_idx, amount=new - old)


def _kickout_surge_followthrough(
    state: MatchState, actor_idx: int, tgt: int
) -> tuple[list[str], list[MatchEvent]]:
    """Near-fall adrenaline: defender surge +2. Caller still dumps attacker momentum."""
    extra_lines: list[str] = []
    extra_events: list[MatchEvent] = []
    old, new = _set_surge(state, tgt, state.surge[tgt] + 2)
    if old != new:
        extra_lines.append(
            f"  {state.wrestlers[tgt].nickname} catches a second wind."
        )
        extra_events.append(
            MatchEvent(
                kind="surge_shift",
                actor=tgt,
                target=actor_idx,
                amount=new - old,
            )
        )
    return extra_lines, extra_events


def _rand_float(rng: random.Random | None) -> float:
    if rng is not None:
        return rng.random()
    return random.random()


def _rand_int(rng: random.Random | None, a: int, b: int) -> int:
    if rng is not None:
        return rng.randint(a, b)
    return random.randint(a, b)


def _damage_with_stats(base: int, actor: Wrestler, target: Wrestler, agility_bonus: bool) -> int:
    raw = base + actor.strength // 3
    mitigation = target.endurance // 4
    if agility_bonus:
        raw += actor.agility // 4
    return max(1, raw - mitigation)


def _apply_standing_groggy(state: MatchState, victim_idx: int) -> None:
    """Standing groggy: the victim keeps acting, just slower and only with escapes.

    Replaces the old lose-a-turn stun. The cost is paid through the speed multiplier in
    ``scheduler.speed_for`` plus the restricted move gate in ``moves.move_valid``.
    """
    state.groggy[victim_idx] = True
    state.groggy_until[victim_idx] = state.clock + _GROGGY_DURATION


def _clear_groggy(state: MatchState, victim_idx: int) -> None:
    state.groggy[victim_idx] = False
    state.groggy_until[victim_idx] = 0.0


def _clear_groggy_from_opponent_damage(state: MatchState, victim_idx: int, m: Move) -> None:
    """Any damaging offensive move from the opponent clears groggy (desperation strike exempted for victim)."""
    if m.id == "desperation_strike":
        return
    if m.base_damage > 0 and state.groggy[victim_idx]:
        _clear_groggy(state, victim_idx)


def _try_apply_groggy_after_damage(
    state: MatchState,
    m: Move,
    tgt: int,
    rng: random.Random | None,
    was_groggy_before_hit: bool,
) -> bool:
    """Maybe apply groggy / pending groggy after a successful damaging hit."""
    if m.causes_groggy_on_stand:
        if _rand_float(rng) >= _GROGGY_ON_STAND_CHANCE:
            return False
        state.pending_groggy[tgt] = True
        return True
    if m.causes_groggy and state.position[tgt] == BodyPosition.STANDING:
        if was_groggy_before_hit:
            return False
        if _rand_float(rng) >= _GROGGY_STANDING_CHANCE:
            return False
        _apply_standing_groggy(state, tgt)
        return True
    return False


def _apply_loop_pressure(
    state: MatchState,
    actor_idx: int,
    m: Move,
    lines: list[str],
    events: list[MatchEvent] | None = None,
) -> int:
    """Tax an actor for repeating their own neutral/setup loop. Returns effective momentum gain.

    Tie-up debt tracks the whole collar→chip→re-tie cycle: attempts count even on a miss,
    light throws only soft-decay pressure, and only whips / real exits wipe it. Grapple
    counter builds its own defender debt so the same answer cannot chip forever for free.
    """
    tgt = 1 - actor_idx
    actor = state.wrestlers[actor_idx]
    mom_gain = m.momentum_gain

    grapple_before = state.grapple_loop_pressure[actor_idx]
    counter_before = state.counter_loop_pressure[actor_idx]
    if m.id == "collar_elbow":
        state.grapple_loop_pressure[actor_idx] = min(4, grapple_before + 1)
        if grapple_before >= _LOOP_STALE_THRESHOLD:
            mom_gain = 0
            _stall_actor_surge(state, actor_idx, events)
            lines.append(
                f"  The repeated tie-up stalls out — {actor.nickname} loses the roll."
            )
            if events is not None:
                events.append(
                    MatchEvent(
                        kind="loop_pressure",
                        actor=actor_idx,
                        target=tgt,
                        move_id=m.id,
                        move_name=m.name,
                    )
                )
    elif m.id in _GRAPPLE_REAL_EXIT_IDS:
        state.grapple_loop_pressure[actor_idx] = 0
    elif m.id in _GRAPPLE_LIGHT_PAYOFF_IDS or m.target_grappled:
        # Chip throws are the treadmill — leave debt alone so re-ties still accumulate.
        pass
    elif m.id == "grapple_counter":
        state.counter_loop_pressure[actor_idx] = min(4, counter_before + 1)
        if counter_before >= _LOOP_STALE_THRESHOLD:
            mom_gain = 0
            _stall_actor_surge(state, actor_idx, events)
            lines.append(
                f"  The counter is getting predictable — {actor.nickname} loses the roll."
            )
            if events is not None:
                events.append(
                    MatchEvent(
                        kind="loop_pressure",
                        actor=actor_idx,
                        target=tgt,
                        move_id=m.id,
                        move_name=m.name,
                    )
                )
    elif m.id == "break_grapple":
        # Clean break is the non-loop escape and wipes the counter habit.
        state.counter_loop_pressure[actor_idx] = 0
    # Everything else leaves debt where it is; `advance_to` sheds it on elapsed timeline
    # so a fast wrestler does not pay staleness twice as fast for the same behaviour.

    setup_before = state.setup_loop_pressure[actor_idx]
    if m.id == "climb":
        state.setup_loop_pressure[actor_idx] = min(4, setup_before + 1)
        if setup_before >= _LOOP_STALE_THRESHOLD:
            mom_gain = 0
            _stall_actor_surge(state, actor_idx, events)
            lines.append(
                f"  The climb looks telegraphed — the sequence stalls."
            )
            if events is not None:
                events.append(
                    MatchEvent(
                        kind="loop_pressure",
                        actor=actor_idx,
                        target=tgt,
                        move_id=m.id,
                        move_name=m.name,
                    )
                )
    elif m.id == "dismount_top":
        state.setup_loop_pressure[actor_idx] = min(4, setup_before + 1)
        if setup_before >= _LOOP_STALE_THRESHOLD:
            _stall_actor_surge(state, actor_idx, events)
            lines.append("  Another empty climb — the sequence stalls.")
            if events is not None:
                events.append(
                    MatchEvent(
                        kind="loop_pressure",
                        actor=actor_idx,
                        target=tgt,
                        move_id=m.id,
                        move_name=m.name,
                    )
                )
    elif m.actor_top and m.base_damage > 0:
        # Cashing the climb is the payoff that clears the debt it built.
        state.setup_loop_pressure[actor_idx] = 0

    return mom_gain


def _top_rope_whiff_crashes(m: Move) -> bool:
    """True when a missed/reversed top-rope attack should dump the actor to the mat.

    Dives leave the buckle on a hit (``actor_after`` is standing or grounded).
    A punch traded on the buckle has no ``actor_after`` and stays put.
    """
    if not m.actor_top or m.skip_hit_roll:
        return False
    if m.actor_after is None or m.actor_after == BodyPosition.TOP_ROPE:
        return False
    return True


def _flatten_sequence_events(seq: PinSequence) -> list[MatchEvent]:
    out = list(seq.preamble_events)
    for step in seq.step_events:
        out.extend(step)
    return out


def apply_move(
    state: MatchState,
    actor_idx: int,
    rule: MoveRule,
    rng: random.Random | None = None,
) -> MoveResult:
    """Mutates state. Returns log, winner, optional pin sequence, and events.

    Unpacks as ``(log, winner, pin_sequence)``. When the pin sequence is not
    ``None``, the UI should play it with timed steps; ``log`` is still the full
    concatenated legacy text for logging/tests. ``events`` feed commentary.
    """
    m = rule.move
    tgt = 1 - actor_idx
    actor = state.wrestlers[actor_idx]
    target = state.wrestlers[tgt]
    lines: list[str] = []
    events: list[MatchEvent] = []

    def emit(kind: str, **kwargs: object) -> None:
        events.append(MatchEvent(kind=kind, **kwargs))  # type: ignore[arg-type]

    if m.is_pin:
        seq, won = _plan_pin(state, actor_idx, rng)
        if actor_idx == 1:
            state.cpu_last_move_id = m.id
        text = pin_sequence_as_text(seq)
        return MoveResult(text, (actor_idx if won else None), seq, _flatten_sequence_events(seq))

    if move_needs_hit_roll(m):
        p = hit_probability(state, actor_idx, rule)
        if _rand_float(rng) >= p:
            miss_lines, miss_events = _resolve_miss(state, actor_idx, rule, rng)
            lines.extend(miss_lines)
            events.extend(miss_events)
            # Whiffed re-ties still feed the collar cycle; ignore returned mom gain
            # because _resolve_miss already handled momentum on the miss path.
            if m.id == "collar_elbow":
                _apply_loop_pressure(state, actor_idx, m, lines, events)
            if actor_idx == 1:
                state.cpu_last_move_id = m.id
            return MoveResult("\n".join(lines), None, None, events)

    if m.is_submission:
        emit("move_attempt", actor=actor_idx, target=tgt, move_id=m.id, move_name=m.name)
        seq, won = _plan_submission(state, actor_idx, rule, rng)
        if actor_idx == 1:
            state.cpu_last_move_id = m.id
        text = pin_sequence_as_text(seq)
        return MoveResult(
            text,
            (actor_idx if won else None),
            seq,
            events + _flatten_sequence_events(seq),
        )

    emit("move_attempt", actor=actor_idx, target=tgt, move_id=m.id, move_name=m.name)

    if m.id == "shake_groggy":
        _clear_groggy(state, actor_idx)
        lines.append(f"  {actor.nickname} steadies themselves — they're back!")
        emit("groggy_cleared", actor=actor_idx, move_id=m.id, move_name=m.name)
        gain = min(5, state.momentum[actor_idx] + m.momentum_gain)
        state.momentum[actor_idx] = gain
        if actor_idx == 1:
            state.cpu_last_move_id = m.id
        text = "\n".join(lines) if lines else f"  {actor.nickname}: {m.name}."
        return MoveResult(text, None, None, events)

    was_groggy_before_hit = state.groggy[tgt]
    pos_before = (state.position[actor_idx], state.position[tgt])

    if m.base_damage > 0:
        top = m.actor_top or m.id.startswith("top_")
        dmg = _damage_with_stats(
            m.base_damage, actor, target, agility_bonus=top or m.actor_running_ropes_only
        )
        if m.id == "grapple_counter" and move_is_stale(state, actor_idx, m):
            dmg = max(1, dmg - 2)
        state.health[tgt] = max(0, state.health[tgt] - dmg)
        lines.append(
            f"  {actor.nickname} snaps off {m.name.lower()} — "
            f"{target.nickname} takes {dmg} damage."
        )
        emit(
            "damage",
            actor=actor_idx,
            target=tgt,
            move_id=m.id,
            move_name=m.name,
            amount=dmg,
            meta={"finisher": m.is_finisher},
        )
        _apply_offensive_hit_surge(state, actor_idx, m, lines, events)
        _clear_groggy_from_opponent_damage(state, tgt, m)
        if m.is_finisher:
            state.finisher_shock[tgt] = min(5, state.finisher_shock[tgt] + 2)
            state.finisher_shock_decay_at[tgt] = (
                state.clock + _FINISHER_SHOCK_DECAY_INTERVAL
            )
        if m.targets_head and not state.bloodied[tgt] and _rand_float(rng) < _BLOODIED_CHANCE:
            state.bloodied[tgt] = True
            lines.append(
                f"  The crowd gasps — {target.nickname} is busted open; blood streams down their face."
            )
            emit("bloodied", actor=actor_idx, target=tgt, move_id=m.id, move_name=m.name)

    if m.actor_after is not None:
        state.position[actor_idx] = m.actor_after
    if m.target_after is not None:
        state.position[tgt] = m.target_after
    if state.position[actor_idx] != pos_before[0]:
        emit(
            "position_change",
            actor=actor_idx,
            move_id=m.id,
            move_name=m.name,
            position=state.position[actor_idx].name,
        )
    if state.position[tgt] != pos_before[1]:
        emit(
            "position_change",
            actor=actor_idx,
            target=tgt,
            move_id=m.id,
            move_name=m.name,
            position=state.position[tgt].name,
        )

    if m.base_damage > 0 and state.health[tgt] <= 0:
        state.position[tgt] = BodyPosition.GROUNDED
        _clear_groggy(state, tgt)
        state.pending_groggy[tgt] = False
        lines.append(f"  {target.nickname} crumples and doesn't move — they are out cold!")
        lines.append(
            f"  *** KNOCKOUT — the match is waved off; {actor.nickname} wins ***"
        )
        emit(
            "knockout",
            actor=actor_idx,
            target=tgt,
            move_id=m.id,
            move_name=m.name,
            won=True,
        )
        if actor_idx == 1:
            state.cpu_last_move_id = m.id
        return MoveResult("\n".join(lines), actor_idx, None, events)

    if m.base_damage > 0 and state.position[tgt] != BodyPosition.GROUNDED:
        worn_down = state.health[tgt] <= target.max_health * _KNOCKDOWN_HP_FRAC
        if worn_down:
            state.position[tgt] = BodyPosition.GROUNDED
            state.pending_groggy[tgt] = True
            state.cover_heat[tgt] = True
            # Flattening them buys timeline as well as position — this is the cover window.
            state.pending_timeline_push[tgt] += _KNOCKDOWN_HEAD_START
            if _COVER_HEAT_PIN_BONUS > state.pin_bonus_next_cover[actor_idx]:
                state.pin_bonus_next_cover[actor_idx] = _COVER_HEAT_PIN_BONUS
            state.finisher_echo_until[actor_idx] = max(
                state.finisher_echo_until[actor_idx],
                state.clock + _FINISHER_ECHO_DURATION,
            )
            lines.append(
                f"  {target.nickname} collapses to the canvas — the cover is there for the taking!"
            )
            emit(
                "knockdown",
                actor=actor_idx,
                target=tgt,
                move_id=m.id,
                move_name=m.name,
                position=BodyPosition.GROUNDED.name,
            )

    if m.base_damage > 0 and (not was_groggy_before_hit or m.causes_groggy_on_stand):
        applied_groggy = _try_apply_groggy_after_damage(
            state, m, tgt, rng, was_groggy_before_hit
        )
        if applied_groggy:
            if m.causes_groggy_on_stand:
                lines.append(
                    f"  {target.nickname} is rattled — when they're forced up, big payoffs may open."
                )
                emit(
                    "groggy_applied",
                    actor=actor_idx,
                    target=tgt,
                    move_id=m.id,
                    move_name=m.name,
                    meta={"pending": True},
                )
            else:
                lines.append(
                    f"  {target.nickname} is GROGGY — power moves and finishers are live!"
                )
                emit(
                    "groggy_applied",
                    actor=actor_idx,
                    target=tgt,
                    move_id=m.id,
                    move_name=m.name,
                )

    if m.id == "desperation_strike":
        _clear_groggy(state, actor_idx)
        lines.append(f"  {actor.nickname} fights through — the groggy haze lifts!")
        emit("groggy_cleared", actor=actor_idx, move_id=m.id, move_name=m.name)

    if m.id == "get_up" and state.position[actor_idx] == BodyPosition.STANDING:
        state.get_up_fail_streak[actor_idx] = 0
        state.finisher_shock[actor_idx] = max(0, state.finisher_shock[actor_idx] - 1)
        state.cover_heat[actor_idx] = False
        if state.pending_groggy[actor_idx]:
            state.pending_groggy[actor_idx] = False
            _apply_standing_groggy(state, actor_idx)
            lines.append(f"  {actor.nickname} rises — still groggy from the impact!")
            emit(
                "groggy_applied",
                actor=actor_idx,
                target=actor_idx,
                move_id=m.id,
                move_name=m.name,
            )

    if m.id == "pickup" and state.position[tgt] == BodyPosition.STANDING:
        if state.pending_groggy[tgt]:
            state.pending_groggy[tgt] = False
            _apply_standing_groggy(state, tgt)
            lines.append(f"  {target.nickname} is yanked up — their legs aren't under them yet!")
            emit(
                "groggy_applied",
                actor=actor_idx,
                target=tgt,
                move_id=m.id,
                move_name=m.name,
            )

    if m.id == "recover":
        heal = max(3, actor.max_health // 25)
        cap = actor.max_health
        state.health[actor_idx] = min(cap, state.health[actor_idx] + heal)
        lines.append(f"  {actor.nickname} recovers {heal} stamina.")
        emit(
            "recover",
            actor=actor_idx,
            move_id=m.id,
            move_name=m.name,
            amount=heal,
        )

    mom_gain = _apply_loop_pressure(state, actor_idx, m, lines, events)

    gain = min(5, state.momentum[actor_idx] + mom_gain)
    state.momentum[actor_idx] = gain
    if m.is_finisher and m.base_damage > 0:
        state.pin_bonus_next_cover[actor_idx] = m.finisher_pin_bonus
        state.finisher_echo_until[actor_idx] = state.clock + _FINISHER_ECHO_DURATION
        if m.triggers_pin_after_hit:
            lines.append("  — FINISHER — the bridge is hooked — pinfall attempt!")
        else:
            lines.append("  — FINISHER — cover them before the echo fades.")
    if actor_idx == 1:
        state.cpu_last_move_id = m.id

    if m.base_damage <= 0 and m.id not in {"recover", "shake_groggy", "desperation_strike"}:
        if not any(e.kind in {"setup", "groggy_applied", "loop_pressure"} for e in events):
            emit("setup", actor=actor_idx, target=tgt, move_id=m.id, move_name=m.name)

    if m.triggers_pin_after_hit and m.base_damage > 0:
        pin_body, won = _plan_pin(state, actor_idx, rng)
        seq = PinSequence(
            won=pin_body.won,
            preamble_lines=list(lines),
            steps=pin_body.steps,
            preamble_events=list(events),
            step_events=list(pin_body.step_events),
        )
        full = pin_sequence_as_text(seq)
        return MoveResult(
            full, (actor_idx if won else None), seq, _flatten_sequence_events(seq)
        )
    text = "\n".join(lines) if lines else f"  {actor.nickname}: {m.name}."
    return MoveResult(text, None, None, events)


def _resolve_miss(
    state: MatchState,
    actor_idx: int,
    rule: MoveRule,
    rng: random.Random | None,
) -> tuple[list[str], list[MatchEvent]]:
    """Failed hit: no target position change, optional chip damage, surge shift.

    Top-rope dives are the exception: the attacker already left the buckle, so a
    miss or reversal dumps them to the canvas.
    """
    m = rule.move
    tgt = 1 - actor_idx
    actor = state.wrestlers[actor_idx]
    target = state.wrestlers[tgt]
    lines: list[str] = []
    events: list[MatchEvent] = []

    if m.id == "get_up":
        state.get_up_fail_streak[actor_idx] = min(
            3, state.get_up_fail_streak[actor_idx] + 1
        )
        state.get_up_fail_decay_at[actor_idx] = (
            state.clock + _GET_UP_FAIL_DECAY_INTERVAL
        )
        events.append(
            MatchEvent(kind="miss", actor=actor_idx, move_id=m.id, move_name=m.name)
        )
        if state.get_up_fail_streak[actor_idx] >= 2:
            state.momentum[actor_idx] = min(5, state.momentum[actor_idx] + 1)
            lines.append(
                f"  {actor.nickname} tries to rise but can't find it — still down and vulnerable, "
                "but the crowd is pulling them up."
            )
            lines.append(f"  Escape momentum builds for {actor.nickname}.")
            return lines, events
        lines.append(
            f"  {actor.nickname} tries to rise but can't find it — still down and vulnerable to a cover!"
        )
        state.momentum[actor_idx] = max(0, state.momentum[actor_idx] - 1)
        return lines, events

    if m.id == "shake_groggy":
        lines.append(
            f"  {actor.nickname} tries to clear their head but they're still wobbly!"
        )
        state.momentum[actor_idx] = max(0, state.momentum[actor_idx] - 1)
        events.append(
            MatchEvent(kind="miss", actor=actor_idx, move_id=m.id, move_name=m.name)
        )
        return lines, events

    if m.id == "desperation_strike":
        lines.append(
            f"  {actor.nickname} lunges wildly but can't connect — still groggy!"
        )
        state.momentum[actor_idx] = max(0, state.momentum[actor_idx] - 1)
        events.append(
            MatchEvent(kind="miss", actor=actor_idx, move_id=m.id, move_name=m.name)
        )
        return lines, events

    if m.base_damage > 0:
        chip = max(1, m.base_damage // 8)
        top = m.actor_top or m.id.startswith("top_")
        dmg = min(
            chip,
            _damage_with_stats(
                chip, actor, target, agility_bonus=top or m.actor_running_ropes_only
            ),
        )
        state.health[tgt] = max(1, state.health[tgt] - dmg)
        _clear_groggy_from_opponent_damage(state, tgt, m)
        events.append(
            MatchEvent(
                kind="reversal",
                actor=actor_idx,
                target=tgt,
                move_id=m.id,
                move_name=m.name,
                amount=dmg,
            )
        )
        if _rand_float(rng) < 0.5:
            lines.append(
                f"  {target.nickname} reverses the {m.name.lower()} — only {dmg} damage, "
                f"and turns the tables!"
            )
        else:
            lines.append(
                f"  {target.nickname} reverses the {m.name.lower()} — only {dmg} damage; "
                f"{actor.nickname} whiffs — {target.nickname} shrugs it off."
            )
        _apply_offensive_miss_surge(state, actor_idx, lines, events)
    else:
        events.append(
            MatchEvent(
                kind="miss",
                actor=actor_idx,
                target=tgt,
                move_id=m.id,
                move_name=m.name,
            )
        )
        if _rand_float(rng) < 0.5:
            lines.append(f"  {target.nickname} turns the tables!")
        else:
            lines.append(f"  {actor.nickname} whiffs — {target.nickname} shrugs it off.")

    if _top_rope_whiff_crashes(m):
        state.position[actor_idx] = BodyPosition.GROUNDED
        lines.append(
            f"  {actor.nickname} crashes off the top rope to the canvas!"
        )
        events.append(
            MatchEvent(
                kind="position_change",
                actor=actor_idx,
                move_id=m.id,
                move_name=m.name,
                position=BodyPosition.GROUNDED.name,
            )
        )

    if m.base_damage <= 0:
        state.momentum[actor_idx] = max(0, state.momentum[actor_idx] - 2)
        state.momentum[tgt] = min(5, state.momentum[tgt] + 1)
    return lines, events


def _plan_pin(state: MatchState, actor_idx: int, rng: random.Random | None) -> tuple[PinSequence, bool]:
    """Resolve pinfall once: build timed steps for the UI; mutate state (momentum, pin bonus)."""
    tgt = 1 - actor_idx
    attacker = state.wrestlers[actor_idx]
    defender = state.wrestlers[tgt]
    steps: list[tuple[list[str], float]] = []
    step_events: list[list[MatchEvent]] = []
    hp_frac = state.health[tgt] / max(1, defender.max_health)
    mom = state.momentum[actor_idx]
    fin_bonus = finisher_echo(state, actor_idx)
    _clear_finisher_echo(state, actor_idx)
    # Seed drama: the first cover of the match near-falls unless they're critically down.
    force_near_fall = (
        state.pins_attempted == 0 and hp_frac > _PIN_NEAR_FALL_FLOOR_HP_FRAC
    )
    state.pins_attempted += 1
    state.cover_heat[tgt] = False

    def add_step(
        step_lines: list[str], delay: float, events: list[MatchEvent]
    ) -> None:
        steps.append((step_lines, delay))
        step_events.append(events)

    if fin_bonus > 0:
        add_step(
            [f"  The finisher still echoes — +{fin_bonus} on the cover!"],
            0.0,
            [
                MatchEvent(
                    kind="setup",
                    actor=actor_idx,
                    target=tgt,
                    move_id="pin",
                    move_name="Pin",
                    amount=fin_bonus,
                    meta={"finisher_echo": True},
                )
            ],
        )

    for count in (1, 2, 3):
        att = (
            attacker.strength
            + _rand_int(rng, 1, 10)
            + mom * 2
            + int((1.0 - hp_frac) * 12)
            + fin_bonus
        )
        defe = defender.endurance + _rand_int(rng, 1, 10) + int(hp_frac * 18)
        kicks_out = att <= defe
        if force_near_fall and count == 2:
            kicks_out = True

        if count == 3:
            if kicks_out:
                # Near-fall: no "3" line — kickout appears after the post-2 delay only.
                kick_lines = [f"  {defender.nickname} kicks out!"]
                kick_events = [
                    MatchEvent(
                        kind="pin_kickout",
                        actor=actor_idx,
                        target=tgt,
                        pin_count=count,
                        won=False,
                    )
                ]
                extra_lines, extra_events = _kickout_surge_followthrough(
                    state, actor_idx, tgt
                )
                kick_lines.extend(extra_lines)
                kick_events.extend(extra_events)
                add_step(kick_lines, 0.0, kick_events)
                state.momentum[actor_idx] = max(0, mom - 2)
                return (
                    PinSequence(
                        won=False,
                        preamble_lines=[],
                        steps=steps,
                        step_events=step_events,
                    ),
                    False,
                )
            add_step(
                [f"  Referee: 3!"],
                0.0,
                [
                    MatchEvent(
                        kind="pin_count",
                        actor=actor_idx,
                        target=tgt,
                        pin_count=3,
                    )
                ],
            )
            break

        line = f"  Referee: {count}…"
        timing = get_config().timing
        delay_after = (
            timing.pin_delay_after_count_1_sec
            if count == 1
            else timing.pin_delay_after_count_2_sec
        )
        add_step(
            [line],
            delay_after,
            [
                MatchEvent(
                    kind="pin_count",
                    actor=actor_idx,
                    target=tgt,
                    pin_count=count,
                )
            ],
        )
        if kicks_out:
            kick_lines = [f"  {defender.nickname} kicks out!"]
            kick_events = [
                MatchEvent(
                    kind="pin_kickout",
                    actor=actor_idx,
                    target=tgt,
                    pin_count=count,
                    won=False,
                )
            ]
            extra_lines, extra_events = _kickout_surge_followthrough(
                state, actor_idx, tgt
            )
            kick_lines.extend(extra_lines)
            kick_events.extend(extra_events)
            add_step(kick_lines, 0.0, kick_events)
            state.momentum[actor_idx] = max(0, mom - 2)
            return (
                PinSequence(
                    won=False, preamble_lines=[], steps=steps, step_events=step_events
                ),
                False,
            )

    add_step(
        [f"  *** PINFALL — {attacker.nickname} wins ***"],
        0.0,
        [
            MatchEvent(
                kind="pinfall",
                actor=actor_idx,
                target=tgt,
                won=True,
            )
        ],
    )
    return (
        PinSequence(won=True, preamble_lines=[], steps=steps, step_events=step_events),
        True,
    )


def _plan_submission(
    state: MatchState,
    actor_idx: int,
    rule: MoveRule,
    rng: random.Random | None,
) -> tuple[PinSequence, bool]:
    """Resolve a submission once: reveal pressure beats, then escape or tap-out."""
    m = rule.move
    tgt = 1 - actor_idx
    attacker = state.wrestlers[actor_idx]
    defender = state.wrestlers[tgt]
    hp_frac = state.health[tgt] / max(1, defender.max_health)
    mom = state.momentum[actor_idx]
    timing = get_config().timing
    steps: list[tuple[list[str], float]] = [
        (
            [
                f"  {attacker.nickname} hooks in {m.name.lower()}!",
                f"  {defender.nickname} reaches for daylight…",
            ],
            timing.pin_delay_after_count_1_sec,
        ),
        (
            [f"  The hold is cinched in deeper!"],
            timing.pin_delay_after_count_2_sec,
        ),
    ]
    step_events: list[list[MatchEvent]] = [
        [
            MatchEvent(
                kind="submission_applied",
                actor=actor_idx,
                target=tgt,
                move_id=m.id,
                move_name=m.name,
            )
        ],
        [
            MatchEvent(
                kind="submission_applied",
                actor=actor_idx,
                target=tgt,
                move_id=m.id,
                move_name=m.name,
                meta={"deeper": True},
            )
        ],
    ]

    pressure = (
        attacker.strength
        + _rand_int(rng, 1, 10)
        + mom * 2
        + int((1.0 - hp_frac) * 18)
        + m.finisher_pin_bonus
    )
    escape = defender.endurance + _rand_int(rng, 1, 10) + int(hp_frac * 22)
    if pressure <= escape:
        steps.append(([f"  {defender.nickname} claws free and breaks the hold!"], 0.0))
        step_events.append(
            [
                MatchEvent(
                    kind="submission_escape",
                    actor=actor_idx,
                    target=tgt,
                    move_id=m.id,
                    move_name=m.name,
                    won=False,
                )
            ]
        )
        state.momentum[actor_idx] = max(0, mom - 2)
        return (
            PinSequence(
                won=False,
                preamble_lines=[],
                steps=steps,
                heading="Submission attempt…",
                step_events=step_events,
            ),
            False,
        )

    steps.append(
        (
            [
                f"  {defender.nickname} taps out!",
                f"  *** SUBMISSION — {attacker.nickname} wins ***",
            ],
            0.0,
        )
    )
    step_events.append(
        [
            MatchEvent(
                kind="submission_tap",
                actor=actor_idx,
                target=tgt,
                move_id=m.id,
                move_name=m.name,
                won=True,
            )
        ]
    )
    return (
        PinSequence(
            won=True,
            preamble_lines=[],
            steps=steps,
            heading="Submission attempt…",
            step_events=step_events,
        ),
        True,
    )


_CPU_VARIETY_PENALTY = 18.0

# Softmax temperature for CPU move choice: higher → more exploration, lower → greedier.
# Scaled for heuristic scores roughly in ~0–150.
_CPU_SOFTMAX_TEMPERATURE = 10.0

# Score-per-tempo is renormalised against a typical move cost so the softmax temperature
# above keeps meaning what it meant when every move cost exactly one turn.
_CPU_TEMPO_REFERENCE_COST = 1.5
# Charged per opponent action conceded while the CPU is recovering.
_CPU_CONCESSION_PENALTY = 14.0


def _cpu_rule_score(state: MatchState, cpu_idx: int, r: MoveRule) -> float:
    """Deterministic preference score for a legal CPU move (softmax input)."""
    m = r.move
    opp = 1 - cpu_idx
    opp_hp = state.health[opp] / max(1, state.wrestlers[opp].max_health)

    if m.is_submission:
        p = hit_probability(state, cpu_idx, r)
        s = 25.0
        if opp_hp < 0.45:
            s += 75
        if opp_hp >= 0.45:
            s -= 25
        s += float(m.finisher_pin_bonus) * 2.5
        return p * s

    if m.is_pin:
        s = 0.0
        fin_echo = finisher_echo(state, cpu_idx)
        if opp_hp < 0.35:
            s += 80
        elif fin_echo > 0:
            s += 25
        else:
            s -= 40
        s += float(fin_echo) * 3.0
        if fin_echo > 0:
            s += _FINISHER_COVER_PIN_SCORE_BONUS
        if state.cover_heat[opp]:
            s += 120
        if state.position[opp] == BodyPosition.GROUNDED and opp_hp < 0.30:
            s += 35
        return s

    if move_needs_hit_roll(m):
        p = hit_probability(state, cpu_idx, r)
        ev_damage = p * float(m.base_damage)
        s = ev_damage + p * m.momentum_gain * 1.5
    else:
        s = float(m.base_damage) + m.momentum_gain * 1.5

    # Prefer the cover tease over murdering a grounded, worn opponent.
    if state.position[opp] == BodyPosition.GROUNDED and (
        state.cover_heat[opp] or opp_hp < 0.25 or finisher_echo(state, cpu_idx) > 0
    ):
        if m.base_damage > 0:
            s -= 55.0
        if m.is_finisher:
            s -= 25.0

    if m.actor_top and m.target_grounded:
        s += 24
    if m.actor_top and m.target_top:
        s += 28
    if m.actor_running_ropes_only:
        s += 10
    if m.target_running_ropes:
        s += 12
    if m.id == "dismount_top":
        s -= 5
        s -= float(state.setup_loop_pressure[cpu_idx]) * 10.0
    if m.id == "climb":
        s -= float(state.setup_loop_pressure[cpu_idx]) * 16.0
    if m.id == "collar_elbow":
        s -= float(state.grapple_loop_pressure[cpu_idx]) * 24.0
    if m.target_grappled:
        s += 12.0
    if m.id == "recover":
        hp_frac = state.health[cpu_idx] / max(1, state.wrestlers[cpu_idx].max_health)
        if hp_frac > 0.8:
            s -= 80
        elif hp_frac > 0.6:
            s -= 45
        else:
            s += (1.0 - hp_frac) * 25.0
    if m.id == "get_up":
        s += 100
    if m.id == "shake_groggy":
        s += 100
    if m.id == "desperation_strike":
        s += 45
    if m.id == "escape_corner":
        s += 100
    if m.id == "break_grapple":
        s += 65
        s += float(state.counter_loop_pressure[cpu_idx]) * 8.0
    if m.id == "grapple_counter":
        s += 90
        s -= float(state.counter_loop_pressure[cpu_idx]) * 28.0
    if state.cpu_last_move_id is not None and m.id == state.cpu_last_move_id:
        s -= _CPU_VARIETY_PENALTY
    if m.is_finisher:
        s += float(m.base_damage) * 0.35 + float(m.finisher_pin_bonus)
        if opp_hp < 0.45:
            s += 25
    if m.triggers_pin_after_hit:
        s += 40.0 if opp_hp < 0.38 else 12.0
    return s


def _tempo_adjusted_score(
    state: MatchState,
    cpu_idx: int,
    rule: MoveRule,
    queue: TurnQueue | None,
) -> float:
    """Raw preference converted into value per unit of recovery, minus what it concedes.

    A one-ply scorer that counts actions is blind to the decision the turn queue is
    actually about: a move worth 60 that leaves the opponent two free actions is usually
    worse than a move worth 40 that gets the CPU back on the clock first.
    """
    raw = _cpu_rule_score(state, cpu_idx, rule)
    cost = move_tempo_cost(rule.move)
    score = raw / max(cost, 0.1) * _CPU_TEMPO_REFERENCE_COST

    if queue is None:
        return score

    speeds = actor_speeds(state)
    defaults = projection_costs(state)
    conceded = opponent_actions_conceded(
        queue, speeds, defaults, actor_idx=cpu_idx, chosen_cost=cost
    )
    if conceded:
        opp = 1 - cpu_idx
        # Handing over the initiative matters more the healthier the opponent still is.
        opp_hp = state.health[opp] / max(1, state.wrestlers[opp].max_health)
        score -= conceded * _CPU_CONCESSION_PENALTY * (0.5 + 0.5 * opp_hp)
    return score


def _softmax_sample_index(scores: list[float], temperature: float) -> int:
    """Sample an index with probabilities ∝ softmax(scores / temperature)."""
    if not scores:
        raise ValueError("scores must be non-empty")
    if temperature <= 0:
        return max(range(len(scores)), key=lambda i: scores[i])
    m = max(scores)
    exps = [math.exp((s - m) / temperature) for s in scores]
    total = sum(exps)
    probs = [e / total for e in exps]
    u = random.random()
    c = 0.0
    for i, p in enumerate(probs):
        c += p
        if u <= c:
            return i
    return len(scores) - 1


def cpu_choose_rule(
    state: MatchState, cpu_idx: int, queue: TurnQueue | None = None
) -> MoveRule:
    """Pick the CPU's move. Pass the live ``queue`` so tempo concessions are priced in."""
    options = state.valid_rules(cpu_idx)
    if not options:
        raise RuntimeError("CPU has no valid moves — state bug.")
    _, rules = zip(*options)
    rules_list = list(rules)
    opp = 1 - cpu_idx
    # Cash cover heat: usually take the pin when it's legal instead of softmaxing into a KO.
    if state.cover_heat[opp]:
        pin_rules = [r for r in rules_list if r.move.is_pin]
        if pin_rules and random.random() < _COVER_HEAT_CPU_PIN_BIAS:
            return pin_rules[0]
    # The finisher echo is a race against the clock, so cover even when a kickout is likely.
    if finisher_echo(state, cpu_idx) > 0:
        pin_rules = [r for r in rules_list if r.move.is_pin]
        if pin_rules and random.random() < _FINISHER_COVER_CPU_PIN_BIAS:
            return pin_rules[0]
    scores = [_tempo_adjusted_score(state, cpu_idx, r, queue) for r in rules_list]
    idx = _softmax_sample_index(scores, _CPU_SOFTMAX_TEMPERATURE)
    return rules_list[idx]


def outcome_label(log: str) -> str:
    """Short label derived from apply_move / pin log text for exchange recap."""
    if not log.strip():
        return "—"
    if "KNOCKOUT" in log:
        return "knockout"
    if "SUBMISSION" in log or "taps out" in log:
        return "submission"
    if "PINFALL" in log or "pinfall" in log.lower():
        return "pinfall"
    if "kicks out" in log:
        return "kickout"
    if "Referee:" in log:
        return "pin"
    if "still on the mat" in log:
        return "miss"
    if "reverses" in log or "whiffs" in log:
        return "miss"
    if "deals" in log or "takes" in log:
        return "hit"
    if "recovers" in log:
        return "recover"
    return "ok"
