"""Human-visible observation of a ``Game``: a global vector plus a set of entity tokens.

Only what the screen (or melmod's export) shows goes in: money, targets, grids, rerolls,
the grid's tiles, owned items with levels / visible counters / order, the rack, shop offers
with prices and freeze flags, frozen stock carried between shops, the current stage's boss
draft (cursed flags), the active boss, Michael's draft, pin levels. Never: RNG state,
future boss drafts, the next grid or restock, the Bucket's hidden queue order.

Tokens (``TOK_*`` types) share one feature layout so one network reads all of them; each
also carries a class id (item / boss vocabulary) for a small learned embedding.

v2 columns are appended after the v1 ones (``model`` loads v1 checkpoints with zero weight
on them): build strength from a probe encounter (``Prober``: fresh grids from an RNG keyed
only by stage / node, greedy words, the build as shown; what ``policy.PowerPolicy`` buys
by) at shops, boss drafts and pin rewards, per boss option at the draft; the previous
encounter's scores; quest rules shared across quests; per-instance colours / tags of items
where they differ from the catalog (Colour Swap, Can of Beans, upgraded pins).
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from cursed_words_solver.sim.game import core as C
from cursed_words_solver.sim.game.features import _counter, _vocab, item_descriptors

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.run import Game

OBS_VERSION = 2
LEGACY_GLOBAL = (208,)   # n_global_features() of older layouts (v1), for model.upgrade_config
LEGACY_TOKEN = (146,)    # n_token_features() of v1

# token types (0 = padding)
TOK_PAD, TOK_STICKER, TOK_STAMP, TOK_PIN, TOK_RACK, TOK_SHOP_STICKER, TOK_SHOP_STAMP, TOK_SHOP_TILE, \
    TOK_FROZEN_STICKER, TOK_FROZEN_STAMP, TOK_BOSS_OPTION, TOK_ACTIVE_BOSS, TOK_MICHAEL_OPTION, TOK_WORD,     TOK_PIN_OFFER, TOK_NESTED = range(16)
N_TOK_TYPES = 16
MAX_TOKENS = 64

RARITIES = ("Common", "Uncommon", "Rare", "Legendary")
LETTERS = "abcdefghijklmnopqrstuvwxyz"

# quest rules shared across quests (``challenges.py`` and where the game checks them)
QUEST_RULES: dict[str, frozenset[str]] = {
    "q_no_stickers": frozenset({"Masochist", "InTheBeginning"}),           # shop offers no stickers
    "q_no_stamps": frozenset({"Antiphilatelist", "InTheBeginning"}),       # shop offers no stamps
    "q_no_restock": frozenset({"DecisionParalysis"}),                      # no restock, sold slots refill
    "q_no_sell": frozenset({"Embargo"}),
    "q_sells_inert": frozenset({"PlayingFavourites"}),                     # only the favourites trigger on sell
    "q_grid_mod": frozenset({"RedLetterDay", "RedPepperDay", "EmptyGrid", "Sudoku", "CallOfTheVoid", "MunchTime",
                             "SupplyAndDemand", "UpAndUp"}),
    "q_word_rule": frozenset({"Chromaphilia", "Chromaphobia", "Cursophobia", "UpAndUp", "SicilianDefense",
                              "Lexographer"}),
    "q_score_rule": frozenset({"TwoWrongs", "Bullseye", "Lexographer", "TheBonesRound", "PlayingFavourites"}),
    "q_encounter_rule": frozenset({"DoNotPassGo", "Embargo", "MunchTime"}),
    "q_shop_rule": frozenset({"Antiphilatelist", "Masochist", "InTheBeginning", "DecisionParalysis", "SecretSanta",
                              "Embargo", "PlayingFavourites"}),
    "q_colour_swap": frozenset({"ColourSwap"}),
    "q_negative_score": frozenset({"TwoWrongs"}),
    "q_exact_target": frozenset({"Bullseye"}),
}

# probe encounters (``Prober``). Cost on full CWEnv episodes (champion, effort 0.05 cheap
# floor, 8 cores busy, 2026-11-11): 2 grids +19.8% run time, 1 grid +6.3%. The value is
# part of the feature's meaning: keep it fixed for a training run.
PROBE_GRIDS = int(os.environ.get("CWS_RL_PROBE_GRIDS", "2"))
PROBE_SEEDS = 1
PROBE_EFFORT = 0.02          # = the teacher's probe search (effort 0.05 at a 0.25 s probe budget)
# Off by default: with one torch thread per worker (as the actors run) probes add +116% (1 grid)
# to +249% (2 grids) run time, and more in look-ahead rollouts (review 2026-11-11). The str_* /
# boss_* columns then stay 0. CWS_RL_PROBES=1 turns them on; keep it fixed for a whole run.
PROBE_PHASES = ("shop", "boss_draft", "pin_reward") if os.environ.get("CWS_RL_PROBES") == "1" else ()


def _lg(x: float) -> float:
    return math.log1p(max(0.0, float(x)))


def _slg(x: float) -> float:
    return math.copysign(math.log1p(abs(float(x))), float(x))


def money_bucket(m: int) -> int:
    """Money rounded down to a half-octave step (0-3 exact, then 4, 6, 8, 12, 16, ...): probes
    run at this money so a restock or a cheap buy reuses the cached probe."""
    m = int(m)
    if m < 4:
        return max(0, m)
    k = 1 << (m.bit_length() - 1)
    return k + k // 2 if m >= k + k // 2 else k


def _ratio_feats(r: float) -> tuple[float, float]:
    """(capped linear, log) encodings of a strength ratio (1 = on pace)."""
    return min(8.0, max(0.0, r)) / 4.0, max(-3.0, min(3.0, math.log(max(r, 0.05)))) / 3.0


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


@lru_cache(maxsize=1)
def _dep_vocab() -> list[str]:
    return [n.split(":", 1)[1] for n in _vocab()["descriptors"] if n.startswith("dep:")]


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
    # v2: instance colours / tags (set only where they differ from the catalog), boss strength
    names += ["inst_changed"] + [f"icol:{t}" for t in v["types"]] + [f"itag:{t}" for t in v["tags"]]
    names += [f"idep:{t}" for t in _dep_vocab()]
    names += ["boss_known", "boss_strength", "boss_log_strength", "boss_target_rel"]
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
    names += [f"crown:{a}" for a in range(9)]   # 9 slots kept for weight compatibility; 8 is never set
    names += [f"char:{c}" for c in v["characters"]]
    names += [f"quest:{q}" for q in v["quests"]]
    names += [f"colour:{t}" for t in v["types"]]
    names += [f"gridtype:{t}" for t in v["types"]] + [f"gridglyph:{g}" for g in v["glyphs"]]
    names += [f"syn:{t}" for t in v["tags"]] + [f"unmet:{t}" for t in v["tags"]]
    # v2: probe strength, previous encounter, quest rules
    names += ["str_known", "str_next", "log_str_next", "str_boss", "log_str_boss", "log_probe_per_grid",
              "probe_grids_next"]
    names += ["last_known", "last_mean_over", "last_max_over", "last_grids_unused", "last_cleared", "last_words",
              "best_word_log", "best_word_over_now"]
    names += list(QUEST_RULES) + ["q_elite", "q_forced_char", "q_start_items", "q_banned_now", "q_banned_any"]
    return {n: i for i, n in enumerate(names)}


def n_global_features() -> int:
    return len(global_columns())


# ------------------------------------------------------------------------- probes


class Prober:
    """Probe encounters for the strength features: ``seeds`` fresh encounters of ``grids``
    grids (RNG keyed by stage / node / seed only, so nothing hidden), the build as shown,
    best word per grid at a fixed deterministic search effort (independent of the caller's
    word search), money rounded by ``money_bucket``. Memoised per build signature (a pure
    function of the visible build, so the cache never changes a value); ``secs`` /
    ``probes`` / ``hits`` count the cost."""

    def __init__(self, cands, *, grids: int = PROBE_GRIDS, seeds: int = PROBE_SEEDS, effort: float = PROBE_EFFORT,
                 bosses: bool = True, cache_cap: int = 20_000) -> None:
        from cursed_words_solver.sim.game.policy import PowerConfig, PowerPolicy

        self.dictionary = getattr(cands, "dictionary", None)
        pc = cands.with_effort(effort, cheap_floor=True)
        # a 0.6 s probe budget keeps the effort as given (Candidates.with_budget)
        self.pol = PowerPolicy(pc, PowerConfig(probe_seeds=seeds, probe_grids=grids, probe_budget=0.6))
        self.grids, self.seeds, self.bosses = grids, seeds, bosses
        self.cache: dict = {}
        self.cache_cap = cache_cap
        self.secs = 0.0
        self.probes = 0
        self.hits = 0

    def _get(self, key, fn):
        hit = self.cache.get(key)
        if hit is not None:
            self.hits += 1
            return hit
        if len(self.cache) >= self.cache_cap:
            self.cache.clear()
        self.probes += 1
        v = self.cache[key] = fn()
        return v

    def _probe(self, game: "Game", stage: int, node, s: int, bosses=None):
        p = game.player
        real = p.money
        p.money = money_bucket(real)   # before the clone: start-of-encounter effects see it too
        try:
            return self.pol._probe_game(game, stage, node, s, bosses)
        finally:
            p.money = real

    def _play(self, g) -> float:
        """Points per grid played (greedy best word)."""
        enc = g.encounter
        pts, k = 0, 0
        for _ in range(min(self.grids, enc.total_grids)):
            if enc.lost or enc.won or enc.remaining_grids <= 0:
                break
            opts = self.pol.probe_cands.words(g, 1)
            k += 1
            if not opts:
                enc.skip()
                continue
            pts += abs(enc.submit(opts[0].path, opts[0].words).score)   # TwoWrongs scores negative
        return pts / max(1, k)

    def rate(self, game: "Game", sig, stage: int, node) -> tuple[float, int]:
        """(points per grid, grids that fight gets) at (stage, node) without boss rules."""
        from cursed_words_solver.sim.game.player import Node

        node = Node.ENCOUNTER_SECOND if node == Node.BOSS else node   # _probe_game plays a boss node so

        def go():
            pp, n = 0.0, 0
            for s in range(self.seeds):
                g = self._probe(game, stage, node, s)
                n = g.encounter.total_grids
                pp += self._play(g)
            return pp / max(1, self.seeds), n

        return self._get((sig, stage, int(node)), go)

    def boss(self, game: "Game", sig, b) -> tuple[float, float]:
        """(strength ratio under that boss's rules, its fight's target), this stage."""
        import copy

        from cursed_words_solver.sim.game.player import Node

        stage = game.player.run.stage

        def go():
            r, tgt = 0.0, 1.0
            for s in range(self.seeds):
                g = self._probe(game, stage, Node.BOSS, s, [copy.deepcopy(b)])
                enc = g.encounter
                tgt = max(1.0, float(enc.total_target))
                r += self._play(g) * enc.total_grids / tgt
            return r / max(1, self.seeds), tgt

        return self._get((sig, stage, "boss", b.game_class, getattr(b, "floor_mod", 0), bool(b.cursed)), go)

    def features(self, game: "Game") -> dict | None:
        from cursed_words_solver.sim.game.player import NUMBER_OF_STAGES, Node
        from cursed_words_solver.sim.game.policy import build_signature, next_encounter_node

        if game.phase not in PROBE_PHASES:
            return None
        t0 = time.perf_counter()
        try:
            p = game.player
            run = p.run
            stage, node = next_encounter_node(game)
            if stage > NUMBER_OF_STAGES:
                return None
            sig = build_signature(game)
            sig = (*sig[:2], money_bucket(p.money), *sig[3:],   # (character, crown, money, pin, ...)
                   run.challenge.game_class if run.challenge is not None else "", tuple(run.available_colours))
            pp, n = self.rate(game, sig, stage, node)
            t_next = max(1.0, float(run.encounter_target(stage, node, p)))
            t_boss = max(1.0, float(run.encounter_target(stage, Node.BOSS, p)))
            out = {"pp": pp, "grids": n, "str_next": pp * n / t_next, "str_boss": pp * n / t_boss, "t_boss": t_boss}
            if self.bosses and game.phase == "boss_draft":
                out["bosses"] = [self.boss(game, sig, b) for b in game.boss_options()]
            return out
        except Exception:
            return None
        finally:
            self.secs += time.perf_counter() - t0


_PROBER: Prober | None = None


def set_probe_cands(cands) -> Prober | None:
    """Probe with ``cands``' dictionary from now on (``CandidateBuilder`` calls this); a
    stand-in without ``with_effort`` (tests) turns the probes off. Reused per dictionary."""
    global _PROBER
    if _PROBER is not None and _PROBER.dictionary is not None and _PROBER.dictionary is getattr(cands, "dictionary", None):
        return _PROBER
    try:
        _PROBER = Prober(cands) if hasattr(cands, "with_effort") else None
    except Exception:
        _PROBER = None
    return _PROBER


def prober() -> Prober | None:
    return _PROBER


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


@lru_cache(maxsize=None)
def _catalog_inst(game_class: str) -> tuple[frozenset, frozenset, frozenset] | None:
    """Catalog (tags, dependency tags, colours as tile types) of a class, as instances start."""
    from cursed_words_solver.sim.game.items import catalog_rows

    row = catalog_rows().get(game_class)
    if row is None:
        return None
    cols = frozenset(C.TYPE_FROM_GAME.get(c, c.lower()) for c in row.get("relevant_colours") or ())
    return frozenset(row.get("tags") or ()), frozenset(row.get("dependency_tags") or ()), cols


def _instance(tk: _Tokens, f: np.ndarray, it) -> None:
    cat = _catalog_inst(it.game_class)
    if cat is None:
        return
    tags, deps, cols = frozenset(it.tags), frozenset(it.dependency_tags), frozenset(it.relevant_colours)
    if (tags, deps, cols) == cat:
        return
    put = tk.put
    put(f, "inst_changed", 1.0)
    for c in cols:
        put(f, f"icol:{c}", 1.0)
    for t in tags:
        put(f, f"itag:{t}", 1.0)
    for t in deps:
        put(f, f"idep:{t}", 1.0)


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
    try:
        _instance(tk, f, it)
    except Exception:
        pass


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


def _boss_token(tk: _Tokens, ttype: int, b, ref, floor: int, strength: tuple[float, float, float] | None = None) -> None:
    f = tk.add(ttype, f"boss:{b.game_class}", ref)
    if f is None:
        return
    tk.put(f, "boss_cursed", float(bool(b.cursed)))
    tk.put(f, "boss_mod", float(getattr(b, "floor_mod", 0) or 0) / 10.0)
    tk.put(f, "boss_floor", floor / 5.0)
    if strength is not None:
        r, tgt, t_plain = strength
        lin, lg = _ratio_feats(r)
        tk.put(f, "boss_known", 1.0)
        tk.put(f, "boss_strength", lin)
        tk.put(f, "boss_log_strength", lg)
        tk.put(f, "boss_target_rel", max(-3.0, min(3.0, math.log(tgt / max(1.0, t_plain)))))


def build_tokens(game: "Game", probe: dict | None = None) -> _Tokens:
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
        strengths = (probe or {}).get("bosses") or ()
        t_plain = (probe or {}).get("t_boss", 1.0)
        for i, b in enumerate(run.boss_drafts[run.stage - 1].options):
            st = (*strengths[i], t_plain) if i < len(strengths) else None
            _boss_token(tk, TOK_BOSS_OPTION, b, ("boss", i), run.stage, st)
    for i, b in enumerate(p.active_bosses or ()):
        _boss_token(tk, TOK_ACTIVE_BOSS, b, ("active_boss", i), run.stage)
    enc = game.encounter
    if enc is not None and enc.michael_draft is not None:
        for i, b in enumerate(enc.michael_draft):
            _boss_token(tk, TOK_MICHAEL_OPTION, b, ("michael", i), run.stage)
    return tk


def _last_encounter(game: "Game") -> dict | None:
    """Scores of the last finished encounter, from the visible word history (a new
    encounter starts where the grid count restarts or the previous word cleared)."""
    from cursed_words_solver.sim.game.player import GRIDS_PER_ROUND

    run = game.player.run
    words = list(run.stats.words_submitted)
    if not words:
        return None
    best = max(abs(w.score) for w in words)
    enc = game.encounter
    if enc is not None:
        cur = sum(1 for w in enc.previous_words if not w.skipped)
        words = words[: len(words) - cur] if cur else words
    out = {"best": best}
    if not words:
        return out
    start = 0
    for i in range(1, len(words)):
        a, b = words[i - 1], words[i]
        if b.submitted_round <= a.submitted_round or a.remainder <= 0:
            start = i
    grp = words[start:]
    target = grp[0].score + grp[0].remainder
    if target <= 0:
        return out
    nominal = GRIDS_PER_ROUND - (1 if run.asc(7) else 0)
    per = target / nominal
    scores = [abs(w.score) for w in grp]
    out.update(mean=sum(scores) / len(scores) / per, max=max(scores) / per,
               unused=max(0, nominal - grp[-1].submitted_round), cleared=grp[-1].remainder <= 0, n=len(grp))
    return out


def build_global(game: "Game", *, best: float = 0.0, second: float = 0.0, n_words: int = 0,
                 phase_steps: int = 0, shop_actions: int = 0, probe: dict | None = None) -> np.ndarray:
    from cursed_words_solver.sim.game.player import ENCOUNTER_NODES, GRIDS_PER_ROUND, MICHAEL_STAGE, NUMBER_OF_STAGES, Node

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
    # ---- v2
    if probe:
        put("str_known", 1.0)
        for k in ("next", "boss"):
            lin, lg = _ratio_feats(probe[f"str_{k}"])
            put(f"str_{k}", lin)
            put(f"log_str_{k}", lg)
        put("log_probe_per_grid", _lg(probe["pp"]) / 10)
        put("probe_grids_next", probe["grids"] / 5.0)
    try:
        last = _last_encounter(game)
    except Exception:
        last = None
    if last:
        put("best_word_log", _lg(last["best"]) / 10)
        put("best_word_over_now", min(8.0, last["best"] / max(1.0, t_now / GRIDS_PER_ROUND)) / 4.0)
        if "mean" in last:
            put("last_known", 1.0)
            put("last_mean_over", min(8.0, last["mean"]) / 4.0)
            put("last_max_over", min(8.0, last["max"]) / 4.0)
            put("last_grids_unused", last["unused"] / 5.0)
            put("last_cleared", float(last["cleared"]))
            put("last_words", last["n"] / 5.0)
    ch = run.challenge
    if ch is not None:
        for name, quests in QUEST_RULES.items():
            if ch.game_class in quests:
                put(name, 1.0)
        put("q_elite", float(bool(ch.elite)))
        put("q_forced_char", float(ch.character is not None))
        put("q_start_items", len(ch.starting_items) / 3.0)
        put("q_banned_now", len(ch.banned_bosses.get(stage - 1, ())) / 5.0)
        put("q_banned_any", float(bool(ch.banned_bosses)))
    return x


def observe(game: "Game", *, probe: bool = True, **kw) -> Obs:
    """``probe``: add the probe-strength features (shop / boss draft / pin reward) when a
    ``Prober`` is set (``set_probe_cands``); otherwise those columns stay zero."""
    pr = _PROBER.features(game) if probe and _PROBER is not None else None
    tk = build_tokens(game, pr)
    F = tk.F
    T = len(tk.types)
    feat = np.stack(tk.feats) if T else np.zeros((0, F), dtype=np.float32)
    return Obs(glob=build_global(game, probe=pr, **kw), tok_type=np.asarray(tk.types, dtype=np.int64),
               tok_cls=np.asarray(tk.cls, dtype=np.int64), tok_feat=feat, refs=tk.refs)
