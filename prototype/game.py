"""Match flow: positions, rebound, damage, and pinfall resolution."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from moves import BodyPosition, Move, MoveRule, all_move_rules, move_valid
from wrestlers import Wrestler

# Hit probability: p = clamp(BASE + k_mom*momentum - k_diff*difficulty + ... , P_MIN, P_MAX)
# Tuned so high-difficulty moves fail more at low momentum / healthy defender — but clean hits
# stay common enough that reversals/whiffs don't dominate the match.
_HIT_BASE = 0.66
_HIT_K_MOMENTUM = 0.065
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
_GET_UP_BASE_BONUS = 0.06  # small edge vs strikes; beatdown / finisher shock do most of the work
_GET_UP_BEATDOWN_PENALTY = 0.42  # multiplied by (1 - HP fraction); worse when badly hurt
_GET_UP_FINISH_SHOCK_K = 0.072  # per stack; stacks when you eat a finisher's damage

# Rare easter egg: successful head-targeting hit may blood the defender for the rest of the match
_BLOODIED_CHANCE = 0.018

# Groggy procs on qualifying hits (separate rolls for strikes vs. slams / pending-on-stand)
_GROGGY_STANDING_CHANCE = 0.42  # punch / kick — immediate standing groggy
_GROGGY_ON_STAND_CHANCE = 0.48  # slams & finishers — pending until they stand


@dataclass
class MatchState:
    wrestlers: tuple[Wrestler, Wrestler]
    health: list[int] = field(default_factory=list)
    position: list[BodyPosition] = field(default_factory=list)
    rebound: list[bool] = field(default_factory=list)
    momentum: list[int] = field(default_factory=list)
    bloodied: list[bool] = field(default_factory=list)
    rules: list[MoveRule] = field(default_factory=all_move_rules)
    cpu_last_move_id: str | None = None
    # Set when a finisher lands; added to each count on the attacker's next pin attempt, then cleared.
    pin_bonus_next_cover: list[int] = field(default_factory=list)
    # Taking finisher damage adds stacks; makes get_up harder until you shake it off (successful stand).
    finisher_shock: list[int] = field(default_factory=list)
    # Standing wobbly — cleared by opponent damage, timer, shake-off, or desperation strike.
    groggy: list[bool] = field(default_factory=list)
    # When groggy[v]: opponent (1-v) has this many actions before auto-clear (starts at 2).
    groggy_opponent_actions_left: list[int] = field(default_factory=list)
    # After certain slams/finishers while grounded; applies groggy when victim next stands (get_up or pickup).
    pending_groggy: list[bool] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.health:
            self.health = [w.max_health for w in self.wrestlers]
        if not self.position:
            self.position = [BodyPosition.STANDING, BodyPosition.STANDING]
        if not self.rebound:
            self.rebound = [False, False]
        if not self.momentum:
            self.momentum = [0, 0]
        if not self.bloodied:
            self.bloodied = [False, False]
        if not self.pin_bonus_next_cover:
            self.pin_bonus_next_cover = [0, 0]
        if not self.finisher_shock:
            self.finisher_shock = [0, 0]
        if not self.groggy:
            self.groggy = [False, False]
        if not self.groggy_opponent_actions_left:
            self.groggy_opponent_actions_left = [0, 0]
        if not self.pending_groggy:
            self.pending_groggy = [False, False]

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
                self.rebound[actor_idx],
                self.momentum[actor_idx],
                actor_groggy=self.groggy[actor_idx],
            ):
                out.append((i, rule))
        return out


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


def hit_probability(state: MatchState, actor_idx: int, rule: MoveRule) -> float:
    """Deterministic P(land) for the current snapshot — shared by runtime roll and CPU EV."""
    m = rule.move
    tgt = 1 - actor_idx
    actor = state.wrestlers[actor_idx]
    target = state.wrestlers[tgt]
    mom = state.momentum[actor_idx]
    att_hp = state.health[actor_idx] / max(1, actor.max_health)
    def_hp = state.health[tgt] / max(1, target.max_health)
    diff = m.difficulty
    agi_gap = (target.agility - actor.agility) / 10.0
    p = (
        _HIT_BASE
        + _HIT_K_MOMENTUM * mom
        - _HIT_K_DIFFICULTY * diff
        + _HIT_K_ATTACKER_HP * att_hp
        - _HIT_K_DEFENDER_HP * def_hp
        - _HIT_K_AGILITY_GAP * agi_gap
    )
    if m.id == "get_up" or m.id == "shake_groggy":
        p += _GET_UP_BASE_BONUS
        p -= _GET_UP_BEATDOWN_PENALTY * (1.0 - att_hp)
        p -= _GET_UP_FINISH_SHOCK_K * float(state.finisher_shock[actor_idx])
    if m.is_finisher:
        p += _FINISHER_HIT_BONUS_MAX * _finisher_wear_fraction(state)
    return max(_HIT_P_MIN, min(_HIT_P_MAX, p))


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


def _tick_groggy_timer(
    state: MatchState,
    actor_idx: int,
    *,
    skip_victim_tick: int | None = None,
) -> None:
    """After each completed action by `actor_idx`, count down groggy timer for victims they can exploit.

    ``skip_victim_tick`` is the victim index when this same action just applied *immediate* standing
    groggy (the stun move itself must not consume the first timer action).
    """
    for v in (0, 1):
        if not state.groggy[v]:
            continue
        if actor_idx != 1 - v:
            continue
        if skip_victim_tick is not None and v == skip_victim_tick:
            continue
        state.groggy_opponent_actions_left[v] -= 1
        if state.groggy_opponent_actions_left[v] <= 0:
            state.groggy[v] = False
            state.groggy_opponent_actions_left[v] = 0


def _clear_groggy_from_opponent_damage(state: MatchState, victim_idx: int, m: Move) -> None:
    """Any damaging offensive move from the opponent clears groggy (desperation strike exempted for victim)."""
    if m.id == "desperation_strike":
        return
    if m.base_damage > 0 and state.groggy[victim_idx]:
        state.groggy[victim_idx] = False
        state.groggy_opponent_actions_left[victim_idx] = 0


def _try_apply_groggy_after_damage(
    state: MatchState, m: Move, tgt: int, rng: random.Random | None
) -> bool:
    """Maybe apply groggy from a successful damaging hit (caller ensures victim was not groggy before this hit)."""
    if m.causes_groggy_on_stand:
        if _rand_float(rng) >= _GROGGY_ON_STAND_CHANCE:
            return False
        state.pending_groggy[tgt] = True
        return True
    if m.causes_groggy and state.position[tgt] == BodyPosition.STANDING:
        if _rand_float(rng) >= _GROGGY_STANDING_CHANCE:
            return False
        state.groggy[tgt] = True
        state.groggy_opponent_actions_left[tgt] = 2
        return True
    return False


def apply_move(
    state: MatchState,
    actor_idx: int,
    rule: MoveRule,
    rng: random.Random | None = None,
) -> tuple[str, int | None]:
    """Mutates state. Returns (narrative, winner_index) — winner set only on 3-count."""
    m = rule.move
    tgt = 1 - actor_idx
    actor = state.wrestlers[actor_idx]
    target = state.wrestlers[tgt]
    lines: list[str] = []

    if m.is_pin:
        pin_text, won = _resolve_pin(state, actor_idx, rng)
        lines.append(pin_text)
        if actor_idx == 1:
            state.cpu_last_move_id = m.id
        _tick_groggy_timer(state, actor_idx)
        return "\n".join(lines), (actor_idx if won else None)

    if move_needs_hit_roll(m):
        p = hit_probability(state, actor_idx, rule)
        if _rand_float(rng) >= p:
            lines.extend(_resolve_miss(state, actor_idx, rule, rng))
            if actor_idx == 1:
                state.cpu_last_move_id = m.id
            _tick_groggy_timer(state, actor_idx)
            return "\n".join(lines), None

    if m.id == "shake_groggy":
        state.groggy[actor_idx] = False
        state.groggy_opponent_actions_left[actor_idx] = 0
        lines.append(f"  {actor.nickname} steadies themselves — they're back!")
        gain = min(5, state.momentum[actor_idx] + m.momentum_gain)
        state.momentum[actor_idx] = gain
        if actor_idx == 1:
            state.cpu_last_move_id = m.id
        _tick_groggy_timer(state, actor_idx)
        text = "\n".join(lines) if lines else f"  {actor.nickname}: {m.name}."
        return text, None

    was_groggy_before_hit = state.groggy[tgt]

    if m.grants_rebound:
        state.rebound[actor_idx] = True

    if m.base_damage > 0:
        top = m.actor_top or m.id.startswith("top_")
        dmg = _damage_with_stats(
            m.base_damage, actor, target, agility_bonus=top or m.actor_rebound or m.actor_running_ropes_only
        )
        state.health[tgt] = max(1, state.health[tgt] - dmg)
        lines.append(f"  {actor.nickname} deals {dmg} damage with {m.name.lower()}.")
        _clear_groggy_from_opponent_damage(state, tgt, m)
        if m.is_finisher:
            state.finisher_shock[tgt] = min(5, state.finisher_shock[tgt] + 2)
        if m.targets_head and not state.bloodied[tgt] and _rand_float(rng) < _BLOODIED_CHANCE:
            state.bloodied[tgt] = True
            lines.append(
                f"  The crowd gasps — {target.nickname} is busted open; blood streams down their face."
            )

    if m.actor_after is not None:
        state.position[actor_idx] = m.actor_after
    if m.target_after is not None:
        state.position[tgt] = m.target_after

    if m.base_damage > 0 and not was_groggy_before_hit:
        _try_apply_groggy_after_damage(state, m, tgt, rng)

    if m.id == "desperation_strike":
        state.groggy[actor_idx] = False
        state.groggy_opponent_actions_left[actor_idx] = 0
        lines.append(f"  {actor.nickname} fights through — the groggy haze lifts!")

    immediate_groggy_from_stand_victim: int | None = None
    if m.id == "get_up" and state.position[actor_idx] == BodyPosition.STANDING:
        state.finisher_shock[actor_idx] = max(0, state.finisher_shock[actor_idx] - 1)
        if state.pending_groggy[actor_idx]:
            state.pending_groggy[actor_idx] = False
            state.groggy[actor_idx] = True
            state.groggy_opponent_actions_left[actor_idx] = 2
            immediate_groggy_from_stand_victim = actor_idx
            lines.append(f"  {actor.nickname} rises — still groggy from the impact!")

    if m.id == "pickup" and state.position[tgt] == BodyPosition.STANDING:
        if state.pending_groggy[tgt]:
            state.pending_groggy[tgt] = False
            state.groggy[tgt] = True
            state.groggy_opponent_actions_left[tgt] = 2
            immediate_groggy_from_stand_victim = tgt
            lines.append(f"  {target.nickname} is yanked up — their legs aren't under them yet!")

    if m.id == "recover":
        heal = max(3, actor.max_health // 25)
        cap = actor.max_health
        state.health[actor_idx] = min(cap, state.health[actor_idx] + heal)
        lines.append(f"  {actor.nickname} recovers {heal} stamina.")

    if m.actor_rebound:
        state.rebound[actor_idx] = False

    gain = min(5, state.momentum[actor_idx] + m.momentum_gain)
    state.momentum[actor_idx] = gain
    if m.is_finisher and m.base_damage > 0:
        state.pin_bonus_next_cover[actor_idx] = m.finisher_pin_bonus
        if m.triggers_pin_after_hit:
            lines.append("  — FINISHER — the bridge is hooked — pinfall attempt!")
        else:
            lines.append("  — FINISHER — the next cover packs extra heat.")
    if actor_idx == 1:
        state.cpu_last_move_id = m.id

    skip_victim_tick = immediate_groggy_from_stand_victim
    if skip_victim_tick is None:
        if (
            m.base_damage > 0
            and not was_groggy_before_hit
            and m.causes_groggy
            and not m.causes_groggy_on_stand
            and state.groggy[tgt]
        ):
            skip_victim_tick = tgt

    if m.triggers_pin_after_hit and m.base_damage > 0:
        pin_text, won = _resolve_pin(state, actor_idx, rng)
        lines.append(pin_text)
        _tick_groggy_timer(state, actor_idx, skip_victim_tick=skip_victim_tick)
        return "\n".join(lines), (actor_idx if won else None)
    text = "\n".join(lines) if lines else f"  {actor.nickname}: {m.name}."
    _tick_groggy_timer(state, actor_idx, skip_victim_tick=skip_victim_tick)
    return text, None


def _resolve_miss(
    state: MatchState,
    actor_idx: int,
    rule: MoveRule,
    rng: random.Random | None,
) -> list[str]:
    """Failed hit: no position change, optional chip damage, momentum shift, consume rebound."""
    m = rule.move
    tgt = 1 - actor_idx
    actor = state.wrestlers[actor_idx]
    target = state.wrestlers[tgt]
    lines: list[str] = []

    if m.id == "get_up":
        lines.append(
            f"  {actor.nickname} tries to rise but can't find it — still on the mat!"
        )
        state.momentum[actor_idx] = max(0, state.momentum[actor_idx] - 1)
        return lines

    if m.id == "shake_groggy":
        lines.append(
            f"  {actor.nickname} tries to clear their head but they're still wobbly!"
        )
        state.momentum[actor_idx] = max(0, state.momentum[actor_idx] - 1)
        return lines

    if m.id == "desperation_strike":
        lines.append(
            f"  {actor.nickname} lunges wildly but can't connect — still groggy!"
        )
        state.momentum[actor_idx] = max(0, state.momentum[actor_idx] - 1)
        return lines

    if m.actor_rebound:
        state.rebound[actor_idx] = False

    if m.base_damage > 0:
        chip = max(1, m.base_damage // 8)
        top = m.actor_top or m.id.startswith("top_")
        dmg = min(
            chip,
            _damage_with_stats(
                chip, actor, target, agility_bonus=top or m.actor_rebound or m.actor_running_ropes_only
            ),
        )
        state.health[tgt] = max(1, state.health[tgt] - dmg)
        lines.append(f"  {target.nickname} reverses the {m.name.lower()} — only {dmg} damage.")
        _clear_groggy_from_opponent_damage(state, tgt, m)

    if _rand_float(rng) < 0.5:
        lines.append(f"  {target.nickname} turns the tables!")
    else:
        lines.append(f"  {actor.nickname} whiffs — {target.nickname} shrugs it off.")

    state.momentum[actor_idx] = max(0, state.momentum[actor_idx] - 2)
    state.momentum[tgt] = min(5, state.momentum[tgt] + 1)
    return lines


def _resolve_pin(state: MatchState, actor_idx: int, rng: random.Random | None) -> tuple[str, bool]:
    tgt = 1 - actor_idx
    attacker = state.wrestlers[actor_idx]
    defender = state.wrestlers[tgt]
    lines: list[str] = []
    hp_frac = state.health[tgt] / max(1, defender.max_health)
    mom = state.momentum[actor_idx]
    fin_bonus = state.pin_bonus_next_cover[actor_idx]
    state.pin_bonus_next_cover[actor_idx] = 0
    if fin_bonus > 0:
        lines.append(f"  The finisher still echoes — +{fin_bonus} on the cover!")

    for count in (1, 2, 3):
        att = (
            attacker.strength
            + _rand_int(rng, 1, 10)
            + mom * 2
            + int((1.0 - hp_frac) * 12)
            + fin_bonus
        )
        defe = defender.endurance + _rand_int(rng, 1, 10) + int(hp_frac * 18)
        lines.append(f"  Referee: {count}…")
        if att <= defe:
            lines.append(f"  {defender.nickname} kicks out!")
            state.momentum[actor_idx] = max(0, mom - 2)
            return "\n".join(lines), False

    lines.append(f"  *** PINFALL — {attacker.nickname} wins ***")
    return "\n".join(lines), True


_CPU_VARIETY_PENALTY = 18.0

# Softmax temperature for CPU move choice: higher → more exploration, lower → greedier.
# Scaled for heuristic scores roughly in ~0–150.
_CPU_SOFTMAX_TEMPERATURE = 10.0


def _cpu_rule_score(state: MatchState, cpu_idx: int, r: MoveRule) -> float:
    """Deterministic preference score for a legal CPU move (softmax input)."""
    m = r.move
    opp = 1 - cpu_idx
    opp_hp = state.health[opp] / max(1, state.wrestlers[opp].max_health)

    if m.is_pin:
        s = 0.0
        if opp_hp < 0.35:
            s += 80
        if opp_hp >= 0.35:
            s -= 40
        s += float(state.pin_bonus_next_cover[cpu_idx]) * 3.0
        return s

    if move_needs_hit_roll(m):
        p = hit_probability(state, cpu_idx, r)
        ev_damage = p * float(m.base_damage)
        s = ev_damage + p * m.momentum_gain * 1.5
    else:
        s = float(m.base_damage) + m.momentum_gain * 1.5

    if m.actor_top and m.target_grounded:
        s += 15
    if m.actor_rebound:
        s += 6
    if m.id == "dismount_top":
        s -= 5
    if m.id == "recover" and state.health[cpu_idx] > state.wrestlers[cpu_idx].max_health * 0.6:
        s -= 10
    if m.id == "get_up":
        s += 100
    if m.id == "shake_groggy":
        s += 100
    if m.id == "desperation_strike":
        s += 45
    if m.id == "escape_corner":
        s += 100
    if state.cpu_last_move_id is not None and m.id == state.cpu_last_move_id:
        s -= _CPU_VARIETY_PENALTY
    if m.is_finisher:
        s += float(m.base_damage) * 0.35 + float(m.finisher_pin_bonus)
        if opp_hp < 0.45:
            s += 25
    if m.triggers_pin_after_hit:
        s += 40.0 if opp_hp < 0.38 else 12.0
    return s


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


def cpu_choose_rule(state: MatchState, cpu_idx: int) -> MoveRule:
    options = state.valid_rules(cpu_idx)
    if not options:
        raise RuntimeError("CPU has no valid moves — state bug.")
    _, rules = zip(*options)
    rules_list = list(rules)
    scores = [_cpu_rule_score(state, cpu_idx, r) for r in rules_list]
    idx = _softmax_sample_index(scores, _CPU_SOFTMAX_TEMPERATURE)
    return rules_list[idx]


def outcome_label(log: str) -> str:
    """Short label derived from apply_move / pin log text for exchange recap."""
    if not log.strip():
        return "—"
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
    if "deals" in log:
        return "hit"
    if "recovers" in log:
        return "recover"
    return "ok"


def format_exchange_summary(player_move: str, player_log: str, cpu_move: str, cpu_log: str) -> str:
    """Single line: your move/outcome, then CPU move/outcome."""
    return (
        f"You: {player_move} — {outcome_label(player_log)} · "
        f"CPU: {cpu_move} — {outcome_label(cpu_log)}"
    )


def format_exchange_summary_after_player(player_move: str, player_log: str) -> str:
    """Recap after your move only; opponent line cleared until CPU acts."""
    return f"You: {player_move} — {outcome_label(player_log)} · CPU: —"
