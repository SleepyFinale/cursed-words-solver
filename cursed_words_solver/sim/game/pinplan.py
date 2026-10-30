"""Learned pin side: which side to upgrade in the current situation.

    python -m cursed_words_solver.sim.game.pinplan            # train from the run log

``NetPolicy`` with ``pin_side="rollout"`` decides each pin reward by playing both sides to
the end of the run on the same keyed futures and logs the state with both outcomes
(``pin_log`` in ``expert.evaluate``'s run log). That is slow (2 × ``pin_samples`` full
play-outs per decision). This module fits a ridge model on those decisions:

    outcome(right) − outcome(left)  ≈  w · state + v · offer + b[character]

where ``state`` is the feature vector before the upgrade (build, money, stage, crown, pin
levels) and ``offer`` is afterstate(right) − afterstate(left): the pin levels each side
raises and, for the random pins, what each side adds (Random Access Memory's offered
sticker / stamp as item:* counts, Octacles' Bucket tile as bucket:* glyph counts). The
per-character intercept is the side that character usually wants; ``w`` and ``v`` are how
the situation and the offers move it. ``pin_side="learned"`` uses the model in play; with no model
or no data for the character it falls back to the lower side.
"""

from __future__ import annotations

import argparse
import json
import pickle
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_PATH = Path.home() / ".cursed_words_solver" / "sim_models" / "pin_model.pkl"
LAMS = (10.0, 100.0, 1000.0, 1e4)


def load_decisions(run_log: Path, horizon: int = 1) -> list[dict[str, Any]]:
    """Every logged rollout pin decision, with its run's character and crown. A rerun of
    the same (character, crown, seed) replaces the earlier run (the log is append-only)."""
    out: list[dict[str, Any]] = []
    try:
        lines = Path(run_log).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    runs: dict[tuple, dict[str, Any]] = {}
    for line in lines:
        if '"pin_log": [{' not in line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        runs[(r["character"], r["crown"], r["seed"])] = r
    for r in runs.values():
        for d in r.get("pin_log") or ():
            res = d.get("outcomes") or {}
            if d.get("x") is None or d.get("dx") is None or "left" not in res or "right" not in res:
                continue
            if d.get("horizon", 0) != horizon:  # full-run labels (horizon 0) were pure noise
                continue
            out.append({**d, "character": r["character"], "crown": r["crown"], "seed": r["seed"],
                        "y": float(np.mean(res["right"]) - np.mean(res["left"]))})
    return out


def _dense(sparse: dict[str, float], width: int) -> np.ndarray:
    x = np.zeros(width, np.float32)
    for i, v in sparse.items():
        if int(i) < width:
            x[int(i)] = v
    return x


class PinModel:
    def __init__(self, w: np.ndarray, bias: dict[str, float], mu: np.ndarray, sd: np.ndarray, info: dict) -> None:
        self.w, self.bias, self.mu, self.sd, self.info = w, bias, mu, sd, info

    def predict(self, character: str, x: np.ndarray, dx: np.ndarray) -> float | None:
        """Predicted outcome(right) − outcome(left); None for a character with no data."""
        if character not in self.bias:
            return None
        z = np.r_[x, dx][: len(self.mu)]
        z = np.pad(z, (0, len(self.mu) - len(z)))
        return float(((z - self.mu) / self.sd) @ self.w + self.bias[character])


def _fit(X: np.ndarray, y: np.ndarray, chars: list[str], lam: float) -> tuple[np.ndarray, dict[str, float]]:
    """Ridge on the state with an unpenalised intercept per character."""
    names = sorted(set(chars))
    C = np.zeros((len(y), len(names)))
    for i, c in enumerate(chars):
        C[i, names.index(c)] = 1.0
    A = np.hstack([X, C])
    reg = np.r_[np.full(X.shape[1], lam), np.full(len(names), 1e-6)]
    coef = np.linalg.solve(A.T @ A + np.diag(reg), A.T @ y)
    return coef[: X.shape[1]], {c: float(coef[X.shape[1] + j]) for j, c in enumerate(names)}


def train(decisions: list[dict[str, Any]], width: int, *, seed: int = 0) -> PinModel:
    """λ by 5-fold CV grouped by run, so one run's decisions never sit on both sides."""
    X = np.stack([np.r_[_dense(d["x"], width), _dense(d["dx"], width)] for d in decisions]).astype(np.float64)
    y = np.array([d["y"] for d in decisions])
    chars = [d["character"] for d in decisions]
    mu, sd = X.mean(0), X.std(0)
    sd[sd < 1e-6] = 1.0
    Xs = (X - mu) / sd
    runs = sorted({(d["character"], d["crown"], d["seed"]) for d in decisions})
    fold_of = {r: int(np.random.default_rng(seed + i).integers(0, 5)) for i, r in enumerate(runs)}
    fold = np.array([fold_of[(d["character"], d["crown"], d["seed"])] for d in decisions])
    scores = {}
    for lam in LAMS:
        pred = np.zeros(len(y))
        for f in range(5):
            tr, te = fold != f, fold == f
            if not te.any() or not tr.any():
                continue
            w, b = _fit(Xs[tr], y[tr], [c for c, t in zip(chars, tr) if t], lam)
            pred[te] = Xs[te] @ w + np.array([b.get(c, 0.0) for c, t in zip(chars, te) if t])
        # agreement: how often the predicted side is the rollout's better side (ties excluded)
        decided = np.abs(y) > 1e-9
        agree = float(np.mean(np.sign(pred[decided]) == np.sign(y[decided]))) if decided.any() else 0.0
        corr = float(np.corrcoef(pred, y)[0, 1]) if np.std(pred) > 0 and np.std(y) > 0 else 0.0
        scores[lam] = {"corr": round(corr, 3), "agree": round(agree, 3)}
    lam = max(LAMS, key=lambda l: scores[l]["agree"])
    w, b = _fit(Xs, y, chars, lam)
    # the intercept-only model (one side per character) is the bar the state has to beat
    base = np.array([np.mean([yy for yy, cc in zip(y, chars) if cc == c]) for c in chars])
    decided = np.abs(y) > 1e-9
    info = {"n": len(y), "lam": lam, "cv": scores,
            "intercept_only_agree": round(float(np.mean(np.sign(base[decided]) == np.sign(y[decided]))), 3)
            if decided.any() else 0.0}
    return PinModel(w, b, mu, sd, info)


def save(model: PinModel, path: Path = DEFAULT_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(model))
    _load.cache_clear()


@lru_cache(maxsize=4)
def _load(path: str) -> PinModel | None:
    try:
        return pickle.loads(Path(path).read_bytes())
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError):
        return None


def choose(character: str, x: np.ndarray, dx: np.ndarray, path: Path = DEFAULT_PATH) -> str | None:
    """"left" / "right" from the model, or None (no model / no data for this character).
    ``x``: state features; ``dx``: afterstate(right) − afterstate(left)."""
    m = _load(str(path))
    if m is None:
        return None
    d = m.predict(character, x, dx)
    return None if d is None or d == 0 else ("right" if d > 0 else "left")


def main(argv: list[str] | None = None) -> int:
    from cursed_words_solver.sim.game.expert import RUN_LOG
    from cursed_words_solver.sim.game.features import feature_names

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", type=Path, default=RUN_LOG)
    ap.add_argument("--out", type=Path, default=DEFAULT_PATH)
    args = ap.parse_args(argv)
    decisions = load_decisions(args.log)
    if len(decisions) < 20:
        print(f"only {len(decisions)} logged pin decisions; run benchmarks with pin_side='rollout' first")
        return 1
    model = train(decisions, len(feature_names()))
    save(model, args.out)
    print(json.dumps(model.info, indent=1))
    for c, b in sorted(model.bias.items()):
        n = sum(d["character"] == c for d in decisions)
        print(f"{c:14s} intercept {b:+.2f} (right − left), {n} decisions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
