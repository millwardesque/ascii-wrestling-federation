"""Player move policies for automated playtest runs."""

from __future__ import annotations

import random
from typing import Sequence

from render_fixed import _MoveChoice


def choose_policy_index(
    policy: str,
    choices: Sequence[_MoveChoice],
    rng: random.Random,
) -> int:
    """Return 1-based menu index into ``choices``."""
    if not choices:
        raise ValueError("choose_policy_index requires at least one choice")

    if policy == "chaotic":
        return rng.randint(1, len(choices))

    if policy == "novice":
        return min(2, len(choices))

    intent_rank = {
        "Finish": 0,
        "Big swing": 1,
        "Grapple control": 2,
        "Set up position": 3,
        "Safe offense": 4,
        "Reset / recover": 5,
        "Pressure": 6,
    }

    if policy == "aggressive":
        preferred = ("Finish", "Big swing")
    elif policy == "methodical":
        preferred = ("Set up position", "Grapple control", "Pressure")
    else:
        raise ValueError(f"Unknown playtest policy: {policy!r}")

    best_rank = len(intent_rank) + 1
    best_indices: list[int] = []
    for idx, choice in enumerate(choices, start=1):
        rank = intent_rank.get(choice.intent, len(intent_rank))
        if choice.intent in preferred:
            rank -= 10
        if rank < best_rank:
            best_rank = rank
            best_indices = [idx]
        elif rank == best_rank:
            best_indices.append(idx)
    return rng.choice(best_indices)
