"""Common random numbers in ``agent.determinize``: a ``KeyedRng`` restarts at every node,
encounter setup, grid (and grid reroll) and shop stock (and restock) from ``(key, where)``, so
two branches of one decision that consumed different amounts of randomness still face the
same later grids and shops. The game's own ``Rng`` never moves on ``mark``."""

from __future__ import annotations

import copy
import pickle

from cursed_words_solver.sim.game import agent
from cursed_words_solver.sim.game.agent import clone, determinize
from cursed_words_solver.sim.game.core import KeyedRng, Rng
from cursed_words_solver.sim.game.run import Game, RunConfig


def _game(seed: int = 3, ch: str = "BonesTheDog", crown: int = 2) -> Game:
    g = Game(RunConfig(character=ch, ascension=crown, seed=seed))
    assert g.phase == "encounter"
    return g


def _tile_fp(t) -> tuple:
    return (*(getattr(t, f) for f in t.__dataclass_fields__ if f != "item"),
            t.item.game_class if t.item is not None else None)


def _grid_fp(g: Game) -> tuple:
    return tuple(_tile_fp(t) for t in g.encounter.grid.tiles)


def _shop_fp(g: Game) -> tuple:
    s = g.shop
    items = tuple((o.item.game_class, o.item.is_foil, o.cost) if o is not None else None
                  for o in (*s.stickers, *s.stamps))
    tiles = tuple(_tile_fp(o.tile) if o is not None else None for o in s.tiles)
    return items, tiles


def _burn(g: Game, n: int = 37) -> None:
    """What a different word's procs / an extra buy would do to a shared stream."""
    for _ in range(n):
        g.rng.range(0, 1000)


def _to_shop(g: Game) -> Game:
    """Skip the rest of the encounter (no word engine in CI) and walk to the next shop."""
    for _ in range(10):
        g._advance()
        if g.phase == "shop":
            return g
    raise AssertionError("no shop reached")


# ------------------------------------------------------------------ the two streams

def test_plain_rng_mark_is_a_noop():
    r = Rng("seed")
    r.range(0, 10)
    st = r.getstate()
    r.mark("grid", 1, "ENCOUNTER_FIRST", 0, 1, 0)
    assert r.getstate() == st


def test_keyed_rng_restarts_by_position():
    a, b = KeyedRng("k"), KeyedRng("k")
    _ = [a.range(0, 100) for _ in range(9)]            # a consumed more than b
    a.mark("shop", 1, "SHOP_ONE", 1)
    b.mark("shop", 1, "SHOP_ONE", 1)
    assert [a.range(0, 10**9) for _ in range(5)] == [b.range(0, 10**9) for _ in range(5)]
    b.mark("shop", 1, "SHOP_ONE", 2)
    c = KeyedRng("other")
    c.mark("shop", 1, "SHOP_ONE", 1)
    a.mark("shop", 1, "SHOP_ONE", 1)
    first = a.range(0, 10**9)
    assert first != b.range(0, 10**9)                  # another position
    assert first != c.range(0, 10**9)                  # another key


def test_real_game_uses_plain_rng():
    g = _game()
    assert type(g.rng) is Rng
    assert g.encounter.rng is g.rng


def test_clone_preserves_keyed_rng():
    h = determinize(clone(_game()), "k")
    _burn(h, 5)
    for c in (agent._pickle_clone(h, False), agent._deepcopy_clone(h, False), clone(h, light=True),
              pickle.loads(pickle.dumps(h.rng)), copy.deepcopy(h.rng)):
        r = c if isinstance(c, Rng) else c.rng
        assert type(r) is KeyedRng and r.key == "k"
        assert r.getstate() == h.rng.getstate()
        if not isinstance(c, Rng):
            assert c.encounter.rng is c.rng          # still one shared stream
    # and it keeps marking after a clone
    a, b = clone(h), clone(h)
    _burn(a)
    a.encounter.build_grid()
    b.encounter.build_grid()
    assert _grid_fp(a) == _grid_fp(b)


# ------------------------------------------------------------------ isolation

def test_grid_isolation_next_grid_and_rerolls():
    h = determinize(clone(_game()), "iso")
    h.encounter.rerolls = 9
    a, b = clone(h), clone(h)
    # a reroll of this grid: same however much the branch consumed first
    _burn(a)
    assert a.encounter.reroll() and b.encounter.reroll()
    assert _grid_fp(a) == _grid_fp(b)
    # a rerolls once more, b doesn't: the next grid is still the same
    assert a.encounter.reroll()
    _burn(b, 3)
    a.encounter.build_grid()
    b.encounter.build_grid()
    assert _grid_fp(a) == _grid_fp(b)
    # the next grid's first reroll is the same though a rerolled the previous grid more
    assert a.encounter.reroll() and b.encounter.reroll()
    assert _grid_fp(a) == _grid_fp(b)


def test_shop_isolation_stock_restock_and_next_grid():
    h = determinize(clone(_game()), "shop")
    a, b = clone(h), clone(h)
    _burn(a)
    a.encounter.rerolls = 3
    a.encounter.reroll()                                # a branch-only grid reroll
    _to_shop(a)
    _to_shop(b)
    assert _shop_fp(a) == _shop_fp(b)                   # first stock
    a.player.money = b.player.money = 60
    _burn(b, 11)                                        # e.g. a buy's item rolls
    assert a.reroll_shop() and b.reroll_shop()
    assert _shop_fp(a) == _shop_fp(b)                   # the 2nd stock of this shop
    assert a.reroll_shop()                              # a restocks once more
    a.leave_shop()
    b.leave_shop()
    while a.phase != "encounter":
        a._advance()
    while b.phase != "encounter":
        b._advance()
    assert a.player.run.node == b.player.run.node
    assert _grid_fp(a) == _grid_fp(b)                   # the next encounter's first grid


def test_old_shared_stream_would_desync(monkeypatch):
    """Sanity check of the test itself: without marks, a branch that consumed more draws
    sees a different next grid."""
    monkeypatch.setattr(KeyedRng, "mark", Rng.mark)
    h = determinize(clone(_game()), "iso")
    a, b = clone(h), clone(h)
    _burn(a)
    a.encounter.build_grid()
    b.encounter.build_grid()
    assert _grid_fp(a) != _grid_fp(b)


def test_no_real_stream_leak():
    """The sampled future depends only on the key and the visible state, not on where the
    real stream happens to be."""
    g = _game()
    x, y = clone(g), clone(g)
    _burn(y, 101)                                       # different hidden RNG state
    a, b = determinize(x, "leak"), determinize(y, "leak")
    a.encounter.build_grid()
    b.encounter.build_grid()
    assert _grid_fp(a) == _grid_fp(b)
    _to_shop(a)
    _to_shop(b)
    assert _shop_fp(a) == _shop_fp(b)


# ------------------------------------------------------------------ determinism

def _script(g: Game) -> tuple:
    out = []
    g.encounter.rerolls = 2
    g.encounter.reroll()
    out.append(_grid_fp(g))
    g.encounter.build_grid()
    out.append(_grid_fp(g))
    _to_shop(g)
    out.append(_shop_fp(g))
    g.player.money = 40
    g.reroll_shop()
    out.append(_shop_fp(g))
    g.leave_shop()
    while g.phase not in ("encounter", "done"):
        g._advance()
    out.append(_grid_fp(g) if g.phase == "encounter" else None)
    out.append((g.player.money, g.player.run.stage, g.player.run.node, len(g.events)))
    return tuple(out)


def test_same_game_key_actions_same_outcome():
    g = _game(seed=8)
    assert _script(determinize(clone(g), "d")) == _script(determinize(clone(g), "d"))
    assert _script(determinize(clone(g), "d")) != _script(determinize(clone(g), "e"))


def test_real_game_stream_unchanged_by_marks(monkeypatch):
    """Real games (plain Rng) draw exactly as before marks existed."""
    calls = []

    def spy(self, *where):
        calls.append(where)

    a = _game(seed=8)
    ref = _script(a)
    monkeypatch.setattr(Rng, "mark", spy)
    b = _game(seed=8)
    assert _script(b) == ref
    assert calls                                        # marks were reached, and changed nothing
