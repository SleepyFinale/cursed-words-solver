"""Rule-level tests for the game-faithful simulator (shop, encounter, bosses)."""

from __future__ import annotations

from cursed_words_solver.sim.game.encounter import Encounter, SubmitResult
from cursed_words_solver.sim.game.items import make_item
from cursed_words_solver.sim.game.player import BossModifier, Node
from cursed_words_solver.sim.game.run import Game, RunConfig
from cursed_words_solver.sim.game.shop import Shop


def _game(**kw) -> Game:
    kw.setdefault("character", "WetDennis")
    kw.setdefault("seed", 7)
    return Game(RunConfig(**kw))


def _clear(game: Game) -> None:
    """Win the current encounter immediately (no word needed)."""
    enc = game.encounter
    enc.remaining_target = 0
    enc._try_next_grid(SubmitResult(0, [], 0, game.player.money, game.player.money))
    game._after_encounter_action()


def _shop_at(game: Game, node: Node, money: int) -> Shop:
    p = game.player
    p.run.node = node
    p.money = money
    game.encounter = None
    game.shop = Shop(p, game.rng)
    return game.shop


# ---------------------------------------------------------------- payouts


def test_clear_payout_is_ten_plus_two_per_unused_grid():
    g = _game()
    g.player.money = 0
    enc = g.encounter
    assert enc.remaining_grids == 4
    _clear(g)
    assert g.player.money == 10 + 4 * 2
    assert g.phase == "shop"


def test_dragon_pays_ten_percent_interest():
    g = _game()
    g.player.stamps[0] = make_item("Dragon")
    g.player.money = 32
    _clear(g)
    # basis = 32 + 18 = 50 → +5
    assert g.player.money == 32 + 18 + 5


# ---------------------------------------------------------------- shop


def test_reroll_price_climbs_and_fried_shrimp_discounts():
    g = _game()
    s = _shop_at(g, Node.SHOP_TWO, 50)
    assert s.reroll_cost == 1
    assert s.reroll()
    assert s.reroll_cost == 2
    assert g.player.money == 49
    g.player.stamps[0] = make_item("FriedShrimp")
    s.reroll_deduction = 1
    assert s.reroll_cost == 1


def test_crown2_rerolls_start_at_two_and_no_free_pick():
    g = _game(ascension=2)
    s = _shop_at(g, Node.SHOP_ONE, 40)
    assert s.reroll_cost == 2
    assert not s.free_item_active
    assert all(o is None or not o.first_discount for o in s.stickers)


def test_frozen_item_carries_to_next_shop():
    g = _game()
    s = _shop_at(g, Node.SHOP_TWO, 50)
    k = next(i for i, o in enumerate(s.stickers) if o is not None)
    cls = s.stickers[k].item.game_class
    assert s.toggle_freeze("sticker", k)
    s2 = _shop_at(g, Node.SHOP_ZERO, 50)
    assert s2.stickers[k] is not None and s2.stickers[k].item.game_class == cls


def test_buying_an_owned_sticker_upgrades_it():
    g = _game()
    s = _shop_at(g, Node.SHOP_TWO, 100)
    k = next(i for i, o in enumerate(s.stickers) if o is not None)
    cls = s.stickers[k].item.game_class
    assert s.buy("sticker", k)
    owned = g.player.stickers[0]
    assert owned.game_class == cls and owned.level(0) == 1
    # Same item offered again: buying upgrades instead of taking a slot.
    from cursed_words_solver.sim.game.shop import ItemInStock

    s.stickers[k] = ItemInStock(make_item(cls), 5)
    assert s.buy("sticker", k)
    assert owned.level(0) == 2 and owned.times_upgraded == 1
    assert sum(1 for x in g.player.stickers if x is not None) == 1


def test_efficient_recycler_restocks_after_a_purchase():
    g = _game()
    g.player.stamps[0] = make_item("EfficientRecycler")
    s = _shop_at(g, Node.SHOP_TWO, 100)
    k = next(i for i, o in enumerate(s.stickers) if o is not None)
    assert s.buy("sticker", k)
    assert s.stickers[k] is not None  # slot refilled
    assert s.reroll_count == 1


def test_sell_returns_half_the_price_paid():
    g = _game()
    it = make_item("Toolbox")
    it.money_invested = [18]
    g.player.add_item(it, g.rng)
    s = _shop_at(g, Node.SHOP_TWO, 0)
    assert s.sell(it) == 9
    assert g.player.money == 9


def test_padlock_costs_money_to_sell():
    g = _game(ascension=4)
    p = g.player
    pad = next(x for x in p.stamps if x is not None and x.game_class == "StampPadlock")
    s = _shop_at(g, Node.SHOP_TWO, 20)
    assert s.sell(pad) == -8
    assert p.money == 12


# ---------------------------------------------------------------- bosses


def test_ogre_curses_current_floor_bosses():
    g = _game(ascension=1)
    p, run = g.player, g.player.run
    assert sum(b.cursed for b in run.boss_drafts[0].options) == 1
    p.add_item(make_item("Ogre"), g.rng)
    assert all(b.cursed for b in run.boss_drafts[0].options)


def test_badger_removes_grids_and_crown7_one_more():
    g = _game(ascension=7)
    p = g.player
    badger = BossModifier("FewerGrids")
    badger.set_floor(0, False)
    p.run.node = Node.BOSS
    p.active_bosses = [badger]
    enc = Encounter(g)
    enc._setup_rest()
    assert enc.total_grids == 5 - badger.floor_mod - 1


def test_diya_adds_a_grid():
    g = _game()
    g.player.stamps[0] = make_item("Diya")
    g.player.run.node = Node.ENCOUNTER_SECOND
    enc = Encounter(g)
    enc._setup_rest()
    assert enc.total_grids == 6


def test_wheel_rerolls_cost_a_dollar_and_grant_three():
    g = _game()
    g.player.stamps[0] = make_item("Wheel")
    g.player.money = 5
    g.player.run.node = Node.ENCOUNTER_SECOND
    enc = Encounter(g)
    enc._setup_rest()
    assert enc.rerolls == 4
    assert enc.reroll()
    assert g.player.money == 4 and enc.rerolls == 3


def test_boss_draft_then_pin_reward_flow():
    g = _game()
    _clear(g)  # EncounterFirst → ShopOne
    g.leave_shop()
    _clear(g)  # EncounterSecond → ShopTwo
    g.leave_shop()
    assert g.phase == "boss_draft"
    g.choose_boss(0)
    assert g.phase == "encounter" and g.encounter.bosses
    _clear(g)
    assert g.phase == "pin_reward"
    pin = g.player.pin
    before = pin.level(0)
    g.upgrade_pin("left")
    assert pin.level(0) == before + 1
    assert g.player.run.stage == 2 and g.phase == "shop"


def test_meg_shop_strips_and_restores_inventory():
    g = _game()
    p = g.player
    it = make_item("Toolbox")
    p.add_item(it, g.rng)
    p.money = 33
    meg = BossModifier("CretaceousMegBoss")
    meg.set_floor(0, False)
    p.run.node = Node.BOSS_DRAFT
    p.active_bosses = [meg]
    g._advance()
    assert g.phase == "shop" and g.shop.is_meg
    assert p.money == 0 and not any(p.stickers)
    g.leave_shop()
    assert g.phase == "encounter"
    _clear(g)
    assert it in p.stickers and p.money >= 33


# ---------------------------------------------------------------- policies / advice


class _NoSearch:
    """Candidates stand-in for policies exercised without a word list."""

    wordlist = None

    def with_budget(self, _budget):
        return self

    def words(self, _game, _n=1):
        return []


def test_advice_policy_shop_actions_are_legal():
    from cursed_words_solver.sim.game.agent import apply
    from cursed_words_solver.sim.game.policy import AdvicePolicy

    g = _game(character="NinaNix", seed=21)
    _clear(g)
    assert g.phase == "shop"
    pol = AdvicePolicy(_NoSearch())
    kinds = []
    for _ in range(20):
        if g.phase != "shop":
            break
        a = pol._advice_shop(g)
        kinds.append(a.kind)
        apply(g, a)
    assert kinds[-1] == "leave" and g.phase == "encounter"
    assert any(k == "buy" for k in kinds)


def test_live_shop_snapshot_round_trips():
    from cursed_words_solver.sim.game.policy import shop_advice_inputs
    from cursed_words_solver.sim.game.shop import Shop

    g = _game(seed=5)
    s = _shop_at(g, Node.SHOP_TWO, 30)
    _, state = shop_advice_inputs(g)
    snap = {
        "restock_cost": s.reroll_price,
        "offers": [
            {"slot": o.slot, "index": o.index, "game_class": next(
                (x.item.game_class for x in (s.stickers + s.stamps) if x is not None and x.item.slug == o.id), ""),
             "price": o.price, "base_price": o.base_price, "foil": o.foil, "frozen": o.frozen,
             "color": o.color, "letter": o.letter}
            for o in state.offers
        ],
    }
    s2 = Shop.from_snapshot(g.player, g.rng, snap)
    got = [o.item.game_class if o else None for o in s2.stickers + s2.stamps]
    want = [o.item.game_class if o else None for o in s.stickers + s.stamps]
    assert got == want


def test_michael_fight_phases_then_finale():
    g = _game(ascension=1, seed=4)
    p, run = g.player, g.player.run
    run.stage, run.node = 6, Node.SHOP_TWO
    g.encounter = None
    g.shop = Shop(p, g.rng)
    g.leave_shop()
    enc = g.encounter
    m = enc.michael
    assert m is not None and m.floor_mod == 3 and enc.michael_draft is not None
    for phase in range(3):
        assert enc.michael_draft is not None and len(enc.michael_draft) == 2
        g.choose_michael_boss(0)
        assert len(enc.bosses) == phase + 1
        enc.remaining_target = 0
        enc._try_next_grid(SubmitResult(0, [], 0, p.money, p.money))
    assert enc.finale and m.summoned_defeated
    from cursed_words_solver.sim.game.agent import Action, apply

    apply(g, Action("finale"))
    assert g.won and g.end_reason == "michael"


def test_all_cursed_crown1_run_continues_past_stage5():
    g = _game(ascension=1, seed=4)
    p, run = g.player, g.player.run
    p.has_faced_uncursed_boss = False
    run.stage, run.node = 5, Node.BOSS
    p.active_bosses = [b for b in run.boss_drafts[4].options if b.cursed][:1]
    enc = Encounter(g)
    g.encounter = enc
    enc._setup_rest()
    assert enc.bosses and enc.bosses[0].cursed
    enc.remaining_target = 0
    enc._try_next_grid(SubmitResult(0, [], 0, p.money, p.money))
    assert enc.won and not enc.run_won
    assert run.cursed_bosses_defeated == [4]
