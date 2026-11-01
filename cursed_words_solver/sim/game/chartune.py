"""Per-character settings (L3): search ``PowerConfig`` knobs character by character.

    python -m cursed_words_solver.sim.game.chartune run <work dir> [--characters A,B] [--passes 1]
    python -m cursed_words_solver.sim.game.chartune show [<table.json>]

Every knob below is tried as a change to one character's current settings (its champion),
on paired seeds (same character, crown and seed for champion and arm; crowns 0-7, seeds
7,000,000 + 1000 x character + 100 x crown + i, apart from the 8,000,000 benchmark seeds).
Successive halving per character and pass: all arms on 16 runs, the best 5 on 32 more, the
best 2 on 48 more; the best finalist is promoted when it beats the champion over all 96 runs
by t >= 2 and also on the last 48 (which played no part in selecting it). A paired run
difference has sd ~3.3, so 96 runs detect effects of about +0.7 outcome (Spike's rack tiles,
Sock Head's stamp order were of that size); smaller ones need more passes. Each pass draws
new seeds and re-tests every knob against the new champion, so changes can also be undone.

Runs are appended to ``<work dir>/runs.jsonl`` and reused (resumable at any point); the
table (``overrides`` for ``PowerConfig.char_overrides`` plus the decision history) is
rewritten after each character. ``NetPolicy(char_tuning=path)`` plays with it.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Callable

DEFAULT_PATH = Path.home() / ".cursed_words_solver" / "sim_models" / "char_tuning.json"
CHARS = ["BonesTheDog", "HayleyBayles", "NathaServo", "NinaNix", "Octacles", "PrismaticBean",
         "SamGambit", "SandySaguaro", "SockHead", "Spike", "WetDennis"]
CROWNS = range(8)
FIRST_SEED = 7_000_000
ROUNDS = ((2, 5), (4, 2), (6, 0))  # (new seeds per crown, arms kept for the next round)
PROMOTE_T = 2.0

# Values tried per numeric knob (the champion's own value is skipped).
VALUES: dict[str, tuple[float, ...]] = {
    "buy_threshold": (0.02, 0.06),
    "power_override": (0.03, 0.1, 1.0),  # 1.0: (almost) always follow Advice's pick
    "spend_over": (10, 20, 40),
    "reroll_reserve": (15, 30),
    "money_weight": (0.0025, 0.01),
    "michael_value": (0.5, 1.0),
}
FLIPS = ("swap_sell", "final_spend", "route_value")


def _tile_buys(cfg, char: str) -> dict[str, Any]:
    on = cfg.tile_buys or char in cfg.tile_buy_chars
    return {"tile_buys": False, "tile_buy_chars": []} if on else {"tile_buys": True}


def _sort_stamps(cfg, char: str) -> dict[str, Any]:
    on = cfg.sort_stamps or char in cfg.sort_stamps_chars
    return {"sort_stamps": False, "sort_stamps_chars": []} if on else {"sort_stamps": True}


COMPOSITE: dict[str, Callable[[Any, str], dict[str, Any]]] = {"tile_buys": _tile_buys, "sort_stamps": _sort_stamps}


def base_config():
    """The benchmark policy's settings (``expert.NetPolicy``), before any override."""
    from cursed_words_solver.sim.game import expert as E

    return E.NetPolicy(E._CANDS, None, seed=0, boss_risk=str(E.BOSS_RISK_PATH)).cfg


def arms(cfg, char: str) -> list[tuple[str, dict[str, Any]]]:
    """(label, settings changed) for every single-knob change to ``cfg`` (the champion as
    ``char`` plays it)."""
    out = []
    for k, vals in VALUES.items():
        for v in vals:
            if v != getattr(cfg, k):
                out.append((f"{k}={v}", {k: v}))
    for k in FLIPS:
        out.append((f"{k}={not getattr(cfg, k)}", {k: not getattr(cfg, k)}))
    for k, fn in COMPOSITE.items():
        d = fn(cfg, char)
        out.append((f"{k}={d[k]}", d))
    return out


def key(over: dict[str, Any]) -> str:
    return json.dumps(over, sort_keys=True)


def seeds(char: str, pass_no: int, rnd: int) -> list[tuple[int, int]]:
    """(crown, seed) of round ``rnd`` of pass ``pass_no``: fresh seeds each round and pass."""
    per_pass = sum(n for n, _ in ROUNDS)
    first = per_pass * pass_no + sum(n for n, _ in ROUNDS[:rnd])
    return [(cr, FIRST_SEED + 1000 * CHARS.index(char) + 100 * cr + i)
            for i in range(first, first + ROUNDS[rnd][0]) for cr in CROWNS]


def paired(runs: dict, char: str, a: str, b: str, ss: list[tuple[int, int]]) -> dict[str, float]:
    """Mean / t of outcome(a) - outcome(b) over ``ss``."""
    d = [runs[(char, s, a)]["outcome"] - runs[(char, s, b)]["outcome"] for _, s in ss]
    n = len(d)
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": round(m, 3), "t": round(m / (sd / math.sqrt(n)), 2) if sd else 0.0}


# -- playing -------------------------------------------------------------------------


def job(j: dict[str, Any]) -> dict[str, Any]:
    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.agent import apply
    from cursed_words_solver.sim.game.features import outcome

    t0 = time.time()
    g = E._game(j)
    pol = E.NetPolicy(E._CANDS, None, seed=j["seed"], boss_risk=str(E.BOSS_RISK_PATH))
    pol.cfg.char_overrides = {j["character"]: j["over"]} if j["over"] else {}
    for _ in range(5000):
        if g.phase == "done":
            break
        apply(g, pol.act(g))
    return {"char": j["character"], "crown": j["crown"], "seed": j["seed"], "key": key(j["over"]),
            "outcome": outcome(g), "won": bool(g.won), "reason": g.end_reason, "secs": round(time.time() - t0, 1)}


class Tuner:
    def __init__(self, work: Path, table: Path, workers: int = 8) -> None:
        self.work, self.table_path, self.workers = Path(work), Path(table), workers
        self.work.mkdir(parents=True, exist_ok=True)
        self.runs_path = self.work / "runs.jsonl"
        self.runs: dict[tuple[str, int, str], dict] = {}
        if self.runs_path.is_file():
            for line in self.runs_path.read_text().splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a line cut short by a restart
                self.runs[(r["char"], r["seed"], r["key"])] = r
        self.table = (json.loads(self.table_path.read_text()) if self.table_path.is_file()
                      else {"overrides": {}, "history": [], "done": []})
        self.pool = None

    def save(self) -> None:
        from cursed_words_solver.sim.game.expert import atomic_write

        self.table_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.table_path, json.dumps(self.table, indent=1))

    def play(self, char: str, overs: list[dict[str, Any]], ss: list[tuple[int, int]]) -> None:
        todo = [{"character": char, "crown": cr, "seed": s, "over": o} for o in overs for cr, s in ss
                if (char, s, key(o)) not in self.runs]
        if not todo:
            return
        print(f"  {len(todo)} runs", flush=True)
        for k, r in enumerate(self.pool.imap_unordered(job, todo), 1):
            self.runs[(r["char"], r["seed"], r["key"])] = r
            with self.runs_path.open("a") as f:
                f.write(json.dumps(r) + "\n")
            if k % 24 == 0:
                print(f"  {k}/{len(todo)}", flush=True)

    def tune(self, char: str, pass_no: int, base) -> dict[str, Any]:
        from cursed_words_solver.sim.game.policy import with_overrides

        champ = dict(self.table["overrides"].get(char, {}))
        alive = [(label, {**champ, **d}) for label, d in arms(with_overrides(base, champ), char)]
        used: list[tuple[int, int]] = []
        rec: dict[str, Any] = {"pass": pass_no, "char": char, "champion": champ, "rounds": []}
        for rnd, (_, keep) in enumerate(ROUNDS):
            ss = seeds(char, pass_no, rnd)
            print(f"{char} pass {pass_no} round {rnd + 1}: {len(alive)} arms x {len(ss)} seeds", flush=True)
            self.play(char, [champ] + [o for _, o in alive], ss)
            used += ss
            stats = sorted(((paired(self.runs, char, key(o), key(champ), used), label, o) for label, o in alive),
                           key=lambda t: -t[0]["mean"])
            rec["rounds"].append({label: st for st, label, _ in stats})
            for st, label, _ in stats:
                print(f"    {label:24s} {st['mean']:+.3f} (t {st['t']:+.2f}, n {st['n']})", flush=True)
            if keep:
                alive = [(label, o) for st, label, o in stats[:keep] if st["mean"] > 0]
                if not alive:
                    break
            else:
                best = stats[0]
                fresh = paired(self.runs, char, key(best[2]), key(champ), ss)
                rec.update(best=best[1], stats=best[0], fresh=fresh)
                if best[0]["mean"] > 0 and best[0]["t"] >= PROMOTE_T and fresh["mean"] > 0:
                    self.table["overrides"][char] = best[2]
                    rec["promoted"] = best[1]
                    print(f"  promoted {best[1]}", flush=True)
        return rec

    def run(self, chars: list[str], passes: int) -> None:
        from cursed_words_solver.sim.game import expert as E
        from cursed_words_solver.sim.game.agent import spawn_pool

        with spawn_pool(self.workers, E._init, (None, None, E.EFFORT, True)) as pool:
            self.pool = pool
            E._init(None, None, E.EFFORT, True)
            base = base_config()
            for p in range(passes):
                for char in chars:
                    if [p, char] in self.table["done"]:
                        continue
                    self.table["history"].append(self.tune(char, p, base))
                    self.table["done"].append([p, char])
                    self.save()


def show(table: dict[str, Any]) -> None:
    print("overrides:", json.dumps(table["overrides"], indent=1))
    for h in table["history"]:
        st = h.get("stats")
        tail = f"best {h['best']} {st['mean']:+.3f} (t {st['t']:+.2f}), fresh {h['fresh']['mean']:+.3f}" if st else "no arm survived"
        print(f"pass {h['pass']} {h['char']:14s} {tail}{'  PROMOTED' if h.get('promoted') else ''}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="per-character PowerConfig tuning (paired seeds, successive halving)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("work", type=Path)
    r.add_argument("--table", type=Path, default=DEFAULT_PATH)
    r.add_argument("--characters", default=",".join(CHARS))
    r.add_argument("--passes", type=int, default=1)
    r.add_argument("--workers", type=int, default=8)
    s = sub.add_parser("show")
    s.add_argument("table", type=Path, nargs="?", default=DEFAULT_PATH)
    args = ap.parse_args(argv)
    if args.cmd == "show":
        show(json.loads(args.table.read_text()))
        return 0
    Tuner(args.work, args.table, args.workers).run(args.characters.split(","), args.passes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
