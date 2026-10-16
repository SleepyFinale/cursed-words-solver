"""``ShopController`` port: stock, buying / upgrading, freezing, rerolls, tiles, selling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cursed_words_solver.sim.game import core as C
from cursed_words_solver.sim.game.core import Rng, Tile
from cursed_words_solver.sim.game.items import Item, make_item, random_scattered_item, random_coloured_tile_type, random_tile_type
from cursed_words_solver.sim.game.player import Node
from cursed_words_solver.sim.game.pools import build_biased_stamp, build_biased_sticker, random_sticker, sticker_pool

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.encounter import Encounter
    from cursed_words_solver.sim.game.player import Player

TILE_COSTS = {
    C.NORMAL: 2, C.RED: 3, C.BLUE: 3, C.VOID: 2, C.SHINY: 4, C.PURPLE: 3, C.GOLD: 3,
    C.WHITE: 3, C.GREEN: 3, C.CACTUS: 3, C.PINK: 3, C.GLITCH: 3,
}
# ShopController._consumableTileTypeWeightings after GetTotalFrequency (fully unlocked).
CONSUMABLE_GLYPHS = {C.G_LETTER: 19, C.G_BLANK: 1, C.G_NUMBER: 1, C.G_CARD: 1, C.G_CHESS: 1}


@dataclass(eq=False)
class ItemInStock:
    item: Item
    cost: int = 0
    frozen: bool = False
    first_discount: bool = False
    free: bool = False

    def reset_cost(self, player: "Player") -> None:
        self.cost = self.item.get_cost(player)


@dataclass(eq=False)
class TileInStock:
    tile: Tile
    price: int
    bought: bool = False

    def get_price(self, player: "Player") -> int:
        return 1 if player.unpacked_of("FallingLeaf") else self.price


def sell_item(player: "Player", item: Item, rng: Rng, *, encounter: "Encounter | None" = None, shop: "Shop | None" = None) -> int | None:
    """``InventoryVisualController`` sell (returns money change, None when not allowed)."""
    if not can_sell(player, item):
        return None
    pf = player.run.challenge_is("PlayingFavourites")
    triggers = not pf or item is _hb_fav_stamp(player) or item.is_hb_favourite_sticker
    player.remove_item(item)
    if triggers:
        cls = item.game_class
        if cls == "MysteryGift":
            gift = random_sticker(rng, player, [s.game_class for s in player.stickers_list(for_comparison=True)], "Rare")
            if gift is not None:
                for _ in range(1, item.level(0)):
                    gift.upgrade(0)
                gift.is_foil = item.is_foil
                gift.times_upgraded = item.times_upgraded
                player.add_item(gift, rng)
        elif cls == "SewingNeedle":
            black = set(item.fields.get("BlacklistedItems", ()))
            pool = [s for s in player.stickers_list(for_comparison=True) if s.game_class not in black]
            if len(pool) >= 2:
                a = pool.pop(rng.range(0, len(pool)))
                b = pool.pop(rng.range(0, len(pool)))
                foil = a.is_foil or b.is_foil
                lvl = max(a.level(0), b.level(0))
                fr = make_item("Frankenstein")
                for part in (a, b):
                    cp = part.clone()
                    cp.is_foil = False
                    while cp.level(0) > 1:
                        cp.downgrade(0)
                    fr.stitched.append(cp)
                fr._retag()
                for _ in range(1, lvl):
                    fr.upgrade(0)
                fr.is_foil = foil
                fr.times_upgraded = lvl - 1
                fr.money_invested = list(a.money_invested) + list(b.money_invested)
                player.remove_item(a)
                player.remove_item(b)
                player.add_item(fr, rng)
        elif cls == "SignalReceiver" and encounter is not None:
            owned = {i.game_class for i in player.all_items(for_comparison=True)}
            for fr in player.unpacked_of("Frankenstein", for_comparison=True):
                owned |= {s.game_class for s in fr.stitched}
            cands = [t for t in encounter.grid.available() if t.get_glyph() == C.G_ITEM and t.item is not None
                     and t.item.is_sticker and t.item.game_class not in owned]
            if cands:
                got = make_item(cands[rng.range(0, len(cands))].item.game_class)
                for _ in range(1, item.level(0)):
                    got.upgrade(0)
                got.is_foil = item.is_foil
                got.times_upgraded = item.times_upgraded
                player.add_item(got, rng)
        elif cls == "Stadium":
            for i in range(5, 10):
                player.consumables[i] = None
        elif cls == "Unicorn":
            plain = [s for s in player.stickers_list(for_comparison=True) if not s.is_foil]
            if plain:
                plain[rng.range(0, len(plain))].is_foil = True
    if item.costs_money_to_sell:
        delta = -item.sell_cost
    else:
        delta = item.sell_value(player)
    before = player.money
    player.change_money(delta)
    if shop is not None:
        shop.after_sell()
    return player.money - before


def can_sell(player: "Player", item: Item) -> bool:
    if player.run.challenge_is("Embargo"):
        return False
    if item.costs_money_to_sell:
        return player.money >= item.sell_cost and (item in player.stickers or item in player.stamps)
    if item.selling_prevented:
        return False
    return item in player.stickers or item in player.stamps


def _hb_fav_stamp(player: "Player") -> Item | None:
    return next((s for s in player.stamps_list(for_comparison=True) if player.is_hb_favourite_stamp(s)), None)


class Shop:
    """One shop visit (ShopZero / ShopOne / ShopTwo / Meg shop)."""

    def __init__(self, player: "Player", rng: Rng, *, character_never_won: bool = False) -> None:
        self.player = player
        self.rng = rng
        self.character_never_won = character_never_won
        run = player.run
        self.is_meg = run.node == Node.MEG_SHOP
        self._meg_frozen: tuple[list, list] | None = None
        if self.is_meg:
            self._meg_frozen = (list(player.frozen_stickers), list(player.frozen_stamps))
            player.frozen_stickers = [None] * 4
            player.frozen_stamps = [None] * 2
        self.stickers: list[ItemInStock | None] = [None] * 4
        self.stamps: list[ItemInStock | None] = [None] * 2
        self.tiles: list[TileInStock | None] = [None] * 2
        self.foil_percent = 5 if player.unpacked_of("FortuneCookie") else 1
        self.reroll_price = 2 if run.asc(2) else 1
        if self.is_meg:
            self.reroll_price = 1
        self.reroll_deduction = 1 if player.unpacked_of("FriedShrimp") else 0
        self.reroll_count = 0
        self.used_angel = False
        self.free_item_active = run.node == Node.SHOP_ONE and run.stage == 1 and not run.asc(2)
        for skate in player.unpacked_of("RollerSkate"):
            skate.fields["PreviousShopRestockCount"] = 0
        player._shop_listener = self._on_item_event
        self._generate(self.free_item_active, is_reroll=False, free=self.angel_available())
        self.left = False

    @classmethod
    def from_snapshot(cls, player: "Player", rng: Rng, snap: dict[str, Any]) -> "Shop":
        """Rebuild a live shop from melmod ``run_state.shop`` (no stock is generated)."""
        from cursed_words_solver.sim.game.importer import item_from_row, tile_from_row

        self = cls.__new__(cls)
        self.player, self.rng = player, rng
        self.character_never_won = False
        run = player.run
        self.is_meg = run.node == Node.MEG_SHOP
        self._meg_frozen = None
        self.stickers = [None] * 4
        self.stamps = [None] * 2
        self.tiles = [None] * 2
        self.foil_percent = 5 if player.unpacked_of("FortuneCookie") else 1
        self.reroll_price = int(snap.get("restock_cost") or 1)
        self.reroll_deduction = 1 if player.unpacked_of("FriedShrimp") else 0
        self.reroll_count = 0
        self.used_angel = bool(player.unpacked_of("FutureFunds")) and not snap.get("angel_investment_available")
        self.free_item_active = bool(snap.get("free_item_available"))
        self.left = False
        for o in snap.get("offers") or ():
            slot, idx = o.get("slot"), int(o.get("index", 0))
            if slot in ("sticker", "stamp"):
                state = o.get("item_state") if isinstance(o.get("item_state"), dict) else None
                row = state or {"class": o.get("game_class") or "", "id": o.get("id")}
                it = item_from_row(row)
                if it is None:
                    continue
                it.is_foil = bool(o.get("foil", it.is_foil))
                offer = ItemInStock(it, int(o.get("base_price", o.get("price", 0)) or 0),
                                    frozen=bool(o.get("frozen")), first_discount=bool(o.get("first_discount")),
                                    free=bool(o.get("free")))
                arr = self.stickers if slot == "sticker" else self.stamps
                if 0 <= idx < len(arr):
                    arr[idx] = offer
            elif slot == "tile" and 0 <= idx < 2:
                ts = o.get("tile_state")
                if isinstance(ts, dict):
                    tile = tile_from_row(ts)
                else:
                    tile = Tile()
                    tile.set_letter(str(o.get("letter") or "a").lower())
                    tile.tile_type = C.TYPE_FROM_GAME.get(str(o.get("color") or "").capitalize(), C.NORMAL)
                self.tiles[idx] = TileInStock(tile, int(o.get("base_price", o.get("price", 2)) or 2), bought=bool(o.get("sold")))
        player._shop_listener = self._on_item_event
        return self

    # -- prices -------------------------------------------------------------------

    @property
    def reroll_cost(self) -> int:
        return max(self.reroll_price - self.reroll_deduction, 0)

    def angel_available(self) -> bool:
        return not self.used_angel and bool(self.player.unpacked_of("FutureFunds"))

    def offer_cost(self, offer: ItemInStock) -> int:
        if offer.first_discount or self.angel_available():
            return 0
        return offer.cost

    # -- generation -----------------------------------------------------------------

    def _generate(self, first_shop: bool, *, is_reroll: bool, free: bool) -> None:
        """``GenerateGoodsInStock``."""
        player, run, rng = self.player, self.player.run, self.rng
        starter_idx = -1
        if first_shop and not is_reroll and self.character_never_won:
            starter_idx = rng.range(0, 4)
        bias_idx = -1
        if run.node == Node.SHOP_ONE and run.stage == 1 and starter_idx == -1 and not is_reroll:
            bias_idx = rng.range(0, 4)
        if is_reroll and player.unpacked_of("Eraser"):
            for o in self.stickers + self.stamps:
                if o is not None and not o.frozen:
                    run.embargoed.add(o.item.game_class)
        for k in range(4):
            held = player.frozen_stickers[k]
            if held is None:
                if k == starter_idx:
                    black = [s.game_class for s in player.stickers_list(for_comparison=True) if s.times_upgraded == player.max_upgrade_count(s)]
                    black += [o.item.game_class for o in self.stickers if o is not None]
                    black += [f.item.game_class for f in player.frozen_stickers if f is not None]
                    cands = [c for c in player.intro_items if c not in black]
                    if cands:
                        it = make_item(cands[rng.range(0, len(cands))])
                        self._maybe_colourswap(it)
                        offer = ItemInStock(it, it.get_cost(player))
                        offer.first_discount = True
                        self.stickers[k] = offer
                    else:
                        self._gen_sticker(k, first_shop, free, bias=True)
                elif k == bias_idx:
                    self._gen_sticker(k, first_shop, free, bias=True)
                else:
                    self._gen_sticker(k, first_shop, free)
            else:
                if not is_reroll and player.unpacked_of("DownwardTrendingChart"):
                    held.item.discount += 2
                    held.reset_cost(player)
                held.first_discount, held.free = first_shop, free
                self.stickers[k] = held
        for k in range(2):
            held = player.frozen_stamps[k]
            if held is None:
                self._gen_stamp(k, first_shop, free)
            else:
                if not is_reroll and player.unpacked_of("DownwardTrendingChart"):
                    held.item.discount += 2
                    held.reset_cost(player)
                if not is_reroll and held.item.game_class == "Avocado":
                    held.item.fields["IsMushy"] = True
                held.first_discount, held.free = first_shop, free
                self.stamps[k] = held
        for k in range(2):
            self._gen_tile(k)

    def _maybe_colourswap(self, it: Item | None) -> None:
        if it is not None and (self.player.run.challenge_is("ColourSwap") or self.player.unpacked_of("CanOfBeans")):
            it.randomise_relevant_colours(self.player, self.rng)

    def _gen_sticker(self, k: int, first_shop: bool, free: bool, bias: bool = False) -> None:
        player, run, rng = self.player, self.player.run, self.rng
        if run.challenge_is("Masochist") or run.challenge_is("InTheBeginning"):
            return
        cur = self.stickers[k]
        if cur is not None and cur.frozen:
            return
        foil = rng.range(0, 100) < self.foil_percent
        if foil and not first_shop:
            black = [o.item.game_class for o in self.stickers if o is not None]
            black += [f.item.game_class for f in player.frozen_stickers if f is not None]
            black += [s.game_class for s in player.stickers_list(for_comparison=True) if s.is_foil]
        else:
            black = [s.game_class for s in player.stickers_list(for_comparison=True) if s.times_upgraded >= player.max_upgrade_count(s)]
            black += [o.item.game_class for o in self.stickers if o is not None]
            black += [f.item.game_class for f in player.frozen_stickers if f is not None]
        black += list(run.embargoed)
        black = [b for b in black if b != "Frankenstein"]
        if first_shop:
            it = build_biased_sticker(rng, player, black, rarity="Common", bias_for_build=bias)
            self._maybe_colourswap(it)
            if it is None:
                self.stickers[k] = None
                return
            offer = ItemInStock(it, it.get_cost(player), first_discount=True)
            self.stickers[k] = offer
            return
        it = build_biased_sticker(rng, player, black, bias_for_build=bias)
        self._maybe_colourswap(it)
        if it is None:
            self.stickers[k] = None
            return
        it.is_foil = foil
        self.stickers[k] = ItemInStock(it, it.get_cost(player), free=free)

    def _gen_stamp(self, k: int, first_shop: bool, free: bool) -> None:
        player, run, rng = self.player, self.player.run, self.rng
        if run.challenge_is("Antiphilatelist") or run.challenge_is("InTheBeginning"):
            return
        cur = self.stamps[k]
        if cur is not None and cur.frozen:
            return
        black = [s.game_class for s in player.stamps_list(for_comparison=True)]
        black += [o.item.game_class for o in self.stamps if o is not None]
        black += [f.item.game_class for f in player.frozen_stamps if f is not None]
        if run.challenge is not None:
            black.append("CoinPurse")
        black += list(run.embargoed)
        it = build_biased_stamp(rng, player, black, rarity="Common" if first_shop else None)
        self._maybe_colourswap(it)
        if it is None:
            self.stamps[k] = None
            return
        self.stamps[k] = ItemInStock(it, it.get_cost(player), first_discount=first_shop, free=free and not first_shop)

    def _gen_tile(self, k: int) -> None:
        player, rng = self.player, self.rng
        if player.unpacked_of("DeliveryTruck"):
            t = Tile()
            it = random_scattered_item(rng, player)
            self._maybe_colourswap(it)
            t.set_item(it)
            t.tile_type = random_tile_type(rng, player)
            if rng.range(0, 10) == 0:
                t.set_suit(C.random_card_suit(rng))
            self.tiles[k] = TileInStock(t, TILE_COSTS[t.tile_type])
            return
        t = Tile()
        glyph = C.weighted_pick(rng, CONSUMABLE_GLYPHS)
        letter = False
        if glyph == C.G_LETTER:
            letter = True
            t.set_letter(C.random_letter_weighted(rng))
        elif glyph == C.G_BLANK:
            t.set_glyph(C.G_BLANK)
        elif glyph == C.G_NUMBER:
            if rng.range(0, 5) == 0:
                t.set_fraction(C.random_fraction(rng))
            else:
                t.set_number(rng.range(1, 10))
        elif glyph == C.G_CARD:
            t.set_glyph(C.G_CARD)
            t.set_suit(C.SUIT_JOKER)
        elif glyph == C.G_CHESS:
            t.set_chess(*C.random_chess_piece(rng))
        if rng.range(0, 10) == 0 and t.suit != C.SUIT_JOKER:
            t.set_suit(C.random_card_suit(rng))
        t.tile_type = random_coloured_tile_type(rng, player) if letter else random_tile_type(rng, player)
        self.tiles[k] = TileInStock(t, TILE_COSTS[t.tile_type])

    # -- events from items -----------------------------------------------------------

    def _on_item_event(self, kind: str) -> bool:
        if kind == "repopulate":
            self.reroll_deduction = 1 if self.player.unpacked_of("FriedShrimp") else 0
            self.update_costs()
        elif kind == "foil":
            self.foil_percent = 5 if self.player.unpacked_of("FortuneCookie") else 0
        elif kind == "volcano":
            for o in self.stickers + self.stamps:
                if o is not None:
                    o.frozen = False
            self.player.frozen_stickers = [None] * 4
            self.player.frozen_stamps = [None] * 2
        return True

    def update_costs(self) -> None:
        for o in self.stickers + self.stamps:
            if o is not None:
                o.reset_cost(self.player)

    def _reset_first_discounts(self) -> None:
        for o in self.stickers + self.stamps:
            if o is not None and (o.first_discount or o.free):
                o.reset_cost(self.player)
                o.first_discount = False
                o.free = False

    def after_sell(self) -> None:
        self.foil_percent = 5 if self.player.unpacked_of("FortuneCookie") else 0
        self.update_costs()
        self.reroll_deduction = 1 if self.player.unpacked_of("FriedShrimp") else 0

    # -- actions ------------------------------------------------------------------

    def _owned_or_stitched(self, cls: str) -> bool:
        player = self.player
        if any(i.game_class == cls for i in player.all_items(for_comparison=True)):
            return True
        for fr in player.stickers_list(for_comparison=True):
            if fr.game_class == "Frankenstein" and any(s.game_class == cls for s in fr.stitched[:2]):
                return True
        return False

    def can_buy(self, kind: str, index: int) -> bool:
        stock = self.stickers if kind == "sticker" else self.stamps
        if not (0 <= index < len(stock)) or stock[index] is None:
            return False
        offer = stock[index]
        player = self.player
        if player.money < offer.cost and not self.angel_available() and not offer.first_discount:
            return False
        if kind == "stamp":
            if len(player.stamps_list(for_comparison=True)) >= 5 or None not in player.stamps:
                return False
            return not any(s.game_class == offer.item.game_class for s in player.stamps_list(for_comparison=True))
        owned = self._owned_or_stitched(offer.item.game_class)
        if len(player.stickers_list(for_comparison=True)) >= 5 and not owned:
            return False
        targets = self._upgrade_targets(offer.item)
        if any(t.times_upgraded >= player.max_upgrade_count(t) for t in targets):
            return False
        if not targets and None not in player.stickers:
            return False
        return True

    def _upgrade_targets(self, item: Item) -> list[Item]:
        player = self.player
        out = [s for s in player.stickers_list(for_comparison=True) if s.game_class == item.game_class]
        for fr in player.stickers_list(for_comparison=True):
            if fr.game_class == "Frankenstein" and any(s.game_class == item.game_class for s in fr.stitched[:2]):
                out.append(fr)
        return out

    def buy(self, kind: str, index: int, *, hippo: bool = False) -> bool:
        """``OnItemBuyButtonClicked`` / ``OnHippoButtonClicked``."""
        if not self.can_buy(kind, index):
            return False
        self.free_item_active = False
        stock = self.stickers if kind == "sticker" else self.stamps
        offer = stock[index]
        assert offer is not None
        ok = self._buy_stamp(index, offer) if kind == "stamp" else self._buy_sticker(index, offer, hippo)
        self._reset_first_discounts()
        self.update_costs()
        if ok and self.player.unpacked_of("EfficientRecycler"):
            self._restock_counters()
            self._generate(False, is_reroll=True, free=self.angel_available())
        return ok

    def _pay(self, offer: ItemInStock, target: Item) -> None:
        player = self.player
        if self.angel_available():
            self.used_angel = True
            target.money_invested.append(0)
        elif not offer.first_discount:
            player.change_money(-offer.cost)
            target.money_invested.append(offer.cost)
        else:
            target.money_invested.append(0)

    def _buy_stamp(self, index: int, offer: ItemInStock) -> bool:
        player = self.player
        if None not in player.stamps:
            return False
        if any(s.game_class == offer.item.game_class for s in player.stamps_list(for_comparison=True)):
            return False
        player.add_item(offer.item, self.rng)
        self._pay(offer, offer.item)
        player.frozen_stamps[index] = None
        self.stamps[index] = None
        if player.run.challenge_is("DecisionParalysis"):
            self._gen_stamp(index, False, False)
        return True

    def _buy_sticker(self, index: int, offer: ItemInStock, hippo: bool) -> bool:
        player = self.player
        item = offer.item
        if hippo:
            hh = make_item("HungryHippo")
            hh.is_foil = item.is_foil
            item = hh
        if item.is_foil:
            held = next((s for s in player.stickers_list(for_comparison=True) if s.game_class == item.game_class), None)
            if held is not None:
                held.is_foil = True
        targets = self._upgrade_targets(item)
        if any(t.times_upgraded >= player.max_upgrade_count(t) for t in targets):
            return False
        upgradable = [t for t in targets if t.times_upgraded < player.max_upgrade_count(t)]
        if not upgradable and None not in player.stickers:
            return False
        if upgradable:
            tgt = upgradable[0]
            tgt.upgrade(0, rng=self.rng, player=player)
            tgt.times_upgraded += 1
            if item.is_foil and tgt.game_class == "Frankenstein":
                tgt.is_foil = True
            self._pay(offer, tgt)
        else:
            player.add_item(item, self.rng)
            self._pay(offer, item)
        player.frozen_stickers[index] = None
        self.stickers[index] = None
        if player.run.challenge_is("DecisionParalysis"):
            self._gen_sticker(index, False, False)
        return True

    def _restock_counters(self) -> None:
        player = self.player
        self.reroll_count += 1
        for skate in player.unpacked_of("RollerSkate"):
            skate.fields["PreviousShopRestockCount"] = self.reroll_count
        from cursed_words_solver.sim.game.encounter import rollercoaster_check

        for _ in player.unpacked_of("Rollercoaster"):
            rollercoaster_check(player, self.rng)
        for pop in player.unpacked_of("Lollipop", for_comparison=True):
            pop.fields["Bonus"] = int(pop.fields.get("Bonus", 0)) + pop.var(0)
        for snail in player.unpacked_of("Snail", for_comparison=True):
            snail.fields["RerollCount"] = int(snail.fields.get("RerollCount", 0)) + 1

    def can_reroll(self) -> bool:
        return self.player.money >= self.reroll_cost and not self.player.run.challenge_is("DecisionParalysis")

    def reroll(self) -> bool:
        """``OnRerollButtonClickedCallback``."""
        if not self.can_reroll():
            return False
        self.free_item_active = False
        player = self.player
        from cursed_words_solver.sim.game.encounter import rollercoaster_check

        for _ in player.unpacked_of("Rollercoaster"):
            rollercoaster_check(player, self.rng)
        for pop in player.unpacked_of("Lollipop"):
            pop.fields["Bonus"] = int(pop.fields.get("Bonus", 0)) + pop.var(0)
        for snail in player.unpacked_of("Snail"):
            snail.fields["RerollCount"] = int(snail.fields.get("RerollCount", 0)) + 1
        player.change_money(-self.reroll_cost)
        self.reroll_price = 1 if self.is_meg else self.reroll_price + 1
        self.reroll_count += 1
        for skate in player.unpacked_of("RollerSkate"):
            skate.fields["PreviousShopRestockCount"] = self.reroll_count
        self._generate(False, is_reroll=True, free=self.angel_available())
        self.reroll_deduction = 1 if player.unpacked_of("FriedShrimp") else 0
        return True

    def toggle_freeze(self, kind: str, index: int) -> bool:
        stock = self.stickers if kind == "sticker" else self.stamps
        frozen = self.player.frozen_stickers if kind == "sticker" else self.player.frozen_stamps
        if not (0 <= index < len(stock)) or stock[index] is None:
            return False
        offer = stock[index]
        offer.frozen = not offer.frozen
        frozen[index] = offer if frozen[index] is None else None
        return True

    def can_buy_tile(self, index: int) -> bool:
        offer = self.tiles[index] if 0 <= index < 2 else None
        player = self.player
        if offer is None or offer.bought:
            return False
        if player.money < offer.get_price(player):
            return False
        n = len(player.tiles())
        return n < player.consumable_capacity()

    def buy_tile(self, index: int) -> bool:
        if not self.can_buy_tile(index):
            return False
        offer = self.tiles[index]
        player = self.player
        if None not in player.consumables:
            return False
        player.add_tile(offer.tile)
        player.change_money(-offer.get_price(player))
        if player.run.challenge_is("DecisionParalysis"):
            self._gen_tile(index)
        else:
            offer.bought = True
        return True

    def sell(self, item: Item) -> int | None:
        return sell_item(self.player, item, self.rng, shop=self)

    def leave(self) -> None:
        """``OnLeaveShopButtonClickedCallback``."""
        player = self.player
        for skate in player.unpacked_of("RollerSkate"):
            skate.fields["PreviousShopRestockCount"] = self.reroll_count
        for _ in player.unpacked_of("SurpriseDelivery"):
            owned = {s.game_class for s in player.stickers_list(for_comparison=True)}
            from cursed_words_solver.sim.game.pools import rarity_of

            pool = [c for c in sticker_pool() if c not in owned and rarity_of(c) == "Common"]
            if pool:
                player.add_item(make_item(pool[self.rng.range(0, len(pool))]), self.rng)
        for f in player.frozen_stamps:
            if f is not None and f.item.game_class == "ShavedIce":
                f.item.fields["Freezes"] = int(f.item.fields.get("Freezes", 0)) + 1
        if self.is_meg and self._meg_frozen is not None:
            player.frozen_stickers, player.frozen_stamps = self._meg_frozen
        player._shop_listener = None
        self.left = True

    # -- observation ------------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        p = self.player
        return {
            "stickers": [None if o is None else {"cls": o.item.game_class, "cost": self.offer_cost(o), "foil": o.item.is_foil, "frozen": o.frozen} for o in self.stickers],
            "stamps": [None if o is None else {"cls": o.item.game_class, "cost": self.offer_cost(o), "frozen": o.frozen} for o in self.stamps],
            "tiles": [None if o is None or o.bought else {"tile": o.tile.srep(), "type": o.tile.tile_type, "cost": o.get_price(p)} for o in self.tiles],
            "reroll_cost": self.reroll_cost,
            "money": p.money,
        }
