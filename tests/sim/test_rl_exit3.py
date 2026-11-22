"""exit3 (judge plan D2a): race search (rl/search.py mode "race"), the early-mode collector
(rl/exit.py --mode early), exit3 distillation (rl/ppo.py --distill2-*, RaceDistillBuffer,
--distill-changed-margin) and the pipeline's --exit-mode early. All off by default."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import exit as X  # noqa: E402
from cursed_words_solver.rl import pipeline  # noqa: E402
from cursed_words_solver.rl import ppo  # noqa: E402
from cursed_words_solver.rl import search as S  # noqa: E402
from cursed_words_solver.rl import store  # noqa: E402
from cursed_words_solver.rl.env import CWEnv, pack  # noqa: E402
from cursed_words_solver.rl.model import Policy, default_config  # noqa: E402


class _NoWords:
    wordlist = None

    def words(self, game, top_n=5):
        return []


def _noise(key: str) -> float:
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=4).digest(), "little") / 2**32 * 10 - 5


class _FakeSearcher(S.Searcher):
    """Rollout value = shared future noise (keyed on ``{key}|{s}``) + ``offset[i]`` (+ own noise
    ``indep`` x per-candidate noise): records every (candidate, key, cfg) rolled."""

    def __init__(self, cfg, offset, indep=0.0):
        super().__init__(actor=None, cfg=cfg)
        self.offset, self.indep, self.calls = offset, indep, []

    def _roll(self, env, st, i, key, s, cfg=None):
        self.stats["rollouts"] += 1
        k = f"{key}|{s}"
        self.calls.append((i, k, cfg))
        return _noise(k) + self.offset[i] + self.indep * _noise(f"{k}|own{i}")


def _st(n):
    return SimpleNamespace(cands=[SimpleNamespace(action=SimpleNamespace(kind="buy")) for _ in range(n)])


_ENV = SimpleNamespace(game=None)
_CFG = dict(mode="race", race_horizon=5.0)


# ------------------------------------------------------------------ race search

def test_race_defaults_off_and_unchanged():
    c = S.SearchConfig()
    assert (c.mode, c.top, c.sims, c.horizon, c.max_steps, c.k, c.min_prob) == ("topk", 3, 4, 2.0, 120, 3, 0.04)
    assert (c.race_n0, c.race_step, c.race_n_max, c.race_drop_t, c.race_stop_t, c.race_max_steps) == (8, 4, 32, -2.5, 2.5, 400)


def test_race_candidates_top_k_by_prob():
    p = np.asarray([0.1, 0.5, 0.03, 0.2, 0.17])
    assert S.race_candidates(p, 3, 0.04) == [1, 3, 4]
    assert S.race_candidates(p, 2, 0.04) == [1, 3]
    assert S.race_candidates(np.asarray([0.97, 0.03]), 3, 0.04) == [0]
    sr = S.Searcher(None, S.SearchConfig(**_CFG))
    assert sr.candidates(p, "a") == sr.candidates(p, "b") == [1, 3, 4]   # no key dependence


def test_race_crn_keys_shared_and_rollout_cfg():
    p = np.asarray([0.5, 0.3, 0.2])
    sr = _FakeSearcher(S.SearchConfig(**_CFG), {0: 0.0, 1: 0.0, 2: 0.0}, indep=1.0)
    info = sr.race(_ENV, _st(3), p, "K")
    by = {}
    for i, k, cfg in sr.calls:
        by.setdefault(i, []).append(k)
        assert cfg.horizon == 5.0 and cfg.max_steps == 400 and cfg.mode == "race"
    n = min(len(v) for v in by.values())
    for i, ks in by.items():
        assert ks == [f"K|{s}" for s in range(len(ks))]   # future s = key|s, in order
        assert ks[:n] == by[0][:n]                         # same futures across candidates
    assert info["n"] == {i: len(v) for i, v in by.items()}


def test_race_deterministic():
    p = np.asarray([0.45, 0.35, 0.2])
    a = _FakeSearcher(S.SearchConfig(**_CFG), {0: 0.0, 1: 0.3, 2: -0.2}, indep=1.0).race(_ENV, _st(3), p, "D")
    b = _FakeSearcher(S.SearchConfig(**_CFG), {0: 0.0, 1: 0.3, 2: -0.2}, indep=1.0).race(_ENV, _st(3), p, "D")
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_race_clear_winner_drops_rest_confident():
    p = np.asarray([0.6, 0.3, 0.1])
    sr = _FakeSearcher(S.SearchConfig(**_CFG), {0: 0.0, 1: 5.0, 2: -5.0})
    info = sr.race(_ENV, _st(3), p, "W")
    assert info["leader"] == 1 and info["policy"] == 0 and info["pick"] == 1
    assert info["confident"] and info["alive"] == [1] and info["runner_up"] is None
    assert info["n"] == {0: 8, 1: 8, 2: 8} and info["rounds"] == 1
    assert info["diff"][0] == pytest.approx(-5.0) and info["diff_pol"] == pytest.approx(5.0)
    assert info["t"][0] < -100 and info["t_pol"] > 100
    assert sr.stats["rollouts"] == 24


def test_race_close_call_runs_to_n_max_unconfident():
    p = np.asarray([0.5, 0.4])
    sr = _FakeSearcher(S.SearchConfig(**_CFG), {0: 0.0, 1: 0.0}, indep=1.0)
    info = sr.race(_ENV, _st(2), p, "C")
    if info["confident"]:   # by chance separated: then the stop rule must hold
        assert abs(info["t2"]) >= 2.5 or info["runner_up"] is None
    else:
        assert info["n"] == {0: 32, 1: 32} and info["pick"] == info["policy"] == 0
        assert info["rounds"] == 1 + (32 - 8) // 4


def test_race_early_stop_on_separation():
    p = np.asarray([0.5, 0.4])
    sr = _FakeSearcher(S.SearchConfig(**_CFG), {0: 0.0, 1: 1.0}, indep=0.3)
    info = sr.race(_ENV, _st(2), p, "E")
    # with two candidates the drop rule (t < -2) ends the race before |t| reaches 2.5: one survivor
    assert info["confident"] and info["leader"] == 1 and (info["alive"] == [1] or abs(info["t2"]) >= 2.5)
    assert info["n"][0] == info["n"][1] < 32


def test_race_horizon_through_next_boss():
    from cursed_words_solver.sim.game.features import progress
    from cursed_words_solver.sim.game.run import Node

    g = SimpleNamespace(player=SimpleNamespace(run=SimpleNamespace(stage=2, node=Node.SHOP_TWO)), won=None)
    assert S.race_horizon(g, S.SearchConfig(mode="race")) == 3 * 2 + 6 - progress(g)
    assert S.race_horizon(g, S.SearchConfig(mode="race", race_horizon=3.0)) == 3.0


def test_choose_race_mode_sets_last(monkeypatch):
    sr = _FakeSearcher(S.SearchConfig(**_CFG), {0: 0.0, 1: 5.0})
    sr.actor = SimpleNamespace(evaluate=lambda pk: (np.asarray([0.6, 0.4]), 0.0, None))
    monkeypatch.setattr(S, "wants_search", lambda *a: True)
    assert sr.choose(_ENV, _st(2), None, "X") == 1
    assert sr.last["confident"] and sr.stats["changed"] == 1


# ------------------------------------------------------------------ exit --mode early

def test_char_weights_and_eligible():
    assert X.parse_char_weights("") is None
    assert X.parse_char_weights("SockHead=3,NinaNix=2") == {"SockHead": 3.0, "NinaNix": 2.0}
    with pytest.raises(ValueError):
        X.parse_char_weights("Nobody=2")
    from cursed_words_solver.sim.game.run import Game, RunConfig

    g = Game(RunConfig(character="Octacles", ascension=0, seed=3))
    from cursed_words_solver.rl.play import step_label

    stage, kind = step_label(g)
    p = np.asarray([0.5, 0.45, 0.05])
    got = X.early_eligible(g, p)
    assert got == ((stage, kind) if kind in X.EARLY_KINDS and 1 <= stage <= 3 else None)
    assert X.early_eligible(g, np.asarray([0.97, 0.03])) is None
    assert X.heldout(70_000_000) and X.heldout(70_000_007) and not X.heldout(70_000_001)


def _pk():
    return pack(CWEnv(_NoWords()).reset(character="WetDennis", crown=0, seed=2))


def _lab(leader, policy, conf, cands=(0, 1, 2)):
    return {"step": 3, "stage": 1, "kind": "shop", "cands": list(cands), "q": [1.0, 2.0, 0.5][: len(cands)],
            "n": [8] * len(cands), "se": [0.0, 0.3, 0.2][: len(cands)], "t": [0.0] * len(cands), "leader": leader,
            "policy": policy, "pick": leader if conf else policy, "changed": leader != policy, "conf": conf,
            "t2": -3.0 if conf else -1.0, "t_pol": 2.0, "diff_pol": 1.0, "margin": 1.0, "h2_pick": -1, "cpu": 1.0}


def test_early_shard_schema():
    pk = _pk()
    labs = [_lab(1, 0, True), _lab(0, 0, True), _lab(2, 0, False, (0, 2))]
    data = X.early_shard({"labels": labs, "label_steps": [pk] * 3}, {"crown": 5, "quest": None})
    import io

    with np.load(io.BytesIO(data)) as z:
        ep = {k: z[k] for k in z.files}
    for k in ("chosen", "policy", "changed", "conf", "t", "t_pol", "diff_pol", "n", "margin", "stage", "kind",
              "step", "h2_pick", "q_idx", "q_val", "q_n", "q_se", "obs_version", "crown", "quest", "free"):
        assert k in ep, k
    assert ep["chosen"].tolist() == [1, 0, 2] and ep["policy"].tolist() == [0, 0, 0]
    assert ep["changed"].tolist() == [True, False, True] and ep["conf"].tolist() == [True, True, False]
    assert ep["q_idx"].shape == (3, 3) and ep["q_idx"][2].tolist() == [0, 2, -1]
    assert ep["n"].tolist() == [8, 8, 8] and ep["crown"].tolist() == [5]
    assert X.early_shard({"labels": [], "label_steps": []}, {}) is None


def test_main_early_end_to_end(tmp_path, monkeypatch):
    """Fake early_run: jobs carry the early settings, seeds % 7 go to heldout, shards load in
    RaceDistillBuffer with per-label weights and in the exit2 DistillBuffer (format compatible)."""
    from cursed_words_solver.rl import play as PL

    pk = _pk()
    seen = []

    def fake(job):
        seen.append(job)
        return {"character": job["character"], "crown": job["crown"], "seed": job["seed"], "quest": None,
                "won": False, "error": "", "cpu": 60.0, "label_cpu": 30.0,
                "labels": [_lab(1, 0, True), _lab(0, 0, True), _lab(2, 0, False)], "label_steps": [pk] * 3}

    monkeypatch.setattr(X, "early_run", fake)
    monkeypatch.setattr(PL, "init_worker", lambda *a, **k: None)
    pol = tmp_path / "ppo" / "weights.pt"
    pol.parent.mkdir()
    pol.write_bytes(b"x")
    out = tmp_path / "exit3"
    X.main(["--mode", "early", "--dir", str(out), "--policy", str(pol), "--workers", "0", "--runs", "10",
            "--crown-weights", "0,0,0,0,1,1,1,1", "--quest-share", "0", "--targets-mix", "free", "--pivot", "off",
            "--char-weights", "SockHead=100", "--curriculum", "-"])
    assert len(seen) == 10
    for j in seen:
        assert j["search"]["mode"] == "race" and j["labels"] == 3 and j["per_stage"] == 1 and j["follow"] == "policy"
        assert j["crown"] >= 4 and j["quest"] is None and not j.get("keyed") and not j["h2"]
        assert j["seed"] >= X.EXIT3_SEED0
    assert sum(j["character"] == "SockHead" for j in seen) >= 8
    held = [j["seed"] for j in seen if j["seed"] % 7 == 0]
    assert held and all((out / "heldout" / "shards" / f"{s}.npz").is_file() for s in held)
    assert not any((out / "shards" / f"{s}.npz").is_file() for s in held)
    train = [j["seed"] for j in seen if j["seed"] % 7]
    assert all((out / "shards" / f"{s}.npz").is_file() for s in train)
    rows = store.read_jsonl(out / "runs.jsonl")
    assert len(rows) == len(train) and rows[0]["n_labels"] == 3 and "label_steps" not in rows[0]
    st = json.loads((out / "state.json").read_text())
    assert st["saved"] == len(train) and st["heldout"] == len(held)

    rb = ppo.RaceDistillBuffer(out)
    assert rb.refresh() == 2 * len(train) and rb.n_skipped == 0
    assert sorted({it["w"] for it in rb.items}) == [0.3, 1.0]
    assert rb.n_changed == len(train)
    db = ppo.DistillBuffer(out)   # exit2 reader: same format, loads too
    db.refresh()
    assert db.n_skipped == 0 and len(db.items) > 0


def test_race_buffer_skips_exit2_shards(tmp_path):
    pk = _pk()
    d = tmp_path / "e2" / "shards"
    d.mkdir(parents=True)
    from cursed_words_solver.rl.obs import OBS_VERSION

    store.atomic_write_bytes(d / "1.npz", store.pack_episode([pk, pk], {
        "chosen": np.asarray([1, 0], np.int16), "margin": np.asarray([0.5, 0.2], np.float32),
        "changed": np.asarray([True, False]), "obs_version": np.asarray([OBS_VERSION], np.int16)}))
    rb = ppo.RaceDistillBuffer(tmp_path / "e2")
    assert rb.refresh() == 0 and rb.n_skipped == 1


def test_distill_changed_margin_filter(tmp_path):
    pk = _pk()
    d = tmp_path / "e2" / "shards"
    d.mkdir(parents=True)
    from cursed_words_solver.rl.obs import OBS_VERSION

    store.atomic_write_bytes(d / "1.npz", store.pack_episode([pk] * 3, {
        "chosen": np.asarray([1, 1, 0], np.int16), "margin": np.asarray([0.5, 2.0, 0.2], np.float32),
        "changed": np.asarray([True, True, False]), "obs_version": np.asarray([OBS_VERSION], np.int16)}))
    a, b = ppo.DistillBuffer(tmp_path / "e2"), ppo.DistillBuffer(tmp_path / "e2", changed_margin=0.0)
    assert a.refresh() == b.refresh() == 3
    c = ppo.DistillBuffer(tmp_path / "e2", changed_margin=1.0)
    assert c.refresh() == 2 and [it["w"] for it in c.items] == [1.0, 0.1]


# ------------------------------------------------------------------ ppo distill2

class _Buf:
    def __init__(self, items):
        self.items = items

    def sample(self, n):
        return [self.items[i] for i in np.random.randint(0, len(self.items), size=min(n, len(self.items)))]


@pytest.fixture(scope="module")
def batch():
    env = CWEnv(_NoWords())
    out = []
    for ch, seed in (("WetDennis", 2), ("Octacles", 3)):
        pk = pack(env.reset(character=ch, crown=0, seed=seed))
        for j in range(4):
            out.append({**pk, "chosen": j % len(pk["act_type"]), "logp": -1.0 - 0.1 * j, "adv": 0.5 - 0.3 * j,
                        "ret": 3.0 + j, "vpred": 4.0 + j, "won": 0.0, "michael": 0.0, "phase": "shop"})
    return out


def _args(**kw):
    a = dict(epochs=2, mb=4, temperature=1.0, clip=0.2, vf_coef=0.5, ent_coef=0.01, kl_coef=0.05, target_kl=10.0,
             max_grad=0.5, distill_coef=0.15, distill_mb=4)
    a.update(kw)
    return argparse.Namespace(**a)


def _models(n):
    torch.manual_seed(0)
    m = Policy(default_config())
    ref = copy.deepcopy(m)
    ms = [copy.deepcopy(m) for _ in range(n)]
    return ms, ref, [torch.optim.AdamW(x.parameters(), lr=1e-3) for x in ms]


def _same(a, b):
    return all(torch.equal(x, y) for x, y in zip(a.state_dict().values(), b.state_dict().values()))


def test_distill2_default_off_identical(batch):
    (m0, m1, m2, m3), ref, (o0, o1, o2, o3) = _models(4)
    d1 = _Buf([{**it, "w": 1.0} for it in batch[:3]])
    d2 = _Buf([{**it, "chosen": 1, "w": 1.0} for it in batch])
    outs = []
    for m, o, call in ((m0, o0, lambda m, o: ppo.ppo_update(m, ref, o, batch, _args(), "cpu", d1)),
                       (m1, o1, lambda m, o: ppo.ppo_update(m, ref, o, batch, _args(), "cpu", d1, None)),
                       (m2, o2, lambda m, o: ppo.ppo_update(m, ref, o, batch, _args(distill2_coef=0.0), "cpu", d1, d2)),
                       (m3, o3, lambda m, o: ppo.ppo_update(m, ref, o, batch, _args(distill2_coef=0.5), "cpu", d1, d2))):
        np.random.seed(7)
        outs.append(call(m, o))
    assert _same(m0, m1) and _same(m0, m2) and outs[0] == outs[1] == outs[2]
    assert "distill2" not in outs[0] and "distill2" in outs[3] and not _same(m0, m3)


def test_cli_and_pipeline_defaults():
    import inspect

    src = inspect.getsource(ppo.main)
    for flag, default in (("--distill2-coef", "0.0"), ("--distill2-dir", '""'), ("--distill-changed-margin", "0.0")):
        line = next(ln for ln in src.splitlines() if f'"{flag}"' in ln)
        assert f"default={default}" in line, flag
    src = inspect.getsource(X.main)
    line = next(ln for ln in src.splitlines() if '"--mode"' in ln)
    assert 'default=""' in line


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "HOME", tmp_path)
    monkeypatch.setattr(store, "RL_HOME", tmp_path)
    return tmp_path


def _pargs(argv=()):
    ns = {}
    orig = pipeline.status
    pipeline.status = lambda args: ns.setdefault("args", args) and {}
    try:
        pipeline.main(["--status", *argv])
    finally:
        pipeline.status = orig
    return ns["args"]


def test_pipeline_exit_mode_early(home):
    plain = _pargs(["--v3"])
    cmd = pipeline.v3_ppo_args(plain)
    assert "--distill2-dir" not in cmd and pipeline.v3_exit3_args(plain) is None
    assert pipeline.v3_dirs(plain) == pipeline.V3_DIRS
    assert all("exit3" not in st for st in pipeline.v3_stages(plain))
    for argv in (["--v4"], ["--v3", "--exit-mode", "early"]):
        a = _pargs(argv)
        cmd = pipeline.v3_ppo_args(a)
        assert cmd[cmd.index("--distill2-dir") + 1] == str(home / "exit3")
        assert cmd[cmd.index("--distill2-coef") + 1] == "0.15"
        assert cmd[: len(pipeline.v3_ppo_args(plain))] == pipeline.v3_ppo_args(plain)
        e3 = pipeline.v3_exit3_args(a)
        assert e3[e3.index("--mode") + 1] == "early" and e3[e3.index("--dir") + 1] == str(home / "exit3")
        assert "exit3" in pipeline.v3_dirs(a)
        st = [s for s in pipeline.v3_stages(a) if s["name"] == "ppo3"][0]
        assert st["exit3"] == e3 and st["exit"] == pipeline.v3_exit_args(plain)
    with pytest.raises(SystemExit):
        _pargs(["--exit-mode", "early"])
