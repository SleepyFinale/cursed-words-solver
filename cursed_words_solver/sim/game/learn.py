"""Self-play value learning for run decisions (shop / boss / pin / Michael draft).

Loop (``python -m cursed_words_solver.sim.game.learn``):

1. **collect** — play runs in parallel with an exploring policy; at every run-level
   decision record ``features.encode(state)``; label each with the run's final
   ``features.progress`` (encounters cleared, +4 for beating Michael).
2. **fit** — a small numpy MLP regresses progress from features (no torch needed).
3. **play** — ``ValuePolicy`` picks the action whose resulting state the model values
   most (ε-greedy while collecting); words / rerolls / consumables use the fast
   heuristics in ``policy.PowerPolicy._encounter``.

Each generation trains on everything collected so far, so the policy improves on its own
data (fitted value iteration with Monte-Carlo returns).
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from cursed_words_solver.sim.game.agent import Action, Candidates, apply, clone, legal_actions
from cursed_words_solver.sim.game.core import Rng
from cursed_words_solver.sim.game.features import encode, feature_names, progress
from cursed_words_solver.sim.game.policy import Policy, PowerConfig, PowerPolicy

DEFAULT_DIR = Path.home() / ".cursed_words_solver" / "sim_models"


# ---------------------------------------------------------------------------- model


class MLP:
    """Tiny fully-connected regressor (ReLU, Adam, standardised inputs/targets)."""

    def __init__(self, n_in: int, hidden: tuple[int, ...] = (256, 128), seed: int = 0) -> None:
        rng = np.random.default_rng(seed)
        sizes = (n_in, *hidden, 1)
        self.W = [rng.normal(0, math.sqrt(2.0 / a), (a, b)).astype(np.float32) for a, b in zip(sizes, sizes[1:])]
        self.b = [np.zeros(b, dtype=np.float32) for b in sizes[1:]]
        self.mu = np.zeros(n_in, dtype=np.float32)
        self.sd = np.ones(n_in, dtype=np.float32)
        self.y_mu = 0.0
        self.y_sd = 1.0

    def _forward(self, X: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
        acts = [X]
        h = X
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            h = h @ W + b
            if i < len(self.W) - 1:
                h = np.maximum(h, 0)
            acts.append(h)
        return h[:, 0], acts

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = (np.atleast_2d(X).astype(np.float32) - self.mu) / self.sd
        y, _ = self._forward(X)
        return y * self.y_sd + self.y_mu

    def fit(self, X: np.ndarray, y: np.ndarray, *, epochs: int = 40, lr: float = 1e-3, batch: int = 256,
            l2: float = 1e-5, seed: int = 0, verbose: bool = True) -> float:
        """Set input / target normalisation from (X, y), then train."""
        X = X.astype(np.float32)
        y = y.astype(np.float32)
        self.mu = X.mean(0)
        self.sd = X.std(0) + 1e-3
        self.y_mu = float(y.mean())
        self.y_sd = float(y.std() + 1e-6)
        return self._train(X, y, epochs=epochs, lr=lr, batch=batch, l2=l2, seed=seed, verbose=verbose)

    def fit_continue(self, X: np.ndarray, y: np.ndarray, *, epochs: int = 5, seed: int = 0, lr: float = 1e-3) -> float:
        """More epochs with the existing normalisation (fresh Adam moments)."""
        return self._train(X.astype(np.float32), y.astype(np.float32), epochs=epochs, lr=lr, seed=seed, verbose=False)

    def _train(self, X: np.ndarray, y: np.ndarray, *, epochs: int, lr: float = 1e-3, batch: int = 256,
               l2: float = 1e-5, seed: int = 0, verbose: bool = False) -> float:
        Xn = (X - self.mu) / self.sd
        yn = (y - self.y_mu) / self.y_sd
        rng = np.random.default_rng(seed)
        mW = [np.zeros_like(w) for w in self.W]
        vW = [np.zeros_like(w) for w in self.W]
        mb = [np.zeros_like(b) for b in self.b]
        vb = [np.zeros_like(b) for b in self.b]
        t = 0
        n = len(Xn)
        loss = float("nan")
        for ep in range(epochs):
            order = rng.permutation(n)
            tot = 0.0
            for s in range(0, n, batch):
                idx = order[s:s + batch]
                xb, yb = Xn[idx], yn[idx]
                pred, acts = self._forward(xb)
                err = pred - yb
                tot += float((err ** 2).sum())
                g = (2.0 / len(idx)) * err[:, None]
                t += 1
                for i in range(len(self.W) - 1, -1, -1):
                    gW = acts[i].T @ g + l2 * self.W[i]
                    gb = g.sum(0)
                    if i > 0:
                        g = (g @ self.W[i].T) * (acts[i] > 0)
                    for P, G, M, V in ((self.W, gW, mW, vW), (self.b, gb, mb, vb)):
                        M[i] = 0.9 * M[i] + 0.1 * G
                        V[i] = 0.999 * V[i] + 0.001 * G * G
                        mh = M[i] / (1 - 0.9 ** t)
                        vh = V[i] / (1 - 0.999 ** t)
                        P[i] -= lr * mh / (np.sqrt(vh) + 1e-8)
            loss = tot / max(1, n)
            if verbose and (ep % 10 == 0 or ep == epochs - 1):
                print(f"  epoch {ep:3d} mse {loss * self.y_sd ** 2:.3f}", flush=True)
        return loss * self.y_sd ** 2

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        arrs = {f"W{i}": w for i, w in enumerate(self.W)} | {f"b{i}": b for i, b in enumerate(self.b)}
        np.savez(path, mu=self.mu, sd=self.sd, y=np.array([self.y_mu, self.y_sd]), n=np.array([len(self.W)]),
                 names=np.array(feature_names()), **arrs)

    @classmethod
    def load(cls, path: Path) -> "MLP":
        d = np.load(path, allow_pickle=False)
        n = int(d["n"][0])
        m = cls.__new__(cls)
        m.W = [d[f"W{i}"] for i in range(n)]
        m.b = [d[f"b{i}"] for i in range(n)]
        m.mu, m.sd = d["mu"], d["sd"]
        m.y_mu, m.y_sd = float(d["y"][0]), float(d["y"][1])
        return m


# ---------------------------------------------------------------------------- policies


_DECISION_KINDS = ("buy", "sell", "hippo", "freeze", "reroll_shop", "leave", "boss", "pin", "michael_pick")


class ValuePolicy(Policy):
    """Run-level choices by learned value of the resulting state; encounter play heuristic."""

    def __init__(self, cands: Candidates, model: MLP | None, *, epsilon: float = 0.0, seed: int = 0,
                 max_shop_actions: int = 14, random_shop: bool = False, explore: str = "random") -> None:
        self.cands = cands
        self.model = model
        self.epsilon = epsilon
        self.rng = random.Random(seed)
        self.heur = PowerPolicy(cands, PowerConfig(probe_seeds=1, probe_grids=2), seed=seed)
        self.max_shop_actions = max_shop_actions
        self.random_shop = random_shop or model is None
        # Exploration moves: "random" (biased random) or "advice" (the in-game Advice button).
        self.explore = explore
        self._advice = None
        if explore == "advice":
            from cursed_words_solver.sim.game.policy import AdvicePolicy

            self._advice = AdvicePolicy(cands, seed=seed)
        self._shop_n = 0
        self.records: list[np.ndarray] = []

    def value(self, game) -> float:
        if self.model is None:
            return 0.0
        return float(self.model.predict(encode(game))[0])

    def _choose(self, game, acts: list[Action]) -> Action:
        self.records.append(encode(game))
        if self.random_shop or self.rng.random() < self.epsilon:
            return self._random(game, acts)
        best, best_a = -math.inf, acts[0]
        for a in acts:
            v = self.action_value(game, a)
            if v > best:
                best, best_a = v, a
        return best_a

    def _after_value(self, g) -> float:
        return self.value(g) if g.phase != "done" else progress(g)

    def action_value(self, game, a: Action, *, samples: int = 3) -> float:
        """Value of the state ``a`` leads to; a shop reroll is valued by its best follow-up
        (the model does not see shop stock), averaged over sampled restocks."""
        if a.kind == "reroll_shop":
            tot = 0.0
            for s in range(samples):
                g = clone(game, light=True)
                g.rng = Rng(f"rr|{s}|{self.rng.random()}")
                g.shop.rng = g.rng
                if not apply(g, a):
                    return -math.inf
                follow = [b for b in legal_actions(g) if b.kind in ("buy", "leave")]
                best = -math.inf
                for b in follow:
                    g2 = clone(g, light=True)
                    try:
                        apply(g2, b)
                    except Exception:
                        continue
                    best = max(best, self._after_value(g2))
                tot += best
            return tot / samples
        g = clone(game, light=True)
        try:
            apply(g, a)
        except Exception:
            return -math.inf
        return self._after_value(g)

    def _random(self, game, acts: list[Action]) -> Action:
        if self._advice is not None and self.rng.random() < 0.85:
            if game.phase == "shop":
                return self._advice._advice_shop(game)
            if game.phase in ("boss_draft", "pin_reward"):
                return self._advice.act(game)
        buys = [a for a in acts if a.kind in ("buy", "hippo")]
        if game.phase == "shop":
            r = self.rng.random()
            owned = {i.game_class for i in game.player.stickers_list(for_comparison=True)}
            upgrades = [a for a in buys if a.args[0] == "sticker" and game.shop.stickers[a.args[1]] is not None
                        and game.shop.stickers[a.args[1]].item.game_class in owned]
            if upgrades and r < 0.7:
                return self.rng.choice(upgrades)
            if buys and r < 0.55:
                return self.rng.choice(buys)
            if r < 0.62 and any(a.kind == "reroll_shop" for a in acts):
                return next(a for a in acts if a.kind == "reroll_shop")
            if r < 0.66:
                sells = [a for a in acts if a.kind in ("sell", "freeze")]
                if sells:
                    return self.rng.choice(sells)
            return next(a for a in acts if a.kind == "leave")
        return self.rng.choice(acts)

    def act(self, game) -> Action:
        ph = game.phase
        if ph != "shop":
            self._shop_n = 0
        if ph == "encounter":
            enc = game.encounter
            if enc.michael_draft is not None:
                return self._choose(game, legal_actions(game))
            return self.heur._encounter(game)
        if ph == "shop":
            self._shop_n += 1
            if self._shop_n > self.max_shop_actions:
                self._shop_n = 0
                return Action("leave")
            acts = [a for a in legal_actions(game) if a.kind in _DECISION_KINDS]
            return self._choose(game, acts)
        acts = legal_actions(game)
        return self._choose(game, acts)


# ---------------------------------------------------------------------------- collection


_CANDS: Candidates | None = None
_MODEL: MLP | None = None


def _init(wordlist: str | None, model_path: str | None) -> None:
    global _CANDS, _MODEL
    _CANDS = Candidates(Path(wordlist) if wordlist else None, time_budget=0.6)
    _MODEL = MLP.load(Path(model_path)) if model_path else None


def _job(job: dict[str, Any]) -> dict[str, Any]:
    from cursed_words_solver.sim.game.policy import play
    from cursed_words_solver.sim.game.run import Game, RunConfig

    t0 = time.time()
    g = Game(RunConfig(character=job["character"], ascension=job["crown"], challenge=job.get("quest"),
                       seed=job["seed"], wordlist=_CANDS.wordlist))
    pol = ValuePolicy(_CANDS, _MODEL, epsilon=job["epsilon"], seed=job["seed"], explore=job.get("explore", "random"))
    err = ""
    try:
        play(g, pol, max_steps=4000)
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    y = progress(g)
    X = np.stack(pol.records) if pol.records else np.zeros((0, len(feature_names())), np.float32)
    return {"X": X, "y": np.full(len(X), y, np.float32), "won": bool(g.won), "progress": y,
            "err": err, "sec": time.time() - t0, "job": job}


def collect(jobs: list[dict[str, Any]], *, workers: int, wordlist: str | None, model: str | None,
            out_npz: Path) -> dict[str, float]:
    Xs, ys, gs = [], [], []
    wins = 0
    prog = []
    errs = 0
    t0 = time.time()
    with mp.get_context("spawn").Pool(workers, initializer=_init, initargs=(wordlist, model)) as pool:
        for i, r in enumerate(pool.imap_unordered(_job, jobs)):
            Xs.append(r["X"])
            ys.append(r["y"])
            gs.append(np.full(len(r["X"]), r["job"]["seed"], np.int64))
            wins += r["won"]
            prog.append(r["progress"])
            errs += bool(r["err"])
            if r["err"]:
                print("  error:", r["job"], r["err"], flush=True)
            if (i + 1) % max(1, len(jobs) // 10) == 0:
                print(f"  {i + 1}/{len(jobs)} runs, win {wins / (i + 1):.1%}, mean progress {np.mean(prog):.2f}, "
                      f"{time.time() - t0:.0f}s", flush=True)
    X = np.concatenate(Xs) if Xs else np.zeros((0, len(feature_names())), np.float32)
    y = np.concatenate(ys) if ys else np.zeros(0, np.float32)
    groups = np.concatenate(gs) if gs else np.zeros(0, np.int64)
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_npz, X=X, y=y, run=groups)
    return {"runs": len(jobs), "win_rate": wins / max(1, len(jobs)), "progress": float(np.mean(prog)) if prog else 0.0,
            "samples": int(len(X)), "errors": errs}


def load_dataset(out: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every ``gen*.npz`` under ``out``; older feature versions are zero-padded (new
    columns are appended) and files without run ids get one id per run block."""
    width = len(feature_names())
    Xs, ys, gs = [], [], []
    for k, f in enumerate(sorted(out.glob("gen*.npz"))):
        d = np.load(f)
        X0, y0 = d["X"], d["y"]
        if X0.shape[1] < width:
            X0 = np.pad(X0, ((0, 0), (0, width - X0.shape[1])))
        if "run" in d.files:
            g0 = d["run"].astype(np.int64)
        else:  # samples of one run are consecutive and share the label
            g0 = np.cumsum(np.r_[0, (np.diff(y0) != 0).astype(np.int64)]) + (k + 1) * 10**9
        Xs.append(X0.astype(np.float32))
        ys.append(y0.astype(np.float32))
        gs.append(g0)
    return np.concatenate(Xs), np.concatenate(ys), np.concatenate(gs)


def fit_with_holdout(m: MLP, X: np.ndarray, y: np.ndarray, groups: np.ndarray, *, seed: int = 0,
                     epochs: int = 60, holdout: float = 0.1) -> float:
    """Train with a run-grouped holdout; keep the epoch with the best holdout MSE."""
    rng = np.random.default_rng(seed)
    runs = np.unique(groups)
    val_runs = set(rng.choice(runs, size=max(1, int(len(runs) * holdout)), replace=False).tolist())
    is_val = np.array([g in val_runs for g in groups])
    Xt, yt, Xv, yv = X[~is_val], y[~is_val], X[is_val], y[is_val]
    base = float(np.mean((yv - yt.mean()) ** 2))
    best, best_state = math.inf, None
    for ep in range(0, epochs, 5):
        m.fit_continue(Xt, yt, epochs=5, seed=seed + ep) if ep else m.fit(Xt, yt, epochs=5, seed=seed, verbose=False)
        v = float(np.mean((m.predict(Xv) - yv) ** 2))
        print(f"  epoch {ep + 5:3d} holdout mse {v:.3f} (predict-mean {base:.3f})", flush=True)
        if v < best:
            best = v
            best_state = ([w.copy() for w in m.W], [b.copy() for b in m.b])
    if best_state is not None:
        m.W, m.b = best_state
    return best


def make_jobs(n: int, *, seed: int, epsilon: float, characters: list[str] | None, crowns: list[int],
              quests: bool, explore: str = "random") -> list[dict[str, Any]]:
    from cursed_words_solver.sim.game.challenges import QUESTS
    from cursed_words_solver.sim.game.player import character_rows

    chars = characters or sorted(character_rows())
    qs = sorted(q for q in QUESTS if q != "SpeedrunChallenge")
    rng = random.Random(seed)
    jobs = []
    for i in range(n):
        quest = rng.choice(qs) if quests and rng.random() < 0.15 else None
        jobs.append({"character": rng.choice(chars), "crown": rng.choice(crowns), "quest": quest,
                     "seed": seed * 100_000 + i, "epsilon": epsilon, "explore": explore})
    return jobs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="self-play value learning")
    ap.add_argument("--generations", type=int, default=3)
    ap.add_argument("--runs", type=int, default=400, help="runs per generation")
    ap.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    ap.add_argument("--characters", default="", help="comma list (default: all)")
    ap.add_argument("--crowns", default="0,1,2,3,4,5,6,7")
    ap.add_argument("--quests", action="store_true")
    ap.add_argument("--epsilon", type=float, default=0.2)
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--wordlist", default=None)
    ap.add_argument("--start-model", default=None)
    ap.add_argument("--explore", default="advice", choices=("advice", "random"),
                    help="exploration moves: the in-game Advice button or biased random")
    args = ap.parse_args(argv)

    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    chars = [c for c in args.characters.split(",") if c] or None
    crowns = [int(c) for c in args.crowns.split(",") if c]
    model_path = args.start_model
    history = []
    for gen in range(args.generations):
        eps = 1.0 if (gen == 0 and model_path is None) else args.epsilon
        print(f"generation {gen}: collecting {args.runs} runs (epsilon {eps})", flush=True)
        jobs = make_jobs(args.runs, seed=gen + 1, epsilon=eps, characters=chars, crowns=crowns, quests=args.quests,
                         explore=args.explore)
        stats = collect(jobs, workers=args.workers, wordlist=args.wordlist, model=model_path,
                        out_npz=out / f"gen{gen}.npz")
        print(f"  collected: {stats}", flush=True)
        X, y, groups = load_dataset(out)
        print(f"  fitting on {len(X)} samples from {len(np.unique(groups))} runs", flush=True)
        m = MLP(X.shape[1], seed=gen)
        mse = fit_with_holdout(m, X, y, groups, seed=gen)
        model_path = str(out / f"value_gen{gen}.npz")
        m.save(Path(model_path))
        m.save(out / "value_latest.npz")
        history.append({"gen": gen, **stats, "mse": mse})
        (out / "history.json").write_text(json.dumps(history, indent=1), encoding="utf-8")
    print(json.dumps(history, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
