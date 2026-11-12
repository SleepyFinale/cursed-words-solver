"""RL observation v2 (probe strength, last encounter, quest rules, instance tags) and the
pruned draft action sets; v1 checkpoints keep scoring exactly as before."""

from __future__ import annotations

import time

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import obs as O  # noqa: E402
from cursed_words_solver.rl.actions import Limits  # noqa: E402
from cursed_words_solver.rl.env import CWEnv, pack  # noqa: E402
from cursed_words_solver.rl.model import (ModelConfig, Policy, collate, default_config, load_policy,  # noqa: E402
                                          save_policy, upgrade_checkpoint, upgrade_optimizer_state)
from cursed_words_solver.sim.game.agent import clone, determinize  # noqa: E402
from cursed_words_solver.sim.game.run import Game, RunConfig  # noqa: E402

V1_G, V1_T = O.LEGACY_GLOBAL[0], O.LEGACY_TOKEN[0]
V2_GLOBAL = [n for n in O.global_columns()][V1_G:]
V2_TOKEN = [n for n in O.token_columns()][V1_T:]


class _NoWords:
    wordlist = None

    def words(self, game, top_n=5):
        return []


@pytest.fixture(scope="module")
def cands():
    try:
        from cursed_words_solver.sim.game.agent import Candidates

        return Candidates(effort=0.05, cheap_floor=True)
    except Exception as exc:  # word list missing (CI)
        pytest.skip(f"no word list: {exc}")


def _v1_cfg() -> ModelConfig:
    return ModelConfig(**{**default_config().__dict__, "n_global": V1_G, "n_tok_feat": V1_T})


def _v1_model(monkeypatch) -> Policy:
    """A genuinely v1-wide model (legacy widening switched off while it is built)."""
    monkeypatch.setattr(O, "LEGACY_GLOBAL", ())
    monkeypatch.setattr(O, "LEGACY_TOKEN", ())
    torch.manual_seed(0)
    m = Policy(_v1_cfg()).eval()
    monkeypatch.undo()
    assert m.cfg.n_global == V1_G
    return m


def _pk(seed=4, ch="SockHead", crown=3):
    env = CWEnv(_NoWords())
    return pack(env.reset(character=ch, crown=crown, seed=seed))


def _noisy(pk, rng):
    """Random values in the v2 columns (what a v1 model must ignore)."""
    g = pk["glob"].copy()
    g[V1_G:] = rng.normal(size=len(g) - V1_G)
    tf = pk["tok_feat"].copy()
    tf[:, V1_T:] = rng.normal(size=(len(tf), tf.shape[1] - V1_T))
    return {**pk, "glob": g, "tok_feat": tf}


def _truncated(pk):
    return {**pk, "glob": pk["glob"][:V1_G], "tok_feat": pk["tok_feat"][:, :V1_T]}


# ------------------------------------------------------------------------- layout / checkpoints


def test_layout_appends_v2_columns():
    assert O.OBS_VERSION == 2
    assert len(O.global_columns()) == len(set(O.global_columns())) and len(O.token_columns()) == len(set(O.token_columns()))
    assert {"str_next", "str_boss", "last_mean_over", "q_no_stickers", "q_banned_now"} <= set(V2_GLOBAL)
    assert {"inst_changed", "boss_strength", "boss_known"} <= set(V2_TOKEN)
    assert not any(n.startswith(("str_", "last_", "q_")) for n in list(O.global_columns())[:V1_G])
    assert list(O.token_columns())[V1_T - 3:V1_T] == ["boss_cursed", "boss_mod", "boss_floor"]   # v1 tail


def test_v1_checkpoint_loads_with_identical_logits(monkeypatch, tmp_path):
    v1 = _v1_model(monkeypatch)
    path = tmp_path / "v1.pt"
    save_policy(v1, path)
    m, _ = load_policy(path)
    assert (m.cfg.n_global, m.cfg.n_tok_feat) == (O.n_global_features(), O.n_token_features())
    assert torch.all(m.glob_in[0].weight[:, V1_G:] == 0) and torch.all(m.tok_in.weight[:, V1_T:] == 0)
    rng = np.random.default_rng(0)
    pks = [_pk(), _pk(seed=7, ch="Octacles", crown=0)]
    with torch.no_grad():
        ref = v1(collate([_truncated(p) for p in pks]))
        for batch in ([_noisy(p, rng) for p in pks], pks, [_truncated(p) for p in pks]):
            out = m(collate(batch))
            assert torch.allclose(out["logits"], ref["logits"], atol=1e-5)
            assert torch.allclose(out["value"], ref["value"], atol=1e-5)
            assert torch.allclose(out["aux"], ref["aux"], atol=1e-5)


def test_training_checkpoint_upgrade_resumes_optimizer(monkeypatch):
    v1 = _v1_model(monkeypatch)
    opt = torch.optim.AdamW(v1.parameters(), lr=1e-3)
    pk = _truncated(_pk())
    v1.train()
    v1(collate([pk]))["value"].sum().backward()
    opt.step()
    ck = upgrade_checkpoint({"config": v1.cfg.__dict__.copy(), "state": v1.state_dict(), "opt": opt.state_dict(), "update": 3})
    assert ck["config"]["n_global"] == O.n_global_features() and ck["update"] == 3
    m = Policy(ModelConfig(**ck["config"]))
    m.load_state_dict(ck["state"])
    opt2 = torch.optim.AdamW(m.parameters(), lr=1e-3)
    opt2.load_state_dict(ck["opt"])
    m(collate([_pk()]))["value"].sum().backward()
    opt2.step()   # moments padded to the new widths
    # the plain ppo.py resume path (Policy(config) + load_state_dict) widens too
    m2 = Policy(ModelConfig(**v1.cfg.__dict__))
    m2.load_state_dict(v1.state_dict())
    opt3 = torch.optim.AdamW(m2.parameters(), lr=1e-3)
    opt3.load_state_dict(upgrade_optimizer_state(opt.state_dict(), m2))
    assert m2.cfg.n_global == O.n_global_features()


def test_collate_mixes_old_and_new_width_steps():
    pk = _pk()
    b = collate([_truncated(pk), pk])
    assert b["glob"].shape[1] == O.n_global_features() and b["tok_feat"].shape[2] == O.n_token_features()
    assert torch.all(b["glob"][0, V1_G:] == 0)
    out = Policy(default_config())(collate([_truncated(pk)]))   # narrower batch: model pads
    assert out["logits"].shape[1] == len(pk["act_type"])


# ------------------------------------------------------------------------- features without probes


def test_quest_rule_flags():
    col = O.global_columns()
    plain = O.observe(Game(RunConfig(character="Spike", seed=1))).glob
    assert not any(plain[col[n]] for n in V2_GLOBAL if n.startswith("q_"))
    g = O.observe(Game(RunConfig(character="NathaServo", challenge="InTheBeginning", seed=1))).glob
    assert g[col["q_no_stickers"]] == 1 and g[col["q_no_stamps"]] == 1 and g[col["q_shop_rule"]] == 1
    assert g[col["q_forced_char"]] == 1 and g[col["q_start_items"]] > 0 and g[col["q_no_sell"]] == 0
    e = O.observe(Game(RunConfig(character="Spike", challenge="Embargo", seed=1))).glob
    assert e[col["q_no_sell"]] == 1 and e[col["q_banned_now"]] > 0 and e[col["q_banned_any"]] == 1
    m = O.observe(Game(RunConfig(character="Spike", challenge="MunchTime", seed=1))).glob
    assert m[col["q_elite"]] == 1 and m[col["q_grid_mod"]] == 1


def test_instance_colours_and_tags_only_when_changed():
    col = O.token_columns()
    g = Game(RunConfig(character="Octacles", seed=3))
    o = O.observe(g)
    i = o.refs[("pin", 0)]
    pin = g.player.pin
    # Octacles' Bucket starts with CashBuild on top of its catalog CurseBuild
    assert "CashBuild" in pin.tags and "CashBuild" not in O._catalog_inst("Bucket")[0]
    assert o.tok_feat[i, col["inst_changed"]] == 1 and o.tok_feat[i, col["itag:CashBuild"]] == 1
    pin.tags = sorted(O._catalog_inst("Bucket")[0])
    assert not O.observe(g).tok_feat[:, V1_T:].any()   # catalog instances: v2 token columns all zero
    other = next(t for t in O._vocab()["types"] if t not in pin.relevant_colours)
    pin.relevant_colours = [other]
    pin.tags = list(pin.tags) + ["NumbersGenerator"]
    f = O.observe(g).tok_feat[i]
    assert f[col["inst_changed"]] == 1 and f[col[f"icol:{other}"]] == 1 and f[col["itag:NumbersGenerator"]] == 1
    assert np.array_equal(f[:V1_T], o.tok_feat[i][:V1_T])   # v1 columns unchanged


def test_last_encounter_from_word_history():
    from cursed_words_solver.sim.game.player import HistoricWord

    g = Game(RunConfig(character="Spike", seed=1))
    hw = lambda s, rem, rnd: HistoricWord(tiles=[], words=["x"], skipped=False, score=s, remainder=rem,
                                          submitted_round=rnd, dims=(5, 5))
    g.player.run.stats.words_submitted[:] = [hw(30, 20, 1), hw(25, -5, 2),            # encounter 1: 50, cleared
                                             hw(40, 60, 1), hw(70, -10, 3)]           # encounter 2: 100 in 2 words
    g.encounter = None
    last = O._last_encounter(g)
    assert last["best"] == 70 and last["n"] == 2 and last["cleared"]
    assert last["mean"] == pytest.approx(55 / 20) and last["max"] == pytest.approx(70 / 20)
    assert last["unused"] == 2


# ------------------------------------------------------------------------- probes and pruned sets (word list)


def _drive(env, rng, until: str, max_steps=400):
    """Greedy-ish play: best word, leave shops, first boss / pin option."""
    st = env.current()
    for _ in range(max_steps):
        if env.done or env.game.phase == until:
            return st
        ph = env.game.phase
        kinds = {c.action.kind: c for c in reversed(st.cands)}
        a = (kinds.get("submit") or kinds.get("leave") or kinds.get("boss") or kinds.get("pin")
             or kinds.get("michael_pick") or st.cands[int(rng.integers(len(st.cands)))]).action
        if ph == "shop" and "buy" in kinds and rng.random() < 0.5:
            a = kinds["buy"].action
        env.step(a)
        if not env.done:
            st = env.current()
    return st


def test_probe_features_pruned_drafts_and_visibility(cands, monkeypatch):
    monkeypatch.setattr(O, "PROBE_PHASES", ("shop", "boss_draft", "pin_reward"))   # opt-in (CWS_RL_PROBES=1)
    env = CWEnv(cands, Limits(afterstates=False))
    pr = O.prober()
    assert pr is not None and pr.dictionary is cands.dictionary
    env.reset(character="Octacles", crown=0, seed=11)
    rng = np.random.default_rng(0)
    gcol, tcol = O.global_columns(), O.token_columns()
    st = _drive(env, rng, "shop")
    assert env.game.phase == "shop"
    g = st.obs.glob
    assert g[gcol["str_known"]] == 1 and g[gcol["str_next"]] > 0 and g[gcol["last_known"]] == 1
    assert g[gcol["last_cleared"]] == 1 and np.isfinite(g).all() and np.isfinite(st.obs.tok_feat).all()
    # hidden state resampled: same observation, probes included
    a, b = determinize(clone(env.game), "one"), determinize(clone(env.game), "two")
    oa = O.observe(a, shop_actions=env.shop_actions)
    O._PROBER = O.Prober(cands)   # recomputed from scratch on the other sample, not read from the cache
    try:
        ob = O.observe(b, shop_actions=env.shop_actions)
    finally:
        O._PROBER = pr
    assert np.array_equal(oa.glob, ob.glob) and np.array_equal(oa.tok_feat, ob.tok_feat)
    assert np.array_equal(oa.glob, st.obs.glob)
    # cached: observing the same state again plays no probe
    n0 = pr.probes
    O.observe(env.game)
    assert pr.probes == n0
    st = _drive(env, rng, "boss_draft")
    assert env.game.phase == "boss_draft"
    assert {c.action.kind for c in st.cands} == {"boss"}
    toks = st.obs.tok_feat[st.obs.tok_type == O.TOK_BOSS_OPTION]
    assert len(toks) == len(env.game.boss_options()) and (toks[:, tcol["boss_known"]] == 1).all()
    assert (toks[:, tcol["boss_strength"]] > 0).all() and np.isfinite(st.obs.glob).all()
    padded = CWEnv(cands, Limits(afterstates=False, draft_anytime=True))
    padded.attach(env.game)
    assert {c.action.kind for c in padded.current().cands} > {"boss"}   # the old set, for display
    st = _drive(env, rng, "pin_reward")
    if env.game.phase == "pin_reward":
        assert {c.action.kind for c in st.cands} == {"pin"}
        assert st.obs.glob[gcol["str_known"]] == 1


def test_no_sell_buy_in_shops_by_default():
    env = CWEnv(_NoWords(), Limits(afterstates=False))
    env.reset(character="BonesTheDog", crown=1, seed=5)
    rng = np.random.default_rng(1)
    for _ in range(200):
        if env.done:
            break
        st = env.current()
        assert not any(c.action.kind == "sell_buy" for c in st.cands)
        if env.game.phase in ("boss_draft", "pin_reward"):
            assert {c.action.kind for c in st.cands} <= {"boss", "pin"}
        prog = [c for c in st.cands if c.action.kind not in ("sell", "move", "discard")] or st.cands
        env.step(prog[int(rng.integers(len(prog)))].action)


def test_probe_timing_report(cands, capsys, monkeypatch):
    monkeypatch.setattr(O, "PROBE_PHASES", ("shop", "boss_draft", "pin_reward"))
    """Cost of one probe set at a shop and of a cached repeat (printed; loose bound only)."""
    env = CWEnv(cands, Limits(afterstates=False))
    env.reset(character="WetDennis", crown=2, seed=23)
    _drive(env, np.random.default_rng(2), "shop")
    pr = O.Prober(cands)
    t0 = time.perf_counter()
    f1 = pr.features(env.game)
    t1 = time.perf_counter()
    f2 = pr.features(env.game)
    t2 = time.perf_counter()
    assert f1 == f2 and pr.probes == 1 and pr.hits == 1
    with capsys.disabled():
        print(f"\n  probe set at a stage-{env.game.player.run.stage} shop: {t1 - t0:.3f}s, cached repeat {t2 - t1:.4f}s")
    assert t2 - t1 < 0.05


def test_probes_off_by_default_leave_strength_columns_zero(cands):
    if O.PROBE_PHASES:
        pytest.skip("CWS_RL_PROBES=1 set")
    env = CWEnv(cands, Limits(afterstates=False))
    env.reset(character="Octacles", crown=0, seed=11)
    st = _drive(env, np.random.default_rng(0), "shop")
    gcol = O.global_columns()
    assert st.obs.glob[gcol["str_known"]] == 0 and st.obs.glob[gcol["last_known"]] == 1
