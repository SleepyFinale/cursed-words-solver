"""Build-conditioned RL core: target builds (``rl/targets.py``), obs v3 columns, model widening
of v2 checkpoints, combo ``plan_class``, teacher plan mapping, env shaping."""

from __future__ import annotations

import random

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import obs as O  # noqa: E402
from cursed_words_solver.rl import targets as T  # noqa: E402
from cursed_words_solver.rl.env import CWEnv, pack, potential  # noqa: E402
from cursed_words_solver.rl.model import (Policy, ModelConfig, collate, conditioned, default_config,  # noqa: E402
                                          load_policy, save_policy)
from cursed_words_solver.sim.game import policy as P  # noqa: E402
from cursed_words_solver.sim.game.agent import clone  # noqa: E402
from cursed_words_solver.sim.game.items import catalog_rows, make_item  # noqa: E402
from cursed_words_solver.sim.game.run import Game, RunConfig  # noqa: E402

V2_G, V2_T = O.LEGACY_GLOBAL[1], O.LEGACY_TOKEN[1]


class _NoWords:
    wordlist = None

    def words(self, game, top_n=5):
        return []


def _game(target="", seed=3, ch="WetDennis", crown=1, quest=None):
    return Game(RunConfig(character=ch, ascension=crown, seed=seed, challenge=quest, target_build=target))


def _classes_by(plan: str, want: str) -> list[str]:
    """Shop stickers / stamps (not pins) in that place of ``plan``."""
    return sorted(c for c, r in catalog_rows().items()
                  if r.get("slot") in ("sticker", "stamp") and P.plan_class(plan, c) == want)


# ------------------------------------------------------------------------- targets.py


def test_plans_and_parse():
    assert set(T.PLANS) == set(P.BUILD_PLANS) and len(T.PLANS) == 14
    assert T.PLANS[0] == "Red" and T.PLANS[-1] == "Colourless"
    assert "Colourless" not in T.SAMPLE_PLANS and len(T.SAMPLE_PLANS) == 13
    assert T.parse(T.FREE) == () and T.parse("Red") == ("Red",) and T.parse("Red+Blue") == ("Red", "Blue")
    with pytest.raises(ValueError):
        T.parse("Purple")
    with pytest.raises(ValueError):
        T.parse("Red+")
    assert T.display("") == "Free" and T.display("Red+Blue") == "Red + Blue"
    assert T.file_tag("Red+Blue") == "Red-Blue"
    assert set(T.THEMES) >= {"BonesTheDog", "WetDennis", "Spike"}
    assert all(set(v) <= set(T.SAMPLE_PLANS) for v in T.THEMES.values())


def test_plan_class_combos():
    rows = list(catalog_rows())
    for c in rows[:400]:   # single plans unchanged; combo = best part
        a, b = P.plan_class("Red", c), P.plan_class("Blue", c)
        best = min((a, b), key=["generator", "fits", "neutral", "off"].index)
        assert P.plan_class("Red+Blue", c) == best == P.plan_class("Blue+Red", c)
        assert T.item_class("Red+Blue", c) == best and T.item_class("", c) is None
    red_gen = _classes_by("Red", "generator")
    blue_gen = _classes_by("Blue", "generator")
    assert red_gen and blue_gen
    assert P.plan_class("Red", blue_gen[0]) == "off"   # another build's generator
    assert P.plan_class("Red+Blue", blue_gen[0]) == "generator"
    # Cash shop helpers stay neutral under Cash, even in a combo whose other part calls them off
    assert P.plan_class("Cash", "FriedShrimp") == "neutral"


def test_teacher_plan_mapping():
    assert T.teacher_plan(T.FREE, "WetDennis", None) == P.DEFAULT_PLAN == "Curse"
    assert T.teacher_plan(T.FREE, "SamGambit", None) == "Chess"
    assert T.teacher_plan(T.FREE, "SockHead", None) == "Chess"
    assert T.teacher_plan("Red", "SamGambit", None) == "Red"
    assert T.teacher_plan("Red+Blue", "WetDennis", None) == "Red+Blue"
    assert T.teacher_plan("Red", "WetDennis", "Chromaphilia") == "Rainbow"
    assert T.teacher_plan("Red", "WetDennis", "Cursophobia") == ""
    assert T.teacher_plan(T.FREE, "SamGambit", "Chromaphobia") == "Colourless"
    assert T.teacher_plan(T.FREE, "Octacles", "Sudoku") == "Numbers"
    assert T.teacher_plan("Cards", "BonesTheDog", "SomeOtherQuest") == "Cards"


def test_sample_target_deterministic_and_mixed():
    a = [T.sample_target(random.Random(i), "WetDennis") for i in range(200)]
    b = [T.sample_target(random.Random(i), "WetDennis") for i in range(200)]
    assert a == b
    assert T.FREE in a and set(a) - {T.FREE} <= set(T.SAMPLE_PLANS)
    rng = random.Random(1)
    assert all(T.sample_target(rng, "WetDennis", (1, 0, 0)) == T.FREE for _ in range(20))
    assert all(T.sample_target(rng, "NinaNix", (0, 1, 0)) in ("Void", "Rainbow") for _ in range(50))
    assert {T.sample_target(rng, "NinaNix", (0, 0, 1)) for _ in range(300)} == set(T.SAMPLE_PLANS)
    # one rng.random() then one rng.choice
    r1, r2 = random.Random(9), random.Random(9)
    t = T.sample_target(r1, "Spike", (0, 1, 0))
    r2.random()
    assert t == r2.choice(T.THEMES["Spike"]) and r1.random() == r2.random()


def test_get_set_target_and_clone():
    g = _game("Red+Blue")
    assert T.get_target(g) == "Red+Blue" and T.get_target(clone(g)) == "Red+Blue"
    g2 = _game()
    assert T.get_target(g2) == T.FREE
    T.set_target(g2, "Cards")
    assert T.get_target(g2) == "Cards"
    with pytest.raises(ValueError):
        T.set_target(g2, "Nope")

    class _Bare:
        pass

    assert T.get_target(_Bare()) == T.FREE


# ------------------------------------------------------------------------- obs v3


def test_obs_v3_widths_and_column_order():
    assert O.OBS_VERSION == 3
    assert O.n_global_features() == O.V3_GLOBAL == V2_G + 1 + len(T.PLANS)
    assert O.n_token_features() == O.V3_TOKEN == V2_T + 4
    g = list(O.global_columns())
    assert g[V2_G:] == ["target_set"] + [f"target:{p}" for p in T.PLANS]
    assert list(O.token_columns())[V2_T:] == ["pc:generator", "pc:fits", "pc:off", "pc:neutral"]


def test_free_obs_matches_prefix_and_is_zero_beyond():
    free, red = O.observe(_game("")), O.observe(_game("Red+Blue"))
    assert np.array_equal(free.glob[:V2_G], red.glob[:V2_G])
    assert np.array_equal(free.tok_feat[:, :V2_T], red.tok_feat[:, :V2_T])
    assert np.array_equal(free.tok_type, red.tok_type) and np.array_equal(free.tok_cls, red.tok_cls)
    assert not free.glob[V2_G:].any() and not free.tok_feat[:, V2_T:].any()
    col = O.global_columns()
    on = {n for n, i in col.items() if i >= V2_G and red.glob[i]}
    assert on == {"target_set", "target:Red", "target:Blue"}
    single = O.observe(_game("Cards"))
    assert {n for n, i in col.items() if i >= V2_G and single.glob[i]} == {"target_set", "target:Cards"}


def test_pc_columns_on_owned_item():
    gen = _classes_by("Red", "generator")
    off = [c for c in _classes_by("Red", "off") if P.plan_class("Blue", c) == "off"]
    g = _game("Red")
    p = g.player
    added = []
    for cls in (gen[0], off[0]):
        it = make_item(cls)
        p.add_item(it, g.rng)
        added.append(it)
    o = O.observe(g)
    tc = O.token_columns()
    vocab = O.class_vocab()
    owned_types = {O.TOK_STICKER, O.TOK_STAMP}
    for it, want in zip(added, ("pc:generator", "pc:off")):
        rows = [i for i in range(len(o.tok_cls))
                if o.tok_cls[i] == vocab[it.game_class] and int(o.tok_type[i]) in owned_types]
        assert rows, it.game_class
        f = o.tok_feat[rows[0]]
        assert f[tc[want]] == 1.0 and sum(f[tc[f"pc:{c}"]] for c in O.PLAN_CLASSES) == 1.0
    # every item token gets exactly one pc:*; tiles / bosses none
    pcs = o.tok_feat[:, [tc[f"pc:{c}"] for c in O.PLAN_CLASSES]].sum(1)
    item_types = {O.TOK_STICKER, O.TOK_STAMP, O.TOK_PIN, O.TOK_SHOP_STICKER, O.TOK_SHOP_STAMP,
                  O.TOK_FROZEN_STICKER, O.TOK_FROZEN_STAMP}
    for i, tt in enumerate(o.tok_type):
        if int(tt) not in (O.TOK_PIN_OFFER, O.TOK_NESTED):
            assert pcs[i] == (1.0 if int(tt) in item_types else 0.0)
    assert T.on_plan_count(g, "Red") >= 1 and T.off_plan_count(g, "Red") >= 1
    assert T.on_plan_count(g, T.FREE) == 0 == T.off_plan_count(g, T.FREE)
    T.set_target(g, "")
    assert not O.observe(g).tok_feat[:, V2_T:].any()


# ------------------------------------------------------------------------- model widening


def test_v2_checkpoint_widened_with_identical_logits(monkeypatch, tmp_path):
    cfg2 = ModelConfig(**{**default_config().__dict__, "n_global": V2_G, "n_tok_feat": V2_T})
    monkeypatch.setattr(O, "LEGACY_GLOBAL", ())
    monkeypatch.setattr(O, "LEGACY_TOKEN", ())
    torch.manual_seed(0)
    v2 = Policy(cfg2).eval()
    monkeypatch.undo()
    assert v2.cfg.n_global == V2_G and not conditioned(v2.cfg)
    path = tmp_path / "v2.pt"
    save_policy(v2, path)
    assert not conditioned(torch.load(path, weights_only=False)["config"])
    m, _ = load_policy(path)
    assert (m.cfg.n_global, m.cfg.n_tok_feat) == (O.n_global_features(), O.n_token_features())
    assert conditioned(m.cfg) and conditioned(default_config())
    assert torch.all(m.glob_in[0].weight[:, V2_G:] == 0) and torch.all(m.tok_in.weight[:, V2_T:] == 0)
    env = CWEnv(_NoWords())
    pk = pack(env.reset(character="SockHead", crown=2, seed=4, target="Curse+Chess"))
    assert pk["glob"][V2_G:].any()
    trunc = {**pk, "glob": pk["glob"][:V2_G], "tok_feat": pk["tok_feat"][:, :V2_T]}
    with torch.no_grad():
        ref = v2(collate([trunc]))
        for batch in ([pk], [trunc]):
            out = m(collate(batch))
            assert torch.allclose(out["logits"], ref["logits"], atol=1e-5)
            assert torch.allclose(out["value"], ref["value"], atol=1e-5)
    # resume path (ppo.py / bc.py: Policy(config) + load_state_dict) widens too
    ck = torch.load(path, weights_only=False)
    r = Policy(ModelConfig(**ck["config"]))
    r.load_state_dict(ck["state"])
    assert r.cfg.n_global == O.n_global_features()


def test_distill_buffer_accepts_v2_width_shards():
    from cursed_words_solver.rl.ppo import DistillBuffer

    buf = DistillBuffer(".", cap=1)
    G, Ft, Fa = buf._widths()
    ep = {"glob": np.zeros((1, V2_G), np.float32), "tok_feat": np.zeros((1, V2_T), np.float32),
          "act_feat": np.zeros((1, Fa), np.float32), "obs_version": np.asarray([2], np.int16)}
    assert buf.format_ok(ep)
    assert not buf.format_ok({**ep, "glob": np.zeros((1, G), np.float32)})


# ------------------------------------------------------------------------- env


def _play(env, rng):
    st = env.current()
    total = 0.0
    while not env.done:
        c = st.cands[rng.randrange(len(st.cands))]
        r, _ = env.step(c.action)
        total += r
        if not env.done:
            st = env.current()
    return total


@pytest.mark.parametrize("target,shaping", [("", 0.0), ("Red", 0.5), ("Curse+Cash", 0.25)])
def test_env_shaping_telescopes_to_outcome(target, shaping):
    env = CWEnv(_NoWords(), shaping=shaping)
    env.reset(character="WetDennis", crown=0, seed=11, target=target)
    assert env.target == target and T.get_target(env.game) == target
    phi0 = env.phi
    assert phi0 == pytest.approx(potential(env.game) + shaping * T.on_plan_count(env.game, target))
    total = _play(env, random.Random(3))
    res = env.result()
    assert env.game.phase == "done"
    assert phi0 + total == pytest.approx(res["outcome"], abs=1e-3)
    assert res["target"] == target and res["on_plan"] == T.on_plan_count(env.game, target)
    assert res["off_plan"] == T.off_plan_count(env.game, target)


def test_env_potential_counts_on_plan_items():
    gen = _classes_by("Red", "generator")
    env = CWEnv(_NoWords(), shaping=0.5)
    env.reset(character="WetDennis", crown=0, seed=2, target="Red")
    g = env.game
    before = env.potential(g)
    g.player.add_item(make_item(gen[0]), g.rng)
    assert env.potential(g) == pytest.approx(before + 0.5)
    free = CWEnv(_NoWords(), shaping=0.5)
    free.attach(g)
    T.set_target(g, "")
    free.attach(g)
    assert free.target == "" and free.potential(g) == pytest.approx(potential(g))


def test_netpolicy_build_plan_kwargs():
    from cursed_words_solver.sim.game.expert import NetPolicy

    class _Cands(_NoWords):
        effort = 0.0

        def with_budget(self, *a, **k):
            return self

        def with_effort(self, *a, **k):
            return self

    d = NetPolicy(_Cands(), boss_model="")
    assert d.cfg.build_plan == P.DEFAULT_PLAN and d.cfg.build_plan_chars == P.DEFAULT_PLAN_CHARS
    n = NetPolicy(_Cands(), boss_model="", build_plan="Red+Blue", build_plan_chars={})
    assert n.cfg.build_plan == "Red+Blue" and n.cfg.build_plan_chars == {}
