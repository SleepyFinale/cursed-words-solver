"""Fast-path caches and ``items.FAST_HOOKS`` vs the reference port (``_score_ref``).

Targets the per-plan pieces of ``calc._score_fast`` directly: the hot-hook rewrites
(Dusty Coffin / Fire Extinguisher / Yellow Glasses / Maple Leaf), scattered path items
resolved once per tile, the cached non-chess selections, the Ctx template and the
last-slot-order identity check (including in-place slot swaps). Every ``EngineResult``
must be bit-identical (score and type, every step, nondeterministic flag, final states).
"""

from __future__ import annotations

import json
import random

import pytest

from cursed_words_solver.engine import calc as C
from cursed_words_solver.engine import items as I
from cursed_words_solver.engine.calc import EnginePlan
from cursed_words_solver.engine.item_data import ITEMS
from cursed_words_solver.models import CurseType, Loadout, Tile, TileColor

from tests.engine.test_engine_units import _board

HOT = ("dusty_coffin", "fire_extinguisher", "yellow_glasses", "maple_leaf")


def _key(res) -> str:
    return repr((res.score, type(res.score).__name__, res.steps, res.nondeterministic, res.final_states))


@pytest.fixture(autouse=True)
def _restore_fastcalc():
    yield
    C.use_fastcalc(C.FASTCALC)


def _row(slug, value, colour=None):
    info = ITEMS[slug]
    row = {"id": slug, "levels": [2 for _ in info.components], "values": [value for _ in info.components],
           "fields": {}}
    if colour:
        row["colours"] = [colour]
    return row


_COLOURS = {(0, 0): TileColor.RED, (0, 2): TileColor.BLUE, (1, 1): TileColor.PURPLE, (1, 3): TileColor.VOID,
            (2, 0): TileColor.VOID, (2, 4): TileColor.RED, (3, 2): TileColor.RED, (3, 3): TileColor.BLUE,
            (4, 1): TileColor.VOID, (4, 4): TileColor.PURPLE, (0, 4): TileColor.RED}
# Scattered path items: the hot hooks, a no-hook item, a stateful (cloned) item, Scissors.
_SCATTER = {(1, 2): ("maple_leaf", 2), (2, 2): ("dusty_coffin", 1), (3, 0): ("fire_extinguisher", 3),
            (4, 3): ("yellow_glasses", 1), (0, 1): ("cable_car", 1), (3, 4): ("ruler", 2), (1, 0): ("scissors", 1),
            # On-path Red Envelope makes red letters wobbly (path-dependent selections).
            (2, 1): ("red_envelope", 1)}


def _hot_board():
    # Repeated letters (Yellow Glasses), every colour the hooks read.
    b = _board(["assel", "tteoo", "ellas", "booke", "mmaae"], _COLOURS)
    for (r, c), (slug, lvl) in _SCATTER.items():
        b.tiles[r][c] = Tile(r, c, "?", "?", 0.0, color=_COLOURS.get((r, c), TileColor.COLORLESS), curse=CurseType.ITEM,
                             metadata={"source": "melmod", "scattered_item_id": slug, "scattered_item_level": lvl})
    return b


def _paths(rng, n):
    out = [[a, b] for a in range(25) for b in range(25) if a != b][::3]
    for _ in range(n):
        out.append(rng.sample(range(25), rng.randint(1, 9)))
    return out


def _compare(plan, paths, word=""):
    for path in paths:
        C.use_fastcalc(False)
        a = plan.score(list(path), word)
        C.use_fastcalc(True)
        b = plan.score(list(path), word)
        assert _key(a) == _key(b), (path, a.score, b.score)


def test_hot_hook_rewrites_parity(monkeypatch):
    """Slot and scattered copies of the rewritten hooks, many levels / colours / limits
    (Maple Leaf 0..30), shared and cloned scattered items; the fast hooks must run."""
    calls = {}
    for ref, fast in list(I.FAST_HOOKS.items()):
        def wrap(*a, _f=fast, _n=fast.__name__):
            calls[_n] = calls.get(_n, 0) + 1
            return _f(*a)
        monkeypatch.setitem(I.FAST_HOOKS, ref, wrap)
    rng = random.Random(11)
    paths = _paths(rng, 400)
    configs = [
        (["maple_leaf", "dusty_coffin", "fire_extinguisher", "yellow_glasses", "ruler"], [0, 1, 2, 30]),
        (["yellow_glasses", "maple_leaf", "maple_leaf", "fire_extinguisher", "dusty_coffin"], [1, 3, 5]),
    ]
    for slugs, values in configs:
        for value in values:
            for colour in (None, "Red", "Blue", "Void", "Normal"):
                states = {"stickers": [_row(s, value, colour) for s in slugs],
                          "stamps": [_row(s, value + 1, colour) for s in reversed(slugs)],
                          "pin": None}
                plan = EnginePlan.build(_hot_board(), Loadout(extras={"item_states": json.dumps(states)}))
                assert not plan.dlc_ref
                _compare(plan, paths[:: 1 + (value % 3)], "word")
    for name in ("_dusty_coffin_fast", "_fire_ext_fast", "_yellow_glasses_fast", "_maple_fast"):
        assert calls.get(name, 0) > 100, (name, calls)


def test_hot_hooks_match_reference_hooks_on_any_context():
    """Each fast hook == its reference hook on the same step / ctx (incl. a ctx without a
    plan cache, where it must defer to the reference)."""
    rng = random.Random(5)
    states = {"stickers": [_row(s, 2, "Red") for s in HOT], "stamps": [], "pin": None}
    plan = EnginePlan.build(_hot_board(), Loadout(extras={"item_states": json.dumps(states)}))
    C.use_fastcalc(True)
    plan.score([0, 1])  # builds the plan cache
    from cursed_words_solver.engine.state import Ctx, Step

    for _ in range(300):
        path = rng.sample(range(25), rng.randint(0, 10))
        tiles = [plan.grid.tiles[i] for i in path]
        for slug in HOT:
            for value in (0, 1, 2, 4):
                for colour in ([], ["red"], ["blue"], ["void"], ["purple"]):
                    inst = C.make_item(slug)
                    inst.variables = [value]
                    inst.colours = list(colour)
                    for with_plan in (True, False):
                        out = []
                        for hook in (I.TILE_HOOKS.get(inst.cls) or I.WORD_HOOKS[inst.cls],):
                            for fn in (hook, I.FAST_HOOKS[hook]):
                                ctx = Ctx(plan.grid, list(tiles), [], [], 1, [], [], [], None, [], False, False, 0, "")
                                ctx.plan = plan if with_plan else None
                                step = Step([7 + k for k in range(len(tiles))], 3, 0)
                                if hook in I.TILE_HOOKS.values():
                                    for i in range(len(tiles)):
                                        fn(inst, step, i, ctx)
                                else:
                                    fn(inst, step, ctx)
                                out.append(repr(step))
                        assert out[0] == out[1], (slug, value, colour, path)


def test_scattered_items_and_cached_selections_parity():
    """Paths through scattered items (resolved-once templates, a cloned stateful one,
    Scissors, a no-hook one) with path-dependent wobbly selections and an Hourglass."""
    rng = random.Random(3)
    paths = _paths(rng, 600)
    for extra in ({}, {"hourglass_count": 1}, {"challenge_game_class": "Lexographer"}):
        for slugs in (["flamingo", "red_envelope", "maple_leaf"], ["spicy_pepper", "yellow_glasses", "jellyfish"]):
            slugs = [s for s in slugs if s in ITEMS]
            states = {"stickers": [_row(s, 2, "Red") for s in slugs], "stamps": [_row("fire_extinguisher", 3)],
                      "pin": None}
            plan = EnginePlan.build(_hot_board(), Loadout(extras={"item_states": json.dumps(states), **extra}))
            _compare(plan, paths)
            pc = plan.__dict__["_fastcalc"]
            assert pc.scr and any(r is C._DYN for r in pc.scr.values())  # ruler is cloned per call
            assert any(r is None for r in pc.scr.values())  # cable car: no scoring hook
            assert any(isinstance(r, tuple) for r in pc.scr.values())


def test_slot_order_identity_check_in_place_swaps():
    """The last-order check keys on item identity, so swapping items inside the same
    list objects (and back) must pick the right order every time."""
    states = {"stickers": [_row("yellow_glasses", 150), _row("dusty_coffin", 8, "Void"), _row("maple_leaf", 2, "Red")],
              "stamps": [_row("fire_extinguisher", 5, "Red"), _row("yellow_glasses", 50)], "pin": None}
    plan = EnginePlan.build(_hot_board(), Loadout(extras={"item_states": json.dumps(states)}))
    rng = random.Random(9)
    paths = _paths(rng, 40)
    st, sp = plan.stickers, plan.stamps
    perms = [(0, 1, 2), (2, 1, 0), (1, 0, 2), (0, 1, 2), (2, 0, 1)]
    base_st = list(st)
    base_sp = list(sp)
    for k, perm in enumerate(perms):
        st[:] = [base_st[i] for i in perm]
        sp[:] = base_sp if k % 2 == 0 else base_sp[::-1]
        assert plan.stickers is st and plan.stamps is sp
        _compare(plan, paths, "word")
    # A fresh value-equal (but distinct) item must not hit the cached order either.
    st[0] = C.inst_from_state(_row("yellow_glasses", 150))
    _compare(plan, paths, "word")


def test_ctx_fields_match_reference_and_are_fresh(monkeypatch):
    """A probe hook sees the same Ctx field values on both paths, and a fresh ``flags`` /
    ``nondeterministic`` each call even after an earlier call wrote them."""
    from dataclasses import fields

    from cursed_words_solver.engine.state import Ctx

    seen: list = []

    def probe(inst, step, ctx):
        row = {}
        for f in fields(Ctx):
            if f.name == "groups":
                continue  # _score_ref fills SubmittedWords groups; only DLC (dlc_ref) hooks read them

            v = getattr(ctx, f.name)
            row[f.name] = v is plan if f.name == "plan" else repr(v)
        seen.append(row)
        # Persists within a submit (the second Egg sees it) but must not leak into the next.
        ctx.flags["probe"] = ctx.flags.get("probe", 0) + 1
        ctx.nondeterministic = True

    monkeypatch.setitem(I.WORD_HOOKS, "Egg", probe)
    states = {"stickers": [_row("egg", 2), _row("ruler", 2)], "stamps": [_row("egg", 3)], "pin": None}
    plan = EnginePlan.build(_hot_board(), Loadout(extras={"item_states": json.dumps(states)}))
    for path in _paths(random.Random(4), 150):
        out = []
        for fast in (False, True, True):
            C.use_fastcalc(fast)
            seen.clear()
            res = plan.score(list(path), "word")
            out.append((_key(res), seen[:]))
        assert out[0] == out[1] == out[2], path


def test_ctx_template_and_hook_cache_lifecycle():
    """Per-call Ctx fields are fresh (flags, lists), the template holds no plan reference,
    and ``invalidate_score_cache`` drops the hook precomputation with the plan cache."""
    states = {"stickers": [_row(s, 3, "Red") for s in HOT], "stamps": [], "pin": None}
    plan = EnginePlan.build(_hot_board(), Loadout(extras={"item_states": json.dumps(states)}))
    C.use_fastcalc(True)
    a = plan.score([0, 4, 9, 14])
    pc = plan.__dict__["_fastcalc"]
    assert pc.ctx0["plan"] is None and pc.ctx0["tiles"] == [] and pc.ctx0["flags"] == {}
    assert pc.hk  # the fast hooks precomputed grid facts
    _compare(plan, _paths(random.Random(1), 60))
    assert pc.ctx0["plan"] is None and pc.ctx0["tiles"] == [] and pc.ctx0["flags"] == {}
    plan.invalidate_score_cache()
    assert "_fastcalc" not in plan.__dict__
    assert _key(plan.score([0, 4, 9, 14])) == _key(a) == _key(plan._score_ref([0, 4, 9, 14]))
