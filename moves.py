"""Move definitions: position gates, damage, and post-move ring state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from wrestlers import Wrestler


class BodyPosition(Enum):
    STANDING = "standing"
    RUNNING_ROPES = "running_ropes"
    GROUNDED = "grounded"
    CORNER = "cornered"
    TOP_ROPE = "top_rope"


@dataclass(frozen=True)
class Move:
    id: str
    name: str
    description: str
    # Actor position required
    actor_standing: bool = True
    actor_top: bool = False
    actor_rebound: bool = False
    actor_grounded_only: bool = False  # e.g. kick out / stand up
    actor_corner_only: bool = False  # fight out of turnbuckles
    # Target position required
    target_standing: bool | None = None  # None = any
    target_grounded: bool | None = None
    target_corner: bool | None = None
    target_top: bool | None = None  # True => opponent on top rope
    target_running_ropes: bool | None = None  # True => opponent is running the ropes
    # Effects
    base_damage: int = 0
    is_pin: bool = False
    # After move: where actor ends (if not specified, stays standing)
    actor_after: BodyPosition | None = None
    target_after: BodyPosition | None = None
    # Sets rebound for actor's NEXT offensive action (then consumed)
    grants_rebound: bool = False
    # Climb — only from standing, ends on top rope
    is_climb: bool = False
    # Hit the ropes — only from standing, ends running the ropes
    is_hit_ropes: bool = False
    # Actor must be running the ropes (return trip / rope sprint)
    actor_running_ropes_only: bool = False
    momentum_gain: int = 0
    # Stochastic resolution (1–5): higher = harder to land when momentum is low
    difficulty: int = 3
    # If True, move always resolves (no hit roll); pins use separate pin logic
    skip_hit_roll: bool = False
    # Head-targeting strikes (easter egg: rare "bloodied" state on successful hit)
    targets_head: bool = False


def _always(_a: Wrestler, _t: Wrestler) -> bool:
    return True


# Predicate: (actor, target) -> extra validation
MovePredicate = Callable[[Wrestler, Wrestler], bool]


@dataclass(frozen=True)
class MoveRule:
    move: Move
    extra: MovePredicate = _always


def all_move_rules() -> list[MoveRule]:
    return [
        MoveRule(
            Move(
                id="lock_up",
                name="Collar-and-elbow lock-up",
                description="Classic tie-up; shove into the corner.",
                target_standing=True,
                base_damage=4,
                target_after=BodyPosition.CORNER,
                momentum_gain=1,
                difficulty=1,
            )
        ),
        MoveRule(
            Move(
                id="punch",
                name="Straight right",
                description="A stiff shot to the jaw.",
                target_standing=True,
                base_damage=6,
                momentum_gain=1,
                difficulty=2,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="kick",
                name="Roundhouse kick",
                description="Spins through — risky but sharp.",
                target_standing=True,
                base_damage=8,
                momentum_gain=1,
                difficulty=3,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="irish_whip",
                name="Irish whip",
                description="Send them flying — they're running the ropes on the return.",
                target_standing=True,
                base_damage=3,
                target_after=BodyPosition.RUNNING_ROPES,
                momentum_gain=2,
                difficulty=2,
            )
        ),
        MoveRule(
            Move(
                id="hit_the_ropes",
                name="Hit the ropes",
                description="Bounce off and build steam — you're running the ropes.",
                actor_standing=True,
                is_hit_ropes=True,
                base_damage=0,
                actor_after=BodyPosition.RUNNING_ROPES,
                momentum_gain=0,
                skip_hit_roll=True,
            )
        ),
        MoveRule(
            Move(
                id="feet_plant",
                name="Kill the run",
                description="Grab the ropes and stop — back to your feet in the center.",
                actor_running_ropes_only=True,
                actor_standing=False,
                base_damage=0,
                actor_after=BodyPosition.STANDING,
                momentum_gain=0,
            )
        ),
        MoveRule(
            Move(
                id="corner_strikes",
                name="Corner mudhole stomps",
                description="Trapped in the turnbuckles — boots and forearms.",
                target_corner=True,
                base_damage=10,
                momentum_gain=2,
                difficulty=3,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="drag_to_center",
                name="Slingshot to center",
                description="Drag them out of the corner — neutral standing in the ring.",
                target_corner=True,
                base_damage=3,
                target_after=BodyPosition.STANDING,
                momentum_gain=1,
                difficulty=1,
            )
        ),
        MoveRule(
            Move(
                id="pull_off_top",
                name="Pull off the top rope",
                description="Yank them down from the buckle — both feet on the mat.",
                target_top=True,
                base_damage=5,
                target_after=BodyPosition.STANDING,
                momentum_gain=2,
                difficulty=2,
            )
        ),
        MoveRule(
            Move(
                id="bulldog",
                name="Running bulldog",
                description="Face-first driver out of the corner.",
                target_corner=True,
                base_damage=14,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=3,
                difficulty=4,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="body_slam",
                name="Body slam",
                description="Hoist and slam — canvas shakes.",
                target_standing=True,
                base_damage=12,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=2,
                difficulty=4,
            )
        ),
        MoveRule(
            Move(
                id="suplex",
                name="Vertical suplex",
                description="Arching throw — authority.",
                target_standing=True,
                base_damage=15,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=3,
                difficulty=5,
            )
        ),
        MoveRule(
            Move(
                id="rope_rebound_clothesline",
                name="Rebound clothesline",
                description="Catch them on the return — lariat as they come off the ropes.",
                target_running_ropes=True,
                base_damage=16,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=3,
                difficulty=5,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="kitchen_sink_knee",
                name="Kitchen-sink knee",
                description="They're running straight at you — drive a knee into the jaw.",
                target_running_ropes=True,
                base_damage=14,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=3,
                difficulty=4,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="drop_toe_hold",
                name="Drop toe hold",
                description="Trip them mid-sprint — they eat canvas.",
                target_running_ropes=True,
                base_damage=11,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=2,
                difficulty=3,
            )
        ),
        MoveRule(
            Move(
                id="rope_rebound_elbow",
                name="Rope-spring elbow drop",
                description="You hit the ropes; they don't — elbow across a downed foe.",
                actor_running_ropes_only=True,
                actor_standing=False,
                target_grounded=True,
                base_damage=14,
                actor_after=BodyPosition.STANDING,
                momentum_gain=2,
                difficulty=4,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="springboard_crossbody",
                name="Springboard crossbody",
                description="Full sprint — you leave your feet and flatten them.",
                actor_running_ropes_only=True,
                actor_standing=False,
                target_standing=True,
                base_damage=17,
                actor_after=BodyPosition.STANDING,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=3,
                difficulty=4,
            )
        ),
        MoveRule(
            Move(
                id="rope_dropkick",
                name="Running dropkick",
                description="Both boots to the chest off the ropes — textbook.",
                actor_running_ropes_only=True,
                actor_standing=False,
                target_standing=True,
                base_damage=15,
                actor_after=BodyPosition.STANDING,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=3,
                difficulty=4,
            )
        ),
        MoveRule(
            Move(
                id="spinning_heel_running",
                name="Spinning heel kick",
                description="Pivot off the run — heel to the temple.",
                actor_running_ropes_only=True,
                actor_standing=False,
                target_standing=True,
                base_damage=14,
                actor_after=BodyPosition.STANDING,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=3,
                difficulty=4,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="rope_collision",
                name="Collision course",
                description="Two freight trains — you both chose violence. The ring shakes.",
                actor_running_ropes_only=True,
                actor_standing=False,
                target_running_ropes=True,
                base_damage=12,
                actor_after=BodyPosition.GROUNDED,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=2,
                difficulty=3,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="climb",
                name="Climb to the top rope",
                description="Scale the buckle — high risk, high reward next turn.",
                actor_standing=True,
                is_climb=True,
                base_damage=0,
                actor_after=BodyPosition.TOP_ROPE,
                momentum_gain=2,
                skip_hit_roll=True,
            )
        ),
        MoveRule(
            Move(
                id="dismount_top",
                name="Climb down carefully",
                description="Opponent won't stay down — reset to the canvas.",
                actor_top=True,
                actor_standing=False,
                base_damage=0,
                actor_after=BodyPosition.STANDING,
                momentum_gain=0,
                skip_hit_roll=True,
            )
        ),
        MoveRule(
            Move(
                id="top_splash",
                name="Flying splash",
                description="From the top — all your weight across their chest.",
                actor_top=True,
                actor_standing=False,
                target_grounded=True,
                base_damage=22,
                actor_after=BodyPosition.STANDING,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=4,
                difficulty=5,
            )
        ),
        MoveRule(
            Move(
                id="top_elbow",
                name="Diving elbow drop",
                description="Elbow driven from the heavens.",
                actor_top=True,
                actor_standing=False,
                target_grounded=True,
                base_damage=20,
                actor_after=BodyPosition.STANDING,
                target_after=BodyPosition.GROUNDED,
                momentum_gain=4,
                difficulty=5,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="elbow_drop",
                name="Elbow drop",
                description="Standard issue — drop the point on a grounded opponent.",
                target_grounded=True,
                base_damage=11,
                momentum_gain=2,
                difficulty=3,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="leg_drop",
                name="Leg drop",
                description="Across the throat — crowd pops.",
                target_grounded=True,
                base_damage=10,
                momentum_gain=2,
                difficulty=3,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="stomp",
                name="Stomp",
                description="Simple, mean, effective.",
                target_grounded=True,
                base_damage=7,
                momentum_gain=1,
                difficulty=2,
                targets_head=True,
            )
        ),
        MoveRule(
            Move(
                id="pin",
                name="Cover — pinfall attempt",
                description="Hook the leg — listen for the count.",
                target_grounded=True,
                base_damage=0,
                is_pin=True,
                momentum_gain=0,
                skip_hit_roll=True,
            )
        ),
        MoveRule(
            Move(
                id="pickup",
                name="Pull opponent up",
                description="Break the cover setup — back to a slugfest.",
                target_grounded=True,
                base_damage=2,
                target_after=BodyPosition.STANDING,
                momentum_gain=0,
                skip_hit_roll=True,
            )
        ),
        MoveRule(
            Move(
                id="escape_corner",
                name="Battle out of the corner",
                description="Turn the tables — meet them in the middle of the ring.",
                actor_corner_only=True,
                actor_standing=False,
                base_damage=0,
                actor_after=BodyPosition.STANDING,
                momentum_gain=1,
            )
        ),
        MoveRule(
            Move(
                id="get_up",
                name="Fight to your feet",
                description="Clear your head and stand — you need the ring back.",
                actor_grounded_only=True,
                actor_standing=False,
                base_damage=0,
                actor_after=BodyPosition.STANDING,
                momentum_gain=0,
                difficulty=1,
                # Not automatic: failure leaves you grounded so the opponent can pin.
            )
        ),
        MoveRule(
            Move(
                id="recover",
                name="Catch your breath",
                description="Reset stance — small recovery.",
                base_damage=0,
                momentum_gain=0,
                skip_hit_roll=True,
            )
        ),
    ]


def move_valid(
    rule: MoveRule,
    actor: Wrestler,
    target: Wrestler,
    actor_pos: BodyPosition,
    target_pos: BodyPosition,
    actor_has_rebound: bool,
) -> bool:
    m = rule.move
    if m.actor_corner_only:
        if actor_pos != BodyPosition.CORNER:
            return False
    elif m.actor_grounded_only:
        if actor_pos != BodyPosition.GROUNDED:
            return False
    elif m.actor_rebound:
        if not actor_has_rebound or actor_pos != BodyPosition.STANDING:
            return False
    elif m.actor_top:
        if actor_pos != BodyPosition.TOP_ROPE:
            return False
    elif m.is_climb:
        if actor_pos != BodyPosition.STANDING:
            return False
    elif m.is_hit_ropes:
        if actor_pos != BodyPosition.STANDING:
            return False
    elif m.actor_running_ropes_only:
        if actor_pos != BodyPosition.RUNNING_ROPES:
            return False
    elif not m.actor_standing:
        return False
    else:
        if actor_pos != BodyPosition.STANDING:
            return False

    if m.target_standing is True and target_pos != BodyPosition.STANDING:
        return False
    if m.target_grounded is True and target_pos != BodyPosition.GROUNDED:
        return False
    if m.target_corner is True and target_pos != BodyPosition.CORNER:
        return False
    if m.target_top is True and target_pos != BodyPosition.TOP_ROPE:
        return False
    if m.target_running_ropes is True and target_pos != BodyPosition.RUNNING_ROPES:
        return False

    return rule.extra(actor, target)
