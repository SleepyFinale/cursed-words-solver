"""Player inventory for full-run simulation (``Player`` stickers/stamps/pin/tiles/money).

``to_loadout`` produces the same ``Loadout`` shape melmod exports, so the existing
engine scores simulated boards unchanged.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.sim.catalog import ItemDef, RunCatalog
from cursed_words_solver.sim.run_rules import (
    CONSUMABLE_SLOTS,
    CONSUMABLE_SLOTS_WITHOUT_STADIUM,
    STAMP_SLOTS,
    STARTING_COLOURS,
    STICKER_SLOTS,
    max_upgrade_count,
    sell_value,
)

# Player.GetOrderedBuildSynergyTags candidate list (in game order).
BUILD_SYNERGY_TAGS = (
    "BlueBuild", "RedBuild", "VoidBuild", "ShinyBuild", "ChessBuild", "BlankBuild",
    "ColourlessBuild", "CashBuild", "RainbowBuild", "ConsumableBuild", "CurseBuild",
    "NumbersBuild", "ArrowBuild", "CardsBuild", "BigNumbersBuild", "ScatteredItemsBuild",
)
# Item.GeneratorTags
GENERATOR_TAGS = (
    "BlankGenerator", "BlueGenerator", "RedGenerator", "CashGenerator", "VoidGenerator",
    "ShinyGenerator", "ArrowGenerator", "CurrencyGenerator", "ChessGenerator",
    "CardsGenerator", "NumbersGenerator", "ItemScatterer",
)


@dataclass
class OwnedItem:
    item: ItemDef
    times_upgraded: int = 0
    foil: bool = False
    money_invested: list[int] = field(default_factory=list)
    # Pins upgrade per side (left = component 0, right = component 1).
    side_levels: list[int] = field(default_factory=list)

    @property
    def level(self) -> int:
        return 1 + self.times_upgraded

    @property
    def max_upgrades(self) -> int:
        return max_upgrade_count(foil=self.foil, hungry_hippo=self.item.game_class == "HungryHippo")

    @property
    def is_maxed(self) -> bool:
        return self.times_upgraded >= self.max_upgrades

    def side_value(self, side: int) -> int:
        """Pin component VariableValue after upgrades (base + increment per level)."""
        base = self.item.component_values[side]
        inc = self.item.component_increments[side]
        return base + inc * (self.side_levels[side] - 1)


@dataclass
class ConsumableTile:
    glyph: str  # letter | blank | number | fraction | joker | chess
    value: str = ""  # letter, digit, fraction "1/2", or chess piece name
    colour: str = "normal"
    suit: str = ""
    price: int = 0


@dataclass
class Inventory:
    character: str  # game class, e.g. "WetDennis"
    character_name: str
    pin: OwnedItem | None
    stickers: list[OwnedItem] = field(default_factory=list)
    stamps: list[OwnedItem] = field(default_factory=list)
    tiles: list[ConsumableTile] = field(default_factory=list)
    money: int = 0
    available_colours: list[str] = field(default_factory=lambda: list(STARTING_COLOURS))
    embargoed: set[str] = field(default_factory=set)
    sticker_slots: int = STICKER_SLOTS
    stamp_slots: int = STAMP_SLOTS

    @classmethod
    def new_run(cls, catalog: RunCatalog, character: str) -> Inventory:
        char = catalog.character(character)
        pin_def = catalog.items.get(char.pin_class)
        pin = None
        if pin_def is not None:
            pin = OwnedItem(pin_def, side_levels=[1] * len(pin_def.component_values))
        return cls(character=char.game_class, character_name=char.name, pin=pin)

    def clone(self) -> Inventory:
        return copy.deepcopy(self)

    # -- queries mirroring Player ------------------------------------------------

    def all_items(self) -> list[OwnedItem]:
        """``Player.GetAllItems`` — pin, then stickers, then stamps."""
        out: list[OwnedItem] = []
        if self.pin is not None:
            out.append(self.pin)
        return out + self.stickers + self.stamps

    def has(self, game_class: str) -> bool:
        return any(o.item.game_class == game_class for o in self.all_items())

    def count(self, game_class: str) -> int:
        return sum(1 for o in self.all_items() if o.item.game_class == game_class)

    def owned_sticker(self, game_class: str) -> OwnedItem | None:
        return next((o for o in self.stickers if o.item.game_class == game_class), None)

    def owned_stamp(self, game_class: str) -> OwnedItem | None:
        return next((o for o in self.stamps if o.item.game_class == game_class), None)

    def consumable_capacity(self) -> int:
        return CONSUMABLE_SLOTS if self.has("Stadium") else CONSUMABLE_SLOTS_WITHOUT_STADIUM

    def ordered_build_synergy_tags(self) -> list[str]:
        """``Player.GetOrderedBuildSynergyTags`` — by count desc, ties in first-seen order."""
        counts: dict[str, int] = {}
        for owned in self.all_items():
            for tag in owned.item.tags:
                if tag in BUILD_SYNERGY_TAGS:
                    counts[tag] = counts.get(tag, 0) + 1
        if not counts:
            return []
        out: list[str] = []
        for n in range(max(counts.values()), 0, -1):
            out.extend(tag for tag, c in counts.items() if c == n)
        return out

    def unfulfilled_dependency_tags(self) -> list[str]:
        """``Player.GetUnfulfilledDependencyTags`` (fixed-point over enabled tags)."""
        active: list[str] = []
        changed = True
        while changed:
            changed = False
            for owned in self.all_items():
                new = [t for t in owned.item.tags if t not in active]
                if not new:
                    continue
                deps = owned.item.dependency_tags
                if not deps or any(d in active for d in deps):
                    active.extend(new)
                    changed = True
        out: list[str] = []
        for owned in self.all_items():
            out.extend(t for t in owned.item.dependency_tags if t not in out and t not in active)
        return out

    def has_generator(self) -> bool:
        return any(t in GENERATOR_TAGS for o in self.all_items() for t in o.item.tags)

    def pin_upgrade_options(self) -> list[str]:
        """Boss-reward pin draft: left or right; ID Card adds "both"."""
        if self.pin is None or len(self.pin.side_levels) < 2:
            return []
        return ["left", "right", "both"] if self.has("IDCard") else ["left", "right"]

    def upgrade_pin(self, choice: str) -> None:
        """``BossRewardController.TakeUpgrade*`` (Human Boy hand side-effect not ported)."""
        if choice not in self.pin_upgrade_options():
            raise ValueError(choice)
        assert self.pin is not None
        if choice in ("left", "both"):
            self.pin.side_levels[0] += 1
        if choice in ("right", "both"):
            self.pin.side_levels[1] += 1

    def sell_price(self, owned: OwnedItem) -> int:
        return sell_value(owned.money_invested, receipt=self.has("Receipt") and owned.item.game_class != "Receipt")

    # -- conversion for the scoring engine -------------------------------------

    def to_loadout(self, *, extras: dict[str, Any] | None = None) -> Loadout:
        out_extras: dict[str, Any] = dict(extras or {})
        if self.pin is not None:
            out_extras["pin_effect"] = self.pin.item.slug
            if len(self.pin.side_levels) >= 2:
                out_extras["pin_left_level"] = str(self.pin.side_levels[0])
                out_extras["pin_right_level"] = str(self.pin.side_levels[1])
                out_extras["pin_left_variable"] = str(self.pin.side_value(0))
                out_extras["pin_right_variable"] = str(self.pin.side_value(1))
        out_extras["sticker_order"] = _json_list(o.item.slug for o in self.stickers)
        out_extras["stamp_order"] = _json_list(o.item.slug for o in self.stamps)
        foils = [o.item.slug for o in self.stickers if o.foil]
        if foils:
            out_extras["foil_sticker_ids"] = foils
        return Loadout(
            character=self.character_name,
            pin_branch="",
            stickers=[LoadoutItem(o.item.slug, o.item.name, o.level, "sticker") for o in self.stickers],
            stamps=[LoadoutItem(o.item.slug, o.item.name, 1, "sticker") for o in self.stamps],
            money=self.money,
            extras=out_extras,
        )


def _json_list(values) -> str:
    import json

    return json.dumps(list(values), separators=(",", ":"))
