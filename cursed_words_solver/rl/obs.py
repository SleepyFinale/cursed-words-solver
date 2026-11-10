"""Human-visible observation of a ``Game``: a global vector plus a set of entity tokens.

Only what the screen (or melmod's export) shows goes in: money, targets, grids, rerolls,
the grid's tiles, owned items with levels / visible counters / order, the rack, shop offers
with prices and freeze flags, frozen stock carried between shops, the current stage's boss
draft (cursed flags), the active boss, Michael's draft, pin levels. Never: RNG state,
future boss drafts, the next grid or restock, the Bucket's hidden queue order.

Tokens (``TOK_*`` types) share one feature layout so one network reads all of them; each
also carries a class id (item / boss vocabulary) for a small learned embedding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from cursed_words_solver.sim.game import core as C
from cursed_words_solver.sim.game.features import _counter, _vocab, item_descriptors

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.run import Game

OBS_VERSION = 1

# token types (0 = padding)
TOK_PAD, TOK_STICKER, TOK_STAMP, TOK_PIN, TOK_RACK, TOK_SHOP_STICKER, TOK_SHOP_STAMP, TOK_SHOP_TILE, \
    TOK_FROZEN_STICKER, TOK_FROZEN_STAMP, TOK_BOSS_OPTION, TOK_ACTIVE_BOSS, TOK_MICHAEL_OPTION, TOK_WORD,     TOK_PIN_OFFER, TOK_NESTED = range(16)
N_TOK_TYPES = 16
MAX_TOKENS = 64

RARITIES = ("Common", "Uncommon", "Rare", "Legendary")
LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _lg(x: float) -> float:
    return math.log1p(max(0.0, float(x)))


def _slg(x: float) -> float:
    return math.copysign(math.log1p(abs(float(x))), float(x))


@lru_cache(maxsize=1)
def class_vocab() -> dict[str, int]:
    """Item classes then boss classes; 0 is 'none' (tiles, words)."""
    v = _vocab()
    out = {"": 0}
    for c in v["items"]:
        out[c] = len(out)
    for b in v["bosses"]:
        out[f"boss:{b}"] = len(out)
    return out


# ------------------------------------------------------------------------- token layout


@lru_cache(maxsize=1)
def token_columns() -> dict[str, int]:
    v = _vocab()
    _, D = item_descriptors()
    names = [f"d{i}" for i in range(D.shape[1])]
    names += ["level", "level2", "foil", "slot", "var", "var2", "counter", "sell_value", "cost", "affordable",
              "frozen", "free", "first_discount", "invested", "times_upgraded", "hb_fav", "no_sell"]
    names += [f"rarity:{r}" for r in RARITIES]
    names += [f"glyph:{g}" for g in v["glyphs"]] + [f"ttype:{t}" for t in v["types"]]
    names += [f"letter:{c}" for c in LETTERS] + ["tile_value", "tile_cursed", "tile_ncurse", "tile_price"]
    names += ["boss_cursed", "boss_mod", "boss_floor"]
    return {n: i for i, n in enumerate(names)}


def n_token_features() -> int:
    return len(token_columns())


# ------------------------------------------------------------------------- global layout


@lru_cache(maxsize=1)
def global_columns() -> dict[str, int]:
    v = _vocab()
    names = ["stage", "crown", "log_money", "money_over_target", "log_target_now", "log_target_boss",
             "log_boss_next_rel", "log_boss_after_rel", "log_final_rel", "stages_left",
             "in_encounter", "grids_left", "total_grids", "grid_index", "first_grid", "rerolls", "can_reroll",
             "remaining_frac", "log_remaining", "log_need_per_grid", "best_over_remaining", "best_over_per_grid",
             "second_over_best", "n_words", "boss_encounter", "michael_encounter", "forced_sell",
             "pin_l", "pin_r", "pin_lv", "pin_rv", "has_pin", "n_stickers", "n_stamps", "n_rack",
             "free_sticker_slots", "free_stamp_slots", "log_sell_value", "has_generator",
             "michael_route", "cursed_defeated", "cursed_needed", "uncursed_faced",
             "shop_restock_cost", "shop_can_restock", "shop_angel", "shop_free_item", "shop_meg",
             "shop_actions", "phase_steps", "log_piggy_bank", "has_quest",
             "grid_cursed", "grid_ncurse_types", "grid_mean_value", "grid_tiles", "n_frozen", "id_card"]
    names += [f"phase:{p}" for p in ("encounter", "shop", "boss_draft", "pin_reward", "michael_draft")]
    names += [f"node:{n}" for n in v["nodes"]]
    names += [f"crown:{a}" for a in range(9)]
    names += [f"char:{c}" for c in v["characters"]]
    names += [f"quest:{q}" for q in v["quests"]]
    names += [f"colour:{t}" for t in v["types"]]
    names += [f"gridtype:{t}" for t in v["types"]] + [f"gridglyph:{g}" for g in v["glyphs"]]
    names += [f"syn:{t}" for t in v["tags"]] + [f"unmet:{t}" for t in v["tags"]]
    return {n: i for i, n in enumerate(names)}


def n_global_features() -> int:
    return len(global_columns())


# ------------------------------------------------------------------------- observation


@dataclass
class Obs:
    glob: np.ndarray          # (G,)
    tok_type: np.ndarray      # (T,) int64
    tok_cls: np.ndarray       # (T,) int64
    tok_feat: np.ndarray      # (T, F)
    refs: dict                # (kind, key) -> token index, for action references


class _Tokens:
    def __init__(self) -> None:
        self.types: list[int] = []
        self.cls: list[int] = []
        self.feats: list[np.ndarray] = []
        self.refs: dict = {}
        self.col = token_columns()
        self.F = len(self.col)

    def add(self, ttype: int, cls_name: str, ref=None) -> np.ndarray | None:
        if len(self.types) >= MAX_TOKENS:
            return None
        f = np.zeros(self.F, dtype=np.float32)
        self.types.append(ttype)
        self.cls.append(class_vocab().get(cls_name, 0))
        self.feats.append(f)
        if ref is not None:
            self.refs[ref] = len(self.types) - 1
        return f

    def put(self, f: np.ndarray, name: str, value: float) -> None:
        i = self.col.get(name)
        if i is not None:
            f[i] = value


def _item_token(tk: _Tokens, ttype: int, it, p, ref, *, slot: int = -1, cost: float | None = None,
                stock=None) -> None:
    f = tk.add(ttype, it.game_class, ref)
    if f is None:
        return
    rows, D = item_descriptors()
    r = rows.get(it.game_class)
    if r is not None:
        f[: D.shape[1]] = D[r]
    put = tk.put
    if it.components:
        put(f, "level", it.level(0))
        put(f, "var", _slg(it.var(0)))
        if len(it.components) > 1:
            put(f, "level2", it.level(1))
            put(f, "var2", _slg(it.var(1)))
    put(f, "foil", float(it.is_foil))
    if slot >= 0:
        put(f, "slot", (slot + 1) / 5.0)
    ctr = _counter(it.fields)
    if ctr:
        put(f, "counter", math.log1p(ctr))
    try:
        put(f, "sell_value", _slg(it.sell_value(p)))
    except Exception:
        pass
    put(f, "invested", _lg(sum(it.money_invested)))
    put(f, "times_upgraded", it.times_upgraded / 3.0)
    put(f, "hb_fav", float(it.is_hb_favourite_sticker))
    put(f, "no_sell", float(it.selling_prevented))
    if it.rarity in RARITIES:
        put(f, f"rarity:{it.rarity}", 1.0)
    if cost is not None:
        put(f, "cost", _lg(cost))
        put(f, "affordable", float(p.money >= cost))
    if stock is not None:
        put(f, "frozen", float(bool(stock.frozen)))
        put(f, "free", float(bool(stock.free)))
        put(f, "first_discount", float(bool(stock.first_discount)))


def _tile_token(tk: _Tokens, ttype: int, t, p, ref, price: float | None = None) -> None:
    f = tk.add(ttype, "", ref)
    if f is None:
        return
    put = tk.put
    put(f, f"glyph:{t.glyph}", 1.0)
    put(f, f"ttype:{t.tile_type}", 1.0)
    letter = (t.letter or "").lower()
    if len(letter) == 1 and letter in LETTERS:
        put(f, f"letter:{letter}", 1.0)
    try:
        put(f, "tile_value", t.get_value(p) / 10.0)
        put(f, "tile_cursed", float(t.is_cursed(p)))
        put(f, "tile_ncurse", float(len(t.curse_types(p))))
    except Exception:
        pass
    if price is not None:
        put(f, "tile_price", price / 5.0)
        put(f, "affordable", float(p.money >= price))
    if t.item is not None:
        put(f, "level", t.item.level(0) if t.item.components else 1)


def _boss_token(tk: _Tokens, ttype: int, b, ref, floor: int) -> None:
    f = tk.add(ttype, f"boss:{b.game_class}", ref)
    if f is None:
        return
    tk.put(f, "boss_cursed", float(bool(b.cursed)))
    tk.put(f, "boss_mod", float(getattr(b, "floor_mod", 0) or 0) / 10.0)
    tk.put(f, "boss_floor", floor / 5.0)


def build_tokens(game: "Game") -> _Tokens:
    p = game.player
    run = p.run
    tk = _Tokens()
    for k, it in enumerate(p.stickers):
        if it is not None:
            _item_token(tk, TOK_STICKER, it, p, ("sticker", k), slot=k)
    for k, it in enumerate(p.stamps):
        if it is not None:
            _item_token(tk, TOK_STAMP, it, p, ("stamp", k), slot=k)
    if p.pin is not None:
        _item_token(tk, TOK_PIN, p.pin, p, ("pin", 0))
        # Random Access Memory / Bucket: what each side adds is shown before choosing;
        # what they already hold is part of the build.
        for i, it in enumerate(getattr(p.pin, "next_items", None) or ()):
            if it is not None:
                _item_token(tk, TOK_PIN_OFFER, it, p, ("pin_offer", i))
        for i, t in enumerate(getattr(p.pin, "next_tiles", None) or ()):
            if t is not None:
                _tile_token(tk, TOK_PIN_OFFER, t, p, ("pin_offer", i))
        for it in getattr(p.pin, "memory", None) or ():
            _item_token(tk, TOK_NESTED, it, p, None)
        for t in getattr(p.pin, "tiles_in_bucket", None) or ():
            _tile_token(tk, TOK_NESTED, t, p, None)
    for k, t in enumerate(p.consumables):
        if t is not None:
            _tile_token(tk, TOK_RACK, t, p, ("rack", k))
    s = game.shop if game.phase == "shop" else None
    if s is not None:
        for k, o in enumerate(s.stickers):
            if o is not None:
                _item_token(tk, TOK_SHOP_STICKER, o.item, p, ("shop_sticker", k), cost=s.offer_cost(o), stock=o)
        for k, o in enumerate(s.stamps):
            if o is not None:
                _item_token(tk, TOK_SHOP_STAMP, o.item, p, ("shop_stamp", k), cost=s.offer_cost(o), stock=o)
        for k, o in enumerate(s.tiles):
            if o is not None and not o.bought:
                _tile_token(tk, TOK_SHOP_TILE, o.tile, p, ("shop_tile", k), price=o.get_price(p))
    else:
        for kind, arr, ttype in (("frozen_sticker", p.frozen_stickers, TOK_FROZEN_STICKER),
                                 ("frozen_stamp", p.frozen_stamps, TOK_FROZEN_STAMP)):
            for k, o in enumerate(arr):
                if o is not None:
                    _item_token(tk, ttype, o.item, p, (kind, k), cost=getattr(o, "cost", None), stock=o)
    if 0 < run.stage <= len(run.boss_drafts) and game.phase in ("encounter", "shop", "boss_draft"):
        for i, b in enumerate(run.boss_drafts[run.stage - 1].options):
            _boss_token(tk, TOK_BOSS_OPTION, b, ("boss", i), run.stage)
    for i, b in enumerate(p.active_bosses or ()):
        _boss_token(tk, TOK_ACTIVE_BOSS, b, ("active_boss", i), run.stage)
    enc = game.encounter
    if enc is not None and enc.michael_draft is not None:
        for i, b in enumerate(enc.michael_draft):
            _boss_token(tk, TOK_MICHAEL_OPTION, b, ("michael", i), run.stage)
    return tk


def build_global(game: "Game", *, best: float = 0.0, second: float = 0.0, n_words: int = 0,
                 phase_steps: int = 0, shop_actions: int = 0) -> np.ndarray:
    from cursed_words_solver.sim.game.player import ENCOUNTER_NODES, MICHAEL_STAGE, NUMBER_OF_STAGES, Node

    col = global_columns()
    x = np.zeros(len(col), dtype=np.float32)

    def put(name: str, value: float) -> None:
        i = col.get(name)
        if i is not None:
            x[i] = value

    p = game.player
    run = p.run
    stage = max(1, run.stage)
    node = run.node if run.node in ENCOUNTER_NODES else Node.ENCOUNTER_FIRST
    try:
        t_now = float(run.encounter_target(stage, node, p))
        t_boss = float(run.encounter_target(stage, Node.BOSS, p))
    except Exception:
        t_now = t_boss = 1.0
    put("stage", stage / 6.0)
    put("crown", run.ascension / 8.0)
    put(f"crown:{min(8, max(0, run.ascension))}", 1.0)
    put("log_money", _lg(p.money))
    put("money_over_target", min(5.0, p.money / max(1.0, t_now) * 10))
    put("log_target_now", _lg(t_now) / 10)
    put("log_target_boss", _lg(t_boss) / 10)
    for name, st in (("log_boss_next_rel", stage + 1), ("log_boss_after_rel", stage + 2), ("log_final_rel", NUMBER_OF_STAGES)):
        try:
            put(name, (_lg(run.encounter_target(min(st, MICHAEL_STAGE), Node.BOSS, p)) - _lg(t_now)))
        except Exception:
            pass
    put("stages_left", max(0, NUMBER_OF_STAGES - stage) / 5.0)
    ph = game.phase
    enc = game.encounter
    if ph == "encounter" and enc is not None and enc.michael_draft is not None:
        put("phase:michael_draft", 1.0)
    elif ph in ("encounter", "shop", "boss_draft", "pin_reward"):
        put(f"phase:{ph}", 1.0)
    put(f"node:{run.node.name}", 1.0)
    if enc is not None:
        put("in_encounter", 1.0)
        put("grids_left", enc.remaining_grids / 5.0)
        put("total_grids", enc.total_grids / 5.0)
        idx = enc.total_grids - enc.remaining_grids
        put("grid_index", idx / 5.0)
        put("first_grid", float(idx == 0))
        put("rerolls", float(enc.rerolls))
        try:
            put("can_reroll", float(enc.can_reroll()))
        except Exception:
            pass
        tot = max(1.0, float(enc.total_target or 1))
        rem = max(0.0, float(enc.remaining_target))
        put("remaining_frac", rem / tot)
        put("log_remaining", _lg(rem) / 10)
        per = rem / max(1, enc.remaining_grids)
        put("log_need_per_grid", _lg(per) / 10)
        put("best_over_remaining", min(4.0, best / max(1.0, rem)))
        put("best_over_per_grid", min(8.0, best / max(1.0, per)))
        put("second_over_best", second / best if best > 0 else 0.0)
        put("n_words", n_words / 8.0)
        put("boss_encounter", float(bool(enc.bosses)))
        put("michael_encounter", float(enc.michael is not None))
        put("forced_sell", float(bool(enc.awaiting_forced_sell)))
        tiles = [t for t in enc.grid.available()] if enc.grid is not None else []
        if tiles:
            put("grid_tiles", len(tiles) / 25.0)
            cur = 0
            kinds: set = set()
            val = 0.0
            for t in tiles:
                try:
                    ct = t.curse_types(p)
                    val += t.get_value(p)
                except Exception:
                    ct = []
                if ct:
                    cur += 1
                    kinds.update(ct)
                i = col.get(f"gridtype:{t.tile_type}")
                if i is not None:
                    x[i] += 1.0 / 25
                j = col.get(f"gridglyph:{t.glyph}")
                if j is not None:
                    x[j] += 1.0 / 25
            put("grid_cursed", cur / 25.0)
            put("grid_ncurse_types", len(kinds) / 4.0)
            put("grid_mean_value", val / len(tiles) / 10.0)
    if p.pin is not None and len(p.pin.components) == 2:
        put("has_pin", 1.0)
        put("pin_l", p.pin.level(0) / 5.0)
        put("pin_r", p.pin.level(1) / 5.0)
        put("pin_lv", _slg(p.pin.var(0)) / 5)
        put("pin_rv", _slg(p.pin.var(1)) / 5)
    put("id_card", float(bool(p.unpacked_of("IDCard"))))
    put("n_stickers", sum(s is not None for s in p.stickers) / 5.0)
    put("n_stamps", sum(s is not None for s in p.stamps) / 5.0)
    put("n_rack", sum(t is not None for t in p.consumables) / 10.0)
    put("free_sticker_slots", sum(s is None for s in p.stickers) / 5.0)
    put("free_stamp_slots", sum(s is None for s in p.stamps) / 5.0)
    owned = [it for it in list(p.stickers) + list(p.stamps) if it is not None]
    try:
        put("log_sell_value", _lg(sum(max(0, it.sell_value(p)) for it in owned)))
    except Exception:
        pass
    try:
        put("has_generator", float(p.has_generator()))
    except Exception:
        pass
    route = run.ascension >= 1 and not p.has_faced_uncursed_boss
    put("michael_route", float(route))
    put("cursed_defeated", len(run.cursed_bosses_defeated) / 5.0)
    put("cursed_needed", max(0, NUMBER_OF_STAGES - len(run.cursed_bosses_defeated)) / 5.0 if route else 0.0)
    put("uncursed_faced", float(p.has_faced_uncursed_boss))
    s = game.shop
    if s is not None and ph == "shop":
        put("shop_restock_cost", s.reroll_cost / 10.0)
        put("shop_can_restock", float(s.can_reroll()))
        put("shop_angel", float(s.angel_available()))
        put("shop_free_item", float(bool(s.free_item_active)))
        put("shop_meg", float(bool(s.is_meg)))
    put("shop_actions", min(1.0, shop_actions / 20.0))
    put("phase_steps", min(1.0, phase_steps / 20.0))
    put("log_piggy_bank", _lg(p.piggy_bank))
    put("has_quest", float(run.challenge is not None))
    if run.challenge is not None:
        put(f"quest:{run.challenge.game_class}", 1.0)
    put(f"char:{p.character}", 1.0)
    for c in run.available_colours:
        put(f"colour:{c}", 1.0)
    put("n_frozen", sum(o is not None for o in list(p.frozen_stickers) + list(p.frozen_stamps)) / 4.0)
    try:
        for r, t in enumerate(p.ordered_build_synergy_tags()):
            put(f"syn:{t}", 1.0 / (r + 1))
        for t in p.unfulfilled_dependency_tags():
            put(f"unmet:{t}", 1.0)
    except Exception:
        pass
    return x


def observe(game: "Game", **kw) -> Obs:
    tk = build_tokens(game)
    F = tk.F
    T = len(tk.types)
    feat = np.stack(tk.feats) if T else np.zeros((0, F), dtype=np.float32)
    return Obs(glob=build_global(game, **kw), tok_type=np.asarray(tk.types, dtype=np.int64),
               tok_cls=np.asarray(tk.cls, dtype=np.int64), tok_feat=feat, refs=tk.refs)
