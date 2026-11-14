"""rl.exit job settings: explicit flags win over PPO's curriculum.json; search JSON merge; shard run columns."""

from __future__ import annotations

import argparse
import json
import random

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import exit as X  # noqa: E402
from cursed_words_solver.rl import ppo as P  # noqa: E402
from cursed_words_solver.rl import store  # noqa: E402

CURR = {"enabled": True, "char": {"SockHead": 2.0}, "quest": {"Bullseye": 2.0}, "quest_share": 0.25,
        "crown_weights": [0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 2.0], "targets_mix": [0.8, 0.1, 0.1],
        "target_curriculum": True, "target": {"SockHead": {"Curse": 1.0}}, "pivot": [0.5, 2, 4]}


def _args(**kw):
    a = {"quest_share": None, "crown_weights": None, "targets_mix": None, "pivot": ""}
    a.update(kw)
    return argparse.Namespace(**a)


def test_inherits_curriculum_when_unset():
    s = X.resolve_settings(_args(), CURR)
    assert s["quest_share"] == 0.25 and s["crown_weights"] == CURR["crown_weights"]
    assert s["targets_mix"] == (0.8, 0.1, 0.1) and s["pivot"] == (0.5, 2, 4)
    assert s["char"] == CURR["char"] and s["quest"] == CURR["quest"] and s["target"] == CURR["target"]


def test_explicit_flags_override_curriculum():
    s = X.resolve_settings(_args(quest_share=0.0, crown_weights="0,0,0,0,0,1,1,1.2", targets_mix="free",
                                 pivot="off"), CURR)
    assert s["quest_share"] == 0.0 and s["crown_weights"] == [0, 0, 0, 0, 0, 1, 1, 1.2]
    assert s["targets_mix"] is None and s["pivot"] is None
    s = X.resolve_settings(_args(targets_mix="0.3,0.4,0.3", pivot="0.2,1,3"), CURR)
    assert s["targets_mix"] == (0.3, 0.4, 0.3) and s["pivot"] == (0.2, 1, 3)
    assert X.resolve_settings(_args(targets_mix="1,0,0"), CURR)["targets_mix"] == (1.0, 0.0, 0.0)


def test_defaults_without_curriculum():
    s = X.resolve_settings(_args(), None)
    assert s["quest_share"] == X.DEFAULT_QUEST_SHARE and s["crown_weights"] == [1.0] * 8
    assert s["targets_mix"] is None and s["pivot"] is None and s["char"] is None and s["target"] is None
    off = X.resolve_settings(_args(), {**CURR, "enabled": False, "target_curriculum": False})
    assert off["char"] is None and off["quest"] is None and off["target"] is None
    assert off["crown_weights"] == CURR["crown_weights"]   # the job mix still follows PPO


def test_focus_jobs_are_free_high_crown():
    s = X.resolve_settings(_args(quest_share=0.0, crown_weights="0,0,0,0,0,1,1,1", targets_mix="free",
                                 pivot="off"), CURR)
    for n in range(300):
        j = P.sample_job(random.Random(n), n, s["quest_share"], s["crown_weights"], s["char"], s["quest"],
                         s["targets_mix"], 0.0, s["target"], s["pivot"])
        assert j["quest"] is None and j["target"] == "" and j["crown"] >= 5 and "pivot_stage" not in j
        assert int(X.run_meta(j)["free"][0]) == 1


def test_bad_flags_fail():
    with pytest.raises(ValueError):
        X.parse_crown_weights("1,2,-1")
    with pytest.raises(ValueError):
        X.parse_crown_weights(",".join(["1"] * 9))
    with pytest.raises(ValueError):
        X.own_mix_arg("0.5,0.5")
    with pytest.raises(ValueError):
        X.parse_search('{"simz": 2}')
    with pytest.raises(ValueError):
        X.parse_search("[2]")


def test_search_merges_onto_default():
    assert X.SEARCH["sims"] == 2
    assert X.parse_search("") == X.SEARCH
    assert X.parse_search('{"sims": 2}') == {"top": 3, "sims": 2, "horizon": 2.0}
    assert X.parse_search('{"sims": 4, "top": 2}') == {"top": 2, "sims": 4, "horizon": 2.0}
    assert X.parse_search('{"mode": "halving"}')["mode"] == "halving"


def test_run_meta():
    m = X.run_meta({"crown": 6, "quest": None, "target": ""})
    assert m["crown"].dtype == np.int16 and m["crown"].tolist() == [6] and m["free"].tolist() == [1]
    assert m["quest"].tolist() == [0]
    assert X.run_meta({"crown": 0, "quest": "Bullseye", "target": ""})["free"].tolist() == [0]
    assert X.run_meta({"crown": 5, "quest": None, "target": "Curse"})["free"].tolist() == [0]
    assert X.run_meta({"crown": 5, "quest": None, "target": "", "pivot_stage": 3})["free"].tolist() == [0]


class _Async:
    def __init__(self, v):
        self.v = v

    def ready(self):
        return True

    def get(self):
        return self.v


class _Pool:
    """Synchronous stand-in for the spawn pool."""

    def apply_async(self, fn, args):
        return _Async(fn(*args))

    def terminate(self):
        pass


def test_main_overrides_and_shard_columns(tmp_path, monkeypatch):
    """End to end with a fake play(): explicit flags beat curriculum.json, shards carry the run
    columns and still load in DistillBuffer."""
    from cursed_words_solver.rl import play as PL
    from cursed_words_solver.rl.env import CWEnv, pack
    from cursed_words_solver.sim.game import agent as AG

    class _NoWords:
        wordlist = None

        def words(self, game, top_n=5):
            return []

    pk = pack(CWEnv(_NoWords()).reset(character="WetDennis", crown=0, seed=2))
    seen = []

    def fake_play(job):
        seen.append(job)
        return {"character": job["character"], "crown": job["crown"], "seed": job["seed"], "quest": job.get("quest"),
                "target": job.get("target", ""), "won": True, "error": "",
                "traj": {"search_steps": [pk, pk], "search_pick": [1, 0], "search_margin": [0.5, 0.5],
                         "search_changed": [True, False]}}

    monkeypatch.setattr(PL, "play", fake_play)
    monkeypatch.setattr(AG, "spawn_pool", lambda *a, **k: _Pool())
    pol = tmp_path / "ppo" / "weights.pt"
    pol.parent.mkdir()
    pol.write_bytes(b"x")
    (pol.parent / "curriculum.json").write_text(json.dumps(CURR))
    out = tmp_path / "exit"
    X.main(["--dir", str(out), "--policy", str(pol), "--workers", "1", "--runs", "12",
            "--search", '{"sims": 2}', "--crown-weights", "0,0,0,0,0,1,1,1", "--quest-share", "0",
            "--targets-mix", "free", "--pivot", "off"])
    assert len(seen) == 12
    for j in seen:
        assert j["search"] == {"top": 3, "sims": 2, "horizon": 2.0}
        assert j["quest"] is None and j["target"] == "" and j["crown"] >= 5 and "pivot_stage" not in j
    rows = store.read_jsonl(out / "runs.jsonl")
    assert len(rows) == 12 and all(r["free"] for r in rows)
    ep = store.load_episode(out / "shards" / f"{seen[0]['seed']}.npz")
    assert ep["crown"].tolist() == [seen[0]["crown"]] and ep["free"].tolist() == [1] and ep["quest"].tolist() == [0]
    buf = P.DistillBuffer(out)
    assert buf.refresh() == 2 * 12 and buf.n_skipped == 0

    # unset flags: inherit curriculum.json (quest share 0.25, its crown weights, mix 0.8,0.1,0.1, pivot)
    seen.clear()
    out2 = tmp_path / "exit_inherit"
    X.main(["--dir", str(out2), "--policy", str(pol), "--workers", "1", "--runs", "200"])
    assert len(seen) == 200 and seen[0]["search"] == X.SEARCH
    assert any(j["quest"] for j in seen) and any(j.get("pivot_stage") for j in seen)
    assert any(j["target"] for j in seen) and {j["crown"] for j in seen if not j["quest"]} >= {0, 7}


def test_michael_bonus_follows_curriculum():
    from cursed_words_solver.sim.game import features as F

    assert X.MICHAEL_BONUS == F.MICHAEL_BONUS
    assert X.resolve_settings(_args(), CURR)["michael_bonus"] == F.MICHAEL_BONUS   # old curriculum: the game's 8
    assert X.resolve_settings(_args(), None)["michael_bonus"] == F.MICHAEL_BONUS
    assert X.resolve_settings(_args(), {**CURR, "michael_bonus": 2.0})["michael_bonus"] == 2.0
    base = X.parse_search("")
    assert X.job_search(base, {}, 8.0) is base                      # unchanged jobs at the game's bonus
    assert X.job_search(base, {}, 2.0) == {**base, "michael_bonus": 2.0}
    own = {"michael_bonus": 5.0}
    s = X.parse_search(json.dumps(own))
    assert X.job_search(s, own, 2.0)["michael_bonus"] == 5.0          # --search wins


def test_rollout_passes_michael_bonus(monkeypatch):
    """rollout_value scores the end state with potential(..., michael_bonus=SearchConfig.michael_bonus)."""
    from cursed_words_solver.rl import search as S
    from cursed_words_solver.rl.env import CWEnv
    from cursed_words_solver.sim.game import features as F

    class _NoWords:
        wordlist = None

        def words(self, game, top_n=5):
            return []

    class _Actor:
        def evaluate(self, packed):
            return None, 0.0, None

    env = CWEnv(_NoWords())
    st = env.reset(character="WetDennis", crown=0, seed=2)
    got = []
    monkeypatch.setattr(S, "potential", lambda g, **kw: got.append(kw.get("michael_bonus")) or 0.0)
    act = st.cands[0].action
    S.rollout_value(env, act, _Actor(), "k", S.SearchConfig(horizon=0.0))
    S.rollout_value(env, act, _Actor(), "k", S.SearchConfig(horizon=0.0, michael_bonus=2.0))
    assert got == [F.MICHAEL_BONUS, 2.0]
    assert S.SearchConfig().michael_bonus == F.MICHAEL_BONUS
