"""Policy iteration from paired full-run rollouts: the AI that improves with more runs.

    python -m cursed_words_solver.sim.game.expert --iterations 10 --runs 256

The policy (``NetPolicy``) plays the in-game Advice suggestion at every run-level decision
(shop buy / restock / sell / leave, boss draft, pin side, Michael's draft) unless its
learned **advantage model** predicts an alternative is better by more than a margin.

Each iteration:

1. **collect** — the current champion plays runs. At a random subset of decisions the
   suggestion *and* one alternative are each played to the end of the run by the champion,
   with keyed randomness (``play_out(keyed=True)``: both branches draw the same grids and
   shops wherever they reach the same point; test-retest label reliability 0.21 vs ~0 for
   one shared stream). The label is the outcome
   difference (encounters cleared, plus the share of the target reached where the run
   ended; a win scores 16), the input the difference of the two after-state feature
   vectors. Pairs accumulate across iterations (``pairs_it*.npz``).
2. **fit** — ridge regression on every pair so far (input dimension ~1000, labels noisy:
   a linear model generalises; an MLP over-fits).
3. **benchmark** — the new model plays a fixed seed set at several margins; word search is
   deterministic (``Candidates.effort``) and worker hash seeds are pinned, so the
   comparison with the champion is exact on the same seeds. A better model becomes the
   champion, i.e. the policy that generates the next iteration's data.

Data and models live in ``~/.cursed_words_solver/sim_models/expert/`` (``--dir``);
``history.json`` records each iteration and the champion is ``champion.npz``.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

import numpy as np

from cursed_words_solver.sim.game.agent import Action, Candidates, apply, clone, legal_actions, spawn_pool
from cursed_words_solver.sim.game.bossrisk import DEFAULT_PATH as BOSS_RISK_PATH
from cursed_words_solver.sim.game.core import Rng
from cursed_words_solver.sim.game.features import encode, feature_names, outcome
from cursed_words_solver.sim.game.learn import Ridge, load_model
from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig

DEFAULT_DIR = Path.home() / ".cursed_words_solver" / "sim_models" / "expert"
SHOP_CAP = 14
EFFORT = 0.05  # deterministic word search (load-independent, reproducible benchmarks)
THRESHOLDS = (0.5, 1.0, 2.0)
ROLL_EFFORT, ROLL_TARGETS = 0.02, 3  # play-out continuation (see _pairs_job)
MIN_CORR = 0.03
PROMOTE_T = 1.65  # one-sided ~95% on the paired per-seed outcome gain  # skip benchmarking a model whose cross-validated fit shows no signal


def shop_candidates(game, suggestion: Action, max_candidates: int = 4) -> list[Action]:
    """Suggestion first, then buys (upgrades of owned stickers first), a restock, leave."""
    acts = legal_actions(game)
    out = [suggestion]
    owned = {i.game_class for i in game.player.stickers_list(for_comparison=True)}

    def key(a: Action) -> int:
        if a.args[0] == "tile":
            return 2
        stock = game.shop.stickers if a.args[0] == "sticker" else game.shop.stamps
        o = stock[a.args[1]]
        return 0 if (o is not None and o.item.game_class in owned) else 1

    for a in sorted((a for a in acts if a.kind in ("buy", "hippo")), key=key):
        if a not in out:
            out.append(a)
        if len(out) >= max_candidates:
            break
    for a in acts:
        if a.kind == "reroll_shop" and a not in out:
            out.append(a)
            break
    if Action("leave") not in out:
        out.append(Action("leave"))
    return out


def afterstate(game, a: Action) -> np.ndarray | None:
    g = clone(game, light=True)
    try:
        apply(g, a)
    except Exception:
        return None
    return encode(g)


class NetPolicy(FastAdvicePolicy):
    """Fast Advice everywhere; run-level choices overridden by a learned advantage model."""

    def __init__(self, cands: Candidates, model=None, *, seed: int = 0, threshold: float | None = None,
                 boss_risk: str = "") -> None:
        super().__init__(cands, PowerConfig(probe_seeds=1, probe_grids=2, boss_risk=boss_risk or "", fast_placement=True,
                                                 placement_targets=8), seed=seed)
        self.model = model
        self.threshold = threshold if threshold is not None else float(getattr(model, "threshold", 0.5))
        self._steps = 0

    def candidates(self, game) -> list[Action]:
        """Options at a run-level decision, the base (Advice / heuristic) choice first."""
        ph = game.phase
        if ph == "shop":
            return shop_candidates(game, self._advice_shop(game))
        if ph == "boss_draft":
            fb = FastAdvicePolicy._boss(self, game)
            return [fb] + [a for a in legal_actions(game) if a.kind == "boss" and a != fb]
        if ph == "pin_reward":
            fp = FastAdvicePolicy._pin(self, game)
            return [fp] + [a for a in legal_actions(game) if a.kind == "pin" and a != fp]
        if ph == "encounter" and game.encounter.michael_draft is not None:
            return [a for a in legal_actions(game) if a.kind == "michael_pick"]
        return []

    def pick(self, game, cands: list[Action]) -> Action:
        """Keep ``cands[0]`` unless the model predicts an alternative beats it by more than
        ``threshold`` (in outcome units: encounters cleared)."""
        if self.model is None or len(cands) == 1:
            return cands[0]
        base = afterstate(game, cands[0])
        if base is None:
            return cands[0]
        rows, acts = [], []
        for a in cands[1:]:
            x = afterstate(game, a)
            if x is not None:
                rows.append(x - base)
                acts.append(a)
        if not rows:
            return cands[0]
        adv = self.model.predict(np.stack(rows))
        i = int(np.argmax(adv))
        return acts[i] if adv[i] > self.threshold else cands[0]

    def decide(self, game) -> tuple[Action, list[Action]]:
        """(action, candidates) — candidates empty when this is not a run-level decision."""
        ph = game.phase
        if ph != "shop":
            self._steps = 0
        elif self._steps >= SHOP_CAP:
            return self._leave_now(), []
        else:
            self._steps += 1
        if ph == "encounter" and game.encounter.michael_draft is None:
            return FastAdvicePolicy.act(self, game), []
        memo = (set(self._frozen_this_shop), set(self._bought_this_shop), self._sold_this_shop)
        cands = self.candidates(game)
        if not cands:
            return FastAdvicePolicy.act(self, game), []
        a = self.pick(game, cands)
        if ph == "shop" and a != cands[0]:
            self._record_override(game, a, memo)
        if a.kind == "leave":
            self._leave_now()
        return a, cands

    def _record_override(self, game, a: Action, memo) -> None:
        """Advice books its per-shop plan (bought / sold / frozen) when it *suggests*; on an
        override undo that and book the action actually taken instead."""
        self._frozen_this_shop, self._bought_this_shop, self._sold_this_shop = memo
        if a.kind == "buy" and a.args[0] in ("sticker", "stamp"):
            stock = game.shop.stickers if a.args[0] == "sticker" else game.shop.stamps
            if stock[a.args[1]] is not None:
                self._bought_this_shop.add(stock[a.args[1]].item.game_class)
        elif a.kind == "sell":
            self._sold_this_shop = True
        elif a.kind == "freeze":
            self._frozen_this_shop.add(tuple(a.args))

    def _leave_now(self) -> Action:
        self._steps = 0
        return self._leave()

    def act(self, game) -> Action:
        return self.decide(game)[0]


# ---------------------------------------------------------------------------- paired rollouts


def _point(g) -> tuple:
    run = g.player.run
    enc = g.encounter
    grid = (enc.total_grids - enc.remaining_grids, enc.reroll_tracker) if enc is not None else (0, 0)
    return (run.stage, run.node.name, *grid)


def play_out(game, action: Action, policy: NetPolicy, seed: str, max_steps: int = 4000,
             keyed: bool = False) -> float:
    """``outcome`` after ``action`` then ``policy`` to the end of the run (own RNG stream).

    ``keyed``: the stream is reseeded before every action from (seed, stage, node, grid,
    grid rerolls, action kind, how many of that kind here), so two branches that reach the
    same point of the run draw the same grids, shops and restocks (leaving a shop after one
    more purchase still deals the same next grid) — the paired difference then measures the
    decision, not which future happened to be sampled."""
    g = clone(game)
    g.rng = Rng(f"pair|{seed}")
    if g.shop is not None:
        g.shop.rng = g.rng
    if g.encounter is not None:
        g.encounter.rng = g.rng
    policy._leave_now()
    if keyed:
        g.rng.reseed(f"pair|{seed}|decision")
    apply(g, action)
    seen: dict[tuple, int] = {}
    for _ in range(max_steps):
        if g.phase == "done":
            break
        a = policy.act(g)
        if keyed:
            k = (*_point(g), a.kind)
            seen[k] = seen.get(k, 0) + 1
            g.rng.reseed(f"pair|{seed}|{k}|{seen[k]}")
        apply(g, a)
    return outcome(g)


_CANDS: Candidates | None = None
_MODEL = None


def _init(wordlist: str | None, model_path: str | None, effort: float = EFFORT) -> None:
    global _CANDS, _MODEL
    _CANDS = Candidates(Path(wordlist) if wordlist else None, effort=effort)
    _MODEL = load_model(Path(model_path)) if model_path else None


def _game(job: dict[str, Any]):
    from cursed_words_solver.sim.game.run import Game, RunConfig

    return Game(RunConfig(character=job["character"], ascension=job["crown"], challenge=job.get("quest"),
                          seed=job["seed"], wordlist=_CANDS.wordlist))


def _pairs_job(job: dict[str, Any]) -> dict[str, Any]:
    """One run by the champion; at sampled decisions, (alternative − suggestion) pairs."""
    t0 = time.time()
    rng = random.Random(job["seed"])
    g = _game(job)
    pol = NetPolicy(_CANDS, _MODEL, seed=job["seed"], threshold=job.get("threshold"), boss_risk=job.get("boss_risk"))
    # Play-outs use a cheaper continuation (3.6x faster: search effort 0.02, 3 placement
    # squares): labels measure the decision under a slightly weaker but same-style policy.
    roll = NetPolicy(_CANDS.with_effort(ROLL_EFFORT), _MODEL, seed=job["seed"] + 1, threshold=job.get("threshold"),
                     boss_risk=job.get("boss_risk"))
    roll.cfg.placement_targets = ROLL_TARGETS
    dX, dy, kinds = [], [], []
    k = 0
    err = ""
    try:
        for _ in range(4000):
            if g.phase == "done":
                break
            a, cands = pol.decide(g)
            if len(cands) > 1 and rng.random() < job["p_sample"]:
                k += 1
                alt = rng.choice(cands[1:])
                xa, xb = afterstate(g, cands[0]), afterstate(g, alt)
                if xa is not None and xb is not None:
                    seed = f"{job['seed']}|{k}"
                    keyed = bool(job.get("keyed"))
                    ya = play_out(g, cands[0], roll, seed, keyed=keyed)
                    yb = play_out(g, alt, roll, seed, keyed=keyed)
                    dX.append(xb - xa)
                    dy.append(yb - ya)
                    kinds.append(g.phase)
            apply(g, a)
    except Exception as exc:  # pragma: no cover - surfaced in the log
        err = f"{type(exc).__name__}: {exc}"
    width = len(feature_names())
    return {"dX": np.stack(dX).astype(np.float32) if dX else np.zeros((0, width), np.float32),
            "dy": np.array(dy, np.float32), "kind": np.array(kinds, dtype="U12"),
            "won": bool(g.won), "outcome": outcome(g), "err": err, "sec": time.time() - t0}


def _eval_job(job: dict[str, Any]) -> dict[str, Any]:
    g = _game(job)
    pol = NetPolicy(_CANDS, _MODEL, seed=job["seed"], threshold=job.get("threshold"), boss_risk=job.get("boss_risk"))
    for k, v in (job.get("cfg") or {}).items():  # PowerConfig overrides (tuning sweeps)
        setattr(pol.cfg, k, v)
    try:
        for _ in range(4000):
            if g.phase == "done":
                break
            apply(g, pol.act(g))
    except Exception:
        pass
    return {"seed": job["seed"], "won": bool(g.won), "stage": g.player.run.stage, "outcome": outcome(g)}


def collect(jobs, *, workers, wordlist, model, out: Path) -> dict[str, Any]:
    dXs, dys, ks = [], [], []
    wins = 0
    t0 = time.time()
    with spawn_pool(workers, _init, (wordlist, model)) as pool:
        for i, r in enumerate(pool.imap_unordered(_pairs_job, jobs)):
            dXs.append(r["dX"])
            dys.append(r["dy"])
            ks.append(r["kind"])
            wins += r["won"]
            if r["err"]:
                print("  error:", r["err"], flush=True)
            if (i + 1) % 16 == 0 or i + 1 == len(jobs):
                print(f"  run {i + 1}/{len(jobs)}: {sum(len(d) for d in dys)} pairs, {wins} wins "
                      f"({time.time() - t0:.0f}s)", flush=True)
    dX = np.concatenate(dXs)
    np.savez_compressed(out, dX=dX, dy=np.concatenate(dys), kind=np.concatenate(ks))
    return {"runs": len(jobs), "wins": wins, "pairs": len(dX)}


def evaluate(jobs, *, workers, wordlist, model, threshold: float | None = None) -> dict[str, Any]:
    jobs = [{**j, "threshold": threshold if threshold is not None else j.get("threshold")} for j in jobs]
    with spawn_pool(workers, _init, (wordlist, model)) as pool:
        res = pool.map(_eval_job, jobs)
    return {"runs": len(res), "wins": sum(r["won"] for r in res),
            "win_rate": sum(r["won"] for r in res) / max(1, len(res)),
            "mean_outcome": float(np.mean([r["outcome"] for r in res])),
            "per_seed": [round(r["outcome"], 2) for r in res]}


def paired_test(a: list[float], b: list[float]) -> dict[str, float]:
    """Per-seed outcome differences a − b on the same seeds: mean, SE and t."""
    d = np.asarray(a, float) - np.asarray(b, float)
    se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else float("inf")
    mean = float(d.mean()) if len(d) else 0.0
    return {"mean": round(mean, 4), "se": round(se, 4), "t": round(mean / se, 2) if se > 0 else 0.0,
            "better": int((d > 0).sum()), "worse": int((d < 0).sum())}


def load_pairs(out: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    width = len(feature_names())
    dXs, dys, ks = [], [], []
    for f in sorted(out.glob("pairs_it*.npz")):
        d = np.load(f)
        dX = d["dX"]
        if dX.shape[1] < width:
            dX = np.pad(dX, ((0, 0), (0, width - dX.shape[1])))
        dXs.append(dX.astype(np.float32))
        dys.append(d["dy"])
        ks.append(d["kind"])
    if not dXs:
        return np.zeros((0, width), np.float32), np.zeros(0, np.float32), np.zeros(0, "U12")
    return np.concatenate(dXs), np.concatenate(dys), np.concatenate(ks)


def train(dX: np.ndarray, dy: np.ndarray, *, seed: int = 0, lams=(100.0, 1000.0, 1e4, 1e5)) -> tuple[Ridge, dict]:
    """Ridge advantage model; λ by 5-fold CV. Reports holdout correlation and the mean
    realised advantage of the pairs the model would switch to (pred > 0)."""
    rng = np.random.default_rng(seed)
    fold = rng.integers(0, 5, len(dy))
    best = None
    for lam in lams:
        pred = np.zeros(len(dy))
        for f in range(5):
            m = Ridge(dX.shape[1], lam).fit(dX[fold != f], dy[fold != f], center=False)
            pred[fold == f] = m.predict(dX[fold == f])
        corr = float(np.corrcoef(pred, dy)[0, 1]) if len(dy) > 2 and np.std(pred) > 0 else 0.0
        sw = pred > 0
        stats = {"lam": lam, "cv_corr": corr, "switch_rate": float(sw.mean()),
                 "switch_gain": float(dy[sw].mean()) if sw.any() else 0.0}
        if best is None or corr > best[1]["cv_corr"]:
            best = (lam, stats)
    m = Ridge(dX.shape[1], best[0]).fit(dX, dy, center=False)
    return m, {**best[1], "pairs": int(len(dy)), "label_mean": float(dy.mean()), "label_sd": float(dy.std())}


def make_jobs(n: int, seed: int, characters: list[str], crowns: list[int], **extra) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    return [{"character": rng.choice(characters), "crown": rng.choice(crowns), "seed": seed * 100_000 + i, **extra}
            for i in range(n)]


def main(argv: list[str] | None = None) -> int:
    import multiprocessing as mp

    ap = argparse.ArgumentParser(description="policy iteration from paired full-run rollouts")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--runs", type=int, default=256, help="data runs per iteration")
    ap.add_argument("--p-sample", type=float, default=0.3, help="share of decisions turned into pairs")
    ap.add_argument("--plain-rng", action="store_true",
                    help="unkeyed play-outs (labels measured ~0 test-retest reliability vs 0.21 keyed)")
    ap.add_argument("--eval-runs", type=int, default=256)
    ap.add_argument("--characters", default="WetDennis")
    ap.add_argument("--crowns", default="0")
    ap.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2)))
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--wordlist", default=None)
    ap.add_argument("--boss-risk", default=str(BOSS_RISK_PATH),
                    help="bossrisk.py table for the boss draft ('' = Fast Advice's fixed rule)")
    args = ap.parse_args(argv)
    risk = args.boss_risk if args.boss_risk and Path(args.boss_risk).is_file() else ""

    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    chars = [c for c in args.characters.split(",") if c]
    crowns = [int(c) for c in args.crowns.split(",") if c]
    hist_path = out / "history.json"
    history = json.loads(hist_path.read_text()) if hist_path.is_file() else []
    eval_jobs = make_jobs(args.eval_runs, 777, chars, crowns, boss_risk=risk)
    kw = {"workers": args.workers, "wordlist": args.wordlist}
    champ_path = out / "champion.npz"
    champ = str(champ_path) if champ_path.is_file() else None
    if not history:
        base = evaluate(eval_jobs, model=None, **kw)
        base.pop("per_seed")
        print("baseline (Fast Advice):", base, flush=True)
        history.append({"iteration": "baseline", "eval": base})
        hist_path.write_text(json.dumps(history, indent=1))
    confirm_jobs = make_jobs(args.eval_runs, 778, chars, crowns, boss_risk=risk)
    champ_confirm = next((h["confirm"] for h in reversed(history) if h.get("champion")), None)
    if champ and not any(h.get("champion") and "paired" in h for h in history):
        # Champion promoted by the old win-count rule: re-check it with the paired test.
        base = evaluate(confirm_jobs, model=None, **kw)
        cur = evaluate(confirm_jobs, model=champ, **kw)
        test = paired_test(cur["per_seed"], base["per_seed"])
        print(f"re-check champion vs Fast Advice on confirm seeds: {test}", flush=True)
        if test["t"] < PROMOTE_T:
            print("  demoted: Fast Advice stays the champion", flush=True)
            champ_path.rename(out / "champion_demoted.npz")
            champ, champ_confirm = None, base
        else:
            champ_confirm = cur
        history.append({"iteration": "recheck", "champion": champ is not None, "paired": test,
                        "confirm": cur if champ else base})
        hist_path.write_text(json.dumps(history, indent=1))
    start = len(list(out.glob("pairs_it*.npz")))
    for it in range(start, start + args.iterations):
        print(f"iteration {it}: {args.runs} runs by {'champion' if champ else 'Fast Advice'}", flush=True)
        stats = collect(make_jobs(args.runs, 2000 + it, chars, crowns, p_sample=args.p_sample, boss_risk=risk,
                                  keyed=not args.plain_rng),
                        model=champ, out=out / f"pairs_it{it:03d}.npz", **kw)
        dX, dy, _ = load_pairs(out)
        m, fit = train(dX, dy, seed=it)
        print("  fit:", fit, flush=True)
        print("  top features:", [(n, round(w, 3)) for n, w in m.top_features(12)], flush=True)
        path = out / f"model_it{it:03d}.npz"
        if fit["cv_corr"] < MIN_CORR:
            m.threshold = 1.0
            m.save(path)
            row = {"iteration": it, "model": str(path), "champion": False, "data": stats, "fit": fit,
                   "skipped": f"cv_corr < {MIN_CORR}: collecting more pairs before benchmarking"}
            print(json.dumps(row), flush=True)
            history.append(row)
            hist_path.write_text(json.dumps(history, indent=1))
            continue
        best_ev, best_th = None, None
        for th in THRESHOLDS:
            m.threshold = th
            m.save(path)
            ev = evaluate(eval_jobs, model=str(path), threshold=th, **kw)
            ev.pop("per_seed")
            print(f"  margin {th}: {ev}", flush=True)
            if best_ev is None or (ev["wins"], ev["mean_outcome"]) > (best_ev["wins"], best_ev["mean_outcome"]):
                best_ev, best_th = ev, th
        m.threshold = best_th
        m.save(path)
        # Margin chosen on the benchmark seeds; promotion is decided on fresh seeds by a
        # paired test (same seeds, deterministic runs): mean per-seed outcome gain > 1.65 SE.
        conf = evaluate(confirm_jobs, model=str(path), **kw)
        if champ_confirm is None or "per_seed" not in champ_confirm:
            champ_confirm = evaluate(confirm_jobs, model=champ, **kw)
        test = paired_test(conf["per_seed"], champ_confirm["per_seed"])
        print(f"  confirm: {conf['wins']} wins / mean {conf['mean_outcome']:.3f} vs champion "
              f"{champ_confirm['wins']} / {champ_confirm['mean_outcome']:.3f}; paired {test}", flush=True)
        promoted = test["t"] >= PROMOTE_T
        if promoted:
            m.save(champ_path)
            champ, champ_confirm = str(champ_path), conf
        row = {"iteration": it, "model": str(path), "threshold": best_th, "champion": promoted,
               "data": stats, "fit": fit, "eval": best_ev, "confirm": conf, "paired": test}
        print(json.dumps(row), flush=True)
        history.append(row)
        hist_path.write_text(json.dumps(history, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
