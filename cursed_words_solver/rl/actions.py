"""Every action a human can take at a decision point, as candidates for the pointer head.

Each candidate is an ``Action`` (``sim.game.agent`` vocabulary) plus a type id, up to two
token references (``obs.Obs.refs`` keys → token indices) and a small feature vector:
word scores, the cost, and a *visible* summary of what the action changes (money, item
levels / counters, rack, slots), measured on a clone whose hidden state is resampled
(``agent.determinize``) so nothing unseen leaks in.

"Anytime" actions (sell, reorder, discard a rack tile) are offered in encounters and shops,
capped per decision point so an episode can't loop forever. Boss drafts and pin rewards
list only their options (``Limits.draft_anytime`` restores the old padded set: the teacher
picked boss / pin there 100% of the time), and shops no longer list sell-and-buy swaps
(``Limits.sell_buy``; the teacher picked them 0.0%: sell, then buy, covers it).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import numpy as np

from cursed_words_solver.sim.game.agent import Action, apply, clears, clone, determinize, submit_action
from cursed_words_solver.sim.game.features import _counter

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.agent import Candidates
    from cursed_words_solver.sim.game.run import Game

ACTION_TYPES = ("submit", "skip", "reroll_grid", "place", "discard", "sell", "move", "buy", "hippo", "freeze",
                "reroll_shop", "leave", "sell_buy", "boss", "pin", "michael_pick", "finale")
ATYPE = {k: i for i, k in enumerate(ACTION_TYPES)}
N_ACTION_TYPES = len(ACTION_TYPES)
ANYTIME = ("sell", "move", "discard")
LEGACY_ACTION = ()   # n_action_features() of older layouts (none yet), for model.upgrade_config


@lru_cache(maxsize=1)
def action_columns() -> dict[str, int]:
    names = ["w_over_remaining", "w_over_per_grid", "w_log", "w_clears", "w_rank", "w_len", "w_nwords",
             "w_cursed_frac", "w_gap_best",
             "d_money", "d_levels", "d_counters", "d_items", "d_rack", "d_sell_value", "d_slots", "d_valid",
             "cost", "money_after", "affordable",
             "pl_gain", "pl_on_best", "pl_square_value",
             "mv_src", "mv_dst", "mv_dir",
             "pin_left", "pin_right", "pin_both", "pin_side_level",
             "is_tile_buy", "frozen_now", "boss_cursed",
             "pl_x", "pl_y", "pl_adj_best", "pl_in_top", "pl_free_nbrs"]
    return {n: i for i, n in enumerate(names)}


def n_action_features() -> int:
    return len(action_columns())


@dataclass
class Cand:
    action: Action
    atype: int
    ref1: Any = None          # obs ref key, e.g. ("shop_sticker", 2)
    ref2: Any = None
    feat: np.ndarray = field(default=None)  # type: ignore[assignment]


@dataclass
class Limits:
    words: int = 8
    place_squares: int = 4
    place_tiles: int = 6
    anytime_per_point: int = 6     # sells / moves / discards between two progress actions
    shop_actions: int = 24         # then only leave (and buys stay possible? no: leave only)
    afterstates: bool = True
    draft_anytime: bool = False    # sells / moves / discards at boss drafts and pin rewards too
    sell_buy: bool = False         # shop swaps (sell an owned item for an offer when that row is full)
    probes: bool = True            # probe-strength observation features (obs.set_probe_cands)


def _lg(x: float) -> float:
    return math.log1p(max(0.0, float(x)))


def _slg(x: float) -> float:
    return math.copysign(math.log1p(abs(float(x))), float(x))


def summary(game: "Game") -> np.ndarray:
    """Visible build summary used for action deltas."""
    p = game.player
    owned = [it for it in list(p.stickers) + list(p.stamps) if it is not None]
    levels = sum(it.level(0) for it in owned if it.components) + (p.pin.level(0) + p.pin.level(1) if p.pin is not None and len(p.pin.components) == 2 else 0)
    ctr = sum(_counter(it.fields) for it in owned)
    try:
        sv = sum(max(0, it.sell_value(p)) for it in owned)
    except Exception:
        sv = 0
    rack = sum(t is not None for t in p.consumables)
    free = sum(s is None for s in p.stickers) + sum(s is None for s in p.stamps)
    return np.array([p.money, levels, math.log1p(ctr), len(owned), rack, sv, free], dtype=np.float64)


def _delta(before: np.ndarray, after: np.ndarray, f: np.ndarray, col: dict) -> None:
    d = after - before
    f[col["d_money"]] = _slg(d[0])
    f[col["d_levels"]] = d[1]
    f[col["d_counters"]] = d[2]
    f[col["d_items"]] = d[3]
    f[col["d_rack"]] = d[4]
    f[col["d_sell_value"]] = _slg(d[5])
    f[col["d_slots"]] = d[6]
    f[col["d_valid"]] = 1.0


class CandidateBuilder:
    """Lists candidates for one decision. ``point_anytime`` / ``shop_actions`` are counters
    kept by the env (anytime actions since the last progress action, actions this shop)."""

    def __init__(self, cands: "Candidates", limits: Limits | None = None) -> None:
        self.cands = cands
        self.lim = limits or Limits()
        self.col = action_columns()
        self.last_words: list = []
        if self.lim.probes:
            from cursed_words_solver.rl.obs import set_probe_cands

            set_probe_cands(cands)

    def _new(self, a: Action, kind: str, ref1=None, ref2=None) -> Cand:
        return Cand(a, ATYPE[kind], ref1, ref2, np.zeros(len(self.col), dtype=np.float32))

    def _after(self, game: "Game", c: Cand, base: np.ndarray, *, light: bool, key: str) -> Any:
        if not self.lim.afterstates:
            return None
        try:
            g = clone(game, light=light)
            determinize(g, key)
            res = apply(g, c.action)
        except Exception:
            return None
        _delta(base, summary(g), c.feat, self.col)
        return res

    # ------------------------------------------------------------------ encounter

    def _words(self, game: "Game", out: list[Cand], base: np.ndarray, key: str) -> None:
        enc = game.encounter
        opts = self.cands.words(game, self.lim.words)
        self.last_words = opts
        best = opts[0].score if opts else 0
        cells = {(t.x, t.y): t for t in enc.grid.available()} if enc.grid is not None else {}
        for r, o in enumerate(opts):
            a = submit_action(o)
            c = self._new(a, "submit")
            self.word_feat(game, c, o.score, o.path, o.words, r, best, cells)
            self._after(game, c, base, light=False, key=key)
            out.append(c)

    def word_feat(self, game: "Game", c: Cand, score: float, path, words, rank: int, best: float,
                  cells: dict | None = None) -> None:
        enc = game.encounter
        p = game.player
        col = self.col
        f = c.feat
        rem = max(1.0, float(enc.remaining_target))
        per = rem / max(1, enc.remaining_grids)
        if cells is None:
            cells = {(t.x, t.y): t for t in enc.grid.available()} if enc.grid is not None else {}
        f[col["w_over_remaining"]] = min(4.0, score / rem)
        f[col["w_over_per_grid"]] = min(8.0, score / max(1.0, per))
        f[col["w_log"]] = _lg(score) / 10
        f[col["w_clears"]] = float(clears(game, score))
        f[col["w_rank"]] = min(rank, 8) / 8.0
        f[col["w_len"]] = len(path) / 10.0
        f[col["w_nwords"]] = len(words)
        cur = 0
        for xy in path:
            t = cells.get(tuple(xy))
            try:
                cur += bool(t is not None and t.is_cursed(p))
            except Exception:
                pass
        f[col["w_cursed_frac"]] = cur / max(1, len(path))
        f[col["w_gap_best"]] = (best - score) / max(1.0, best)

    def _places(self, game: "Game", out: list[Cand]) -> None:
        enc = game.encounter
        p = game.player
        if enc.grid is None:
            return
        best_path = set(tuple(xy) for xy in (self.last_words[0].path if self.last_words else ()))
        seen: set = set()
        rack = []
        for i, t in enumerate(p.consumables):
            if t is None:
                continue
            k = t.srep() + t.tile_type
            if k in seen:
                continue
            seen.add(k)
            rack.append((i, t))
        rack = rack[: self.lim.place_tiles]
        squares = [t for t in enc.grid.available() if t.consumable_replacement_allowed(p)]
        try:
            squares.sort(key=lambda t: t.get_value(p))
        except Exception:
            pass
        # cheapest squares, plus the best word's squares (placing there can lift that word)
        chosen = squares[: self.lim.place_squares]
        chosen += [t for t in squares if (t.x, t.y) in best_path and t not in chosen][:2]
        for i, rt in rack:
            for sq in chosen:
                a = Action("place", (i, sq.x, sq.y), f"place {rt.srep()} on {sq.x},{sq.y}")
                c = self._new(a, "place", ("rack", i))
                self.place_feat(game, c, rt, sq)
                out.append(c)

    def place_feat(self, game: "Game", c: Cand, rt, sq) -> None:
        """Value gain plus the square's position and context, so two squares never look identical."""
        p = game.player
        grid = game.encounter.grid
        col = self.col
        f = c.feat
        try:
            rv = rt.get_value(p)
        except Exception:
            rv = 0
        try:
            sv = sq.get_value(p)
        except Exception:
            sv = 0
        words = self.last_words or []
        best_path = set(tuple(xy) for xy in (words[0].path if words else ()))
        avail = {(t.x, t.y) for t in grid.available()} if grid is not None else set()
        xs = [x for x, _ in avail] or [1]
        ys = [y for _, y in avail] or [1]
        w, h = max(1, max(xs)), max(1, max(ys))
        nbrs = [(sq.x + dx, sq.y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
        f[col["pl_gain"]] = (rv - sv) / 10.0
        f[col["pl_on_best"]] = float((sq.x, sq.y) in best_path)
        f[col["pl_square_value"]] = sv / 10.0
        f[col["pl_x"]] = sq.x / w
        f[col["pl_y"]] = sq.y / h
        f[col["pl_adj_best"]] = sum(n in best_path for n in nbrs) / 8.0
        f[col["pl_in_top"]] = sum((sq.x, sq.y) in set(map(tuple, o.path)) for o in words) / max(1, len(words))
        f[col["pl_free_nbrs"]] = sum(n in avail for n in nbrs) / 8.0

    def static_feat(self, game: "Game", c: Cand) -> None:
        """Per-kind features that depend only on the action and the visible state (shared with cand_for)."""
        col = self.col
        f = c.feat
        k, x = c.action.kind, c.action.args
        p = game.player
        if k == "move":
            s, d = x[1], x[2]
            f[col["mv_src"]] = s / 4.0
            f[col["mv_dst"]] = d / 4.0
            f[col["mv_dir"]] = float(np.sign(d - s))
        elif k == "discard":
            f[col["d_rack"]] = -1.0
        elif k in ("buy", "hippo", "freeze", "sell_buy") and game.phase == "shop":
            s = game.shop
            if k == "buy" and x[0] == "tile":
                o = s.tiles[x[1]]
                price = o.get_price(p)
                f[col["cost"]] = _lg(price)
                f[col["money_after"]] = _slg(p.money - price)
                f[col["affordable"]] = 1.0
                f[col["is_tile_buy"]] = 1.0
                return
            kind = x[0]
            o = (s.stickers if kind == "sticker" else s.stamps)[x[2] if k == "sell_buy" else x[1]]
            if o is None:
                return
            cost = s.offer_cost(o)
            f[col["cost"]] = _lg(cost)
            if k == "buy":
                f[col["money_after"]] = _slg(p.money - cost)
                f[col["affordable"]] = 1.0
            if k in ("buy", "freeze"):
                f[col["frozen_now"]] = float(bool(o.frozen))
        elif k == "reroll_shop" and game.phase == "shop":
            f[col["cost"]] = _lg(game.shop.reroll_cost)
            f[col["money_after"]] = _slg(p.money - game.shop.reroll_cost)
        elif k == "boss":
            opts = game.boss_options()
            if x[0] < len(opts):
                f[col["boss_cursed"]] = float(bool(opts[x[0]].cursed))
        elif k == "pin":
            ch = x[0] if x else ""
            if ch in ("left", "right", "both"):
                f[col[f"pin_{ch}"]] = 1.0
            pin = p.pin
            if pin is not None and len(pin.components) == 2 and ch in ("left", "right"):
                f[col["pin_side_level"]] = pin.level(0 if ch == "left" else 1) / 5.0

    # ------------------------------------------------------------------ anytime

    def _anytime(self, game: "Game", out: list[Cand], base: np.ndarray, key: str, point_anytime: int) -> None:
        from cursed_words_solver.sim.game.shop import can_sell

        if point_anytime >= self.lim.anytime_per_point:
            return
        p = game.player
        for kind, arr in (("sticker", p.stickers), ("stamp", p.stamps)):
            for i, it in enumerate(arr):
                if it is not None and can_sell(p, it):
                    c = self._new(Action("sell", (kind, i), f"sell {it.game_class}"), "sell", (kind, i))
                    self._after(game, c, base, light=True, key=key)
                    out.append(c)
            filled = [i for i, it in enumerate(arr) if it is not None]
            if len(filled) >= 2:
                for s in filled:
                    for d in range(5):
                        if d == s or (arr[d] is None and d > max(filled)):
                            continue
                        c = self._new(Action("move", (kind, s, d), f"move {kind} {s}->{d}"), "move", (kind, s),
                                      (kind, d) if arr[d] is not None else None)
                        self.static_feat(game, c)
                        out.append(c)
        seen: set = set()
        for i, t in enumerate(p.consumables):
            if t is None:
                continue
            k = t.srep() + t.tile_type
            if k in seen:
                continue
            seen.add(k)
            c = self._new(Action("discard", (i,), f"discard rack {t.srep()}"), "discard", ("rack", i))
            self.static_feat(game, c)
            out.append(c)

    # ------------------------------------------------------------------ shop

    def _shop(self, game: "Game", out: list[Cand], base: np.ndarray, key: str, shop_actions: int) -> None:
        s = game.shop
        p = game.player
        col = self.col
        if shop_actions >= self.lim.shop_actions:
            return
        for kind, offers, tok in (("sticker", s.stickers, "shop_sticker"), ("stamp", s.stamps, "shop_stamp")):
            owned = p.stickers if kind == "sticker" else p.stamps
            full = all(it is not None for it in owned)
            for k, o in enumerate(offers):
                if o is None or s.slots_hidden(kind):  # Masochist / In The Beginning / Antiphilatelist
                    continue
                cost = s.offer_cost(o)
                if s.can_buy(kind, k):
                    c = self._new(Action("buy", (kind, k), f"buy {o.item.game_class} ${cost}"), "buy", (tok, k))
                    c.feat[col["cost"]] = _lg(cost)
                    c.feat[col["money_after"]] = _slg(p.money - cost)
                    c.feat[col["affordable"]] = 1.0
                    c.feat[col["frozen_now"]] = float(bool(o.frozen))
                    self._after(game, c, base, light=True, key=key)
                    out.append(c)
                    if kind == "sticker" and p.unpacked_of("HungryHippo"):  # Shop.buy ignores hippo on stamps
                        c = self._new(Action("hippo", (kind, k), f"feed {o.item.game_class} to Hungry Hippo"), "hippo", (tok, k))
                        c.feat[col["cost"]] = _lg(cost)
                        self._after(game, c, base, light=True, key=key)
                        out.append(c)
                elif full and self.lim.sell_buy:
                    # swap: sell an owned item for this offer (only when that row is full)
                    from cursed_words_solver.sim.game.shop import can_sell

                    for i, it in enumerate(owned):
                        if it is None or not can_sell(p, it):
                            continue
                        try:
                            if p.money + max(0, it.sell_value(p)) < cost:
                                continue
                        except Exception:
                            continue
                        a = Action("sell_buy", (kind, i, k), f"sell {it.game_class}, buy {o.item.game_class}")
                        c = self._new(a, "sell_buy", (tok, k), (kind, i))
                        c.feat[col["cost"]] = _lg(cost)
                        res = self._after(game, c, base, light=True, key=key)
                        if res is False:
                            continue
                        out.append(c)
                c = self._new(Action("freeze", (kind, k), f"{'unfreeze' if o.frozen else 'freeze'} {o.item.game_class}"),
                              "freeze", (tok, k))
                c.feat[col["frozen_now"]] = float(bool(o.frozen))
                c.feat[col["cost"]] = _lg(cost)
                out.append(c)
        for k, o in enumerate(s.tiles):
            if o is not None and s.can_buy_tile(k):
                price = o.get_price(p)
                c = self._new(Action("buy", ("tile", k), f"buy tile {o.tile.srep()} ${price}"), "buy", ("shop_tile", k))
                c.feat[col["cost"]] = _lg(price)
                c.feat[col["money_after"]] = _slg(p.money - price)
                c.feat[col["affordable"]] = 1.0
                c.feat[col["is_tile_buy"]] = 1.0
                self._after(game, c, base, light=True, key=key)
                out.append(c)
        if s.can_reroll():
            c = self._new(Action("reroll_shop", (), f"restock ${s.reroll_cost}"), "reroll_shop")
            c.feat[col["cost"]] = _lg(s.reroll_cost)
            c.feat[col["money_after"]] = _slg(p.money - s.reroll_cost)
            out.append(c)

    # ------------------------------------------------------------------ main

    def build(self, game: "Game", *, point_anytime: int = 0, shop_actions: int = 0, key: str = "afterstate") -> list[Cand]:
        ph = game.phase
        out: list[Cand] = []
        if ph == "done":
            return out
        base = summary(game)
        col = self.col
        if ph == "encounter":
            enc = game.encounter
            if enc.michael_draft is not None:
                for i, b in enumerate(enc.michael_draft):
                    c = self._new(Action("michael_pick", (i,), f"Michael draft: {b.game_class}"), "michael_pick", ("michael", i))
                    out.append(c)
                return out
            if enc.finale:
                return [self._new(Action("finale", (), "Solve Michael's puzzle grid"), "finale")]
            if enc.awaiting_forced_sell:
                self._anytime(game, out, base, key, 0)
                return [c for c in out if c.action.kind == "sell"] or out
            self._words(game, out, base, key)
            out.append(self._new(Action("skip", (), "skip grid"), "skip"))
            if enc.can_reroll():
                out.append(self._new(Action("reroll_grid", (), "reroll grid"), "reroll_grid"))
            self._places(game, out)
            self._anytime(game, out, base, key, point_anytime)
        elif ph == "shop":
            self._shop(game, out, base, key, shop_actions)
            self._anytime(game, out, base, key, point_anytime)
            out.append(self._new(Action("leave", (), "leave shop"), "leave"))
        elif ph == "boss_draft":
            for i, b in enumerate(game.boss_options()):
                c = self._new(Action("boss", (i,), f"fight {b.game_class}{' (cursed)' if b.cursed else ''}"), "boss", ("boss", i))
                c.feat[col["boss_cursed"]] = float(bool(b.cursed))
                out.append(c)
            if self.lim.draft_anytime:
                self._anytime(game, out, base, key, point_anytime)
        elif ph == "pin_reward":
            pin = game.player.pin
            for ch in game.pin_options():
                c = self._new(Action("pin", (ch,), f"pin upgrade: {ch}"), "pin", ("pin_offer", 0 if ch == "left" else 1) if ch in ("left", "right") else None)
                if ch in ("left", "right", "both"):
                    c.feat[col[f"pin_{ch}"]] = 1.0
                if pin is not None and len(pin.components) == 2 and ch in ("left", "right"):
                    c.feat[col["pin_side_level"]] = pin.level(0 if ch == "left" else 1) / 5.0
                out.append(c)
            if self.lim.draft_anytime:
                self._anytime(game, out, base, key, point_anytime)
        return out


def refs_for(a: Action) -> tuple[Any, Any]:
    k, x = a.kind, a.args
    if k in ("buy", "freeze", "hippo"):
        return (("shop_tile" if x[0] == "tile" else f"shop_{x[0]}", x[1]), None)
    if k == "sell":
        return ((x[0], x[1]), None)
    if k == "move":
        return ((x[0], x[1]), (x[0], x[2]))
    if k == "sell_buy":
        return ((f"shop_{x[0]}", x[2]), (x[0], x[1]))
    if k in ("place", "discard"):
        return (("rack", x[0]), None)
    if k == "boss":
        return (("boss", x[0]), None)
    if k == "michael_pick":
        return (("michael", x[0]), None)
    if k == "pin" and x and x[0] in ("left", "right"):
        return (("pin_offer", 0 if x[0] == "left" else 1), None)
    return (None, None)


def cand_for(builder: "CandidateBuilder", game: "Game", a: Action, key: str = "afterstate") -> Cand | None:
    """A candidate for an action the builder didn't list (e.g. a teacher's pick)."""
    if a.kind not in ATYPE:
        return None
    r1, r2 = refs_for(a)
    c = builder._new(a, a.kind, r1, r2)
    # same features the builder would have given it, so an added label is not recognisable
    try:
        if a.kind == "submit":
            import re

            path, words = a.args[0], a.args[1]
            m = re.search(r"\((-?\d+)\)\s*$", a.label or "")
            score = float(m.group(1)) if m else 0.0
            ws = builder.last_words or []
            best = max([ws[0].score if ws else 0, score])
            builder.word_feat(game, c, score, path, words, len(ws), best)
        elif a.kind == "place":
            i, x, y = a.args
            sq = next((t for t in game.encounter.grid.available() if (t.x, t.y) == (x, y)), None)
            rt = game.player.consumables[i]
            if sq is not None and rt is not None:
                builder.place_feat(game, c, rt, sq)
        else:
            builder.static_feat(game, c)
    except Exception:
        pass
    if a.kind in ("submit", "buy", "sell", "sell_buy", "hippo"):  # the kinds the builder measures
        builder._after(game, c, summary(game), light=a.kind != "submit", key=key)
    return c


PROGRESS_KINDS = frozenset({"submit", "skip", "reroll_grid", "place", "leave", "boss", "pin", "michael_pick", "finale",
                            "buy", "hippo", "sell_buy", "reroll_shop", "freeze"})


def same_action(a: Action, b: Action) -> bool:
    """Kind + args (labels differ between policies)."""
    if a.kind != b.kind:
        return False
    if a.kind == "submit":
        return tuple(map(tuple, a.args[0])) == tuple(map(tuple, b.args[0])) and tuple(a.args[1]) == tuple(b.args[1])
    return tuple(a.args) == tuple(b.args)
