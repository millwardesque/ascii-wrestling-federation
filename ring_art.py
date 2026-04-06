"""ASCII ring strip: idle stick figures from match state and short move animations.

Animations are keyed by category with per-move overrides (hybrid). Used only by
fixed-layout rendering."""

from __future__ import annotations

from game import MatchState
from moves import BodyPosition, Move

# Per-move-id overrides → animation key (see FRAMES below)
MOVE_ANIMATION_OVERRIDES: dict[str, str] = {
    "perfect_plex": "plex",
    "stunner": "stunner",
    "rock_bottom": "slam",
    "gts": "strike",
    "sharp_shooter": "grapple",
    "frog_splash_finisher": "top_dive",
    "flying_elbow_finisher": "top_dive",
    "razors_edge": "slam",
    "figure_four": "grapple",
    "spinebuster": "slam",
    "giant_boot": "strike",
    "atomic_leg_drop": "leg_drop",
    "pin": "pin_attempt",
    "get_up": "recover",
    "recover": "recover",
    "climb": "climb",
    "top_splash": "top_dive",
    "top_elbow": "top_dive",
}


def infer_animation_key(m: Move) -> str:
    """Default key from move fields when id is not overridden."""
    if m.is_pin:
        return "pin_attempt"
    if m.triggers_pin_after_hit:
        return "plex"
    if m.id == "get_up" or m.id == "recover":
        return "recover"
    if m.is_climb:
        return "climb"
    if m.actor_top:
        return "top_dive"
    if m.actor_running_ropes_only or m.target_running_ropes is True:
        return "rebound"
    if m.actor_rebound:
        return "rebound"
    if m.base_damage >= 17:
        return "slam"
    if m.base_damage >= 9:
        return "strike"
    if m.base_damage > 0:
        return "grapple"
    return "generic"


def animation_for_move(move_id: str, m: Move) -> str:
    return MOVE_ANIMATION_OVERRIDES.get(move_id, infer_animation_key(m))


# --- Idle poses (5 lines each side, no labels inside art) ---

def _pose_standing() -> list[str]:
    return [
        "  o  ",
        " /|\\ ",
        " / \\ ",
        "     ",
        "     ",
    ]


def _pose_grounded() -> list[str]:
    return [
        "     ",
        " ___ ",
        "/   \\",
        "~~~  ",
        "     ",
    ]


def _pose_running() -> list[str]:
    return [
        "  o→ ",
        " /|  ",
        "/    ",
        "     ",
        "     ",
    ]


def _pose_corner() -> list[str]:
    return [
        "| o  ",
        "|/|\\ ",
        "|/ \\ ",
        "     ",
        "     ",
    ]


def _pose_top() -> list[str]:
    return [
        " ^   ",
        " o   ",
        "/|\\  ",
        " |   ",
        "     ",
    ]


def pose_for_position(pos: BodyPosition) -> list[str]:
    if pos == BodyPosition.STANDING:
        return _pose_standing()
    if pos == BodyPosition.GROUNDED:
        return _pose_grounded()
    if pos == BodyPosition.RUNNING_ROPES:
        return _pose_running()
    if pos == BodyPosition.CORNER:
        return _pose_corner()
    if pos == BodyPosition.TOP_ROPE:
        return _pose_top()
    return _pose_standing()


def _combine_lr(
    left: list[str],
    right: list[str],
    *,
    lw: int = 8,
    rw: int = 8,
    gap: str = "   │   ",
) -> list[str]:
    out: list[str] = []
    for i in range(max(len(left), len(right))):
        a = left[i] if i < len(left) else ""
        b = right[i] if i < len(right) else ""
        out.append(a.ljust(lw) + gap + b.ljust(rw))
    return out


RING_HEADER_LINE = "  YOU" + " " * 10 + "CPU"


def idle_ring_lines(state: MatchState) -> list[str]:
    """Left = player (0), right = CPU (1)."""
    left = pose_for_position(state.position[0])
    right = pose_for_position(state.position[1])
    body = _combine_lr(left, right)
    return [RING_HEADER_LINE, *body]


def _swap_lr_frame(lines: list[str]) -> list[str]:
    """Mirror so CPU-on-left / player-on-right for CPU attacker animations."""
    gap = "   │   "
    out: list[str] = []
    for line in lines:
        if gap not in line:
            out.append(line)
            continue
        a, b = line.split(gap, 1)
        out.append(b + gap + a)
    return out


# --- Animation frames: attacker on LEFT when actor_is_player ---

def _strike_frames() -> list[list[str]]:
    a0, a1, a2 = _pose_standing(), _pose_standing(), _pose_grounded()
    v0, v1, v2 = _pose_standing(), _pose_standing(), _pose_grounded()
    # wind-up, contact, victim down
    wind_l = ["  o  ", " /|\\ ", " / \\ ", "     ", "     "]
    hit_l = ["  o→ ", " /|  ", " /   ", "     ", "     "]
    frames = [
        _combine_lr(wind_l, v0),
        _combine_lr(hit_l, v1),
        _combine_lr(_pose_standing(), v2),
    ]
    return frames


def _slam_frames() -> list[list[str]]:
    lift = ["  o  ", " /|\\ ", " |   ", " / \\ ", "     "]
    slam = ["  o  ", "—|\\ ", " / \\ ", "     ", "     "]
    down = _pose_standing()
    grounded = _pose_grounded()
    return [
        _combine_lr(lift, down),
        _combine_lr(slam, down),
        _combine_lr(_pose_standing(), grounded),
    ]


def _grapple_frames() -> list[list[str]]:
    return [
        _combine_lr(["  o  ", " /|\\—", " / \\ ", "     ", "     "], _pose_standing()),
        _combine_lr(["  o  ", " /|\\ ", " /|\\ ", " / \\ ", "     "], ["  o  ", " /|\\ ", " / \\ ", "     ", "     "]),
        _combine_lr(_pose_standing(), _pose_grounded()),
    ]


def _top_dive_frames() -> list[list[str]]:
    air = ["  ^  ", "  o  ", " /|\\ ", "     ", "     "]
    dive = ["     ", "  \\o ", "   |\\", "     ", "     "]
    return [
        _combine_lr(_pose_top(), _pose_grounded()),
        _combine_lr(air, _pose_grounded()),
        _combine_lr(_pose_standing(), _pose_grounded()),
        _combine_lr(_pose_standing(), _pose_grounded()),
    ]


def _rebound_frames() -> list[list[str]]:
    r = _pose_running()
    return [
        _combine_lr(r, _pose_standing()),
        _combine_lr(["  o→ ", " /|  ", " /   ", "     ", "     "], _pose_standing()),
        _combine_lr(_pose_standing(), _pose_grounded()),
    ]


def _pin_frames() -> list[list[str]]:
    cover = ["  o  ", " /|\\ ", " /|  ", " / \\ ", "     "]
    return [
        _combine_lr(cover, _pose_grounded()),
        _combine_lr(["  o  ", " /|\\ ", " / \\ ", "  ‖  ", "     "], _pose_grounded()),
        _combine_lr(cover, _pose_grounded()),
    ]


def _plex_frames() -> list[list[str]]:
    return [
        _combine_lr(_pose_standing(), _pose_standing()),
        _combine_lr(["  o  ", " /|\\ ", " / \\ ", "     ", "     "], ["  o  ", " /|\\ ", " / \\ ", "     ", "     "]),
        _combine_lr(_pose_standing(), _pose_grounded()),
        _combine_lr(_pose_standing(), _pose_grounded()),
    ]


def _stunner_frames() -> list[list[str]]:
    return [
        _combine_lr(_pose_standing(), _pose_standing()),
        _combine_lr(["  o  ", " /|\\ ", " / \\ ", "     ", "     "], ["  o  ", "  |\\ ", " / \\ ", "     ", "     "]),
        _combine_lr(_pose_standing(), _pose_grounded()),
    ]


def _leg_drop_frames() -> list[list[str]]:
    return [
        _combine_lr(_pose_standing(), _pose_grounded()),
        _combine_lr(["  o  ", "  |  ", " / \\ ", "     ", "     "], _pose_grounded()),
        _combine_lr(_pose_standing(), _pose_grounded()),
    ]


def _recover_frames() -> list[list[str]]:
    return [
        _combine_lr(_pose_grounded(), _pose_standing()),
        _combine_lr(["  o  ", " /|\\ ", " / \\ ", "     ", "     "], _pose_standing()),
        _combine_lr(_pose_standing(), _pose_standing()),
    ]


def _climb_frames() -> list[list[str]]:
    return [
        _combine_lr(_pose_standing(), _pose_standing()),
        _combine_lr(["  |  ", "  o  ", " /|\\ ", " / \\ ", "     "], _pose_standing()),
        _combine_lr(_pose_top(), _pose_standing()),
    ]


def _generic_frames() -> list[list[str]]:
    return _strike_frames()


FRAMES: dict[str, list[list[str]]] = {
    "strike": _strike_frames(),
    "slam": _slam_frames(),
    "grapple": _grapple_frames(),
    "top_dive": _top_dive_frames(),
    "rebound": _rebound_frames(),
    "pin_attempt": _pin_frames(),
    "plex": _plex_frames(),
    "stunner": _stunner_frames(),
    "leg_drop": _leg_drop_frames(),
    "recover": _recover_frames(),
    "climb": _climb_frames(),
    "generic": _generic_frames(),
}


def frames_for_key(key: str, *, actor_is_player: bool) -> list[list[str]]:
    """Return animation frames; mirror left/right when CPU attacks."""
    frames = FRAMES.get(key, FRAMES["generic"])
    if not actor_is_player:
        return [_swap_lr_frame(f) for f in frames]
    return [list(f) for f in frames]


def frames_for_move(move_id: str, m: Move, *, actor_is_player: bool) -> list[list[str]]:
    key = animation_for_move(move_id, m)
    return frames_for_key(key, actor_is_player=actor_is_player)
