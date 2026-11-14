"""Training-only Michael bonus (rl/env.py, rl/ppo.py --michael-bonus, rl/evaluate.py paired /
promote_ok with the training bonus) and the pipeline --v2 ppo2 / exit2 settings (rl/pipeline.py)."""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("torch")

from cursed_words_solver.rl import env as EN  # noqa: E402
from cursed_words_solver.rl import evaluate as E  # noqa: E402
from cursed_words_solver.rl import ppo as P  # noqa: E402
from cursed_words_solver.sim.game.features import MICHAEL_BONUS, outcome  # noqa: E402


def _done(reason: str, won: bool = True):
    return SimpleNamespace(phase="done", won=won, end_reason=reason)


# ------------------------------------------------------------------ env


def test_game_bonus_is_eight():
    assert MICHAEL_BONUS == 8.0 and E.MICHAEL_BONUS == MICHAEL_BONUS and P.MICHAEL_BONUS == MICHAEL_BONUS


def test_train_outcome_only_moves_michael_wins():
    m = _done("michael")
    assert outcome(m) == 24.0
    assert EN.train_outcome(m) == 24.0
    assert EN.train_outcome(m, 2.0) == 18.0
    assert EN.potential(m, michael_bonus=2.0) == 18.0
    assert EN.potential(m) == 24.0
    w = _done("won")   # a plain stage-5 win (incl. losing to Michael) is untouched
    assert EN.train_outcome(w, 2.0) == outcome(w) == 16.0


def test_env_potential_and_result_report_bonus():
    e = EN.CWEnv.__new__(EN.CWEnv)   # no candidate builder needed for potential()
    e.target, e.shaping, e.michael_bonus = "", 0.0, 2.0
    assert e.potential(_done("michael")) == 18.0
    e.michael_bonus = MICHAEL_BONUS
    assert e.potential(_done("michael")) == 24.0


# ------------------------------------------------------------------ ppo returns


def _traj(rew):
    steps = [{"act_type": np.zeros(2, np.int64)} for _ in rew]
    return {"steps": steps, "chosen": [0] * len(rew), "logp": [0.0] * len(rew), "value": [0.0] * len(rew),
            "reward": list(rew)}


def test_michael_reward_delta():
    assert P.michael_reward_delta({"won": True, "reason": "michael"}, 2.0) == -6.0
    assert P.michael_reward_delta({"won": True, "reason": "michael"}) == 0.0
    assert P.michael_reward_delta({"won": True, "reason": "michael", "michael_bonus": 2.0}, 2.0) == 0.0
    assert P.michael_reward_delta({"won": True, "reason": "won"}, 2.0) == 0.0
    assert P.michael_reward_delta({"won": False, "reason": "lost"}, 2.0) == 0.0


def test_episode_items_returns_use_training_bonus():
    rew = [3.0, 5.0, 16.0]   # telescopes to the game outcome 24 (a Michael win)
    res = {"won": True, "reason": "michael", "traj": _traj(rew)}
    r8 = [it["ret"] for it in P.episode_items(res, lam=1.0)]
    assert r8 == pytest.approx([24.0, 21.0, 16.0])
    res = {"won": True, "reason": "michael", "traj": _traj(rew)}
    r2 = [it["ret"] for it in P.episode_items(res, lam=1.0, michael_bonus=2.0)]
    assert r2 == pytest.approx([18.0, 15.0, 10.0])
    # the env already applied b (play.py forwarding job["michael_bonus"]): no double count
    applied = [3.0, 5.0, 10.0]
    res = {"won": True, "reason": "michael", "michael_bonus": 2.0, "traj": _traj(applied)}
    assert [it["ret"] for it in P.episode_items(res, lam=1.0, michael_bonus=2.0)] == pytest.approx(r2)
    # a plain win is unchanged by the bonus
    res = {"won": True, "reason": "won", "traj": _traj([3.0, 5.0, 8.0])}
    assert [it["ret"] for it in P.episode_items(res, lam=1.0, michael_bonus=2.0)] == pytest.approx([16.0, 13.0, 8.0])


def test_resolve_michael_bonus(tmp_path):
    assert P.resolve_michael_bonus(None, None, tmp_path) == MICHAEL_BONUS        # fresh, no flag
    assert P.resolve_michael_bonus(None, {"update": 3}, tmp_path) == MICHAEL_BONUS   # pre-flag checkpoint
    (tmp_path / "curriculum.json").write_text(json.dumps({"michael_bonus": 3.0}))
    assert P.resolve_michael_bonus(None, None, tmp_path) == 3.0
    assert P.resolve_michael_bonus(None, {"michael_bonus": 2.0}, tmp_path) == 2.0    # checkpoint first
    assert P.resolve_michael_bonus(5.0, {"michael_bonus": 2.0}, tmp_path) == 5.0     # explicit flag wins
    assert P.resolve_michael_bonus(8.0, {"michael_bonus": 2.0}, tmp_path) == 8.0
    (tmp_path / "curriculum.json").write_text("{broken")
    assert P.resolve_michael_bonus(None, None, tmp_path) == MICHAEL_BONUS


def test_command_argv_records_resolved_bonus():
    assert P.command_argv(["--dir", "x"], None, 2.0) == ["--dir", "x", "--michael-bonus", "2"]
    assert P.command_argv(["--dir", "x", "--michael-bonus", "5"], 5.0, 5.0) == ["--dir", "x", "--michael-bonus", "5"]
    assert P.command_argv([], None, MICHAEL_BONUS) == ["--michael-bonus", "8"]
    ns = argparse.ArgumentParser()
    ns.add_argument("--michael-bonus", type=float, default=None)
    assert ns.parse_args(P.command_argv([], None, 2.5)).michael_bonus == 2.5


# ------------------------------------------------------------------ evaluate / gate


def _row(seed, won, reason, out):
    return {"character": "Spike", "crown": 6, "quest": None, "seed": seed, "won": won, "reason": reason, "outcome": out}


def test_row_outcome_and_summarize():
    m, w, lost = _row(1, True, "michael", 24.0), _row(2, True, "won", 16.0), _row(3, False, "lost", 12.5)
    assert E.row_outcome(m) == 24.0 and E.row_outcome(m, 2.0) == 18.0
    assert E.row_outcome(w, 2.0) == 16.0 and E.row_outcome(lost, 2.0) == 12.5
    s8 = E.summarize([m, w, lost])
    assert "train_outcome" not in s8 and s8["outcome"] == round((24 + 16 + 12.5) / 3, 3)
    s2 = E.summarize([m, w, lost], 2.0)
    assert s2["outcome"] == s8["outcome"]            # true outcome kept
    assert s2["train_outcome"] == round((18 + 16 + 12.5) / 3, 3)


def test_gate_promotes_on_training_bonus_not_on_michael_chasing():
    # champion: 4 Michael wins, 6 losses; candidate: 6 plain wins (incl. the champion's 4 seeds), 4 losses
    champ = [_row(i, True, "michael", 24.0) if i < 4 else _row(i, False, "lost", 10.0) for i in range(10)]
    cand = [_row(i, True, "won", 16.0) if i < 6 else _row(i, False, "lost", 10.0) for i in range(10)]
    c8 = E.paired(cand, champ)
    assert c8["win_diff"] > 0 and c8["outcome_diff"] < 0 and not E.promote_ok(c8)   # old rule: Michael bonus wins
    assert "michael_bonus" not in c8
    c2 = E.paired(cand, champ, michael_bonus=2.0)
    assert c2["win_diff"] == c8["win_diff"] and c2["win_z"] == c8["win_z"]
    assert c2["outcome_diff"] == pytest.approx(0.4) and c2["michael_bonus"] == 2.0
    assert E.promote_ok(c2)
    # b == 8 is exactly the old comparison
    assert E.paired(cand, champ, michael_bonus=8.0) == c8


# ------------------------------------------------------------------ pipeline --v2


@pytest.fixture()
def home(tmp_path, monkeypatch):
    from cursed_words_solver.rl import pipeline

    monkeypatch.setattr(pipeline, "HOME", tmp_path)
    return tmp_path


def _pargs(argv=()):
    from cursed_words_solver.rl import pipeline

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
    return ns["args"]


def _val(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def test_pipeline_v2_ppo2_michael_bonus(home):
    from cursed_words_solver.rl import pipeline

    ppo = pipeline.v2_ppo_args(_pargs(["--v2"]))
    assert _val(ppo, "--michael-bonus") == "2"
    assert _val(pipeline.v2_ppo_args(_pargs(["--v2", "--michael-bonus", "8"])), "--michael-bonus") == "8"
    # the flag rl.ppo gets parses to the value
    ap = argparse.ArgumentParser()
    ap.add_argument("--michael-bonus", type=float)
    assert ap.parse_known_args(ppo)[0].michael_bonus == 2.0


def test_pipeline_v2_exit2_settings(home):
    from cursed_words_solver.rl import pipeline

    (home / "ppo2").mkdir()
    (home / "ppo2" / "curriculum.json").write_text(json.dumps({"targets_mix": [0.8, 0.1, 0.1], "pivot": None}))
    ex = pipeline.v2_exit_args(_pargs(["--v2"]))
    assert json.loads(_val(ex, "--search")) == {"sims": 2}
    assert _val(ex, "--crown-weights") == "0.2,0.2,0.3,0.5,1.0,2.0,2.5,1.5"
    assert _val(ex, "--quest-share") == "0.1"
    assert _val(ex, "--targets-mix") == "1,0,0"
    assert "--pivot" not in ex
    # ppo2 keeps its own job settings
    ppo = pipeline.v2_ppo_args(_pargs(["--v2"]))
    assert _val(ppo, "--crown-weights") == "0.4,0.6,0.8,1,1.2,1.4,1.6,2.0" and _val(ppo, "--quest-share") == "0.25"
    assert _val(ppo, "--targets-mix") == "0.8,0.1,0.1"
    # overrides; '' targets mix = ppo2's
    ex = pipeline.v2_exit_args(_pargs(["--v2", "--exit-search", '{"sims": 4}', "--exit-quest-share", "0.25",
                                       "--exit-crown-weights", "1,1,1,1,1,1,1,1", "--exit-targets-mix", "",
                                       "--exit-pivot", "off"]))
    assert json.loads(_val(ex, "--search")) == {"sims": 4} and _val(ex, "--quest-share") == "0.25"
    assert _val(ex, "--crown-weights") == "1,1,1,1,1,1,1,1"
    assert _val(ex, "--targets-mix") == "0.8,0.1,0.1" and _val(ex, "--pivot") == "off"


def test_pipeline_exit2_args_parse_in_rl_exit(home, monkeypatch):
    """Every flag v2_exit_args passes is one rl.exit's argparse accepts (main stops right after parsing)."""
    from cursed_words_solver.rl import exit as X
    from cursed_words_solver.rl import pipeline

    ex = pipeline.v2_exit_args(_pargs(["--v2"]))
    assert ex[0] == "cursed_words_solver.rl.exit"
    got = {}
    orig = argparse.ArgumentParser.parse_args

    class Parsed(Exception):
        pass

    def spy(self, args=None, namespace=None):
        got["ns"] = orig(self, args, namespace)
        raise Parsed

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", spy)
    with pytest.raises(Parsed):
        X.main(ex[1:])
    ns = got["ns"]
    assert json.loads(ns.search) == {"sims": 2} and float(ns.quest_share) == 0.1
    assert ns.crown_weights == "0.2,0.2,0.3,0.5,1.0,2.0,2.5,1.5" and ns.targets_mix == "1,0,0"
    if hasattr(X, "parse_search"):   # merged onto rl.exit's SEARCH: top / horizon kept, sims 2
        cfg = X.parse_search(ns.search)
        assert cfg["sims"] == 2 and cfg["top"] == X.SEARCH["top"]


def test_pipeline_v2_status_reports_bonus(home):
    from cursed_words_solver.rl import pipeline

    args = _pargs(["--v2"])
    assert pipeline.v2_status(args)["ppo2_michael_bonus"] is None
    (home / "ppo2").mkdir()
    (home / "ppo2" / "curriculum.json").write_text(json.dumps({"michael_bonus": 2.0}))
    st = pipeline.v2_status(args)
    assert st["ppo2_michael_bonus"] == 2.0 and st["ppo2"] == "todo"


# ------------------------------------------------------------------ distill shards across obs v4


def test_distill_accepts_v3_shards_with_old_action_width():
    """obs v4 widened the action features 38 -> 54; v3 exit shards (act width 38) stay usable."""
    from cursed_words_solver.rl import obs as O
    from cursed_words_solver.rl.actions import LEGACY_ACTION_BY_OBS, n_action_features

    buf = P.DistillBuffer(__import__("pathlib").Path("."))

    def ep(v, G, Ft, Fa):
        return {"obs_version": np.asarray([v]), "glob": np.zeros((3, G), np.float32),
                "tok_feat": np.zeros((5, Ft), np.float32), "act_feat": np.zeros((3, Fa), np.float32)}

    if O.OBS_VERSION < 4:
        pytest.skip("obs v4 not present")
    i3 = 3 - P.LEGACY_OBS_VERSION
    G3, T3 = O.LEGACY_GLOBAL[i3], O.LEGACY_TOKEN[i3]
    assert buf.format_ok(ep(3, G3, T3, LEGACY_ACTION_BY_OBS[3]))
    cur = (O.n_global_features(), O.n_token_features(), n_action_features())
    assert buf.format_ok(ep(O.OBS_VERSION, *cur))
    assert not buf.format_ok(ep(O.OBS_VERSION, cur[0], cur[1], LEGACY_ACTION_BY_OBS[3]))
