"""Auto-arrange (``rules.best_arrangement``): drag Human Boy's (SockHead) hands so the best
target-capped submit scores more; real drags (``Game.move``) + submit must give that score.
Off by default: env results, play rows and eval cache keys are unchanged unless enabled."""

from __future__ import annotations

import pytest

from cursed_words_solver.rl import rules as R
from cursed_words_solver.sim.game.agent import Candidates, apply, clone, submit_action
from cursed_words_solver.sim.game.items import make_item
from cursed_words_solver.sim.game.run import Game, RunConfig

_C = None


def _cands():
    global _C
    if _C is None:
        _C = Candidates(effort=0.05, cheap_floor=True)
    return _C


def _enc(ch: str = "SockHead", seed: int = 5) -> Game:
    g = Game(RunConfig(character=ch, ascension=2, seed=seed))
    for _ in range(10):
        if g.phase == "encounter":
            return g
        g._advance()
    raise AssertionError("no encounter")


def _hb_case() -> Game:
    """Human Boy with a strong stamp two slots right of Right Hand (not its favourite) and a
    Right Hand that re-triggers (pin var(1) = 4); the target is out of reach (no cap)."""
    g = _enc()
    p = g.player
    for _ in range(3):
        p.pin.upgrade(1)
    p.stamps[2] = make_item("NewEruptingVolcano")
    g.encounter.remaining_target = 10 ** 6
    return g


def _order(g) -> tuple:
    p = g.player
    return tuple(x.game_class if x is not None else None for x in (*p.stickers, *p.stamps))


def test_gain_matches_real_drags_and_submit():
    g = _hb_case()
    words = _cands().words(g, R.ARRANGE_K)
    info: dict = {}
    drags = R.best_arrangement(g, words, info=info)
    assert drags and info["best"] > info["base"] * 1.005
    h = clone(g)
    assert R.apply_arrangement(h, drags) == len(drags)
    st = h.player.stamps
    i = next(k for k, x in enumerate(st) if x is not None and x.game_class == "RightHumanHand")
    assert st[i + 1] is not None and st[i + 1].game_class == "NewEruptingVolcano"
    opts = [o for o in words if not o.placements]
    best = max(opts, key=lambda o: h.encounter.score_preview(o.path, o.words).score)
    res = apply(h, submit_action(best))
    assert float(res.score) == pytest.approx(info["best"])
    # the original order really scores less with the same word
    g0 = clone(g)
    assert float(apply(g0, submit_action(best)).score) < float(res.score)
    steps = R.describe_drags(g, drags)
    assert steps and steps[0].startswith("rearrange: move ") and " slot " in steps[0]


def test_capped_target_no_gain():
    g = _enc()   # the starting encounter's target is already reached by the best word
    assert R.best_arrangement(g, _cands().words(g, R.ARRANGE_K)) == []


def test_noop_without_hands():
    g = _enc("BonesTheDog")
    assert not R.has_positional(g.player)
    assert R.best_arrangement(g, _cands().words(g, 8)) == []


def test_deterministic_and_no_side_effects():
    g = _hb_case()
    words = _cands().words(g, R.ARRANGE_K)
    before, rng = _order(g), g.rng.state if hasattr(g.rng, "state") else None
    a = R.best_arrangement(g, words)
    b = R.best_arrangement(g, words)
    assert a == b and a
    assert _order(g) == before   # the search scores clones
    if rng is not None:
        assert g.rng.state == rng
    assert R.best_arrangement(_hb_case(), _cands().words(_hb_case(), R.ARRANGE_K)) == a


def test_flag_parsing():
    assert R.parse_arrange(True) and R.parse_arrange("1") and R.parse_arrange("on")
    assert not R.parse_arrange(None) and not R.parse_arrange("") and not R.parse_arrange("0")


def test_env_arranges_only_when_on():
    from cursed_words_solver.rl.env import CWEnv

    off = CWEnv(_cands())
    off.attach(_hb_case())
    o0 = _order(off.game)
    off.current()
    assert _order(off.game) == o0
    assert not any(k.startswith("arrange") for k in off.result())
    on = CWEnv(_cands(), arrange=True)
    on.attach(_hb_case())
    st = on.current()
    assert _order(on.game) != o0 and on.arrange_drags > 0
    assert any(c.action.kind == "submit" for c in st.cands)
    r = on.result()
    assert r["arrange"] is True and r["arrange_drags"] == on.arrange_drags and r["arrange_calls"] >= 1


def test_eval_cache_key_and_run_arm_plumbing(tmp_path):
    from cursed_words_solver.rl import evaluate as E

    row = {"character": "SockHead", "crown": 2, "quest": None, "seed": 1, "target": ""}
    assert E.cache_key(row) == E.cache_key({**row, "arrange": False})
    assert E.cache_key({**row, "arrange": True}) == (*E.cache_key(row), ("arrange",))
    assert E.key({**row, "arrange": True}) == E.key(row)   # still pairs with a plain arm
    seen: list = []

    def fake_play(job):
        seen.append(job)
        return {**{k: job[k] for k in ("character", "crown", "seed")}, "quest": None, "target": "",
                "won": False, "outcome": 0.0, "error": "", **({"arrange": True} if job.get("arrange") else {})}

    class Pool:
        def imap_unordered(self, fn, js):
            return [fake_play(j) for j in js]

    jobs = [{"character": "SockHead", "crown": 2, "seed": 1, "quest": None}]
    a = E.run_arm("plain", "teacher", jobs, out_dir=tmp_path, verbose=False, pool=Pool())
    b = E.run_arm("arr", "teacher", jobs, out_dir=tmp_path, verbose=False, pool=Pool(), arrange=True)
    assert "arrange" not in seen[0] and seen[1]["arrange"] is True
    assert "arrange" not in a[0] and b[0]["arrange"] is True
    # cached: a second call plays nothing
    E.run_arm("arr", "teacher", jobs, out_dir=tmp_path, verbose=False, pool=Pool(), arrange=True)
    assert len(seen) == 2


def test_play_row_default_off(monkeypatch):
    """play(): arrange only in rows of jobs that set it (a bad policy path errors fast)."""
    from cursed_words_solver.rl import play as PL

    if PL._CANDS is None:
        PL._CANDS = _cands()
    base = {"character": "SockHead", "crown": 2, "seed": 1, "quest": None, "policy": "no_such_policy.pt"}
    monkeypatch.setattr(PL, "_model", lambda p: (_ for _ in ()).throw(FileNotFoundError(p)))
    assert "arrange" not in PL.play(base)
    assert PL.play({**base, "arrange": True})["arrange"] is True


def test_evaluate_cli_has_arrange_flag():
    import inspect

    from cursed_words_solver.rl import evaluate as E

    assert "--arrange" in inspect.getsource(E.main)
    assert inspect.signature(E.run_arm).parameters["arrange"].default is False


def test_assistant_arrange_steps(monkeypatch, tmp_path):
    """advise_game(arrange=True) on an encounter opens with the drag steps and leaves the
    caller's game as it was; arrange off shows none."""
    torch = pytest.importorskip("torch")   # noqa: F841
    from cursed_words_solver.rl import assistant as A
    from cursed_words_solver.rl.model import Policy, default_config, save_policy

    d = tmp_path
    pol = Policy(default_config())
    save_policy(pol, d / "p.pt")
    g = _hb_case()
    o0 = _order(g)
    adv = A.advise_game(g, cands=_cands(), model_path=d / "p.pt", search=False, arrange=True)
    assert _order(g) == o0
    assert adv.context and adv.context[0].startswith("rearrange: move ")
    monkeypatch.setenv(R.ARRANGE_ENV, "0")
    adv2 = A.advise_game(_hb_case(), cands=_cands(), model_path=d / "p.pt", search=False)
    assert not any(s.startswith("rearrange") for s in adv2.context)
    # the live assistant default (env unset) is ON
    monkeypatch.delenv(R.ARRANGE_ENV, raising=False)
    adv3 = A.advise_game(_hb_case(), cands=_cands(), model_path=d / "p.pt", search=False)
    assert adv3.context and adv3.context[0].startswith("rearrange: move ")


def test_shop_probe_arrange_real_drags_no_rng():
    """At a shop (no encounter) the order is scored on a probe of the next encounter; the drags
    are real ``Game.move`` drags and the real game's RNG is untouched."""
    import pickle

    from cursed_words_solver.sim.game.policy import PowerPolicy

    pol = PowerPolicy(_cands())
    g = Game(RunConfig(character="SockHead", ascension=2, seed=11))
    for _ in range(400):
        if g.phase == "shop":
            break
        apply(g, pol.act(g))
    assert g.phase == "shop"
    p = g.player
    for _ in range(3):
        p.pin.upgrade(1)
    p.stamps[:] = [make_item("RightHumanHand"), None, None, make_item("NewEruptingVolcano"), None]
    rng = pickle.dumps(g.rng)
    info: dict = {}
    drags = R.best_arrangement(g, cands=_cands(), info=info)
    assert drags and info["best"] > info["base"]
    assert pickle.dumps(g.rng) == rng
    assert R.describe_drags(g, drags)[0].startswith("rearrange: move RightHumanHand to stamp slot")
    assert R.apply_arrangement(g, drags) == len(drags)
    assert p.is_hb_favourite_stamp(p.stamps[[x is not None and x.game_class for x in p.stamps].index("NewEruptingVolcano")])
    assert pickle.dumps(g.rng) == rng
