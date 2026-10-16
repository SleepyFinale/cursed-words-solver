"""Baseline policies over the simulator.

``GreedyPolicy``     best word each grid, never shops (floor reference).
``PowerPolicy``      decisions by simulated *power*: the points a loadout scores over a
                     probe encounter (fresh grids, greedy best word), compared with the
                     upcoming targets. Shop buys / rerolls / freezes / sells, boss picks
                     and pin upgrades all reduce to "which choice makes the build score
                     more against what's coming", so no per-item rules are needed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cursed_words_solver.sim.game.agent import Action, Candidates, WordOption, apply, clone, legal_actions
from cursed_words_solver.sim.game.core import Rng
from cursed_words_solver.sim.game.encounter import Encounter
from cursed_words_solver.sim.game.player import ENCOUNTER_NODES, Node

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.run import Game


class Policy:
    def act(self, game: "Game") -> Action:  # pragma: no cover - interface
        raise NotImplementedError


def play(game: "Game", policy: Policy, *, max_steps: int = 3000, log=None) -> "Game":
    steps = 0
    while game.phase != "done" and steps < max_steps:
        steps += 1
        a = policy.act(game)
        if log is not None:
            log(game, a)
        apply(game, a)
    return game


# ---------------------------------------------------------------------------- greedy


class GreedyPolicy(Policy):
    def __init__(self, cands: Candidates, *, boss_index: int = 0) -> None:
        self.cands = cands
        self.boss_index = boss_index

    def act(self, game: "Game") -> Action:
        ph = game.phase
        if ph == "encounter":
            enc = game.encounter
            if enc.michael_draft is not None:
                return Action("michael_pick", (0,))
            if enc.finale:
                return Action("finale")
            if enc.awaiting_forced_sell:
                return next(a for a in legal_actions(game) if a.kind == "sell")
            opts = self.cands.words(game, 1)
            if not opts:
                return Action("reroll_grid") if enc.can_reroll() else Action("skip")
            o = opts[0]
            return Action("submit", (tuple(o.path), tuple(o.words)), o.word)
        if ph == "shop":
            return Action("leave")
        if ph == "boss_draft":
            return Action("boss", (min(self.boss_index, len(game.boss_options()) - 1),))
        return Action("pin", (game.pin_options()[0],))


# ---------------------------------------------------------------------------- power


@dataclass
class PowerConfig:
    probe_grids: int = 4  # grids per probe encounter
    probe_seeds: int = 2  # probe encounters averaged
    reroll_ratio: float = 0.55  # reroll when best < ratio × needed-per-grid
    buy_threshold: float = 0.02  # min relative power gain per purchase
    money_weight: float = 0.0025  # relative power a $1 is worth keeping
    reroll_reserve: int = 15  # reroll the shop when nothing is worth buying and this much is spare
    max_shop_actions: int = 12
    placement_targets: int = 3
    go_for_michael: bool = True  # at crown ≥ 1, take cursed bosses to reach Michael
    probe_budget: float = 0.25  # seconds per probe-grid search (best found so far)


def next_encounter_node(game: "Game") -> tuple[int, Node]:
    run = game.player.run
    stage, node = run.stage, run.node
    if node in (Node.SHOP_ZERO,):
        return stage, Node.ENCOUNTER_FIRST
    if node == Node.SHOP_ONE:
        return stage, Node.ENCOUNTER_SECOND
    if node in (Node.SHOP_TWO, Node.BOSS_DRAFT, Node.MEG_SHOP):
        return stage, Node.BOSS
    if node == Node.BOSS_REWARD:
        return stage + 1, Node.ENCOUNTER_FIRST
    if node in ENCOUNTER_NODES:
        return stage, node
    return max(1, stage), Node.ENCOUNTER_FIRST


class PowerPolicy(Policy):
    def __init__(self, cands: Candidates, cfg: PowerConfig | None = None, seed: int = 0) -> None:
        self.cands = cands
        self.cfg = cfg or PowerConfig()
        self.probe_cands = cands.with_budget(self.cfg.probe_budget)
        self._shop_actions = 0
        self._probe_rng_seed = seed

    # -- power -------------------------------------------------------------------

    def power(self, game: "Game", *, bosses: list | None = None, stage_node: tuple[int, Node] | None = None) -> float:
        """Mean points a fresh probe encounter yields with this loadout (greedy words)."""
        cfg = self.cfg
        total = 0.0
        stage, node = stage_node or next_encounter_node(game)
        for s in range(cfg.probe_seeds):
            g = clone(game)
            g.rng = Rng(f"probe|{self._probe_rng_seed}|{stage}|{node}|{s}")
            run = g.player.run
            run.stage, run.node = stage, (Node.ENCOUNTER_SECOND if node == Node.BOSS and bosses is None else node)
            g.shop = None
            g.player._shop_listener = None
            enc = Encounter(g)
            enc.bosses = list(bosses or [])
            g.player.active_bosses = []
            g.encounter = enc
            if bosses:
                _probe_boss_setup(enc, bosses)
            else:
                enc._setup_rest()
            enc.awaiting_forced_sell = False
            enc.remaining_target = 10**15
            pts = 0
            for _ in range(min(cfg.probe_grids, enc.total_grids)):
                if enc.lost or enc.won:
                    break
                opts = self.probe_cands.words(g, 1)
                if not opts:
                    if enc.remaining_grids <= 0:
                        break
                    enc.skip()
                    continue
                o = opts[0]
                res = enc.submit(o.path, o.words)
                pts += max(0, res.score)
                if enc.remaining_grids <= 0:
                    break
            total += pts
        return total / max(1, cfg.probe_seeds)

    # -- decisions -------------------------------------------------------------------

    def act(self, game: "Game") -> Action:
        ph = game.phase
        if ph != "shop":
            self._shop_actions = 0
        if ph == "encounter":
            return self._encounter(game)
        if ph == "shop":
            return self._shop(game)
        if ph == "boss_draft":
            return self._boss(game)
        if ph == "pin_reward":
            return self._pin(game)
        return Action("leave")

    def _encounter(self, game: "Game") -> Action:
        enc = game.encounter
        cfg = self.cfg
        if enc.michael_draft is not None:
            best, best_i = -1.0, 0
            for i, b in enumerate(enc.michael_draft):
                pw = self.power(game, bosses=list(enc.michael.drafted) + [b], stage_node=(game.player.run.stage, Node.BOSS))
                if pw > best:
                    best, best_i = pw, i
            return Action("michael_pick", (best_i,))
        if enc.finale:
            return Action("finale")
        if enc.awaiting_forced_sell:
            return self._cheapest_sell(game) or Action("skip")
        opts = self.cands.words(game, 3)
        best = opts[0] if opts else None
        need = enc.remaining_target
        grids_left = enc.remaining_grids + 1
        per_grid = need / max(1, grids_left)
        if best is not None and best.score >= need:
            return Action("submit", (tuple(best.path), tuple(best.words)), best.word)
        # Consumables: when behind pace, try placing rack tiles where they lift the best word most.
        if game.player.tiles() and (best is None or best.score < per_grid):
            place = self._best_placement(game, best.score if best else 0)
            if place is not None:
                return place
        if enc.can_reroll() and (best is None or best.score < cfg.reroll_ratio * per_grid):
            return Action("reroll_grid")
        if best is None:
            return Action("skip")
        return Action("submit", (tuple(best.path), tuple(best.words)), best.word)

    def _best_placement(self, game: "Game", base: int) -> Action | None:
        enc = game.encounter
        p = game.player
        seen: set[str] = set()
        rack = []
        for i, t in enumerate(p.consumables):
            if t is not None and t.srep() + t.tile_type not in seen:
                seen.add(t.srep() + t.tile_type)
                rack.append(i)
        tiles = sorted(
            (t for t in enc.grid.available() if t.consumable_replacement_allowed(p)),
            key=lambda t: t.get_value(p),
        )[: self.cfg.placement_targets]
        best_gain, best_act = 0.0, None
        for ri in rack:
            for t in tiles:
                g = clone(game)
                if not g.place_consumable(ri, t.x, t.y):
                    continue
                opts = self.probe_cands.words(g, 1)
                if opts and opts[0].score > base * 1.15 + 2:
                    gain = opts[0].score - base
                    if gain > best_gain:
                        best_gain, best_act = gain, Action("place", (ri, t.x, t.y), f"place rack {ri} on {t.x},{t.y}")
        return best_act

    def _cheapest_sell(self, game: "Game") -> Action | None:
        sells = [a for a in legal_actions(game) if a.kind == "sell"]
        if not sells:
            return None
        base = self.power(game)
        best, best_a = -math.inf, sells[0]
        for a in sells:
            g = clone(game)
            apply(g, a)
            v = self.power(g)
            if v - base > best:
                best, best_a = v - base, a
        return best_a

    def _shop(self, game: "Game") -> Action:
        cfg = self.cfg
        if self._shop_actions >= cfg.max_shop_actions:
            self._shop_actions = 0
            return Action("leave")
        self._shop_actions += 1
        acts = [a for a in legal_actions(game) if a.kind in ("buy", "sell", "hippo")]
        base = self.power(game)
        if base <= 0:
            base = 1.0
        money = game.player.money
        best_score, best_a = 0.0, None
        for a in acts:
            g = clone(game)
            if not apply(g, a) and a.kind != "sell":
                continue
            v = self.power(g)
            spent = money - g.player.money
            score = (v - base) / base - cfg.money_weight * spent
            if score > best_score:
                best_score, best_a = score, a
        if best_a is not None and best_score >= cfg.buy_threshold:
            return best_a
        s = game.shop
        if s.can_reroll() and money - s.reroll_cost >= cfg.reroll_reserve:
            return Action("reroll_shop")
        self._shop_actions = 0
        return Action("leave")

    def _boss(self, game: "Game") -> Action:
        opts = game.boss_options()
        run = game.player.run
        if self.cfg.go_for_michael and run.ascension >= 1:
            cursed = [i for i, b in enumerate(opts) if b.cursed]
            if cursed and not game.player.has_faced_uncursed_boss:
                return Action("boss", (cursed[0],))
        best, best_i = -math.inf, 0
        for i, b in enumerate(opts):
            target = run.encounter_target(run.stage, Node.BOSS, game.player)
            if b.game_class == "BigBoss":
                target = int(round(target * b.floor_mod / 100.0))
            pw = self.power(game, bosses=[b], stage_node=(run.stage, Node.BOSS))
            ratio = pw / max(1, target)
            if ratio > best:
                best, best_i = ratio, i
        return Action("boss", (best_i,))

    def _pin(self, game: "Game") -> Action:
        opts = game.pin_options()
        if len(opts) == 1:
            return Action("pin", (opts[0],))
        best, best_c = -math.inf, opts[0]
        for c in opts:
            g = clone(game)
            g.player.pin.upgrade(-1 if c == "both" else (0 if c == "left" else 1), c == "both", rng=g.rng, player=g.player)
            v = self.power(g, stage_node=(game.player.run.stage + 1, Node.ENCOUNTER_FIRST))
            if v > best:
                best, best_c = v, c
        return Action("pin", (best_c,))


class AdvicePolicy(PowerPolicy):
    """Shop by the game's own Advice button (``game_shop.recommendation`` port); words,
    rerolls and consumables by the fast encounter heuristics; boss / pin by power probes."""

    def __init__(self, cands: Candidates, cfg: PowerConfig | None = None, seed: int = 0,
                 max_shop_actions: int = 15) -> None:
        super().__init__(cands, cfg or PowerConfig(probe_seeds=1, probe_grids=3), seed=seed)
        self.max_shop_actions_advice = max_shop_actions
        self._n = 0
        self._frozen_this_shop: set[tuple[str, int]] = set()
        self._bought_this_shop: set[str] = set()
        self._sold_this_shop = False

    def act(self, game: "Game") -> Action:
        if game.phase != "shop":
            self._n = 0
            self._frozen_this_shop = set()
            return super().act(game)
        self._n += 1
        if self._n > self.max_shop_actions_advice:
            return self._leave()
        return self._advice_shop(game)

    def _leave(self) -> Action:
        self._n = 0
        self._frozen_this_shop = set()
        self._bought_this_shop = set()
        self._sold_this_shop = False
        return Action("leave")

    def _advice_shop(self, game: "Game") -> Action:
        from cursed_words_solver.game_shop.recommendation import compute_shop_advice

        s = game.shop
        loadout, state = shop_advice_inputs(game)
        try:
            adv = compute_shop_advice(loadout, state)
        except Exception:
            return self._leave()
        if adv.recommended_tiles and adv.should_buy:
            for t in adv.recommended_tiles:
                if s.can_buy_tile(t.index):
                    return Action("buy", ("tile", t.index), "advice: tile")
        if adv.recommended_items:
            for it in adv.recommended_items:
                kind = it.slot
                if kind not in ("sticker", "stamp"):
                    continue
                if (adv.should_buy or adv.should_upgrade) and s.can_buy(kind, it.index):
                    stock = s.stickers if kind == "sticker" else s.stamps
                    if stock[it.index] is not None:
                        self._bought_this_shop.add(stock[it.index].item.game_class)
                    return Action("buy", (kind, it.index), f"advice: buy {it.name}")
            if adv.should_sell:
                sell = self._weakest_sell(game, adv.recommended_items[0].price)
                if sell is not None:
                    return sell
            if adv.should_freeze:
                it = adv.recommended_items[0]
                key = (it.slot, it.index)
                stock = s.stickers if it.slot == "sticker" else s.stamps
                if key not in self._frozen_this_shop and 0 <= it.index < len(stock) and stock[it.index] is not None and not stock[it.index].frozen:
                    self._frozen_this_shop.add(key)
                    return Action("freeze", key, f"advice: freeze {it.name}")
        if adv.should_restock and s.can_reroll():
            return Action("reroll_shop", (), "advice: restock")
        return self._leave()

    def _weakest_sell(self, game: "Game", price: int) -> Action | None:
        """"Sell then buy": at most once per shop, only a level-1 sticker not bought here,
        and only when the recommended item is affordable afterwards (no buy/sell churn)."""
        from cursed_words_solver.sim.game.shop import can_sell

        if self._sold_this_shop:
            return None
        p = game.player
        cands = [
            (it.sell_value(p), i) for i, it in enumerate(p.stickers)
            if it is not None and can_sell(p, it) and it.level(0) <= 1
            and it.game_class not in self._bought_this_shop
            and p.money + it.sell_value(p) >= price
        ]
        if not cands:
            return None
        _, slot = min(cands)
        self._sold_this_shop = True
        return Action("sell", ("sticker", slot), "advice: sell weakest sticker")


def shop_advice_inputs(game: "Game"):
    """Sim shop → (``Loadout``, ``ShopState``) for ``game_shop.recommendation``."""
    from cursed_words_solver.game_state import loadout_from_game_state
    from cursed_words_solver.models import ShopOffer, ShopState
    from cursed_words_solver.sim.game.bridge import player_state, run_state

    p = game.player
    loadout = loadout_from_game_state({"player": player_state(p), "run": run_state(p)})
    loadout.extras["consumable_tile_count"] = str(len(p.tiles()))
    s = game.shop
    offers: list[ShopOffer] = []
    for kind, stock in (("sticker", s.stickers), ("stamp", s.stamps)):
        for i, o in enumerate(stock):
            if o is None:
                continue
            offers.append(ShopOffer(
                slot=kind, index=i, id=o.item.slug, name=o.item.name,
                level=o.item.times_upgraded + 1, foil=o.item.is_foil, price=s.offer_cost(o),
                base_price=o.cost, frozen=o.frozen, free=o.free or o.first_discount,
                hippo_eligible=bool(p.unpacked_of("HungryHippo")) and kind == "sticker",
            ))
    for i, t in enumerate(s.tiles):
        if t is None:
            continue
        offers.append(ShopOffer(
            slot="tile", index=i, id="consumable_tile", name="Consumable tile",
            price=t.get_price(p), base_price=t.price, sold=t.bought,
            color=t.tile.tile_type, curse=t.tile.glyph, letter=t.tile.srep(True),
        ))
    state = ShopState(
        restock_cost=s.reroll_cost, free_item_available=s.free_item_active,
        angel_investment_available=s.angel_available(),
        hungry_hippo_equipped=bool(p.unpacked_of("HungryHippo")), offers=offers,
    )
    return loadout, state


def _probe_boss_setup(enc: Encounter, bosses: list) -> None:
    g = enc.game
    g.player.active_bosses = list(bosses)
    enc._setup_rest()
    enc.awaiting_forced_sell = False
