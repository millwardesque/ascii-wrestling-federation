"""Commentary booth roster: play-by-play + color pairs chosen per match.

Archetypes inspired by classic wrestling broadcast teams (Monsoon, Ventura,
Heenan, Ross, Lawler, Cornette). Personalities are data here; the
``CommentaryEngine`` in ``commentary.py`` will render ``MatchEvent`` facts into
lines once ``apply_move`` emits events instead of f-strings.

See ``docs/commentary-design.md``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal


CommentatorRole = Literal["pbp", "color"]
CommentatorRegister = Literal["straight", "excitable", "sardonic", "folksy"]
CommentatorBias = Literal["neutral", "face", "heel"]

# XOR salt keeps commentary selection independent of in-match move RNG.
COMMENTARY_TEAM_SALT = 0xC041E7A1


@dataclass(frozen=True)
class Commentator:
    id: str
    name: str
    short: str  # move-log prefix, e.g. "GORILLA"
    role: CommentatorRole
    register: CommentatorRegister
    bias: CommentatorBias
    intensity: int  # 1–5: near-fall / finisher urgency
    catchphrases: tuple[str, ...] = ()
    vocab: frozenset[str] = frozenset()
    avoid: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CommentatorPair:
    """One booth: play-by-play first, color second."""

    pbp_id: str
    color_id: str

    @property
    def ids(self) -> tuple[str, str]:
        return (self.pbp_id, self.color_id)

    def pbp(self) -> Commentator:
        return ROSTER[self.pbp_id]

    def color(self) -> Commentator:
        return ROSTER[self.color_id]

    def label(self) -> str:
        pbp = self.pbp()
        color = self.color()
        return f"{pbp.name} & {color.name}"

    def intro_line(self) -> str:
        return f"On the call: {self.label()}"


ROSTER: dict[str, Commentator] = {
    "gorilla": Commentator(
        id="gorilla",
        name="Gorilla Monsoon",
        short="GORILLA",
        role="pbp",
        register="straight",
        bias="neutral",
        intensity=3,
        catchphrases=("Will you look at that!", "What a maneuver!"),
        vocab=frozenset({"maneuver", "cover", "bridge", "canvas", "ropes"}),
        avoid=frozenset({"hp", "stunned", "damage meter"}),
    ),
    "ross": Commentator(
        id="ross",
        name="Jim Ross",
        short="JR",
        role="pbp",
        register="excitable",
        bias="face",
        intensity=5,
        catchphrases=("Business is about to pick up!", "As God as my witness!"),
        vocab=frozenset({"slobberknocker", "bowl of human garbage", "magnitude"}),
        avoid=frozenset({"hp", "star power"}),
    ),
    "ventura": Commentator(
        id="ventura",
        name="Jesse Ventura",
        short="JESSE",
        role="color",
        register="sardonic",
        bias="heel",
        intensity=3,
        catchphrases=("You don't get paid to think!", "That's a conspiracy!"),
        vocab=frozenset({"conspiracy", "smart money", "booked"}),
        avoid=frozenset({"hp", "crowd meter"}),
    ),
    "heenan": Commentator(
        id="heenan",
        name="Bobby Heenan",
        short="BRAIN",
        role="color",
        register="sardonic",
        bias="heel",
        intensity=4,
        catchphrases=("Give me a break!", "The Brain knows!"),
        vocab=frozenset({"idiot", "manager", "payoff", "scheme"}),
        avoid=frozenset({"hp", "stunned"}),
    ),
    "lawler": Commentator(
        id="lawler",
        name="Jerry Lawler",
        short="KING",
        role="color",
        register="sardonic",
        bias="heel",
        intensity=4,
        catchphrases=("That's a classic!",),
        vocab=frozenset({"Memphis", "piledriver", "crowd"}),
        avoid=frozenset({"hp"}),
    ),
    "cornette": Commentator(
        id="cornette",
        name="Jim Cornette",
        short="JIM",
        role="color",
        register="excitable",
        bias="heel",
        intensity=4,
        catchphrases=("Oh come on!", "This is an outrage!"),
        vocab=frozenset({"tennis racket", "tag team", "booked"}),
        avoid=frozenset({"hp"}),
    ),
}

# Curated booths — complementary PBP + color, not every combination.
CURATED_PAIRS: tuple[CommentatorPair, ...] = (
    CommentatorPair("gorilla", "ventura"),
    CommentatorPair("gorilla", "heenan"),
    CommentatorPair("gorilla", "cornette"),
    CommentatorPair("ross", "lawler"),
    CommentatorPair("ross", "cornette"),
)


def list_commentators() -> list[Commentator]:
    return [ROSTER[cid] for cid in sorted(ROSTER)]


def list_curated_pairs() -> list[CommentatorPair]:
    return list(CURATED_PAIRS)


def choose_commentary_team(seed: int | None) -> CommentatorPair:
    """Pick a booth from ``seed`` so replays and playtests stay reproducible."""
    if seed is None:
        seed = random.randrange(1 << 30)
    rng = random.Random(seed ^ COMMENTARY_TEAM_SALT)
    return rng.choice(CURATED_PAIRS)


def validate_roster() -> None:
    """Raise ``ValueError`` if any curated pair references a missing or wrong-role id."""
    for pair in CURATED_PAIRS:
        for cid in pair.ids:
            if cid not in ROSTER:
                raise ValueError(f"unknown commentator id: {cid}")
        if pair.pbp().role != "pbp":
            raise ValueError(f"{pair.pbp_id} must be play-by-play")
        if pair.color().role != "color":
            raise ValueError(f"{pair.color_id} must be color")
