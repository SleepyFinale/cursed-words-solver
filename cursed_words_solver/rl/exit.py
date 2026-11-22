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

``--mode early`` (exit3; off by default: without it everything above is unchanged). The greedy policy
plays each run; at most ``--labels`` (3) stage 1-``--max-stage`` (3) decisions per run are labelled
by the race search (``SearchConfig`` mode "race", ``EARLY_SEARCH``: top-3, 8 -> 32 paired futures
with drops / early stop, rollouts through the next stage's boss), at most ``--per-stage`` (1) per
stage, each eligible state with probability ``--label-p``. Eligible: shop / boss_draft /
pin_reward / Michael draft picks whose 2nd most probable candidate has probability >= 0.04. The
run then goes on with the policy's own action (``--follow pick``: the race's confident pick).
``--char-weights SockHead=3,...`` weights characters (as ``--crown-weights`` crowns); ``--keyed``
plays position-keyed real games. Seeds ``EXIT3_SEED0 + n``; seeds % 7 == 0 are held out: their
shards / rows go to ``--heldout-dir`` (default ``<dir>/heldout``). Shard columns per label:
``chosen`` (race leader), ``policy``, ``changed`` (leader != policy), ``conf`` (confident), ``t``
(runner-up vs leader paired t), ``t_pol`` / ``diff_pol`` (leader vs policy), ``n`` (leader's futures),
``margin``, ``stage``, ``kind`` (index into ``EARLY_KINDS``), ``step``, ``h2_pick`` (-1 unless
``--h2``: an exit2-style sims-2 horizon-2 pick) and the soft-target arrays (``q_se`` vs the leader).
PPO reads them with ``--distill2-dir`` (``ppo.RaceDistillBuffer``). The log prints CPU-min per label.

``--arrange`` (both modes; default off): runs play with auto-arrange (``CWEnv(arrange=True)``,
``rules.best_arrangement``: Human Boy's hands dragged before submits and at shop leave), as an
``rl.ppo --arrange`` run trains; the look-ahead's rollouts copy it (``search._sub_env``). Jobs and
runs.jsonl rows then carry ``arrange``; off = unchanged.
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
# --mode early (exit3)
EXIT3_SEED0 = 70_000_000
EARLY_SEARCH = {"mode": "race", "k": 3, "min_prob": 0.04, "race_n0": 8, "race_step": 4, "race_n_max": 32,
                "race_drop_t": -2.0, "race_stop_t": 2.5, "race_horizon": 0.0, "race_max_steps": 400}
EARLY_KINDS = ("shop", "boss_draft", "pin_reward", "michael_pick")
HELDOUT_MOD = 7   # seeds with seed % HELDOUT_MOD == 0 are held out (never distilled)
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


def parse_search(text: str | None, base: dict | None = None) -> dict:
    """``--search`` JSON merged onto ``base`` (default ``SEARCH``; so '{"sims": 2}' keeps top /
    horizon); unknown keys fail here, not in every worker."""
    import dataclasses

    from cursed_words_solver.rl.search import SearchConfig

    own = json.loads(text) if text and text.strip() else {}
    if not isinstance(own, dict):
        raise ValueError(f"--search needs a JSON object, got {text!r}")
    cfg = {**(SEARCH if base is None else base), **own}
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


def parse_char_weights(text: str | None) -> dict[str, float] | None:
    """``"SockHead=3,WetDennis=2"`` -> {character: weight} (unlisted characters 1); None / "" -> None."""
    if text is None or not str(text).strip():
        return None
    from cursed_words_solver.rl.teacher import CHARS

    out: dict[str, float] = {}
    for part in str(text).split(","):
        name, _, w = part.partition("=")
        name = name.strip()
        if name not in CHARS or not w.strip():
            raise ValueError(f"--char-weights needs NAME=W pairs with names from {list(CHARS)}, got {part!r}")
        out[name] = float(w)
        if out[name] < 0:
            raise ValueError(f"--char-weights: negative weight {part!r}")
    if sum(out.get(c, 1.0) for c in CHARS) <= 0:
        raise ValueError("--char-weights: all weights 0")
    return out


def early_eligible(game, probs, max_stage: int = 3, min_second: float = 0.04) -> tuple[int, str] | None:
    """(stage, kind) when this decision is an exit3 label candidate: stage 1..``max_stage``, kind in
    ``EARLY_KINDS`` (play.step_label: Michael draft picks are "michael_pick"), >= 2 candidates and
    the 2nd most probable has probability >= ``min_second``; else None."""
    from cursed_words_solver.rl.play import step_label

    stage, kind = step_label(game)
    if kind not in EARLY_KINDS or not 1 <= stage <= max_stage or len(probs) < 2:
        return None
    if float(np.sort(np.asarray(probs))[-2]) < min_second:
        return None
    return stage, kind


def heldout(seed: int) -> bool:
    return int(seed) % HELDOUT_MOD == 0


def early_run(job: dict) -> dict:
    """One exit3 run in a worker (``play.init_worker``): the greedy policy plays the job; eligible
    decisions (``early_eligible``) are race-labelled (``Searcher.race``, key ``exit3|{seed}|{step}``)
    up to ``labels`` per run / ``per_stage`` per stage, each with probability ``label_p`` (drawn from
    ``random.Random(f"exit3|{seed}")``). Job keys beyond play's: search (SearchConfig dict), labels,
    per_stage, label_p, max_stage, min_second, follow ("policy" | "pick"), h2 (bool), keep_vals (bool:
    labels carry the rollout values). Returns the run row with ``labels`` (JSON-able dicts),
    ``label_steps`` (env.pack per label), ``cpu`` / ``label_cpu`` (process seconds)."""
    import traceback

    from cursed_words_solver.rl import play as P
    from cursed_words_solver.rl.env import CWEnv, pack
    from cursed_words_solver.rl.model import Actor
    from cursed_words_solver.rl.search import SearchConfig, Searcher
    from cursed_words_solver.rl.targets import FREE

    t0, c0 = time.time(), time.process_time()
    seed = int(job["seed"])
    labels: list[dict] = []
    steps: list[dict] = []
    label_cpu = 0.0
    res: dict = {k: job.get(k) for k in ("character", "crown", "seed", "quest")}
    try:
        env = CWEnv(P._CANDS, arrange=bool(job.get("arrange")))
        env.reset(character=job["character"], crown=job["crown"], seed=seed, quest=job.get("quest"),
                  target=job.get("target") or FREE, keyed=bool(job.get("keyed")))
        actor = Actor(P._model(job["policy"]), greedy=True, seed=seed)
        cfg = SearchConfig(**{**EARLY_SEARCH, **(job.get("search") or {})})
        searcher = Searcher(actor, cfg)
        h2 = Searcher(actor, SearchConfig(top=3, sims=2, horizon=2.0, michael_bonus=cfg.michael_bonus)) \
            if job.get("h2") else None
        rng = random.Random(f"exit3|{seed}")
        L, per_stage = int(job.get("labels", 3)), int(job.get("per_stage", 1))
        p_label = float(job.get("label_p", 0.5))
        per: dict[int, int] = {}
        while not env.done:
            st = env.current()
            if not st.cands:
                raise RuntimeError(f"no candidates in phase {env.game.phase}")
            pk = pack(st)
            probs, _, _ = actor.evaluate(pk)
            best = int(np.argmax(probs))
            i = best
            el = early_eligible(env.game, probs, int(job.get("max_stage", 3)), float(job.get("min_second", 0.04))) \
                if len(labels) < L else None
            if el is not None and per.get(el[0], 0) < per_stage and rng.random() < p_label:
                lc = time.process_time()
                key = f"exit3|{seed}|{env.steps}"
                info = searcher.race(env, st, probs, key)
                if len(info["cands"]) >= 2:
                    per[el[0]] = per.get(el[0], 0) + 1
                    lab = {"step": int(env.steps), "stage": el[0], "kind": el[1], "key": key, "n_cands": len(st.cands),
                           "cands": [int(c) for c in info["cands"]],
                           "probs": [float(probs[c]) for c in info["cands"]],
                           "desc": [str(st.cands[c].action)[:160] for c in info["cands"]],
                           "q": [info["q"][c] for c in info["cands"]], "n": [info["n"][c] for c in info["cands"]],
                           "t": [float(info["t"][c]) for c in info["cands"]],
                           "se": [float(info["se"][c]) if np.isfinite(info["se"][c]) else 0.0 for c in info["cands"]],
                           "alive": [int(c) for c in info["alive"]], "leader": int(info["leader"]),
                           "policy": int(info["policy"]), "pick": int(info["pick"]),
                           "changed": int(info["leader"]) != int(info["policy"]), "conf": bool(info["confident"]),
                           "t2": float(info["t2"]), "t_pol": float(info["t_pol"]), "diff_pol": float(info["diff_pol"]),
                           "margin": float(info["margin"]), "horizon": float(info["horizon"]),
                           "rounds": int(info["rounds"]), "h2_pick": -1}
                    lab["cpu_race"] = round(time.process_time() - lc, 2)
                    if job.get("keep_vals"):
                        lab["vals"] = {str(c): list(v) for c, v in info["vals"].items()}
                    if h2 is not None:
                        sc = h2.scores(env, st, probs, f"search|{seed}|{env.steps}")
                        lab["h2_pick"] = int(max(sc, key=lambda c: (sc[c], probs[c])))
                        lab["h2_scores"] = {str(c): float(v) for c, v in sc.items()}
                    lab["cpu"] = round(time.process_time() - lc, 2)   # race (+ h2) search
                    label_cpu += time.process_time() - lc
                    labels.append(lab)
                    steps.append(pk)
                    if job.get("follow") == "pick":
                        i = int(info["pick"])
            env.step(st.cands[i].action)
        res.update({**env.result(), "error": ""})
    except Exception as exc:   # noqa: BLE001 - the collector logs and moves on
        res.update({"won": False, "outcome": 0.0, "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc()[-1200:]})
        labels, steps = [], []
    res.update({"secs": round(time.time() - t0, 1), "cpu": round(time.process_time() - c0, 2),
                "label_cpu": round(label_cpu, 2), "labels": labels, "label_steps": steps,
                **({"keyed": True} if job.get("keyed") else {}), **({"arrange": True} if job.get("arrange") else {})})
    return res


def _label_t(x: dict) -> float:
    """Shard ``t`` of one label: the runner-up's t vs the leader, or (only the leader survived) the
    largest t among the other candidates (the closest dropped one); 0 with no other candidate."""
    if len(x.get("alive") or []) > 1 or "t" not in x:
        return float(x["t2"])
    ts = [float(t) for c, t in zip(x["cands"], x["t"]) if c != x["leader"]]
    return max(ts) if ts else 0.0


def early_shard(res: dict, job: dict, k: int = 3) -> bytes | None:
    """The exit3 shard of one ``early_run`` result (None: no labels)."""
    from cursed_words_solver.rl.obs import OBS_VERSION

    labs, steps = res.get("labels") or [], res.get("label_steps") or []
    if not labs or len(labs) != len(steps):
        return None
    w = max(k, max(len(x["cands"]) for x in labs))

    def row(x, key, fill, dt):
        v = np.full(w, fill, dt)
        v[: len(x[key])] = x[key]
        return v

    cols = {
        "chosen": np.asarray([x["leader"] for x in labs], np.int16),
        "policy": np.asarray([x["policy"] for x in labs], np.int16),
        "changed": np.asarray([x["changed"] for x in labs], np.bool_),
        "conf": np.asarray([x["conf"] for x in labs], np.bool_),
        # runner-up's t; with no survivor besides the leader (confident by drops) race's t2 is 0, so
        # store the closest dropped candidate's t instead (a confident label never reads as t 0)
        "t": np.asarray([_label_t(x) for x in labs], np.float32),
        "t_pol": np.asarray([x["t_pol"] for x in labs], np.float32),
        "diff_pol": np.asarray([x["diff_pol"] for x in labs], np.float32),
        "n": np.asarray([x["n"][x["cands"].index(x["leader"])] for x in labs], np.int16),
        "margin": np.asarray([x["margin"] for x in labs], np.float32),
        "stage": np.asarray([x["stage"] for x in labs], np.int16),
        "kind": np.asarray([EARLY_KINDS.index(x["kind"]) for x in labs], np.int16),
        "step": np.asarray([x["step"] for x in labs], np.int32),
        "h2_pick": np.asarray([x.get("h2_pick", -1) for x in labs], np.int16),
        "q_idx": np.stack([row(x, "cands", -1, np.int16) for x in labs]),
        "q_val": np.stack([row(x, "q", 0, np.float32) for x in labs]),
        "q_n": np.stack([row(x, "n", 0, np.int16) for x in labs]),
        "q_se": np.stack([row(x, "se", 0, np.float32) for x in labs]),
        "obs_version": np.asarray([OBS_VERSION], np.int16), **run_meta(job)}
    return store.pack_episode(steps, cols)


class _InlinePool:
    """``--workers 0``: run jobs in this process (one CPU process; tests / smoke)."""

    class _Done:
        def __init__(self, v):
            self.v = v

        def ready(self):
            return True

        def get(self):
            return self.v

    def apply_async(self, fn, args):
        return self._Done(fn(*args))

    def terminate(self):
        pass


def main_early(args: argparse.Namespace) -> None:
    """``--mode early``: the exit3 collector (module doc)."""
    out = Path(args.dir).expanduser()
    ho = Path(args.heldout_dir).expanduser() if args.heldout_dir else out / "heldout"
    for d in (out, ho):
        (d / "shards").mkdir(parents=True, exist_ok=True)
    st_path = out / "state.json"
    state = json.loads(st_path.read_text()) if st_path.is_file() else {"started": 0, "saved": 0, "heldout": 0}
    search = parse_search(args.search, EARLY_SEARCH)
    own_search = json.loads(args.search) if args.search and args.search.strip() else {}
    char_w = parse_char_weights(args.char_weights)
    parse_crown_weights(args.crown_weights), own_mix_arg(args.targets_mix), own_pivot_arg(args.pivot)   # fail fast
    policy = str(Path(args.policy).expanduser())
    curr_path = None if args.curriculum == "-" else Path(args.curriculum or Path(policy).parent / "curriculum.json").expanduser()
    curr_data = None

    from cursed_words_solver.rl.play import init_worker
    from cursed_words_solver.rl.ppo import sample_job
    from cursed_words_solver.sim.game.agent import spawn_pool

    while not Path(policy).is_file():
        if store.stop_requested(out):
            return
        time.sleep(2)
    if args.workers > 0:
        pool = spawn_pool(args.workers, init_worker, ())
    else:
        init_worker()
        pool = _InlinePool()
    in_flight: deque = deque()
    jobs: dict[int, dict] = {}
    tot = {"cpu": 0.0, "label_cpu": 0.0, "labels": 0, "conf": 0, "changed_conf": 0}

    def submit() -> None:
        nonlocal curr_data
        if store.stop_requested(out) or state["started"] >= args.runs:
            return
        try:
            if curr_path is not None and curr_path.is_file():
                curr_data = json.loads(curr_path.read_text())
        except (OSError, ValueError):
            pass
        n = state["started"]
        st = resolve_settings(args, curr_data)
        rng = random.Random(n * 104729 + 11)
        j = sample_job(rng, n, st["quest_share"], st["crown_weights"], char_w if char_w is not None else st["char"],
                       st["quest"], st["targets_mix"], 0.0, st["target"], None)
        j["seed"] = EXIT3_SEED0 + n
        j.update({"policy": policy, "search": job_search(search, own_search, st["michael_bonus"]),
                  "labels": args.labels, "per_stage": args.per_stage, "label_p": args.label_p,
                  "max_stage": args.max_stage, "min_second": args.min_second, "follow": args.follow,
                  "h2": bool(args.h2), **({"keyed": True} if args.keyed else {}),
                  **({"arrange": True} if args.arrange else {})})
        jobs[j["seed"]] = j
        state["started"] += 1
        store.atomic_write_json(st_path, state)
        in_flight.append(pool.apply_async(early_run, (j,)))

    print(f"[exit3] mode early: labels {args.labels}/run, per stage {args.per_stage}, p {args.label_p:g}, "
          f"stages 1-{args.max_stage}, follow {args.follow}, chars {char_w}, search {json.dumps(search)}"
          + (", arrange on" if args.arrange else ""), flush=True)
    try:
        for _ in range(max(1, args.workers) * 2):
            submit()
        done = 0
        while in_flight:
            ready = [a for a in in_flight if a.ready()]
            if not ready:
                time.sleep(0.2)
                continue
            for a in ready:
                in_flight.remove(a)
                res = a.get()
                job = jobs.pop(res.get("seed"), None) or res
                hold = heldout(res["seed"])
                dst = ho if hold else out
                data = early_shard(res, job) if not res.get("error") else None
                if data is not None:
                    store.atomic_write_bytes(dst / "shards" / f"{res['seed']}.npz", data)
                    state["heldout" if hold else "saved"] = state.get("heldout" if hold else "saved", 0) + 1
                    store.atomic_write_json(st_path, state)
                elif res.get("error"):
                    print("ERROR", res["error"], res.get("trace", "")[-300:], flush=True)
                    time.sleep(5 if args.workers > 0 else 0)
                labs = res.pop("labels", [])
                res.pop("label_steps", None)
                res["n_labels"] = len(labs)
                res["n_conf"] = sum(bool(x["conf"]) for x in labs)
                res["n_changed_conf"] = sum(bool(x["conf"] and x["changed"]) for x in labs)
                res["label_summary"] = [{k: x[k] for k in ("step", "stage", "kind", "cands", "n", "leader", "policy",
                                                          "conf", "t2", "h2_pick", "cpu")} for x in labs]
                res["heldout"] = hold
                res["free"] = bool(run_meta(job)["free"][0])
                store.append_jsonl(dst / "runs.jsonl", res)
                tot["cpu"] += float(res.get("cpu", 0.0))
                tot["label_cpu"] += float(res.get("label_cpu", 0.0))
                tot["labels"] += len(labs)
                tot["conf"] += res["n_conf"]
                tot["changed_conf"] += res["n_changed_conf"]
                done += 1
                if done % 5 == 0 or not in_flight:
                    nl = max(1, tot["labels"])
                    print(f"[exit3] {done} runs, {tot['labels']} labels ({tot['conf']} confident, "
                          f"{tot['changed_conf']} confident switches), CPU-min/label {tot['cpu'] / 60 / nl:.2f} "
                          f"(search only {tot['label_cpu'] / 60 / nl:.2f})", flush=True)
                submit()
    finally:
        pool.terminate()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="output dir (default rl/exit; --mode early: rl/exit3)")
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
    # --mode early (exit3); none of these change the default collector
    ap.add_argument("--mode", default="", choices=("", "early"),
                    help="'early': exit3 race labels of stage 1-3 decisions (module doc); default: the exit2 collector")
    ap.add_argument("--labels", type=int, default=3, help="early: labels per run at most")
    ap.add_argument("--per-stage", type=int, default=1, help="early: labels per stage at most")
    ap.add_argument("--label-p", type=float, default=0.5, help="early: probability an eligible state is labelled")
    ap.add_argument("--max-stage", type=int, default=3, help="early: label stages 1..N")
    ap.add_argument("--min-second", type=float, default=0.04, help="early: 2nd candidate probability needed")
    ap.add_argument("--follow", default="policy", choices=("policy", "pick"),
                    help="early: the run continues with the policy's action, or the race's confident pick")
    ap.add_argument("--char-weights", default=None, metavar="NAME=W,...",
                    help="early: character weights (unlisted 1; default: PPO's curriculum, else uniform)")
    ap.add_argument("--heldout-dir", default="", help="early: dir of the held-out seeds (seed %% 7 == 0); default <dir>/heldout")
    ap.add_argument("--keyed", action="store_true", help="early: position-keyed real games (RunConfig.keyed_rng)")
    ap.add_argument("--h2", action="store_true", help="early: also store an exit2-style sims-2 horizon-2 pick (h2_pick)")
    ap.add_argument("--arrange", action="store_true",
                    help="both modes: auto-arrange positional items (Human Boy's hands) in the runs and rollouts")
    args = ap.parse_args(argv)
    if args.mode == "early":
        args.dir = args.dir or str(store.RL_HOME / "exit3")
        return main_early(args)
    args.dir = args.dir or str(store.RL_HOME / "exit")
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
    if args.arrange:
        print("[exit] auto-arrange on", flush=True)

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
                                                   "record_search": True, **({"arrange": True} if args.arrange else {})},)))

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
