"""Playable roster: stats influence damage, pin strength, and kickouts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Wrestler:
    id: str
    name: str
    nickname: str
    strength: int  # offense / pin
    agility: int  # dodge / top-rope bonus
    endurance: int  # health scaling / kickout
    charisma: int  # momentum gain (flavor / tie-breaks)

    @property
    def max_health(self) -> int:
        return 80 + self.endurance * 4


ROSTER: dict[str, Wrestler] = {
    "ace": Wrestler(
        id="ace",
        name="Jordan \"The Ace\" Hayes",
        nickname="The Ace",
        strength=14,
        agility=13,
        endurance=12,
        charisma=11,
    ),
    "vulture": Wrestler(
        id="vulture",
        name="Rico \"The Vulture\" Vega",
        nickname="The Vulture",
        strength=12,
        agility=10,
        endurance=16,
        charisma=9,
    ),
    "phantom": Wrestler(
        id="phantom",
        name="Sable \"Phantom\" Okada",
        nickname="The Phantom",
        strength=10,
        agility=16,
        endurance=11,
        charisma=13,
    ),
    "tank": Wrestler(
        id="tank",
        name="Bruno \"The Tank\" Kowalski",
        nickname="The Tank",
        strength=17,
        agility=7,
        endurance=15,
        charisma=8,
    ),
}


def list_roster() -> list[Wrestler]:
    return list(ROSTER.values())
