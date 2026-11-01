"""Long-horizon item value: what an item will still add to the build in later stages.

    python -m cursed_words_solver.sim.game.buildvalue collect <out.jsonl> --seeds 3 --crowns 0,1,2,3
    python -m cursed_words_solver.sim.game.buildvalue fit <logs.jsonl> ...   # fit and save

The shop judges a buy by its *contribution* now: probe points with the item over probe
points without it, minus 1, at the next encounter. Runs are lost in stages 4-5, where
targets have grown x3.8 per stage, and items differ in how their contribution develops:
grid-changing and scaling items (Haunted Mirror, Radio, Cursed VHS, Tombstone) grow from
~+0.6 at purchase to many times the build later, flat-point items (Briefcase, Ham
Sandwich, Candle) fade (2026-10-30, 132 runs, ``collect``).

``collect`` plays base runs and measures leave-one-out contributions of owned stickers /
stamps at shop exits (items bought there, and all items at each SHOP_TWO), on the same
probe grids with and without the item. ``ItemGrowth`` is a ridge regression of
log(1 + contribution at stage t) on log(1 + contribution at an earlier stage u), t - u, u,
and per-class offset and per-class slope in t - u (shrunk toward the average item), fitted
on every ordered pair of one item's measurements. ``value`` is the item's contribution
averaged in log space over the stages left (this one included, at its measured value),
in the same units as the shop's probe gain: uniformly, or (``build_value_risk``) weighted by
each stage's chance of losing a fight (``stage_weights``), so a fight at risk now counts
more than safe later ones. ``PowerConfig.build_value`` makes the shop use
it for buys, Advice overrides and swaps. Every run collected adds data, so refitting
improves it as the policy changes.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_PATH = Path.home() / ".cursed_words_solver" / "sim_models" / "build_value.json"
LAST_STAGE = 5
PROBE_SEEDS, PROBE_GRIDS = 2, 2
CHARS = ["BonesTheDog", "HayleyBayles", "NathaServo", "NinaNix", "Octacles", "PrismaticBean",
         "SamGambit", "SandySaguaro", "SockHead", "Spike", "WetDennis"]


def _l(c: float) -> float:
    return math.log1p(max(c, -0.95))


# -- data ----------------------------------------------------------------------------


def rows(paths: list[Path]) -> list[tuple[int, str, int, int, float, float]]:
    """(run index, class, stage u, stage t, contribution at u, at t) for every ordered pair
    u < t of one item's measurements."""
    out, k = [], 0
    for path in paths:
        for line in Path(path).read_text().splitlines():
            r = json.loads(line)
            for it in r["items"]:
                cs = it["contrib"]
                for i, a in enumerate(cs):
                    for b in cs[i + 1:]:
                        if b[0] > a[0]:
                            out.append((k, it["cls"], a[0], b[0], a[2], b[2]))
            k += 1
    return out


# -- model ---------------------------------------------------------------------------


class ItemGrowth:
    N_BASE = 4  # log(1 + c_u), t - u, u, 1

    def __init__(self, classes: list[str], w: list[float], lam: float = 10.0) -> None:
        self.classes, self.w, self.lam = list(classes), np.array(w, dtype=float), lam
        self._ix = {c: i for i, c in enumerate(self.classes)}

    def _x(self, cls: str, c_u: float, u: int, t: int) -> np.ndarray:
        n = len(self.classes)
        x = np.zeros(self.N_BASE + 2 * n)
        d = t - u
        x[:4] = (_l(c_u), d, u, 1.0)
        i = self._ix.get(cls)
        if i is not None:
            x[4 + i] = 1.0
            x[4 + n + i] = d
        return x

    @classmethod
    def fit(cls, data: list[tuple], lam: float = 10.0) -> "ItemGrowth":
        m = cls(sorted({r[1] for r in data}), [], lam)
        X = np.array([m._x(r[1], r[4], r[2], r[3]) for r in data])
        y = np.array([_l(r[5]) for r in data])
        reg = np.full(X.shape[1], lam)
        reg[: cls.N_BASE] = 1e-6
        m.w = np.linalg.solve(X.T @ X + np.diag(reg), X.T @ y)
        return m

    def predict(self, cls: str, c_u: float, u: int, t: int) -> float:
        """log(1 + contribution) expected at stage ``t`` (= measured at ``t == u``)."""
        if t <= u:
            return _l(c_u)
        return float(self._x(cls, c_u, u, t) @ self.w)

    def value(self, cls: str, c_now: float, stage: int, weights: dict[int, float] | None = None) -> float:
        """Contribution averaged in log space over stages ``stage``..5 (relative-gain units),
        uniformly or by ``weights`` per stage (``stage_weights``)."""
        stage = max(1, min(stage, LAST_STAGE))
        ts = range(stage, LAST_STAGE + 1)
        w = [max(0.0, (weights or {}).get(t, 0.0)) for t in ts] if weights else [1.0] * len(ts)
        if sum(w) < 1e-6:
            w = [1.0] * len(ts)
        return math.expm1(sum(wi * self.predict(cls, c_now, stage, t) for wi, t in zip(w, ts)) / sum(w))

    def save(self, path: Path = DEFAULT_PATH, **info: Any) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"classes": self.classes, "w": list(self.w), "lam": self.lam, **info}))

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "ItemGrowth":
        d = json.loads(Path(path).read_text())
        return cls(d["classes"], d["w"], d.get("lam", 10.0))


# -- survival weights ----------------------------------------------------------------

# P(clearing a fight) = sigmoid(a log strength + b stage + c), strength = probe points per grid
# x the fight's grids / its target (``PowerPolicy.boss_strength``'s units). Fitted on the 2,606
# boss-draft options of bossdiag (352 base runs, crowns 0-7, 2026-10-30).
CLEAR_W = (3.63, -0.434, 1.94)
# Mean growth of probe points from one stage's SHOP_TWO to the next (132 base runs, crowns 0-3).
STAGE_GROWTH = {1: 3.25, 2: 2.27, 3: 2.52, 4: 1.67}


def p_clear(strength: float, stage: int) -> float:
    a, b, c = CLEAR_W
    return 1 / (1 + math.exp(-(a * math.log(max(strength, 1e-3)) + b * stage + c)))


def stage_weights(strength: float, stage: int, node, target) -> dict[int, float]:
    """P(losing one of the stage's fights still ahead) for stages ``stage``..5, from
    ``strength`` at the next fight (``node`` of ``stage``) projected to each later fight by
    its target (``target(stage, node)``) and the build's usual growth per stage. An item's
    contribution only matters where a fight can be lost, and d log P(clear) / d log strength
    is proportional to P(lose) under the logistic, so these weight its log contribution."""
    from cursed_words_solver.sim.game.player import ENCOUNTER_NODES

    t0 = target(stage, node)
    out = {}
    for t in range(stage, LAST_STAGE + 1):
        grow = math.prod(STAGE_GROWTH.get(s, 1.0) for s in range(stage, t))
        clear = 1.0
        for n in ENCOUNTER_NODES:
            if t == stage and n < node:
                continue
            clear *= p_clear(strength * grow * t0 / max(1, target(t, n)), t)
        out[t] = 1 - clear
    return out


def cross_validate(data: list[tuple], lam: float, with_class: bool = True, folds: int = 5) -> dict[str, float]:
    """Held-out R^2 / correlation of log(1 + later contribution), folds split by run."""
    data = [r if with_class else (r[0], "", *r[2:]) for r in data]
    y = np.array([_l(r[5]) for r in data])
    pred = np.zeros(len(data))
    for f in range(folds):
        tr = [r for r in data if r[0] % folds != f]
        te = [i for i, r in enumerate(data) if r[0] % folds == f]
        m = ItemGrowth.fit(tr, lam)
        for i in te:
            r = data[i]
            pred[i] = m.predict(r[1], r[4], r[2], r[3])
    r2 = 1 - float(np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2))
    return {"r2": round(r2, 3), "corr": round(float(np.corrcoef(pred, y)[0, 1]), 3)}


# -- collection ----------------------------------------------------------------------


def probe(pol, game) -> float:
    """Greedy probe points at the next encounter (fixed probe grids, so with / without an
    item see the same grids wherever the item does not change them)."""
    from cursed_words_solver.sim.game.policy import next_encounter_node

    stage, node = next_encounter_node(game)
    tot = 0
    for s in range(PROBE_SEEDS):
        g = pol._probe_game(game, stage, node, 100 + s)
        enc = g.encounter
        for _ in range(min(PROBE_GRIDS, enc.total_grids)):
            if enc.lost or enc.remaining_grids <= 0:
                break
            opts = pol.probe_cands.words(g, 1)
            if not opts:
                enc.skip()
                continue
            tot += max(0, enc.submit(opts[0].path, opts[0].words).score)
    return tot / PROBE_SEEDS


def contributions(pol, game, which: set[int]) -> tuple[float, dict[int, tuple[float, int]]]:
    """Probe points, and for each owned sticker / stamp whose id is in ``which``: (with /
    without - 1, slot)."""
    from cursed_words_solver.sim.game.agent import clone

    base = probe(pol, game)
    out = {}
    p = game.player
    for kind, arr in (("sticker", p.stickers), ("stamp", p.stamps)):
        for i, it in enumerate(arr):
            if it is None or id(it) not in which:
                continue
            g = clone(game)
            g.player.remove_item((g.player.stickers if kind == "sticker" else g.player.stamps)[i])
            out[id(it)] = (base / max(1.0, probe(pol, g)) - 1, i)
    return base, out


def collect_job(j: dict[str, Any]) -> dict[str, Any]:
    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.agent import apply
    from cursed_words_solver.sim.game.features import outcome

    t0 = time.time()
    g = E._game(j)
    pol = E.NetPolicy(E._CANDS, None, seed=j["seed"], boss_risk=str(E.BOSS_RISK_PATH))
    for k, v in (j.get("cfg") or {}).items():
        setattr(pol.cfg, k, v)
    items: dict[int, dict] = {}
    new_here: set[int] = set()

    def owned():
        p = g.player
        return {id(it): (k, it) for k, arr in (("sticker", p.stickers), ("stamp", p.stamps)) for it in arr if it is not None}

    for _ in range(5000):
        if g.phase == "done":
            break
        a = pol.act(g)
        run = g.player.run
        if g.phase == "shop" and a.kind == "leave":
            have = owned()
            which = set(have) if run.node.name == "SHOP_TWO" else (new_here & set(have))
            if which:
                base, cs = contributions(pol, g, which)
                for uid, (c, slot) in cs.items():
                    kind, it = have[uid]
                    rec = items.setdefault(uid, {"cls": it.game_class, "kind": kind, "contrib": []})
                    rec["contrib"].append([run.stage, run.node.name, round(c, 4), it.level() if kind == "sticker" else 1,
                                           slot, base])
            new_here = set()
        before = set(owned()) if a.kind == "buy" else None
        apply(g, a)
        if before is not None:
            new_here |= set(owned()) - before
    return {"char": j["character"], "crown": j["crown"], "seed": j["seed"], "won": bool(g.won),
            "reason": g.end_reason, "outcome": outcome(g), "stage": g.player.run.stage,
            "items": list(items.values()), "secs": round(time.time() - t0, 1)}


def collect(out: Path, seeds: int, crowns: list[int], chars: list[str], first_seed: int = 9_700_000,
            cfg: dict | None = None, workers: int = 8) -> None:
    """Resumable: runs already in ``out`` (by seed) are skipped."""
    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.agent import spawn_pool

    jobs = [{"character": ch, "crown": cr, "seed": first_seed + 1000 * CHARS.index(ch) + 100 * cr + i, "cfg": cfg}
            for i in range(seeds) for ch in chars for cr in crowns]
    have = {json.loads(x)["seed"] for x in out.read_text().splitlines()} if out.is_file() else set()
    todo = [j for j in jobs if j["seed"] not in have]
    print(f"{len(have)} done, {len(todo)} to run", flush=True)
    with spawn_pool(workers, E._init, (None, None, E.EFFORT, True)) as pool:
        for k, r in enumerate(pool.imap_unordered(collect_job, todo), 1):
            with out.open("a") as f:
                f.write(json.dumps(r) + "\n")
            if k % 11 == 0:
                print(f"{k}/{len(todo)}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="long-horizon item value: collect contributions, fit ItemGrowth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("out", type=Path)
    c.add_argument("--seeds", type=int, default=3)
    c.add_argument("--crowns", default="0,1,2,3")
    c.add_argument("--characters", default=",".join(CHARS))
    c.add_argument("--first-seed", type=int, default=9_700_000)
    c.add_argument("--workers", type=int, default=8)
    f = sub.add_parser("fit")
    f.add_argument("logs", nargs="+", type=Path)
    f.add_argument("--out", type=Path, default=DEFAULT_PATH)
    args = ap.parse_args(argv)
    if args.cmd == "collect":
        collect(args.out, args.seeds, [int(x) for x in args.crowns.split(",")], args.characters.split(","),
                args.first_seed, workers=args.workers)
        return 0
    data = rows(args.logs)
    print(f"{len(data)} pairs, {len({r[1] for r in data})} classes, {max(r[0] for r in data) + 1} runs")
    print("  without class:", cross_validate(data, 10.0, with_class=False))
    best = max((1.0, 3.0, 10.0, 30.0, 100.0), key=lambda lam: cross_validate(data, lam)["r2"])
    print(f"  with class (lam {best}):", cross_validate(data, best))
    m = ItemGrowth.fit(data, best)
    m.save(args.out, pairs=len(data))
    print("saved", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
