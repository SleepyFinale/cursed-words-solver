"""``Player``, ``RunProgress``, ``BossModifier`` / ``BossDraft`` and ``HistoricWord`` ports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import IntEnum
from functools import lru_cache
from typing import Any, Callable

import numpy as np

from cursed_words_solver.paths import data_path
from cursed_words_solver.sim.game import core as C
from cursed_words_solver.sim.game.core import Rng, Tile
from cursed_words_solver.sim.game.items import GENERATOR_TAGS, Item, make_item

BUILD_SYNERGY_TAGS = (
    "BlueBuild", "RedBuild", "VoidBuild", "ShinyBuild", "ChessBuild", "BlankBuild",
    "ColourlessBuild", "CashBuild", "RainbowBuild", "ConsumableBuild", "CurseBuild",
    "NumbersBuild", "ArrowBuild", "CardsBuild", "BigNumbersBuild", "ScatteredItemsBuild",
)

NUMBER_OF_STAGES = 5
MICHAEL_STAGE = 6
GRIDS_PER_ROUND = 5
GRID_DIMENSION = 5


class Node(IntEnum):
    NONE = 0
    SHOP_ZERO = 1
    ENCOUNTER_FIRST = 2
    SHOP_ONE = 3
    ENCOUNTER_SECOND = 4
    SHOP_TWO = 5
    BOSS_DRAFT = 6
    BOSS = 7
    BOSS_REWARD = 8
    MEG_SHOP = 9


ENCOUNTER_NODES = (Node.ENCOUNTER_FIRST, Node.ENCOUNTER_SECOND, Node.BOSS)
SHOP_NODES = (Node.SHOP_ZERO, Node.SHOP_ONE, Node.SHOP_TWO, Node.MEG_SHOP)
_ENCOUNTER_INDEX = {Node.ENCOUNTER_FIRST: 0, Node.ENCOUNTER_SECOND: 1, Node.BOSS: 2}


class Ascension(IntEnum):
    NONE = 0
    CURSED_BOSSES = 1
    UNKIND_SHOPS = 2
    LOWER_TILE_SCORES = 3
    LOCKED_STAMP_SLOTS = 4
    HARDER_GRID_GENERATION = 5
    LOCKED_STICKER_SLOTS = 6
    ONE_FEWER_GRID = 7
    HARDER_BOSSES = 8


# ---------------------------------------------------------------------------- characters


@lru_cache(maxsize=1)
def character_rows() -> dict[str, dict[str, Any]]:
    data = json.loads(data_path("data", "game", "run_catalog.json").read_text(encoding="utf-8"))
    return {row["type"]: row for row in data.get("characters") or () if row.get("ok")}


def resolve_character(key: str) -> str:
    """Game class from class name, display name ("Rodman", "Carpman") or pin."""
    rows = character_rows()
    if key in rows:
        return key
    low = key.lower().replace(" ", "").replace("-", "")
    aliases = {"carpman": "WetDennis", "rodman": "WetDennis", "nat-h4": "NathaServo", "nath4": "NathaServo",
               "beans": "PrismaticBean", "humanboy": "SockHead", "meg": "Spike", "cretaceousmeg": "Spike"}
    if low in aliases:
        return aliases[low]
    for cls, row in rows.items():
        name = str(row.get("name") or "").lower().replace(" ", "").replace("-", "")
        if low in (cls.lower(), name, str(row.get("pin") or "").lower()):
            return cls
    raise KeyError(key)


# ---------------------------------------------------------------------------- bosses


@lru_cache(maxsize=1)
def boss_rows() -> dict[str, dict[str, Any]]:
    data = json.loads(data_path("data", "game", "run_catalog.json").read_text(encoding="utf-8"))
    return {row["type"]: row for row in data.get("bosses") or () if row.get("ok")}


SECRET_BOSSES = ("SandySaguaroBoss", "CretaceousMegBoss", "HumanBoyBoss", "PrismaticBeanBoss")
SECRET_BOSS_CHARACTER = {
    "SandySaguaroBoss": "SandySaguaro", "CretaceousMegBoss": "Spike",
    "HumanBoyBoss": "SockHead", "PrismaticBeanBoss": "PrismaticBean",
}


class BossModifier:
    def __init__(self, game_class: str) -> None:
        row = boss_rows()[game_class]
        self.game_class = game_class
        self.difficulty = list(row.get("difficulty_modifier") or [0] * 7)
        self.increase = list(row.get("difficulty_increase") or [0] * 7)
        self.banned_floors = tuple(row.get("banned_floor_indexes") or ())
        self.is_secret = bool(row.get("is_secret_character"))
        self.summonable = bool(row.get("can_be_summoned_by_michael"))
        self.floor_mod = 0
        self.cursed = False
        self.fields: dict[str, Any] = {}
        if game_class == "ExtraVoids":
            self.fields["TileTypeToScatter"] = C.VOID
        if game_class == "DestroyGrid":
            self.fields["DestroyedCoordinates"] = []
        if game_class == "MichaelBoss":
            self.difficulty = [0, 0, 0, 0, 0, 3, 4]
            self.increase = [0, 0, 0, 0, 0, 0, 1]
            self.drafts: list[list[BossModifier]] = []
            self.drafted: list[BossModifier] = []
            self.summoned_defeated = False
        if game_class == "CretaceousMegBoss":
            self.stored: dict[str, Any] | None = None

    def set_floor(self, floor: int, harder: bool) -> None:
        """``SetFloorAdjustedModification``."""
        idx = min(floor + 1 if harder else floor, len(self.difficulty) - 1)
        self.floor_mod = self.difficulty[idx]

    def make_cursed(self) -> None:
        if not self.cursed:
            self.cursed = True
            self.difficulty = [d + i for d, i in zip(self.difficulty, self.increase)]

    def to_state(self) -> dict[str, Any]:
        fields: dict[str, Any] = {"FloorAdjustedModification": self.floor_mod, "IsCursed": self.cursed}
        if self.game_class == "MichaelBoss":
            fields["SummonedBossesDefeated"] = self.summoned_defeated
        return {"class": self.game_class, "fields": fields}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.game_class}{' cursed' if self.cursed else ''} {self.floor_mod}>"


def secret_boss_condition(boss: str, player: "Player") -> bool:
    """``HasMetSecretBossCondition`` (assumes the character is not yet unlocked)."""
    stats = player.run.stats
    if boss == "CretaceousMegBoss":
        return player.money >= 50
    if boss == "HumanBoyBoss":
        return any(s.level(0) > 3 for s in player.stickers_list(for_comparison=True))
    if boss == "PrismaticBeanBoss":
        return any(
            any(not t.is_type(C.NORMAL) and not t.is_type(C.BLUE) and not t.is_type(C.RED)
                and not t.is_type(C.SHINY) and not t.is_type(C.VOID) for t in w.tiles)
            for w in stats.words_submitted
        )
    if boss == "SandySaguaroBoss":
        return stats.consumables_used_count >= 15
    return False


@dataclass
class BossDraft:
    options: list[BossModifier] = field(default_factory=list)


# ---------------------------------------------------------------------------- history


@dataclass(eq=False)
class HistoricWord:
    tiles: list[Tile]
    words: list[str]
    skipped: bool
    score: int
    remainder: int
    submitted_round: int
    dims: tuple[int, int]
    wobbly: list[bool] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    values: list[int] = field(default_factory=list)

    def tile_value(self, t: Tile) -> int:
        try:
            return self.values[self.tiles.index(t)]
        except (ValueError, IndexError):
            return 0

    def curse_level(self) -> int:
        n = sum(1 for i, t in enumerate(self.tiles) if t.get_glyph() != C.G_LETTER or (i < len(self.wobbly) and self.wobbly[i]))
        return 0 if n == 0 else (2 if n >= 3 else 1)


@dataclass
class RunStatistics:
    words_submitted: list[HistoricWord] = field(default_factory=list)
    consumables_used_count: int = 0
    total_cash_earned: int = 0
    has_seen_secret_boss: bool = False
    bosses: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------- run progress


def _f32(x) -> np.float32:
    return np.float32(x)


def round_to_int(x: float) -> int:
    return int(round(float(x)))


class RunProgress:
    def __init__(self, ascension: int = 0, challenge: Any = None) -> None:
        self.ascension = int(ascension)
        self.challenge = challenge  # ChallengeRun instance (challenges.py) or None
        self.node = Node.NONE
        self.stage = 0
        self.boss_drafts: list[BossDraft] = []
        self.available_colours: list[str] = [C.RED, C.BLUE, C.VOID, C.SHINY]
        self.cactus_growth_level = 0
        self.embargoed: set[str] = set()
        self.cursed_bosses_defeated: list[int] = []
        self.stats = RunStatistics()
        self.saved_final_inventory: list[Item] | None = None

    @property
    def stats_consumables_used(self) -> int:
        return self.stats.consumables_used_count

    @stats_consumables_used.setter
    def stats_consumables_used(self, v: int) -> None:
        self.stats.consumables_used_count = v

    def challenge_is(self, name: str) -> bool:
        return self.challenge is not None and self.challenge.game_class == name

    def asc(self, level: int) -> bool:
        return self.ascension >= level

    def is_final_stage(self) -> bool:
        return self.stage == NUMBER_OF_STAGES and self.node == Node.BOSS

    def is_first_stage(self) -> bool:
        return self.stage == 1 and self.node == Node.ENCOUNTER_FIRST

    def remaining_encounters(self) -> int:
        n = (5 - self.stage) * 3
        if self.node == Node.ENCOUNTER_FIRST:
            return n + 2
        if self.node == Node.ENCOUNTER_SECOND:
            return n + 1
        return n

    def get_new_tile_colour(self, rng: Rng) -> str:
        pool = [c for c in (C.PURPLE, C.GOLD, C.WHITE, C.GREEN, C.PINK, C.CACTUS) if c not in self.available_colours]
        if not pool:
            return C.GLITCH
        c = pool[rng.range(0, len(pool))]
        self.available_colours.append(c)
        return c

    def add_available_colour(self, c: str) -> None:
        if c not in self.available_colours:
            self.available_colours.append(c)

    # -- targets ------------------------------------------------------------------

    def encounter_target(self, stage: int, node: Node, player: "Player") -> int:
        """``RunProgress.GetEncounterTarget`` (float32 Unity math)."""
        base = 12 * round_to_int(_f32(np.power(_f32(3.8), _f32(stage - 1))))
        progress = _f32(((stage - 1) * 3 + _ENCOUNTER_INDEX[node]) / _f32(14.0))
        ramp = _f32(np.power(progress, _f32(1.2)))
        asc = _f32(1.0) + _f32(self.ascension) * _f32(0.4) * ramp
        mask = _f32(1.0)
        masks = player.unpacked_of("DivingMask")
        if masks:
            pct = sum(m.var(0) for m in masks)
            mask = _f32((100 - pct) / _f32(100.0))
        if mask <= 0:
            return 1
        mult = {Node.ENCOUNTER_FIRST: _f32(1.0), Node.ENCOUNTER_SECOND: _f32(1.4), Node.BOSS: _f32(2.0)}[node]
        if node == Node.ENCOUNTER_FIRST:
            return round_to_int(_f32(base) * mask * asc)
        return round_to_int(_f32(base) * mult * mask * asc)

    def current_encounter_target(self, player: "Player") -> int:
        node = self.node if self.node in ENCOUNTER_NODES else Node.BOSS
        return self.encounter_target(self.stage, node, player)

    # -- bosses ------------------------------------------------------------------

    def generate_boss_drafts(self, rng: Rng, player: "Player") -> None:
        """``RunProgress.GetRandomBossDrafts``."""
        harder = self.asc(Ascension.HARDER_BOSSES)
        remaining = [b for b in boss_rows() if b not in SECRET_BOSSES and b != "MichaelBoss"]
        drafts: list[BossDraft] = []
        for floor in range(NUMBER_OF_STAGES):
            draft = BossDraft()
            banned = set()
            if self.challenge is not None:
                banned = set(self.challenge.banned_bosses.get(floor, ()))
            cands = [BossModifier(b) for b in remaining if b not in banned]
            cands = [b for b in cands if floor not in b.banned_floors and not b.is_secret]
            first = cands.pop(rng.range(0, len(cands)))
            draft.options.append(first)
            if not self.challenge_is("MunchTime"):
                remaining = [b for b in remaining if b != first.game_class]
            if self.challenge_is("ColourSwap") and first.game_class == "ExtraVoids":
                _randomise_extra_voids(first, rng)
            second = cands[rng.range(0, len(cands))]
            draft.options.append(second)
            remaining = [b for b in remaining if b != second.game_class]
            if self.challenge_is("ColourSwap") and second.game_class == "ExtraVoids":
                _randomise_extra_voids(second, rng)
            if self.asc(Ascension.CURSED_BOSSES):
                draft.options[rng.range(0, 2)].make_cursed()
            else:
                player.has_faced_uncursed_boss = True
            for b in draft.options:
                b.set_floor(floor, harder)
            drafts.append(draft)
        michael = BossModifier("MichaelBoss")
        michael.set_floor(5, harder)
        drafts.append(BossDraft([michael]))
        self.boss_drafts = drafts

    def curse_current_stage_bosses(self) -> None:
        if 0 < self.stage <= len(self.boss_drafts):
            for b in self.boss_drafts[self.stage - 1].options:
                b.make_cursed()
                b.set_floor(self.stage - 1, self.asc(Ascension.HARDER_BOSSES))

    def check_secret_bosses(self, rng: Rng, player: "Player", unlocked_characters: set[str]) -> None:
        """``CheckSecretBossesConditions`` (run at BossReward → next stage, stages 2–4)."""
        if self.challenge is not None or self.stats.has_seen_secret_boss:
            return
        for boss in SECRET_BOSSES:
            if SECRET_BOSS_CHARACTER[boss] in unlocked_characters:
                continue
            if not secret_boss_condition(boss, player):
                continue
            self.stats.has_seen_secret_boss = True
            draft = self.boss_drafts[self.stage]
            uncursed = [b for b in draft.options if not b.cursed]
            if not uncursed:
                return
            draft.options.remove(uncursed[rng.range(0, len(uncursed))])
            secret = BossModifier(boss)
            secret.set_floor(self.stage, self.asc(Ascension.HARDER_BOSSES))
            draft.options.append(secret)
            from cursed_words_solver.sim.game.grid_util import shuffle

            draft.options = [b for b in shuffle(rng, draft.options) if b is not None]
            return

    # -- progression ----------------------------------------------------------------

    def advance(self, player: "Player", rng: Rng, unlocked_characters: set[str]) -> Node:
        """``AdvanceToNextNodeType`` (+ Meg-shop detour from ``GoToNextNodeAndGetSceneName``)."""
        if self.node == Node.MEG_SHOP:
            self.node = Node.BOSS
            return self.node
        if self.node == Node.NONE:
            self.stage += 1
            self.node = Node.ENCOUNTER_FIRST
        elif self.node == Node.BOSS_REWARD:
            if self.stage in (2, 3, 4):
                self.check_secret_bosses(rng, player, unlocked_characters)
            if player.unpacked_of("Ogre") and self.stage < len(self.boss_drafts):
                for b in self.boss_drafts[self.stage].options:
                    b.make_cursed()
                    b.set_floor(self.stage, self.asc(Ascension.HARDER_BOSSES))
            self.stage += 1
            self.node = Node.SHOP_ZERO
        elif self.node == Node.SHOP_TWO and self.stage == MICHAEL_STAGE:
            player.active_bosses = [self.boss_drafts[5].options[0]]
            self.node = Node.BOSS
        else:
            self.node = Node(self.node + 1)
        if self.node in ENCOUNTER_NODES:
            meg = next((b for b in player.active_bosses if b.game_class == "CretaceousMegBoss"), None)
            if meg is not None and meg.stored is None and self.node == Node.BOSS:
                store_meg_inventory(meg, player)
                self.node = Node.MEG_SHOP
        return self.node


def _randomise_extra_voids(boss: BossModifier, rng: Rng) -> None:
    pool = [C.RED, C.BLUE, C.CACTUS, C.SHINY, C.GREEN, C.GOLD, C.PINK, C.WHITE, C.PURPLE]
    boss.fields["TileTypeToScatter"] = pool[rng.range(0, len(pool))]


def store_meg_inventory(meg: BossModifier, player: "Player") -> None:
    """``CretaceousMegBoss.StorePlayerInventory`` → Meg shop with nothing."""
    meg.stored = {
        "items": player.stickers_list(for_comparison=True) + player.stamps_list(for_comparison=True),
        "tiles": list(player.consumables),
        "money": player.money,
    }
    player.clear_inventory()


def restore_meg_inventory(meg: BossModifier, player: "Player", rng: Rng) -> None:
    stored = meg.stored or {}
    player.clear_inventory()
    for it in stored.get("items", []):
        player.add_item(it, rng, acquire=True)
    player.consumables = list(stored.get("tiles") or [None] * 10) + [None] * max(0, 10 - len(stored.get("tiles") or []))
    player.money = int(stored.get("money", 0))


# ---------------------------------------------------------------------------- player


class Player:
    def __init__(self, character: str, ascension: int = 0, challenge: Any = None) -> None:
        self.character = resolve_character(character)
        row = character_rows()[self.character]
        self.character_name = row.get("name") or self.character
        self.intro_items: tuple[str, ...] = tuple(row.get("intro_items") or ())
        self.run = RunProgress(ascension, challenge)
        self.stickers: list[Item | None] = [None] * 5
        self.stamps: list[Item | None] = [None] * 5
        self.consumables: list[Tile | None] = [None] * 10
        self.pin: Item | None = make_item(row["pin"]) if row.get("pin") else None
        self.money = 0
        self.frozen_stickers: list[Any] = [None] * 4
        self.frozen_stamps: list[Any] = [None] * 2
        self.active_bosses: list[BossModifier] = []
        self.bosses_faced: list[str] = []
        self.has_faced_uncursed_boss = False
        self.piggy_bank = 0
        # Shop-side OnAcquire effects (FallingLeaf, FortuneCookie, Snail, Volcano).
        self._shop_listener: Callable[[str], bool] | None = None

    # -- character setup ------------------------------------------------------------

    def set_character_items(self, rng: Rng) -> None:
        """``Player.SetCharacter``: Human Boy gets both hands."""
        if self.pin is not None and self.pin.game_class == "HumanHands":
            self.add_item(make_item("LeftHumanHand"), rng)
            self.add_item(make_item("RightHumanHand"), rng)

    # -- queries --------------------------------------------------------------------

    def all_items(self, for_comparison: bool = False) -> list[Item]:
        """``GetAllItems`` (Playing Favourites restricts unless for_comparison)."""
        if self.run.challenge_is("PlayingFavourites") and not for_comparison:
            out: list[Item] = []
            if self.pin is not None:
                out.append(self.pin)
            out.extend(s for s in self.stickers if s is not None and s.is_hb_favourite_sticker)
            left = next((s for s in self.stickers if s is not None and s.game_class == "LeftHumanHand"), None)
            right = next((s for s in self.stamps if s is not None and s.game_class == "RightHumanHand"), None)
            if left is not None:
                out.append(left)
            if right is not None:
                out.append(right)
                idx = self.stamps.index(right)
                if idx < 4 and self.stamps[idx + 1] is not None:
                    out.append(self.stamps[idx + 1])
            return out
        out = [self.pin] if self.pin is not None else []
        out.extend(s for s in self.stickers if s is not None)
        out.extend(s for s in self.stamps if s is not None)
        return out

    def stickers_list(self, for_comparison: bool = False) -> list[Item]:
        if self.run.challenge_is("PlayingFavourites") and not for_comparison:
            out = [s for s in self.stickers if s is not None and s.is_hb_favourite_sticker]
            left = next((s for s in self.stickers if s is not None and s.game_class == "LeftHumanHand"), None)
            if left is not None:
                out.append(left)
            return out
        return [s for s in self.stickers if s is not None]

    def stamps_list(self, for_comparison: bool = False) -> list[Item]:
        if self.run.challenge_is("PlayingFavourites") and not for_comparison:
            right = next((s for s in self.stamps if s is not None and s.game_class == "RightHumanHand"), None)
            out = [right] if right is not None else []
            if right is not None:
                idx = self.stamps.index(right)
                if idx < 4 and self.stamps[idx + 1] is not None:
                    out.append(self.stamps[idx + 1])
            return out
        return [s for s in self.stamps if s is not None]

    def _unpacked(self, base: list[Item]) -> list[Item]:
        out = list(base)
        ram = next((i for i in base if i.game_class == "RandomAccessMemory"), None)
        snap = next((i for i in base if i.game_class == "Snapshot"), None)
        if ram is not None:
            out.extend(ram.nested_items())
        if snap is not None:
            out.extend(snap.nested_items())
        for fr in [i for i in base if i.game_class == "Frankenstein"]:
            out.extend(fr.nested_items())
        return out

    def unpacked_of(self, game_class: str, for_comparison: bool = False) -> list[Item]:
        """``GetUnpackedItemsOfType``."""
        return [i for i in self._unpacked(self.all_items(for_comparison)) if i.game_class == game_class]

    def all_items_unpacked_shallow(self) -> list[Item]:
        return self._unpacked(self.all_items())

    def all_items_unpacked_for_letters(self, extra: Any = ()) -> list[Item]:
        base = self.all_items() + [i for i in extra if i is not None]
        return self._unpacked(base)

    def all_items_including_nested(self, for_comparison: bool = False) -> list[Item]:
        out: list[Item] = []
        for it in self.all_items(for_comparison):
            out.append(it)
            out.extend(it.nested_items())
        return out

    def has(self, game_class: str) -> bool:
        return bool(self.unpacked_of(game_class))

    def max_upgrade_count(self, item: Item) -> int:
        """``GameStatics.GetMaxUpgradeCount``."""
        if item.game_class == "HungryHippo":
            return 99_999_999
        n = 2
        held = next((i for i in self.all_items() if i.game_class == item.game_class), None)
        if held is not None and held.is_foil:
            n += 2
        if self.unpacked_of("StackOfPancakes"):
            n += 1
        return n

    def stamp_index(self, item: Item) -> int:
        try:
            return self.stamps.index(item)
        except ValueError:
            return -1

    def frozen_count(self) -> int:
        return sum(1 for f in self.frozen_stickers + self.frozen_stamps if f is not None)

    def tiles(self) -> list[Tile]:
        return [t for t in self.consumables if t is not None]

    def consumable_capacity(self) -> int:
        return 10 if self.unpacked_of("Stadium") else 5

    def has_generator(self) -> bool:
        return any(t in GENERATOR_TAGS for i in self.all_items() for t in i.tags)

    def ordered_build_synergy_tags(self) -> list[str]:
        counts: dict[str, int] = {}
        for it in self.all_items():
            for t in it.tags:
                if t in BUILD_SYNERGY_TAGS:
                    counts[t] = counts.get(t, 0) + 1
        if not counts:
            return []
        out: list[str] = []
        for n in range(max(counts.values()), 0, -1):
            out.extend(t for t, c in counts.items() if c == n)
        return out

    def unfulfilled_dependency_tags(self) -> list[str]:
        active: list[str] = []
        changed = True
        items = self.all_items()
        while changed:
            changed = False
            for it in items:
                new = [t for t in it.tags if t not in active]
                if not new:
                    continue
                if not it.dependency_tags or any(d in active for d in it.dependency_tags):
                    active.extend(new)
                    changed = True
        out: list[str] = []
        for it in items:
            out.extend(t for t in it.dependency_tags if t not in out and t not in active)
        return out

    def is_hb_favourite_stamp(self, item: Item) -> bool:
        idx = self.stamp_index(item)
        return idx > 0 and self.stamps[idx - 1] is not None and self.stamps[idx - 1].game_class == "RightHumanHand"

    def is_overhand_target(self, item: Item) -> bool:
        idx = self.stamp_index(item)
        return idx >= 0 and self.stickers[idx] is not None and self.stickers[idx].game_class == "Overhand"

    def accumulator_words(self) -> list[str]:
        """``InventoryCache`` accumulator words (Microphone's depend on free slots)."""
        out: list[str] = []
        for it in self.all_items():
            if it.game_class == "Microphone":
                from cursed_words_solver.sim.game.encounter import microphone_tables

                out.extend(microphone_tables(self)[0])
            else:
                out.extend(it.accumulator_words())
        return out

    # -- shop hook ----------------------------------------------------------------------

    def shop_event(self, kind: str) -> bool:
        if self._shop_listener is None:
            return False
        return bool(self._shop_listener(kind))

    # -- mutations ---------------------------------------------------------------------

    def add_item(self, item: Item, rng: Rng, acquire: bool = True) -> bool:
        """``Player.AddItemToInventory`` (+ ``OnAcquire``)."""
        placed = False
        if item.is_stamp:
            if None in self.stamps:
                self.stamps[self.stamps.index(None)] = item
                placed = True
        elif item.is_sticker:
            if None in self.stickers:
                self.stickers[self.stickers.index(None)] = item
                placed = True
                self.refresh_favourite_sticker()
                self.refresh_underhand_target()
        elif item.is_pin:
            self.pin = item
            placed = True
        self._sewing_needle()
        if acquire:
            item.on_acquire(self, rng)
        return placed

    def remove_item(self, item: Item) -> None:
        if item in self.stickers:
            self.stickers[self.stickers.index(item)] = None
        elif item in self.stamps:
            self.stamps[self.stamps.index(item)] = None
        elif self.pin is item:
            self.pin = None
        self._sewing_needle()

    def _sewing_needle(self) -> None:
        needle = next((s for s in self.stamps if s is not None and s.game_class == "SewingNeedle"), None)
        if needle is None:
            return
        black = set(needle.fields.get("BlacklistedItems", ()))
        stickers = [s for s in self.stickers_list(for_comparison=True) if s.game_class not in black]
        needle.selling_prevented = len(stickers) < 2

    def clear_inventory(self, remove_pin: bool = False) -> None:
        self.stickers = [None] * 5
        self.stamps = [None] * 5
        self.consumables = [None] * 10
        self.money = 0
        if remove_pin:
            self.pin = None

    def add_tile(self, tile: Tile) -> bool:
        """``Player.AddTileToInventory``."""
        from cursed_words_solver.sim.game.grid_util import add_tile_to_array, rack_count

        before = rack_count(self.consumables)
        self.consumables = add_tile_to_array(self, tile, self.consumables)
        return rack_count(self.consumables) > before

    def change_money(self, change: int) -> None:
        """``Player.ChangeMoney``."""
        self.money = max(0, self.money + int(change))
        if change > 0:
            self.run.stats.total_cash_earned += change
        if change < 0:
            for purse in self.unpacked_of("CoinPurse"):
                purse.fields["Count"] = int(purse.fields.get("Count", 0)) + 1

    def refresh_favourite_sticker(self) -> None:
        """Human Boy Left Hand: the sticker left of it gets ``LeftHandUpgrade``."""
        pin_var = self.pin.var(0) if self.pin is not None and self.pin.game_class == "HumanHands" else 0
        for s in self.stickers:
            if s is not None and s.is_hb_favourite_sticker:
                s.is_hb_favourite_sticker = False
                for _ in range(pin_var):
                    s.downgrade(0)
        left = next((s for s in self.stickers if s is not None and s.game_class == "LeftHumanHand"), None)
        if left is not None:
            idx = self.stickers.index(left)
            if idx > 0 and self.stickers[idx - 1] is not None:
                fav = self.stickers[idx - 1]
                fav.is_hb_favourite_sticker = True
                for _ in range(pin_var):
                    fav.upgrade(0)

    def refresh_underhand_target(self) -> None:
        for s in self.stickers:
            if s is not None and s.is_underhand_target:
                s.is_underhand_target = False
                for _ in range(3):
                    s.downgrade(0)
        under = next((s for s in self.stamps if s is not None and s.game_class == "Underhand"), None)
        if under is not None:
            idx = self.stamps.index(under)
            tgt = self.stickers[idx]
            if tgt is not None:
                tgt.is_underhand_target = True
                for _ in range(3):
                    tgt.upgrade(0)

    def randomise_item_order(self, rng: Rng, include_stamps: bool) -> None:
        """Capybara (``RandomiseItemOrder``)."""
        from cursed_words_solver.sim.game.grid_util import shuffle

        self.stickers = shuffle(rng, list(self.stickers))
        if include_stamps:
            self.stamps = shuffle(rng, list(self.stamps))
        self.refresh_favourite_sticker()

    def move_item(self, kind: str, src: int, dst: int) -> bool:
        """Drag to reorder (``ItemReorderController``): swap two slots."""
        arr = self.stickers if kind == "sticker" else self.stamps
        if not (0 <= src < 5 and 0 <= dst < 5) or src == dst or arr[src] is None:
            return False
        arr[src], arr[dst] = arr[dst], arr[src]
        if kind == "sticker":
            self.refresh_favourite_sticker()
        self.refresh_underhand_target()
        return True
