"""Keyed group rollouts (rl/ppo.py --group K / --group-mix BETA, default off): leave-one-out
group advantages, the job fan-out, mixing with GAE, the per-group buffer, and K=1 unchanged."""

from __future__ import annotations

import random

import numpy as np
import pytest

pytest.importorskip("torch")

from cursed_words_solver.rl import ppo  # noqa: E402
from cursed_words_solver.rl.actions import ATYPE  # noqa: E402
from cursed_words_solver.rl.bc import VALUE_SCALE  # noqa: E402
from cursed_words_solver.rl.evaluate import rep_actor_seed  # noqa: E402


def _st(*kinds):
    return {"act_type": np.asarray([ATYPE[k] for k in kinds], np.int64)}


def _res(rew, val=None, bonus=None, won=False, reason="lost", error=""):
    n = len(rew)
    kinds = [("submit", "skip")] * n
    tr = {"steps": [_st(*k) for k in kinds], "chosen": [0] * n, "logp": [-0.5] * n,
          "value": list(np.asarray(val if val is not None else np.zeros(n)) / VALUE_SCALE), "reward": list(rew)}
    if bonus is not None:
        tr["bonus"] = list(bonus)
    return {"won": won, "reason": reason, "traj": tr, "error": error}


# ------------------------------------------------------------------ group_advantages


def test_group_advantages_leave_one_out():
    r = [1.0, 4.0, 7.0, 0.0]
    a = ppo.group_advantages(r)
    for i, x in enumerate(r):
        others = [y for j, y in enumerate(r) if j != i]
        assert a[i] == pytest.approx(x - sum(others) / len(others))


def test_group_advantages_k2_symmetric():
    a = ppo.group_advantages([3.0, 10.0])
    assert a == pytest.approx([-7.0, 7.0])


def test_group_advantages_all_equal_and_small():
    assert ppo.group_advantages([5.0, 5.0, 5.0]) == pytest.approx([0.0, 0.0, 0.0])
    assert ppo.group_advantages([2.5]) == [0.0]
    assert ppo.group_advantages([]) == []


# ------------------------------------------------------------------ returns


def test_episode_return_unshaped_and_michael():
    rew = [1.0, -0.5, 2.0]
    assert ppo.episode_return(_res(rew)) == pytest.approx(2.5)
    # shaping: shaped phi(s0) = unshaped + bonus[0]; the return adds it back
    assert ppo.episode_return(_res(rew, bonus=[0.3, 0.6, 0.9])) == pytest.approx(2.8)
    # Michael win: env applied 8, training bonus 2 -> -6 on the last reward
    r = _res(rew, won=True, reason="michael")
    assert ppo.episode_return(r, michael_bonus=2.0) == pytest.approx(2.5 - 6.0)
    assert ppo.episode_return({"traj": {"reward": []}}) == 0.0


# ------------------------------------------------------------------ fan-out


def test_group_jobs_fan_out():
    j = ppo.sample_job(random.Random(3), 40, 0.25, [1.0] * 8)
    jobs = ppo.group_jobs(j, 4, gid=40)
    assert len(jobs) == 4
    for g in jobs:
        assert g["keyed"] is True and g["group"] == 40
        for k in ("seed", "character", "crown", "quest", "target"):
            assert g[k] == j[k]
    seeds = [g["actor_seed"] for g in jobs]
    assert len(set(seeds)) == 4
    assert seeds == [rep_actor_seed(j["seed"], r) for r in range(4)]
    assert seeds[0] == j["seed"]


# ------------------------------------------------------------------ mixing


def test_episode_items_group_mix():
    rng = np.random.default_rng(0)
    rew, val = list(rng.normal(size=5)), list(rng.normal(size=5))
    res = _res(rew, val)
    base = ppo.episode_items(res, 0.9)
    for beta in (0.0, 0.3, 1.0):
        g = ppo.episode_items(res, 0.9, group_adv=2.0, group_mix=beta)
        for b, x in zip(base, g):
            assert x["adv"] == pytest.approx((1 - beta) * b["adv"] + beta * 2.0)
            assert x["ret"] == b["ret"] and x["vpred"] == b["vpred"]


def test_k1_episode_items_identical():
    rng = np.random.default_rng(1)
    res = _res(list(rng.normal(size=6)), list(rng.normal(size=6)), bonus=list(rng.normal(size=6)))
    a = ppo.episode_items(res, 0.95)
    b = ppo.episode_items(res, 0.95, group_adv=None, group_mix=0.5)
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert x.keys() == y.keys()
        assert x["adv"] == y["adv"] and x["ret"] == y["ret"]


def test_group_items_loo_fallback_and_errors():
    r1, r2, r3 = _res([1.0, 1.0]), _res([0.0, 5.0]), _res([0.0], error="boom")
    items, valid, st = ppo.group_items([r1, r2, r3], 0.9, group_mix=1.0)
    assert len(valid) == 2 and st["valid"] == 2 and st["zero"] is False
    assert st["abs_adv"] == pytest.approx([3.0, 3.0])
    assert [it["adv"] for it in items] == pytest.approx([-3.0, -3.0, 3.0, 3.0])
    # one valid member: plain GAE
    items1, valid1, st1 = ppo.group_items([r1, r3], 0.9)
    assert st1["zero"] is None and len(valid1) == 1
    assert [it["adv"] for it in items1] == [it["adv"] for it in ppo.episode_items(r1, 0.9)]
    # all equal R -> zero advantages with beta 1
    items2, _, st2 = ppo.group_items([_res([2.0]), _res([1.0, 1.0])], 0.9)
    assert st2["zero"] is True and all(abs(it["adv"]) < 1e-9 for it in items2)
    rs = ppo.group_row_stats([st, st1, st2])
    assert rs["group_n"] == 3 and rs["group_fallback"] == 1
    assert rs["group_zero"] == 0.5 and rs["group_abs_adv"] == pytest.approx(1.5)


# ------------------------------------------------------------------ normalisation


def test_normalize_default_path_unchanged():
    rng = np.random.default_rng(2)
    items = ppo.episode_items(_res(list(rng.normal(size=7)), list(rng.normal(size=7))), 0.9)
    raw = [it["adv"] for it in items]
    ppo.normalize_advantages(items)
    a = np.asarray(raw, np.float32)
    mu, sd = float(a.mean()), float(a.std() + 1e-6)
    assert [it["adv"] for it in items] == [(x - mu) / sd for x in raw]
    ppo.normalize_advantages([])


def test_normalize_group_term_not_centred_by_steps():
    # reviewer case: K=2, beta=1; group A winner 3 steps (A=+5) / loser 1 step (A=-5);
    # group B all-equal 2 + 2 steps (A=0). Step-mean centring would give B -mu/sd != 0.
    win, lose = _res([8.0, 8.0, 8.0]), _res([14.0])
    eq1, eq2 = _res([5.0, 5.0]), _res([4.0, 6.0])
    ia, _, _ = ppo.group_items([win, lose], 0.9, group_mix=1.0)
    ib, _, sb = ppo.group_items([eq1, eq2], 0.9, group_mix=1.0)
    assert sb["zero"] is True
    items = ia + ib
    ppo.normalize_advantages(items)
    assert all(it["adv"] == 0.0 for it in items[len(ia):])
    a = [it["adv"] for it in items[:len(ia)]]
    assert a[0] > 0 and a[-1] < 0 and a[0] == pytest.approx(-a[-1])
    # mixed beta: GAE part is centred, group part is not
    rng = np.random.default_rng(4)
    r1 = _res(list(rng.normal(size=5)), list(rng.normal(size=5)))
    r2 = _res(list(rng.normal(size=3)), list(rng.normal(size=3)))
    its, _, _ = ppo.group_items([r1, r2], 0.9, group_mix=0.4)
    gae = np.asarray([it["adv"] - it["adv_grp"] for it in its])
    grp = np.asarray([it["adv_grp"] for it in its])
    ppo.normalize_advantages(its)
    c = gae - gae.mean() + grp
    assert [it["adv"] for it in its] == pytest.approx(list(c / (np.sqrt(np.mean(c * c)) + 1e-6)))


# ------------------------------------------------------------------ buffer / carry-over


def test_group_buffer_carry_over():
    gb = ppo.GroupBuffer()
    gb.open(0, 2)
    gb.open(2, 2)
    assert gb.add(0, {"i": 0}) is None
    assert gb.add(2, {"i": 2}) is None
    done = gb.add(0, {"i": 1})
    assert [r["i"] for r in done] == [0, 1]
    assert len(gb) == 1          # group 2 stays (carries over to the next update)
    gb.open(4, 2)
    assert gb.add(2, {"i": 3}) is not None and len(gb) == 1


# ------------------------------------------------------------------ resume / flags


def test_resolve_group():
    assert ppo.resolve_group(None, None, None) == (1, 1.0)
    assert ppo.resolve_group(4, 0.5, None) == (4, 0.5)
    assert ppo.resolve_group(None, None, {"group": 4, "group_mix": 0.7}) == (4, 0.7)
    assert ppo.resolve_group(None, None, {}) == (1, 1.0)          # old checkpoints
    assert ppo.resolve_group(1, None, {"group": 4, "group_mix": 0.7}) == (1, 0.7)
    with pytest.raises(ValueError):
        ppo.resolve_group(2, 1.5, None)


def test_cli_group_flags_default_off():
    import inspect

    src = inspect.getsource(ppo.main)
    for flag in ("--group", "--group-mix"):
        line = next(ln for ln in src.splitlines() if f'"{flag}"' in ln)
        assert "default=None" in line, flag
