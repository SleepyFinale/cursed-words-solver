"""numba kernels (engine/_jit.py) vs the Python reference (``search.USE_JIT = False``,
the same as CWS_NO_JIT=1): results, visit order and stats must be bit-identical.

A shadow wrapper runs every ``enumerate`` / ``enumerate_subsets`` / ``_np_advance`` call
twice (reference, then kernels) on the same search and compares everything they return
or write to ``stats``.
"""

from __future__ import annotations

import collections
import pickle
import random
import sys
import time
from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("numba")

from cursed_words_solver.engine import _jit as J  # noqa: E402
from cursed_words_solver.engine import search as S  # noqa: E402
from cursed_words_solver.engine.calc import EnginePlan  # noqa: E402
from cursed_words_solver.engine.search import ExactSearch  # noqa: E402
from cursed_words_solver.engine.trie import CsrTrie  # noqa: E402
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _snap(stats) -> dict:
    d = {f.name: getattr(stats, f.name) for f in fields(stats)}
    d["extra"] = dict(stats.extra)
    return d


def _restore(stats, snap: dict) -> None:
    for k, v in snap.items():
        setattr(stats, k, dict(v) if k == "extra" else v)


@pytest.fixture
def shadow(monkeypatch):
    """Counts of kernel calls that ran (``letter`` / ``subset``) and of compared calls."""
    count = collections.Counter()
    enum, subsets, adv = ExactSearch.enumerate, ExactSearch.enumerate_subsets, S._np_advance

    def both(fn, name, norm):
        def run(self, *a, **k):
            before = _snap(self.stats)
            S.USE_JIT = False
            try:
                ref = norm(fn(self, *a, **k))
            finally:
                S.USE_JIT = True
            ref_stats = _snap(self.stats)
            _restore(self.stats, before)
            out = fn(self, *a, **k)
            assert norm(out) == ref, name
            assert _snap(self.stats) == ref_stats, name
            count[name] += 1
            return out
        return run

    def advance(arrays, nodes, wild, codes, tokens):
        prev = S.USE_JIT
        try:
            S.USE_JIT = False
            ref = adv(arrays, nodes, wild, codes, tokens)
            S.USE_JIT = True
            new = adv(arrays, nodes, wild, codes, tokens)
        finally:
            S.USE_JIT = prev
        assert (ref is None) == (new is None)
        if ref is not None:
            assert ref.dtype == new.dtype and np.array_equal(ref, new)
        count["advance"] += 1
        return new if prev else ref

    def counted(fn, name):
        def run(*a, **k):
            r = fn(*a, **k)
            if r is not None:
                count[name] += 1
            return r
        return run

    monkeypatch.setattr(S, "USE_JIT", True)
    monkeypatch.setattr(ExactSearch, "enumerate", both(enum, "enumerate", lambda r: list(r.items())))
    monkeypatch.setattr(ExactSearch, "enumerate_subsets", both(subsets, "subsets", lambda r: (list(r[0].items()), r[1])))
    monkeypatch.setattr(S, "_np_advance", advance)
    monkeypatch.setattr(J, "letter_enum", counted(J.letter_enum, "letter"))
    monkeypatch.setattr(J, "subset_enum", counted(J.subset_enum, "subset"))
    ExactSearch._enum_cache.clear()
    yield count
    ExactSearch._enum_cache.clear()


@pytest.fixture(scope="module")
def cands():
    from cursed_words_solver.sim.game.agent import Candidates

    return Candidates(effort=0.05, cheap_floor=True)


def _find(c, rec, jit: bool):
    board, loadout, top_n = pickle.loads(rec)
    saved = S.USE_JIT
    S.USE_JIT = jit
    try:
        ExactSearch._enum_cache.clear()
        return [(r.word, tuple(r.path), r.score, r.rank_score) for r in c._find(board, loadout, top_n)]
    finally:
        S.USE_JIT = saved


# ----------------------------------------------------------------------------- simulated runs

# (character, crown, seed): CWEnv / Candidates(effort=0.05, cheap_floor=True) as in RL training
_RUNS = [("BonesTheDog", 6, 71), ("SockHead", 7, 72), ("NinaNix", 0, 73), ("WetDennis", 5, 74),
         ("SamGambit", 2, 75), ("Octacles", 1, 76), ("HayleyBayles", 3, 77)]
_STEPS = 60


def _pick(env, st, rng) -> int:
    """Mostly the best word, a few shop buys, then on to the next encounter."""
    by_kind = collections.defaultdict(list)
    for k, c in enumerate(st.cands):
        by_kind[c.action.kind].append(k)
    if by_kind["submit"]:
        sub = by_kind["submit"]
        return sub[0] if rng.random() < 0.8 else sub[rng.randrange(len(sub))]
    if env.game.phase == "shop":
        if by_kind["buy"] and env.shop_actions < 2 and rng.random() < 0.7:
            return by_kind["buy"][0]
        if by_kind["leave"]:
            return by_kind["leave"][0]
    return 0


@pytest.mark.parametrize("character,crown,seed", _RUNS)
def test_cwenv_run_matches_reference(cands, shadow, character, crown, seed) -> None:
    from cursed_words_solver.rl.env import CWEnv

    keep: list[bytes] = []
    orig_find = cands._find

    def record(board, loadout, top_n):
        if len(keep) < 2:
            keep.append(pickle.dumps((board, loadout, top_n)))
        return orig_find(board, loadout, top_n)

    env = CWEnv(cands)
    rng = random.Random(seed)
    cands._find = record
    try:
        st = env.reset(character=character, crown=crown, seed=seed)
        for _ in range(_STEPS):
            if env.done or not st.cands:
                break
            _, done = env.step(st.cands[_pick(env, st, rng)].action)
            if done:
                break
            st = env.current()
    finally:
        del cands._find
    assert shadow["letter"] > 0 and shadow["enumerate"] > 0
    assert keep
    for rec in keep:  # whole search results (words, paths, scores, rank) old vs new
        assert _find(cands, rec, True) == _find(cands, rec, False)


# ----------------------------------------------------------------------------- real captures

# Scattered movement / letter items (path-dependent tables), Number Go Up, accumulator words,
# challenges, Full Moon, Michael's finale.
_CAPTURES = [
    "mismatches/20260529_210954.json", "mismatches/20260709_145336.json", "mismatches/20260709_144945.json",
    "mismatches/20260802_002533.json", "mismatches/20260607_121208.json",
    "round_logs/20260808_entoiled_path_mismatch.json", "round_logs/20260809_llama_path_mismatch.json",
    "round_logs/20260808_falchion_path_mismatch.json",
    "mismatches/20260524_211328.json", "mismatches/20260617_111126.json",
    "round_logs/20260626_112549_625_stale_f8_historic_lag.json", "mismatches/20260621_223803.json",
    "mismatches/20260715_184612.json", "mismatches/20260817_000602.json", "mismatches/20260615_201534.json",
    "mismatches/20260530_000134.json", "mismatches/20260605_175906.json", "mismatches/20260625_145011.json",
]


def _scaled_budgets(monkeypatch, effort: float = 0.05) -> None:
    from cursed_words_solver.sim.game.agent import _EFFORT_ATTRS

    for k, floor in _EFFORT_ATTRS.items():
        scale = 2 * effort if k == "beam_fixed_width" else effort
        if k == "max_exact_paths":
            floor = max(500, int(floor * min(1.0, effort / 0.05)))
        monkeypatch.setattr(ExactSearch, k, max(floor, int(getattr(ExactSearch, k) * scale)))


def test_captures_match_reference(cands, shadow, monkeypatch) -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from test_engine_captures import _load

    from cursed_words_solver.engine.solver import trie_for
    from cursed_words_solver.sim.replay import prepare_replay

    _scaled_budgets(monkeypatch)
    trie = trie_for(cands.dictionary)
    keys = S._numpy_trie(trie)[3]
    assert np.all(np.diff(keys) > 0)  # kernels stop scanning at the first larger letter
    dynamic = 0
    for rel in _CAPTURES:
        prep, err = prepare_replay(_load(FIXTURES / rel))
        assert prep is not None, (rel, err)
        plan = EnginePlan.build(prep.board, prep.loadout)
        out = []
        for jit in (False, True):
            monkeypatch.setattr(S, "USE_JIT", jit)
            ExactSearch._enum_cache.clear()
            xs = ExactSearch(plan, trie)
            out.append(([(c.path, c.word, c.score, c.nondeterministic) for c in xs.run(top_n=0)],
                        list(xs.last_found.items()), xs.stats.nodes,
                        {k: v for k, v in xs.stats.extra.items() if not k.endswith("_sec")}))
        assert out[0] == out[1], rel
        dynamic += bool(xs.super_inv.classes - xs.base_inv.classes)
    assert dynamic >= 5 and shadow["letter"] > 0 and shadow["subset"] > 0


# ----------------------------------------------------------------------------- synthetic boards


def _tile(r: int, c: int, ch: str) -> Tile:
    from cursed_words_solver.engine.model import LETTER_VALUES

    if ch == "?":
        t = Tile(r, c, "?", "?", 0.0, curse=CurseType.WILDCARD)
    elif ch.isdigit():
        t = Tile(r, c, ch, ch, float(int(ch)), curse=CurseType.NUMBER, number_value=int(ch))
    elif ch.isupper():  # scattered item, by its first letter
        slug = _ITEM_KEYS[ch]
        t = Tile(r, c, "*", "*", 0.0, curse=CurseType.ITEM, metadata={"scattered_item_id": slug})
    else:
        t = Tile(r, c, ch, ch.upper(), float(LETTER_VALUES[ch]))
    t.metadata["source"] = "melmod"
    return t


_ITEM_KEYS = {"F": "full_moon", "H": "hungry_snake", "R": "red_envelope", "S": "spicy_pepper",
              "Z": "sluggish_zombie", "J": "jellyfish", "C": "card_shark", "T": "test_tube"}
_WORDS = {"cat", "cats", "act", "acts", "tea", "teas", "sat", "eat", "eats", "stack", "tacks", "at", "as",
          "taste", "state", "seat", "east", "set", "sea", "tease", "jest", "zest", "quest", "quit", "suit",
          "quite", "squat", "aqua", "tat", "stat", "test", "tests", "estate", "a", "sec", "case"}


def _search(rows: list[str], loadout: Loadout | None = None, colors=None, words=_WORDS) -> ExactSearch:
    grid = []
    for r, line in enumerate(rows):
        row = [_tile(r, c, ch) for c, ch in enumerate(line)]
        for (rr, cc), col in (colors or {}).items():
            if rr == r:
                row[cc].color = col
        grid.append(row)
    plan = EnginePlan.build(Board(tiles=grid, money=0), loadout or Loadout())
    return ExactSearch(plan, CsrTrie.from_words(words))


def _both(make, **run_kw):
    """Full ``run`` with the reference, then with kernels (fresh search, no enumeration reuse)."""
    out = []
    for jit in (False, True):
        saved = S.USE_JIT
        S.USE_JIT = jit
        try:
            ExactSearch._enum_cache.clear()
            xs = make()
            res = [(c.path, c.word, c.score) for c in xs.run(top_n=0, **run_kw)]
            out.append((res, xs.stats.nodes, {k: v for k, v in xs.stats.extra.items() if not k.endswith("_sec")}))
        finally:
            S.USE_JIT = saved
    assert out[0] == out[1]
    return out[1][0]


def _stamps(*slugs: str) -> Loadout:
    return Loadout(stamps=[LoadoutItem(s, s, 1, "stamp") for s in slugs])


_ROWS = ["catsx", "atexF", "stack", "xtaHs", "acats"]


def test_dynamic_inventory_board(shadow) -> None:
    # Full Moon / Hungry Snake picked up mid-path change the moves after them.
    xs = _search(_ROWS)
    assert xs.super_inv.classes - xs.base_inv.classes
    tab = J.tables(xs, xs.super_inv)
    assert tab is not None and tab[2].any() and tab[0][1].shape[0] == 4  # 2 classes -> 4 tables
    assert _both(lambda: _search(_ROWS))
    assert shadow["letter"] > 0


def test_budget_overflow_and_wild_boards(shadow) -> None:
    # Wildcards + numbers + Number Go Up / Test Tube; tiny budgets force the subset tier.
    rows = ["c?ts1", "2te?x", "st3ck", "x?a4s", "ac5?s"]

    def tight(loadout=None):
        xs = _search(rows, loadout)
        xs.exhaustive_node_budget = xs.min_start_node_budget = 50
        xs.subset_path_budget = 400
        return xs

    for loadout in (None, _stamps("number_go_up"), _stamps("test_tube"), _stamps("microscope")):
        _both(lambda: _search(rows, loadout))
        _both(lambda: tight(loadout))
    assert shadow["letter"] > 0 and shadow["subset"] > 0


def test_white_portal_and_letter_items(shadow) -> None:
    rows = ["jests", "zxtea", "cSxat", "Rsack", "aJZCs"]
    colors = {(0, 1): TileColor.WHITE, (2, 3): TileColor.RED}
    _both(lambda: _search(rows, colors=colors))
    _both(lambda: _search(rows, _stamps("full_moon", "card_shark"), colors=colors))
    assert shadow["letter"] > 0


def test_fallbacks_stay_on_python(shadow) -> None:
    # Queenie "qu" token, Honeypot, deadline: the kernels decline and Python runs.
    qrows = ["quits", "aqtea", "stqck", "xtaqs", "acats"]
    xs = _search(qrows, _stamps("queenie"))
    assert J.tables(xs, xs.base_inv) is None
    _both(lambda: _search(qrows, _stamps("queenie")))
    honey = Loadout(stickers=[LoadoutItem("honeypot", "honeypot", 1)], extras={"wolf_max_length": "4"})
    xs = _search(_ROWS, honey)
    assert xs.honeypot and J.tables(xs, xs.base_inv) is None
    _both(lambda: _search(_ROWS, honey))
    assert shadow["letter"] == shadow["subset"] == 0
    # a deadline search never reaches the kernels
    _search(["catsx", "atexx", "stack", "xtacs", "acats"]).run(top_n=0, deadline=time.perf_counter() + 30)
    assert shadow["letter"] == 0 and shadow["enumerate"] > 0


def test_fallback_large_board_and_many_item_classes(shadow) -> None:
    big = ["catsxcats", "atexxatex", "stackstac", "xtacsxtac", "acatsacat", "teastease", "eatseatsx", "setsatsea"]
    xs = _search(big)
    assert len(xs.tiles) > 64 and J.tables(xs, xs.base_inv) is None
    _both(lambda: _search(big))
    many = ["FcatH", "RateS", "stZck", "JtaCs", "acTts"]  # 8 scattered item classes
    xs = _search(many)
    assert J.tables(xs, xs.base_inv) is None
    _both(lambda: _search(many))
    assert shadow["letter"] == 0


def test_no_jit_switch_and_missing_numba_use_python(monkeypatch) -> None:
    import cursed_words_solver.engine as engine_pkg

    monkeypatch.setattr(S, "USE_JIT", False)
    assert S._jit() is None
    monkeypatch.setattr(S, "USE_JIT", True)
    assert S._jit() is J
    # numba not importable: the kernels module fails to load and search stays on Python
    monkeypatch.setitem(sys.modules, "numba", None)
    monkeypatch.delitem(sys.modules, "cursed_words_solver.engine._jit")
    monkeypatch.delattr(engine_pkg, "_jit")
    monkeypatch.setattr(S, "_JIT_MOD", [])
    assert S._jit() is None
    ExactSearch._enum_cache.clear()
    best = _search(["catsx", "atexx", "stack", "xtacs", "acats"]).run(top_n=1)[0]
    assert best.word and len(best.path) >= 3


@pytest.mark.slow
@pytest.mark.parametrize("character", ["BonesTheDog", "HayleyBayles", "NathaServo", "NinaNix", "Octacles",
                                       "PrismaticBean", "SamGambit", "SandySaguaro", "SockHead", "Spike",
                                       "WetDennis"])
def test_long_cwenv_runs_match_reference(cands, shadow, monkeypatch, character) -> None:
    """Optional replay (pytest -m slow): whole runs per character, every search shadowed."""
    monkeypatch.setattr(sys.modules[__name__], "_STEPS", 400)
    for crown in (0, 4, 7):
        test_cwenv_run_matches_reference(cands, shadow, character, crown, 90_000 + crown)
