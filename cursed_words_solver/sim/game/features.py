"""State → fixed-size feature vector for learned value / policy models.

Layout (all float32):

- run position: stage, node one-hot, crown, quest one-hot, character one-hot
- economy: money (log), targets ahead (log), grids / rerolls of the current encounter
- inventory: per item class a level-weighted slot (sticker level, 1 for stamps, foil flag
  folded in), pin levels / values, rack tile glyph + colour counts
- upcoming bosses: current floor's options one-hot by class (+ cursed / floor mod)
- form: points per grid over the last encounter vs the next target (cheap power proxy)
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from cursed_words_solver.sim.game import core as C
from cursed_words_solver.sim.game.challenges import QUESTS
from cursed_words_solver.sim.game.items import catalog_rows
from cursed_words_solver.sim.game.player import ENCOUNTER_NODES, Node, boss_rows, character_rows

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.run import Game


@lru_cache(maxsize=1)
def _vocab() -> dict[str, list[str]]:
    return {
        "items": sorted(catalog_rows()),
        "bosses": sorted(boss_rows()),
        "characters": sorted(character_rows()),
        "quests": sorted(QUESTS),
        "nodes": [n.name for n in Node],
        "glyphs": [C.G_LETTER, C.G_BLANK, C.G_NUMBER, C.G_FRACTION, C.G_CHESS, C.G_CARD, C.G_CURRENCY, C.G_ARROW, C.G_ITEM],
        "types": list(C.ALL_TILE_TYPES),
    }


@lru_cache(maxsize=1)
def feature_names() -> list[str]:
    v = _vocab()
    names = ["stage", "crown", "log_money", "money_over_target", "log_target_now", "log_target_boss",
             "grids_left", "rerolls", "remaining_frac", "form_ratio", "pin_l", "pin_r", "pin_lv", "pin_rv",
             "n_stickers", "n_stamps", "n_tiles", "uncursed_faced", "cursed_defeated", "has_challenge"]
    names += [f"node:{n}" for n in v["nodes"]]
    names += [f"char:{c}" for c in v["characters"]]
    names += [f"quest:{q}" for q in v["quests"]]
    names += [f"item:{i}" for i in v["items"]]
    names += [f"foil:{i}" for i in v["items"]]
    names += [f"boss:{b}" for b in v["bosses"]]
    names += ["boss_cursed_any", "boss_mod_mean"]
    names += [f"rack_glyph:{g}" for g in v["glyphs"]]
    names += [f"rack_type:{t}" for t in v["types"]]
    names += [f"colour:{t}" for t in v["types"]]
    # v2 (appended so older datasets pad with zeros): frozen shop stock, piggy bank.
    names += ["frozen_n", "log_piggy_bank"]
    names += [f"frozen:{i}" for i in v["items"]]
    # v3: Octacles' Bucket contents (the pin reward offers a tile per side; RAM's offered
    # items already show up as item:* counts).
    names += [f"bucket:{g}" for g in v["glyphs"]] + ["bucket_suited", "bucket_joker"]
    return names


def _lg(x: float) -> float:
    return math.log1p(max(0.0, float(x)))


def encode(game: "Game", *, form_ratio: float = 0.0) -> np.ndarray:
    v = _vocab()
    names = feature_names()
    idx = {n: i for i, n in enumerate(names)}
    x = np.zeros(len(names), dtype=np.float32)
    p = game.player
    run = p.run

    def put(name: str, value: float) -> None:
        i = idx.get(name)
        if i is not None:
            x[i] = value

    stage = max(1, run.stage)
    node = run.node if run.node in ENCOUNTER_NODES else Node.ENCOUNTER_FIRST
    try:
        t_now = run.encounter_target(stage, node, p)
        t_boss = run.encounter_target(stage, Node.BOSS, p)
    except Exception:
        t_now = t_boss = 1
    put("stage", stage)
    put("crown", run.ascension)
    put("log_money", _lg(p.money))
    put("money_over_target", p.money / max(1.0, float(t_now)))
    put("log_target_now", _lg(t_now))
    put("log_target_boss", _lg(t_boss))
    enc = game.encounter
    if enc is not None:
        put("grids_left", enc.remaining_grids)
        put("rerolls", enc.rerolls)
        put("remaining_frac", enc.remaining_target / max(1.0, float(enc.total_target or 1)))
    put("form_ratio", form_ratio)
    if p.pin is not None and len(p.pin.components) == 2:
        put("pin_l", p.pin.level(0))
        put("pin_r", p.pin.level(1))
        put("pin_lv", _lg(p.pin.var(0)))
        put("pin_rv", _lg(p.pin.var(1)))
    put("n_stickers", len(p.stickers_list(for_comparison=True)))
    put("n_stamps", len(p.stamps_list(for_comparison=True)))
    put("n_tiles", len(p.tiles()))
    put("uncursed_faced", float(p.has_faced_uncursed_boss))
    put("cursed_defeated", len(run.cursed_bosses_defeated))
    put("has_challenge", float(run.challenge is not None))
    put(f"node:{run.node.name}", 1.0)
    put(f"char:{p.character}", 1.0)
    if run.challenge is not None:
        put(f"quest:{run.challenge.game_class}", 1.0)
    for it in p.all_items_including_nested(for_comparison=True):
        if it is p.pin:
            continue
        lvl = it.level(0) if it.components else 1
        i = idx.get(f"item:{it.game_class}")
        if i is not None:
            x[i] += lvl
        if it.is_foil:
            put(f"foil:{it.game_class}", 1.0)
    if 0 < run.stage <= len(run.boss_drafts):
        opts = run.boss_drafts[run.stage - 1].options
        for b in opts:
            put(f"boss:{b.game_class}", 1.0)
        put("boss_cursed_any", float(any(b.cursed for b in opts)))
        put("boss_mod_mean", float(np.mean([b.floor_mod for b in opts])) if opts else 0.0)
    for t in p.tiles():
        i = idx.get(f"rack_glyph:{t.glyph}")
        if i is not None:
            x[i] += 1
        j = idx.get(f"rack_type:{t.tile_type}")
        if j is not None:
            x[j] += 1
    for c in run.available_colours:
        put(f"colour:{c}", 1.0)
    frozen = [f for f in list(p.frozen_stickers) + list(p.frozen_stamps) if f is not None]
    put("frozen_n", len(frozen))
    put("log_piggy_bank", _lg(p.piggy_bank))
    for f in frozen:
        i = idx.get(f"frozen:{f.item.game_class}")
        if i is not None:
            x[i] += 1
    for t in getattr(p.pin, "tiles_in_bucket", None) or ():
        i = idx.get(f"bucket:{t.get_glyph()}")
        if i is not None:
            x[i] += 1
        x[idx["bucket_suited"]] += float(t.is_suited_card())
        x[idx["bucket_joker"]] += float(t.suit == C.SUIT_JOKER)
    return x


# Extra outcome for beating Michael on top of a run win (16): a full win is worth 1.5 plain
# wins, so the AI weighs chasing him (every boss cursed) against a safe stage-5 win.
# Losing to Michael is still a run win ("michael_lost": the crown was beaten at stage 5).
MICHAEL_BONUS = 8.0


def progress(game: "Game") -> float:
    """Training target: encounters cleared (15 for a stage-5 win, + ``MICHAEL_BONUS`` for Michael)."""
    run = game.player.run
    order = {Node.ENCOUNTER_FIRST: 0, Node.SHOP_ONE: 1, Node.ENCOUNTER_SECOND: 1, Node.SHOP_TWO: 2,
             Node.BOSS_DRAFT: 2, Node.MEG_SHOP: 2, Node.BOSS: 2, Node.BOSS_REWARD: 3, Node.SHOP_ZERO: 0}
    base = (max(1, run.stage) - 1) * 3 + order.get(run.node, 0)
    if game.won:
        return 15.0 + (MICHAEL_BONUS if game.end_reason == "michael" else 0.0)
    return float(base)


def outcome(game: "Game") -> float:
    """Final-run label: ``progress`` plus the share of the target reached in the encounter
    that ended the run (a near miss scores more than a rout); a win scores 16, beating
    Michael 16 + ``MICHAEL_BONUS``."""
    if game.won:
        return 16.0 + (MICHAEL_BONUS if game.end_reason == "michael" else 0.0)
    base = progress(game)
    enc = game.encounter
    if game.won is False and enc is not None and enc.total_target > 0:
        base += max(0.0, min(1.0, 1.0 - enc.remaining_target / enc.total_target))
    return base
