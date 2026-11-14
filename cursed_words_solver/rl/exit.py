"""Expert iteration: the look-ahead (rl.search) plays training seeds with the latest PPO
weights and saves every searched decision with the look-ahead's pick. PPO distils these
(``--distill-dir``), so the network learns what the search finds and the next search
starts from a stronger policy.

    python -m cursed_words_solver.rl.exit --dir ~/.cursed_words_solver/rl/exit --policy ~/.cursed_words_solver/rl/ppo1/weights.pt

Resumable: ``state.json`` counts started runs; a run in flight at a kill is replayed with a
new seed. ``STOP`` file in the dir = finish nothing more and exit. Output: ``shards/*.npz``
(env.pack steps + ``chosen`` = look-ahead pick, ``margin``, ``changed``, ``obs_version``) and
``runs.jsonl``. With a halving search (``--search '{"mode": "halving"}'``) shards also hold
soft targets ``q_idx`` / ``q_val`` / ``q_n`` / ``q_se`` (see ``soft_targets``; PPO ``--distill-soft``).
Jobs follow PPO's curriculum (``--curriculum``, ppo1/curriculum.json, re-read as it changes): the same character / quest weights, so the labels cover the slices PPO is weak on.
Build targets: ``--targets-mix`` (as rl.ppo; default: the ``targets_mix`` PPO writes to its
curriculum.json, none = FREE) gives runs a target build, which the shards' obs carry
(``obs_version`` 3). ``--pivot p,lo,hi`` (default: PPO's curriculum.json ``pivot``, none = off)
makes that share of runs pivot runs (rl.ppo ``--pivot``). A second collector runs beside a second PPO with its own ``--dir`` (exit2).

Job settings (``resolve_settings``): an explicit flag always wins over curriculum.json.
``--crown-weights`` / ``--quest-share`` unset inherit PPO's ``crown_weights`` / ``quest_share``
(else 1,...,1 / 0.25); ``--targets-mix free`` (or ``off``) forces FREE runs. ``--search`` JSON is
merged onto ``SEARCH`` (sims 2: +5.7 points at crowns 5-7, about sims 4 at 1/3 the cost). To
focus the labels where look-ahead helps (FREE crowns 5-7):
``--crown-weights 0,0,0,0,0,1,1,1.2 --quest-share 0 --targets-mix free --pivot off``.
The rollouts score a finished Michael win with PPO's training bonus (curriculum.json
``michael_bonus``, rl.ppo ``--michael-bonus``; ``SearchConfig.michael_bonus``) unless ``--search`` sets it.
Shards also carry the run's ``crown`` / ``quest`` (1 = quest run) / ``free`` (1 = no quest,
FREE target, not a pivot run) as 1-element int16 arrays (readers ignore unknown keys).
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import deque
from pathlib import Path

import numpy as np

from cursed_words_solver.rl import store

EXIT_SEED0 = 60_000_000
# sims 4 = +6.4% wins on fresh seeds (2026-11-11); sims 2 = +5.7 points at crowns 5-7 (43.6 vs 37.9%),
# about as good as sims 4 at 1/3 the cost (2026-11-14)
SEARCH = {"top": 3, "sims": 2, "horizon": 2.0}
DEFAULT_CROWN_WEIGHTS = (1.0,) * 8   # crowns 0-7, when neither the flag nor curriculum.json gives them
DEFAULT_QUEST_SHARE = 0.25
FREE_WORDS = ("free", "off", "none")
MICHAEL_BONUS = 8.0   # sim.game.features.MICHAEL_BONUS (checked in tests); PPO's curriculum.json may carry its own


def soft_targets(tr: dict) -> dict[str, np.ndarray]:
    """Halving-mode search (``"mode": "halving"``): per-decision soft targets, (decisions, k)
    arrays ``q_idx`` (searched candidate indices, -1 = pad), ``q_val`` (mean Q), ``q_n``
    (futures) and ``q_se`` (paired SE vs the policy argmax). Empty for top-k search, and only
    when every decision of the run has a row (so rows line up with ``chosen``)."""
    rows = tr.get("search_q_idx")
    if not rows or len(rows) != len(tr.get("search_steps") or []):
        return {}
    w = max(len(r) for r in rows)

    def pad(xs, fill, dt):
        return np.stack([np.pad(np.asarray(x, dt), (0, w - len(x)), constant_values=fill) for x in xs]).astype(dt)

    return {"q_idx": pad(rows, -1, np.int16), "q_val": pad(tr["search_q_val"], 0, np.float32),
            "q_n": pad(tr["search_q_n"], 0, np.int16), "q_se": pad(tr["search_q_se"], 0, np.float32)}


def own_pivot_arg(text: str) -> tuple[bool, tuple[float, int, int] | None]:
    """``--pivot`` -> (off, own pivot): "" inherits PPO's curriculum.json pivot (False, None);
    "off" / "none" / p=0 turn pivot off (True, None); "p,lo,hi" is used as given."""
    from cursed_words_solver.rl.ppo import parse_pivot

    t = (text or "").strip()
    if not t:
        return False, None
    if t.lower() in ("off", "none"):
        return True, None
    pv = parse_pivot(t)
    return pv is None, pv


def parse_search(text: str | None) -> dict:
    """``--search`` JSON merged onto ``SEARCH`` (so '{"sims": 2}' keeps top / horizon); unknown
    keys fail here, not in every worker."""
    import dataclasses

    from cursed_words_solver.rl.search import SearchConfig

    own = json.loads(text) if text and text.strip() else {}
    if not isinstance(own, dict):
        raise ValueError(f"--search needs a JSON object, got {text!r}")
    cfg = {**SEARCH, **own}
    bad = set(cfg) - {f.name for f in dataclasses.fields(SearchConfig)}
    if bad:
        raise ValueError(f"--search: unknown SearchConfig keys {sorted(bad)}")
    SearchConfig(**cfg)
    return cfg


def parse_crown_weights(text: str | None) -> tuple[float, ...] | None:
    """``"w0,...,w7"`` -> tuple; None / "" -> None (inherit)."""
    if text is None or not str(text).strip():
        return None
    w = tuple(float(x) for x in str(text).split(","))
    if not 1 <= len(w) <= 8 or min(w) < 0 or sum(w) <= 0:
        raise ValueError(f"crown weights need 1-8 non-negative weights (crowns 0-7), got {text!r}")
    return w


def own_mix_arg(text: str | None) -> tuple[bool, tuple[float, float, float] | None]:
    """``--targets-mix`` -> (force FREE, own mix): None / "" inherit curriculum.json (False, None);
    "free" / "off" / "none" force FREE runs (True, None); "p_free,p_theme,p_any" is used as given."""
    from cursed_words_solver.rl.ppo import parse_mix

    t = (text or "").strip()
    if not t:
        return False, None
    if t.lower() in FREE_WORDS:
        return True, None
    return False, parse_mix(t)


def resolve_settings(args: argparse.Namespace, curr: dict | None) -> dict:
    """The job-sampling settings of the next run: each explicit flag wins over PPO's
    curriculum.json (``curr``: its parsed dict, None = none / off), which wins over the defaults.
    Returns quest_share, crown_weights (list), char / quest / target weights, targets_mix, pivot."""
    c = curr or {}
    on = c.get("enabled", True)
    qs = args.quest_share if args.quest_share is not None else c.get("quest_share", DEFAULT_QUEST_SHARE)
    cw = parse_crown_weights(args.crown_weights) or \
        (tuple(float(x) for x in c["crown_weights"]) if c.get("crown_weights") else DEFAULT_CROWN_WEIGHTS)
    force_free, mix = own_mix_arg(args.targets_mix)
    if mix is None and not force_free and c.get("targets_mix"):
        mix = tuple(float(x) for x in c["targets_mix"])
    pivot_off, pivot = own_pivot_arg(args.pivot)
    if pivot is None and not pivot_off and c.get("pivot"):
        pv = c["pivot"]
        pivot = (float(pv[0]), int(pv[1]), int(pv[2]))
    return {"quest_share": float(qs), "crown_weights": [float(x) for x in cw],
            "char": c.get("char") if on else None, "quest": c.get("quest") if on else None,
            "target": c.get("target") if c.get("target_curriculum") else None,
            "targets_mix": None if force_free else mix, "pivot": None if pivot_off else pivot,
            "michael_bonus": float(c.get("michael_bonus", MICHAEL_BONUS))}


def job_search(search: dict, own: dict, michael_bonus: float) -> dict:
    """The job's SearchConfig dict: rollouts score a finished Michael win with PPO's training bonus
    (curriculum.json ``michael_bonus``) unless ``--search`` set ``michael_bonus`` itself; at the game's
    bonus (8) the dict is unchanged (old jobs)."""
    if "michael_bonus" in own or float(michael_bonus) == MICHAEL_BONUS:
        return search
    return {**search, "michael_bonus": float(michael_bonus)}


def run_meta(job: dict) -> dict[str, np.ndarray]:
    """Per-run shard columns (1-element int16): ``crown``, ``quest`` (1 = quest run), ``free``
    (1 = no quest, FREE target, no pivot): for crown / slice weighting in distillation."""
    quest = bool(job.get("quest"))
    free = not quest and not job.get("target") and not job.get("pivot_stage")
    return {"crown": np.asarray([int(job.get("crown") or 0)], np.int16),
            "quest": np.asarray([int(quest)], np.int16), "free": np.asarray([int(free)], np.int16)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(store.RL_HOME / "exit"))
    ap.add_argument("--policy", default=str(store.RL_HOME / "ppo1" / "weights.pt"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--runs", type=int, default=10**9)
    ap.add_argument("--search", default="", help="JSON SearchConfig, merged onto " + json.dumps(SEARCH))
    ap.add_argument("--quest-share", type=float, default=None,
                    help=f"share of quest runs; default: PPO's curriculum.json quest_share, else {DEFAULT_QUEST_SHARE}")
    ap.add_argument("--crown-weights", default=None, metavar="W0,...,W7",
                    help="crown 0-7 weights of non-quest runs; default: PPO's curriculum.json crown_weights, else uniform")
    ap.add_argument("--curriculum", default="", help="PPO curriculum.json (default: next to --policy; '-' = off)")
    ap.add_argument("--targets-mix", default=None, metavar="P_FREE,P_THEME,P_ANY",
                    help="build targets of non-quest runs (rl.ppo); 'free' / 'off' = FREE only; "
                         "default: PPO's curriculum.json targets_mix, else FREE")
    ap.add_argument("--pivot", default="", metavar="P,LO,HI",
                    help="pivot runs (rl.ppo --pivot); 'off' or p=0 = off; default: PPO's curriculum.json pivot, else off")
    args = ap.parse_args(argv)
    out = Path(args.dir).expanduser()
    (out / "shards").mkdir(parents=True, exist_ok=True)
    st_path = out / "state.json"
    state = json.loads(st_path.read_text()) if st_path.is_file() else {"started": 0, "saved": 0}
    search = parse_search(args.search)
    own_search = json.loads(args.search) if args.search and args.search.strip() else {}
    parse_crown_weights(args.crown_weights), own_mix_arg(args.targets_mix), own_pivot_arg(args.pivot)   # fail fast
    policy = str(Path(args.policy).expanduser())
    curr_path = None if args.curriculum == "-" else Path(args.curriculum or Path(policy).parent / "curriculum.json").expanduser()
    curr: dict = {"mtime": None, "data": None, "shown": None}

    def settings() -> dict:
        """``resolve_settings`` on PPO's curriculum.json (re-read when its mtime changes; missing = defaults)."""
        try:
            mt = curr_path.stat().st_mtime if curr_path is not None else None
            if mt is not None and mt != curr["mtime"]:
                curr.update(mtime=mt, data=json.loads(curr_path.read_text()))
        except (OSError, ValueError):
            pass   # being replaced: keep the last one
        st = resolve_settings(args, curr["data"])
        shown = (st["quest_share"], tuple(st["crown_weights"]), st["targets_mix"], st["pivot"], st["michael_bonus"])
        if shown != curr["shown"]:
            curr["shown"] = shown
            cws = ",".join(f"{x:g}" for x in shown[1])
            print(f"[exit] jobs: quest_share {shown[0]:g}, crown_weights {cws}, targets_mix {shown[2]}, "
                  f"pivot {shown[3]}, search {json.dumps(job_search(search, own_search, shown[4]))}", flush=True)
        return st

    from cursed_words_solver.rl.obs import OBS_VERSION
    from cursed_words_solver.rl.play import init_worker, play
    from cursed_words_solver.rl.ppo import sample_job
    from cursed_words_solver.sim.game.agent import spawn_pool

    # a fresh pipeline starts this before PPO has written its first weights
    while not Path(policy).is_file():
        if store.stop_requested(out):
            return
        time.sleep(2)
    pool = spawn_pool(args.workers, init_worker, ())
    in_flight: deque = deque()
    jobs: dict[int, dict] = {}   # seed -> job in flight, for the shard's run columns

    def submit() -> None:
        if store.stop_requested(out) or state["started"] >= args.runs:
            return
        n = state["started"]
        rng = random.Random(n * 104729 + 7)
        st = settings()
        j = sample_job(rng, n, st["quest_share"], st["crown_weights"], st["char"], st["quest"],
                       st["targets_mix"], 0.0, st["target"], st["pivot"])
        j["seed"] = EXIT_SEED0 + n
        jobs[j["seed"]] = j
        state["started"] += 1
        store.atomic_write_json(st_path, state)
        in_flight.append(pool.apply_async(play, ({**j, "policy": policy, "greedy": True, "search": job_search(search, own_search, st["michael_bonus"]),
                                                   "record_search": True},)))

    try:
        for _ in range(args.workers * 2):
            submit()
        t0, done = time.time(), 0
        while in_flight:
            ready = [a for a in in_flight if a.ready()]
            if not ready:
                time.sleep(0.2)
                continue
            for a in ready:
                in_flight.remove(a)
                res = a.get()
                tr = res.pop("traj", {}) or {}
                job = jobs.pop(res.get("seed"), None) or res
                if job.get("pivot_stage") and "pivot_stage" not in res:
                    res["pivot_stage"] = job["pivot_stage"]
                res["free"] = bool(run_meta(job)["free"][0])   # FREE-slice run (no quest / target / pivot)
                if not res.get("error") and tr.get("search_steps"):
                    data = store.pack_episode(tr["search_steps"], {
                        "chosen": np.asarray(tr["search_pick"], np.int16),
                        "margin": np.asarray(tr["search_margin"], np.float32),
                        "changed": np.asarray(tr["search_changed"], np.bool_),
                        "obs_version": np.asarray([OBS_VERSION], np.int16), **run_meta(job), **soft_targets(tr)})
                    store.atomic_write_bytes(out / "shards" / f"{res['seed']}.npz", data)
                    state["saved"] += 1
                    store.atomic_write_json(st_path, state)
                elif res.get("error"):
                    print("ERROR", res["error"], res.get("trace", "")[-300:], flush=True)
                    time.sleep(5)   # don't spin through seeds on a persistent failure
                res["n_search"] = len(tr.get("search_steps") or [])
                store.append_jsonl(out / "runs.jsonl", res)
                done += 1
                if done % 10 == 0:
                    rows = [r for r in store.read_jsonl(out / "runs.jsonl")[-200:] if not r.get("error") and r.get("crown", 0) <= 7]
                    win = np.mean([bool(r["won"]) for r in rows]) if rows else float("nan")
                    print(f"[exit] {state['saved']} shards, {done / (time.time() - t0) * 3600:.0f} runs/h, "
                          f"recent win {win:.3f}", flush=True)
                submit()
    finally:
        pool.terminate()


if __name__ == "__main__":
    main()
