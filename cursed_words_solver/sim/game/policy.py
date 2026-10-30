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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cursed_words_solver.sim.game.agent import Action, Candidates, WordOption, apply, clone, legal_actions
from cursed_words_solver.sim.game.core import Rng
from cursed_words_solver.sim.game.encounter import Encounter
from cursed_words_solver.sim.game.player import ENCOUNTER_NODES, NUMBER_OF_STAGES, Node

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
    boss_risk: str = ""  # bossrisk.py table: draft the boss least likely to end the run
    pin_side: str = "lower"  # FastAdvicePolicy pin reward: "lower" side, "power" (probe), "left" / "right",
    # "learned" (pinplan.py's model of the rollout choices), or "rollout" (NetPolicy:
    # each side played to the end of the run on the same keyed futures; see expert._pin_rollout)
    pin_samples: int = 2  # "rollout": keyed futures per side
    # "rollout" horizon: 0 = run outcome at the end of the run (labels were pure noise,
    # 2026-10-29); n = build strength after n more stages (expert.play_out ``stages``)
    pin_horizon: int = 1
    pin_playout_side: str = "lower"  # pin rule inside those play-outs (no nested rollouts)
    michael_aware: bool = True  # stage-5 draft: weigh surviving the cursed boss and the Michael bonus
    michael_prior_risk: float = 0.5
    michael_value: float = 0.5  # extra run wins a Michael win is worth (features.MICHAEL_BONUS / 16)
    cursed_margin: float = 0.05  # with boss_risk: take a cursed boss unless this much riskier
    swap_sell: bool = False  # slots full: sell an owned item to buy a better one (probe-checked)
    power_override: float = 0.0  # replace Advice's buy when another adds this much more probe power
    spend_over: int = 0  # Advice says leave but money > this: buy by probe power / restock (0 = off)
    spend_threshold: float = 0.0  # spend-down buys need this relative probe gain (0 = buy_threshold)
    item_value: str = ""  # learned item-value table (itemvalue.py); "" = off
    item_value_weight: float = 0.0  # relative probe gain added per encounter of learned item value
    boss_effort: float = 0.0  # effort-mode word search at this effort in boss encounters (0 = same)
    final_spend: bool = False  # last shop before the final boss: money is worthless after it, spend it all
    sort_items: bool = False  # before leaving a shop, swap stickers when it adds probe points
    advice_fallback: bool = False  # Advice silent (no build yet): buy by probe-encounter power
    fast_placement: bool = False  # FastAdvicePolicy: place rack tiles when behind pace (probe search)
    # Rack tiles. Advice almost never buys them (20 of 944 offers in 22 runs, 2026-10-29):
    # ``tile_buys`` buys an affordable one that, placed on a probe grid, lifts the best word by
    # ``tile_buy_gain`` (relative), keeping ``tile_reserve`` money and at most ``tile_rack_max``.
    # ``tile_buy_chars`` turns it on for those characters only. Benchmarked 2026-10-29: neutral
    # overall with a $20 reserve (a $5 one starved item buys: -0.30), Spike 13 -> 18 of 32 wins.
    tile_buys: bool = False
    tile_buy_chars: tuple[str, ...] = ()
    tile_buy_gain: float = 0.1  # median offer lifts 1.6%, p90 18% (44 offers, 3 runs)
    tile_reserve: int = 20  # = spend_over: only money spend-down would have spent anyway
    tile_rack_max: int = 3
    # ``tile_save``: placing, use the least valuable rack tile (Tile.GetValue: shiny 50, gold =
    # money, letter value + colour) among those within ``tile_save_ratio`` of the best gain.
    tile_save: bool = False
    tile_save_ratio: float = 0.85
    # FastAdvicePolicy encounter planner: compare the top words / reroll / best placement by
    # playing the rest of the encounter out (see ``FastAdvicePolicy._plan``).
    plan_encounter: bool = False
    plan_from_stage: int = 1  # plan only from this stage (the planner is ~4x slower per encounter)
    plan_words: int = 4
    plan_samples: int = 2
    plan_level_value: float = 3.0  # $ per item level gained (Bar Chart, Fountain Pen, ...)
    plan_tile_value: float = 2.0  # $ per consumable tile still on the rack


def tuned_config(**kw) -> PowerConfig:
    """Fast Advice settings found best by deterministic benchmarks (Carpman crown 0): the
    learned boss-risk table when one exists, rack-tile placement when behind pace (8 target
    squares) and the encounter planner (top words / reroll / placement played out)."""
    from cursed_words_solver.sim.game.bossrisk import DEFAULT_PATH

    base = {"probe_seeds": 1, "probe_grids": 2, "fast_placement": True, "placement_targets": 8,
            "advice_fallback": True, "sort_items": True, "spend_over": 20, "power_override": 0.1,
            "swap_sell": True, "plan_encounter": True, "tile_buy_chars": ("Spike",),
            "boss_risk": str(DEFAULT_PATH) if DEFAULT_PATH.is_file() else ""}
    return PowerConfig(**{**base, **kw})


def build_signature(game: "Game") -> tuple:
    """Everything a probe encounter's score depends on: items in order with levels, foil,
    colours and counters, the rack, money and crown / character."""
    p = game.player

    def sig(it):
        if it is None:
            return None
        return (it.game_class, tuple(tuple(c) for c in it.components), it.is_foil,
                tuple(it.relevant_colours), repr(sorted(it.state_fields().items())),
                tuple(sig(n) for n in it.nested_items()))

    return (p.character, p.run.ascension, p.money, sig(p.pin), tuple(sig(i) for i in p.stickers),
            tuple(sig(i) for i in p.stamps), tuple((t.srep(), t.tile_type) if t else None for t in p.consumables))


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

    def enc_cands(self, game: "Game") -> Candidates:
        """Word search for the current encounter: deeper in boss fights (``boss_effort``)."""
        if self.cfg.boss_effort and self.cands.effort and game.player.run.node == Node.BOSS:
            if getattr(self, "_boss_cands", None) is None:
                self._boss_cands = self.cands.with_effort(self.cfg.boss_effort)
            return self._boss_cands
        return self.cands

    # -- power -------------------------------------------------------------------

    def power(self, game: "Game", *, bosses: list | None = None, stage_node: tuple[int, Node] | None = None) -> float:
        """Mean points a fresh probe encounter yields with this loadout (greedy words).

        Deterministic for a given build / money / position (the probe RNG is keyed by
        position), so results are memoised per build signature."""
        key = None
        if bosses is None:
            key = (build_signature(game), stage_node or next_encounter_node(game))
            cache = getattr(self, "_power_cache", None)
            if cache is None or len(cache) > 4096:
                cache = self._power_cache = {}
            if key in cache:
                return cache[key]
        v = self._power(game, bosses=bosses, stage_node=stage_node)
        if key is not None:
            self._power_cache[key] = v
        return v

    def _power(self, game: "Game", *, bosses: list | None = None, stage_node: tuple[int, Node] | None = None) -> float:
        cfg = self.cfg
        total = 0.0
        stage, node = stage_node or next_encounter_node(game)
        for s in range(cfg.probe_seeds):
            g = self._probe_game(game, stage, node, s, bosses)
            enc = g.encounter
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

    def _probe_game(self, game: "Game", stage: int, node: Node, s: int, bosses: list | None = None) -> "Game":
        """A copy of ``game`` in a fresh probe encounter at (stage, node), probe RNG ``s``."""
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
        return g

    def _tile_lift(self, game: "Game", rack_index: int) -> float:
        """Relative lift of the best word on a probe grid of the next encounter when the rack
        tile ``rack_index`` is placed on the best of the lowest-value squares."""
        stage, node = next_encounter_node(game)
        g = self._probe_game(game, stage, node, 0)
        opts = self.probe_cands.words(g, 1)
        base = opts[0].score if opts else 0
        p = g.player
        squares = sorted((t for t in g.encounter.grid.available() if t.consumable_replacement_allowed(p)),
                         key=lambda t: t.get_value(p))[: self.cfg.placement_targets]
        best = base
        for t in squares:
            h = clone(g)
            if h.place_consumable(rack_index, t.x, t.y):
                o = self.probe_cands.words(h, 1)
                best = max(best, o[0].score if o else 0)
        return (best - base) / max(1, base)

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
        opts = self.enc_cands(game).words(game, 3)
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
        found: list[tuple[float, int, Action]] = []
        for ri in rack:
            for t in tiles:
                g = clone(game)
                if not g.place_consumable(ri, t.x, t.y):
                    continue
                opts = self.probe_cands.words(g, 1)
                if opts and opts[0].score > base * 1.15 + 2:
                    found.append((opts[0].score - base, ri, Action("place", (ri, t.x, t.y), f"place rack {ri} on {t.x},{t.y}")))
        if not found:
            return None
        best_gain = max(f[0] for f in found)
        if self.cfg.tile_save:
            # keep the valuable rack tiles: the cheapest one that does nearly as well
            near = [f for f in found if f[0] >= self.cfg.tile_save_ratio * best_gain]
            return min(near, key=lambda f: (p.consumables[f[1]].get_value(p), -f[0]))[2]
        return next(f[2] for f in found if f[0] == best_gain)

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
        self._moves_this_shop = 0
        self._spend_restocks = 0
        self._swaps_this_shop = 0
        self._pending_buy = None

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
        self._moves_this_shop = 0
        self._spend_restocks = 0
        self._swaps_this_shop = 0
        self._pending_buy = None
        return Action("leave")

    def _advice_shop(self, game: "Game") -> Action:
        from cursed_words_solver.game_shop.recommendation import compute_shop_advice

        s = game.shop
        pending, self._pending_buy = getattr(self, "_pending_buy", None), None
        if pending is not None and s.can_buy(*pending):
            return Action("buy", pending, "swap: buy replacement")
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
                    pick = Action("buy", (kind, it.index), f"advice: buy {it.name}")
                    if self.cfg.power_override:
                        pick = self._power_check(game, pick)
                    stock = s.stickers if pick.args[0] == "sticker" else s.stamps
                    if stock[pick.args[1]] is not None:
                        self._bought_this_shop.add(stock[pick.args[1]].item.game_class)
                    return pick
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
        if self.cfg.advice_fallback and not adv.recommended_items and not adv.recommended_tiles:
            buy = self._fallback_buy(game)
            if buy is not None:
                return buy
        final = self.cfg.final_spend and self._final_shop(game)
        if self.cfg.swap_sell and self._swaps_this_shop < (3 if final else 1):
            swap = self._best_swap(game)
            if swap is not None:
                self._swaps_this_shop += 1
                return swap
        if self._tile_buys_on(game):
            buy = self._tile_buy(game)
            if buy is not None:
                return buy
        floor = 0 if final else self.cfg.spend_over
        if (self.cfg.spend_over or final) and game.player.money > floor:
            buy = self._fallback_buy(game, threshold=0.005 if final else self.cfg.spend_threshold or None)
            if buy is not None:
                return buy
            if s.can_reroll() and game.player.money - s.reroll_cost >= floor + (not final) and self._spend_restocks < (8 if final else 3):
                self._spend_restocks += 1
                return Action("reroll_shop", (), "spend down: restock")
        if self.cfg.sort_items and self._moves_this_shop < 2:
            move = self._best_move(game)
            if move is not None:
                self._moves_this_shop += 1
                return move
        return self._leave()

    @staticmethod
    def _final_shop(game: "Game") -> bool:
        run = game.player.run
        return run.stage == NUMBER_OF_STAGES and run.node == Node.SHOP_TWO

    def _best_swap(self, game: "Game") -> Action | None:
        """With every slot of a kind full no purchase is possible: try selling each owned
        sticker / stamp for each shop offer of that kind and, if the best pair adds more than
        ``power_override`` probe points, sell now and buy the replacement next."""
        from cursed_words_solver.sim.game.shop import can_sell

        p, s = game.player, game.shop
        base = max(1.0, self.power(game))
        best, best_pair = max(self.cfg.power_override, self.cfg.buy_threshold), None
        for kind, owned, stock in (("sticker", p.stickers, s.stickers), ("stamp", p.stamps, s.stamps)):
            if any(o is not None and s.can_buy(kind, j) for j, o in enumerate(stock)):
                continue  # something is buyable outright: ordinary buys handle it
            for i, it in enumerate(owned):
                if it is None or not can_sell(p, it) or it.game_class in self._bought_this_shop:
                    continue
                for j, o in enumerate(stock):
                    if o is None or o.item.game_class == it.game_class:
                        continue
                    g = clone(game)
                    if g.sell(kind, i) is None or not g.shop.can_buy(kind, j):
                        continue
                    if not apply(g, Action("buy", (kind, j))):
                        continue
                    gain = ((self.power(g) - base) / base + self._item_bonus(game, o.item.game_class)
                            - self._item_bonus(game, it.game_class))
                    if gain > best:
                        best, best_pair = gain, (kind, i, j)
        if best_pair is None:
            return None
        kind, i, j = best_pair
        self._pending_buy = (kind, j)
        self._sold_this_shop = True
        return Action("sell", (kind, i), f"swap: sell {owned_name(p, kind, i)} for {stock_name(s, kind, j)} (+{best:.0%})")

    def _best_move(self, game: "Game") -> Action | None:
        """Sticker order matters (Human Boy's hands, Overhand / Underhand, left-to-right
        effects): before leaving, take the swap that adds the most probe-encounter points."""
        p = game.player
        filled = [i for i, it in enumerate(p.stickers) if it is not None]
        if len(filled) < 2:
            return None
        sig = tuple((it.game_class, tuple(tuple(c) for c in it.components)) if it else None for it in p.stickers)
        if sig == getattr(self, "_sorted_sig", None):
            return None  # no improving swap was found for exactly this line-up
        base = max(1.0, self.power(game))
        best, best_a = self.cfg.buy_threshold, None
        for a in range(5):
            for b in range(a + 1, 5):
                if p.stickers[a] is None and p.stickers[b] is None:
                    continue
                src, dst = (a, b) if p.stickers[a] is not None else (b, a)
                g = clone(game)
                if not g.move("sticker", src, dst):
                    continue
                gain = (self.power(g) - base) / base
                if gain > best:
                    best, best_a = gain, Action("move", ("sticker", src, dst), f"swap stickers {src}<->{dst}")
        if best_a is None:
            self._sorted_sig = sig
        return best_a

    def _item_bonus(self, game: "Game", game_class: str | None) -> float:
        """Learned long-term value of owning ``game_class`` (``item_value``), in probe-gain units."""
        if not (self.cfg.item_value and self.cfg.item_value_weight and game_class):
            return 0.0
        if getattr(self, "_item_table", None) is None:
            from cursed_words_solver.sim.game.itemvalue import ItemValue

            self._item_table = ItemValue.load(Path(self.cfg.item_value))
        p = game.player
        return self.cfg.item_value_weight * self._item_table.value(game_class, p.run.stage, p.character)

    def _power_gains(self, game: "Game", acts: list[Action]) -> list[tuple[float, Action]]:
        """(relative probe-encounter points gained, action) for each buy that applies."""
        base = max(1.0, self.power(game))
        out = []
        for a in acts:
            g = clone(game)
            bonus = self._item_bonus(game, offer_class(game, a))
            if apply(g, a):
                out.append(((self.power(g) - base) / base + bonus, a))
        return out

    def _power_check(self, game: "Game", pick: Action) -> Action:
        """Advice's purchase unless another affordable sticker / stamp adds more than
        ``power_override`` (relative probe points) beyond what Advice's pick adds."""
        acts = [a for a in legal_actions(game) if a.kind == "buy" and a.args[0] in ("sticker", "stamp")]
        gains = self._power_gains(game, acts)
        mine = next((v for v, a in gains if a.args == pick.args), None)
        if mine is None or not gains:
            return pick
        v, best = max(gains, key=lambda t: t[0])
        if v > mine + self.cfg.power_override and best.args != pick.args:
            return Action("buy", best.args, f"probe: {best.label} (+{v:.0%} vs Advice +{mine:.0%})")
        return pick

    def _fallback_buy(self, game: "Game", threshold: float | None = None) -> Action | None:
        """The game's Advice has nothing to say until an owned item carries a build tag
        (Human Boy, Sam Gambit, Nat-H4 start with none), so it would never buy. Then take
        the affordable sticker / stamp that adds the most points to a probe encounter."""
        acts = [a for a in legal_actions(game) if a.kind == "buy" and a.args[0] in ("sticker", "stamp")]
        if not acts:
            return None
        base = max(1.0, self.power(game))
        best, best_a = self.cfg.buy_threshold if threshold is None else threshold, None
        for a in acts:
            g = clone(game)
            bonus = self._item_bonus(game, offer_class(game, a))
            if not apply(g, a):
                continue
            gain = (self.power(g) - base) / base + bonus
            if gain > best:
                best, best_a = gain, a
        if best_a is not None:
            stock = game.shop.stickers if best_a.args[0] == "sticker" else game.shop.stamps
            if stock[best_a.args[1]] is not None:
                self._bought_this_shop.add(stock[best_a.args[1]].item.game_class)
        return best_a

    def _tile_buys_on(self, game: "Game") -> bool:
        return self.cfg.tile_buys or game.player.character in self.cfg.tile_buy_chars

    def _tile_buy(self, game: "Game") -> Action | None:
        """The affordable rack tile that lifts a probe grid's best word the most, if by at
        least ``tile_buy_gain`` (results memoised per build and offer)."""
        s, p = game.shop, game.player
        if len(p.tiles()) >= self.cfg.tile_rack_max:
            return None
        cache = getattr(self, "_tile_cache", None)
        if cache is None or len(cache) > 1024:
            cache = self._tile_cache = {}
        best, best_a = self.cfg.tile_buy_gain, None
        for k, o in enumerate(s.tiles):
            if o is None or not s.can_buy_tile(k) or p.money - o.get_price(p) < self.cfg.tile_reserve:
                continue
            sig = build_signature(game)
            key = (sig[:2] + sig[3:], next_encounter_node(game), o.tile.srep(), o.tile.tile_type)  # not money
            if key not in cache:
                g = clone(game)
                before = list(g.player.consumables)
                lift = 0.0
                if apply(g, Action("buy", ("tile", k))):
                    new = [i for i, (a, b) in enumerate(zip(before, g.player.consumables)) if a is None and b is not None]
                    lift = self._tile_lift(g, new[0]) if new else 0.0
                cache[key] = lift
            if cache[key] > best:
                best, best_a = cache[key], Action("buy", ("tile", k), f"probe: tile {o.tile.srep()} (+{cache[key]:.0%})")
        return best_a

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


class FastAdvicePolicy(AdvicePolicy):
    """Advice shopping with no simulation anywhere: the cheap base policy for rollouts.

    Boss: an uncursed option unless chasing Michael (crown ≥ 1, all cursed so far), else the
    lower floor modification. Pin: the less-upgraded side. No consumable-placement search.
    """

    def _best_placement(self, game: "Game", base: int) -> Action | None:
        return super()._best_placement(game, base) if self.cfg.fast_placement else None

    def _boss(self, game: "Game") -> Action:
        opts = game.boss_options()
        p = game.player
        if self.cfg.boss_risk:
            return Action("boss", (self._risk_boss(game, opts),))
        if self.cfg.go_for_michael and p.run.ascension >= 1 and not p.has_faced_uncursed_boss:
            cursed = [i for i, b in enumerate(opts) if b.cursed]
            if cursed:
                return Action("boss", (cursed[0],))
        ranked = sorted(range(len(opts)), key=lambda i: (opts[i].cursed, opts[i].game_class == "BigBoss"))
        return Action("boss", (ranked[0],))

    def _encounter(self, game: "Game") -> Action:
        enc = game.encounter
        if (self.cfg.plan_encounter and enc.michael_draft is None and not enc.finale
                and not enc.awaiting_forced_sell and game.player.run.stage >= self.cfg.plan_from_stage):
            a = self._plan(game)
            if a is not None:
                return a
        return super()._encounter(game)

    def _terminal_value(self, game: "Game") -> float:
        p = game.player
        levels = sum(it.level(i) for it in p.all_items(for_comparison=True) for i in range(len(it.components)))
        return p.money + self.cfg.plan_level_value * levels + self.cfg.plan_tile_value * len(p.tiles())

    def _plan(self, game: "Game") -> Action | None:
        scored = self.plan_scores(game)
        return scored[0][2] if scored else None

    def plan_scores(self, game: "Game", samples: int | None = None) -> list[tuple[float, float, Action]]:
        """Pick among the top words, a grid reroll and the best rack-tile placement by the
        rest of the encounter: clearing dominates (a loss ends the run), then money, item
        levels gained and rack tiles kept at the end of the encounter. A word that clears
        is valued exactly; others by ``plan_samples`` greedy play-outs. ``plan_scores``
        returns (value, P(clear), action), best first. A lower word that
        does not clear is considered while the best one would, only if it earns more than
        the $2 an unused grid pays (builds that make money per grid)."""
        from cursed_words_solver.sim.game.core import Rng

        enc = game.encounter
        samples = samples or self.cfg.plan_samples
        opts = self.enc_cands(game).words(game, self.cfg.plan_words)
        if not opts:
            return []
        if getattr(self, "_inner", None) is None:
            self._inner = FastAdvicePolicy(self.probe_cands, PowerConfig(reroll_ratio=self.cfg.reroll_ratio))
        LOSS = -1000.0
        best_clears = opts[0].score >= enc.remaining_target
        cands: list[tuple[Action, Any]] = []
        for o in opts:
            a = Action("submit", (tuple(o.path), tuple(o.words)), f"{o.word} ({o.score})")
            cands.append((a, o))
        if not best_clears:
            if enc.can_reroll():
                cands.append((Action("reroll_grid"), None))
            if game.player.tiles():
                place = super()._best_placement(game, opts[0].score)
                if place is not None:
                    cands.append((place, None))
        if len(cands) == 1:
            return [(0.0, 1.0, cands[0][0])]
        money0 = game.player.money
        scored: list[tuple[float, int, float, Action]] = []
        for rank, (a, o) in enumerate(cands):
            g = clone(game)
            e = g.encounter
            apply(g, a)
            if e.won or e.lost or e.finale:
                ok = bool(e.won or e.finale)
                scored.append((self._terminal_value(g) if ok else LOSS, -rank, float(ok), a))
                continue
            if best_clears and a.kind == "submit" and g.player.money - money0 <= 2:
                continue  # not clearing when we could, and the grid earns no more than its payout
            tot, wins = 0.0, 0
            for s in range(samples):
                h = clone(g)
                h.rng = Rng(f"plan|{s}|{len(e.previous_words)}")
                h.encounter.rng = h.rng
                f = h.encounter
                for _ in range(40):
                    if f.won or f.lost or f.finale or h.encounter is not f:
                        break
                    apply(h, self._inner.act(h))
                ok = bool(f.won or f.finale)
                wins += ok
                tot += self._terminal_value(h) if ok else LOSS
            scored.append((tot / samples, -rank, wins / samples, a))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [(v, pc, a) for v, _, pc, a in scored]

    def _risk_boss(self, game: "Game", opts: list) -> int:
        """Lowest learned risk; a cursed boss is preferred while it is not much riskier
        (``cursed_margin``) when chasing Michael (crown ≥ 1, every boss so far cursed), or
        slightly when Blessing of the Fairies makes the fairy worth something."""
        if getattr(self, "_boss_risk", None) is None:
            from cursed_words_solver.sim.game.bossrisk import BossRisk

            self._boss_risk = BossRisk.load(Path(self.cfg.boss_risk))
        p = game.player
        crown = p.run.ascension
        risk = [self._boss_risk.risk(b, crown, p.character) for b in opts]
        cursed = [i for i, b in enumerate(opts) if b.cursed]
        clean = [i for i, b in enumerate(opts) if not b.cursed]
        margin = None
        if crown >= 1 and self.cfg.go_for_michael and not p.has_faced_uncursed_boss:
            margin = self.cfg.cursed_margin
        elif crown >= 1 and p.unpacked_of("BlessingOfTheFairies"):
            margin = 0.02
        best_clean = min(clean, key=lambda i: risk[i]) if clean else None
        best_cursed = min(cursed, key=lambda i: risk[i]) if cursed else None
        if (margin is not None and best_cursed is not None and best_clean is not None
                and p.run.stage >= 5 and self.cfg.michael_aware):
            # The fifth cursed boss commits the run to Michael. Losing to him still wins the
            # run, so the cursed boss is worth its survival chance times (1 + the Michael
            # bonus if he is beaten); the uncursed one only its survival chance.
            if self._boss_risk.counts.get("MichaelBoss", (0, 0))[0] >= 10:
                michael = self._boss_risk.risk_key(f"MichaelBoss@c{crown}#{p.character}")
            else:
                michael = self.cfg.michael_prior_risk  # too few simulated Michael fights yet
            v_cursed = (1 - risk[best_cursed]) * (1 + self.cfg.michael_value * (1 - michael))
            return best_cursed if v_cursed >= (1 - risk[best_clean]) - margin else best_clean
        if best_cursed is not None and (best_clean is None or (
                margin is not None and risk[best_cursed] <= risk[best_clean] + margin)):
            return best_cursed
        return best_clean if best_clean is not None else best_cursed

    def _pin(self, game: "Game") -> Action:
        opts = game.pin_options()
        pin = game.player.pin
        if "both" in opts:
            return Action("pin", ("both",))
        if pin is None or len(opts) < 2:
            return Action("pin", (opts[0],))
        side = self.cfg.pin_side
        if side == "learned":
            from cursed_words_solver.sim.game.features import encode
            from cursed_words_solver.sim.game.pinplan import choose

            after = {}
            for o in ("left", "right"):
                g = clone(game, light=True)
                apply(g, Action("pin", (o,)))
                after[o] = encode(g)
            side = choose(game.player.character, encode(game), after["right"] - after["left"]) or "lower"
        if side in ("left", "right") and side in opts:
            return Action("pin", (side,))
        if side == "power":
            # Each side played into a probe encounter (RAM: which item joins the memory).
            def gain(o: str) -> float:
                g = clone(game)
                apply(g, Action("pin", (o,)))
                return self.power(g)
            scored = [(gain(o), -(pin.level(0) if o == "left" else pin.level(1)), o) for o in opts]
            return Action("pin", (max(scored)[2],))
        return Action("pin", ("left" if pin.level(0) <= pin.level(1) else "right",))

    def _cheapest_sell(self, game: "Game") -> Action | None:
        from cursed_words_solver.sim.game.shop import can_sell

        p = game.player
        cands = [(it.level(0) if it.components else 1, kind, i)
                 for kind, arr in (("sticker", p.stickers), ("stamp", p.stamps))
                 for i, it in enumerate(arr) if it is not None and can_sell(p, it)]
        if not cands:
            return None
        _, kind, i = min(cands)
        return Action("sell", (kind, i))

    def michael_pick(self, game: "Game") -> int:
        """Michael's draft: the boss effect the risk table rates least run-ending (first
        option without a table)."""
        draft = game.encounter.michael_draft
        if not self.cfg.boss_risk or not draft:
            return 0
        if getattr(self, "_boss_risk", None) is None:
            from cursed_words_solver.sim.game.bossrisk import BossRisk

            self._boss_risk = BossRisk.load(Path(self.cfg.boss_risk))
        p = game.player
        return min(range(len(draft)), key=lambda i: self._boss_risk.risk(draft[i], p.run.ascension, p.character))

    def act(self, game: "Game") -> Action:
        if game.phase == "encounter" and game.encounter.michael_draft is not None:
            return Action("michael_pick", (self.michael_pick(game),))
        return super().act(game)


def owned_name(p, kind: str, i: int) -> str:
    arr = p.stickers if kind == "sticker" else p.stamps
    return arr[i].game_class if arr[i] is not None else "?"


def offer_class(game: "Game", a: Action) -> str | None:
    """Item class a sticker / stamp ``buy`` action would purchase (None otherwise)."""
    if a.kind != "buy" or a.args[0] not in ("sticker", "stamp") or game.shop is None:
        return None
    stock = game.shop.stickers if a.args[0] == "sticker" else game.shop.stamps
    o = stock[a.args[1]] if 0 <= a.args[1] < len(stock) else None
    return o.item.game_class if o is not None else None


def stock_name(s, kind: str, j: int) -> str:
    arr = s.stickers if kind == "sticker" else s.stamps
    return arr[j].item.game_class if arr[j] is not None else "?"


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
