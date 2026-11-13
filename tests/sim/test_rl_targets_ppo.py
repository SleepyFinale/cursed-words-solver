"""Build-conditioned RL: PPO job sampling, evaluation pairing / target pick, exit shard format,
pipeline --v2 stage plan (rl/ppo.py, rl/evaluate.py, rl/pipeline.py)."""

from __future__ import annotations

import json
import random

import numpy as np
import pytest

pytest.importorskip("torch")

from cursed_words_solver.rl import evaluate as E  # noqa: E402
from cursed_words_solver.rl import ppo as P  # noqa: E402
from cursed_words_solver.rl import targets as TG  # noqa: E402

CW = [0.4, 0.6, 0.8, 1, 1.2, 1.4, 1.6, 2.0]


def _jobs(mix, n=300, char_w=None):
    out = []
    for i in range(n):
        rng = random.Random(i * 104729 + 7)
        out.append(P.sample_job(rng, i, 0.25, CW, char_w, None, mix, 0.15 if mix else 0.0))
    return out


def test_sample_job_targets_do_not_move_other_draws():
    base = _jobs(None)
    for mix in ((0.3, 0.4, 0.3), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        tj = _jobs(mix)
        strip = [{k: j[k] for k in ("character", "crown", "quest", "seed")} for j in tj]
        assert strip == [{k: j[k] for k in ("character", "crown", "quest", "seed")} for j in base]
    # curriculum-weighted draws too
    w = {c: 1.0 + i for i, c in enumerate(P.CHARS)}
    a, b = _jobs(None, 100, w), _jobs((0.3, 0.4, 0.3), 100, w)
    assert [(j["character"], j["crown"], j["seed"]) for j in a] == [(j["character"], j["crown"], j["seed"]) for j in b]


def test_sample_job_target_values():
    assert all(j["target"] == TG.FREE and j["shaping"] == 0.0 for j in _jobs(None))
    assert all(j["target"] == TG.FREE for j in _jobs((1.0, 0.0, 0.0)))
    th = _jobs((0.0, 1.0, 0.0))
    for j in th:
        if j["quest"]:
            assert j["target"] == TG.FREE      # quests fix the plan
        else:
            assert j["target"] in TG.THEMES[j["character"]]
    anyp = [j["target"] for j in _jobs((0.0, 0.0, 1.0), 600) if not j["quest"]]
    assert set(anyp) <= set(TG.SAMPLE_PLANS) and len(set(anyp)) >= 10
    mixed = [j["target"] for j in _jobs((0.3, 0.4, 0.3), 1000) if not j["quest"]]
    share_free = mixed.count(TG.FREE) / len(mixed)
    assert 0.2 < share_free < 0.4
    assert _jobs((0.3, 0.4, 0.3), 50) == _jobs((0.3, 0.4, 0.3), 50)   # deterministic per n
    assert all(j["shaping"] == 0.15 for j in _jobs((0.3, 0.4, 0.3), 20))


def test_parse_mix():
    assert P.parse_mix("") is None and P.parse_mix(None) is None
    assert P.parse_mix("0.3,0.4,0.3") == (0.3, 0.4, 0.3)
    with pytest.raises(ValueError):
        P.parse_mix("1,0")
    with pytest.raises(ValueError):
        P.parse_mix("0,0,0")


def test_by_target_stats():
    rows = [{"target": "", "won": True, "on_plan": 0}, {"target": "Red+Blue", "won": False, "on_plan": 4},
            {"target": "Red+Blue", "won": True, "on_plan": 2}]
    bt = P.by_target(rows)
    assert bt["free"] == {"n": 1, "win": 1.0, "on_plan": 0.0}
    assert bt["Red-Blue"] == {"n": 2, "win": 0.5, "on_plan": 3.0}


def test_key_includes_target_and_old_rows_match_free():
    old = {"character": "Spike", "crown": 3, "quest": None, "seed": 7}
    assert E.key(old) == E.key({**old, "target": ""})
    assert E.key(old) != E.key({**old, "target": "Cash"})


def test_eval_jobs_targets_pairing():
    base = E.eval_jobs(per=1, per_quest=1, block=1)
    assert E.eval_jobs(per=1, per_quest=1, block=1, targets=None) == base
    assert all("target" not in j for j in base)
    lst = E.eval_jobs(per=1, per_quest=1, block=1, targets=["", "Red", "Red+Blue"])
    assert len(lst) == 3 * len(base)
    for t in ("", "Red", "Red+Blue"):
        assert [(j["character"], j["crown"], j["quest"], j["seed"]) for j in lst if j["target"] == t] == \
               [(j["character"], j["crown"], j["quest"], j["seed"]) for j in base]
    own = E.eval_jobs(per=1, per_quest=0, block=1, targets="own")
    for ch in P.CHARS:
        ts = {j["target"] for j in own if j["character"] == ch}
        assert ts == {"", *TG.THEMES[ch]}
    assert len({E.key(j) for j in own}) == len(own)


def test_themed_gate_jobs_pair_with_gate():
    th = E.themed_gate_jobs()
    assert len(th) == 8 * sum(len(v) for v in TG.THEMES.values()) == 144
    assert all(j["target"] and j["quest"] is None for j in th)
    gate = {E.key(j)[:4] for j in E.gate_jobs()}
    assert all(E.key(j)[:4] in gate for j in th)          # each themed run has a FREE twin in the gate
    assert not ({E.key(j) for j in th} & {E.key(j) for j in E.gate_jobs()})


def test_table_tuple_keys():
    rows = [{"character": "Spike", "crown": c, "quest": None, "seed": c, "target": t, "won": w, "outcome": 8.0 + w}
            for c in range(2) for t, w in (("", 0), ("Cash", 1))]
    tab = E.table(rows, ("character", "target"))
    assert set(tab) == {("Spike", ""), ("Spike", "Cash")}
    assert tab[("Spike", "Cash")]["win_rate"] == 1.0
    assert set(E.table(rows, "target")) == {"", "Cash"}
    d = E.vs_free(rows, "crown")
    assert set(d) == {(0, "Cash"), (1, "Cash")} and d[(0, "Cash")]["win_diff"] == 1.0


def _rows(ch, target, crowns, n_per, win_t, win_f, out_d=1.0, seed0=0):
    """Paired rows: FREE wins on the first ``win_f`` seeds, target on the first ``win_t`` seeds per crown."""
    rows = []
    for c in crowns:
        for i in range(n_per):
            s = seed0 + 1000 * c + i
            rows.append({"character": ch, "crown": c, "quest": None, "seed": s, "target": target,
                         "won": i < win_t, "outcome": 10.0 + out_d * (i < win_t)})
    return rows


def _free(ch, crowns, n_per, win_f, seed0=0):
    return [{"character": ch, "crown": c, "quest": None, "seed": seed0 + 1000 * c + i, "target": "",
             "won": i < win_f, "outcome": 10.0} for c in crowns for i in range(n_per)]


def test_pick_table_logic():
    rows = []
    # Spike: Cash clearly better everywhere; Curse a little better (passes, smaller win_diff)
    rows += _free("Spike", range(8), 10, 2) + _rows("Spike", "Cash", range(8), 10, 6, 2)
    rows += _rows("Spike", "Curse", range(8), 10, 3, 2)
    # WetDennis: Red better on 0-3, Blue better on 4-7 -> per band
    rows += _free("WetDennis", range(8), 10, 3)
    rows += _rows("WetDennis", "Red", range(4), 10, 8, 3) + _rows("WetDennis", "Red", range(4, 8), 10, 3, 3)
    rows += _rows("WetDennis", "Blue", range(4), 10, 3, 3) + _rows("WetDennis", "Blue", range(4, 8), 10, 8, 3)
    # NinaNix: Void wins more but loses outcome -> FREE
    rows += _free("NinaNix", range(8), 10, 2) + _rows("NinaNix", "Void", range(8), 10, 6, 2, out_d=-5.0)
    # a quest row never counts
    rows += [{"character": "Octacles", "crown": 0, "quest": "X", "seed": 1, "target": "Curse", "won": True, "outcome": 20.0},
             {"character": "Octacles", "crown": 0, "quest": "X", "seed": 1, "target": "", "won": False, "outcome": 1.0}]
    tab = E.pick_table(rows)
    assert set(tab) == set(P.CHARS)
    assert all(set(v) == {"0-3", "4-7"} for v in tab.values())
    assert tab["Spike"] == {"0-3": "Cash", "4-7": "Cash"}
    assert tab["WetDennis"] == {"0-3": "Red", "4-7": "Blue"}
    assert tab["NinaNix"] == {"0-3": "", "4-7": ""}
    assert tab["Octacles"] == {"0-3": "", "4-7": ""}
    assert tab["BonesTheDog"] == {"0-3": "", "4-7": ""}


def test_pick_table_band_fallback_to_overall():
    # Cash passes overall and on 0-3, not on 4-7 alone -> both bands get the overall pick
    rows = _free("Spike", range(8), 10, 2) + _rows("Spike", "Cash", range(4), 10, 7, 2) \
        + _rows("Spike", "Cash", range(4, 8), 10, 2, 2)
    assert E.pick_table(rows)["Spike"] == {"0-3": "Cash", "4-7": "Cash"}


def test_pick_table_band_that_loses_gets_free():
    # Cards passes overall (big win on 0-3) but clearly loses to FREE on 4-7 -> 4-7 stays FREE
    rows = _free("BonesTheDog", range(4), 10, 1) + _rows("BonesTheDog", "Cards", range(4), 10, 9, 1)
    rows += _free("BonesTheDog", range(4, 8), 10, 4) + _rows("BonesTheDog", "Cards", range(4, 8), 10, 2, 4, out_d=-1.0)
    tab = E.pick_table(rows)["BonesTheDog"]
    assert tab == {"0-3": "Cards", "4-7": ""}


def test_episode_items_value_target_is_unshaped():
    from cursed_words_solver.rl import ppo

    # 3 steps, shaped rewards; bonus = shaping * on-plan items before each step
    rew = [0.15, 0.5, 1.0]
    bonus = [0.0, 0.15, 0.15]
    steps = [{"act_type": np.zeros(2, np.int64)} for _ in rew]
    tr = {"steps": steps, "chosen": [0] * 3, "logp": [0.0] * 3, "value": [0.0] * 3, "reward": rew, "bonus": bonus}
    items = ppo.episode_items({"traj": tr}, lam=1.0)
    # shaped return-to-go + bonus = unshaped return-to-go
    shaped = np.cumsum(rew[::-1])[::-1]
    assert [it["ret"] for it in items] == pytest.approx(list(shaped + np.asarray(bonus)))
    # advantages equal those of a shaped value (val - bonus)
    adv, _ = ppo.gae(np.asarray(rew, np.float32), -np.asarray(bonus, np.float32), 1.0)
    assert [it["adv"] for it in items] == pytest.approx(list(adv))
    tr.pop("bonus")
    assert [it["ret"] for it in ppo.episode_items({"traj": tr}, lam=1.0)] == pytest.approx(list(shaped))


def test_evaluate_run_cli_targets_and_out_dir(tmp_path, monkeypatch):
    got = {}

    def fake_run_arm(arm, policy, jobs, workers=7, **kw):
        got.update(arm=arm, jobs=jobs, out_dir=kw.get("out_dir"))
        return []

    monkeypatch.setattr(E, "run_arm", fake_run_arm)
    E.main(["run", "--arm", "x", "--policy", "teacher", "--per", "1", "--per-quest", "0", "--targets", "own",
            "--out-dir", str(tmp_path / "ev")])
    assert got["out_dir"] == tmp_path / "ev" and (tmp_path / "ev").is_dir()
    assert {j["target"] for j in got["jobs"] if j["character"] == "BonesTheDog"} == {"", "Cards"}
    E.main(["run", "--arm", "x", "--policy", "teacher", "--per", "1", "--per-quest", "0", "--targets", "free,Red+Blue"])
    assert {j["target"] for j in got["jobs"]} == {"", "Red+Blue"}


def test_pick_cli_writes_table(tmp_path, monkeypatch):
    rows = _free("Spike", range(8), 10, 2) + _rows("Spike", "Cash", range(8), 10, 6, 2)
    src = tmp_path / "arm.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp_path / "target_table.json"
    E.main(["pick", str(src), "--out", str(out)])
    got = json.loads(out.read_text())
    assert got["version"] == 1 and got["source"] == str(src)
    assert got["table"]["Spike"] == {"0-3": "Cash", "4-7": "Cash"}
    assert got["table"]["HayleyBayles"] == {"0-3": "", "4-7": ""}
    E.main(["targets", str(src)])   # prints, no crash


def test_champion_eval_path(tmp_path):
    d = tmp_path / "ppo1"
    (d / "eval").mkdir(parents=True)
    assert E.champion_eval_path(d) is None
    for u in (0, 25, 100):
        (d / "eval" / f"champion_u{u}.jsonl").write_text("")
    assert E.champion_eval_path(d).name == "champion_u100.jsonl"
    (d / "gates.jsonl").write_text(json.dumps({"update": 125, "promoted": False, "champion_update": 25}) + "\n")
    assert E.champion_eval_path(d).name == "champion_u25.jsonl"


def _ep(G, Ft, version):
    from cursed_words_solver.rl.actions import n_action_features

    ep = {"glob": np.zeros((2, G), np.float32), "tok_feat": np.zeros((5, Ft), np.float32),
          "act_feat": np.zeros((3, n_action_features()), np.float32)}
    if version is not None:
        ep["obs_version"] = np.asarray([version], np.int16)
    return ep


def test_distill_format_ok_legacy(tmp_path):
    from cursed_words_solver.rl import obs as O

    buf = P.DistillBuffer(tmp_path)
    G, Ft = O.n_global_features(), O.n_token_features()
    assert buf.format_ok(_ep(G, Ft, O.OBS_VERSION))
    for i, (g, t) in enumerate(zip(O.LEGACY_GLOBAL, O.LEGACY_TOKEN)):
        v = P.LEGACY_OBS_VERSION + i
        assert buf.format_ok(_ep(g, t, v)), v
        assert not buf.format_ok(_ep(G, Ft, v))            # version / width mismatch
    assert buf.format_ok(_ep(O.LEGACY_GLOBAL[0], O.LEGACY_TOKEN[0], None))   # no version array = v1
    assert not buf.format_ok(_ep(G, Ft, O.OBS_VERSION + 1))
    assert not buf.format_ok(_ep(O.LEGACY_GLOBAL[1], O.LEGACY_TOKEN[1], O.OBS_VERSION))


# ------------------------------------------------------------------ pipeline --v2

@pytest.fixture()
def home(tmp_path, monkeypatch):
    from cursed_words_solver.rl import pipeline

    monkeypatch.setattr(pipeline, "HOME", tmp_path)
    return tmp_path


def _args(argv=()):
    import argparse

    from cursed_words_solver.rl import pipeline

    # parse like main() does, without running anything
    ns = {}

    def fake_status(args):
        ns["args"] = args
        return {}

    orig = pipeline.status
    pipeline.status = fake_status
    try:
        pipeline.main(["--status", *argv])
    finally:
        pipeline.status = orig
    assert isinstance(ns["args"], argparse.Namespace)
    return ns["args"]


def test_pipeline_v2_stage_plan(home, capsys):
    from cursed_words_solver.rl import pipeline

    args = _args(["--v2", "--teacher2-runs", "2"])
    st = pipeline.v2_stages(args)
    assert [s["name"] for s in st] == ["teacher2", "bc2", "baseline2", "ppo2"]
    assert not any(s["done"] for s in st)
    t2 = st[0]["cmd"]
    assert t2[0] == "cursed_words_solver.rl.teacher" and "--themed" in t2 and str(home / "teacher2") in t2
    bc2 = st[1]["cmd"]
    for flag, val in (("--data", str(home / "teacher2")), ("--dir", str(home / "bc2")),
                      ("--init", str(home / "ppo1" / "champion.pt")), ("--anchor", str(home / "ppo1" / "champion.pt")),
                      ("--anchor-coef", "5.0"), ("--lr", "0.0001"), ("--epochs", "12")):
        assert bc2[bc2.index(flag) + 1] == val
    ppo = st[3]["cmd"]
    for flag, val in (("--dir", str(home / "ppo2")), ("--init", str(home / "bc2" / "best.pt")),
                      ("--kl-ref", "champion"), ("--targets-mix", "0.3,0.4,0.3"), ("--shaping", "0.15"),
                      ("--compare-dir", str(home / "ppo1")), ("--distill-dir", str(home / "exit2"))):
        assert ppo[ppo.index(flag) + 1] == val
    assert "--gate-targets" in ppo
    ex = st[3]["exit"]
    assert ex[ex.index("--dir") + 1] == str(home / "exit2")
    assert ex[ex.index("--policy") + 1] == str(home / "ppo2" / "weights.pt")
    # teacher2 done once its shards exist
    (home / "teacher2" / "shards").mkdir(parents=True)
    for i in range(2):
        (home / "teacher2" / "shards" / f"{i}.npz").write_bytes(b"")
    assert pipeline.v2_stages(args)[0]["done"]
    assert pipeline.main(["--v2", "--dry-run", "--teacher2-runs", "2"]) == 0
    out = capsys.readouterr().out
    assert "teacher2   done" in out and "bc2        todo" in out and "exit2" in out


def test_pipeline_v1_status_has_no_v2(home):
    from cursed_words_solver.rl import pipeline

    args = _args()
    assert "v2" not in pipeline.status(args)
    (home / "ppo2").mkdir()
    assert "v2" in pipeline.status(args)


def test_seed_baseline2(home):
    from cursed_words_solver.rl import pipeline, store

    (home / "ppo1" / "eval").mkdir(parents=True)
    (home / "ppo1" / "champion.pt").write_bytes(b"x")
    rows = [{"character": "Spike", "crown": 0, "quest": None, "seed": 1, "won": True, "outcome": 16.0},
            {"character": "Spike", "crown": 0, "quest": None, "seed": 2, "won": True, "outcome": 16.0, "error": "boom"}]
    store.append_jsonl(home / "ppo1" / "eval" / "champion_u0.jsonl", rows[0])
    store.append_jsonl(home / "ppo1" / "eval" / "champion_u0.jsonl", rows[1])
    assert pipeline.seed_baseline2() == 1
    assert pipeline.seed_baseline2() == 0       # idempotent
    assert (home / "ppo2" / "ppo1_champion.pt").read_bytes() == b"x"
    got = store.read_jsonl(home / "ppo2" / "eval" / "ppo1_champion.jsonl")
    assert len(got) == 1 and E.key(got[0]) == E.key({**rows[0], "target": ""})


# ------------------------------------------------------------------ play

class _NoWords:
    wordlist = None

    def words(self, game, top_n=5):
        return []

    def with_budget(self, budget):
        return self


def test_play_carries_target(tmp_path, monkeypatch):
    from cursed_words_solver.rl import play as PL
    from cursed_words_solver.rl.model import Policy, default_config, save_policy

    import torch

    torch.manual_seed(0)
    path = tmp_path / "w.pt"
    save_policy(Policy(default_config()), path)
    monkeypatch.setattr(PL, "_CANDS", _NoWords())
    job = {"character": "WetDennis", "crown": 0, "seed": 11, "quest": None, "policy": str(path), "greedy": True}
    free = PL.play(dict(job))
    assert not free["error"], free.get("trace")
    assert free["target"] == "" and free["on_plan"] == 0 and free["off_plan"] == 0
    tr = PL.play({**job, "target": "Red+Blue", "shaping": 0.15, "record": True})
    assert not tr["error"], tr.get("trace")
    assert tr["target"] == "Red+Blue" and "on_plan" in tr and "off_plan" in tr
    assert abs(sum(tr["traj"]["reward"]) - tr["outcome"]) < 1e-4      # shaping still telescopes
    assert E.key(tr) != E.key(free) and E.key(tr)[:4] == E.key(free)[:4]
    bad = PL.play({**job, "target": "NotAPlan"})
    assert bad["error"] and bad["target"] == "NotAPlan"


def test_targeted_teacher_plan(monkeypatch):
    from cursed_words_solver.rl import play as PL

    pol = PL.targeted_teacher(_NoWords(), 3, "Red+Blue", "WetDennis", None)
    assert pol.cfg.build_plan == "Red+Blue" and pol.cfg.build_plan_chars == {}
    pol = PL.targeted_teacher(_NoWords(), 3, "Cards", "BonesTheDog", "Chromaphobia")
    assert pol.cfg.build_plan == TG.teacher_plan("Cards", "BonesTheDog", "Chromaphobia")
