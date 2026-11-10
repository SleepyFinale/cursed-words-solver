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

    from cursed_words_solver.rl.ppo import DistillBuffer, ppo_update

    env = CWEnv(_NoWords())
    st = env.reset(character="WetDennis", crown=0, seed=2)
    pk = pack(st)
    (tmp_path / "shards").mkdir()
    data = store.pack_episode([pk, pk], {"chosen": np.array([1, 0], np.int16),
                                         "margin": np.zeros(2, np.float32), "changed": np.array([True, False])})
    store.atomic_write_bytes(tmp_path / "shards" / "1.npz", data)
    buf = DistillBuffer(tmp_path)
    assert buf.refresh() == 2 and buf.refresh() == 0
    m = Policy(default_config())
    opt = torch.optim.AdamW(m.parameters(), lr=1e-3)
    item = {**pk, "chosen": 0, "logp": -1.0, "adv": 0.5, "ret": 1.0}
    args = argparse.Namespace(epochs=1, mb=4, temperature=1.0, clip=0.2, vf_coef=0.5, ent_coef=0.0, kl_coef=0.0,
                              target_kl=1.0, max_grad=0.5, distill_coef=0.5, distill_mb=4)
    out = ppo_update(m, None, opt, [item, item], args, torch.device("cpu"), buf)
    assert out["distill"] > 0
