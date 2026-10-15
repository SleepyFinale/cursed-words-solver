"""Shop simulation — ``ShopController`` stock generation and player actions.

Stock: 4 stickers, 2 stamps, 2 consumable tiles. Item picks follow ``ItemPools``
build-biased rolls (dependency → upgrade → top-3 synergy tags → generator → uniform
by rarity). Frozen items carry over between shops (``Player.FrozenStickers/Stamps``).

Not yet ported (rare or item-specific): Hungry Hippo buy, Frankenstein, Eraser,
Delivery Truck tiles, Angel Investment (Future Funds), Downward Trending Chart,
Roller Skate / Rollercoaster / Lollipop / Snail counters, Meg shop, challenge rules.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from cursed_words_solver.sim.catalog import ItemDef, RunCatalog
from cursed_words_solver.sim.inventory import GENERATOR_TAGS, ConsumableTile, Inventory, OwnedItem
from cursed_words_solver.sim.run_rules import (
    BUILD_BIAS_ONE_IN,
    CONSUMABLE_GLYPH_WEIGHTS,
    FOIL_PERCENT,
    LEGENDARY_PERCENT,
    RARE_STAMP_PERCENT,
    RARE_STICKER_PERCENT,
    SHOP_STAMP_SLOTS,
    SHOP_STICKER_SLOTS,
    SHOP_TILE_SLOTS,
    TILE_COSTS,
    Ascension,
    Node,
    _weighted,
    first_item_free,
    item_price,
    random_letter,
    random_tile_type,
    reroll_price,
    starting_reroll_price,
)

CHESS_PIECES = ("pawn", "knight", "bishop", "rook", "queen", "king")
CARD_SUITS = ("hearts", "diamonds", "clubs", "spades")
FRACTIONS = (
    "1/7", "1/9", "1/10", "1/2", "1/3", "2/3", "1/4", "3/4", "1/5", "2/5", "3/5", "4/5",
    "1/6", "5/6", "1/8", "3/8", "5/8", "7/8",
)


@dataclass
class StockItem:
    item: ItemDef
    foil: bool = False
    frozen: bool = False
    first_discount: bool = False  # first-shop free pick (cleared after any buy)
    discount: int = 0

    def price(self, inv: Inventory) -> int:
        if self.first_discount:
            return 0
        # Game checks GetDescription().Contains("red") — which also matches words like
        # "scored"; descriptions aren't in the catalog, so approximate with the tag.
        red = "RedBuild" in self.item.tags
        return item_price(
            self.item.cost,
            discount=self.discount,
            avocado_count=inv.count("Avocado"),
            northern_cardinal_red=inv.has("NorthernCardinal") and red,
            blessing_of_the_shopkeeper=inv.has("BlessingOfTheShopkeeper"),
        )


@dataclass
class StockTile:
    tile: ConsumableTile
    bought: bool = False

    def price(self, inv: Inventory) -> int:
        return 1 if inv.has("FallingLeaf") else self.tile.price


@dataclass
class ShopContext:
    stage: int
    node: Node
    ascension: Ascension = Ascension.NONE
    # Shop Advice / character-starter path only fires before the character's first
    # crown win; a returning player sees the build-biased slot instead.
    character_never_won: bool = False


@dataclass
class FrozenStock:
    """Items frozen across shops (``Player.FrozenStickers`` / ``FrozenStamps``)."""

    stickers: list[StockItem | None] = field(default_factory=lambda: [None] * SHOP_STICKER_SLOTS)
    stamps: list[StockItem | None] = field(default_factory=lambda: [None] * SHOP_STAMP_SLOTS)


class ItemRoller:
    """Port of ``ItemPools`` random pickers against a catalog + inventory."""

    def __init__(self, catalog: RunCatalog, inv: Inventory, rng: random.Random, stage: int) -> None:
        self.catalog = catalog
        self.inv = inv
        self.rng = rng
        self.stage = stage
        self._pools = {
            "sticker": catalog.shop_pool("sticker"),
            "stamp": catalog.shop_pool("stamp"),
        }

    def _rare_percent(self, slot: str) -> int:
        pct = RARE_STAMP_PERCENT if slot == "stamp" else RARE_STICKER_PERCENT
        return pct * 3 ** self.inv.count("Genie")

    def _legendary_percent(self) -> int:
        return LEGENDARY_PERCENT * 3 ** self.inv.count("Genie")

    def _pick(self, items: list[ItemDef]) -> ItemDef | None:
        return items[self.rng.randrange(len(items))] if items else None

    def with_tag(self, tags, slot: str, blacklist: set[str], rarity: str | None = None) -> ItemDef | None:
        """``GetItemWithTag`` (rarity rolled unless forced)."""
        forced = rarity is not None
        if not forced:
            rare = self.rng.randrange(100) < self._rare_percent(slot)
            legendary = self.rng.randrange(100) < self._legendary_percent()
            rarity = "Legendary" if legendary else "Rare" if rare else "Common"
        tagset = set(tags)
        cands = [
            i for i in self._pools[slot]
            if tagset.intersection(i.tags) and i.game_class not in blacklist
        ]
        if not cands:
            return None
        exact = [i for i in cands if i.rarity == rarity]
        if forced:
            return self._pick(exact)
        if not exact:
            exact = [i for i in cands if i.rarity != "Legendary"]
        return self._pick(exact or cands)

    def random_item(self, slot: str, blacklist: set[str], rarity: str | None = None) -> ItemDef | None:
        """``GetRandomSticker`` / ``GetRandomStamp``."""
        source = [i for i in self._pools[slot] if i.game_class not in blacklist]

        def of(r: str) -> list[ItemDef]:
            return [i for i in source if i.rarity == r]

        if rarity is not None:
            return self._pick(of(rarity))
        if slot == "sticker":
            if self.rng.randrange(100) < self._rare_percent("sticker") and of("Rare"):
                return self._pick(of("Rare"))
            return self._pick(of("Common")) or self._pick(of("Rare"))
        roll = self.rng.randrange(100)
        if roll < self._legendary_percent() and of("Legendary"):
            return self._pick(of("Legendary"))
        if roll < self._rare_percent("stamp") and of("Rare"):
            return self._pick(of("Rare"))
        return self._pick(of("Common")) or self._pick(of("Rare")) or self._pick(of("Legendary"))

    def _non_max_upgrade_sticker(self, blacklist: set[str]) -> ItemDef | None:
        if len(self.inv.stickers) < 5:
            return None
        cands = [
            o.item for o in self.inv.stickers
            if o.item.game_class not in blacklist and not o.is_maxed and o.item.rarity != "Unique"
        ]
        return self._pick(cands)

    def build_biased(
        self,
        slot: str,
        blacklist: set[str],
        *,
        rarity: str | None = None,
        bias_for_build: bool = False,
    ) -> ItemDef | None:
        """``GetRandomBuildBiasedSticker`` / ``GetRandomBuildBiasedStamp`` (± rarity)."""
        rng = self.rng
        one_in = BUILD_BIAS_ONE_IN
        is_sticker = slot == "sticker"
        biased = bias_for_build and is_sticker

        if rng.randrange(one_in) == 0 and not biased:
            hit = self.with_tag(self.inv.unfulfilled_dependency_tags(), slot, blacklist, rarity)
            if hit is not None:
                return hit
        if is_sticker:
            upgrade_one_in = 10 if rarity is not None else (6 - len(self.inv.stickers)) * 5 + 5
            if rng.randrange(upgrade_one_in) == 0 and not biased:
                hit = self._non_max_upgrade_sticker(blacklist)
                if hit is not None:
                    return hit
        tags = self.inv.ordered_build_synergy_tags()
        for idx in range(3):
            if len(tags) > idx and (rng.randrange(one_in) == 0 or biased):
                hit = self.with_tag([tags[idx]], slot, blacklist, rarity)
                if hit is not None:
                    return hit
        if rng.randrange(10) == 0:
            if self.stage < 2 or not self.inv.has_generator():
                return self.with_tag(GENERATOR_TAGS, slot, blacklist, rarity)
        return self.random_item(slot, blacklist, rarity)


class ShopSession:
    """One shop visit. Mutates ``inv`` and ``frozen`` in place."""

    def __init__(
        self,
        catalog: RunCatalog,
        inv: Inventory,
        ctx: ShopContext,
        rng: random.Random,
        frozen: FrozenStock | None = None,
    ) -> None:
        self.catalog = catalog
        self.inv = inv
        self.ctx = ctx
        self.rng = rng
        self.frozen = frozen or FrozenStock()
        self.stickers: list[StockItem | None] = [None] * SHOP_STICKER_SLOTS
        self.stamps: list[StockItem | None] = [None] * SHOP_STAMP_SLOTS
        self.tiles: list[StockTile | None] = [None] * SHOP_TILE_SLOTS
        self.base_reroll_price = starting_reroll_price(ctx.ascension)
        self.reroll_count = 0
        self.first_shop = first_item_free(ctx.stage, ctx.node, ctx.ascension)
        self.foil_percent = 5 if inv.has("FortuneCookie") else FOIL_PERCENT
        self._generate(is_reroll=False)

    # -- prices -----------------------------------------------------------------

    @property
    def reroll_cost(self) -> int:
        return reroll_price(self.base_reroll_price, fried_shrimp=self.inv.has("FriedShrimp"))

    # -- generation (GenerateGoodsInStock) ----------------------------------------

    def _generate(self, *, is_reroll: bool) -> None:
        roller = ItemRoller(self.catalog, self.inv, self.rng, self.ctx.stage)
        first = self.first_shop and not is_reroll
        starter_idx = -1
        if first and self.ctx.character_never_won:
            starter_idx = self.rng.randrange(SHOP_STICKER_SLOTS)
        bias_idx = -1
        if self.ctx.node == Node.SHOP_ONE and self.ctx.stage == 1 and starter_idx == -1 and not is_reroll:
            bias_idx = self.rng.randrange(SHOP_STICKER_SLOTS)

        for k in range(SHOP_STICKER_SLOTS):
            held = self.frozen.stickers[k]
            if held is not None:
                self.stickers[k] = held
                continue
            if k == starter_idx:
                self.stickers[k] = self._starter_item(k)
            else:
                self.stickers[k] = self._roll_sticker(roller, k, first, bias=k == bias_idx)

        for k in range(SHOP_STAMP_SLOTS):
            held = self.frozen.stamps[k]
            if held is not None:
                self.stamps[k] = held
                continue
            self.stamps[k] = self._roll_stamp(roller, k, first)

        for k in range(SHOP_TILE_SLOTS):
            self.tiles[k] = StockTile(self._roll_tile())

    def _stock_classes(self, stock: list[StockItem | None], frozen: list[StockItem | None]) -> set[str]:
        return {s.item.game_class for s in stock if s is not None} | {
            s.item.game_class for s in frozen if s is not None
        }

    def _starter_item(self, k: int) -> StockItem | None:
        char = self.catalog.character(self.inv.character)
        blacklist = {o.item.game_class for o in self.inv.stickers if o.is_maxed}
        blacklist |= self._stock_classes(self.stickers, self.frozen.stickers)
        cands = [c for c in char.intro_items if c not in blacklist and c in self.catalog.items]
        if not cands:
            return None
        return StockItem(self.catalog.items[cands[self.rng.randrange(len(cands))]], first_discount=True)

    def _roll_sticker(self, roller: ItemRoller, k: int, first: bool, *, bias: bool) -> StockItem | None:
        foil = self.rng.randrange(100) < self.foil_percent
        in_stock = self._stock_classes(self.stickers, self.frozen.stickers)
        if foil and not first:
            blacklist = in_stock | {o.item.game_class for o in self.inv.stickers if o.foil}
        else:
            blacklist = {o.item.game_class for o in self.inv.stickers if o.is_maxed} | in_stock
        blacklist |= self.inv.embargoed
        if first:
            item = roller.build_biased("sticker", blacklist, rarity="Common", bias_for_build=bias)
            return StockItem(item, first_discount=True) if item else None
        item = roller.build_biased("sticker", blacklist, bias_for_build=bias)
        return StockItem(item, foil=foil) if item else None

    def _roll_stamp(self, roller: ItemRoller, k: int, first: bool) -> StockItem | None:
        blacklist = {o.item.game_class for o in self.inv.stamps}
        blacklist |= self._stock_classes(self.stamps, self.frozen.stamps)
        blacklist |= self.inv.embargoed
        item = roller.build_biased("stamp", blacklist, rarity="Common" if first else None)
        return StockItem(item, first_discount=first) if item else None

    def _roll_tile(self) -> ConsumableTile:
        rng = self.rng
        glyph = _weighted(rng, CONSUMABLE_GLYPH_WEIGHTS)
        tile = ConsumableTile(glyph=glyph)
        if glyph == "letter":
            tile.value = random_letter(rng)
        elif glyph == "number":
            if rng.randrange(5) == 0:
                tile.glyph = "fraction"
                tile.value = FRACTIONS[rng.randrange(len(FRACTIONS))]
            else:
                tile.value = str(rng.randrange(1, 10))
        elif glyph == "chess":
            tile.value = CHESS_PIECES[rng.randrange(len(CHESS_PIECES))]
            rng.randrange(2)  # piece colour
        if rng.randrange(10) == 0 and glyph != "joker":
            tile.suit = CARD_SUITS[rng.randrange(len(CARD_SUITS))]
        tile.colour = random_tile_type(rng, self.inv.available_colours, coloured_only=glyph == "letter")
        tile.price = TILE_COSTS[tile.colour]
        return tile

    # -- actions ----------------------------------------------------------------

    def can_buy_item(self, slot: str, index: int) -> bool:
        stock = self.stickers if slot == "sticker" else self.stamps
        offer = stock[index] if 0 <= index < len(stock) else None
        if offer is None:
            return False
        if self.inv.money < offer.price(self.inv) and not offer.first_discount:
            return False
        if slot == "stamp":
            return len(self.inv.stamps) < self.inv.stamp_slots and self.inv.owned_stamp(offer.item.game_class) is None
        owned = self.inv.owned_sticker(offer.item.game_class)
        if owned is not None:
            return not owned.is_maxed
        return len(self.inv.stickers) < self.inv.sticker_slots

    def buy_item(self, slot: str, index: int) -> bool:
        """``OnItemBuyButtonClicked`` → ``BuySticker`` / ``BuyStamp``.

        Buying an owned sticker upgrades it (and applies foil). The first-shop free
        pick costs $0; any purchase clears first-discount on the remaining stock.
        """
        if not self.can_buy_item(slot, index):
            return False
        stock = self.stickers if slot == "sticker" else self.stamps
        frozen = self.frozen.stickers if slot == "sticker" else self.frozen.stamps
        offer = stock[index]
        assert offer is not None
        cost = offer.price(self.inv)
        if slot == "sticker":
            owned = self.inv.owned_sticker(offer.item.game_class)
            if owned is not None:
                if offer.foil:
                    owned.foil = True
                owned.times_upgraded += 1
                owned.money_invested.append(cost)
            else:
                self.inv.stickers.append(OwnedItem(offer.item, foil=offer.foil, money_invested=[cost]))
        else:
            self.inv.stamps.append(OwnedItem(offer.item, money_invested=[cost]))
        self.inv.money -= cost
        stock[index] = None
        frozen[index] = None
        self._clear_first_discount()
        if self.inv.has("EfficientRecycler"):
            self.reroll_count += 1
            self._generate(is_reroll=True)
        return True

    def _clear_first_discount(self) -> None:
        for s in self.stickers + self.stamps:
            if s is not None:
                s.first_discount = False
        self.first_shop = False

    def can_buy_tile(self, index: int) -> bool:
        offer = self.tiles[index] if 0 <= index < len(self.tiles) else None
        if offer is None or offer.bought:
            return False
        return self.inv.money >= offer.price(self.inv) and len(self.inv.tiles) < self.inv.consumable_capacity()

    def buy_tile(self, index: int) -> bool:
        if not self.can_buy_tile(index):
            return False
        offer = self.tiles[index]
        assert offer is not None
        self.inv.money -= offer.price(self.inv)
        self.inv.tiles.append(offer.tile)
        offer.bought = True
        return True

    def toggle_freeze(self, slot: str, index: int) -> bool:
        stock = self.stickers if slot == "sticker" else self.stamps
        frozen = self.frozen.stickers if slot == "sticker" else self.frozen.stamps
        offer = stock[index]
        if offer is None:
            return False
        offer.frozen = not offer.frozen
        frozen[index] = offer if frozen[index] is None else None
        return True

    def can_reroll(self) -> bool:
        return self.inv.money >= self.reroll_cost

    def reroll(self) -> bool:
        """``OnRerollButtonClickedCallback`` — pay, price +1, regenerate unfrozen stock."""
        if not self.can_reroll():
            return False
        self.inv.money -= self.reroll_cost
        self.base_reroll_price += 1
        self.reroll_count += 1
        self._generate(is_reroll=True)
        return True

    def sell(self, kind: str, index: int) -> bool:
        items = self.inv.stickers if kind == "sticker" else self.inv.stamps
        if not (0 <= index < len(items)):
            return False
        owned = items[index]
        if owned.item.selling_prevented:
            return False
        self.inv.money += self.inv.sell_price(owned)
        items.pop(index)
        return True

    def move(self, kind: str, src: int, dst: int) -> bool:
        """Reorder stickers or stamps (scoring order matters)."""
        items = self.inv.stickers if kind == "sticker" else self.inv.stamps
        if not (0 <= src < len(items) and 0 <= dst < len(items)):
            return False
        items.insert(dst, items.pop(src))
        return True
