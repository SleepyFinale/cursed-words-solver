"""``clone`` pickle fast path vs the deepcopy reference (``CWS_DEEPCOPY_CLONE=1``).

Compared structurally: types, dict / set order, aliasing, float bits, RNG state and which
objects are shared with the original — on states from every phase, then again after
``determinize`` + ``apply`` of each legal action.
"""

from __future__ import annotations

import pathlib
import random

import pytest

from cursed_words_solver.sim.game import agent
from cursed_words_solver.sim.game.agent import Action, apply, determinize, legal_actions
from cursed_words_solver.sim.game.player import Node
from cursed_words_solver.sim.game.run import Game, RunConfig

_ATOM = (str, int, float, bool, type(None), bytes, complex, type, pathlib.PurePath)


def _same(a, b, shared, m=None, path="g"):
    if m is None:
        m = ({}, {})
    if id(a) in shared or id(b) in shared:
        assert a is b, f"{path}: shared object not shared"
        return
    assert type(a) is type(b), f"{path}: type {type(a)} vs {type(b)}"
    if isinstance(a, float):
        assert repr(a) == repr(b), f"{path}: {a} vs {b}"
        return
    if isinstance(a, _ATOM) or callable(a) and not hasattr(a, "__self__") and not hasattr(a, "__dict__"):
        assert a == b, f"{path}: {a!r} vs {b!r}"
        return
    fa, fb = m
    if id(a) in fa:
        assert fa[id(a)] is b, f"{path}: aliasing differs"
        return
    assert id(b) not in fb, f"{path}: aliasing differs (b)"
    fa[id(a)], fb[id(b)] = b, a
    if isinstance(a, random.Random):
        assert a.getstate() == b.getstate(), f"{path}: rng state"
        return
    if hasattr(a, "__self__") and hasattr(a, "__func__"):  # bound method
        assert a.__func__ is b.__func__, path
        _same(a.__self__, b.__self__, shared, m, path + ".__self__")
        return
    if isinstance(a, dict):
        assert list(a) == list(b), f"{path}: keys {list(a)} vs {list(b)}"
        for k in a:
            _same(a[k], b[k], shared, m, f"{path}[{k!r}]")
        return
    if isinstance(a, (list, tuple, set, frozenset)):
        la, lb = list(a), list(b)
        assert len(la) == len(lb), f"{path}: len"
        for i, (x, y) in enumerate(zip(la, lb)):
            _same(x, y, shared, m, f"{path}[{i}]")
        return
    slots = [s for c in type(a).__mro__ for s in getattr(c, "__slots__", ())]
    if hasattr(a, "__dict__"):
        _same(vars(a), vars(b), shared, m, path)
    for s in slots:
        if hasattr(a, s) or hasattr(b, s):
            _same(getattr(a, s), getattr(b, s), shared, m, f"{path}.{s}")
    if not hasattr(a, "__dict__") and not slots:
        assert a == b, f"{path}: {a!r} vs {b!r} ({type(a)})"


def _shared(g: Game, light: bool) -> dict[int, tuple[int, str]]:
    """id of each object the clone shares -> (id of its owner, attribute)."""
    out = {id(g.words): (id(g), "words")}
    if light:
        out[id(g.player.run.stats)] = (id(g.player.run), "stats")
        if g.encounter is not None:
            out[id(g.encounter.previous_words)] = (id(g.encounter), "previous_words")
    return out


def _referrers(root, targets) -> list[tuple]:
    """Every (target id, referencing object id, key / attribute) in ``root``'s object graph."""
    out, seen, stack = [], set(), [root]
    while stack:
        o = stack.pop()
        if id(o) in seen or isinstance(o, _ATOM):
            continue
        seen.add(id(o))
        if isinstance(o, dict):
            kids = [(repr(k), v) for k, v in o.items()] + [(f"<key {i}>", k) for i, k in enumerate(o)]
        elif isinstance(o, (list, tuple, set, frozenset)):
            kids = [(str(i), v) for i, v in enumerate(o)]
        else:
            kids = list(vars(o).items()) if hasattr(o, "__dict__") else []
            kids += [(s, getattr(o, s)) for c in type(o).__mro__ for s in getattr(c, "__slots__", ()) if hasattr(o, s)]
            if hasattr(o, "__self__") and hasattr(o, "__func__"):
                kids.append(("__self__", o.__self__))
        for k, v in kids:
            if id(v) in targets:
                out.append((id(v), id(o), k))
            else:
                stack.append(v)
    return out


def _check_sharing(g: Game, light: bool) -> None:
    # the pickle path re-attaches each shared object only at its own attribute
    targets = _shared(g, light)
    assert sorted(_referrers(g, targets)) == sorted((t, *owner) for t, owner in targets.items())


def _phase(g: Game) -> str:
    enc = g.encounter
    if g.phase == "encounter" and enc.michael is not None:
        return "michael_draft" if enc.michael_draft is not None else "michael"
    return g.phase


def _michael(g: Game) -> list[Game]:
    """Jump a late state to the stage-6 Michael fight (as test_game_rules does)."""
    from cursed_words_solver.sim.game.shop import Shop

    g = agent._deepcopy_clone(g, False)
    p, run = g.player, g.player.run
    run.stage, run.node = 6, Node.SHOP_TWO
    g.encounter = None
    g.shop = Shop(p, g.rng)
    g.leave_shop()
    out = [agent._deepcopy_clone(g, False)]
    g.choose_michael_boss(0)
    out.append(agent._deepcopy_clone(g, False))
    return out


def _play(character: str, crown: int, seed: int, record=None) -> Game:
    from cursed_words_solver.sim.game.agent import Candidates
    from cursed_words_solver.sim.game.policy import FastAdvicePolicy

    try:
        cands = Candidates(effort=0.01, cheap_floor=True)
        g = Game(RunConfig(character=character, ascension=crown, seed=seed))
    except FileNotFoundError as exc:
        pytest.skip(f"word list not installed: {exc}")
    pol = FastAdvicePolicy(cands)
    for _ in range(400):
        if g.phase == "done":
            break
        a = pol.act(g)
        if record is not None:
            record.append((agent._deepcopy_clone(g, False), a))
        apply(g, a)
    return g


@pytest.fixture(scope="module")
def states() -> list[tuple[Game, Action]]:
    out = []
    for run in [("BonesTheDog", 1, 1), ("Octacles", 1, 1)]:
        seen: list[tuple[Game, Action]] = []
        _play(*run, record=seen)
        by_phase: dict[str, list] = {}
        for s in seen:
            by_phase.setdefault(_phase(s[0]), []).append(s)
        for lst in by_phase.values():  # up to 4 per phase, spread over the run
            out += lst[:: max(1, len(lst) // 4)][:4]
        late = [s for s in seen if s[0].phase == "shop"][-1][0]
        out += [(m, None) for m in _michael(late)]
    phases = {_phase(s) for s, _ in out}
    assert {"encounter", "shop", "boss_draft", "pin_reward", "michael_draft", "michael"} <= phases
    return out


@pytest.mark.parametrize("light", [False, True])
def test_clone_structure_matches_deepcopy(states, light):
    for g, _ in states:
        _check_sharing(g, light)
        shared = set(_shared(g, light))
        ref = agent._deepcopy_clone(g, light)
        new = agent._pickle_clone(g, light)
        _same(ref, new, shared)
        # the detach / re-attach left the original intact (a copy, not g itself: rebuilding
        # a set can reorder it, for deepcopy and pickle alike)
        _same(ref, agent._deepcopy_clone(g, light), shared)
        _check_sharing(new, light)


def test_clone_matches_deepcopy_after_determinize_and_apply(states):
    for n, (g, chosen) in enumerate(states):
        acts = legal_actions(g)
        if chosen is not None and chosen not in acts:
            acts.insert(0, chosen)
        rnd = random.Random(n)
        acts = acts[:2] + rnd.sample(acts[2:], min(3, len(acts) - 2)) if len(acts) > 5 else acts
        for k, a in enumerate(acts):
            # light copies are evaluate-only: shop / boss / pin actions, no words
            for light in ([False, True] if g.phase in ("shop", "boss_draft", "pin_reward") else [False]):
                key = f"parity|{n}|{k}"
                ref = determinize(agent._deepcopy_clone(g, light), key)
                new = determinize(agent._pickle_clone(g, light), key)
                ra, rb = apply(ref, a), apply(new, a)
                _same((ra, ref), (rb, new), set(_shared(g, light)))
                assert ref.rng.range(0, 10**9) == new.rng.range(0, 10**9)


def test_clone_switch_and_fallback(states, monkeypatch):
    g = states[0][0]
    calls = []
    monkeypatch.setattr(agent, "_deepcopy_clone", lambda game, light: calls.append(light) or game)
    agent.clone(g)
    assert calls == []
    monkeypatch.setenv("CWS_DEEPCOPY_CLONE", "1")
    assert agent.clone(g, light=True) is g and calls == [True]
    monkeypatch.delenv("CWS_DEEPCOPY_CLONE")

    def boom(*_):
        raise TypeError("unpicklable")

    monkeypatch.setattr(agent.pickle, "dumps", boom)
    words = g.words
    assert agent.clone(g) is g and calls == [True, False]
    assert g.words is words  # restored after the failed dump


@pytest.mark.slow
@pytest.mark.parametrize("run", [("BonesTheDog", 1, 2), ("WetDennis", 0, 3), ("SockHead", 2, 4)])
def test_clone_cwenv_episode(run, monkeypatch):
    """A CWEnv episode (the action builder clones every candidate's afterstate) gives the same
    candidates, features and result with the pickle clone as with deepcopy."""
    import numpy as np

    from cursed_words_solver.rl.env import CWEnv
    from cursed_words_solver.sim.game.agent import Candidates

    def episode():
        calls = []
        real = agent._pickle_clone

        def counted(g, light):
            calls.append(light)
            return real(g, light)

        monkeypatch.setattr(agent, "_pickle_clone", counted)
        env = CWEnv(Candidates(effort=0.01, cheap_floor=True))
        ch, cr, sd = run
        env.reset(character=ch, crown=cr, seed=sd)
        trace = []
        for _ in range(150):
            if env.done:
                break
            st = env.current()
            trace.append(([c.action.label for c in st.cands], np.stack([c.feat for c in st.cands])))
            env.step(st.cands[0].action)
        return trace, env.game.won, calls

    try:
        new, won_new, calls = episode()
    except FileNotFoundError as exc:
        pytest.skip(f"word list not installed: {exc}")
    assert calls, "the episode never used the pickle clone"
    monkeypatch.setenv("CWS_DEEPCOPY_CLONE", "1")
    ref, won_ref, calls_ref = episode()
    assert not calls_ref
    assert won_ref == won_new and len(ref) == len(new)
    for (la, fa), (lb, fb) in zip(ref, new):
        assert la == lb and np.array_equal(fa, fb)