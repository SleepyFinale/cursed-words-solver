"""Rule-level tests for the game-faithful simulator (shop, encounter, bosses)."""

from __future__ import annotations

import numpy as np

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


def test_northern_cardinal_discounts_any_description_with_red_in_it():
    # GetDescription().Contains("red"): "coloured" and "Scattered" count, as the shop exports show
    g = _game()
    p = g.player
    base = {c: make_item(c).get_cost(p) for c in ("Parrot", "Magnet", "Candle")}
    p.stamps[0] = make_item("NorthernCardinal")
    assert make_item("Parrot").get_cost(p) == base["Parrot"] - 4
    assert make_item("Magnet").get_cost(p) == max(0, base["Magnet"] - 4)
    assert make_item("Candle").get_cost(p) == base["Candle"]


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


def test_losing_to_michael_still_wins_the_run():
    from cursed_words_solver.sim.game.bossrisk import boss_outcomes
    from cursed_words_solver.sim.game.features import MICHAEL_BONUS, outcome

    g = _game(ascension=1, seed=4)
    p, run = g.player, g.player.run
    run.stage, run.node = 6, Node.SHOP_TWO
    g.encounter = None
    g.shop = Shop(p, g.rng)
    g.leave_shop()
    g.choose_michael_boss(0)
    g.encounter.remaining_grids = 0
    g.skip()
    assert g.won and g.end_reason == "michael_lost"  # the crown was beaten at stage 5
    assert outcome(g) == 16.0 < 16.0 + MICHAEL_BONUS
    assert boss_outcomes(g)[-1] == ("MichaelBoss", True)


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


def test_net_policy_picks_from_candidates_and_trains():
    import numpy as np

    from cursed_words_solver.sim.game.agent import apply
    from cursed_words_solver.sim.game.expert import NetPolicy, train
    from cursed_words_solver.sim.game.features import feature_names
    from cursed_words_solver.sim.game.learn import Ridge, load_model

    g = _game(seed=31)
    _clear(g)
    width = len(feature_names())
    model = Ridge(width)
    model.w[:] = 0.01
    pol = NetPolicy(_NoSearch(), model, threshold=0.0)
    cands = pol.candidates(g)
    assert cands[0].kind in ("buy", "leave", "reroll_shop", "sell", "freeze", "move")
    assert any(c.kind == "leave" for c in cands)
    a, seen = pol.decide(g)
    assert a in seen
    apply(g, a)
    # train() recovers a linear advantage from noisy pairs and round-trips through save/load
    rng = np.random.default_rng(0)
    dX = rng.normal(size=(8000, width)).astype(np.float32)
    dy = (dX[:, 0] + rng.normal(scale=2.0, size=8000)).astype(np.float32)
    m, fit = train(dX, dy)
    assert fit["cv_corr"] > 0.2 and fit["switch_gain"] > 0
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        m.threshold = 0.25
        m.save(Path(d) / "m.npz")
        m2 = load_model(Path(d) / "m.npz")
        assert m2.threshold == 0.25 and np.allclose(m2.predict(dX[:5]), m.predict(dX[:5]))


def test_effort_search_is_deterministic():
    from cursed_words_solver.engine.search import ExactSearch
    from cursed_words_solver.sim.game.agent import Candidates

    g = _game(seed=5)
    before = ExactSearch.subset_path_budget
    c = Candidates(effort=0.02)
    a, b = c.words(g, 3), c.words(g, 3)
    assert a and [(o.word, o.score, o.path) for o in a] == [(o.word, o.score, o.path) for o in b]
    assert ExactSearch.subset_path_budget == before  # limits restored after the search
    assert not c.cheap_floor and c.with_effort(0.01).cheap_floor is False  # full floor by default
    cheap = c.with_effort(0.02, cheap_floor=True)
    assert cheap.with_budget(0.3).cheap_floor and cheap.words(g, 3)  # mode kept by probes


def test_boss_risk_counts_and_smoothing(tmp_path):
    from cursed_words_solver.sim.game.bossrisk import BossRisk, boss_outcomes
    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig

    g = _game(seed=11)
    for _ in range(4):  # stage 1: three encounters with shops in between
        if g.phase == "encounter":
            _clear(g)
        elif g.phase == "shop":
            g.leave_shop()
    assert g.phase == "boss_draft"
    table = BossRisk({"SmallGrid": [100, 2], "NegativeMoney": [100, 40]})
    assert table.risk_key("NegativeMoney") > table.risk_key("Unseen") > table.risk_key("SmallGrid")
    path = tmp_path / "risk.json"
    opts = g.boss_options()
    table = BossRisk({f"{b.game_class}{'*' if b.cursed else ''}": [100, 90 - 10 * i] for i, b in enumerate(opts)})
    table.save(path)
    pol = FastAdvicePolicy(_NoSearch(), PowerConfig(boss_risk=str(path)))
    a = pol.act(g)
    uncursed = [i for i, b in enumerate(opts) if not b.cursed]
    assert a.args[0] == max(uncursed)  # lowest risk among uncursed options
    g.choose_boss(a.args[0])
    g._end(False, "test")  # lost at the boss
    g.player.run.node = Node.BOSS
    assert boss_outcomes(g) == [(opts[a.args[0]].game_class, True)]


def test_route_value_takes_a_somewhat_riskier_cursed_boss_while_chasing_michael():
    from types import SimpleNamespace

    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig

    g = _game(seed=11, ascension=2)
    for _ in range(4):
        if g.phase == "encounter":
            _clear(g)
        elif g.phase == "shop":
            g.leave_shop()
    assert g.phase == "boss_draft"
    opts = g.boss_options()
    cursed = next(i for i, b in enumerate(opts) if b.cursed)
    # cursed 0.2 vs uncursed 0.1: outside the 0.05 margin, but staying on the Michael route is
    # worth 0.8 x (1 + 0.5 x 0.5 x 0.8^4) = 0.882 >= 0.9 - 0.05
    table = SimpleNamespace(risk=lambda b, *_: 0.2 if b.cursed else 0.1, mean=lambda cursed=None: 0.2, counts={})
    for route, want in ((False, 1 - cursed), (True, cursed)):
        pol = FastAdvicePolicy(_NoSearch(), PowerConfig(boss_risk="x", route_value=route))
        pol._boss_risk = table
        assert pol._risk_boss(g, opts) == want
    g.player.has_faced_uncursed_boss = True  # off the route: the safer boss
    assert pol._risk_boss(g, opts) == 1 - cursed


def test_ogre_is_bought_only_while_chasing_michael():
    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig, shop_advice_inputs
    from cursed_words_solver.sim.game.shop import ItemInStock

    g = _game(seed=13, ascension=1)
    s = _shop_at(g, Node.SHOP_ONE, 30)
    s.stamps[0] = ItemInStock(make_item("Ogre"), 12)
    pol = FastAdvicePolicy(_NoSearch(), PowerConfig(ogre=True))
    a = pol._ogre_buy(g)
    assert (a.kind, a.args) == ("buy", ("stamp", 0))
    assert all(o.name != "Ogre" for o in shop_advice_inputs(g, frozenset({"Ogre"}))[1].offers)
    assert not pol._offer_ok(g, "Ogre") and pol._offer_ok(g, "Dragon")
    g.player.has_faced_uncursed_boss = True
    assert pol._ogre_buy(g) is None
    g.player.has_faced_uncursed_boss = False
    run = g.player.run
    run.stage = 4
    for b in run.boss_drafts[3].options:
        b.make_cursed()
    assert pol._ogre_buy(g) is None  # stage 4's draft is already all cursed
    assert g.buy("stamp", 0)
    a = pol._ogre_buy(g)  # held into stage 4: sell it so the stage-5 draft stays a choice
    assert (a.kind, a.args[0], g.player.stamps[a.args[1]].game_class) == ("sell", "stamp", "Ogre")
    run.stage = 5
    g.player.stamps[a.args[1]] = None
    assert pol._ogre_buy(g) is None


def test_boss_model_learns_that_stronger_builds_clear_and_round_trips(tmp_path):
    from cursed_words_solver.sim.game.bossmodel import BossModel, features

    rng = np.random.default_rng(0)
    X, y = [], []
    for _ in range(600):
        st, r = float(np.exp(rng.normal(0, 0.6))), float(rng.uniform(0.05, 0.4))
        X.append(features(st, r, bool(rng.integers(2)), int(rng.integers(1, 6)), int(rng.integers(0, 8))))
        y.append(float(rng.random() < 1 / (1 + np.exp(-4 * np.log(st)))))  # clears when strength > 1
    m = BossModel.fit(np.array(X), np.array(y))
    assert m.risk(2.0, 0.2, False, 3, 1) < 0.2 < 0.8 < m.risk(0.5, 0.2, False, 3, 1)
    m.save(tmp_path / "bm.json")
    assert BossModel.load(tmp_path / "bm.json").risk(1.3, 0.1, True, 4, 2) == m.risk(1.3, 0.1, True, 4, 2)


def test_boss_model_replaces_table_risk_in_the_draft():
    from types import SimpleNamespace

    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig

    g = _game(seed=11)
    for _ in range(4):
        if g.phase == "encounter":
            _clear(g)
        elif g.phase == "shop":
            g.leave_shop()
    opts = g.boss_options()
    table = SimpleNamespace(risk=lambda b, *_: 0.1 if b is opts[0] else 0.3, mean=lambda cursed=None: 0.2, counts={})
    pol = FastAdvicePolicy(_NoSearch(), PowerConfig(boss_risk="x"))
    pol._boss_risk = table
    assert pol._risk_boss(g, opts) == 0  # the table alone: the first option is safer
    pol = FastAdvicePolicy(_NoSearch(), PowerConfig(boss_risk="x", boss_model="m"))
    pol._boss_risk = table
    pol._boss_model = SimpleNamespace(risk=lambda st, *_: 1 / (1 + st))  # stronger build vs it = safer
    pol.boss_strength = lambda game, b: 0.5 if b is opts[0] else 3.0
    assert pol._risk_boss(g, opts) == 1


def test_item_growth_learns_which_items_grow_and_round_trips(tmp_path):
    import json

    import pytest
    from cursed_words_solver.sim.game.buildvalue import ItemGrowth, rows

    runs = []
    for k in range(30):  # Grower doubles its contribution each stage, Fader halves it
        items = []
        for cls, f in (("Grower", 2.0), ("Fader", 0.5)):
            c0 = 0.2 + 0.01 * k
            items.append({"cls": cls, "contrib": [[s, "SHOP_TWO", c0 * f ** (s - 1), 1, 0, 100] for s in range(1, 6)]})
        runs.append({"items": items})
    log = tmp_path / "c.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in runs))
    data = rows([log])
    assert len(data) == 30 * 2 * 10  # every ordered pair of stages, per item
    m = ItemGrowth.fit(data, lam=1.0)
    assert m.value("Grower", 0.3, 1) > 0.3 > m.value("Fader", 0.3, 1)
    assert m.value("Grower", 0.3, 5) == pytest.approx(0.3) == m.value("Fader", 0.3, 5)  # last stage: measured only
    m.save(tmp_path / "bv.json")
    assert ItemGrowth.load(tmp_path / "bv.json").value("Grower", 0.3, 2) == m.value("Grower", 0.3, 2)


def test_build_value_turns_a_probe_gain_into_its_long_horizon_value():
    from types import SimpleNamespace

    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig

    g = _game()
    off = FastAdvicePolicy(_NoSearch(), PowerConfig())
    assert off._horizon(g, "Grower", 0.25) == 0.25
    on = FastAdvicePolicy(_NoSearch(), PowerConfig(build_value="bv"))
    on._growth = SimpleNamespace(value=lambda cls, c, stage, weights=None: c * (4 if cls == "Grower" else 0.5))
    assert on._horizon(g, "Grower", 0.25) == 1.0 and on._horizon(g, "Fader", 0.25) == 0.125
    assert on._horizon(g, None, 0.25) == 0.25


def test_survival_weights_put_the_horizon_where_fights_can_be_lost():
    import math

    import pytest

    from cursed_words_solver.sim.game.buildvalue import ItemGrowth, stage_weights
    from cursed_words_solver.sim.game.player import Node

    target = lambda t, n: 100 * 3.8 ** (t - 1) * (1 + 0.1 * int(n == Node.BOSS))
    weak = stage_weights(0.8, 2, Node.ENCOUNTER_SECOND, target)
    strong = stage_weights(6.0, 2, Node.ENCOUNTER_SECOND, target)
    assert sorted(weak) == [2, 3, 4, 5] and weak[2] > 0.5 > strong[2]
    assert all(strong[t] <= weak[t] for t in weak)
    assert strong[5] > strong[2]  # targets outgrow the build: late fights are the risky ones
    # grows x2 per stage from a 0.0 log contribution
    m = ItemGrowth(["Grower"], [1.0, 0.0, 0.0, 0.0, 0.0, math.log(2)], 1.0)
    assert m.value("Grower", 0.0, 3) == pytest.approx(1.0)  # uniform: mean of 0, 1, 2 stages of growth
    assert m.value("Grower", 0.0, 3, {3: 1.0, 4: 0.0, 5: 0.0}) == pytest.approx(0.0, abs=1e-9)  # only now counts
    assert m.value("Grower", 0.0, 3, {5: 1.0}) == pytest.approx(3.0, rel=1e-3)
    assert m.value("Grower", 0.0, 3, {}) == m.value("Grower", 0.0, 3)  # no risk anywhere: uniform


def test_item_value_baselines_and_shrinkage(tmp_path):
    import json

    from cursed_words_solver.sim.game.itemvalue import PRIOR_WEIGHT, ItemValue, read_runs

    runs = [  # both runs reached a stage-2 shop (baseline 12); only the winner bought Gem
        {"character": "A", "outcome": 16.0, "shops": [[1, "SHOP_ONE"], [2, "SHOP_ONE"]], "buys": [[2, "SHOP_ONE", "Gem"]]},
        {"character": "A", "outcome": 8.0, "shops": [[1, "SHOP_ONE"], [2, "SHOP_TWO"]], "buys": [[1, "SHOP_ONE", "Rock"]]},
        {"character": "A", "outcome": 0.0, "error": "boom", "shops": [[1, "SHOP_ONE"]], "buys": [[1, "SHOP_ONE", "Rock"]]},
    ]
    log = tmp_path / "runs.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in runs) + "\n{cut short")
    kept = read_runs(log)
    assert len(kept) == 2  # crashed and truncated lines skipped
    t = ItemValue.build(kept)
    assert t.sums["Gem"] == [1, 4.0] and t.sums["Rock"] == [1, -4.0]  # vs stage baselines 12 / 12
    assert t.value("Gem") == 4.0 / (1 + PRIOR_WEIGHT) > 0 > t.value("Rock")
    assert t.value("Gem", 2, "A") == t.value("Gem")  # the same purchase is not counted twice
    assert t.value("Unseen", 3, "B") == 0.0
    t.save(tmp_path / "iv.json")
    assert ItemValue.load(tmp_path / "iv.json").sums == t.sums
    kept[1]["buys"].append([1, "SHOP_ONE", "Gem"])  # the loser bought Gem too, at stage 1
    t = ItemValue.build(kept)
    assert t.value("Gem") == 0.0 and t.value("Gem", 2) > 0 > t.value("Gem", 1)


def test_boss_risk_reads_the_run_log_once(tmp_path):
    import json

    from cursed_words_solver.sim.game.bossrisk import BossRisk

    log = tmp_path / "runs.jsonl"
    run = {"character": "A", "crown": 2, "bosses": [["SmallGrid", False], ["ExtraQs*", True]]}
    log.write_text(json.dumps(run) + "\n" + json.dumps({**run, "error": "boom"}) + "\n")
    t = BossRisk()
    assert t.add_log(log) == 1
    assert t.counts["ExtraQs*@c2#A"] == [1, 1] and t.counts["SmallGrid"] == [1, 0]
    assert t.add_log(log) == 0  # already counted
    with log.open("a") as f:
        f.write(json.dumps(run) + "\n")
    t.save(tmp_path / "br.json")
    t = BossRisk.load(tmp_path / "br.json")
    assert t.add_log(log) == 1 and t.counts["SmallGrid"] == [2, 0]


def test_pin_model_learns_the_side_from_the_situation_and_the_offers(tmp_path):
    import json

    from cursed_words_solver.sim.game import pinplan

    # A wants "right" when feature 0 (say, money) is high and "left" when it is low.
    # N (a random pin) wants whichever side offers item 2 (dx[2] = +1: right offers it).
    rows = []
    for seed in range(60):
        rich = seed % 2 == 0
        a_gain = 1.0 if rich else -1.0
        rows.append({"character": "A", "crown": 0, "seed": seed, "pin_log": [
            {"horizon": 1, "x": {"0": 1.0 if rich else 0.0, "3": 1.0}, "dx": {},
             "outcomes": {"left": [10.0], "right": [10.0 + a_gain]}}]})
        offer = 1.0 if seed % 3 else -1.0
        rows.append({"character": "N", "crown": 0, "seed": seed, "pin_log": [
            {"horizon": 1, "x": {"0": 1.0 if rich else 0.0}, "dx": {"2": offer},
             "outcomes": {"left": [12.0], "right": [12.0 + 2 * offer]}}]})
    rows.append({"character": "C", "crown": 0, "seed": 0, "pin_log": []})
    log = tmp_path / "runs.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    decisions = pinplan.load_decisions(log)
    assert len(decisions) == 120
    model = pinplan.train(decisions, width=4)
    assert model.info["cv"][model.info["lam"]]["agree"] > 0.9
    pinplan.save(model, tmp_path / "pin.pkl")
    x, dx = np.zeros(4), np.zeros(4)
    x[3] = 1.0
    assert pinplan.choose("A", x, dx, tmp_path / "pin.pkl") == "left"
    x[0] = 1.0
    assert pinplan.choose("A", x, dx, tmp_path / "pin.pkl") == "right"
    dx[2] = 1.0
    assert pinplan.choose("N", x, dx, tmp_path / "pin.pkl") == "right"
    dx[2] = -1.0
    assert pinplan.choose("N", x, dx, tmp_path / "pin.pkl") == "left"
    assert pinplan.choose("C", x, dx, tmp_path / "pin.pkl") is None  # no data: caller keeps its rule


def _full_shop():
    """Shop with every sticker slot full and an unowned sticker offer that fits only after a sale."""
    from cursed_words_solver.sim.game.shop import ItemInStock

    g = _game(seed=31)
    s = _shop_at(g, Node.SHOP_TWO, 40)
    p = g.player
    for k, cls in enumerate(("Candle", "GamePad", "Backpack", "Ruler", "Zebra")):
        p.stickers[k] = make_item(cls)
    s.stickers[0] = ItemInStock(make_item("Parrot"), 12)
    return g, s


def test_full_shop_candidates_cover_every_kind_of_move_within_the_cap():
    from cursed_words_solver.sim.game.agent import Action, apply
    from cursed_words_solver.sim.game.expert import SHOP_CANDIDATES, afterstate, full_shop_candidates, shop_candidates

    g, s = _full_shop()
    cands = full_shop_candidates(g, Action("leave"))
    kinds = {c.kind for c in cands}
    assert {"leave", "reroll_shop", "sell_buy", "freeze", "sell", "move"} <= kinds
    assert len(cands) <= SHOP_CANDIDATES and len({(c.kind, c.args) for c in cands}) == len(cands)
    assert not {"sell_buy", "sell", "move"} & {c.kind for c in shop_candidates(g, Action("leave"))}
    swap = next(c for c in cands if c.kind == "sell_buy" and c.args[2] == 0)
    assert all(afterstate(g, c) is not None for c in cands if c.kind != "sell_buy")
    sold = g.player.stickers[swap.args[1]].game_class
    assert apply(g, swap) is not False
    owned = {i.game_class for i in g.player.stickers_list()}
    assert "Parrot" in owned and sold not in owned


def test_training_alternatives_are_drawn_group_first():
    import collections
    import random

    from cursed_words_solver.sim.game.agent import Action
    from cursed_words_solver.sim.game.expert import sample_alternative

    cands = [Action("leave")] + [Action("move", ("sticker", i, i + 1)) for i in range(10)] + [Action("buy", ("sticker", 0))]
    rng = random.Random(0)
    n = collections.Counter(sample_alternative(rng, cands).kind for _ in range(2000))
    assert 800 < n["buy"] < 1200  # half the draws, though it is 1 move in 11


def test_v4_features_see_order_growth_crown_route_and_shared_descriptors():
    from cursed_words_solver.sim.game.agent import Action, apply
    from cursed_words_solver.sim.game.features import encode, feature_names, item_descriptors
    from cursed_words_solver.sim.game.learn import Ridge

    names = feature_names()
    col = {n: i for i, n in enumerate(names)}
    g, s = _full_shop()
    g.player.run.ascension = 3
    g.player.has_faced_uncursed_boss = False  # set when crown 0 drafted its uncursed bosses
    x = encode(g)
    assert x[col["crown:3"]] == 1 and x[col["michael_route"]] == 1 and x[col["free_sticker_slots"]] == 0
    assert x[col["pos:Candle"]] == 0.2 and x[col["pos:Zebra"]] == 1.0
    apply(g, Action("move", ("sticker", 0, 4)))
    y = encode(g)
    assert y[col["pos:Candle"]] == 1.0 and y[col["pos:Zebra"]] == 0.2  # reorders are visible
    rows, D = item_descriptors()
    desc = [col[n] for n in names if n.startswith("desc:")]
    want = sum(D[rows[c]] for c in ("Candle", "GamePad", "Backpack", "Ruler", "Zebra"))
    assert np.allclose(y[desc], want)
    before = y[col["ivar:Candle"]]
    g.player.stickers[4].upgrade()
    assert encode(g)[col["ivar:Candle"]] > before  # component value (growth) is visible
    g.player.has_faced_uncursed_boss = True
    assert encode(g)[col["michael_route"]] == 0
    old = Ridge(1035)  # a model saved before v4 reads the prefix it was fitted on
    old.w[:] = 1.0
    assert np.isclose(old.predict(y)[0], old.predict(y[:1035])[0])


class _FixedWords(_NoSearch):
    """Candidates stand-in whose best word scores ``score``."""

    def __init__(self, score):
        self.score = score

    def words(self, _game, _n=1):
        from cursed_words_solver.sim.game.agent import WordOption

        return [WordOption("cat", ["cat"], [(0, 0), (1, 0), (2, 0)], self.score)]


def test_finish_early_rerolls_for_a_clearing_word_and_never_submits_a_losing_last_word():
    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig

    def kind(score, grids_after, finish_early):
        g = _game(seed=41)
        enc = g.encounter
        enc.remaining_target, enc.remaining_grids, enc.rerolls = 100, grids_after, 1
        g.player.consumables = [None] * len(g.player.consumables)
        return FastAdvicePolicy(_FixedWords(score), PowerConfig(finish_early=finish_early)).act(g).kind

    assert kind(60, 0, 0.0) == "submit"  # last grid, 60 of 100: the old rule plays it and loses
    assert kind(60, 0, 0.75) == "reroll_grid"
    assert kind(60, 2, 0.75) == "submit"  # 3 grids left and far from clearing: keep playing
    assert kind(80, 2, 0.75) == "reroll_grid"  # close: hunt for a word that clears now
    assert kind(120, 0, 0.75) == "submit"  # it clears


def test_bench_sequential_test_stops_on_a_real_gain_a_loss_or_no_effect():
    import random

    from cursed_words_solver.sim.game.bench import sequential

    def blocks(mean, n=60, sd=2.5, seed=1):
        rng = random.Random(seed)
        return [[rng.gauss(mean, sd) for _ in range(88)] for _ in range(n)]

    good, bad = sequential(blocks(0.6)), sequential(blocks(-0.6))
    assert good["decision"] == "accept" and good["llr"] >= 2.77 and good["blocks"] < 10
    assert bad["decision"] == "reject" and bad["llr"] <= -1.56 and bad["blocks"] < 10
    assert sequential(blocks(0.0))["decision"] in ("reject", "cap", "continue")
    assert sequential([[0.0] * 88])["decision"] == "reject"  # the change never affected a run
    assert sequential([])["decision"] == "continue"
    # no bound crossed and the runs of a fixed-sample test passed: undecided, not accepted
    assert sequential([[0.1, -0.1] * 44] * 2, delta=0.2)["decision"] != "accept"
    # false positives near the design's 5%
    trials = [sequential(blocks(0.0, 25, seed=i))["decision"] for i in range(200)]
    assert trials.count("accept") / len(trials) < 0.12


def test_bench_gate_figures_and_seed_rules(tmp_path):
    import json

    import pytest

    from cursed_words_solver.sim.game import bench

    assert bench.shrunk(0.152, 0.078) == pytest.approx(0.1198, abs=0.001)
    rc = bench.rate_change([True] * 62 + [False] * 62 + [True] * 100, [False] * 62 + [True] * 62 + [True] * 100)
    assert rc["change"] == 0 and rc["se"] > 0 and rc["lower"] < 0
    lo, hi = bench.bootstrap_interval({("a", 0): [1.0, 1.0], ("b", 0): [1.0]})
    assert lo == hi == 1.0

    # promotion blocks never overlap each other or the older seeds
    every = [set(s for _, _, s in bench.seeds(100, first=f)) for f in
             (bench.FIRST_SEED, bench.SEARCH_SEED, bench.block_first_seed(0), bench.block_first_seed(1))]
    assert sum(map(len, every)) == len(set().union(*every))

    def row(ch, cr, sd, out, won=False):
        return {"char": ch, "crown": cr, "seed": sd, "won": won, "reason": "x", "outcome": out, "stage": 5}

    ss = bench.seeds(4)
    base = {k: row(*k, 10.0) for k in ss}
    arm = {k: row(*k, 10.0 + (1.2 if k[1] % 2 else 0.6)) for k in ss}
    rep = bench.gate_report(base, arm, single_use=True, searched=3)
    assert rep["decision"] == "accept" and rep["promote"] and rep["searched"] == 3
    assert rep["blocks"] == 1 and rep["n"] == 4 * 88 and 0 < rep["shrunk"] < rep["gain"]  # all blocks count in the figures
    assert not bench.gate_report(base, arm, single_use=False)["promote"]  # search seeds cannot promote
    losing = {k: row(*k, 11.0, won=False) for k in ss}
    winning = {k: row(*k, 10.0, won=True) for k in ss}
    assert not bench.gate_report(winning, losing, single_use=True)["promote"]  # higher mean, fewer wins
    # a block with a run missing does not count yet
    assert bench.gate_report(base, {k: v for k, v in arm.items() if k != ss[0]})["n"] == 0

    bench.claim_block(3, "base", "a", tmp_path)
    bench.claim_block(3, "base", "a", tmp_path)  # resuming the same candidate is fine
    with pytest.raises(SystemExit):
        bench.claim_block(3, "base", "b", tmp_path)
    with pytest.raises(SystemExit):
        bench.same_stream(bench.spec(keyed=True), bench.spec())
    bench.same_stream(bench.spec(keyed=True), bench.spec(keyed=True, salt=1))

    # an arm made before the keyed setting existed still resumes, and is not keyed
    old = bench.spec({"late_swaps": 3})
    del old["keyed"], old["salt"]
    (tmp_path / "a.json").write_text(json.dumps({"spec": old}))
    assert bench._spec_settings(old) == bench._spec_settings(bench.spec({"late_swaps": 3}))
    with pytest.raises(SystemExit):
        bench.run("a", bench.spec({"late_swaps": 3}, keyed=True), out_dir=tmp_path)


def test_bench_keyed_stream_follows_the_point_of_the_run_not_what_came_before():
    from cursed_words_solver.sim.game.bench import reseed_for

    a, b = _game(seed=41), _game(seed=41)
    b.rng.range(0, 10)  # this run has drawn more by now
    seen_a, seen_b = {}, {}
    reseed_for(a, 41, 0, seen_a, "leave")
    reseed_for(b, 41, 0, seen_b, "leave")
    assert a.rng.range(0, 10 ** 9) == b.rng.range(0, 10 ** 9)
    reseed_for(a, 41, 0, seen_a, "leave")  # the same action again at the same point is a new draw
    first = a.rng.range(0, 10 ** 9)
    c = _game(seed=41)
    reseed_for(c, 41, 0, {}, "leave")
    assert c.rng.range(0, 10 ** 9) != first
    d = _game(seed=41)
    reseed_for(d, 41, 1, {}, "leave")  # a salt is another game
    e = _game(seed=41)
    reseed_for(e, 41, 0, {}, "leave")
    assert d.rng.range(0, 10 ** 9) != e.rng.range(0, 10 ** 9)


def test_plan_class_sorts_items_by_a_build_plan():
    import pytest

    from cursed_words_solver.sim.game.items import catalog_rows
    from cursed_words_solver.sim.game.policy import plan_class

    assert plan_class("Curse", "Amphora") == "generator"
    assert plan_class("Curse", "Broom") == "fits"
    assert plan_class("Red", "Broom") == "off"
    assert plan_class("Red", "Avocado") == "neutral"  # no build tag
    generic = next(k for k, r in catalog_rows().items() if {"GenericMultiplier", "GenericAdditive"} & set(r["function_tags"])
                   and any(t.endswith("Build") and t != "RedBuild" for t in r["tags"]) and "RedBuild" not in r["tags"]
                   and "RedGenerator" not in r["dependency_tags"])
    assert plan_class("Red", generic) == "neutral"  # generic points help any build
    with pytest.raises(KeyError):
        plan_class("NoSuchPlan", "Broom")


def _plan_shop(plan: str, money: int = 60, **cfg):
    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig

    g = _game(seed=31)
    s = _shop_at(g, Node.SHOP_ONE, money)
    s.stickers[:] = [None] * len(s.stickers)
    s.stamps[:] = [None] * len(s.stamps)
    return g, s, FastAdvicePolicy(_NoSearch(), PowerConfig(build_plan=plan, **cfg))


def test_build_plan_buys_its_generators_first_and_refuses_other_builds():
    from cursed_words_solver.sim.game.shop import ItemInStock

    g, s, pol = _plan_shop("Curse")
    s.stickers[0] = ItemInStock(make_item("Broom"), 12)
    s.stickers[1] = ItemInStock(make_item("Amphora"), 13)
    a = pol._advice_shop(g)
    assert (a.kind, a.args) == ("buy", ("sticker", 1)) and "Amphora" in a.label
    assert not pol._offer_ok(g, "Beefeater") and pol._offer_ok(g, "Broom") and pol._offer_ok(g, "Avocado")
    _, _, off = _plan_shop("")
    assert off._build_plan_step(g) is None and off._offer_ok(g, "Beefeater")


def test_generator_reserve_keeps_money_for_a_generator_and_holds_one_it_cannot_buy():
    from cursed_words_solver.sim.game.agent import apply
    from cursed_words_solver.sim.game.shop import ItemInStock

    def shop(**cfg):
        g, s, pol = _plan_shop("Curse", money=20, **cfg)
        s.stickers[0] = ItemInStock(make_item("Broom"), 12)  # payoff item
        s.stickers[1] = ItemInStock(make_item("Amphora"), 25)  # generator, not affordable yet
        return g, pol

    g, pol = shop()
    assert "Broom" in pol._advice_shop(g).label  # no reserve: the payoff item is bought
    g, pol = shop(build_plan_gen_reserve=15)
    a = pol._advice_shop(g)
    assert (a.kind, a.args) == ("freeze", ("sticker", 1))  # hold the generator for later
    apply(g, a)
    a = pol._advice_shop(g)
    assert a.kind == "reroll_shop" and a.label.startswith("plan")  # and look for another, not Broom
    g.player.stickers[0] = make_item("CursedVHS")  # owning a generator lifts the reserve
    assert pol._gen_reserve(g) == 0


def test_build_plan_replaces_a_non_plan_item_when_slots_are_full_and_keeps_its_own():
    from cursed_words_solver.sim.game.shop import ItemInStock, can_sell

    g, s, pol = _plan_shop("Curse")
    p = g.player
    names = ["Amphora", "Avocado", "Chips", "Dartboard", "Eraser", "Egg", "Chick", "Axe"]
    p.stickers[:] = [make_item(n) for n in names[:len(p.stickers)]]
    p.stickers[1].sell_cost = 1  # any non-plan item may go, but never the plan's generator
    assert can_sell(p, p.stickers[0])
    s.stickers[0] = ItemInStock(make_item("Broom"), 12)
    a = pol._advice_shop(g)
    assert a.kind == "sell" and a.args[0] == "sticker" and a.args[1] != 0
    assert pol._pending_buy == ("sticker", 0) and pol._sold_this_shop
    assert g.sell(*a.args) is not None
    bought = pol._advice_shop(g)
    assert (bought.kind, bought.args) == ("buy", ("sticker", 0))


def test_build_plan_restocks_for_an_offer_up_to_its_limit_and_reserve():
    g, s, pol = _plan_shop("Curse", build_plan_restocks=2)
    assert pol._build_plan_step(g).kind == "reroll_shop"
    assert pol._build_plan_step(g).kind == "reroll_shop"
    assert pol._build_plan_step(g) is None
    pol._leave()
    assert pol._build_plan_step(g).kind == "reroll_shop"  # a new shop, new restocks
    pol._leave()
    g.player.money = s.reroll_cost + pol.cfg.build_plan_reserve - 1
    assert pol._build_plan_step(g) is None


def test_plantest_pairs_every_plan_with_the_rules_player_on_the_same_runs(tmp_path):
    import json

    from cursed_words_solver.sim.game import plantest as T

    jobs = T.make_jobs([T.BASE, "Cards"], ["Spike", "SockHead"], 0, 16)
    assert len(jobs) == 2 * 2 * 16 and len({(j["plan"], j["seed"]) for j in jobs}) == len(jobs)
    assert sorted(j["crown"] for j in jobs if j["plan"] == "Cards" and j["character"] == "Spike") == sorted(list(range(8)) * 2)
    assert next(j for j in jobs if j["plan"] == "Cards")["cfg"] == {"build_plan": "Cards", "build_plan_chars": {}}
    assert next(j for j in jobs if j["plan"] == T.BASE)["cfg"] == {"build_plan": ""}  # the rules player, not the default plan
    more = T.make_jobs([T.BASE], ["Spike"], 16, 4)
    assert not {j["seed"] for j in more} & {j["seed"] for j in jobs}

    path = tmp_path / "runs.jsonl"
    rows = [{"plan": j["plan"], "character": j["character"], "crown": j["crown"], "seed": j["seed"], "error": None, "stage": 5,
             "outcome": 10.0 + (j["plan"] == "Cards") * (1 + (j["seed"] % 2) / 10), "won": j["plan"] == "Cards" and j["crown"] == 0}
            for j in jobs]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n{cut short", encoding="utf-8")
    runs = T.load_runs(path)
    assert len(runs) == len(jobs)
    g = T.gains(runs, "Cards")
    assert g["n"] == 32 and abs(g["gain"] - 1.05) < 1e-9 and g["t"] > 10 and (g["wins"], g["base_wins"]) == (4, 0)
    assert T.gains(runs, "Cards", lambda r: r["crown"] == 0)["n"] == 4
    text = "\n".join(T.report(runs))
    assert "Cards" in text and "Spike" in text and "SockHead" in text


def test_late_swaps_raise_the_swap_limit_from_the_given_stage():
    from cursed_words_solver.sim.game.policy import AdvicePolicy, PowerConfig

    def limit(stage, late, final=False):
        g = _game(seed=31)
        g.player.run.stage = stage
        return AdvicePolicy(_NoSearch(), PowerConfig(late_swaps=late))._swap_limit(g, final)

    assert limit(4, 0) == 1 and limit(3, 3) == 1 and limit(4, 3) == 3 and limit(5, 2) == 2
    assert limit(5, 0, final=True) == 3


def test_bench_seeds_report_and_settings_guard(tmp_path):
    import json

    import pytest

    from cursed_words_solver.sim.game import bench

    ss = bench.seeds()
    assert len(ss) == 528 and len(set(ss)) == 528
    assert ("Spike", 3, 8_000_000 + 1000 * bench.CHARS.index("Spike") + 300 + 5) in ss

    def row(ch, cr, sd, out, reason="out_of_grids"):
        return {"char": ch, "crown": cr, "seed": sd, "won": out >= 16, "reason": reason, "outcome": out, "stage": 5}

    base = {(c, r, s): row(c, r, s, 10.0) for c, r, s in ss}
    arm = {k: row(*k, 10.0 + (1.0 if k[1] < 4 else 0.0)) for k in base}
    arm[ss[0]] = row(*ss[0], 24.0, "michael")
    rep = bench.compare(base, arm)
    assert rep["all"]["n"] == 528 and rep["crown 0"]["mean"] > 1 and rep["crown 7"]["mean"] == 0
    assert rep["all"]["michael_beaten"] == (0, 1) and rep["all"]["wins"] == (0, 1)
    assert rep["first half"]["n"] == rep["second half"]["n"] == 264
    # results files skip a line cut short; another arm under the same name is refused
    path = tmp_path / "a.jsonl"
    path.write_text(json.dumps(row(*ss[0], 3.0)) + "\n" + '{"char": "Sp')
    assert list(bench.load(path)) == [ss[0]]
    (tmp_path / "a.json").write_text(json.dumps({"spec": bench.spec({"late_swaps": 3})}))
    with pytest.raises(SystemExit):
        bench.run("a", bench.spec({"finish_early": 0.75}), out_dir=tmp_path)
    assert len(bench.code_fingerprint()) == 10


def test_training_resumes_benchmarks_data_and_refuses_other_settings(tmp_path):
    import json

    import pytest

    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.learn import Ridge

    # a benchmark whose runs are all cached plays nothing (no worker pool) and keeps job order
    jobs = [{"character": "WetDennis", "crown": 0, "seed": s} for s in (5, 3)]
    cache = tmp_path / "evals" / "eval_base.jsonl"
    cache.parent.mkdir()
    cache.write_text("".join(json.dumps({"seed": s, "won": s == 3, "outcome": float(s), "error": None}) + "\n" for s in (3, 5)))
    res = E.evaluate(jobs, workers=1, wordlist=None, model=None, run_log=None, cache=cache)
    assert res["per_seed"] == [5.0, 3.0] and res["wins"] == 1
    # a finished data file is reused, not collected again
    out = tmp_path / "pairs_it000.npz"
    np.savez(out, dX=np.zeros((2, 3), np.float32), dy=np.ones(2, np.float32), kind=np.array(["shop", "shop"]),
             seeds=np.array([1, 2]), wins=np.array([1]))
    assert E.collect([], workers=1, wordlist=None, model=None, out=out) == {"runs": 2, "wins": 1, "pairs": 2}
    # a model is named by its arrays, not the file's write time
    m = Ridge(4)
    m.w[:] = 0.5
    m.save(tmp_path / "m1.npz")
    m.save(tmp_path / "m2.npz")
    assert E.model_tag(str(tmp_path / "m1.npz")) == E.model_tag(str(tmp_path / "m2.npz")) != "base"
    # a directory started with other characters / crowns is refused before anything runs
    (tmp_path / "config.json").write_text(json.dumps({"characters": ["Spike"], "crowns": [0]}))
    with pytest.raises(SystemExit):
        E.main(["--dir", str(tmp_path), "--characters", "WetDennis", "--boss-risk", ""])


def test_lambda_returns_follow_the_visit_inside_a_shop_and_bootstrap_between_visits():
    import numpy as np

    from cursed_words_solver.sim.game.expert import lambda_returns

    run = np.array([1, 1, 1, 1, 2, 2])
    visit = np.array([10, 10, 20, 30, 10, 20])
    value = np.array([0.0, 0.0, 4.0, 8.0, 0.0, 3.0])
    final = np.array([10.0, 10.0, 10.0, 10.0, 2.0, 2.0])
    y = lambda_returns(value, run, visit, final, 0.5)
    # run 1: last state -> outcome 10; state 2 -> .5*8 + .5*10 = 9; states 0, 1 share the visit
    # with state 1 -> .5*4 + .5*9 = 6.5, and state 0 copies state 1
    assert np.allclose(y, [6.5, 6.5, 9.0, 10.0, 2.5, 2.0])
    assert np.allclose(lambda_returns(value, run, visit, final, 1.0), final)  # λ = 1: Monte Carlo


def test_value_fit_matches_closed_form_ridge_and_finds_build_signal():
    import numpy as np

    from cursed_words_solver.sim.game.expert import _FoldGram, train_value
    from cursed_words_solver.sim.game.learn import Ridge

    rng = np.random.default_rng(0)
    n, w = 3000, 12
    X = rng.normal(size=(n, w)).astype(np.float32)
    X[:, 5] = 0.0  # a dead column
    y = X[:, 0] * 2 + rng.normal(size=n)
    g = _FoldGram(X, rng.integers(0, 5, n), 5, chunk=700)
    m = g.ridge(g.solve(10.0, g.h(y)), 10.0)
    ref = Ridge(w, 10.0).fit(X, y)
    assert np.allclose(m.predict(X), ref.predict(X), atol=1e-6)
    # 400 runs of 6 states over 3 visits; every state of a run shares its outcome, which a
    # hidden build strength drives and column 0 measures noisily at each state
    runs = np.repeat(np.arange(400), 6)
    visit = np.tile([1, 1, 2, 2, 3, 3], 400).astype(np.int16)
    strength = np.repeat(rng.normal(size=400), 6)
    Xs = rng.normal(size=(len(runs), w)).astype(np.float32)
    Xs[:, 0] = strength + rng.normal(scale=0.5, size=len(runs))
    final = 2 * strength + np.repeat(rng.normal(size=400), 6)
    data = {"X": Xs, "run": runs, "visit": visit, "outcome": final.astype(np.float32),
            "crown": np.zeros(len(runs), np.int8), "explored": np.zeros(len(runs), bool)}
    model, fit = train_value(data, lam=0.8, sweeps=3)
    _, mc = train_value(data, sweeps=1)
    assert fit["r2_within"] > 0.4 and fit["runs"] == 400 and model.target == "value"
    assert model.w[0] / model.sd[0] > 1 and fit["pairs_corr"] is None
    assert abs(fit["r2_within"] - mc["r2_within"]) < 0.1


def test_learning_curve_reads_stored_states_without_playing(tmp_path):
    import numpy as np

    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.features import feature_names

    rng = np.random.default_rng(1)
    runs = np.repeat(np.arange(200), 4)
    strength = np.repeat(rng.normal(size=200), 4)
    X = np.zeros((len(runs), 30), np.float32)  # an older, narrower feature width: padded on load
    X[:, 0] = strength + rng.normal(scale=0.3, size=len(runs))
    np.savez(tmp_path / "states_it000.npz", X=X, visit=np.tile([17, 17, 18, 33], 200).astype(np.int16),
             explored=np.zeros(len(runs), bool), run=runs, crown=np.zeros(len(runs), np.int8),
             outcome=(3 * strength + rng.normal(size=len(runs)).repeat(1)).astype(np.float32),
             seeds=np.arange(200), wins=np.array([0]))
    np.savez(tmp_path / "states_it001.partial.npz", X=X[:4])  # an unfinished iteration is ignored
    assert E.load_states(tmp_path)["X"].shape == (800, len(feature_names()))
    rows = E.curve(tmp_path, [50, 200, 999], [0.8, 1.0])
    assert [(r["runs"], r["td_lambda"]) for r in rows] == [(50, 0.8), (50, 1.0), (200, 0.8), (200, 1.0)]
    assert rows[-1]["r2_within"] > 0.3 and rows[-1]["sweeps"] == 1


def test_mlp_value_learns_an_interaction_the_linear_value_cannot(tmp_path):
    import numpy as np

    from cursed_words_solver.sim.game import expert as E

    # the outcome depends on owning two items together (a combo), not on either alone
    rng = np.random.default_rng(2)
    n = 600
    runs = np.repeat(np.arange(n), 3)
    a, b = np.repeat(rng.integers(0, 2, n), 3), np.repeat(rng.integers(0, 2, n), 3)
    X = rng.normal(scale=0.1, size=(len(runs), 8)).astype(np.float32)
    X[:, 0], X[:, 1] = a, b
    outcome = 6.0 * (a & b) + np.repeat(rng.normal(scale=0.5, size=n), 3)
    np.savez(tmp_path / "states_it000.npz", X=X, visit=np.tile([17, 18, 33], n).astype(np.int16),
             explored=np.zeros(len(runs), bool), run=runs, crown=np.zeros(len(runs), np.int8),
             outcome=outcome.astype(np.float32), seeds=np.arange(n), wins=np.array([0]))
    rows = E.compare_values(tmp_path, hiddens=((16,),), sweeps=2, epochs=60)
    ridge, mlp = rows
    assert mlp["model"] == "mlp (16,)" and mlp["r2"] > 0.8 and mlp["r2"] > ridge["r2"] + 0.1
    m, fit = E.train_value_mlp(E.load_states(tmp_path), hidden=(16,), sweeps=1, epochs=20)
    assert m.target == "value" and fit["runs"] == n


def test_value_models_compare_after_states_skip_restocks_and_explore():
    from cursed_words_solver.sim.game.agent import Action
    from cursed_words_solver.sim.game.expert import NetPolicy
    from cursed_words_solver.sim.game.features import feature_names

    class Money:  # values money only: leaving (keeping the cash) beats any purchase
        target = "value"

        def predict(self, X):
            return X[:, feature_names().index("log_money")]

    g, _ = _full_shop()
    pol = NetPolicy(_NoSearch(), Money(), threshold=0.0)
    buy = next(a for a in pol.candidates(g) if a.kind == "buy")
    restock = Action("reroll_shop")
    assert pol.pick(g, [buy, Action("leave")]).kind == "leave"
    assert pol.pick(g, [restock, Action("leave")]).kind == "reroll_shop"  # a suggested restock stands
    assert pol.pick(g, [buy, restock]).kind == "buy"  # and is never picked over the suggestion
    pol.threshold = 1e9
    assert pol.pick(g, [buy, Action("leave")]).kind == "buy"  # inside the margin: keep the suggestion
    explorer = NetPolicy(_NoSearch(), None, explore=1.0, seed=3)
    a, cands = explorer.decide(g)
    assert explorer.explored and len(cands) > 1 and a in cands[1:]


def test_value_models_value_advice_swaps_whole_and_leave_freezes_and_sells_to_advice():
    from cursed_words_solver.sim.game.agent import Action
    from cursed_words_solver.sim.game.expert import NetPolicy, full_shop_candidates
    from cursed_words_solver.sim.game.features import feature_names

    def model(name):
        class M:
            target = "value"

            def predict(self, X):
                return X[:, feature_names().index(name)]

        return M()

    g, _ = _full_shop()  # 5 stickers owned, Parrot on offer that fits only after a sale
    pol = NetPolicy(_NoSearch(), model("n_stickers"), threshold=0.0)
    sell, leave = Action("sell", ("sticker", 0), "swap: sell Candle for Parrot"), Action("leave")
    # the sell alone looks like a sticker lost; with the planned buy it is a like-for-like swap
    pol._pending_buy = ("sticker", 0)
    assert pol.pick(g, [sell, leave]).kind == "sell"
    pol._pending_buy = None  # a plain sell is Advice's call
    assert pol.pick(g, [sell, leave]).kind == "sell"
    money = NetPolicy(_NoSearch(), model("log_money"), threshold=0.0)
    money._pending_buy = ("sticker", 0)  # valued as a whole, the swap costs money: a money-only model leaves
    assert money.pick(g, [sell, leave]).kind == "leave"
    money._pending_buy = None
    cands = full_shop_candidates(g, leave)
    freeze = next(a for a in cands if a.kind == "freeze")
    buy = next(a for a in cands if a.kind in ("buy", "sell_buy"))
    assert money.pick(g, [freeze, leave]).kind == "freeze"  # a suggested freeze stands
    assert money.pick(g, [buy, freeze]) == buy  # a freeze is never picked (it looks free)


def test_value_fits_leave_out_spending_and_frozen_stock():
    import numpy as np

    from cursed_words_solver.sim.game.expert import train_value, value_drop_mask
    from cursed_words_solver.sim.game.features import feature_names

    names = feature_names()
    mask = value_drop_mask()
    assert mask[names.index("log_invested")] and mask[names.index("frozen:Candle")] and not mask[names.index("log_money")]
    rng = np.random.default_rng(3)
    runs = np.repeat(np.arange(300), 2)
    X = np.zeros((len(runs), len(names)), np.float32)
    rich = np.repeat(rng.normal(size=300), 2)
    X[:, names.index("log_invested")] = rich  # tracks the outcome perfectly, but is not allowed
    X[:, names.index("log_money")] = rich + rng.normal(scale=1.0, size=len(runs))
    data = {"X": X, "run": runs, "visit": np.tile([17, 33], 300).astype(np.int16), "outcome": (2 * rich).astype(np.float32),
            "crown": np.zeros(len(runs), np.int8), "explored": np.zeros(len(runs), bool)}
    m, fit = train_value(data, sweeps=1)
    assert m.w[names.index("log_invested")] == 0 and m.w[names.index("log_money")] > 0 and fit["dropped"] == mask.sum()
    _, open_fit = train_value(data, sweeps=1, drop=False)
    assert open_fit["r2"] > fit["r2"]


def test_trials_randomise_choices_that_show_their_effect_and_keep_controls():
    import numpy as np

    from cursed_words_solver.sim.game.agent import Action
    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.expert import NetPolicy, afterstate, full_shop_candidates

    g, _ = _full_shop()
    leave = Action("leave")
    cands = full_shop_candidates(g, leave)
    pol = NetPolicy(_NoSearch(), None, randomise=1.0, control=0.0, seed=4)
    take = pol._trial(g, cands, leave)
    xa, xt, kind, control = pol.trial
    assert take.kind in E.VALUE_KINDS - {"leave"} and kind == take.kind and not control and pol.explored
    assert np.array_equal(xa, afterstate(g, leave)) and np.array_equal(xt, afterstate(g, take))
    keep = NetPolicy(_NoSearch(), None, randomise=1.0, control=1.0, seed=4)
    assert keep._trial(g, cands, leave) == leave and keep.trial[3] and np.array_equal(keep.trial[0], keep.trial[1])
    freeze = next(a for a in cands if a.kind == "freeze")
    pol.trial = None
    assert pol._trial(g, cands, freeze) == freeze and pol.trial is None  # a freeze's effect is not in the features
    pins_only = NetPolicy(_NoSearch(), None, randomise=1.0, control=0.0, seed=4, trial_kinds=frozenset({"pin"}))
    assert pins_only._trial(g, cands, leave) == leave and pins_only.trial is None  # shop choices stay the champion's
    from cursed_words_solver.sim.game.expert import SHOP_CAP

    pol._steps = SHOP_CAP  # a step that is no run-level decision (here: the shop's step cap)
    assert pol.decide(g)[1] == [] and pol.trial is None and not pol.explored  # the last trial is not recorded again


def test_rct_models_pick_on_after_state_differences():
    from cursed_words_solver.sim.game.agent import Action
    from cursed_words_solver.sim.game.expert import NetPolicy
    from cursed_words_solver.sim.game.features import feature_names

    class Money:  # an advantage model: keeping cash is good; its intercept must not count
        target = "rct"

        def predict(self, X):
            return X[:, feature_names().index("log_money")] + 5.0

    g, _ = _full_shop()
    pol = NetPolicy(_NoSearch(), Money(), threshold=0.0)
    buy = next(a for a in pol.candidates(g) if a.kind in ("buy", "sell_buy"))
    assert pol.pick(g, [buy, Action("leave")]).kind == "leave"
    assert pol.pick(g, [Action("leave"), buy]).kind == "leave"

    import numpy as np

    class Unsure(Money):  # the same advantage, but too uncertain to act on
        penalty = 1.0

        def se(self, D):
            return np.full(len(D), 100.0)

    assert NetPolicy(_NoSearch(), Unsure(), threshold=0.0).pick(g, [buy, Action("leave")]) == buy

    class ByKind:  # a tree model: told the suggestion's after-state and each move's kind
        target = "rct_tree"
        threshold = 0.0

        def advantage(self, xa, xt, kinds):
            assert xa.ndim == 1 and len(xt) == len(kinds)
            return np.array([0.5 if k == "leave" else -0.5 for k in kinds])

    assert NetPolicy(_NoSearch(), ByKind(), threshold=0.0).pick(g, [buy, Action("leave")]).kind == "leave"
    assert NetPolicy(_NoSearch(), ByKind(), threshold=0.6).pick(g, [buy, Action("leave")]) == buy
    assert NetPolicy(_NoSearch(), ByKind(), threshold=0.0).pick(g, [Action("leave"), buy]).kind == "leave"


def test_tree_advantage_depends_on_the_build_and_survives_a_save(tmp_path):
    import numpy as np
    import pytest

    lgb = pytest.importorskip("lightgbm")
    from cursed_words_solver.sim.game.learn import TreeAdvantage, load_model

    rng = np.random.default_rng(3)
    n, width = 2000, 4
    xa = rng.normal(size=(n, width)).astype(np.float32)
    xt = xa.copy()
    xt[:, 1] += rng.choice((0.0, 1.0), n).astype(np.float32)  # some moves add one of item 1
    kinds = rng.choice(["buy", "leave"], n).tolist()
    # item 1 pays only in builds with a high column 0 (no linear difference model can say this)
    y = (xt[:, 1] - xa[:, 1]) * np.where(xa[:, 0] > 0, 1.0, -1.0)
    m = TreeAdvantage(None, ["buy", "leave"])
    X = m.rows(xa[0], xt[:1], kinds[:1])
    assert X.shape == (1, 2 * width + 1)
    X = np.vstack([m.rows(a, t[None, :], [k]) for a, t, k in zip(xa, xt, kinds)])
    m.booster = lgb.train({"objective": "regression", "verbosity": -1, "min_data_in_leaf": 10, "num_threads": 1},
                          lgb.Dataset(X, y), 60)
    high, low = np.array([2.0, 0, 0, 0], np.float32), np.array([-2.0, 0, 0, 0], np.float32)
    move = np.array([[0, 1.0, 0, 0]], np.float32)
    assert m.advantage(high, high + move, ["buy"])[0] > 0.5
    assert m.advantage(low, low + move, ["buy"])[0] < -0.5
    assert m.threshold == 0.0
    m.threshold = 0.3
    path = tmp_path / "trees.npz"
    m.save(path)
    loaded = load_model(path)
    assert loaded.target == "rct_tree" and loaded.kinds == ["buy", "leave"] and loaded.threshold == 0.3
    assert loaded.advantage(high, high + move, ["buy"]) == pytest.approx(m.advantage(high, high + move, ["buy"]))
    assert np.isfinite(loaded.advantage(high, high + move, ["never_seen"])).all()
    old = dict(np.load(path))  # a file saved before margins were stored plays at 0
    del old["threshold"]
    np.savez_compressed(path, **old)
    assert load_model(path).threshold == 0.0


def test_rct_fit_finds_the_effect_a_confounded_state_value_misses(tmp_path):
    import numpy as np

    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.features import feature_names

    rng = np.random.default_rng(5)
    n, width = 600, 6
    strength = rng.normal(size=n)
    # column 1: an item that adds +1.5 when a trial buys it; column 2: one that adds nothing,
    # but strong runs own more of it (the confound a state value learns)
    xa = np.zeros((2 * n, width), np.float32)
    trun = np.repeat(np.arange(n), 2)
    xa[:, 0] = strength[trun] + rng.normal(scale=0.5, size=2 * n)
    xa[:, 2] = strength[trun]
    change = rng.integers(0, 4, 2 * n)  # 0 control, 1 +col1, 2 −col1, 3 +col2
    xt = xa.copy()
    xt[change == 1, 1] += 1
    xt[change == 2, 1] -= 1
    xt[change == 3, 2] += 1
    effect = np.select([change == 1, change == 2], [1.5, -1.5], 0.0)
    final = 3 * strength + np.bincount(trun, effect, n) + rng.normal(scale=0.5, size=n)
    X = np.concatenate([xa, xt])
    srun = np.concatenate([trun, trun])
    order = np.argsort(srun, kind="stable")
    rep = np.insert(np.arange(2 * n), 1, 0)  # older files repeat a trial at the steps after it: dropped on load
    kinds = np.where(change == 0, "leave", "buy")
    np.savez(tmp_path / "rct_it000.npz", X=X[order], visit=np.tile([17, 33], 2 * n).astype(np.int16),
             explored=np.zeros(4 * n, bool), run=srun[order], crown=np.zeros(4 * n, np.int8),
             outcome=final[srun[order]].astype(np.float32),
             t_xa=xa[rep], t_xt=xt[rep], t_kind=kinds[rep], t_control=(change == 0)[rep],
             t_visit=np.full(2 * n + 1, 17, np.int16), t_run=trun[rep], t_crown=np.zeros(2 * n + 1, np.int8),
             t_outcome=final[trun[rep]].astype(np.float32), seeds=np.arange(n), wins=np.array([0]))
    np.savez(tmp_path / "rct_it001.partial.npz", t_xa=xa[:2])  # an unfinished iteration is ignored
    trials, states = E.load_trials(tmp_path), E.load_states(tmp_path, "rct_it*.npz")
    assert trials["xa"].shape == (2 * n, len(feature_names())) and len(states["run"]) == 4 * n
    m, fit = E.train_rct(states, trials, sweeps=1)
    W = len(feature_names())

    def adv(col, d):
        x = np.zeros((1, W), np.float32)
        x[0, col] = d
        return float(m.predict(x)[0] - m.predict(np.zeros((1, W), np.float32))[0])

    assert m.target == "rct" and fit["deviations"] == int((change != 0).sum())
    assert adv(1, 1.0) > 1.0 and abs(adv(2, 1.0)) < 0.5 and fit["oof_corr"] > 0.3 and fit["baseline_r2"] > 0.5
    assert fit["switch_gain"] > 0.5 and fit["switch_gain_t"] > 3 and set(fit["by_kind"]) == {"buy"}
    assert fit["switch_by_margin"]["0.3"][0] > 0 and fit["switch_by_margin"]["0.3"][1] > 0.5
    x1 = np.zeros((1, W), np.float32)
    x1[0, 1] = 1.0
    se1 = float(m.se(x1)[0])
    assert 0 < se1 < adv(1, 1.0) / 3 and set(fit["lcb_by_margin"]) == {"1", "2"}
    m.penalty = 2.0
    m.save(tmp_path / "m.npz")
    from cursed_words_solver.sim.game.learn import load_model

    back = load_model(tmp_path / "m.npz")
    assert back.penalty == 2.0 and abs(float(back.se(x1)[0]) - se1) < 1e-4 * se1 + 1e-6
    _, lfit = E.train_rct(states, trials, sweeps=1, label_lam=0.5)  # trained on λ-returns, still checked on outcomes
    assert lfit["label_lam"] == 0.5 and lfit["label_sd"] == fit["label_sd"] and lfit["fit_label_sd"] < fit["fit_label_sd"]
    assert lfit["oof_corr"] > 0.3
    names = feature_names()
    xt2 = trials["xt"].copy()
    xt2[:, names.index("item:Candle")] += 1  # a per-class change: a shared model cannot see it
    shared, sfit = E.train_rct(states, {**trials, "xt": xt2}, sweeps=1, shared=True)
    assert sfit["shared"] and shared.w[names.index("item:Candle")] == 0 and shared.w[1] > 0


def test_saved_models_say_what_they_predict(tmp_path):
    import numpy as np

    from cursed_words_solver.sim.game.learn import MLP, Ridge, load_model

    r = Ridge(4)
    r.save(tmp_path / "a.npz")
    assert load_model(tmp_path / "a.npz").target == "advantage"
    r.target, r.threshold = "value", 0.3
    r.save(tmp_path / "v.npz")
    assert (load_model(tmp_path / "v.npz").target, load_model(tmp_path / "v.npz").threshold) == ("value", 0.3)
    m = MLP(4, hidden=(3,))
    m.threshold = 0.6
    m.save(tmp_path / "m.npz")
    back = load_model(tmp_path / "m.npz")
    assert back.target == "value" and back.threshold == 0.6
    assert np.allclose(back.predict(np.ones((2, 4))), m.predict(np.ones((2, 4))))


def test_quick_pick_is_a_legal_shop_action(tmp_path):
    from cursed_words_solver.sim.game.advise import quick_pick
    from cursed_words_solver.sim.game.agent import legal_actions

    g = _game(seed=13)
    _clear(g)
    assert g.phase == "shop"
    a = quick_pick(g, _NoSearch(), model=None)
    assert (a.kind, a.args) in {(b.kind, b.args) for b in legal_actions(g)} or a.kind == "leave"


def _letter(ch: str, tile_type: str = "normal"):
    from cursed_words_solver.sim.game.core import Tile

    t = Tile()
    t.set_letter(ch)
    t.tile_type = tile_type
    return t


def test_tile_buys_take_the_offer_that_lifts_a_probe_grid_most():
    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig
    from cursed_words_solver.sim.game.shop import TileInStock

    g = _game(seed=13)
    s = _shop_at(g, Node.SHOP_ONE, 20)
    s.tiles = [TileInStock(_letter("Q"), 4), TileInStock(_letter("E"), 3)]
    pol = FastAdvicePolicy(_NoSearch(), PowerConfig(tile_buys=True, tile_buy_gain=0.25, tile_reserve=5))
    lift = {"q": 0.2, "e": 0.6}
    pol._tile_lift = lambda game, ri: lift[game.player.consumables[ri].srep()]
    a = pol._tile_buy(g)
    assert (a.kind, a.args) == ("buy", ("tile", 1))
    lift["e"] = 0.1  # neither lifts enough (the memo is per build and offer: clear it)
    pol._tile_cache = {}
    assert pol._tile_buy(g) is None
    lift["e"] = 0.6
    pol._tile_cache = {}
    g.player.money = 7  # buying E would leave $4, under the $5 reserve
    assert pol._tile_buy(g) is None
    g.player.money = 20
    for ch in "ABC":  # rack already holds tile_rack_max tiles
        g.player.add_tile(_letter(ch))
    assert pol._tile_buy(g) is None


def test_per_character_settings_in_the_benchmark_policy():
    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.policy import tuned_config

    pol = E.NetPolicy(_NoSearch(), None)
    assert pol._tile_buys_on(_game(character="Spike"))
    assert not pol._tile_buys_on(_game(character="WetDennis"))
    assert tuned_config().tile_buy_chars == ("Spike",)
    assert pol.cfg.tile_reserve == pol.cfg.spend_over
    assert pol._sort_stamps_on(_game(character="SockHead"))
    assert not pol._sort_stamps_on(_game(character="Spike"))
    assert tuned_config().sort_stamps_chars == ("SockHead",)
    assert pol.cfg.route_value and tuned_config().route_value and not pol.cfg.ogre
    from cursed_words_solver.sim.game.bossmodel import DEFAULT_PATH

    want = str(DEFAULT_PATH) if DEFAULT_PATH.is_file() else ""  # CI has no fitted model: table only
    assert pol.cfg.boss_model == tuned_config().boss_model == want
    assert E.NetPolicy(_NoSearch(), None, boss_model="").cfg.boss_model == ""


def test_sort_stamps_searches_stamp_swaps_too():
    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig

    g = _game(seed=13)
    _shop_at(g, Node.SHOP_ONE, 0)
    g.player.stamps[0] = make_item("Dragon")
    g.player.stamps[1] = make_item("RightHumanHand")
    for on in (False, True):
        pol = FastAdvicePolicy(_NoSearch(), PowerConfig(sort_items=True, sort_stamps=on))
        # probe points: 100, or 150 with the hand left of the Dragon (it boosts the stamp to its right)
        pol.power = lambda game: 150.0 if [getattr(x, "game_class", None) for x in game.player.stamps[:2]] == ["RightHumanHand", "Dragon"] else 100.0
        a = pol._best_move(g)
        assert (a is not None and (a.kind, a.args) == ("move", ("stamp", 0, 1))) == on


def test_tile_save_places_the_cheaper_rack_tile_when_it_does_nearly_as_well():
    from types import SimpleNamespace

    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig

    g = _game(seed=13)
    assert g.phase == "encounter"
    g.player.consumables = [None] * 5
    g.player.add_tile(_letter("E", "shiny"))  # value 50
    g.player.add_tile(_letter("E"))  # value 1

    class _Probe(_NoSearch):
        def words(self, game, _n=1):  # the shiny tile placed: 100, the plain one: 95, none: 50
            rack = [t.tile_type for t in game.player.tiles()]
            score = 50 if len(rack) == 2 else (95 if rack == ["shiny"] else 100)
            return [SimpleNamespace(score=score)]

    for save, used in ((False, 0), (True, 1)):
        pol = FastAdvicePolicy(_Probe(), PowerConfig(fast_placement=True, placement_targets=2, tile_save=save))
        a = pol._best_placement(g, 50)
        assert a.kind == "place" and a.args[0] == used


def test_char_overrides_switch_settings_by_character_and_crown():
    import pytest

    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig, char_settings, with_overrides

    over = {"Spike": {"buy_threshold": 0.06, "tile_buy_chars": []}, "Spike@3-7": {"spend_over": 40}, "Carpman@0": {"swap_sell": True}}
    assert char_settings(over, "Spike", 1) == {"buy_threshold": 0.06, "tile_buy_chars": []}
    assert char_settings(over, "Spike", 5) == {"buy_threshold": 0.06, "tile_buy_chars": [], "spend_over": 40}
    assert char_settings(over, "Carpman", 0) == {"swap_sell": True} and char_settings(over, "Carpman", 1) == {}
    cfg = with_overrides(PowerConfig(tile_buy_chars=("Spike",)), char_settings(over, "Spike", 5))
    assert (cfg.buy_threshold, cfg.spend_over, cfg.tile_buy_chars) == (0.06, 40, ())
    with pytest.raises(ValueError):
        with_overrides(PowerConfig(), {"no_such_knob": 1})
    pol = FastAdvicePolicy(_NoSearch(), PowerConfig(char_overrides={"WetDennis": {"buy_threshold": 0.5}}))
    pol._tune(_game())  # Wet Dennis, crown 0
    assert pol.cfg.buy_threshold == 0.5 and pol._base_cfg.buy_threshold == 0.02
    pol._tune(_game(character="HumanBoy"))
    assert pol.cfg is pol._base_cfg


def test_chartune_seeds_arms_and_promotion(tmp_path):
    from cursed_words_solver.sim.game import chartune as C
    from cursed_words_solver.sim.game.policy import PowerConfig

    all_seeds = [s for p in range(3) for r in range(3) for _, s in C.seeds("Spike", p, r)]
    assert len(all_seeds) == len(set(all_seeds)) == 3 * 96 and all(7_000_000 <= s < 8_000_000 for s in all_seeds)
    labels = dict(C.arms(PowerConfig(tile_buy_chars=("Spike",)), "Spike"))
    assert labels["tile_buys=False"] == {"tile_buys": False, "tile_buy_chars": []}
    assert "buy_threshold=0.02" not in labels and labels["swap_sell=True"] == {"swap_sell": True}

    t = C.Tuner(tmp_path / "work", tmp_path / "table.json")

    def play(char, overs, ss):  # buy_threshold=0.06 is worth +1.5, everything else noise
        for o in overs:
            for _, s in ss:
                noise = ((s * 7919 + len(C.key(o)) * 104729) % 1000) / 250 - 2
                t.runs[(char, s, C.key(o))] = {"outcome": 8 + noise + 1.5 * (o.get("buy_threshold") == 0.06)}

    t.play = play
    rec = t.tune("Spike", 0, PowerConfig(tile_buy_chars=("Spike",)))
    assert rec["promoted"] == "buy_threshold=0.06" and t.table["overrides"]["Spike"] == {"buy_threshold": 0.06}
    assert rec["stats"]["n"] == 96 and rec["fresh"]["n"] == 48
    rec = t.tune("Spike", 1, PowerConfig(tile_buy_chars=("Spike",)))  # now the champion: going back loses
    assert "promoted" not in rec and t.table["overrides"]["Spike"] == {"buy_threshold": 0.06}


def test_curse_items_follow_the_game_through_the_simulator():
    """Decompiled rules for the Curse items, scored by the real sim -> bridge -> engine path."""
    from cursed_words_solver.sim.game import core as C
    from cursed_words_solver.sim.game.items import make_item

    def letter(c):
        return lambda t: t.set_letter(c)

    def blank(t):
        t.set_glyph(C.G_BLANK)

    def chess(t):
        t.set_chess("knight", True)

    def card(t):
        t.set_letter("a")
        t.set_suit(C.HEARTS)

    def red_blank(t):
        blank(t)
        t.tile_type = C.RED

    def setup(names, spec, fields=None):
        g = _game(character="WetDennis", seed=7, ascension=0)
        p = g.player
        p.stickers, p.stamps = [None] * 5, [None] * 5
        made = [make_item(n) for n in names]
        for it in made:
            assert p.add_item(it, g.rng, acquire=False)
        enc = Encounter(g)
        g.encounter = enc
        enc.setup()
        enc.bosses = []
        enc.remaining_target = 10**9
        for t in enc.grid.available():
            t.set_as_copy(C.Tile(letter="z", x=t.x, y=t.y), False)
        for x, f in enumerate(spec):
            f(enc.grid.at(x, 0))
        for it in made:  # after generation: the Crystal Ball rolls at the start of each grid
            it.fields.update(fields or {})
        return g, enc, [(x, 0) for x in range(len(spec))], made

    def score(names, spec, fields=None):
        _, enc, path, _ = setup(names, spec, fields)
        return enc.score_preview(path, ["cat"]).int_score

    plain = [letter("c"), letter("a"), letter("t")]
    one = [blank, letter("a"), letter("t")]
    two = [blank, card, letter("t")]
    three = [blank, card, chess]
    same_ends = [blank, letter("a"), blank]
    diff_ends = [blank, letter("a"), chess]

    assert score(["Oden"], plain) == 0  # no curse types: x0
    assert score(["Oden"], one) == score([], one)  # one type: unchanged
    assert score(["Oden"], two) == 2 * score([], two)
    assert score(["MischievousImp"], one) == score([], one)
    assert score(["MischievousImp"], three) == 2 * score([], three)
    assert score(["CreakyChair"], two) == score([], two)
    assert score(["CreakyChair"], three) == 2 * score([], three)
    assert score(["Broom"], same_ends) == score([], same_ends)
    assert score(["Broom"], diff_ends) == int(1.5 * score([], diff_ends))
    assert score(["Broom"], [letter("c"), letter("a"), blank]) == score([], [letter("c"), letter("a"), blank])
    assert score(["CrystalBall"], one, {"ChosenCurseType": "Blank"}) == score([], one) + 70
    assert score(["CrystalBall"], one, {"ChosenCurseType": "Chess"}) == score([], one)
    assert score(["MysteriousAmulet"], plain) == score([], plain)
    assert score(["MysteriousAmulet"], one) > score([], one)
    assert score(["Moai"], one) > score([], one)
    coloured = [red_blank, letter("a"), letter("t")]
    assert score(["Moai"], coloured) == score([], coloured)

    g, enc, path, _ = setup(["JackOLantern"], one)
    with_jack = enc.submit(path, ["cat"])
    g2, enc2, path2, _ = setup([], one)
    without = enc2.submit(path2, ["cat"])
    assert (with_jack.money_after - with_jack.money_before) - (without.money_after - without.money_before) == 1

    g, enc, path, (book,) = setup(["MichaelsBook"], plain, {"CurrentWord": "cat", "WordLength": 3})
    assert enc.submit(path, ["cat"]).score == score([], plain) + 30
    assert book.fields["Count"] == 1 and len(book.fields["CurrentWord"]) == 4


def test_soft_commitment_seeks_generators_until_the_plan_has_a_source():
    from dataclasses import replace

    from cursed_words_solver.sim.game.items import make_item
    from cursed_words_solver.sim.game.shop import ItemInStock

    g, s, pol = _plan_shop("Curse")
    pol.cfg = replace(pol.cfg, build_plan_commit=1)
    g.player.pin = make_item("CarpStreamers")  # makes no cursed tiles
    assert pol._plan_phase(g) == "seek"
    assert pol._offer_ok(g, "Beefeater")  # off-plan items stay open while seeking
    s.stickers[0] = ItemInStock(make_item("Broom"), 12)
    for j in range(1, len(s.stickers)):
        s.stickers[j] = None
    for j in range(len(s.stamps)):
        s.stamps[j] = None
    step = pol._build_plan_step(g)
    assert step is None or step.kind == "reroll_shop"  # a payoff item alone is not the plan's to buy yet
    s.stickers[1] = ItemInStock(make_item("Amphora"), 13)
    step = pol._build_plan_step(g)
    assert (step.kind, step.args) == ("buy", ("sticker", 1))
    assert g.player.add_item(make_item("Amphora"), g.rng, acquire=False)
    assert pol._plan_phase(g) == "commit" and not pol._offer_ok(g, "Beefeater")

    g2, _, pol2 = _plan_shop("Curse")
    pol2.cfg = replace(pol2.cfg, build_plan_commit=1)
    g2.player.pin = make_item("Bicycle")  # scatters suited, so cursed, tiles by itself
    assert pol2._plan_phase(g2) == "commit"

    g3, _, pol3 = _plan_shop("Curse")
    pol3.cfg = replace(pol3.cfg, build_plan_stage=2)
    g3.player.run.stage = 1
    assert pol3._plan_phase(g3) == "" and pol3._build_plan_step(g3) is None and pol3._offer_ok(g3, "Beefeater")
    g3.player.run.stage = 2
    assert pol3._plan_phase(g3) == "commit"


def test_plantest_arms_share_seeds_and_report_against_any_arm():
    from cursed_words_solver.sim.game import plantest as T

    name, cfg = T.parse_arm("g1=Curse:build_plan_commit=1,build_plan_reserve=13")
    assert name == "g1" and cfg == {"build_plan": "Curse", "build_plan_chars": {}, "build_plan_commit": 1, "build_plan_reserve": 13}
    jobs = T.make_jobs([T.BASE, "Curse", "g1"], ["Spike"], 0, 8, arms={"g1": cfg})
    seeds = {p: {j["seed"] for j in jobs if j["plan"] == p} for p in (T.BASE, "Curse", "g1")}
    assert seeds["Curse"] == seeds["g1"] == seeds[T.BASE]
    assert next(j for j in jobs if j["plan"] == "g1")["cfg"] == cfg
    assert next(j for j in jobs if j["plan"] == "Curse")["cfg"] == {"build_plan": "Curse", "build_plan_chars": {}}
    runs = {(j["plan"], j["seed"]): {"plan": j["plan"], "seed": j["seed"], "character": j["character"], "crown": j["crown"],
                                     "error": None, "stage": 5, "outcome": 10.0 + (j["plan"] == "g1"),
                                     "won": j["plan"] == "g1" and j["seed"] % 2 == 0}
            for j in jobs}
    g = T.gains(runs, "g1", base="Curse")
    assert g["only_plan"] == 4 and g["only_base"] == 0 and g["wins"] == 4
    text = "\n".join(T.versus(runs, "Curse"))
    assert "Against Curse" in text and "g1" in text and "Spike" in text


def test_gate_wins_route_passes_a_big_win_gain_with_no_mean_gain_and_needs_seeds():
    from cursed_words_solver.sim.game import bench

    def row(k, out, won):
        return {"char": k[0], "crown": k[1], "seed": k[2], "won": won, "reason": "x", "outcome": out, "stage": 5}

    ss = bench.seeds(8)  # 704 seeds
    # all or nothing: the arm's wins come with losses that cancel the mean
    base = {k: row(k, 10.0, False) for k in ss}
    arm = {k: row(k, 18.0 if i % 4 == 0 else 7.33, i % 4 == 0) for i, k in enumerate(ss)}
    rep = bench.gate_report(base, arm, single_use=True)
    assert rep["wins_pass"] and rep["promote"] and rep["decision"] != "accept"
    assert not bench.gate_report(base, arm, single_use=False)["promote"]
    few = bench.seeds(2)
    rep = bench.gate_report({k: base[k] for k in few}, {k: arm[k] for k in few}, single_use=True)
    assert not rep["wins_pass"]  # too few seeds
    # wins bought with a clearly lower mean do not pass
    worse = {k: row(k, 18.0 if i % 4 == 0 else 2.0, i % 4 == 0) for i, k in enumerate(ss)}
    assert not bench.gate_report(base, worse, single_use=True)["wins_pass"]


def test_default_ai_plays_curse_with_chess_for_sam_gambit_and_human_boy():
    from cursed_words_solver.sim.game import plantest as T
    from cursed_words_solver.sim.game.expert import NetPolicy
    from cursed_words_solver.sim.game.policy import tuned_config

    assert tuned_config().build_plan == "Curse"
    assert tuned_config().build_plan_chars == {"SamGambit": "Chess", "SockHead": "Chess"}
    for ch, want in (("SamGambit", "Chess"), ("SockHead", "Chess"), ("Spike", "Curse")):
        g, _, _ = _plan_shop("Curse")
        g.player.character = ch
        pol = NetPolicy(_NoSearch(), None, seed=1)
        pol._tune(g)
        assert pol.cfg.build_plan == want
    # no plan is the rules player for every character, the Chess pair included
    g, _, _ = _plan_shop("Curse")
    g.player.character = "SamGambit"
    pol = NetPolicy(_NoSearch(), None, seed=1)
    for k, v in T.plan_cfg(T.BASE).items():
        setattr(pol.cfg, k, v)
    pol._tune(g)
    assert pol.cfg.build_plan == ""
    # a plan arm plays that plan for everyone
    pol = NetPolicy(_NoSearch(), None, seed=1)
    for k, v in T.plan_cfg("Curse").items():
        setattr(pol.cfg, k, v)
    pol._tune(g)
    assert pol.cfg.build_plan == "Curse"


def test_model_candidates_keep_to_the_plan():
    from cursed_words_solver.sim.game.expert import NetPolicy
    from cursed_words_solver.sim.game.items import make_item
    from cursed_words_solver.sim.game.policy import offer_class
    from cursed_words_solver.sim.game.shop import ItemInStock

    g, s, _ = _plan_shop("Curse")
    s.stickers[0] = ItemInStock(make_item("Beefeater"), 5)  # another build's item
    pol = NetPolicy(_NoSearch(), None, seed=1)
    pol._tune(g)
    cands = pol.candidates(g)
    assert all(offer_class(g, a) != "Beefeater" for a in cands[1:])
