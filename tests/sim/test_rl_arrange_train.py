"""Training with auto-arrange (2026-11-21): rl.ppo --arrange (actor episodes, gate jobs, champion rows,
curriculum.json / resume), rl.exit --arrange (both modes) and pipeline --v3-arrange. Off by default:
argv, jobs, rows and cache keys are unchanged."""

from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import evaluate as E  # noqa: E402
from cursed_words_solver.rl import exit as X  # noqa: E402
from cursed_words_solver.rl import pipeline  # noqa: E402
from cursed_words_solver.rl import ppo as P  # noqa: E402
from cursed_words_solver.rl import store  # noqa: E402


class _Async:
    def __init__(self, v):
        self.v = v

    def ready(self):
        return True

    def get(self):
        return self.v


class _Pool:
    """Records apply_async jobs (never runs them); imap_unordered plays ``self.play``."""

    def __init__(self, play=None):
        self.jobs: list[dict] = []
        self.play = play

    def apply_async(self, fn, args):
        self.jobs.append(args[0])
        return _Async({"error": "not run"})

    def imap_unordered(self, fn, jobs):
        for j in jobs:
            yield self.play(j)

    def terminate(self):
        pass


def _row(j, won=True):
    return {"character": j["character"], "crown": j["crown"], "seed": j["seed"], "quest": j.get("quest"),
            "target": j.get("target") or "", "won": won, "outcome": 16.0 if won else 3.0, "error": "",
            "reason": "final_boss", **({"arrange": True} if j.get("arrange") else {})}


# ------------------------------------------------------------------ helpers


def test_arrange_jobs_and_cache_keys_separate():
    jobs = E.gate_jobs(1, 0)[:5]
    assert P.arrange_jobs(jobs, False) == jobs   # off: unchanged
    on = P.arrange_jobs(jobs, True)
    assert all(j["arrange"] for j in on) and not any("arrange" in j for j in jobs)
    assert {E.cache_key(j) for j in on}.isdisjoint({E.cache_key(j) for j in jobs})
    assert [E.key(j) for j in on] == [E.key(j) for j in jobs]   # same pairing key
    rows = [_row(j) for j in jobs] + [_row(j) for j in on]
    assert len(P.same_arrange(rows, False)) == 5 and all(r.get("arrange") for r in P.same_arrange(rows, True))


def test_resolve_arrange_and_command_argv(tmp_path):
    assert P.resolve_arrange(None, None, tmp_path) is False
    assert P.resolve_arrange(True, None, tmp_path) is True
    assert P.resolve_arrange(None, {"arrange": True}, tmp_path) is True
    assert P.resolve_arrange(False, {"arrange": True}, tmp_path) is False   # --no-arrange wins
    (tmp_path / "curriculum.json").write_text(json.dumps({"arrange": True}))
    assert P.resolve_arrange(None, None, tmp_path) is True
    assert P.resolve_arrange(None, {}, tmp_path) is True
    # defaults: command.txt argv as before
    assert P.command_argv(["--dir", "d"], None, 8.0) == ["--dir", "d", "--michael-bonus", "8"]
    assert P.command_argv(["--dir", "d"], None, 8.0, None, False) == ["--dir", "d", "--michael-bonus", "8"]
    assert P.command_argv(["--dir", "d"], None, 8.0, None, True)[-1] == "--arrange"
    assert "--arrange" not in P.command_argv(["--arrange"], None, 8.0, True, True)[1:]


def test_run_arm_does_not_reuse_non_arrange_champion_rows(tmp_path):
    """A champion's non-arrange rows are replayed once for an arrange gate, then cached."""
    jobs = E.gate_jobs(1, 0)[:6]
    for j in jobs:
        store.append_jsonl(tmp_path / "champion_u7.jsonl", _row(j, won=False))
    played = []
    pool = _Pool(lambda j: played.append(j) or _row(j))
    assert len(E.run_arm("champion_u7", "x", jobs, out_dir=tmp_path, pool=pool, verbose=False)) == 6
    assert played == []   # off: the cached rows serve
    rows = E.run_arm("champion_u7", "x", P.arrange_jobs(jobs, True), out_dir=tmp_path, pool=pool, verbose=False)
    assert len(played) == 6 and all(j["arrange"] for j in played)
    assert len(rows) == 6 and all(r["arrange"] and r["won"] for r in rows)
    played.clear()
    E.run_arm("champion_u7", "x", P.arrange_jobs(jobs, True), out_dir=tmp_path, pool=pool, verbose=False)
    assert played == []
    off = E.run_arm("champion_u7", "x", jobs, out_dir=tmp_path, pool=pool, verbose=False)
    assert played == [] and not any(r.get("arrange") or r["won"] for r in off)


# ------------------------------------------------------------------ rl.ppo main


def _ppo_main(tmp_path, monkeypatch, argv):
    from cursed_words_solver.rl.model import Policy, default_config, save_policy
    from cursed_words_solver.sim.game import agent as AG

    init = tmp_path / "init.pt"
    if not init.is_file():
        torch.manual_seed(0)
        save_policy(Policy(default_config()), init, {"update": 0})
    pool = _Pool()
    gates = []
    monkeypatch.setattr(AG, "spawn_pool", lambda *a, **k: pool)
    monkeypatch.setattr(E, "run_arm", lambda arm, pol, jobs, **k: gates.append((arm, jobs)) or [])
    out = tmp_path / "ppo"
    P.main(["--dir", str(out), "--init", str(init), "--workers", "1", "--updates", "0", *argv])
    return out, pool.jobs, gates


def test_ppo_default_jobs_and_gate_unchanged(tmp_path, monkeypatch):
    out, jobs, gates = _ppo_main(tmp_path, monkeypatch, [])
    assert jobs and not any("arrange" in j for j in jobs)
    arm, gj = gates[0]
    assert arm == "champion_u0" and gj == E.gate_jobs(P.GATE_PER, P.GATE_PER_QUEST)
    assert "arrange" not in json.loads((out / "curriculum.json").read_text())
    assert "--arrange" not in (out / "command.txt").read_text()


def test_ppo_arrange_plumbs_and_resume_keeps_it(tmp_path, monkeypatch):
    out, jobs, gates = _ppo_main(tmp_path, monkeypatch, ["--arrange", "--gate-targets"])
    assert jobs and all(j["arrange"] is True for j in jobs)
    arm, gj = gates[0]
    want = E.gate_jobs(P.GATE_PER, P.GATE_PER_QUEST) + E.themed_gate_jobs()
    assert arm == "champion_u0" and len(gj) == len(want) and all(j["arrange"] for j in gj)
    assert {E.cache_key(j) for j in gj}.isdisjoint({E.cache_key(j) for j in want})
    assert json.loads((out / "curriculum.json").read_text())["arrange"] is True
    # resume without the flag: curriculum.json keeps arrange; command.txt reproduces it
    out, jobs, gates = _ppo_main(tmp_path, monkeypatch, [])
    assert all(j["arrange"] for j in jobs) and all(j["arrange"] for j in gates[0][1])
    assert (out / "command.txt").read_text().split()[-1] == "--arrange"
    # --no-arrange turns it off again
    out, jobs, gates = _ppo_main(tmp_path, monkeypatch, ["--no-arrange"])
    assert not any("arrange" in j for j in jobs) and not any("arrange" in j for j in gates[0][1])
    assert "arrange" not in json.loads((out / "curriculum.json").read_text())


# ------------------------------------------------------------------ rl.exit


def test_exit_both_modes_pass_arrange(tmp_path, monkeypatch):
    from cursed_words_solver.rl import play as PL
    from cursed_words_solver.sim.game import agent as AG

    pol = tmp_path / "ppo" / "weights.pt"
    pol.parent.mkdir()
    pol.write_bytes(b"x")
    seen = []

    def fake_play(job):
        seen.append(job)
        return {"character": job["character"], "crown": job["crown"], "seed": job["seed"], "quest": job.get("quest"),
                "won": False, "error": "", "traj": {}}

    class Pool:
        def apply_async(self, fn, args):
            return _Async(fn(*args))

        def terminate(self):
            pass

    monkeypatch.setattr(PL, "play", fake_play)
    monkeypatch.setattr(AG, "spawn_pool", lambda *a, **k: Pool())
    base = ["--policy", str(pol), "--workers", "1", "--runs", "3", "--curriculum", "-"]
    X.main(["--dir", str(tmp_path / "e0"), *base])
    assert len(seen) == 3 and not any("arrange" in j for j in seen)
    seen.clear()
    X.main(["--dir", str(tmp_path / "e1"), *base, "--arrange"])
    assert len(seen) == 3 and all(j["arrange"] is True for j in seen)

    def fake_early(job):
        seen.append(job)
        return {"character": job["character"], "crown": job["crown"], "seed": job["seed"], "quest": None,
                "won": False, "error": "", "cpu": 1.0, "label_cpu": 0.0, "labels": [], "label_steps": []}

    monkeypatch.setattr(X, "early_run", fake_early)
    monkeypatch.setattr(PL, "init_worker", lambda *a, **k: None)
    seen.clear()
    early = ["--mode", "early", *base[:2], "--workers", "0", "--runs", "3", "--curriculum", "-"]
    X.main([*early, "--dir", str(tmp_path / "x0")])
    assert len(seen) == 3 and not any("arrange" in j for j in seen)
    seen.clear()
    X.main([*early, "--dir", str(tmp_path / "x1"), "--arrange"])
    assert len(seen) == 3 and all(j["arrange"] is True for j in seen)


def test_early_run_env_arranges(monkeypatch):
    """early_run builds its CWEnv with the job's arrange (search._sub_env copies it to rollouts)."""
    from cursed_words_solver.rl import env as EV

    made = []

    class Stop(Exception):
        pass

    class FakeEnv:
        def __init__(self, cands, *a, arrange=False, **k):
            made.append(arrange)
            raise Stop

    monkeypatch.setattr(EV, "CWEnv", FakeEnv)
    for job, want in (({}, False), ({"arrange": True}, True)):
        res = X.early_run({"character": "SockHead", "crown": 0, "seed": 1, "policy": "p", **job})
        assert made[-1] is want and "Stop" in res["error"]
        assert bool(res.get("arrange")) is want


# ------------------------------------------------------------------ pipeline


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


def _fake_ppo2(home):
    p2 = home / "ppo2"
    (p2 / "eval").mkdir(parents=True)
    torch.save({"config": {}, "state": {}, "extra": {"update": 425}}, p2 / "champion.pt")
    (p2 / "curriculum.json").write_text(json.dumps({"targets_mix": [0.8, 0.1, 0.1], "pivot": None,
                                                    "michael_bonus": 2.0}))
    store.append_jsonl(p2 / "history.jsonl", {"update": 668, "kl_coef": 0.0214, "ent_coef_next": 0.00228})
    store.append_jsonl(p2 / "gates.jsonl", {"update": 425, "promoted": True, "champion_update": 325})
    for j in pipeline.v2_gate_jobs(_pargs(["--v3"])):
        store.append_jsonl(p2 / "eval" / "champion_u425.jsonl", _row(j))
        store.append_jsonl(p2 / "eval" / "ppo1_champion.jsonl", _row(j, won=False))
    (home / "ppo1" / "eval").mkdir(parents=True)


def test_pipeline_v3_arrange_flags(home, capsys):
    _fake_ppo2(home)
    off = _pargs(["--v4"])
    on = _pargs(["--v4", "--v3-arrange"])
    p_off, p_on = pipeline.v3_ppo_args(off), pipeline.v3_ppo_args(on)
    e_off, e_on = pipeline.v3_exit_args(off), pipeline.v3_exit_args(on)
    x_off, x_on = pipeline.v3_exit3_args(off), pipeline.v3_exit3_args(on)
    for a, b in ((p_off, p_on), (e_off, e_on), (x_off, x_on)):
        assert "--arrange" not in a and b == a + ["--arrange"]
    assert pipeline.main(["--v4", "--dry-run"]) == 0
    out_off = capsys.readouterr().out
    assert "--arrange" not in out_off and "arrange   on" not in out_off and "seed      ok" in out_off
    assert pipeline.main(["--v4", "--v3-arrange", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "arrange   on" in out and "seed      replay (arrange)" in out
    assert sum(ln.rstrip().endswith(" --arrange") for ln in out.splitlines()) == 3   # ppo3, exit2, exit3


def test_pipeline_v3_arrange_seed_copies_no_champion_rows(home):
    _fake_ppo2(home)
    args = _pargs(["--v3", "--v3-arrange"])
    info = pipeline.seed_ppo3(args)
    assert info["champion_rows"] == "replay (arrange)"
    assert not (home / "ppo3" / "eval" / "champion_u0.jsonl").is_file()
    assert (home / "ppo3" / "eval" / "ppo1_champion.jsonl").is_file()   # baseline rows (rl.ppo pairs same-arrange only)
    assert pipeline.v3_stages(args)[0]["done"]
    assert all(j["arrange"] for j in pipeline.v3_gate_jobs(args))
    assert pipeline.v3_gate_jobs(_pargs(["--v3"])) == pipeline.v2_gate_jobs(_pargs(["--v3"]))


def test_pipeline_v3_resume_keeps_arrange_from_ppo3_curriculum(home):
    _fake_ppo2(home)
    (home / "ppo3").mkdir()
    (home / "ppo3" / "curriculum.json").write_text(json.dumps({"arrange": True, "targets_mix": [0.8, 0.1, 0.1]}))
    args = _pargs(["--v4"])
    assert pipeline.v3_arrange(args)
    assert pipeline.v3_ppo_args(args)[-1] == "--arrange" and pipeline.v3_exit_args(args)[-1] == "--arrange"
    assert pipeline.v3_exit3_args(args)[-1] == "--arrange"
