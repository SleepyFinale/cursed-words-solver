"""pipeline --v3 (rl/pipeline.py): ppo3 forked from the ppo2 champion with the value / aux fixes, its
seeded starting-champion gate rows, the exit2 collector beside it, and that ppo2 is never written."""

from __future__ import annotations

import argparse
import hashlib
import json

import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import pipeline  # noqa: E402
from cursed_words_solver.rl import store  # noqa: E402
from cursed_words_solver.rl.evaluate import cache_key, champion_eval_path, run_arm  # noqa: E402


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


def _val(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def _row(j, won=True):
    return {"character": j["character"], "crown": j["crown"], "seed": j["seed"], "quest": j.get("quest"),
            "target": j.get("target") or "", "won": won, "outcome": 16.0 if won else 3.0, "michael": False,
            "error": "", "reason": "final_boss", "stage": 5}


def _fake_ppo2(home, champ_update=425, stamp=425, n_rows=None):
    """A paused ppo2: champion.pt stamped ``stamp``, gates naming champion ``champ_update``, its gate rows."""
    p2 = home / "ppo2"
    (p2 / "eval").mkdir(parents=True)
    torch.save({"config": {}, "state": {}, "extra": {"update": stamp}}, p2 / "champion.pt")
    (p2 / "STOP").touch()
    (p2 / "curriculum.json").write_text(json.dumps({"targets_mix": [0.8, 0.1, 0.1], "pivot": None,
                                                    "michael_bonus": 2.0}))
    store.append_jsonl(p2 / "history.jsonl", {"update": 668, "kl_coef": 0.0214, "ent_coef": 0.0023,
                                              "ent_coef_next": 0.00228})
    store.append_jsonl(p2 / "gates.jsonl", {"update": champ_update, "promoted": True,
                                            "champion_update": 325})
    store.append_jsonl(p2 / "gates.jsonl", {"update": 650, "promoted": False, "champion_update": champ_update})
    jobs = pipeline.v2_gate_jobs(_pargs(["--v3"]))
    for j in jobs[:n_rows]:
        store.append_jsonl(p2 / "eval" / f"champion_u{champ_update}.jsonl", _row(j))
        store.append_jsonl(p2 / "eval" / "ppo1_champion.jsonl", _row(j, won=False))
    # a stale older champion's rows (must not be the ones copied)
    store.append_jsonl(p2 / "eval" / "champion_u0.jsonl", _row(jobs[0], won=False))
    (home / "ppo1" / "eval").mkdir(parents=True)
    return jobs


def _snapshot(d):
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.rglob("*")) if p.is_file()}


# ------------------------------------------------------------------ commands


def test_v3_ppo_args_mirror_ppo2_plus_fixes(home):
    _fake_ppo2(home)
    args = _pargs(["--v3"])
    v2 = pipeline.v2_ppo_args(args)
    v3 = pipeline.v3_ppo_args(args)
    assert _val(v3, "--dir") == str(home / "ppo3")
    assert _val(v3, "--init") == str(home / "ppo3" / pipeline.V3_INIT)
    # every ppo2 flag is passed with ppo2's value, except --dir / --init
    for i, f in enumerate(v2):
        if f.startswith("--") and f not in ("--dir", "--init"):
            nxt = v2[i + 1] if i + 1 < len(v2) and not v2[i + 1].startswith("--") else None
            assert f in v3 and (nxt is None or _val(v3, f) == nxt), f
    assert _val(v3, "--targets-mix") == "0.8,0.1,0.1" and "--pivot" not in v3   # ppo2's curriculum
    assert _val(v3, "--michael-bonus") == "2"
    assert _val(v3, "--compare-dir") == str(home / "ppo1")
    assert _val(v3, "--distill-dir") == str(home / "exit2")
    assert _val(v3, "--gate-per") == "4" and _val(v3, "--gate-per-quest") == "2" and "--gate-targets" in v3
    assert float(_val(v3, "--aux-coef")) == pipeline.V3_AUX_COEF == 0.2
    assert float(_val(v3, "--vf-lam")) == pipeline.V3_VF_LAM == 1.0
    assert int(_val(v3, "--vf-epochs")) == pipeline.V3_VF_EPOCHS == 2
    assert "--lam-build" not in v3
    # ppo2's effective KL anchor / entropy coefficient at the fork
    assert float(_val(v3, "--kl-coef")) == 0.0214 and float(_val(v3, "--ent-coef")) == 0.00228
    v3b = pipeline.v3_ppo_args(_pargs(["--v3", "--v3-lam-build", "0.8", "--v3-aux-coef", "0", "--v3-vf-epochs", "1",
                                       "--v3-kl-coef", "0.05", "--v3-ent-coef", "0.003"]))
    assert float(_val(v3b, "--lam-build")) == 0.8 and float(_val(v3b, "--aux-coef")) == 0.0
    assert _val(v3b, "--vf-epochs") == "1" and float(_val(v3b, "--kl-coef")) == 0.05
    assert float(_val(v3b, "--ent-coef")) == 0.003


def test_v3_ppo_args_parse_in_rl_ppo(home, monkeypatch):
    """Every flag v3_ppo_args passes is one rl.ppo's argparse accepts, with the intended values."""
    from cursed_words_solver.rl import ppo as P

    _fake_ppo2(home)
    cmd = pipeline.v3_ppo_args(_pargs(["--v3"]))
    assert cmd[0] == "cursed_words_solver.rl.ppo"
    got = {}
    orig = argparse.ArgumentParser.parse_args

    class Parsed(Exception):
        pass

    def spy(self, args=None, namespace=None):
        got["ns"] = orig(self, args, namespace)
        raise Parsed

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", spy)
    with pytest.raises(Parsed):
        P.main(cmd[1:])
    ns = got["ns"]
    assert ns.aux_coef == 0.2 and ns.vf_lam == 1.0 and ns.vf_epochs == 2 and ns.lam_build is None
    assert ns.michael_bonus == 2.0 and ns.kl_ref == "champion" and ns.gate_targets and ns.target_curriculum
    assert ns.kl_coef == 0.0214 and ns.ent_coef == 0.00228


def test_v3_exit_args_follow_ppo3_into_exit2(home):
    _fake_ppo2(home)
    args = _pargs(["--v3"])
    ex = pipeline.v3_exit_args(args)
    v2 = pipeline.v2_exit_args(args)
    assert _val(ex, "--dir") == str(home / "exit2")
    assert _val(ex, "--policy") == str(home / "ppo3" / "weights.pt")
    assert _val(ex, "--curriculum") == str(home / "ppo3" / "curriculum.json")
    for f in ("--search", "--crown-weights", "--quest-share", "--targets-mix", "--pivot", "--workers"):
        assert _val(ex, f) == _val(v2, f), f
    st = {s["name"]: s for s in pipeline.v3_stages(args)}
    assert st["ppo3"]["exit"] == ex
    assert pipeline.v3_stages(_pargs(["--v3", "--exit-workers", "0"]))[1]["exit"] is None
    assert "--distill-dir" not in pipeline.v3_ppo_args(_pargs(["--v3", "--exit-workers", "0"]))


# ------------------------------------------------------------------ seeding


def test_seed_copies_champion_rows_under_the_name_a_fresh_ppo3_reads(home):
    jobs = _fake_ppo2(home)
    before = _snapshot(home / "ppo2")
    args = _pargs(["--v3"])
    assert not pipeline.v3_stages(args)[0]["done"]
    plan = pipeline.v3_seed_plan()
    assert plan["ok"] and plan["src"].endswith("champion_u425.jsonl") and plan["stamp"] == 425
    info = pipeline.seed_ppo3(args)
    assert info["champion_rows"] == len(jobs) == 548
    ev = home / "ppo3" / "eval"
    # rl.ppo on a fresh dir: champion_update 0 -> run_arm("champion_u0", ...) on eval/: nothing left to play
    got = run_arm("champion_u0", "unused.pt", jobs, out_dir=ev, pool=object(), verbose=False)
    assert len(got) == len(jobs) and all(r["won"] for r in got)   # the u425 rows, not ppo2's old u0 rows
    assert champion_eval_path(home / "ppo3") == ev / "champion_u0.jsonl"
    # the gate's vs_ppo1_all rows and the frozen init
    assert {cache_key(r) for r in store.read_jsonl(ev / "ppo1_champion.jsonl")} == {cache_key(j) for j in jobs}
    assert (home / "ppo3" / pipeline.V3_INIT).read_bytes() == (home / "ppo2" / "champion.pt").read_bytes()
    assert json.loads((home / "ppo3" / pipeline.V3_INHERIT).read_text())["kl_coef"] == 0.0214
    assert pipeline.v3_stages(args)[0]["done"]
    # idempotent; ppo2 untouched (its STOP too)
    assert pipeline.seed_ppo3(args).get("champion_rows", 0) == 0
    assert _snapshot(home / "ppo2") == before


def test_seed_skips_rows_of_another_champion(home):
    _fake_ppo2(home, champ_update=425, stamp=450)   # ppo2/champion.pt is not the u425 champion
    plan = pipeline.v3_seed_plan()
    assert not plan["ok"] and "450" in plan["why"]
    info = pipeline.seed_ppo3(_pargs(["--v3"]))
    assert "champion_rows" not in info
    assert not (home / "ppo3" / "eval" / "champion_u0.jsonl").is_file()
    assert not pipeline.v3_stages(_pargs(["--v3"]))[0]["done"]


def test_seed_partial_rows_and_started_ppo3(home):
    jobs = _fake_ppo2(home, n_rows=100)
    args = _pargs(["--v3"])
    assert pipeline.seed_ppo3(args)["champion_rows"] == 100
    assert not pipeline.v3_stages(args)[0]["done"]   # rl.ppo plays the other 448
    (home / "ppo3" / "ckpt.pt").write_bytes(b"x")
    assert pipeline.seed_ppo3(args) == {"skipped": "ppo3 already started"}
    assert pipeline.v3_stages(args)[0]["done"]
    assert len(jobs) == 548


def test_seed_replay_champion_copies_no_champion_rows(home, capsys):
    """--v3-replay-champion: rl.ppo re-plays the starting champion with the current code."""
    _fake_ppo2(home)
    args = _pargs(["--v3", "--v3-replay-champion"])
    assert pipeline.main(["--v3", "--v3-replay-champion", "--dry-run"]) == 0
    assert "seed      replay" in capsys.readouterr().out and not (home / "ppo3").exists()
    info = pipeline.seed_ppo3(args)
    assert info["champion_rows"] == "replay"
    assert not (home / "ppo3" / "eval" / "champion_u0.jsonl").is_file()
    assert (home / "ppo3" / "eval" / "ppo1_champion.jsonl").is_file()   # vs_ppo1_all report rows still copied
    assert pipeline.v3_stages(args)[0]["done"]


# ------------------------------------------------------------------ main / run


def test_v3_needs_ppo2_champion(home, capsys):
    assert pipeline.main(["--v3", "--dry-run"]) == 1
    assert pipeline.main(["--v3"]) == 1
    assert "ppo2 champion" in capsys.readouterr().out
    assert not (home / "ppo3").exists()
    with pytest.raises(SystemExit):
        pipeline.main(["--v2", "--v3"])


def test_v3_dry_run_and_status(home, capsys):
    _fake_ppo2(home)
    before = _snapshot(home)
    assert pipeline.main(["--v3", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "seed      ok" in out and "champion_u425.jsonl" in out and "champion_u0.jsonl" in out
    assert "--vf-lam 1" in out and "--aux-coef 0.2" in out and "beside: cursed_words_solver.rl.exit" in out
    assert _snapshot(home) == before and not (home / "ppo3").exists()   # dry run writes nothing
    assert pipeline.main(["--v3", "--status"]) == 0
    st = json.loads(capsys.readouterr().out)["v3"]
    assert st["seed3"] == "todo" and st["ppo3"] == "todo" and st["seed"]["ok"]


def test_run_v3_seeds_then_runs_ppo3_with_exit2(home, monkeypatch):
    _fake_ppo2(home)
    (home / "ppo3").mkdir()
    (home / "ppo3" / "STOP").touch()
    (home / "exit2").mkdir()
    (home / "exit2" / "STOP").touch()
    before = _snapshot(home / "ppo2")
    calls = []
    monkeypatch.setattr(pipeline, "_run_with_exit", lambda *a: calls.append(a))
    monkeypatch.setattr(pipeline, "_single_instance", lambda: object())
    assert pipeline.main(["--v3"]) == 0
    assert len(calls) == 1
    cmd, ex, run, exit_name, _log, dirs = calls[0]
    assert run == "ppo3" and exit_name == "exit2" and dirs == pipeline.V3_DIRS and "ppo2" not in dirs
    assert _val(cmd, "--dir") == str(home / "ppo3") and _val(cmd, "--kl-coef") == "0.0214"
    assert _val(ex, "--policy") == str(home / "ppo3" / "weights.pt")
    # own STOP files cleared, ppo2's (paused run) kept; seeded rows in place
    assert not (home / "ppo3" / "STOP").exists() and not (home / "exit2" / "STOP").exists()
    assert (home / "ppo2" / "STOP").exists() and _snapshot(home / "ppo2") == before
    assert len(store.read_jsonl(home / "ppo3" / "eval" / "champion_u0.jsonl")) == 548
    # the global pause stops before anything runs
    calls.clear()
    (home / "STOP").touch()
    assert pipeline.main(["--v3"]) == 0 and calls == []


def test_v3_stop_forwarding_reaches_ppo3_and_exit2_only(home, monkeypatch):
    """_run forwards rl/STOP to the dirs it is given: for v3 that is ppo3 and exit2, never ppo2."""
    (home / "ppo2").mkdir()
    (home / "STOP").touch()

    class P:
        returncode = 0
        n = 0

        def poll(self):
            P.n += 1
            return None if P.n == 1 else 0

    monkeypatch.setattr(pipeline.subprocess, "Popen", lambda *a, **k: P())
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    pipeline._run(["x"], home / "log.txt", pipeline.V3_DIRS)
    assert (home / "ppo3" / "STOP").exists() and (home / "exit2" / "STOP").exists()
    assert not (home / "ppo2" / "STOP").exists()
