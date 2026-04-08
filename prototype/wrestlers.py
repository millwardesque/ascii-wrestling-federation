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
    "bret_hart": Wrestler(
        id="bret_hart",
        name="Bret \"Hitman\" Hart",
        nickname="Hitman",
        strength=12,
        agility=14,
        endurance=13,
        charisma=12,
    ),
    "cm_punk": Wrestler(
        id="cm_punk",
        name="CM Punk",
        nickname="Punk",
        strength=13,
        agility=12,
        endurance=14,
        charisma=12,
    ),
    "stone_cold": Wrestler(
        id="stone_cold",
        name="Stone Cold Steve Austin",
        nickname="Stone Cold",
        strength=16,
        agility=10,
        endurance=14,
        charisma=15,
    ),
    "the_rock": Wrestler(
        id="the_rock",
        name="The Rock",
        nickname="The Rock",
        strength=15,
        agility=11,
        endurance=13,
        charisma=16,
    ),
    "mr_perfect": Wrestler(
        id="mr_perfect",
        name="Mr. Perfect",
        nickname="Perfect",
        strength=12,
        agility=15,
        endurance=12,
        charisma=11,
    ),
    "scott_hall": Wrestler(
        id="scott_hall",
        name="Scott Hall",
        nickname="Hall",
        strength=14,
        agility=11,
        endurance=13,
        charisma=12,
    ),
    "ric_flair": Wrestler(
        id="ric_flair",
        name="Ric Flair",
        nickname="Nature Boy",
        strength=11,
        agility=12,
        endurance=14,
        charisma=16,
    ),
    "arn_anderson": Wrestler(
        id="arn_anderson",
        name="Arn Anderson",
        nickname="Arn",
        strength=15,
        agility=9,
        endurance=16,
        charisma=10,
    ),
    "andre": Wrestler(
        id="andre",
        name="Andre the Giant",
        nickname="Andre",
        strength=17,
        agility=6,
        endurance=17,
        charisma=8,
    ),
    "macho_man": Wrestler(
        id="macho_man",
        name="Macho Man Randy Savage",
        nickname="Macho Man",
        strength=14,
        agility=13,
        endurance=12,
        charisma=15,
    ),
    "hulk_hogan": Wrestler(
        id="hulk_hogan",
        name="Hulk Hogan",
        nickname="Hulkster",
        strength=16,
        agility=9,
        endurance=14,
        charisma=15,
    ),
}


def list_roster() -> list[Wrestler]:
    return list(ROSTER.values())
