"""``ChallengeRun`` (quests) port.

The quest classes are data (character, starting items / upgrades / tiles, banned
bosses); their rules live where the game checks them:

- grid generation: RedLetterDay, RedPepperDay, EmptyGrid, Sudoku, CallOfTheVoid,
  MunchTime, SupplyAndDemand, UpAndUp (``gridgen.py``)
- word validity: Chromaphilia, Chromaphobia, Cursophobia, UpAndUp, SicilianDefense,
  Lexographer (engine search via ``challenge_game_class``)
- scoring: TwoWrongs, Bullseye, Lexographer, TheBonesRound, PlayingFavourites (engine)
- encounter: DoNotPassGo, Embargo, MunchTime loss (``encounter.py``)
- shop: Antiphilatelist, Masochist, InTheBeginning, DecisionParalysis, SecretSanta,
  Embargo, PlayingFavourites (``shop.py``)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cursed_words_solver.sim.game.core import Tile


@dataclass
class ChallengeRun:
    game_class: str
    character: str | None = None  # forced character (None = player picks)
    starting_items: tuple[str, ...] = ()
    item_upgrades: tuple[int, ...] = ()
    elite: bool = False
    banned_bosses: dict[int, tuple[str, ...]] = field(default_factory=dict)
    # MunchTime state
    path: list[tuple[int, int]] = field(default_factory=list)
    munched: list[tuple[int, int]] = field(default_factory=list)

    def starting_tiles(self) -> list[Tile]:
        if self.game_class == "Sudoku":
            out = []
            for i in range(1, 6):
                t = Tile()
                t.set_number(i)
                t.was_consumable = True
                out.append(t)
            return out
        return []


def _all_floors(*bosses: str) -> dict[int, tuple[str, ...]]:
    return {i: tuple(bosses) for i in range(5)}


_MUNCH = {
    0: ("SmallGrid", "DestroyGrid"),
    1: ("SmallGrid", "DestroyGrid", "MinWordLength"),
    **{i: ("SmallGrid", "DestroyGrid", "ExtraVoids", "ExtraQs", "MinWordLength", "DiscolourTiles", "AddNumbers") for i in (2, 3, 4)},
}
_UP = {0: ("SmallGrid", "DestroyGrid"), **{i: ("SmallGrid", "DestroyGrid", "MaxWordLength") for i in (1, 2, 3, 4)}}

# ChallengeRuns.ItemUnlocks order (quest number = index + 1).
QUESTS: dict[str, dict] = {
    "SupplyAndDemand": {},
    "DecisionParalysis": {},
    "Sudoku": {},
    "UpAndUp": {"elite": True, "banned_bosses": _UP},
    "SecretSanta": {},
    "MunchTime": {"elite": True, "banned_bosses": _MUNCH},
    "Antiphilatelist": {},
    "Masochist": {"elite": True},
    "CallOfTheVoid": {"starting_items": ("FullMoon", "HungrySnake", "TwinkleToes")},
    "Chromaphilia": {"character": "WetDennis", "starting_items": ("GamePad",), "item_upgrades": (2,)},
    "Chromaphobia": {"character": "WetDennis", "starting_items": ("GamePad",), "item_upgrades": (2,)},
    "TwoWrongs": {"character": "NinaNix", "starting_items": ("DangerousSummit",)},
    "Bullseye": {"character": "HayleyBayles", "elite": True},
    "SicilianDefense": {"character": "SamGambit", "banned_bosses": _all_floors("SmallGrid")},
    "TheBonesRound": {"character": "BonesTheDog"},
    "Cursophobia": {"character": "Octacles", "starting_items": ("Amphora",), "item_upgrades": (2,)},
    "Lexographer": {"character": "Octacles"},
    "InTheBeginning": {"character": "NathaServo", "starting_items": ("Microphone",)},
    "RedLetterDay": {"character": "SandySaguaro", "starting_items": ("RedEnvelope",)},
    "RedPepperDay": {"character": "SandySaguaro", "starting_items": ("SpicyPepper",)},
    "EmptyGrid": {"character": "SandySaguaro", "starting_items": ("SpoutingWhale", "WeeklyShop")},
    "DoNotPassGo": {"character": "Spike", "starting_items": ("KokeshiDolls",)},
    "Embargo": {"character": "Spike", "banned_bosses": _all_floors("ForcedSell")},
    "PlayingFavourites": {"character": "SockHead", "elite": True},
    "ColourSwap": {"character": "PrismaticBean"},
    "SpeedrunChallenge": {},
}

# Wiki display names (melmod ``challenge_name``) for lookup convenience.
QUEST_NAMES = {
    "Knight Time": "SicilianDefense",
    "Shelf Life": "DecisionParalysis",
    "On Cooldown": "SupplyAndDemand",
}


def make_challenge(name: str | None) -> ChallengeRun | None:
    if not name:
        return None
    cls = QUEST_NAMES.get(name, name)
    if cls not in QUESTS:
        low = cls.lower().replace(" ", "")
        cls = next((k for k in QUESTS if k.lower() == low), cls)
    if cls not in QUESTS:
        raise KeyError(f"unknown quest {name!r}")
    spec = QUESTS[cls]
    return ChallengeRun(
        game_class=cls,
        character=spec.get("character"),
        starting_items=tuple(spec.get("starting_items", ())),
        item_upgrades=tuple(spec.get("item_upgrades", ())),
        elite=bool(spec.get("elite", False)),
        banned_bosses={k: tuple(v) for k, v in (spec.get("banned_bosses") or {}).items()},
    )
