"""Self-learning agent plumbing: observation, candidates, env, shards, model, GAE."""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import store  # noqa: E402
from cursed_words_solver.rl.actions import ACTION_TYPES, CandidateBuilder, Limits, cand_for, same_action  # noqa: E402
from cursed_words_solver.rl.env import CWEnv, pack, potential  # noqa: E402
from cursed_words_solver.rl.model import Actor, Policy, collate, default_config  # noqa: E402
from cursed_words_solver.rl.obs import observe  # noqa: E402
from cursed_words_solver.rl.ppo import gae  # noqa: E402
from cursed_words_solver.sim.game.agent import Action, clone, determinize  # noqa: E402
from cursed_words_solver.sim.game.run import Game, RunConfig  # noqa: E402


class _NoWords:
    """Candidates stand-in: no engine search (the word list may be missing in CI)."""

    wordlist = None

    def words(self, game, top_n=5):
        return []


def _game(seed=3, ch="Octacles", crown=2):
    return Game(RunConfig(character=ch, ascension=crown, seed=seed))


def test_observation_ignores_hidden_state():
    g = _game()
    a = determinize(clone(g), "one")
    b = determinize(clone(g), "two")
    oa, ob = observe(a), observe(b)
    assert np.array_equal(oa.glob, ob.glob)
    assert np.array_equal(oa.tok_feat, ob.tok_feat)
    assert np.array_equal(oa.tok_cls, ob.tok_cls)


def test_candidates_cover_every_phase_and_play_a_run():
    env = CWEnv(_NoWords(), Limits(afterstates=True))
    st = env.reset(character="BonesTheDog", crown=1, seed=5)
    seen = set()
    total = 0.0
    import random

    rng = random.Random(0)
    while not env.done:
        assert st.cands, env.game.phase
        for c in st.cands:
            assert ACTION_TYPES[c.atype] == c.action.kind
        c = st.cands[rng.randrange(len(st.cands))]
        seen.add(c.action.kind)
        r, _ = env.step(c.action)
        total += r
        if not env.done:
            st = env.current()
    assert abs(total - env.result()["outcome"]) < 1e-6   # rewards telescope to the outcome
    assert {"skip", "leave"} & seen


def test_cand_for_and_same_action():
    g = _game()
    b = CandidateBuilder(_NoWords())
    c = cand_for(b, g, Action("skip"))
    assert c is not None and same_action(c.action, Action("skip", (), "other label"))


def test_shard_roundtrip(tmp_path):
    env = CWEnv(_NoWords())
    st = env.reset(character="WetDennis", crown=0, seed=2)
    steps = [pack(st)]
    data = store.pack_episode(steps, {"chosen": np.array([0], np.int16), "reward": np.array([1.0], np.float32)})
    p = tmp_path / "x.npz"
    store.atomic_write_bytes(p, data)
    ep = store.load_episode(p)
    s = store.unpack_step(ep, 0)
    assert np.array_equal(s["act_type"], steps[0]["act_type"])
    assert np.allclose(s["tok_feat"], steps[0]["tok_feat"], atol=1e-2)


def test_model_forward_masks_padding():
    env = CWEnv(_NoWords())
    st = env.reset(character="SockHead", crown=3, seed=4)
    pk = pack(st)
    m = Policy(default_config())
    out = m(collate([pk, pk]))
    A = len(pk["act_type"])
    assert out["logits"].shape[0] == 2
    probs, v, aux = Actor(m).evaluate(pk)
    assert len(probs) == A and abs(probs.sum() - 1) < 1e-5


def test_gae_lambda_one_is_return_to_go():
    rew = np.array([1.0, 0.0, 2.0], np.float32)
    val = np.zeros(3, np.float32)
    adv, ret = gae(rew, val, lam=1.0)
    assert np.allclose(ret, [3.0, 2.0, 2.0])


def test_potential_starts_at_zero():
    assert potential(_game()) == pytest.approx(0.0, abs=1e-9)


def test_cand_for_matches_builder_features():
    """A teacher pick the builder missed gets the same features it would have had (no label leak)."""
    env = CWEnv(_NoWords(), Limits(afterstates=True))
    st = env.reset(character="SandySaguaro", crown=3, seed=17)
    checked = 0
    rng = np.random.default_rng(0)
    while not env.done and checked < 400:
        for c in st.cands:
            if c.action.kind in ("submit",):
                continue
            d = cand_for(env.builder, env.game, c.action)
            assert d is not None
            assert np.allclose(d.feat, c.feat), (c.action, d.feat - c.feat)
            checked += 1
        prog = [c for c in st.cands if c.action.kind not in ("sell", "move", "discard")] or st.cands
        env.step(prog[int(rng.integers(len(prog)))].action)
        if env.done:
            break
        st = env.current()
    assert checked >= 10


def test_no_hippo_candidate_for_stamps():
    env = CWEnv(_NoWords(), Limits(afterstates=False))
    env.reset(character="BonesTheDog", crown=1, seed=5)
    rng = np.random.default_rng(1)
    for _ in range(300):
        if env.done:
            break
        st = env.current()
        assert not any(c.action.kind == "hippo" and c.action.args[0] == "stamp" for c in st.cands)
        prog = [c for c in st.cands if c.action.kind not in ("sell", "move", "discard")] or st.cands
        env.step(prog[int(rng.integers(len(prog)))].action)


def test_search_scores_and_assistant_look_ahead():
    """Look-ahead runs on resampled clones and leaves the real game untouched."""
    from cursed_words_solver.rl import assistant as A
    from cursed_words_solver.rl.search import SearchConfig, Searcher

    env = CWEnv(_NoWords(), Limits(afterstates=False))
    st = env.reset(character="BonesTheDog", crown=1, seed=5)
    assert len(st.cands) >= 2
    actor = Actor(Policy(default_config()), greedy=True)
    probs, _, _ = actor.evaluate(pack(st))
    before = observe(env.game)
    sc = Searcher(actor, SearchConfig(top=2, sims=1, horizon=0.5, max_steps=20)).scores(env, st, probs, "t")
    assert 1 <= len(sc) <= 2 and all(np.isfinite(v) for v in sc.values())
    after = observe(env.game)
    assert np.array_equal(before.glob, after.glob) and np.array_equal(before.tok_feat, after.tok_feat)
    adv = A.Advice(phase=env.game.phase, options=[A.Option(c.action, float(p)) for c, p in zip(st.cands, probs)])
    adv.pick = max(adv.options, key=lambda o: o.prob)
    A.SEARCH_DEFAULT, old = {"top": 2, "sims": 1, "horizon": 0.5, "max_steps": 20, "margin": 1.0}, A.SEARCH_DEFAULT
    try:
        A._look_ahead(adv, actor, env, st, probs, _NoWords())
    finally:
        A.SEARCH_DEFAULT = old
    assert adv.pick is not None and any("look-ahead" in o.note for o in adv.options)


def test_distill_buffer_and_update(tmp_path):
    """rl.exit shard format -> DistillBuffer -> a PPO update with the distillation term."""
    import argparse

    from cursed_words_solver.rl.obs import OBS_VERSION
    from cursed_words_solver.rl.ppo import DistillBuffer, ppo_update

    env = CWEnv(_NoWords())
    st = env.reset(character="WetDennis", crown=0, seed=2)
    pk = pack(st)
    (tmp_path / "shards").mkdir()
    ver = np.asarray([OBS_VERSION], np.int16)
    data = store.pack_episode([pk, pk], {"chosen": np.array([1, 0], np.int16), "obs_version": ver,
                                         "margin": np.zeros(2, np.float32), "changed": np.array([True, False])})
    store.atomic_write_bytes(tmp_path / "shards" / "1.npz", data)
    buf = DistillBuffer(tmp_path)
    assert buf.refresh() == 0 and len(buf.items) == 0   # margin 0 = one candidate scored: no label
    data = store.pack_episode([pk, pk], {"chosen": np.array([1, 0], np.int16), "obs_version": ver,
                                         "margin": np.full(2, 0.5, np.float32), "changed": np.array([True, False])})
    store.atomic_write_bytes(tmp_path / "shards" / "2.npz", data)
    assert buf.refresh() == 2 and buf.refresh() == 0
    m = Policy(default_config())
    opt = torch.optim.AdamW(m.parameters(), lr=1e-3)
    item = {**pk, "chosen": 0, "logp": -1.0, "adv": 0.5, "ret": 1.0}
    args = argparse.Namespace(epochs=1, mb=4, temperature=1.0, clip=0.2, vf_coef=0.5, ent_coef=0.0, kl_coef=0.0,
                              target_kl=1.0, max_grad=0.5, distill_coef=0.5, distill_mb=4)
    out = ppo_update(m, None, opt, [item, item], args, torch.device("cpu"), buf)
    assert out["distill"] > 0


def _distill_shard(path, pk, n, *, changed=True, margin=0.5, version=None, mtime=None):
    import os

    extra = {"chosen": np.zeros(n, np.int16), "margin": np.full(n, margin, np.float32),
             "changed": np.full(n, changed, np.bool_)}
    if version is not None:
        extra["obs_version"] = np.asarray([version], np.int16)
    store.atomic_write_bytes(path, store.pack_episode([pk] * n, extra))
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_distill_weights_cap_and_format(tmp_path):
    from cursed_words_solver.rl.ppo import LEGACY_OBS_VERSION, DistillBuffer

    env = CWEnv(_NoWords())
    pk = pack(env.reset(character="WetDennis", crown=0, seed=2))
    assert len(pk["act_type"]) > 1
    d = tmp_path / "shards"
    d.mkdir()
    V = 7   # stands for the current obs version
    _distill_shard(d / "old.npz", pk, 3, changed=True, version=V, mtime=1_000)       # oldest: past the cap
    _distill_shard(d / "same.npz", pk, 2, changed=False, version=V, mtime=2_000)
    _distill_shard(d / "new.npz", pk, 2, changed=True, version=V, mtime=3_000)
    _distill_shard(d / "legacy.npz", pk, 2, mtime=3_500)                              # no obs_version: v1
    _distill_shard(d / "v99.npz", pk, 2, version=99, mtime=4_000)                     # other obs version
    wide = {**pk, "glob": np.zeros(len(pk["glob"]) + 3, np.float32)}
    _distill_shard(d / "wide.npz", wide, 2, version=V, mtime=5_000)                   # other feature width
    buf = DistillBuffer(tmp_path, cap=4, same_w=0.1, version=V)
    assert buf.refresh() == 4
    assert buf.n_skipped == 3 and len(buf.seen) == 6
    assert sorted(it["w"] for it in buf.items) == [0.1, 0.1, 1.0, 1.0] and buf.n_changed == 2
    # a newer shard pushes the oldest decisions out
    _distill_shard(d / "newest.npz", pk, 2, changed=True, version=V, mtime=6_000)
    assert buf.refresh() == 2 and len(buf.items) == 4 and buf.n_changed == 4
    # untagged shards are read while the obs is still at the legacy version
    old = DistillBuffer(tmp_path, cap=100, version=LEGACY_OBS_VERSION)
    assert old.refresh() == 2 and old.n_skipped == 6


def test_distill_loss_is_weighted(tmp_path):
    """A weight-0 label does not enter the distillation loss."""
    import argparse

    from cursed_words_solver.rl.ppo import DistillBuffer, ppo_update

    env = CWEnv(_NoWords())
    pk = pack(env.reset(character="WetDennis", crown=0, seed=2))
    m = Policy(default_config())
    args = argparse.Namespace(epochs=1, mb=4, temperature=1.0, clip=0.2, vf_coef=0.5, ent_coef=0.0, kl_coef=0.0,
                              target_kl=1.0, max_grad=0.5, distill_coef=1.0, distill_mb=8)
    item = {**pk, "chosen": 0, "logp": -1.0, "adv": 0.0, "ret": 0.0}
    buf = DistillBuffer(tmp_path)
    buf.items.extend([{**pk, "chosen": 0, "w": 1.0}, {**pk, "chosen": 1, "w": 0.0}])
    buf.sample = lambda n: list(buf.items)   # both labels in the minibatch
    with torch.no_grad():
        ce0 = float(torch.nn.functional.cross_entropy(m(collate([pk]))["logits"], torch.tensor([0])))
    out = ppo_update(m, None, torch.optim.SGD(m.parameters(), lr=0.0), [item], args, torch.device("cpu"), buf)
    assert out["distill"] == pytest.approx(ce0, abs=1e-3)


def test_search_skips_single_candidate(monkeypatch):
    """One candidate past min_prob: the policy's argmax, no rollouts, no distillation label."""
    from cursed_words_solver.rl import search as S

    class _Actor:
        def evaluate(self, packed):
            return np.array([0.01, 0.97, 0.02]), 0.0, np.zeros(2)

    def boom(*a, **k):
        raise AssertionError("rollout on a single candidate")

    monkeypatch.setattr(S, "wants_search", lambda *a: True)
    monkeypatch.setattr(S, "rollout_value", boom)
    sr = S.Searcher(_Actor(), S.SearchConfig(top=3, min_prob=0.04))
    assert sr.choose(None, None, {}, "k") == 1
    assert sr.last is None and sr.stats["searched"] == 0 and sr.stats["single"] == 1
    # two candidates qualify: it searches and records a label
    monkeypatch.setattr(S, "rollout_value", lambda env, a, actor, key, cfg: 1.0 if a == "c" else 0.0)
    st = type("St", (), {"cands": [type("C", (), {"action": x})() for x in "abc"]})()
    sr = S.Searcher(_Actor(), S.SearchConfig(top=3, min_prob=0.015, sims=1))
    assert sr.choose(None, st, {}, "k") == 2 and sr.last is not None and sr.stats["searched"] == 1


def test_adaptive_entropy_coef():
    from cursed_words_solver.rl.ppo import adapt_ent_coef

    c = 0.003
    up = adapt_ent_coef(c, 0.06, 0.2, 0.3)
    assert up == pytest.approx(c * np.exp(0.3 * 0.7))
    assert adapt_ent_coef(c, 0.4, 0.2, 0.3) == pytest.approx(c * np.exp(-0.3))      # step clipped to lr
    assert adapt_ent_coef(c, 0.2, 0.2, 0.3) == pytest.approx(c)
    assert adapt_ent_coef(0.19, 0.0, 0.2, 0.3) == 0.2 and adapt_ent_coef(1e-4, 5.0, 0.2, 0.3) == 1e-4
    assert adapt_ent_coef(c, 0.0, 0.0, 0.3) == c                                       # target 0 = fixed


def test_curriculum_weights_clamp_and_determinism():
    import random

    from cursed_words_solver.rl.ppo import Curriculum, curriculum_weights, sample_job
    from cursed_words_solver.rl.teacher import CHARS

    rows = [("a", 1)] * 200 + [("b", 0)] * 200 + [("c", i % 2) for i in range(200)]
    w, _ = curriculum_weights(rows, ["a", "b", "c", "d"])
    assert w["a"] == pytest.approx(0.6 / (205 / 210 + 0.1), abs=1e-3)   # prior: 10 pseudo-runs at the mean
    assert w["b"] == 2.0 and w["c"] == pytest.approx(1.0, abs=0.01) and w["d"] == pytest.approx(1.0)
    assert curriculum_weights([("a", 1)] * 100 + [("b", 0)] * 900, ["a"])[0]["a"] == 0.5
    assert curriculum_weights([], ["a"])[0] == {"a": 1.0}
    c = Curriculum()
    for _ in range(50):
        c.add({"character": CHARS[0], "crown": 3, "quest": None, "won": True})
        c.add({"character": CHARS[1], "crown": 3, "quest": None, "won": False})
        c.add({"character": CHARS[2], "crown": 0, "quest": "Sudoku", "won": False})
    c.add({"character": CHARS[0], "crown": 8, "quest": None, "won": False})   # unplayable crown: ignored
    cw = c.weights()
    assert cw["n_char"] == 100 and cw["n_quest"] == 50
    assert cw["char"][CHARS[0]] < 1 < cw["char"][CHARS[1]]
    assert Curriculum(c.state()["chars"], c.state()["quests"]).weights() == cw   # resumes from the checkpoint
    crowns = [0.4, 0.6, 0.8, 1, 1.2, 1.4, 1.6, 2.0]
    jobs = [[sample_job(random.Random(n), n, 0.25, crowns, cw["char"], cw["quest"]) for n in range(300)] for _ in range(2)]
    assert jobs[0] == jobs[1]
    assert sum(j["character"] == CHARS[1] for j in jobs[0]) > sum(j["character"] == CHARS[0] for j in jobs[0])
    # no weights = the old uniform draws
    assert sample_job(random.Random(3), 5, 0.1, crowns) == sample_job(random.Random(3), 5, 0.1, crowns, None, None)


def test_gate_jobs_and_promotion_rule():
    from cursed_words_solver.rl.evaluate import eval_jobs, gate_jobs, key, paired, promote_ok

    old = eval_jobs(per=2, per_quest=1, block=1)
    new = gate_jobs()
    assert len(old) == 202 and len(new) == 404
    assert {key(j) for j in old} <= {key(j) for j in new}   # rows of the 202-run gate stay valid
    base = [{**j, "won": False, "outcome": 10.0} for j in new]
    # 20 extra wins, each +1 outcome: win z = 20 / sqrt(20)
    cand = [{**r, "won": i < 20, "outcome": r["outcome"] + (1.0 if i < 20 else 0.0)} for i, r in enumerate(base)]
    cmp = paired(cand, base)
    assert cmp["win_z"] == pytest.approx(20 / np.sqrt(20), abs=0.01) and promote_ok(cmp)
    assert not promote_ok({**cmp, "outcome_diff": -0.1})
    assert not promote_ok({**cmp, "win_diff": 0.0})
    assert not promote_ok({**cmp, "t": 0.5, "win_z": 0.9})
    assert promote_ok({**cmp, "t": 1.2, "win_z": 0.5})
    assert not promote_ok({"n": 0})


def test_distill_keeps_v1_shards_at_v2(tmp_path):
    """Pre-v2 look-ahead labels (no obs_version, v1 widths) stay usable after the obs widening."""
    from cursed_words_solver.rl.obs import LEGACY_GLOBAL, LEGACY_TOKEN, OBS_VERSION
    from cursed_words_solver.rl.ppo import LEGACY_OBS_VERSION, DistillBuffer

    if OBS_VERSION != LEGACY_OBS_VERSION + 1:
        pytest.skip("only meaningful at obs v2")
    env = CWEnv(_NoWords())
    pk = pack(env.reset(character="WetDennis", crown=0, seed=2))
    v1 = {**pk, "glob": pk["glob"][:LEGACY_GLOBAL[0]], "tok_feat": pk["tok_feat"][:, :LEGACY_TOKEN[0]]}
    d = tmp_path / "shards"
    d.mkdir()
    _distill_shard(d / "v1.npz", v1, 2, changed=True, mtime=1_000)
    buf = DistillBuffer(tmp_path, cap=10)
    assert buf.refresh() == 2 and buf.n_skipped == 0


# --- halving look-ahead (opt-in "mode": "halving") -------------------------------------------

def _fake_step(n):
    return type("St", (), {"cands": [type("C", (), {"action": chr(97 + i)})() for i in range(n)]})()


class _ProbActor:
    def __init__(self, probs):
        self.probs = np.asarray(probs, np.float64)

    def evaluate(self, packed):
        return self.probs, 0.0, np.zeros(2)


def test_halving_gumbel_candidates_reproducible():
    from cursed_words_solver.rl.search import gumbel_candidates

    probs = np.array([0.30, 0.25, 0.20, 0.15, 0.10])
    a = gumbel_candidates(probs, "search|7|12", 3, 0.04)
    assert a == gumbel_candidates(probs, "search|7|12", 3, 0.04)   # same decision key -> same set
    assert len(a) == 3 and a[0] == 0 and len(set(a)) == 3          # argmax always in, first
    sets = {tuple(gumbel_candidates(probs, f"search|7|{s}", 3, 0.04)) for s in range(40)}
    assert len(sets) > 1 and all(s[0] == 0 for s in sets)            # the draw depends on the key
    # the floor: only candidates with prob >= min_prob (plus the argmax) can be drawn
    assert gumbel_candidates(np.array([0.01, 0.97, 0.02]), "k", 3, 0.04) == [1]
    assert set(gumbel_candidates(np.array([0.01, 0.95, 0.04]), "k", 3, 0.04)) == {1, 2}


def test_halving_common_random_numbers_and_rounds(monkeypatch):
    """Every candidate sees the same determinize keys; round 2 extends only the best two."""
    from cursed_words_solver.rl import search as S

    calls = []

    def fake(env, a, actor, key, cfg):
        calls.append((a, key))
        return {"a": 1.0, "b": 0.5, "c": 0.0}[a]

    monkeypatch.setattr(S, "wants_search", lambda *a: True)
    monkeypatch.setattr(S, "rollout_value", fake)
    cfg = S.SearchConfig(mode="halving", k=3, sims0=4, sims1=8, min_prob=0.0)
    sr = S.Searcher(_ProbActor([0.5, 0.3, 0.2]), cfg)
    assert sr.choose(None, _fake_step(3), {}, "dec") == 0
    keys = {}
    for a, k in calls:
        keys.setdefault(a, []).append(k)
    assert keys["a"][:4] == keys["b"][:4] == keys["c"] == [f"dec|{s}" for s in range(4)]
    assert keys["a"] == keys["b"] == [f"dec|{s}" for s in range(12)]   # round 2: same keys for both
    assert sr.stats["rollouts"] == 3 * 4 + 2 * 8 == len(calls)
    L = sr.last
    assert L["n"] == {0: 12, 1: 12, 2: 4} and L["pick"] == 0 and L["policy"] == 0
    assert L["q"][0] == pytest.approx(1.0) and L["se"][0] == 0.0 and set(L["se"]) == {0, 1, 2}
    assert {"scores", "pick", "policy", "margin"} <= set(L) and L["margin"] == pytest.approx(0.5)


def test_halving_switch_rule(monkeypatch):
    """The challenger replaces the policy argmax only at paired t >= switch_t with mean > 0."""
    from cursed_words_solver.rl import search as S

    def sidx(key):
        return int(key.rsplit("|", 1)[1])

    def noisy(env, a, actor, key, cfg):
        return 0.0 if a == "a" else (1.0 if sidx(key) % 2 == 0 else -0.9)

    def clear(env, a, actor, key, cfg):
        return 0.0 if a == "a" else 0.5 + 0.01 * (sidx(key) % 3)

    monkeypatch.setattr(S, "wants_search", lambda *a: True)
    cfg = S.SearchConfig(mode="halving", k=2, sims0=4, sims1=8, switch_t=1.0, min_prob=0.0)
    monkeypatch.setattr(S, "rollout_value", noisy)
    sr = S.Searcher(_ProbActor([0.6, 0.4]), cfg)
    # the challenger's mean is higher (+0.05) but inside the noise: keep the policy pick
    assert sr.choose(None, _fake_step(2), {}, "d") == 0
    assert sr.last["q"][1] > sr.last["q"][0] and sr.last["t"][1] < 1.0 and sr.stats["changed"] == 0
    monkeypatch.setattr(S, "rollout_value", clear)
    sr = S.Searcher(_ProbActor([0.6, 0.4]), cfg)
    assert sr.choose(None, _fake_step(2), {}, "d") == 1 and sr.last["t"][1] >= 1.0 and sr.stats["changed"] == 1
    # same evidence, a threshold above its t: keep the argmax
    t_clear = sr.last["t"][1]
    sr = S.Searcher(_ProbActor([0.6, 0.4]), S.SearchConfig(mode="halving", k=2, sims0=4, sims1=8,
                                                            switch_t=t_clear + 1.0, min_prob=0.0))
    assert sr.choose(None, _fake_step(2), {}, "d") == 0


def test_halving_skips_single_candidate(monkeypatch):
    from cursed_words_solver.rl import search as S

    def boom(*a, **k):
        raise AssertionError("rollout on a single candidate")

    monkeypatch.setattr(S, "wants_search", lambda *a: True)
    monkeypatch.setattr(S, "rollout_value", boom)
    sr = S.Searcher(_ProbActor([0.01, 0.97, 0.02]), S.SearchConfig(mode="halving", min_prob=0.04))
    assert sr.choose(None, _fake_step(3), {}, "k") == 1
    assert sr.last is None and sr.stats["searched"] == 0 and sr.stats["single"] == 1 and sr.stats["rollouts"] == 0


def test_halving_soft_targets_shard_roundtrip(tmp_path):
    """play.soft_target_row -> exit.soft_targets -> shard -> DistillBuffer items carry Q."""
    from cursed_words_solver.rl.exit import soft_targets
    from cursed_words_solver.rl.obs import OBS_VERSION
    from cursed_words_solver.rl.play import soft_target_row
    from cursed_words_solver.rl.ppo import DistillBuffer

    env = CWEnv(_NoWords())
    pk = pack(env.reset(character="WetDennis", crown=0, seed=2))
    assert len(pk["act_type"]) >= 2
    last2 = {"cands": [1, 0], "q": {1: 2.0, 0: 1.5}, "n": {1: 12, 0: 12}, "se": {1: 0.0, 0: 0.2}}
    qi, qv, qn, qs = soft_target_row(last2, 3)
    assert list(qi) == [1, 0, -1] and list(qn) == [12, 12, 0] and qv[0] == 2.0 and qs[1] == pytest.approx(0.2)
    tr = {"search_steps": [pk, pk], "search_q_idx": [qi, qi], "search_q_val": [qv, qv],
          "search_q_n": [qn, qn], "search_q_se": [qs, qs]}
    extra = soft_targets(tr)
    assert extra["q_idx"].shape == (2, 3) and extra["q_val"].dtype == np.float32
    assert soft_targets({"search_steps": [pk]}) == {}   # top-k search: nothing extra
    (tmp_path / "shards").mkdir()
    data = store.pack_episode([pk, pk], {"chosen": np.array([1, 1], np.int16), "margin": np.full(2, 0.5, np.float32),
                                         "changed": np.array([True, True]),
                                         "obs_version": np.asarray([OBS_VERSION], np.int16), **extra})
    store.atomic_write_bytes(tmp_path / "shards" / "1.npz", data)
    buf = DistillBuffer(tmp_path)
    assert buf.refresh() == 2
    it = buf.items[0]
    assert list(it["q_idx"]) == [1, 0] and list(it["q_val"]) == [2.0, 1.5]


def test_soft_distill_loss_limits_and_update(tmp_path):
    """TEMP -> 0 (pick = best Q) and items without Q reduce to the hard CE; the update path runs."""
    import argparse

    from cursed_words_solver.rl.ppo import DistillBuffer, distill_loss, ppo_update, soft_distill_targets

    env = CWEnv(_NoWords())
    pk = pack(env.reset(character="WetDennis", crown=0, seed=2))
    m = Policy(default_config())
    hard = [{**pk, "chosen": 1, "w": 1.0}, {**pk, "chosen": 0, "w": 0.5}]
    soft = [{**pk, "chosen": 1, "w": 1.0, "q_idx": np.array([1, 0]), "q_val": np.array([2.0, 1.5], np.float32)},
            {**pk, "chosen": 0, "w": 0.5}]
    with torch.no_grad():
        logits = m(collate(hard))["logits"]
        h = float(distill_loss(logits, hard, 0.0))
        ce = torch.nn.functional.cross_entropy(logits, torch.tensor([1, 0]), reduction="none")
        assert h == pytest.approx(float((ce * torch.tensor([1.0, 0.5])).sum() / 1.5), abs=1e-6)
        assert float(distill_loss(logits, hard, 0.7)) == pytest.approx(h, abs=1e-5)       # no Q: hard CE
        assert float(distill_loss(logits, soft, 1e-4)) == pytest.approx(h, abs=1e-5)      # TEMP -> 0 limit
        assert float(distill_loss(logits, soft, 2.0)) != pytest.approx(h, abs=1e-4)       # soft targets bite
    t = soft_distill_targets(soft, logits.shape[1], 1.0, 0.5)
    assert t.sum(1) == pytest.approx(np.ones(2)) and t[0, 1] > t[0, 0] > 0 and t[1, 0] == 1.0
    buf = DistillBuffer(tmp_path)
    buf.items.extend(soft)
    item = {**pk, "chosen": 0, "logp": -1.0, "adv": 0.5, "ret": 1.0}
    args = argparse.Namespace(epochs=1, mb=4, temperature=1.0, clip=0.2, vf_coef=0.5, ent_coef=0.0, kl_coef=0.0,
                              target_kl=1.0, max_grad=0.5, distill_coef=0.5, distill_mb=4, distill_soft=1.0,
                              distill_soft_mix=0.5)
    out = ppo_update(m, None, torch.optim.AdamW(m.parameters(), lr=1e-3), [item, item], args, torch.device("cpu"), buf)
    assert out["distill"] > 0


def test_assistant_halving_note(monkeypatch):
    """CWS_AI_SEARCH=halving config: the look-ahead note shows Q, SE and t; a clear win overrides."""
    from cursed_words_solver.rl import assistant as A
    from cursed_words_solver.rl import search as S

    env = CWEnv(_NoWords(), Limits(afterstates=False))
    st = env.reset(character="BonesTheDog", crown=1, seed=5)
    probs = np.zeros(len(st.cands))
    probs[0], probs[1] = 0.55, 0.45
    monkeypatch.setattr(S, "wants_search", lambda *a: True)
    monkeypatch.setattr(S, "rollout_value",
                        lambda env, a, actor, key, cfg: 1.0 + 0.01 * int(key.rsplit("|", 1)[1]) if a is st.cands[1].action else 0.0)
    adv = A.Advice(phase=env.game.phase, options=[A.Option(c.action, float(p)) for c, p in zip(st.cands, probs)])
    adv.pick = adv.options[0]
    monkeypatch.setattr(A, "SEARCH_DEFAULT", {**A.SEARCH_HALVING, "sims0": 2, "sims1": 2})
    A._look_ahead(adv, None, env, st, probs, _NoWords())
    assert adv.pick.action is st.cands[1].action and "vs policy pick" in adv.options[1].note


def test_halving_extends_and_tests_the_round1_challenger(monkeypatch):
    """Round 2 extends the argmax and the round-1 challenger; a clearly better challenger switches
    even when a third candidate's short round-1 mean looks higher afterwards (review 2026-11-11)."""
    from cursed_words_solver.rl import search as S

    def sidx(key):
        return int(key.rsplit("|", 1)[1])

    def roll(env, a, actor, key, cfg):
        s = sidx(key)
        if a == "a":
            return 0.5 if s < 4 else -0.5
        if a == "b":
            return 1.0 if s < 4 else 0.2
        return 0.48

    monkeypatch.setattr(S, "wants_search", lambda *a: True)
    monkeypatch.setattr(S, "rollout_value", roll)
    sr = S.Searcher(_ProbActor([0.5, 0.3, 0.2]), S.SearchConfig(mode="halving", k=3, sims0=4, sims1=8, min_prob=0.0))
    assert sr.choose(None, _fake_step(3), {}, "dec") == 1
    L = sr.last
    assert L["challenger"] == 1 and L["n"] == {0: 12, 1: 12, 2: 4}


def test_assistant_shows_in_game_item_names():
    """Advice text uses the names the game shows: some classes differ (EruptingVolcano is Disco
    Ball, PiggyBank / CoinPurse are swapped), and words played stay as they are."""
    from cursed_words_solver.rl.assistant import display, label
    from cursed_words_solver.sim.game.agent import Action

    assert display("buy EruptingVolcano $14") == "buy Disco Ball $14"
    assert display("buy NewEruptingVolcano $9") == "buy Erupting Volcano $9"
    assert display("sell PiggyBank") == "sell Coin Purse"
    assert display("sell CoinPurse") == "sell Piggy Bank"
    assert display("buy Pinata $7") == "buy Piñata $7"
    assert display("buy CursedVHS $9") == "buy Cursed VHS $9"
    assert display("submit BONE (120)") == "submit BONE (120)"
    assert label(Action("buy", ("stamp", 0), "buy MirrorBall $4")) == "buy Banana $4"
