"""Play many seeded runs in parallel and report win rates (also writes decision logs).

    python -m cursed_words_solver.sim.game.evaluate --character Carpman --crown 0 --runs 16
    python -m cursed_words_solver.sim.game.evaluate --quest SicilianDefense --runs 8 --policy greedy

Each run appends one JSON line to ``--out`` with the outcome and every decision
(phase, chosen action, money, stage/node) — the raw material for training.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
from pathlib import Path
from typing import Any

_CANDS = None


def _worker_init(wordlist: str | None, effort: float | None = None) -> None:
    global _CANDS
    from cursed_words_solver.sim.game.agent import Candidates

    _CANDS = Candidates(Path(wordlist) if wordlist else None, time_budget=5.0, effort=effort)


def _make_policy(name: str, seed: int, cfg: dict | None = None):
    from cursed_words_solver.sim.game.policy import AdvicePolicy, GreedyPolicy, PowerConfig, PowerPolicy

    pc = None
    if cfg and name != "rollout":
        pc = PowerConfig(probe_seeds=1, probe_grids=3) if name == "advice" else PowerConfig()
        for k, v in cfg.items():
            setattr(pc, k, type(getattr(pc, k))(v) if not isinstance(getattr(pc, k), bool) else v in ("1", "true", "True"))

    if name == "greedy":
        return GreedyPolicy(_CANDS)
    if name == "advice":
        return AdvicePolicy(_CANDS, pc, seed=seed)
    if name == "rollout":
        from cursed_words_solver.sim.game.rollout import RolloutConfig, RolloutPolicy

        rc = RolloutConfig()
        for k, v in (cfg or {}).items():
            if hasattr(rc, k):
                setattr(rc, k, type(getattr(rc, k))(v))
        return RolloutPolicy(_CANDS, rc, seed=seed)
    if name.startswith("value:"):
        from cursed_words_solver.sim.game.learn import MLP, ValuePolicy

        return ValuePolicy(_CANDS, MLP.load(Path(name.split(":", 1)[1])), epsilon=0.0, seed=seed)
    return PowerPolicy(_CANDS, pc, seed=seed)


def play_one(job: dict[str, Any]) -> dict[str, Any]:
    from cursed_words_solver.sim.game.policy import play
    from cursed_words_solver.sim.game.run import Game, RunConfig

    t0 = time.time()
    g = Game(RunConfig(
        character=job["character"], ascension=job["crown"], challenge=job.get("quest"),
        seed=job["seed"], wordlist=_CANDS.wordlist,
    ))
    pol = _make_policy(job["policy"], job["seed"], job.get("cfg"))
    decisions: list[dict[str, Any]] = []

    def log(game, action):
        run = game.player.run
        row = {"stage": run.stage, "node": run.node.name, "money": game.player.money, "kind": action.kind,
               "label": action.label or action.kind}
        if game.encounter is not None:
            e = game.encounter
            row.update({"remaining": e.remaining_target, "grids_left": e.remaining_grids, "rerolls": e.rerolls})
        decisions.append(row)

    err = ""
    try:
        play(g, pol, log=log)
    except Exception as exc:  # keep sweeping; report the failure
        import traceback

        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}"
    p = g.player
    return {
        **job,
        "won": bool(g.won),
        "end": g.end_reason,
        "stage": p.run.stage,
        "node": p.run.node.name,
        "money": p.money,
        "stickers": [f"{i.game_class}:{i.level(0)}{'*' if i.is_foil else ''}" for i in p.stickers if i],
        "stamps": [i.game_class for i in p.stamps if i],
        "pin": [p.pin.level(0), p.pin.level(1)] if p.pin is not None and len(p.pin.components) == 2 else None,
        "seconds": round(time.time() - t0, 1),
        "error": err,
        "decisions": decisions,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--character", default="Carpman")
    ap.add_argument("--crown", type=int, default=0)
    ap.add_argument("--quest", default=None)
    ap.add_argument("--runs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--policy", default="power", help="power | greedy | advice | value:<model.npz>")
    ap.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    ap.add_argument("--wordlist", default=None)
    ap.add_argument("--out", default="sim_runs.jsonl")
    ap.add_argument("--cfg", action="append", default=[], help="PowerConfig override key=value (repeatable)")
    ap.add_argument("--effort", type=float, default=None,
                    help="deterministic word search at this effort (e.g. 0.05) instead of a 5 s deadline")
    ap.add_argument("--verbose", action="store_true", help="print every decision (runs play in this process)")
    args = ap.parse_args(argv)

    if args.verbose:
        _worker_init(args.wordlist, args.effort)
        for i in range(args.runs):
            res = play_one({"character": args.character, "crown": args.crown, "quest": args.quest,
                            "seed": args.seed + i, "policy": args.policy})
            for d in res["decisions"]:
                extra = f" need {d['remaining']} grids {d['grids_left']}" if "remaining" in d else ""
                print(f"  st{d['stage']} {d['node']:16s} ${d['money']:<4}{extra}  {d['label']}")
            print(f"seed {res['seed']}: {'WIN' if res['won'] else 'loss'} {res['end']} stage {res['stage']} {res['stickers']} {res['stamps']}")
        return 0

    jobs = [
        {"character": args.character, "crown": args.crown, "quest": args.quest,
         "seed": args.seed + i, "policy": args.policy, "cfg": dict(kv.split("=", 1) for kv in args.cfg)}
        for i in range(args.runs)
    ]
    t0 = time.time()
    wins = 0
    stages: list[int] = []
    out = Path(args.out)
    from cursed_words_solver.sim.game.agent import spawn_pool

    with spawn_pool(args.workers, initializer=_worker_init, initargs=(args.wordlist, args.effort)) as pool, \
            out.open("a", encoding="utf-8") as fh:
        for res in pool.imap_unordered(play_one, jobs):
            wins += res["won"]
            stages.append(res["stage"])
            fh.write(json.dumps(res) + "\n")
            fh.flush()
            tag = "ERROR " + res["error"].splitlines()[0] if res["error"] else ""
            print(f"seed {res['seed']}: {'WIN ' if res['won'] else 'loss'} {res['end']:12s} stage {res['stage']} "
                  f"{res['node']:16s} ${res['money']:<4} {res['stickers']} {res['stamps']} {res['seconds']}s {tag}", flush=True)
    n = len(jobs)
    print(f"\n{args.policy} {args.character} crown {args.crown}{' quest ' + args.quest if args.quest else ''}: "
          f"{wins}/{n} wins ({100 * wins / n:.0f}%), mean stage {sum(stages) / n:.2f}, {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
