"""PPO value / representation fixes (rl/ppo.py, all default off): per-step GAE lambda
(--lam-build), value-target lambda (--vf-lam), aux BCE (--aux-coef), value-only passes with a
KL-to-snapshot (--vf-epochs), and the epochs_run / explained-variance instrumentation."""

from __future__ import annotations

import argparse
import copy

import numpy as np
import pytest

torch = pytest.importorskip("torch")

import torch.nn.functional as F  # noqa: E402

from cursed_words_solver.rl import ppo  # noqa: E402
from cursed_words_solver.rl.actions import ATYPE  # noqa: E402
from cursed_words_solver.rl.bc import VALUE_SCALE  # noqa: E402
from cursed_words_solver.rl.env import CWEnv, pack  # noqa: E402
from cursed_words_solver.rl.model import Policy, collate, default_config  # noqa: E402


class _NoWords:
    wordlist = None

    def words(self, game, top_n=5):
        return []


# ------------------------------------------------------------------ gae


def test_gae_constant_lambda_array_matches_float():
    rng = np.random.default_rng(0)
    for n in (1, 2, 7, 40):
        rew = rng.normal(size=n).astype(np.float32)
        val = rng.normal(size=n).astype(np.float32)
        for lam in (0.0, 0.5, 0.95, 1.0):
            a0, r0 = ppo.gae(rew, val, lam)
            a1, r1 = ppo.gae(rew, val, np.full(n, lam))
            assert np.array_equal(a0, a1) and np.array_equal(r0, r1)
            a2, _ = ppo.gae(rew, val, [lam] * n)
            assert np.array_equal(a0, a2)


def test_gae_per_step_lambda_is_each_steps_own():
    rng = np.random.default_rng(1)
    n = 9
    rew = rng.normal(size=n).astype(np.float32)
    val = rng.normal(size=n).astype(np.float32)
    lam = np.where(np.arange(n) % 3 == 0, 1.0, 0.5)
    adv, ret = ppo.gae(rew, val, lam)
    a_hi, _ = ppo.gae(rew, val, 1.0)
    a_lo, _ = ppo.gae(rew, val, 0.5)
    assert np.allclose(adv, np.where(lam == 1.0, a_hi, a_lo))
    assert np.allclose(ret, adv + val)
    # brute force: sum_k lam_t^k delta_{t+k}
    nv = np.append(val[1:], 0.0)
    delta = rew + nv - val
    for t in range(n):
        want = sum(lam[t] ** k * delta[t + k] for k in range(n - t))
        assert adv[t] == pytest.approx(want, abs=1e-5)
    with pytest.raises(ValueError):
        ppo.gae(rew, val, np.ones(n - 1))


# ------------------------------------------------------------------ build steps / episode items


def _st(*kinds):
    return {"act_type": np.asarray([ATYPE[k] for k in kinds], np.int64)}


def test_step_phase_and_build_steps():
    assert ppo.step_phase(_st("buy", "leave")) == "shop"
    assert ppo.step_phase(_st("submit", "skip")) == "encounter"
    assert ppo.step_phase(_st("boss", "boss")) == "boss_draft"
    assert ppo.step_phase(_st("michael_pick", "michael_pick")) == "michael_pick"
    assert ppo.step_phase(_st("submit", "skip"), "shop") == "shop"     # the recorded phase wins
    assert ppo.is_build_step(_st("buy", "leave"), 0)
    assert ppo.is_build_step(_st("submit", "skip"), 1)                 # skip grid = build
    assert not ppo.is_build_step(_st("submit", "skip"), 0)
    assert ppo.is_build_step(_st("pin", "pin"), 0, "pin_reward")


def _traj(phases, kinds, rew, val=None, stage=True):
    n = len(rew)
    tr = {"steps": [_st(*k) for k in kinds], "chosen": [0] * n, "logp": [-0.5] * n,
          "value": list(np.asarray(val if val is not None else np.zeros(n)) / VALUE_SCALE), "reward": list(rew)}
    if phases is not None:
        tr["phase"] = list(phases)
    if stage:
        tr["stage"] = [1 + i // 2 for i in range(n)]
    return tr


def test_episode_items_flags_default_and_old_trajs():
    rng = np.random.default_rng(2)
    rew = list(rng.normal(size=6))
    val = list(rng.normal(size=6))
    kinds = [("buy", "leave"), ("submit", "skip"), ("submit", "skip"), ("buy", "leave"), ("submit", "skip"),
             ("submit", "skip")]
    phases = ["shop", "encounter", "encounter", "shop", "encounter", "encounter"]
    res = {"won": True, "reason": "michael", "traj": _traj(phases, kinds, rew, val)}
    base = ppo.episode_items(res, 0.9)
    assert [it["phase"] for it in base] == phases
    assert [it["stage"] for it in base] == [1, 1, 2, 2, 3, 3]
    assert [it["build"] for it in base] == [True, False, False, True, False, False]
    assert all(it["won"] == 1.0 and it["michael"] == 1.0 for it in base)
    assert [it["vpred"] for it in base] == pytest.approx(val, rel=1e-5)
    # explicit lam_build / vf_lam == lam: the same numbers
    same = ppo.episode_items(res, 0.9, lam_build=0.9, vf_lam=0.9)
    assert [(a["adv"], a["ret"]) for a in same] == [(b["adv"], b["ret"]) for b in base]
    # old traj without stage / phase: phases inferred, stage None, same adv / ret
    old = ppo.episode_items({"won": False, "reason": "lost", "traj": _traj(None, kinds, rew, val, stage=False)}, 0.9)
    assert [it["phase"] for it in old] == phases and all(it["stage"] is None for it in old)
    assert [it["adv"] for it in old] == [it["adv"] for it in base]
    assert all(it["won"] == 0.0 and it["michael"] == 0.0 for it in old)
    # mismatched length (corrupt) falls back too
    tr = _traj(phases[:3], kinds, rew, val)
    assert [it["phase"] for it in ppo.episode_items({"traj": tr}, 0.9)] == phases


def test_lam_build_changes_only_build_advantages_and_vf_lam_only_returns():
    rng = np.random.default_rng(3)
    n = 8
    rew = list(rng.normal(size=n))
    val = list(rng.normal(size=n))
    kinds = [("buy", "leave") if i % 3 == 0 else ("submit", "skip") for i in range(n)]
    res = {"won": False, "traj": _traj(None, kinds, rew, val)}
    base = ppo.episode_items(res, 0.8)
    lb = ppo.episode_items(res, 0.8, lam_build=1.0)
    for a, b in zip(base, lb):
        assert b["ret"] == a["ret"]                       # value target: --vf-lam (default lam)
        if a["build"]:
            assert b["adv"] != pytest.approx(a["adv"])
        else:
            assert b["adv"] == a["adv"]                   # word steps keep their advantages
    vf = ppo.episode_items(res, 0.8, vf_lam=1.0)
    assert [a["adv"] for a in vf] == [a["adv"] for a in base]
    _, ret1 = ppo.gae(np.asarray(rew, np.float32), np.asarray(val, np.float32), 1.0)
    assert [a["ret"] for a in vf] == pytest.approx(list(ret1), abs=1e-5)


# ------------------------------------------------------------------ ppo_update


def _old_ppo_update(model, ref, opt, batch, args, device):
    """Frozen copy of ppo_update before the fixes (no distillation), the default-flags reference."""
    model.train()
    idx = np.arange(len(batch))
    stats: dict[str, list[float]] = {}
    beta = args.kl_coef
    for _ in range(args.epochs):
        np.random.shuffle(idx)
        ep_kl = []
        for s in range(0, len(idx), args.mb):
            items = [batch[i] for i in idx[s:s + args.mb]]
            b = collate(items, device)
            chosen = torch.tensor([it["chosen"] for it in items], device=device)
            old_logp = torch.tensor([it["logp"] for it in items], device=device)
            adv = torch.tensor([it["adv"] for it in items], device=device)
            ret = torch.tensor([it["ret"] for it in items], device=device)
            out = model(b)
            logp_all = F.log_softmax(out["logits"] / args.temperature, -1)
            logp = logp_all.gather(1, chosen.unsqueeze(1)).squeeze(1)
            ratio = torch.exp(logp - old_logp)
            pg = -torch.min(ratio * adv, ratio.clamp(1 - args.clip, 1 + args.clip) * adv).mean()
            vloss = F.smooth_l1_loss(out["value"], ret / VALUE_SCALE)
            p = logp_all.exp() * b["act_mask"]
            ent = -(p * logp_all.masked_fill(b["act_mask"] == 0, 0)).sum(-1).mean()
            loss = pg + args.vf_coef * vloss - args.ent_coef * ent
            kl_ref = torch.zeros((), device=device)
            if ref is not None and beta > 0:
                with torch.no_grad():
                    rl = F.log_softmax(ref(b)["logits"] / args.temperature, -1)
                kl_ref = (p * (logp_all - rl).masked_fill(b["act_mask"] == 0, 0)).sum(-1).mean()
                loss = loss + beta * kl_ref
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad)
            opt.step()
            with torch.no_grad():
                lr_ = logp - old_logp
                approx_kl = (torch.exp(lr_) - 1 - lr_).mean().item()
                ep_kl.append(approx_kl)
                clipfrac = ((ratio - 1).abs() > args.clip).float().mean().item()
            for k, v in (("pg", pg.item()), ("v", vloss.item()), ("ent", ent.item()), ("kl_ref", kl_ref.item()),
                         ("distill", 0.0), ("approx_kl", approx_kl), ("clipfrac", clipfrac)):
                stats.setdefault(k, []).append(v)
        if ep_kl and np.mean(ep_kl) > args.target_kl:
            break
    return {k: round(float(np.mean(v)), 4) for k, v in stats.items()}


@pytest.fixture(scope="module")
def batch():
    env = CWEnv(_NoWords())
    out = []
    for ch, seed in (("WetDennis", 2), ("Octacles", 3), ("WetDennis", 5)):
        st = env.reset(character=ch, crown=0, seed=seed)
        pk = pack(st)
        assert len(pk["act_type"]) > 1
        for j in range(4):
            won = float(j % 2)
            out.append({**pk, "chosen": j % len(pk["act_type"]), "logp": -1.0 - 0.1 * j, "adv": 0.5 - 0.3 * j,
                        "ret": 8.0 * won + j, "vpred": 4.0 + j, "won": won, "michael": float(j == 3),
                        "phase": "shop" if j < 2 else "encounter"})
    return out


def _args(**kw):
    a = dict(epochs=2, mb=5, temperature=1.0, clip=0.2, vf_coef=0.5, ent_coef=0.01, kl_coef=0.05, target_kl=10.0,
             max_grad=0.5, distill_coef=0.0, distill_mb=4)
    a.update(kw)
    return argparse.Namespace(**a)


def _models(n=2, lr=1e-3):
    torch.manual_seed(0)
    m = Policy(default_config())
    ref = copy.deepcopy(m)
    for p in ref.parameters():
        p.requires_grad_(False)
    ms = [copy.deepcopy(m) for _ in range(n)]
    return ms, ref, [torch.optim.AdamW(x.parameters(), lr=lr) for x in ms]


def _run(fn, m, ref, opt, batch, args, seed=7):
    np.random.seed(seed)
    return fn(m, ref, opt, batch, args, torch.device("cpu"))


def _same_params(a, b):
    return all(torch.equal(x, y) for x, y in zip(a.state_dict().values(), b.state_dict().values()))


def test_default_flags_identical_to_old_update(batch):
    (m0, m1, m2), ref, (o0, o1, o2) = _models(3)
    old = _run(_old_ppo_update, m0, ref, o0, batch, _args())
    new = _run(lambda *a: ppo.ppo_update(*a), m1, ref, o1, batch, _args())           # flags absent
    new2 = _run(lambda *a: ppo.ppo_update(*a), m2, ref, o2, batch,
                _args(aux_coef=0.0, vf_epochs=0, vf_kl_coef=1.0))                   # flags at their defaults
    for k, v in old.items():
        assert new[k] == v and new2[k] == v, k
    assert _same_params(m0, m1) and _same_params(m0, m2)
    assert new["epochs_run"] == 2 and "aux" not in new and "vf_v" not in new
    for k in ("ev", "ev_shop", "ev_word", "ev_fit", "ev_fit_shop", "ev_fit_word"):
        assert k in new


def test_epochs_run_counts_early_stop(batch):
    (m,), ref, (o,) = _models(1)
    st = _run(lambda *a: ppo.ppo_update(*a), m, ref, o, batch, _args(epochs=4, target_kl=-1.0))
    assert st["epochs_run"] == 1


def test_explained_variance_values(batch):
    ret = np.asarray([it["ret"] for it in batch])
    ev = ppo._ev_stats(batch, "vpred", "ev")
    assert ev["ev"] == pytest.approx(ppo.explained_variance([it["vpred"] for it in batch], ret), abs=1e-4)
    assert ppo._ev_stats(batch, "", "x", pred=ret) == {"x": 1.0, "x_shop": 1.0, "x_word": 1.0}
    assert ppo._ev_stats([{k: v for k, v in it.items() if k != "vpred"} for it in batch], "vpred", "ev") == {}
    assert np.isnan(ppo.explained_variance([1.0], [2.0]))


def test_aux_coef_trains_only_through_aux(batch):
    (m0, m1), ref, (o0, o1) = _models(2)
    a = _run(lambda *x: ppo.ppo_update(*x), m0, ref, o0, batch, _args(epochs=1, mb=len(batch)))
    b = _run(lambda *x: ppo.ppo_update(*x), m1, ref, o1, batch, _args(epochs=1, mb=len(batch), aux_coef=0.5))
    # one minibatch: the losses are computed before the (only) step, so they match
    for k in ("pg", "v", "ent", "kl_ref"):
        assert a[k] == b[k]
    assert "aux" in b and b["aux"] > 0
    init = _models(1)[0][0]
    aux_p = [k for k in init.state_dict() if k.startswith("aux.")]
    assert aux_p
    sd0, sd1, sdi = m0.state_dict(), m1.state_dict(), init.state_dict()
    assert all(torch.equal(sd0[k], sdi[k]) for k in aux_p)          # off: the aux head gets no gradient
    assert any(not torch.equal(sd1[k], sdi[k]) for k in aux_p)      # on: it trains
    # and it learns the flags
    b_ = collate(batch)
    y = torch.tensor([[it["won"], it["michael"]] for it in batch])
    with torch.no_grad():
        before = float(F.binary_cross_entropy_with_logits(init(b_)["aux"], y))
    (m2,), _, (o2,) = _models(1, lr=3e-3)
    for _ in range(15):
        ppo.ppo_update(m2, None, o2, batch, _args(epochs=1, mb=len(batch), aux_coef=1.0, vf_coef=0.0, ent_coef=0.0,
                                                  kl_coef=0.0), torch.device("cpu"))
    with torch.no_grad():
        after = float(F.binary_cross_entropy_with_logits(m2(b_)["aux"], y))
    assert after < before


def test_vf_epochs_fit_value_and_keep_policy(batch):
    (m0, m1), ref, (o0, o1) = _models(2, lr=3e-3)
    a = _run(lambda *x: ppo.ppo_update(*x), m0, ref, o0, batch, _args(epochs=1))
    b = _run(lambda *x: ppo.ppo_update(*x), m1, ref, o1, batch, _args(epochs=1, vf_epochs=6))
    for k in ("pg", "v", "ent", "kl_ref", "approx_kl", "clipfrac"):   # policy epochs untouched
        assert a[k] == b[k]
    assert b["vf_epochs_run"] == 6 and "vf_v" in b and "vf_kl" in b and b["epochs_run"] == 1
    bb = collate(batch)
    ret = torch.tensor([it["ret"] for it in batch]) / VALUE_SCALE
    with torch.no_grad():
        oa, ob = m0(bb), m1(bb)
        va = float(F.smooth_l1_loss(oa["value"], ret))
        vb = float(F.smooth_l1_loss(ob["value"], ret))
        kl = float(ppo._masked_kl(F.log_softmax(oa["logits"], -1), F.log_softmax(ob["logits"], -1), bb["act_mask"]))
    assert vb < va                 # the value passes fit the targets
    assert kl < 0.05               # while the policy stays (nearly) where the policy epochs left it


def test_vf_epochs_do_not_carry_policy_momentum(batch):
    """With no value / aux loss the value passes have only the KL term, whose gradient is ~0 at the
    snapshot: the policy epochs' Adam momentum must not keep moving the policy, and the optimiser
    state is restored afterwards."""
    (m0, m1), ref, (o0, o1) = _models(2, lr=3e-3)
    _run(lambda *x: ppo.ppo_update(*x), m0, ref, o0, batch, _args(epochs=2, vf_coef=0.0))
    _run(lambda *x: ppo.ppo_update(*x), m1, ref, o1, batch, _args(epochs=2, vf_epochs=4, vf_coef=0.0))
    bb = collate(batch)
    with torch.no_grad():
        kl = float(ppo._masked_kl(F.log_softmax(m0(bb)["logits"], -1), F.log_softmax(m1(bb)["logits"], -1), bb["act_mask"]))
    assert abs(kl) < 1e-3          # live momentum: KL ~0.01-0.02 after the first value steps
    for k, s0 in o0.state.items():
        s1 = o1.state[dict(zip(m0.parameters(), m1.parameters()))[k]]
        assert torch.equal(s0["exp_avg"], s1["exp_avg"]) and torch.equal(s0["exp_avg_sq"], s1["exp_avg_sq"])


def test_cli_flags_default_off():
    import inspect

    src = inspect.getsource(ppo.main)
    for flag, default in (("--aux-coef", "0.0"), ("--lam-build", "None"), ("--vf-lam", "None"),
                          ("--vf-epochs", "0"), ("--vf-kl-coef", "1.0")):
        line = next(ln for ln in src.splitlines() if f'"{flag}"' in ln)
        assert f"default={default}" in line, flag


def test_play_step_label():
    from cursed_words_solver.rl.play import step_label
    from cursed_words_solver.sim.game.run import Game, RunConfig

    g = Game(RunConfig(character="Octacles", ascension=0, seed=3))
    stage, ph = step_label(g)
    assert stage == int(g.player.run.stage) and ph == g.phase
