"""Play one run with a learned policy (sampled for training, greedy for evaluation) or the
teacher, in a worker process. Workers cache the model per weights file + mtime."""

from __future__ import annotations

import os
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

_CANDS = None
_MODELS: dict[str, tuple[float, Any]] = {}
_TEACHER = None


def init_worker(effort: float = 0.05, cheap: bool = True) -> None:
    global _CANDS
    os.environ.setdefault("PYTHONHASHSEED", "0")
    import torch

    torch.set_num_threads(1)
    from cursed_words_solver.sim.game.agent import Candidates

    _CANDS = Candidates(effort=effort, cheap_floor=cheap)


def _model(path: str):
    from cursed_words_solver.rl.model import load_policy

    for _ in range(50):   # weights.pt is replaced atomically every PPO update
        try:
            mt = os.path.getmtime(path)
            break
        except OSError:
            time.sleep(0.2)
    else:
        mt = os.path.getmtime(path)
    hit = _MODELS.get(path)
    if hit is None or hit[0] != mt:
        for _ in range(20):
            try:
                m, _ = load_policy(path)
                break
            except Exception:
                time.sleep(0.2)  # being replaced
        else:
            m, _ = load_policy(path)
        _MODELS[path] = (mt, m)
        hit = _MODELS[path]
    return hit[1]


def soft_target_row(last: dict, k: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """One halving-search decision as fixed-width rows: candidate indices (-1 = pad), mean Q,
    number of futures and paired SE vs the policy argmax (pads: 0)."""
    cands = list(last.get("cands") or last["q"].keys())
    k = max(int(k), len(cands))
    qi = np.full(k, -1, np.int16)
    qv = np.zeros(k, np.float32)
    qn = np.zeros(k, np.int16)
    qs = np.zeros(k, np.float32)
    for j, c in enumerate(cands):
        qi[j], qv[j], qn[j] = c, last["q"][c], last["n"][c]
        se = float(last.get("se", {}).get(c, 0.0))
        qs[j] = se if np.isfinite(se) else 0.0
    return qi, qv, qn, qs


def targeted_teacher(cands, seed: int, target: str, character: str, quest: str | None):
    """The teacher (rules player + champion override, as ``teacher.teacher_policy``) playing the
    build ``targets.teacher_plan(target, ...)`` for every character (no per-character defaults)."""
    import cursed_words_solver.rl.teacher as T
    from cursed_words_solver.rl.targets import teacher_plan
    from cursed_words_solver.sim.game.bossrisk import DEFAULT_PATH
    from cursed_words_solver.sim.game.expert import NetPolicy

    return NetPolicy(cands, T._TEACHER_MODEL, seed=seed, boss_risk=str(DEFAULT_PATH) if DEFAULT_PATH.is_file() else "",
                     build_plan=teacher_plan(target, character, quest), build_plan_chars={})


def play(job: dict[str, Any]) -> dict[str, Any]:
    """``job``: character, crown, seed, quest, policy ('teacher' or a .pt path), greedy,
    record (return the trajectory), temperature, target (build target, default FREE; an obs
    input for a net, the rules player's ``build_plan`` for the teacher), shaping (CWEnv
    potential per on-target item)."""
    from cursed_words_solver.rl.env import CWEnv, pack, potential
    from cursed_words_solver.rl.model import Actor

    from cursed_words_solver.rl.targets import FREE

    t0 = time.time()
    target = job.get("target") or FREE
    env = CWEnv(_CANDS, shaping=float(job.get("shaping") or 0.0))
    rec = bool(job.get("record"))
    traj: dict[str, list] = {"steps": [], "chosen": [], "logp": [], "value": [], "reward": []}
    try:
        env.reset(character=job["character"], crown=job["crown"], seed=job["seed"], quest=job.get("quest"),
                  target=target)
        if job["policy"] == "teacher":
            from cursed_words_solver.rl.teacher import _init_worker, teacher_policy
            import cursed_words_solver.rl.teacher as T

            if T._CANDS is None:
                T._CANDS = _CANDS
                try:
                    from cursed_words_solver.sim.game.advise import champion_path
                    from cursed_words_solver.sim.game.learn import load_model

                    p = champion_path()
                    T._TEACHER_MODEL = load_model(p) if p else None
                except Exception:
                    T._TEACHER_MODEL = None
            if target:
                pol = targeted_teacher(_CANDS, job["seed"], target, job["character"], job.get("quest"))
            else:
                pol = teacher_policy(_CANDS, job["seed"])
            while not env.done:
                env.step(pol.act(env.game))
        else:
            actor = Actor(_model(job["policy"]), greedy=bool(job.get("greedy")),
                          temperature=float(job.get("temperature", 1.0)), seed=job["seed"])
            searcher = None
            if job.get("search") is not None:
                from cursed_words_solver.rl.search import SearchConfig, Searcher

                searcher = Searcher(Actor(actor.model, greedy=True, seed=job["seed"]),
                                    SearchConfig(**(job["search"] if isinstance(job["search"], dict) else {})))
            while not env.done:
                st = env.current()
                if not st.cands:
                    raise RuntimeError(f"no candidates in phase {env.game.phase}")
                pk = pack(st)
                if searcher is not None:
                    i = searcher.choose(env, st, pk, key=f"search|{job['seed']}|{env.steps}")
                    logp, v = 0.0, 0.0
                else:
                    i, logp, v = actor.choose(pk)
                if searcher is not None and searcher.last is not None and job.get("record_search"):
                    traj.setdefault("search_steps", []).append(pk)
                    traj.setdefault("search_pick", []).append(i)
                    traj.setdefault("search_margin", []).append(float(searcher.last["margin"]))
                    traj.setdefault("search_changed", []).append(i != searcher.last["policy"])
                    if "q" in searcher.last:   # halving mode: soft targets (candidate idx, mean Q, n; padded to k)
                        qi, qv, qn, qs = soft_target_row(searcher.last, searcher.cfg.k)
                        traj.setdefault("search_q_idx", []).append(qi)
                        traj.setdefault("search_q_val", []).append(qv)
                        traj.setdefault("search_q_n", []).append(qn)
                        traj.setdefault("search_q_se", []).append(qs)
                # shaping part of the potential before the step (ppo trains the value head on
                # the UNSHAPED return-to-go, so search / assistant can add the plain potential)
                bonus = env.potential(env.game) - potential(env.game) if env.shaping else 0.0
                r, _ = env.step(st.cands[i].action)
                if rec:
                    traj["steps"].append(pk)
                    traj["chosen"].append(i)
                    traj["logp"].append(logp)
                    traj["value"].append(v)
                    traj["reward"].append(r)
                    traj.setdefault("bonus", []).append(float(bonus))
        res = {**{k: job[k] for k in ("character", "crown", "seed") }, "quest": job.get("quest"), **env.result(),
               "secs": round(time.time() - t0, 1), "error": ""}
        if job["policy"] != "teacher" and job.get("search") is not None:
            res["search"] = dict(searcher.stats)
    except Exception as exc:
        res = {**{k: job.get(k) for k in ("character", "crown", "seed")}, "quest": job.get("quest"),
               "target": target, "won": False, "outcome": 0.0, "error": f"{type(exc).__name__}: {exc}",
               "trace": traceback.format_exc()[-1200:], "secs": round(time.time() - t0, 1)}
        traj = {"steps": [], "chosen": [], "logp": [], "value": [], "reward": []}
    if rec or job.get("record_search"):
        res["traj"] = traj
    res["tag"] = job.get("tag", "")
    return res
