"""Game ``Item`` port: catalog-backed instances plus every non-scoring hook.

Scoring (``ApplyTileBonus`` / ``ApplyWordBonus``) stays in the engine
(``cursed_words_solver.engine``); this module ports what the engine never needed:
``ApplyStartOfGridEffect`` / ``FinalStartOfGridEffect``, ``StartOfEncounterSetUp``,
``OnAcquire``, overridden ``Upgrade`` / ``Downgrade``, ``GetSellValue``,
``RandomiseRelevantColours`` and ``GetCost``. Item counters live in ``fields``
under the game's field names, which is what melmod's ``game_state`` exports and the
engine reads (``engine.calc._ITEM_STATE_FIELDS``).
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Callable

from cursed_words_solver.engine.item_data import CLASS_TO_SLUG, POOLS
from cursed_words_solver.paths import data_path
from cursed_words_solver.sim.game import core as C
from cursed_words_solver.sim.game.core import Rng, Tile, randomly_curse_tile
from cursed_words_solver.sim.game.grid_util import (
    GenCtx,
    contains_2x2,
    knight_targets,
    remove_tile_from_array,
    shuffle,
    tile_for_item_scatter,
)

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.player import Player

GENERATOR_TAGS = (
    "BlankGenerator", "BlueGenerator", "RedGenerator", "CashGenerator", "VoidGenerator",
    "ShinyGenerator", "ArrowGenerator", "CurrencyGenerator", "ChessGenerator",
    "CardsGenerator", "NumbersGenerator", "ItemScatterer",
)

# ---------------------------------------------------------------------------- catalog


@lru_cache(maxsize=1)
def catalog_rows() -> dict[str, dict[str, Any]]:
    data = json.loads(data_path("data", "game", "run_catalog.json").read_text(encoding="utf-8"))
    return {row["type"]: row for row in data.get("items") or () if row.get("ok")}


def slug_for(game_class: str) -> str:
    if game_class in CLASS_TO_SLUG:
        return CLASS_TO_SLUG[game_class]
    import re

    return re.sub(r"(?<!^)(?=[A-Z])", "_", game_class).lower()


# ---------------------------------------------------------------------------- base


class Item:
    """One live game item (sticker: 1 component, stamp: 0, pin: 2)."""

    game_class = ""

    def __init__(self, game_class: str | None = None) -> None:
        cls = game_class or type(self).game_class
        row = catalog_rows().get(cls)
        if row is None:
            raise KeyError(f"unknown item class {cls!r}")
        self.game_class = cls
        self.slug = slug_for(cls)
        self.name = row.get("name") or cls
        self.rarity = row.get("rarity") or "Common"
        self.base_cost = int(row.get("cost") or 0)
        self.sell_cost = int(row.get("sell_cost") or 0)
        self.components: list[list[int]] = [
            [int(c.get("level", 1)), int(c.get("increment", 0)), int(c.get("value", 0))]
            for c in row.get("components") or ()
        ]
        self.tags: list[str] = list(row.get("tags") or ())
        self.dependency_tags: list[str] = list(row.get("dependency_tags") or ())
        self.function_tags: list[str] = list(row.get("function_tags") or ())
        self.relevant_colours: list[str] = [C.TYPE_FROM_GAME.get(c, c.lower()) for c in row.get("relevant_colours") or ()]
        self.is_food = bool(row.get("is_food"))
        self.is_animal = bool(row.get("is_animal"))
        self.selling_prevented = bool(row.get("selling_prevented"))
        self.costs_money_to_sell = cls in ("StickerPadlock", "StampPadlock")
        self.times_upgraded = 0
        self.discount = 0
        self.is_foil = False
        self.money_invested: list[int] = []
        self.fields: dict[str, Any] = {}
        self.is_hb_favourite_sticker = False
        self.is_underhand_target = False
        self.wrapped_present_index = 0
        self.init_fields()

    def init_fields(self) -> None:
        """Per-class field defaults (constructor initialisers)."""

    # -- components ---------------------------------------------------------------

    @property
    def is_sticker(self) -> bool:
        return len(self.components) == 1

    @property
    def is_stamp(self) -> bool:
        return len(self.components) == 0

    @property
    def is_pin(self) -> bool:
        return len(self.components) == 2

    def var(self, i: int = 0) -> int:
        return self.components[i][2] if i < len(self.components) else 0

    def level(self, i: int = 0) -> int:
        return self.components[i][0] if i < len(self.components) else 0

    def _base_upgrade(self, i: int) -> None:
        comp = self.components[i]
        comp[0] += 1
        comp[2] += comp[1]

    def _base_downgrade(self, i: int) -> None:
        comp = self.components[i]
        comp[0] -= 1
        comp[2] -= comp[1]

    def upgrade(self, i: int = 0, both: bool = False, *, rng: Rng | None = None, player: "Player | None" = None) -> None:
        """``Item.Upgrade``."""
        if both:
            self._base_upgrade(0)
            self._base_upgrade(1)
        else:
            self._base_upgrade(i)

    def downgrade(self, i: int = 0) -> None:
        self._base_downgrade(i)

    def can_be_upgraded(self, max_upgrades: int) -> bool:
        return self.game_class != "LeftHumanHand" and self.is_sticker and self.times_upgraded < max_upgrades

    # -- economy ------------------------------------------------------------------

    def sell_value(self, player: "Player") -> int:
        """``Item.GetSellValue`` (Nest Egg overrides)."""
        if player.unpacked_of("Receipt") and self.game_class != "Receipt":
            return max(0, sum(self.money_invested))
        total = 0
        for j, paid in enumerate(self.money_invested):
            total += paid // 2 if j == 0 else paid // 4
        return max(0, total)

    def mentions_red(self) -> bool:
        """``GetDescription().Contains("red")`` — approximated from tags / colours."""
        return "RedBuild" in self.tags or C.RED in self.relevant_colours

    def get_cost(self, player: "Player") -> int:
        """``Item.GetCost``."""
        price = max(self.base_cost - self.discount, 0)
        red = self.mentions_red()
        for it in player.all_items_unpacked_shallow():
            if it.game_class == "Avocado":
                price *= 2
            if it.game_class == "NorthernCardinal" and red:
                price = max(0, price - 4)
            if it.game_class == "BlessingOfTheShopkeeper":
                price = 10
        return max(0, price)

    # -- hooks (overridden per class) ----------------------------------------------

    def start_of_grid(self, g: GenCtx) -> None:
        """``ApplyStartOfGridEffect``."""

    def final_start_of_grid(self, g: GenCtx) -> None:
        """``FinalStartOfGridEffect``."""

    def start_of_encounter(self, player: "Player", rng: Rng) -> None:
        """``StartOfEncounterSetUp``."""

    def on_acquire(self, player: "Player", rng: Rng) -> None:
        """``OnAcquire`` (shop-side effects routed through ``player.shop_hook``)."""

    def randomise_relevant_colours(self, player: "Player", rng: Rng) -> None:
        """``Item.RandomiseRelevantColours`` (Colour Swap / Can of Beans)."""
        held = [i for i in player.unpacked_of(self.game_class, for_comparison=True)]
        if held:
            self.relevant_colours = list(held[0].relevant_colours)
            return
        n = len(self.relevant_colours)
        pool = [C.RED, C.BLUE, C.SHINY, C.VOID, C.CACTUS, C.PINK, C.GOLD, C.GREEN, C.PURPLE, C.WHITE]
        self.relevant_colours = []
        for _ in range(n):
            self.relevant_colours.append(pool.pop(rng.range(0, len(pool))))

    def accumulator_words(self) -> list[str]:
        return []

    def nested_items(self) -> list["Item"]:
        return []

    # -- copies / serialisation ---------------------------------------------------

    def fresh_copy(self) -> "Item":
        """``Activator.CreateInstance`` + ``Upgrade(0)`` to the same component-0 level."""
        it = make_item(self.game_class)
        if self.components and self.level(0) > 1:
            for _ in range(self.level(0) - 1):
                it.upgrade(0)
        return it

    def clone(self) -> "Item":
        return copy.deepcopy(self)

    def to_state(self) -> dict[str, Any]:
        """melmod ``game_state`` item row."""
        out: dict[str, Any] = {
            "id": self.slug,
            "class": self.game_class,
            "levels": [c[0] for c in self.components],
            "values": [c[2] for c in self.components],
            "colours": [C.GAME_TYPE_NAMES.get(c, c) for c in self.relevant_colours],
            "fields": self.state_fields(),
        }
        nested = self.nested_items()
        if nested:
            out["nested"] = [n.to_state() for n in nested if n is not None]
        return out

    def state_fields(self) -> dict[str, Any]:
        return {k: v for k, v in self.fields.items() if isinstance(v, (int, float, str, bool, list, dict))}

    def __repr__(self) -> str:  # pragma: no cover
        lv = "/".join(str(c[0]) for c in self.components)
        return f"<{self.game_class}{' L' + lv if lv else ''}{' foil' if self.is_foil else ''}>"


_REGISTRY: dict[str, type[Item]] = {}


def register(cls: type[Item]) -> type[Item]:
    _REGISTRY[cls.game_class] = cls
    return cls


def make_item(game_class: str) -> Item:
    cls = _REGISTRY.get(game_class)
    return cls() if cls is not None else Item(game_class)


def item_for_slug(slug: str) -> Item:
    for cls, s in CLASS_TO_SLUG.items():
        if s == slug:
            return make_item(cls)
    raise KeyError(slug)


# ---------------------------------------------------------------------------- scattered pools

_POOL_ORDER = (
    "RedBuildItems", "BlueBuildItems", "VoidBuildItems", "ShinyBuildItems", "RainbowBuildItems",
    "NumberBuildItems", "ChessBuildItems", "UtilityItems", "ColourlessBuildItems",
    "GenericMultItems", "CardBuildItems", "CursedBuildItems",
)
_SLUG_TO_CLASS = {s: c for c, s in CLASS_TO_SLUG.items()}


def _pool_classes(name: str) -> list[str]:
    return [_SLUG_TO_CLASS[s] for s in POOLS.get(name, ()) if s in _SLUG_TO_CLASS]


def rarity_weighted_item(rng: Rng, classes: list[str]) -> Item:
    """``ScatteredItemPools.GetRarityWeightedItem`` (fully unlocked)."""
    rows = catalog_rows()
    common: list[str] = []
    rare: list[str] = []
    legendary: list[str] = []
    for c in classes:
        r = (rows.get(c) or {}).get("rarity", "Common")
        bucket = common if r == "Common" else rare if r == "Rare" else legendary if r == "Legendary" else None
        if bucket is not None and c not in bucket:
            bucket.append(c)
    roll = rng.range(0, 100)
    if roll == 0 and legendary:
        return make_item(legendary[rng.range(0, len(legendary))])
    if roll < 10 and rare:
        return make_item(rare[rng.range(0, len(rare))])
    if not common:
        return make_item("GraduationCap")
    return make_item(common[rng.range(0, len(common))])


def random_scattered_item(rng: Rng, player: "Player | None" = None) -> Item:
    """``ScatteredItemPools.GetRandomItem``."""
    seen: list[str] = []
    for name in _POOL_ORDER:
        for c in _pool_classes(name):
            seen.append(c)
    return rarity_weighted_item(rng, seen)


def random_pool_item(rng: Rng, pool: str) -> Item:
    return rarity_weighted_item(rng, _pool_classes(pool))


def random_colour_build_item(rng: Rng, colour: str) -> Item | None:
    name = {C.RED: "RedBuildItems", C.BLUE: "BlueBuildItems", C.VOID: "VoidBuildItems"}.get(colour)
    return random_pool_item(rng, name) if name else None


# ---------------------------------------------------------------------------- tile type rolls

TILE_TYPE_WEIGHTS = {
    C.NORMAL: 24, C.RED: 4, C.BLUE: 4, C.VOID: 3, C.SHINY: 1, C.PURPLE: 2,
    C.GOLD: 2, C.WHITE: 2, C.PINK: 2, C.GREEN: 2, C.CACTUS: 2,
}


def random_coloured_tile_type(rng: Rng, player: "Player") -> str:
    """``ItemPools.GetRandomColouredTileTypeWeighted``."""
    avail = player.run.available_colours
    weights = {k: v for k, v in TILE_TYPE_WEIGHTS.items() if k in avail and k != C.NORMAL}
    return C.weighted_pick(rng, weights)


def random_tile_type(rng: Rng, player: "Player") -> str:
    """``ItemPools.GetRandomTileTypeWeighted`` (Normal is never available)."""
    avail = player.run.available_colours
    weights = {k: v for k, v in TILE_TYPE_WEIGHTS.items() if k in avail}
    return C.weighted_pick(rng, weights)


# ---------------------------------------------------------------------------- helpers


def _scatter_colour(item: Item, g: GenCtx, colour: str, count: int, glyph: str = C.G_NONE) -> list[Tile]:
    out = []
    for _ in range(count):
        t = tile_for_item_scatter(g, colour, glyph)
        if t is not None:
            t.tile_type = colour
            out.append(t)
    return out


def _cursed_copy_scatter(g: GenCtx, count: int) -> None:
    """Amphora / Ghost: RandomlyCurseTile then copy onto a scatter tile."""
    for _ in range(count):
        tile = Tile()
        randomly_curse_tile(tile, g.rng, g.player, True)
        target = tile_for_item_scatter(g, C.NORMAL, tile.get_glyph(), None, tile.is_suited_card())
        if target is not None:
            tile.tile_type = target.tile_type
            if tile.suit == C.SUIT_NONE:
                tile.set_suit(target.suit)
            target.set_as_copy(tile, False)


def _upgrade_scattered(item: Item | None, levels: int) -> None:
    if item is not None and item.is_sticker:
        for _ in range(levels):
            item.upgrade(0)


def _add_colour(player: "Player", colour: str) -> None:
    if colour not in player.run.available_colours:
        player.run.available_colours.append(colour)


# ---------------------------------------------------------------------------- items


@register
class Abacus(Item):
    game_class = "Abacus"

    def start_of_grid(self, g: GenCtx) -> None:
        nums = [1, 2, 3, 4, 5]
        for i in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_NUMBER)
            if t is not None:
                n = nums[g.rng.range(0, len(nums))] if nums else i + 1
                t.set_number(n)
                if n in nums:
                    nums.remove(n)

    def upgrade(self, i=0, both=False, **kw) -> None:
        if both:
            self.upgrade(0)
            self.upgrade(1)
            return
        self._base_upgrade(i)
        if self.level(0) >= 2 and "NumbersGenerator" not in self.tags:
            self.tags.append("NumbersGenerator")


@register
class AkoyaPearl(Item):
    game_class = "AkoyaPearl"

    def start_of_grid(self, g: GenCtx) -> None:
        w, h = g.grid.width, g.grid.height
        if w % 2 == 0 or h % 2 == 0:
            return
        t = g.grid.available_at(w // 2, h // 2)
        if t is not None and not t.is_type(self.relevant_colours[0]):
            t.tile_type = self.relevant_colours[0]


@register
class Amphora(Item):
    game_class = "Amphora"

    def start_of_grid(self, g: GenCtx) -> None:
        _cursed_copy_scatter(g, self.var(0))


@register
class AprilShower(Item):
    game_class = "AprilShower"

    def init_fields(self) -> None:
        self.fields["ChosenLetters"] = []

    def _choose(self, rng: Rng) -> None:
        letters = list(C.LETTERS)
        for _ in range(self.var(0)):
            if not letters:
                break
            self.fields["ChosenLetters"].append(letters.pop(rng.range(0, len(letters))))

    def start_of_grid(self, g: GenCtx) -> None:
        if g.grid_number == 1:
            self.fields["ChosenLetters"] = []
            self._choose(g.rng)
        chosen = self.fields["ChosenLetters"]
        for t in g.grid.available():
            if t.srep() in chosen and not t.is_type(self.relevant_colours[0]):
                t.tile_type = self.relevant_colours[0]

    def on_acquire(self, player, rng) -> None:
        self._choose(rng)


@register
class Backpack(Item):
    game_class = "Backpack"

    def start_of_grid(self, g: GenCtx) -> None:
        colour = self.relevant_colours[0]
        whites = blacks = 0

        def row(y: int) -> list[Tile]:
            return [t for t in g.grid.available() if t.y == y]

        for _ in range(self.var(0)):
            white = whites < 5 and (blacks >= 5 or g.rng.range(0, 2) == 1)
            t = tile_for_item_scatter(g, colour, C.G_CHESS, row(1) if white else row(g.grid.height - 2))
            if t is None:
                white = not white
                t = tile_for_item_scatter(g, colour, C.G_CHESS, row(1) if white else row(g.grid.height - 2))
                if t is None:
                    continue
            whites += 1 if white else 0
            blacks += 0 if white else 1
            t.tile_type = colour
            t.set_chess(C.PAWN, white)


@register
class Bank(Item):
    game_class = "Bank"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in g.grid.available():
            if t.get_glyph() == C.G_LETTER and t.srep(True) in C.CURRENCY_FROM_LETTER:
                t.set_currency(C.CURRENCY_FROM_LETTER[t.srep(True)])


@register
class BarChart(Item):
    game_class = "BarChart"
    WORDS = (
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
        "nineteen", "twenty", "twentyone", "twentytwo", "twentythree", "twentyfour", "twentyfive",
    )

    def init_fields(self) -> None:
        self.fields["NumbersFound"] = [0] * len(self.WORDS)

    def accumulator_words(self) -> list[str]:
        return list(self.WORDS)

    def start_of_grid(self, g: GenCtx) -> None:
        for i, n in enumerate(self.fields["NumbersFound"]):
            for _ in range(max(0, n)):
                t = tile_for_item_scatter(g, C.NORMAL, C.G_NUMBER)
                if t is not None:
                    t.set_number(i + 1)


@register
class BeamMeUp(Item):
    game_class = "BeamMeUp"

    def start_of_grid(self, g: GenCtx) -> None:
        idx = g.player.stamp_index(self)
        rack = g.rack
        picks = [rack[idx] if 0 <= idx < len(rack) else None, rack[idx + 5] if 0 <= idx + 5 < len(rack) else None]
        if all(p is None for p in picks):
            return
        for src in picks:
            if src is None:
                continue
            t = tile_for_item_scatter(g, src.tile_type, src.get_glyph(), None, src.is_suited_card())
            if t is None:
                return
            t.set_as_copy(src, False)
            t.was_consumable = True
            t.already_on_rack = False
            g.player.run.stats_consumables_used += 1
            for ninja in g.player.unpacked_of("TileNinja"):
                ninja.fields["ConsumableTilesUsed"] = int(ninja.fields.get("ConsumableTilesUsed", 0)) + 1


@register
class Beefeater(Item):
    game_class = "Beefeater"

    def start_of_grid(self, g: GenCtx) -> None:
        for letter in ("j", "q", "k"):
            t = tile_for_item_scatter(g, self.relevant_colours[0], C.G_LETTER, None, True)
            if t is not None:
                t.set_letter(letter)
                t.set_suit(C.random_card_suit(g.rng))
                t.tile_type = self.relevant_colours[0]


@register
class Bicycle(Item):
    game_class = "Bicycle"

    def init_fields(self) -> None:
        self.fields["WordScoreBonus"] = 0

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_NONE, None, True)
            if t is not None:
                t.set_suit(C.random_card_suit(g.rng))


@register
class BigBang(Item):
    game_class = "BigBang"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None or not last.tiles or not last.tiles[0].is_type(self.relevant_colours[0]):
            return
        _scatter_colour(self, g, self.relevant_colours[0], len(last.tiles))


@register
class BlackHole(Item):
    game_class = "BlackHole"

    def start_of_grid(self, g: GenCtx) -> None:
        c = self.relevant_colours[0]
        n = sum(1 for t in g.grid.available() if t.is_type(c))
        for _ in range(n):
            t = tile_for_item_scatter(g, c, C.G_NONE)
            if t is None:
                break
            t.tile_type = c


@register
class Bomb(Item):
    game_class = "Bomb"

    def init_fields(self) -> None:
        self.fields["WordScoreBonus"] = 0

    def start_of_grid(self, g: GenCtx) -> None:
        c = self.relevant_colours[0]
        changed: list[Tile] = []
        frontier: list[Tile] = []
        first = tile_for_item_scatter(g, c, C.G_NONE)
        if first is not None:
            first.tile_type = c
            changed.append(first)
            from cursed_words_solver.sim.game.core import adjacent_tiles

            frontier.extend(adjacent_tiles(g.grid, first.x, first.y, g.player))
        n = g.rng.range(2, 7)
        for _ in range(n):
            t = tile_for_item_scatter(g, c, C.G_NONE, frontier)
            if t is not None:
                from cursed_words_solver.sim.game.core import adjacent_tiles

                t.tile_type = c
                changed.append(t)
                frontier.extend(adjacent_tiles(g.grid, t.x, t.y, g.player))
                ids = {id(x) for x in changed}
                frontier = [x for x in frontier if id(x) not in ids]


@register
class Briefcase(Item):
    game_class = "Briefcase"

    def start_of_grid(self, g: GenCtx) -> None:
        n = 5 - len(g.player.stickers_list(for_comparison=True))
        for _ in range(max(0, n)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_ITEM)
            if t is not None:
                t.set_item(random_pool_item(g.rng, "GenericMultItems"))


@register
class Bucket(Item):
    game_class = "Bucket"

    def init_fields(self) -> None:
        self.tiles_in_bucket: list[Tile] = []
        self.next_tiles: list[Tile | None] = [None, None]
        self.fields["MostRecentUpgrade"] = 0

    def _tile_tags(self, t: Tile) -> None:
        if "CardsBuild" not in self.tags and (t.get_glyph() == C.G_CARD or t.suit != C.SUIT_NONE):
            self.tags.append("CardsBuild")
        if "BlankBuild" not in self.tags and t.get_glyph() == C.G_BLANK:
            self.tags.append("BlankBuild")
        elif "CashBuild" not in self.tags and t.get_glyph() == C.G_CURRENCY:
            self.tags.append("CashBuild")
        elif "NumbersBuild" not in self.tags and t.get_glyph() in (C.G_NUMBER, C.G_FRACTION):
            self.tags.append("NumbersBuild")
        elif "ChessBuild" not in self.tags and t.get_glyph() == C.G_CHESS:
            self.tags.append("ChessBuild")

    @staticmethod
    def possible_tile(rng: Rng, kind: int) -> Tile:
        t = Tile()
        suited = rng.range(0, 10) == 0
        if kind == 0:
            t.set_glyph(C.G_BLANK)
        elif kind == 1:
            if rng.range(0, 2) == 0:
                t.set_number(rng.range(1, 6))
            else:
                t.set_fraction(C.random_fraction(rng))
        elif kind == 2:
            t.set_chess(*C.random_chess_piece(rng))
        elif kind == 3:
            t.set_letter(C.random_currency(rng))
            t.set_glyph(C.G_CURRENCY)
        elif kind == 4:
            if rng.range(0, 10) == 0:
                t.set_glyph(C.G_CARD)
                t.set_suit(C.SUIT_JOKER)
                return t
            suited = True
            t.set_letter(C.LETTERS[rng.range(0, 26)])
        if suited:
            t.set_suit(C.random_card_suit(rng))
        return t

    def populate_next(self, rng: Rng) -> None:
        kinds = [0, 1, 2, 3, 4]
        a = kinds.pop(rng.range(0, len(kinds)))
        b = kinds[rng.range(0, len(kinds))]
        self.next_tiles = [self.possible_tile(rng, a), self.possible_tile(rng, b)]

    def upgrade(self, i=0, both=False, *, rng: Rng | None = None, player=None) -> None:
        rng = rng or Rng(0)
        if both:
            for t in self.next_tiles:
                if t is not None:
                    self.tiles_in_bucket.append(t)
                    self._tile_tags(t)
            self._base_upgrade(0)
            self._base_upgrade(1)
            self.fields["MostRecentUpgrade"] = 1
        else:
            self._base_upgrade(i)
            t = self.next_tiles[i] if i < 2 else None
            if t is not None:
                self.tiles_in_bucket.append(t)
                self._tile_tags(t)
            self.fields["MostRecentUpgrade"] = i
        self.populate_next(rng)

    def start_of_grid(self, g: GenCtx) -> None:
        for src in self.tiles_in_bucket:
            t = tile_for_item_scatter(g, src.tile_type, src.get_glyph(), None, True)
            if t is not None:
                t.set_as_copy(src, False)

    def start_of_encounter(self, player, rng) -> None:
        if not self.tiles_in_bucket:
            t = self.possible_tile(rng, rng.range(0, 5))
            self.tiles_in_bucket.append(t)
            self._tile_tags(t)
        self.populate_next(rng)


@register
class BusinessGoose(Item):
    game_class = "BusinessGoose"

    def start_of_grid(self, g: GenCtx) -> None:
        pawns = [t for t in g.grid.available() if t.get_glyph() == C.G_CHESS and t.piece == C.PAWN]
        pieces = [C.KNIGHT, C.ROOK, C.BISHOP, C.QUEEN]
        while pawns:
            t = pawns[g.rng.range(0, len(pawns))]
            t.set_chess(pieces[g.rng.range(0, len(pieces))], t.white)
            pawns.remove(t)


@register
class BusySchedule(Item):
    game_class = "BusySchedule"

    def start_of_grid(self, g: GenCtx) -> None:
        pool = list(g.grid.available())
        for i in range(1, len(pool) + 1):
            t = pool[g.rng.range(0, len(pool))]
            t.set_number(i)
            pool.remove(t)


@register
class Candle(Item):
    game_class = "Candle"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, self.relevant_colours[0], C.G_CURRENCY)
            if t is not None:
                t.tile_type = self.relevant_colours[0]
                t.set_currency(C.random_currency(g.rng))


@register
class CarouselHorse(Item):
    game_class = "CarouselHorse"

    def start_of_grid(self, g: GenCtx) -> None:
        knights: list[Tile] = []
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_CHESS)
            if t is not None:
                t.set_chess(C.KNIGHT, g.rng.range(0, 2) == 0)
                knights.append(t)
        for k in knights:
            for target in knight_targets(g.grid, k, g.player):
                target.multiply_tile_value(2, g.player)


@register
class CarpStreamers(Item):
    game_class = "CarpStreamers"

    def start_of_grid(self, g: GenCtx) -> None:
        _scatter_colour(self, g, self.relevant_colours[0], self.var(0))
        _scatter_colour(self, g, self.relevant_colours[1], self.var(1))

    def upgrade(self, i=0, both=False, **kw) -> None:
        if both:
            self.upgrade(0)
            self.upgrade(1)
            return
        self._base_upgrade(i)
        self.tags = []
        if self.level(0) - self.level(1) >= 2:
            self.tags += ["RedBuild", "RedGenerator"]
        elif self.level(1) - self.level(0) >= 2:
            self.tags += ["BlueBuild", "BlueGenerator"]
        else:
            self.tags += ["RedBuild", "BlueBuild", "RainbowBuild"]
            if self.level(0) >= 2:
                self.tags.append("RedGenerator")
            if self.level(1) >= 2:
                self.tags.append("BlueGenerator")


@register
class Castle(Item):
    game_class = "Castle"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in g.grid.available():
            if t.get_glyph() != C.G_CHESS:
                continue
            t.value_modifier = 0
            v = t.get_value(g.player)
            t.value_modifier = self.var(0) + v if t.tile_type == C.VOID else self.var(0) - v


@register
class Champagne(Item):
    game_class = "Champagne"

    def start_of_grid(self, g: GenCtx) -> None:
        coloured = [t for t in g.grid.available() if not t.is_type(C.NORMAL)]
        n = len(coloured) // 5 * self.var(0)
        if n <= 0:
            return
        cands = [t for t in coloured if not t.is_type(self.relevant_colours[0])]
        for _ in range(n):
            if not cands:
                break
            t = cands.pop(g.rng.range(0, len(cands)))
            t.tile_type = self.relevant_colours[0]


@register
class Cherries(Item):
    game_class = "Cherries"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None:
            return
        n = sum(1 for t in last.tiles if t.is_type(self.relevant_colours[0]))
        if n:
            _scatter_colour(self, g, self.relevant_colours[0], n * self.var(0))


@register
class ChessBoard(Item):
    game_class = "ChessBoard"

    def start_of_grid(self, g: GenCtx) -> None:
        c = self.relevant_colours[0]
        for t in g.grid.available():
            if (t.x + t.y) % 2 == 0:
                t.tile_type = c
            else:
                tt = c
                while tt == c:
                    tt = random_coloured_tile_type(g.rng, g.player)
                t.tile_type = tt


@register
class ChessStrategyGuide(Item):
    game_class = "ChessStrategyGuide"
    WORDS = ("pawn", "knight", "bishop", "rook", "queen", "king")

    def init_fields(self) -> None:
        self.fields["PiecesFound"] = [0] * 6

    def accumulator_words(self) -> list[str]:
        return list(self.WORDS)

    def start_of_grid(self, g: GenCtx) -> None:
        for i, n in enumerate(self.fields["PiecesFound"]):
            for _ in range(max(0, n)):
                t = tile_for_item_scatter(g, C.NORMAL, C.G_CHESS)
                white = g.rng.range(0, 2) == 0
                if t is not None:
                    t.set_chess(self.WORDS[i], white)


@register
class ChocolateCandy(Item):
    game_class = "ChocolateCandy"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in [t for t in g.grid.available() if t.srep() in ("m", "s")]:
            t.tile_type = random_coloured_tile_type(g.rng, g.player)


@register
class ChristmasTree(Item):
    game_class = "ChristmasTree"

    def start_of_grid(self, g: GenCtx) -> None:
        avail = g.player.run.available_colours
        missing = [c for c in avail if not any(t.tile_type == c for t in g.grid.available())]
        if not missing:
            colour = g.player.run.get_new_tile_colour(g.rng)
        else:
            colour = missing[g.rng.range(0, len(missing))]
        t = tile_for_item_scatter(g, colour, C.G_NONE)
        if t is not None:
            t.tile_type = colour


@register
class CoinPurse(Item):
    game_class = "CoinPurse"

    def init_fields(self) -> None:
        self.fields["Count"] = 0

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(2):
            t = tile_for_item_scatter(g, self.relevant_colours[0], C.G_NONE)
            if t is not None:
                t.tile_type = self.relevant_colours[0]
                _add_colour(g.player, self.relevant_colours[0])


@register
class CrystalBall(Item):
    game_class = "CrystalBall"
    CURSES = (C.C_BLANK, C.C_NUMBER, C.C_CHESS, C.C_CARD, C.C_WOBBLY, C.C_CURRENCY, C.C_ITEM)

    def init_fields(self) -> None:
        self.fields["ChosenCurseType"] = "None"
        self.fields["PreviousCurseType"] = "None"

    def start_of_grid(self, g: GenCtx) -> None:
        self.fields["PreviousCurseType"] = self.fields["ChosenCurseType"]
        self.fields["ChosenCurseType"] = self.CURSES[g.rng.range(0, len(self.CURSES))]


@register
class CursedVHS(Item):
    game_class = "CursedVHS"

    def start_of_grid(self, g: GenCtx) -> None:
        kinds: list[str] = []
        for t in g.grid.available():
            for ct in t.curse_types(g.player):
                if ct not in kinds:
                    kinds.append(ct)
        for _ in range(len(kinds)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_ITEM)
            if t is None:
                continue
            t.set_item(random_pool_item(g.rng, "CursedBuildItems"))
            if self.var(0) > 1 and t.item.is_sticker:
                _upgrade_scattered(t.item, self.var(0) - 1)


@register
class Dancer(Item):
    game_class = "Dancer"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_CHESS, None, True)
            if t is not None:
                t.set_chess(C.KING, False)
                t.set_suit(C.CLUBS)


@register
class DangerousSummit(Item):
    game_class = "DangerousSummit"

    def start_of_grid(self, g: GenCtx) -> None:
        pool = list(g.grid.available())
        chosen: list[Tile] = []
        for _ in range(3):
            if not pool:
                break
            best = None
            ties: list[Tile] = []
            for t in pool:
                v = t.get_value(g.player)
                if best is None or v > best:
                    best, ties = v, [t]
                elif v == best:
                    ties.append(t)
            if not ties:
                break
            pick = ties[g.rng.range(0, len(ties))]
            chosen.append(pick)
            pool.remove(pick)
        for t in chosen:
            t.tile_type = self.relevant_colours[0]


@register
class Dartboard(Item):
    game_class = "Dartboard"

    def init_fields(self) -> None:
        self.fields["_targetNumber"] = 1

    def start_of_grid(self, g: GenCtx) -> None:
        self.fields["_targetNumber"] = g.rng.range(1, 21)


@register
class Doughnut(Item):
    game_class = "Doughnut"

    def start_of_grid(self, g: GenCtx) -> None:
        from cursed_words_solver.sim.game.core import adjacent_tiles

        for t in g.grid.available():
            types: list[str] = []
            for a in adjacent_tiles(g.grid, t.x, t.y, g.player):
                if a.tile_type != C.NORMAL and a.tile_type not in types:
                    types.append(a.tile_type)
            if types:
                t.value_modifier += self.var(0) * len(types)


@register
class Eclipse(Item):
    game_class = "Eclipse"

    def start_of_grid(self, g: GenCtx) -> None:
        es = [t for t in g.grid.available() if t.srep() == "e"]
        if not es:
            return
        first = es.pop(g.rng.range(0, len(es)))
        first.tile_type = self.relevant_colours[0]
        for t in es:
            t.tile_type = self.relevant_colours[1]


@register
class EightBall(Item):
    game_class = "EightBall"
    PIECES = ("none", C.PAWN, C.KNIGHT, C.BISHOP, C.ROOK, C.QUEEN, C.KING)

    def init_fields(self) -> None:
        self.fields["_selectedPiece"] = "None"

    def start_of_grid(self, g: GenCtx) -> None:
        self.fields["_selectedPiece"] = self.PIECES[g.rng.range(1, 7)].capitalize()


@register
class EruptingVolcano(Item):
    game_class = "EruptingVolcano"

    def on_acquire(self, player, rng) -> None:
        for t in player.consumables:
            if t is not None and t.tile_type != self.relevant_colours[0]:
                t.tile_type = self.relevant_colours[0]


@register
class FallingLeaf(Item):
    game_class = "FallingLeaf"

    def on_acquire(self, player, rng) -> None:
        player.shop_event("repopulate")


@register
class BlessingOfTheShopkeeper(Item):
    game_class = "BlessingOfTheShopkeeper"

    def on_acquire(self, player, rng) -> None:
        player.shop_event("repopulate")


@register
class FamilyTicket(Item):
    game_class = "FamilyTicket"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None:
            return
        for t in last.tiles:
            if last.tile_value(t) >= 4:
                _scatter_colour(self, g, self.relevant_colours[0], 1)


@register
class FilingCabinet(Item):
    game_class = "FilingCabinet"

    def start_of_grid(self, g: GenCtx) -> None:
        groups: dict[str, list[Tile]] = {}
        for t in g.grid.available():
            if t.tile_type != C.NORMAL:
                groups.setdefault(t.tile_type, []).append(t)
        for tiles in groups.values():
            letters = [t for t in tiles if t.get_glyph() == C.G_LETTER]
            src = letters if letters else tiles
            pick = src[g.rng.range(0, len(src))]
            pick.set_item(random_pool_item(g.rng, "RainbowBuildItems"))


@register
class Fireworks(Item):
    game_class = "Fireworks"

    def start_of_grid(self, g: GenCtx) -> None:
        if g.grid_number != g.number_of_grids:
            return
        _scatter_colour(self, g, self.relevant_colours[0], self.var(0))


@register
class FlashyFountainPen(Item):
    game_class = "FlashyFountainPen"
    WORDS = ("red", "blue", "void", "shiny", "purple", "gold", "white", "green", "pink", "glitch", "cactus")
    FIELD = {
        "red": "RedsFound", "blue": "BluesFound", "void": "VoidsFound", "shiny": "ShinysFound",
        "purple": "PurplesFound", "gold": "GoldsFound", "white": "WhitesFound", "green": "GreensFound",
        "pink": "PinksFound", "glitch": "GlitchesFound", "cactus": "CactusesFound",
    }

    def init_fields(self) -> None:
        for f in self.FIELD.values():
            self.fields[f] = 0

    def accumulator_words(self) -> list[str]:
        return list(self.WORDS)

    def start_of_grid(self, g: GenCtx) -> None:
        for colour in self.WORDS:
            for _ in range(int(self.fields[self.FIELD[colour]])):
                t = tile_for_item_scatter(g, colour, C.G_NONE)
                if t is None:
                    continue
                if colour == C.PINK and g.player.run.challenge is not None:
                    continue
                t.tile_type = colour


@register
class FleurDeLis(Item):
    game_class = "FleurDeLis"

    def start_of_grid(self, g: GenCtx) -> None:
        a, b, purple = self.relevant_colours[:3]
        for t in [t for t in g.grid.available() if t.is_type(a) or t.is_type(b)]:
            t.tile_type = purple
            _add_colour(g.player, purple)


@register
class FoodPoisoning(Item):
    game_class = "FoodPoisoning"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in [t for t in g.grid.available() if t.get_glyph() != C.G_LETTER or t.suit != C.SUIT_NONE]:
            t.tile_type = self.relevant_colours[0]
            _add_colour(g.player, self.relevant_colours[0])


@register
class FortuneCookie(Item):
    game_class = "FortuneCookie"

    def on_acquire(self, player, rng) -> None:
        player.shop_event("foil")


@register
class Fountain(Item):
    game_class = "Fountain"

    def start_of_grid(self, g: GenCtx) -> None:
        _scatter_colour(self, g, self.relevant_colours[0], self.var(0))


@register
class FourLeafClover(Item):
    game_class = "FourLeafClover"

    def start_of_grid(self, g: GenCtx) -> None:
        suit = C.random_card_suit(g.rng)
        for colour in self.relevant_colours[:4]:
            t = tile_for_item_scatter(g, colour, C.G_NONE, None, True)
            if t is not None:
                t.set_suit(suit)
                t.tile_type = colour


@register
class FractionFrog(Item):
    game_class = "FractionFrog"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None:
            return
        target = g.player.run.current_encounter_target(g.player)
        frac = (last.score / target) if target else 0.0
        best, best_d = None, float("inf")
        for sym, (a, b) in C.FRACTIONS.items():
            d = abs(frac - a / b)
            if d < best_d:
                best, best_d = (a, b), d
        if best is not None:
            t = Tile()
            t.tile_type = C.NORMAL
            t.set_fraction(best)
            t.was_consumable = True
            g.add_to_rack(t)


class _Container(Item):
    def nested_items(self) -> list[Item]:
        return list(self.fields.get("_nested", []))


@register
class Frankenstein(Item):
    game_class = "Frankenstein"

    def init_fields(self) -> None:
        self.stitched: list[Item] = []

    def nested_items(self) -> list[Item]:
        return [i for i in self.stitched if i is not None]

    def _retag(self) -> None:
        if len(self.stitched) < 2:
            return
        a, b = self.stitched[0], self.stitched[1]
        self.tags = list(a.tags) + [t for t in b.tags if t not in a.tags]
        for t in a.dependency_tags:
            if t not in self.tags:
                self.dependency_tags.append(t)
        for t in b.dependency_tags:
            if t not in self.tags and t not in self.dependency_tags:
                self.dependency_tags.append(t)

    def upgrade(self, i=0, both=False, **kw) -> None:
        self._base_upgrade(i)
        for s in self.stitched[:2]:
            s.upgrade(0)
        self._retag()

    def downgrade(self, i=0) -> None:
        self._base_downgrade(i)
        for s in self.stitched[:2]:
            s.downgrade(0)
        self._retag()


@register
class FriedShrimp(Item):
    game_class = "FriedShrimp"

    def on_acquire(self, player, rng) -> None:
        player.shop_event("repopulate")


@register
class GamePad(Item):
    game_class = "GamePad"

    def start_of_grid(self, g: GenCtx) -> None:
        for colour in self.relevant_colours[:3]:
            _scatter_colour(self, g, colour, self.var(0))


@register
class Ghost(Item):
    game_class = "Ghost"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None:
            return
        n = sum(1 for t in last.tiles if t.is_cursed(g.player))
        if n:
            _cursed_copy_scatter(g, self.var(0) * n)


@register
class GlobeTrotter(Item):
    game_class = "GlobeTrotter"

    def start_of_grid(self, g: GenCtx) -> None:
        from cursed_words_solver.sim.game.core import is_corner

        for t in g.grid.available():
            if is_corner(t, g.grid):
                t.set_currency(C.random_currency(g.rng))
                t.change_value_modifier(10)


@register
class GoFish(Item):
    game_class = "GoFish"

    def start_of_grid(self, g: GenCtx) -> None:
        suit = C.random_card_suit(g.rng)
        start = g.rng.range(1, 6)
        for n in range(start, start + 5):
            t = tile_for_item_scatter(g, self.relevant_colours[0], C.G_NUMBER, None, True)
            if t is not None:
                t.set_number(n)
                t.set_suit(suit)
                t.tile_type = self.relevant_colours[0]


@register
class GoldFish(Item):
    game_class = "GoldFish"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = Tile()
            t.set_currency(C.random_currency(g.rng))
            g.add_to_rack(t)


@register
class GoldenScales(Item):
    game_class = "GoldenScales"

    def start_of_grid(self, g: GenCtx) -> None:
        if g.grid_number != 1:
            return
        n = 5 - len(g.player.stickers_list(for_comparison=True))
        if n > 0:
            g.money_change += n
            g.earnings[self.name] = g.earnings.get(self.name, 0) + n


@register
class Gorilla(Item):
    game_class = "Gorilla"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, self.relevant_colours[0], C.G_CHESS)
            if t is not None:
                t.tile_type = self.relevant_colours[0]
                white = g.rng.range(0, 2) == 0
                piece = (C.KING, C.QUEEN)[g.rng.range(0, 2)]
                t.set_chess(piece, white)


@register
class HauntedHouse(Item):
    game_class = "HauntedHouse"

    def start_of_grid(self, g: GenCtx) -> None:
        protos: list[Tile] = []
        while len(protos) < 2:
            t = Tile()
            randomly_curse_tile(t, g.rng, g.player, True)
            if not any(p.srep() == t.srep() for p in protos):
                protos.append(t)
        for proto, count in ((protos[0], 2), (protos[1], 3)):
            for _ in range(count):
                target = tile_for_item_scatter(g, C.NORMAL, proto.get_glyph(), None, True)
                if target is not None:
                    proto.tile_type = target.tile_type
                    target.set_as_copy(proto, False)
                    target.set_suit(C.random_card_suit(g.rng))


@register
class HauntedMirror(Item):
    game_class = "HauntedMirror"

    def start_of_grid(self, g: GenCtx) -> None:
        cursed = [t for t in g.grid.available() if t.is_cursed(g.player)]
        while cursed:
            t = cursed.pop(g.rng.range(0, len(cursed)))
            t.tile_type = random_coloured_tile_type(g.rng, g.player)


@register
class HeadInTheClouds(Item):
    game_class = "HeadInTheClouds"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in _scatter_colour(self, g, self.relevant_colours[0], 2):
            _add_colour(g.player, self.relevant_colours[0])


@register
class HeadTrauma(Item):
    game_class = "HeadTrauma"

    def start_of_grid(self, g: GenCtx) -> None:
        _scatter_colour(self, g, self.relevant_colours[0], 2)
        for _ in range(2):
            t = tile_for_item_scatter(g, self.relevant_colours[1], C.G_BLANK)
            if t is not None:
                t.tile_type = self.relevant_colours[1]
                t.set_glyph(C.G_BLANK)


@register
class Jellyfish(Item):
    game_class = "Jellyfish"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in g.grid.available():
            if t.srep() == "j" and not t.is_type(self.relevant_colours[0]):
                t.tile_type = self.relevant_colours[0]


@register
class Joker(Item):
    game_class = "Joker"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_CARD, None, True)
            if t is not None:
                t.set_glyph(C.G_CARD)
                t.set_suit(C.SUIT_JOKER)


@register
class JuiceBox(Item):
    game_class = "JuiceBox"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None:
            return
        for src in last.tiles:
            t = tile_for_item_scatter(g, src.tile_type, src.get_glyph(), None, True)
            if t is not None:
                t.set_as_copy(src, False)


@register
class Kimono(Item):
    game_class = "Kimono"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None:
            return
        n = sum(1 for t in last.tiles if t.is_type(self.relevant_colours[0]))
        for _ in range(n):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_BLANK)
            if t is not None:
                t.set_glyph(C.G_BLANK)


@register
class Ladybird(Item):
    game_class = "Ladybird"

    def start_of_grid(self, g: GenCtx) -> None:
        for colour, nums in ((self.relevant_colours[0], (2, 4, 6, 8)), (self.relevant_colours[1], (1, 3, 5, 7, 9))):
            for _ in range(self.var(0)):
                t = tile_for_item_scatter(g, colour, C.G_NUMBER)
                if t is not None:
                    t.tile_type = colour
                    t.set_number(nums[g.rng.range(0, len(nums))])


@register
class LeftHumanHand(Item):
    game_class = "LeftHumanHand"

    def __init__(self) -> None:
        super().__init__()
        self.selling_prevented = True

    def upgrade(self, i=0, both=False, **kw) -> None:
        pass

    def downgrade(self, i=0) -> None:
        pass


@register
class RightHumanHand(Item):
    game_class = "RightHumanHand"

    def __init__(self) -> None:
        super().__init__()
        self.selling_prevented = True


@register
class Lipstick(Item):
    game_class = "Lipstick"

    def start_of_grid(self, g: GenCtx) -> None:
        if g.grid_number == 1:
            _scatter_colour(self, g, self.relevant_colours[0], self.var(0))


@register
class LuckyDice(Item):
    game_class = "LuckyDice"

    def init_fields(self) -> None:
        self.fields["_diceNumber"] = 1

    def start_of_grid(self, g: GenCtx) -> None:
        self.fields["_diceNumber"] = g.rng.range(1, 7)


@register
class MagicWand(Item):
    game_class = "MagicWand"

    def start_of_grid(self, g: GenCtx) -> None:
        if g.rng.range(0, 4) != 0:
            return
        a, b, c = self.relevant_colours[:3]
        pool = [t for t in g.grid.available() if t.is_type(a) or t.is_type(b)]
        for _ in range(self.var(0)):
            if pool:
                pool.pop(g.rng.range(0, len(pool))).tile_type = c


@register
class MagiciansHat(Item):
    game_class = "MagiciansHat"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in g.grid.available():
            if t.is_type(self.relevant_colours[0]) and t.suit != C.SPADES and t.get_glyph() != C.G_CARD:
                t.set_suit(C.SPADES)


@register
class MahjongRedDragon(Item):
    game_class = "MahjongRedDragon"

    def start_of_grid(self, g: GenCtx) -> None:
        if g.grid_number != 1:
            return
        for _ in range(self.var(0)):
            t = Tile()
            t.tile_type = self.relevant_colours[0]
            t.was_consumable = True
            if g.rng.range(0, 2) == 0:
                t.set_letter(C.random_letter_weighted(g.rng))
            else:
                randomly_curse_tile(t, g.rng, g.player, False)
            g.add_to_rack(t)


@register
class Maracas(Item):
    game_class = "Maracas"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None:
            return
        n = sum(1 for t in last.tiles if not t.is_type(C.NORMAL))
        for _ in range(self.var(0) * n):
            colour = random_coloured_tile_type(g.rng, g.player)
            t = tile_for_item_scatter(g, colour, C.G_NONE)
            if t is not None:
                t.tile_type = colour


@register
class MichaelsBook(Item):
    game_class = "MichaelsBook"

    def init_fields(self) -> None:
        self.fields["WordLength"] = 3
        self.fields["Count"] = 0
        self.fields["CurrentWord"] = "try"
        self.words_at_level: dict[int, list[str]] = {}
        self.starter_initialised = False

    def initialise_starter_words(self, rng: Rng, random_word: Callable[[int], str | None]) -> None:
        if self.starter_initialised:
            return
        starters = [w for w in (random_word(3) for _ in range(100)) if w]
        for j, w in enumerate(starters):
            self.words_at_level[j] = [w]
        self.starter_initialised = True
        if starters:
            lv = min(self.level(0), len(starters) - 1)
            self.fields["CurrentWord"] = starters[lv]
            self.fields["WordLength"] = len(starters[lv])

    def _sync(self) -> None:
        words = self.words_at_level.get(self.level(0))
        if words:
            self.fields["CurrentWord"] = words[-1]
            self.fields["WordLength"] = len(words[-1])

    def upgrade(self, i=0, both=False, **kw) -> None:
        self._base_upgrade(i)
        self._sync()

    def downgrade(self, i=0) -> None:
        self._base_downgrade(i)
        self._sync()

    def accumulator_words(self) -> list[str]:
        return [self.fields["CurrentWord"]]


@register
class MilkyWay(Item):
    game_class = "MilkyWay"

    def upgrade(self, i=0, both=False, **kw) -> None:
        if both:
            self.upgrade(0)
            self.upgrade(1)
            return
        self._base_upgrade(i)
        if self.level(0) >= 2 and "VoidGenerator" not in self.tags:
            self.tags.append("VoidGenerator")
        if self.level(1) >= 2 and "ShinyGenerator" not in self.tags:
            self.tags.append("ShinyGenerator")

    def start_of_grid(self, g: GenCtx) -> None:
        _scatter_colour(self, g, self.relevant_colours[0], self.var(0))

    def final_start_of_grid(self, g: GenCtx) -> None:
        for t in [t for t in g.grid.available() if t.is_type(self.relevant_colours[0])]:
            if g.rng.range(0, 100) < self.var(1):
                t.tile_type = self.relevant_colours[1]


@register
class MushroomUpgrade(Item):
    game_class = "MushroomUpgrade"

    def init_fields(self) -> None:
        self.fields["RedCount"] = 0

    def start_of_grid(self, g: GenCtx) -> None:
        if g.grid_number == 1:
            _scatter_colour(self, g, self.relevant_colours[0], int(self.fields["RedCount"]) // 5)


@register
class MusicalNotes(Item):
    game_class = "MusicalNotes"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, self.relevant_colours[0], C.G_LETTER, None, True)
            if t is not None:
                t.set_letter("e")
                t.set_suit(C.random_card_suit(g.rng))
                t.tile_type = self.relevant_colours[0]


@register
class NestEgg(Item):
    game_class = "NestEgg"

    def init_fields(self) -> None:
        self.fields["BlueTilesUsed"] = 0

    def sell_value(self, player) -> int:
        return int(self.fields["BlueTilesUsed"])


@register
class NewEruptingVolcano(Item):
    game_class = "NewEruptingVolcano"

    def on_acquire(self, player, rng) -> None:
        if not player.shop_event("volcano"):
            player.frozen_stickers = [None] * 4
            player.frozen_stamps = [None] * 2


@register
class NorthernCardinal(Item):
    game_class = "NorthernCardinal"

    def on_acquire(self, player, rng) -> None:
        player.shop_event("repopulate")


@register
class NumberFactory(Item):
    game_class = "NumberFactory"

    def start_of_grid(self, g: GenCtx) -> None:
        t = Tile()
        t.set_number(g.grid_number)
        g.add_to_rack(t)


@register
class NumbersBunchOfGrapes(Item):
    game_class = "NumbersBunchOfGrapes"

    def start_of_grid(self, g: GenCtx) -> None:
        for n in (1, 5, 10):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_NUMBER)
            if t is not None:
                t.set_number(n)


@register
class Ogre(Item):
    game_class = "Ogre"

    def on_acquire(self, player, rng) -> None:
        player.run.curse_current_stage_bosses()


@register
class PaperLantern(Item):
    game_class = "PaperLantern"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None or not last.tiles:
            return
        for src in [t for t in last.tiles if t.is_type(self.relevant_colours[0])]:
            t = g.grid.at(src.x, src.y)
            if t is not None and not t.is_type(self.relevant_colours[0]):
                t.tile_type = self.relevant_colours[0]


@register
class Parachute(Item):
    game_class = "Parachute"

    def start_of_grid(self, g: GenCtx) -> None:
        if any(t.is_type(self.relevant_colours[0]) for t in g.grid.available()):
            return
        _scatter_colour(self, g, self.relevant_colours[0], 3)


@register
class PetriDish(Item):
    game_class = "PetriDish"

    def start_of_grid(self, g: GenCtx) -> None:
        for n in range(1, self.var(0) + 1):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_NUMBER)
            if t is not None:
                t.set_number(n)


@register
class PiggyBank(Item):
    game_class = "PiggyBank"

    def start_of_grid(self, g: GenCtx) -> None:
        if g.player.money + g.money_change < 3:
            return
        placed = 0
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, self.relevant_colours[0], C.G_NONE)
            if t is not None:
                t.tile_type = self.relevant_colours[0]
                t.set_glyph(C.G_BLANK)
                placed += 1
        if placed:
            g.money_change -= 3
            g.earnings[self.name] = g.earnings.get(self.name, 0) - 3


@register
class Pinata(Item):
    game_class = "Pinata"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None or len(last.tiles) < 7:
            return
        _scatter_colour(self, g, self.relevant_colours[0], 1)


@register
class PizzaSlice(Item):
    game_class = "PizzaSlice"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in [t for t in g.grid.available() if t.get_glyph() == C.G_NUMBER]:
            t.set_fraction(C.random_fraction(g.rng))


@register
class PostalHorn(Item):
    game_class = "PostalHorn"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_NONE, None, True)
            if t is not None:
                t.set_suit(C.random_card_suit(g.rng))


class _ColourScatterer(Item):
    """Printer / Retro Raider / Toolbox: colour randomisation limited to red/blue/void."""

    def randomise_relevant_colours(self, player, rng) -> None:
        held = [i for i in player.all_items() if i.game_class == self.game_class]
        if held:
            self.relevant_colours = list(held[0].relevant_colours)
            return
        n = len(self.relevant_colours)
        pool = [C.RED, C.BLUE, C.VOID]
        self.relevant_colours = [pool.pop(rng.range(0, len(pool))) for _ in range(n)]


@register
class Printer(_ColourScatterer):
    game_class = "Printer"

    def start_of_grid(self, g: GenCtx) -> None:
        c = self.relevant_colours[0]
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, c, C.G_ITEM)
            if t is not None:
                t.tile_type = c
                item = random_colour_build_item(g.rng, c)
                if item is not None:
                    t.set_item(item)


@register
class QueenBee(Item):
    game_class = "QueenBee"

    def start_of_grid(self, g: GenCtx) -> None:
        white = g.rng.range(0, 2) == 0
        for colour_white in (white, not white):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_CHESS)
            if t is not None:
                t.set_chess(C.QUEEN, colour_white)


@register
class Raccoon(Item):
    game_class = "Raccoon"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_CHESS)
            if t is not None:
                t.set_chess(*C.random_chess_piece(g.rng))


@register
class Radio(Item):
    game_class = "Radio"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_ITEM)
            if t is None:
                continue
            t.tile_type = C.NORMAL
            t.set_item(random_pool_item(g.rng, "ColourlessBuildItems"))
            if self.var(0) > 1 and t.item.is_sticker:
                _upgrade_scattered(t.item, self.var(0) - 1)


@register
class Rainbow(Item):
    game_class = "Rainbow"

    def init_fields(self) -> None:
        self.fields["ChosenTileTypes"] = []
        self.fields["MostRecentUpgrade"] = 0

    def _fill(self, rng: Rng) -> None:
        chosen = self.fields["ChosenTileTypes"]
        while len(chosen) < self.var(0):
            left = [c for c in self.relevant_colours if c not in chosen]
            chosen.append(left[rng.range(0, len(left))])

    def upgrade(self, i=0, both=False, *, rng: Rng | None = None, player=None) -> None:
        if both:
            self.upgrade(0, rng=rng)
            self.upgrade(1, rng=rng)
            return
        self._base_upgrade(i)
        self.fields["MostRecentUpgrade"] = i
        self._fill(rng or Rng(0))

    def start_of_grid(self, g: GenCtx) -> None:
        if self.var(0) < 1:
            return
        self._fill(g.rng)
        pool = list(self.fields["ChosenTileTypes"])
        for _ in range(self.var(0)):
            colour = pool.pop(g.rng.range(0, len(pool)))
            t = tile_for_item_scatter(g, colour, C.G_NONE)
            if t is not None:
                t.tile_type = colour
                _add_colour(g.player, colour)


@register
class RainbowSprinkles(Item):
    game_class = "RainbowSprinkles"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None:
            return
        types = {t.tile_type for t in last.tiles if t.tile_type != C.NORMAL}
        if len(types) < 3:
            return
        _scatter_colour(self, g, self.relevant_colours[0], self.var(0))


@register
class RandomAccessMemory(Item):
    game_class = "RandomAccessMemory"
    BLACKLIST = (
        "Arrivals", "BeamMeUp", "CrystalBall", "Dartboard", "Departures", "EightBall", "HungryHippo",
        "LuckyDice", "MichaelsBook", "MysteryGift", "NestEgg", "Overhand", "SewingNeedle", "ShavedIce",
        "SignalReceiver", "Snapshot", "Underhand", "Unicorn",
    )

    def init_fields(self) -> None:
        self.memory: list[Item] = []
        self.next_items: list[Item | None] = [None, None]
        self.fields["MostRecentUpgrade"] = 0

    def nested_items(self) -> list[Item]:
        return list(self.memory)

    def _absorb(self, it: Item | None) -> None:
        if it is None:
            return
        self.memory.append(it)
        for t in it.tags:
            if t not in self.tags:
                self.tags.append(t)
        for t in it.dependency_tags:
            if t not in self.dependency_tags:
                self.dependency_tags.append(t)

    def upgrade(self, i=0, both=False, *, rng: Rng | None = None, player=None) -> None:
        if both:
            self._absorb(self.next_items[0])
            self._absorb(self.next_items[1])
            self._base_upgrade(0)
            self._base_upgrade(1)
            self.fields["MostRecentUpgrade"] = 1
        else:
            self._base_upgrade(i)
            self._absorb(self.next_items[i] if i < 2 else None)
            self.fields["MostRecentUpgrade"] = i
        if player is not None and rng is not None:
            self.populate_next(player, rng)

    def start_of_encounter(self, player, rng) -> None:
        self.populate_next(player, rng)

    def accumulator_words(self) -> list[str]:
        out: list[str] = []
        for it in self.memory:
            out.extend(it.accumulator_words())
        return out

    def populate_next(self, player: "Player", rng: Rng) -> None:
        from cursed_words_solver.sim.game.pools import random_stamp, random_sticker

        black = set(self.BLACKLIST) | {i.game_class for i in self.memory}
        picks: list[Item | None] = []
        for _ in range(2):
            if rng.range(0, 3) == 0:
                black |= {s.game_class for s in player.stamps_list(for_comparison=True)}
                it = random_stamp(rng, player, black)
            else:
                black |= {s.game_class for s in player.stickers_list(for_comparison=True)}
                it = random_sticker(rng, player, black)
            picks.append(it)
            if it is not None:
                black.add(it.game_class)
        self.next_items = picks


@register
class RedBalloon(Item):
    game_class = "RedBalloon"

    def start_of_grid(self, g: GenCtx) -> None:
        t = tile_for_item_scatter(g, self.relevant_colours[0], C.G_NUMBER)
        if t is not None:
            t.set_number(99)
            t.tile_type = self.relevant_colours[0]


@register
class RetroRaider(_ColourScatterer):
    game_class = "RetroRaider"

    def start_of_grid(self, g: GenCtx) -> None:
        if self.var(0) < 1:
            return
        t = tile_for_item_scatter(g, C.NORMAL, C.G_ITEM)
        if t is None:
            return
        item = random_colour_build_item(g.rng, self.relevant_colours[0])
        if item is None:
            return
        t.set_item(item)
        if self.var(0) > 1:
            for _ in range(self.var(0) - 1):
                if t.item.is_sticker:
                    t.item.upgrade(0)
        from cursed_words_solver.sim.game.core import adjacent_tiles

        adj = adjacent_tiles(g.grid, t.x, t.y, g.player)
        for _ in range(self.var(0)):
            a = tile_for_item_scatter(g, self.relevant_colours[0], C.G_NONE, adj)
            if a is not None:
                a.tile_type = self.relevant_colours[0]


@register
class Rex(Item):
    game_class = "Rex"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_ITEM)
            if t is not None:
                t.set_item(make_item("Bone"))


@register
class RollerSkate(Item):
    game_class = "RollerSkate"

    def init_fields(self) -> None:
        self.fields["PreviousShopRestockCount"] = 0

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(int(self.fields["PreviousShopRestockCount"]) * self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_CURRENCY)
            if t is not None:
                t.set_currency(C.random_currency(g.rng))


@register
class Rolodex(Item):
    game_class = "Rolodex"

    def start_of_grid(self, g: GenCtx) -> None:
        suit = C.random_card_suit(g.rng)
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_ITEM)
            if t is not None:
                t.set_item(random_pool_item(g.rng, "CardBuildItems"))
                t.set_suit(suit)


@register
class Rosebud(Item):
    game_class = "Rosebud"

    def start_of_grid(self, g: GenCtx) -> None:
        if g.grid_number != 1:
            return
        for letter in ("r", "e", "d", "s"):
            t = Tile()
            t.tile_type = self.relevant_colours[0]
            t.set_letter(letter)
            g.add_to_rack(t)


@register
class SaguaroSeedling(Item):
    game_class = "SaguaroSeedling"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in _scatter_colour(self, g, self.relevant_colours[0], 2):
            _add_colour(g.player, self.relevant_colours[0])


@register
class SlotMachine(Item):
    game_class = "SlotMachine"

    def init_fields(self) -> None:
        self.fields["_hasGivenReroll"] = False

    def start_of_grid(self, g: GenCtx) -> None:
        _scatter_colour(self, g, self.relevant_colours[0], 2)
        if g.grid_number == 1 and not self.fields["_hasGivenReroll"]:
            g.rerolls_change += 1
            self.fields["_hasGivenReroll"] = True

    def start_of_encounter(self, player, rng) -> None:
        self.fields["_hasGivenReroll"] = False


@register
class SluggishZombie(Item):
    game_class = "SluggishZombie"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in g.grid.available():
            if t.srep() == "s":
                t.set_letter("z")


@register
class SmartShirt(Item):
    game_class = "SmartShirt"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in [t for t in g.grid.available() if not t.is_type(C.NORMAL) and t.get_glyph() != C.G_CARD]:
            t.set_suit(C.random_card_suit(g.rng))


@register
class Snail(Item):
    game_class = "Snail"

    def init_fields(self) -> None:
        self.fields["RerollCount"] = 0

    def rarity_multiplier(self) -> float:
        return (100 + int(self.fields["RerollCount"]) * 20) / 100.0

    def on_acquire(self, player, rng) -> None:
        player.shop_event("foil")


@register
class Snapshot(Item):
    game_class = "Snapshot"

    def init_fields(self) -> None:
        self.snapshotted: Item | None = None

    def nested_items(self) -> list[Item]:
        return [self.snapshotted] if self.snapshotted is not None else []

    def start_of_grid(self, g: GenCtx) -> None:
        cands = [t for t in g.grid.available() if t.get_glyph() == C.G_ITEM and t.item is not None and t.item.is_sticker]
        if cands:
            src = cands[g.rng.range(0, len(cands))]
            self.snapshotted = make_item(src.item.game_class)
            for _ in range(self.level(0) - 1):
                self.snapshotted.upgrade(0)
        if self.snapshotted is not None:
            self.snapshotted.start_of_grid(g)


@register
class Snowman(Item):
    game_class = "Snowman"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(g.player.frozen_count() * self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_CURRENCY)
            if t is not None:
                t.set_currency(C.random_currency(g.rng))


@register
class SoaringKite(Item):
    game_class = "SoaringKite"

    def start_of_grid(self, g: GenCtx) -> None:
        present = []
        for t in g.grid.available():
            if t.get_glyph() == C.G_NUMBER and t.number not in present:
                present.append(t.number)
        for _ in range(self.var(0)):
            n = 1
            while n in present:
                n += 1
            t = tile_for_item_scatter(g, self.relevant_colours[0], C.G_NUMBER)
            if t is not None:
                t.tile_type = self.relevant_colours[0]
                t.set_number(n)
                present.append(n)


@register
class SpoutingWhale(Item):
    game_class = "SpoutingWhale"

    def start_of_grid(self, g: GenCtx) -> None:
        t = Tile()
        t.tile_type = self.relevant_colours[0]
        t.set_glyph(C.G_BLANK)
        g.add_to_rack(t)


@register
class StatueOfLiberty(Item):
    game_class = "StatueOfLiberty"

    def start_of_grid(self, g: GenCtx) -> None:
        c = self.relevant_colours[0]
        n_col = sum(1 for t in g.grid.available() if t.is_type(c))
        n_blank = sum(1 for t in g.grid.available() if t.is_blank())
        if (n_col == 0 and n_blank == 0) or n_col == n_blank:
            return
        top = max(n_col, n_blank)
        if n_col < top:
            _scatter_colour(self, g, c, top - n_col)
        elif n_blank < top:
            for _ in range(top - n_blank):
                t = tile_for_item_scatter(g, C.NORMAL, C.G_BLANK)
                if t is not None:
                    t.set_glyph(C.G_BLANK)


@register
class Stethoscope(Item):
    game_class = "Stethoscope"

    def start_of_grid(self, g: GenCtx) -> None:
        nums = [t for t in g.grid.available() if t.get_glyph() == C.G_NUMBER and t.number < 10]
        if not nums:
            return
        t = nums[g.rng.range(0, len(nums))]
        n = t.number
        t.set_item(random_pool_item(g.rng, "NumberBuildStickers"))
        for _ in range(max(0, n - 1)):
            t.item.upgrade(0)


@register
class StickerPadlock(Item):
    game_class = "StickerPadlock"

    def __init__(self) -> None:
        super().__init__()
        self.sell_cost = 8
        self.costs_money_to_sell = True

    def upgrade(self, i=0, both=False, **kw) -> None:
        self._base_upgrade(i)
        self.sell_cost = self.var(0)

    def downgrade(self, i=0) -> None:
        self._base_downgrade(i)
        self.sell_cost = self.var(0)


@register
class StickingPlaster(Item):
    game_class = "StickingPlaster"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None:
            return
        cands = [t for t in last.tiles if t.is_number() and g.grid.available_at(t.x, t.y) is not None]
        chosen: list[Tile] = []
        for _ in range(self.var(0)):
            if not cands:
                break
            chosen.append(cands.pop(g.rng.range(0, len(cands))))
        for src in chosen:
            t = g.grid.available_at(src.x, src.y)
            if t is not None:
                t.set_as_copy(src, True)
                t.value_modifier += 5 * (self.var(0) - 1)


@register
class StormCloud(Item):
    game_class = "StormCloud"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = Tile()
            randomly_curse_tile(t, g.rng, g.player, True)
            g.add_to_rack(t)


@register
class Suitcase(Item):
    game_class = "Suitcase"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, self.relevant_colours[0], C.G_CHESS)
            if t is not None:
                t.tile_type = self.relevant_colours[0]
                piece = C.BISHOP if g.rng.range(0, 2) == 0 else C.ROOK
                t.set_chess(piece, g.rng.range(0, 2) == 0)


@register
class SuperEight(Item):
    game_class = "SuperEight"

    def upgrade(self, i=0, both=False, **kw) -> None:
        if both:
            self.upgrade(0)
            self.upgrade(1)
            return
        self._base_upgrade(i)
        if self.level(0) >= 2 and "ChessGenerator" not in self.tags:
            self.tags.append("ChessGenerator")

    def start_of_grid(self, g: GenCtx) -> None:
        if self.var(0) < 1:
            return
        order = C.ALL_CHESS_PIECES
        for i in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_CHESS)
            if t is not None:
                t.set_chess(order[i] if i < len(order) else C.QUEEN, g.rng.range(0, 2) == 0)


@register
class Supervillain(Item):
    game_class = "Supervillain"

    def start_of_grid(self, g: GenCtx) -> None:
        present: set[str] = set()
        for t in g.grid.available():
            present.update(t.curse_types(g.player))
        if C.C_BLANK not in present:
            t = tile_for_item_scatter(g, C.NORMAL, C.G_BLANK)
            if t is not None:
                t.set_glyph(C.G_BLANK)
        if C.C_NUMBER not in present:
            t = tile_for_item_scatter(g, C.NORMAL, C.G_NUMBER)
            if t is not None:
                if g.rng.range(0, 2) == 0:
                    t.set_number(g.rng.range(1, 9))
                else:
                    t.set_fraction(C.random_fraction(g.rng))
        if C.C_CHESS not in present:
            t = tile_for_item_scatter(g, C.NORMAL, C.G_CHESS)
            if t is not None:
                t.set_chess(*C.random_chess_piece(g.rng))
        if C.C_CARD not in present:
            if g.rng.range(0, 10) == 0:
                t = tile_for_item_scatter(g, C.NORMAL, C.G_CARD)
                if t is not None:
                    t.set_glyph(C.G_CARD)
                    t.set_suit(C.SUIT_JOKER)
            else:
                t = tile_for_item_scatter(g, C.NORMAL, C.G_NONE, None, True)
                if t is not None:
                    t.set_suit(C.random_card_suit(g.rng))
        if C.C_ITEM not in present:
            t = tile_for_item_scatter(g, C.NORMAL, C.G_ITEM)
            if t is not None:
                t.set_item(random_scattered_item(g.rng))
        if C.C_CURRENCY not in present:
            t = tile_for_item_scatter(g, C.NORMAL, C.G_CURRENCY)
            if t is not None:
                t.set_currency(C.random_currency(g.rng))


@register
class TakeoutBox(Item):
    game_class = "TakeoutBox"

    def start_of_grid(self, g: GenCtx) -> None:
        count = sum(1 for t in g.rack if t is not None)
        if count > 0:
            g.rack = [None] * 10
            g.money_change += count
            g.earnings[self.name] = g.earnings.get(self.name, 0) + count


@register
class Teapot(Item):
    game_class = "Teapot"

    def start_of_grid(self, g: GenCtx) -> None:
        _scatter_colour(self, g, self.relevant_colours[0], g.grid_number)


@register
class Television(Item):
    game_class = "Television"

    def start_of_grid(self, g: GenCtx) -> None:
        t = tile_for_item_scatter(g, C.NORMAL, C.G_ITEM)
        if t is not None:
            t.set_item(random_pool_item(g.rng, "ChessBuildItems"))


@register
class TenPinBowling(Item):
    game_class = "TenPinBowling"

    def _chain(self, g: GenCtx, avail: list[Tile]) -> list[Tile]:
        """``GetAdjacentTiles``: first adjacency chain of the longest feasible length."""
        from cursed_words_solver.sim.game.core import adjacent_tiles

        def grow(chain: list[Tile], pool: list[Tile], want: int) -> list[Tile] | None:
            if len(chain) == want:
                return chain
            ids = {id(t) for t in chain}
            pool_ids = {id(t) for t in pool}
            nxt = [a for a in adjacent_tiles(g.grid, chain[-1].x, chain[-1].y, g.player) if id(a) in pool_ids and id(a) not in ids]
            if not nxt:
                return None
            pick = nxt[0]
            rest = [t for t in pool if t is not pick]
            return grow(chain + [pick], rest, want)

        want = self.var(0)
        while want > 0:
            for start in avail:
                got = grow([start], [t for t in avail if t is not start], want)
                if got is not None:
                    return got
            want -= 1
        return []

    def start_of_grid(self, g: GenCtx) -> None:
        from cursed_words_solver.sim.game.core import adjacent_tiles

        tiles = shuffle(g.rng, list(g.grid.available()))
        base = [t for t in tiles if t.is_type(C.NORMAL) and t.get_glyph() == C.G_LETTER]
        if g.player.unpacked_of("Magnet"):
            near: set[int] = set()
            for t in g.grid.available():
                if t.get_glyph() in (C.G_NUMBER, C.G_FRACTION):
                    near |= {id(a) for a in adjacent_tiles(g.grid, t.x, t.y, g.player) if a.get_glyph() == C.G_LETTER}
            base = [t for t in base if id(t) in near]
        chain = self._chain(g, base)
        if not chain:
            chain = self._chain(g, [t for t in tiles if t.get_glyph() == C.G_LETTER])
        if not chain:
            chain = self._chain(g, [t for t in tiles if t.is_type(C.NORMAL)])
        if not chain:
            chain = self._chain(g, tiles)
        n = len(chain)
        if n:
            start = 1 if n > 9 else g.rng.range(1, 11 - n)
            for k, t in enumerate(chain):
                t.tile_type = self.relevant_colours[0]
                t.set_number(start + k)


@register
class Toolbox(_ColourScatterer):
    game_class = "Toolbox"

    def start_of_grid(self, g: GenCtx) -> None:
        c = self.relevant_colours[0]
        for _ in range(2):
            t = tile_for_item_scatter(g, c, C.G_ITEM)
            if t is None:
                continue
            item = random_colour_build_item(g.rng, c)
            if item is None:
                continue
            t.tile_type = c
            t.set_item(item)
            if self.var(0) > 1 and t.item.is_sticker:
                _upgrade_scattered(t.item, self.var(0) - 1)


@register
class ToriiGate(Item):
    game_class = "ToriiGate"

    def start_of_grid(self, g: GenCtx) -> None:
        if g.grid_number != 1:
            return
        mx = g.grid.width - 1
        for t in g.grid.available():
            if t.x in (0, mx):
                t.tile_type = self.relevant_colours[0]


@register
class TrafficLights(Item):
    game_class = "TrafficLights"

    def start_of_grid(self, g: GenCtx) -> None:
        colours = list(g.player.run.available_colours)
        nums = [1, 2, 3, 4, 5, 6]
        for _ in range(self.var(0)):
            colour = colours[g.rng.range(0, len(colours))] if colours else g.player.run.get_new_tile_colour(g.rng)
            t = tile_for_item_scatter(g, colour, C.G_NUMBER)
            if not nums:
                nums = [7, 8, 9]
            if t is not None:
                t.tile_type = colour
                if colour in colours:
                    colours.remove(colour)
                n = nums[g.rng.range(0, len(nums))]
                t.set_number(n)
                nums.remove(n)


@register
class TrophyOfWealth(Item):
    game_class = "TrophyOfWealth"

    def start_of_grid(self, g: GenCtx) -> None:
        money = g.player.money + g.money_change
        if money < 15:
            return
        for _ in _scatter_colour(self, g, self.relevant_colours[0], money // 15):
            _add_colour(g.player, self.relevant_colours[0])


@register
class TwinkleToes(Item):
    game_class = "TwinkleToes"

    def init_fields(self) -> None:
        self.fields["TileSwapAvailable"] = True

    def start_of_grid(self, g: GenCtx) -> None:
        self.fields["TileSwapAvailable"] = True


@register
class ValentinesDayCard(Item):
    game_class = "ValentinesDayCard"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in g.grid.available():
            if t.is_type(self.relevant_colours[0]) and t.suit != C.HEARTS and t.get_glyph() != C.G_CARD:
                t.set_suit(C.HEARTS)


@register
class WadOfCash(Item):
    game_class = "WadOfCash"

    def upgrade(self, i=0, both=False, **kw) -> None:
        if both:
            self.upgrade(0)
            self.upgrade(1)
            return
        self._base_upgrade(i)
        if self.level(0) >= 2 and "CashGenerator" not in self.tags:
            self.tags.append("CashGenerator")

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(self.var(0)):
            t = tile_for_item_scatter(g, C.NORMAL, C.G_CURRENCY)
            if t is not None:
                t.set_currency(C.random_currency(g.rng))


@register
class WaxyVizor(Item):
    game_class = "WaxyVizor"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in g.grid.available():
            if t.srep() in ("v", "w", "x", "y", "z") and not t.is_type(self.relevant_colours[0]):
                t.tile_type = self.relevant_colours[0]


@register
class WeeklyShop(Item):
    game_class = "WeeklyShop"

    def start_of_grid(self, g: GenCtx) -> None:
        for _ in range(2):
            t = Tile()
            t.set_letter(C.random_letter_weighted(g.rng))
            g.add_to_rack(t)


@register
class Wheel(Item):
    game_class = "Wheel"

    def init_fields(self) -> None:
        self.fields["_hasGivenReroll"] = False

    def start_of_grid(self, g: GenCtx) -> None:
        if g.grid_number == 1 and not self.fields["_hasGivenReroll"]:
            g.rerolls_change += 3
            self.fields["_hasGivenReroll"] = True

    def start_of_encounter(self, player, rng) -> None:
        self.fields["_hasGivenReroll"] = False


@register
class Window(Item):
    game_class = "Window"

    def start_of_grid(self, g: GenCtx) -> None:
        last = g.last_word()
        if last is None or not contains_2x2(g.grid, last.tiles):
            return
        _scatter_colour(self, g, self.relevant_colours[0], 4)


@register
class WorkOfArt(Item):
    game_class = "WorkOfArt"

    def start_of_grid(self, g: GenCtx) -> None:
        by_suit = {C.HEARTS: 0, C.DIAMONDS: 1, C.CLUBS: 2, C.SPADES: 3}
        for t in g.grid.available():
            if t.suit in by_suit:
                t.tile_type = self.relevant_colours[by_suit[t.suit]]


@register
class WornOutJeans(Item):
    game_class = "WornOutJeans"

    def start_of_grid(self, g: GenCtx) -> None:
        pool = [t for t in g.grid.available() if t.is_type(self.relevant_colours[0]) and not t.is_blank()]
        for _ in range(self.var(0)):
            if not pool:
                break
            t = tile_for_item_scatter(g, C.NORMAL, C.G_BLANK, pool)
            if t is not None:
                t.set_glyph(C.G_BLANK)
                pool.remove(t)


@register
class Xray(Item):
    game_class = "Xray"

    def start_of_grid(self, g: GenCtx) -> None:
        for t in g.grid.available():
            if t.is_type(self.relevant_colours[0]) and t.srep() in C.VOWELS and not t.is_blank():
                t.set_glyph(C.G_BLANK)
