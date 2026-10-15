"""Run-level rules ported from RunProgress / EncounterController / ShopController."""

from __future__ import annotations

import random

import pytest

from cursed_words_solver.sim.catalog import load_run_catalog
from cursed_words_solver.sim.inventory import Inventory, OwnedItem
from cursed_words_solver.sim.run_rules import (
    ENCOUNTER_NODES,
    Ascension,
    Node,
    credited_payout,
    encounter_payout,
    encounter_target,
    generate_boss_drafts,
    grids_per_round,
    next_node,
    run_won_after_boss,
    sell_value,
)
from cursed_words_solver.sim.shop import FrozenStock, ShopContext, ShopSession


@pytest.fixture(scope="module")
def catalog():
    return load_run_catalog()


def test_crown0_targets_match_round_logs():
    table = [[encounter_target(s, n, 0) for n in ENCOUNTER_NODES] for s in range(1, 6)]
    assert table == [
        [12, 17, 24],
        [48, 67, 96],
        [168, 235, 336],
        [660, 924, 1320],
        [2508, 3511, 5016],
    ]


@pytest.mark.parametrize(
    ("stage", "node", "crown", "target"),
    [
        (1, Node.BOSS, 1, 25),
        (2, Node.BOSS, 2, 118),
        (2, Node.BOSS, 3, 129),
    ],
)
def test_crown_targets_seen_in_round_logs(stage, node, crown, target):
    assert encounter_target(stage, node, crown) == target


def test_diving_mask_reduces_target():
    # Round log: stage 4 EncounterFirst target 1013 = crown 3 with a 10% Diving Mask.
    assert encounter_target(4, Node.ENCOUNTER_FIRST, 3, diving_mask_percent=10, has_diving_mask=True) == 1013


def test_stage_progression():
    seq = [(0, Node.NONE)]
    for _ in range(12):
        seq.append(next_node(*seq[-1]))
    assert seq[1:] == [
        (1, Node.ENCOUNTER_FIRST), (1, Node.SHOP_ONE), (1, Node.ENCOUNTER_SECOND),
        (1, Node.SHOP_TWO), (1, Node.BOSS_DRAFT), (1, Node.BOSS), (1, Node.BOSS_REWARD),
        (2, Node.SHOP_ZERO), (2, Node.ENCOUNTER_FIRST), (2, Node.SHOP_ONE),
        (2, Node.ENCOUNTER_SECOND), (2, Node.SHOP_TWO),
    ]
    assert next_node(6, Node.SHOP_TWO) == (6, Node.BOSS)


def test_run_end_rules():
    assert run_won_after_boss(5, ascension=Ascension.NONE, has_faced_uncursed_boss=False)
    assert not run_won_after_boss(4, ascension=Ascension.NONE, has_faced_uncursed_boss=True)
    # Crown 1+: all-cursed run continues to Michael.
    assert not run_won_after_boss(5, ascension=Ascension.CURSED_BOSSES, has_faced_uncursed_boss=False)
    assert run_won_after_boss(5, ascension=Ascension.CURSED_BOSSES, has_faced_uncursed_boss=True)


def test_grids_and_payout():
    assert grids_per_round() == 5
    assert grids_per_round(ascension=7, fewer_grids_modification=1, extra_grids=1) == 4
    p = encounter_payout(3, is_boss=True, money_before=20, ogre_count=1, dragon_count=1)
    assert (p.clear, p.unused_grids, p.boss, p.ogre, p.interest) == (10, 6, 5, 5, 4)
    assert credited_payout(p) == 25


def test_sell_value():
    assert sell_value([9]) == 4
    assert sell_value([9, 9, 10]) == 4 + 2 + 2
    assert sell_value([9, 9], receipt=True) == 18


def test_boss_drafts(catalog):
    for seed in range(50):
        drafts = generate_boss_drafts(random.Random(seed), catalog, Ascension.CURSED_BOSSES)
        assert len(drafts) == 6
        assert drafts[-1].options[0].boss.game_class == "MichaelBoss"
        seen = [c.boss.game_class for d in drafts[:5] for c in d.options]
        assert len(seen) == len(set(seen)) == 10
        for floor, d in enumerate(drafts[:5]):
            assert sum(c.cursed for c in d.options) == 1
            assert all(floor not in c.boss.banned_floor_indexes for c in d.options)
            assert not any(c.boss.is_secret_character for c in d.options)
    crown0 = generate_boss_drafts(random.Random(0), catalog, Ascension.NONE)
    assert not any(c.cursed for d in crown0 for c in d.options)


def test_cursed_boss_is_stronger(catalog):
    wolf = catalog.bosses["MinWordLength"]
    assert wolf.floor_modification(0, cursed=False, harder_bosses=False) == 4
    assert wolf.floor_modification(0, cursed=True, harder_bosses=False) == 5


def _shop(catalog, stage=2, node=Node.SHOP_ZERO, money=50, seed=0, frozen=None):
    inv = Inventory.new_run(catalog, "WetDennis")
    inv.money = money
    return inv, ShopSession(catalog, inv, ShopContext(stage, node), random.Random(seed), frozen)


def test_first_shop_is_common_and_one_pick_free(catalog):
    inv, shop = _shop(catalog, stage=1, node=Node.SHOP_ONE, money=0)
    offers = [o for o in shop.stickers + shop.stamps if o is not None]
    assert offers and all(o.item.rarity == "Common" and o.price(inv) == 0 for o in offers)
    assert shop.buy_item("sticker", 0)
    assert inv.money == 0 and len(inv.stickers) == 1
    assert all(o.price(inv) > 0 for o in shop.stickers + shop.stamps if o is not None)


def test_buying_owned_sticker_upgrades_it(catalog):
    inv, shop = _shop(catalog)
    offer = shop.stickers[0]
    inv.stickers.append(OwnedItem(offer.item, money_invested=[offer.item.cost]))
    assert shop.buy_item("sticker", 0)
    assert len(inv.stickers) == 1 and inv.stickers[0].level == 2


def test_reroll_price_increments_and_freeze_persists(catalog):
    inv, shop = _shop(catalog, money=10)
    kept = shop.stickers[1]
    shop.toggle_freeze("sticker", 1)
    assert shop.reroll_cost == 1
    assert shop.reroll() and inv.money == 9 and shop.reroll_cost == 2
    assert shop.stickers[1] is kept
    # Frozen stock carries into the next shop.
    nxt = ShopSession(catalog, inv, ShopContext(2, Node.SHOP_ONE), random.Random(9), shop.frozen)
    assert nxt.stickers[1] is kept


def test_stamp_duplicates_blocked(catalog):
    inv, shop = _shop(catalog)
    offer = shop.stamps[0]
    assert shop.buy_item("stamp", 0)
    shop.stamps[0] = offer
    assert not shop.can_buy_item("stamp", 0)


def test_sticker_slots_full(catalog):
    inv, shop = _shop(catalog, money=500)
    pool = [i for i in catalog.shop_pool("sticker") if i.game_class not in {o.item.game_class for o in shop.stickers if o}]
    inv.stickers = [OwnedItem(i) for i in pool[:5]]
    assert not shop.can_buy_item("sticker", 0)


def test_loadout_conversion(catalog):
    inv = Inventory.new_run(catalog, "WetDennis")
    inv.pin.side_levels = [2, 1]
    lo = inv.to_loadout()
    assert lo.character == "Rodman"
    assert lo.extras["pin_effect"] == "carp_streamers"
    assert lo.extras["pin_left_level"] == "2" and lo.extras["pin_left_variable"] == "2"


def test_pin_upgrade(catalog):
    inv = Inventory.new_run(catalog, "WetDennis")
    assert inv.pin_upgrade_options() == ["left", "right"]
    inv.upgrade_pin("right")
    assert inv.pin.side_levels == [1, 2] and inv.pin.side_value(1) == 2
    with pytest.raises(ValueError):
        inv.upgrade_pin("both")
    inv.stamps.append(OwnedItem(catalog.items["IDCard"]))
    inv.upgrade_pin("both")
    assert inv.pin.side_levels == [2, 3]


def test_round_preview_shows_only_current_floor(catalog):
    from cursed_words_solver.sim.run_rules import round_preview

    drafts = generate_boss_drafts(random.Random(4), catalog, Ascension.CURSED_BOSSES)
    p = round_preview(2, Ascension.CURSED_BOSSES, drafts)
    assert p.targets == (51, 73, 107)
    assert [b.game_class for b in p.boss_options] == [c.boss.game_class for c in drafts[1].options]
    assert sum(b.cursed for b in p.boss_options) == 1


def test_ogre_curses_floors(catalog):
    from cursed_words_solver.sim.run_rules import on_boss_reward_advance, on_ogre_acquired

    drafts = generate_boss_drafts(random.Random(1), catalog, Ascension.NONE)
    on_ogre_acquired(drafts, 2)
    assert all(c.cursed for c in drafts[1].options)
    on_boss_reward_advance(drafts, 2, holds_ogre=True)
    assert all(c.cursed for c in drafts[2].options)
    on_boss_reward_advance(drafts, 3, holds_ogre=False)
    assert not any(c.cursed for c in drafts[3].options)
