"""Types mirroring the game's shop advice enums and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ItemTag(StrEnum):
    NO_BUILD = "NoBuild"
    BLUE_BUILD = "BlueBuild"
    RED_BUILD = "RedBuild"
    VOID_BUILD = "VoidBuild"
    SHINY_BUILD = "ShinyBuild"
    CHESS_BUILD = "ChessBuild"
    BLANK_BUILD = "BlankBuild"
    COLOURLESS_BUILD = "ColourlessBuild"
    CASH_BUILD = "CashBuild"
    RAINBOW_BUILD = "RainbowBuild"
    CONSUMABLE_BUILD = "ConsumableBuild"
    CURSE_BUILD = "CurseBuild"
    NUMBERS_BUILD = "NumbersBuild"
    ARROW_BUILD = "ArrowBuild"
    CARDS_BUILD = "CardsBuild"
    BIG_NUMBERS_BUILD = "BigNumbersBuild"
    SCATTERED_ITEMS_BUILD = "ScatteredItemsBuild"


class ItemFunction(StrEnum):
    BUILD = "Build"
    SCORING = "Scoring"
    ADDITIVE = "Additive"
    MULTIPLIER = "Multiplier"
    SCATTERER = "Scatterer"
    OTHER = "Other"
    TILE = "Tile"


class ItemFunctionTag(StrEnum):
    GENERIC_ADDITIVE = "GenericAdditive"
    GENERIC_MULTIPLIER = "GenericMultiplier"
    SPECIFIC_MULTIPLIER = "SpecificMultiplier"
    SPECIFIC_ADDITIVE = "SpecificAdditive"
    SCATTERER = "Scatterer"
    TECH = "Tech"


BUILD_TAG_LABELS: dict[ItemTag, str] = {
    ItemTag.BLUE_BUILD: "BLUE",
    ItemTag.RED_BUILD: "RED",
    ItemTag.VOID_BUILD: "VOID",
    ItemTag.SHINY_BUILD: "SHINY",
    ItemTag.CHESS_BUILD: "CHESS",
    ItemTag.BLANK_BUILD: "?",
    ItemTag.COLOURLESS_BUILD: "COLOURLESS",
    ItemTag.CASH_BUILD: "MONEY",
    ItemTag.RAINBOW_BUILD: "RAINBOW",
    ItemTag.CONSUMABLE_BUILD: "CONSUMABLE",
    ItemTag.CURSE_BUILD: "CURSE",
    ItemTag.NUMBERS_BUILD: "NUMBERS",
    ItemTag.ARROW_BUILD: "ARROWS",
    ItemTag.CARDS_BUILD: "CARDS",
    ItemTag.BIG_NUMBERS_BUILD: "BIG NUMBERS",
    ItemTag.SCATTERED_ITEMS_BUILD: "ITEMS",
    ItemTag.NO_BUILD: "NO BUILD",
}

FUNCTION_TAG_MAP: dict[ItemFunction, frozenset[ItemFunctionTag]] = {
    ItemFunction.SCORING: frozenset(
        {
            ItemFunctionTag.GENERIC_ADDITIVE,
            ItemFunctionTag.SPECIFIC_ADDITIVE,
            ItemFunctionTag.GENERIC_MULTIPLIER,
            ItemFunctionTag.SPECIFIC_MULTIPLIER,
        }
    ),
    ItemFunction.ADDITIVE: frozenset(
        {
            ItemFunctionTag.GENERIC_ADDITIVE,
            ItemFunctionTag.SPECIFIC_ADDITIVE,
        }
    ),
    ItemFunction.MULTIPLIER: frozenset(
        {
            ItemFunctionTag.GENERIC_MULTIPLIER,
            ItemFunctionTag.SPECIFIC_MULTIPLIER,
        }
    ),
    ItemFunction.SCATTERER: frozenset({ItemFunctionTag.SCATTERER}),
    ItemFunction.OTHER: frozenset({ItemFunctionTag.TECH}),
    ItemFunction.BUILD: frozenset(
        {
            ItemFunctionTag.GENERIC_ADDITIVE,
            ItemFunctionTag.SPECIFIC_ADDITIVE,
            ItemFunctionTag.GENERIC_MULTIPLIER,
            ItemFunctionTag.SPECIFIC_MULTIPLIER,
            ItemFunctionTag.TECH,
            ItemFunctionTag.SCATTERER,
        }
    ),
}

FUNCTION_LABELS: dict[ItemFunction, str] = {
    ItemFunction.BUILD: "item",
    ItemFunction.SCORING: "scoring item",
    ItemFunction.ADDITIVE: "additive item",
    ItemFunction.MULTIPLIER: "multiplier",
    ItemFunction.SCATTERER: "tile scatterer",
    ItemFunction.OTHER: "item",
    ItemFunction.TILE: "consumable tile",
}


@dataclass
class GameShopItem:
    id: str
    name: str
    slot: str
    index: int
    price: int
    shop_advice_tags: frozenset[str] = field(default_factory=frozenset)
    function_tags: frozenset[str] = field(default_factory=frozenset)
    blacklisted: bool = False

    def has_build_tag(self, tag: ItemTag) -> bool:
        return tag.value in self.shop_advice_tags

    def fulfills_function(self, function: ItemFunction) -> bool:
        needed = FUNCTION_TAG_MAP.get(function, frozenset())
        return bool(self.function_tags.intersection({t.value for t in needed}))


@dataclass
class GameShopTile:
    index: int
    price: int
    color: str = ""
    curse: str = ""
    letter: str = ""
    sold: bool = False


@dataclass
class BuildData:
    build_tag: ItemTag
    relevant_items: list[GameShopItem]
    function_tag_counts: dict[ItemFunction, int]


@dataclass
class AdviceData:
    build: ItemTag
    recommended_items: list[GameShopItem] = field(default_factory=list)
    recommended_tiles: list[GameShopTile] = field(default_factory=list)
    function_fulfilled: ItemFunction = ItemFunction.OTHER
    is_generic: bool = False
    is_upgrade: bool = False
    should_freeze: bool = False
    should_buy: bool = False
    should_upgrade: bool = False
    should_restock: bool = False
    should_leave: bool = False
    should_sell: bool = False
    is_free_item: bool = False
    specific_reason: str = ""


def player_should_restock(player_money: int, restock_price: int) -> bool:
    if player_money < restock_price:
        return False
    if restock_price <= 2:
        return True
    if restock_price >= 6:
        return False
    return player_money // 2 > restock_price


@dataclass
class ShopAdviceContext:
    money: int
    sticker_count: int
    stamp_count: int
    tile_count: int
    inventory: list[GameShopItem]
    shop_items: list[GameShopItem]
    shop_tiles: list[GameShopTile]
    restock_cost: int
    free_item_available: bool
    unlocks: frozenset[str] = field(default_factory=frozenset)
    block_restock: bool = False
    block_sell: bool = False
    sticker_shop_enabled: bool = True
    stamp_shop_enabled: bool = True
