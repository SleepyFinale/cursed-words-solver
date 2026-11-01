"""Build-aware boss risk: P(clearing a boss fight) from how this build does against it.

    python -m cursed_words_solver.sim.game.bossmodel <bossdiag.jsonl> ...   # fit and save

The risk table (``bossrisk.py``) knows how often each boss ends runs on average, not how the
build in hand does against it. ``PowerPolicy.boss_strength`` probes the build under each
draft option's rules (points per grid × that fight's grids / its target). Training rows come
from boss drafts of base runs where *both* options were fought once from the same state
(``cleared``), so every option gets a label. A logistic regression on

    log strength, logit table risk, cursed, stage, crown

gives the clear chance; ``PowerConfig.boss_model`` makes ``_risk_boss`` use 1 − that
instead of the table's risk.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_PATH = Path.home() / ".cursed_words_solver" / "sim_models" / "boss_model.json"
NAMES = ["log_strength", "logit_risk", "cursed", "stage", "crown"]


def features(strength: float, risk: float, cursed: bool, stage: int, crown: int) -> list[float]:
    r = min(max(risk, 1e-3), 1 - 1e-3)
    return [math.log(max(strength, 1e-3)), math.log(r / (1 - r)), float(cursed), float(stage), float(crown)]


def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 50) -> np.ndarray:
    """Newton steps on the L2-penalised log-likelihood; the last column of ``X`` is 1."""
    w = np.zeros(X.shape[1])
    reg = np.full(X.shape[1], l2)
    reg[-1] = 1e-6  # keeps H invertible when a fold is all one label
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (p - y) + reg * w
        H = (X * (p * (1 - p))[:, None]).T @ X + np.diag(reg)
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def rows(paths: list[Path]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(features, cleared, run index) for every option of every logged draft."""
    X, y, run = [], [], []
    k = 0
    for path in paths:
        for line in Path(path).read_text().splitlines():
            r = json.loads(line)
            for d in r["drafts"]:
                for o in d["opts"]:
                    X.append(features(o["strength"], o["risk"], o["cursed"], d["stage"], r["crown"]))
                    y.append(float(o["cleared"]))
                    run.append(k)
            k += 1
    return np.array(X), np.array(y), np.array(run)


class BossModel:
    def __init__(self, w: list[float], mean: list[float], scale: list[float]) -> None:
        self.w, self.mean, self.scale = np.array(w), np.array(mean), np.array(scale)

    @classmethod
    def fit(cls, X: np.ndarray, y: np.ndarray, l2: float = 1.0) -> "BossModel":
        mean, scale = X.mean(0), X.std(0) + 1e-9
        Z = np.hstack([(X - mean) / scale, np.ones((len(X), 1))])
        return cls(list(fit_logistic(Z, y, l2)), list(mean), list(scale))

    def p_clear(self, x: list[float] | np.ndarray) -> np.ndarray:
        Z = (np.atleast_2d(x) - self.mean) / self.scale
        return 1 / (1 + np.exp(-(Z @ self.w[:-1] + self.w[-1])))

    def risk(self, strength: float, risk: float, cursed: bool, stage: int, crown: int) -> float:
        return float(1 - self.p_clear(features(strength, risk, cursed, stage, crown))[0])

    def save(self, path: Path = DEFAULT_PATH, **info: Any) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"names": NAMES, "w": list(self.w), "mean": list(self.mean),
                                    "scale": list(self.scale), **info}, indent=1))

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "BossModel":
        d = json.loads(Path(path).read_text())
        return cls(d["w"], d["mean"], d["scale"])


def cross_validate(X: np.ndarray, y: np.ndarray, run: np.ndarray, cols: list[int], folds: int = 5) -> dict[str, float]:
    """Log loss and AUC of held-out predictions, folds split by run."""
    pred = np.zeros(len(y))
    fold = run % folds
    for f in range(folds):
        tr, te = fold != f, fold == f
        m = BossModel.fit(X[tr][:, cols], y[tr])
        pred[te] = m.p_clear(X[te][:, cols])
    p = np.clip(pred, 1e-6, 1 - 1e-6)
    loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    pos, neg = pred[y == 1], pred[y == 0]
    auc = float(np.mean([(pos > q).mean() + 0.5 * (pos == q).mean() for q in neg])) if len(pos) and len(neg) else float("nan")
    return {"log_loss": round(loss, 4), "auc": round(auc, 4)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="fit the build-aware boss model from boss-draft logs")
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=DEFAULT_PATH)
    args = ap.parse_args(argv)
    X, y, run = rows(args.logs)
    print(f"{len(y)} options, {int(len(y) - y.sum())} fights lost, {run.max() + 1} runs")
    for name, cols in (("table risk", [1]), ("table + cursed/stage/crown", [1, 2, 3, 4]),
                       ("probe", [0]), ("probe + table", [0, 1]), ("all", [0, 1, 2, 3, 4])):
        print(f"  {name:28s} {cross_validate(X, y, run, cols)}")
    m = BossModel.fit(X, y)
    m.save(args.out, rows=int(len(y)))
    print("saved", args.out, dict(zip(NAMES + ["bias"], np.round(m.w, 3))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
