"""Learned item value: how a run's outcome moves when an item is bought, from logged runs.

    python -m cursed_words_solver.sim.game.itemvalue             # rebuild from runs.jsonl

``expert.evaluate`` appends every simulated run (purchases, shops visited, outcome) to
``runs.jsonl``. For each stage the baseline is the mean outcome of the runs (same
character) that reached a shop in that stage; a purchase of item X there scores
``outcome − baseline``. The advantage of X is the mean of those scores shrunk towards its
parent key (X@stage#character → X@stage → X → 0, ``PRIOR_WEIGHT`` pseudo-purchases each),
so rare items start neutral and sharpen as runs accumulate, like the boss-risk table.

It is confounded (the policy buys what Advice and the probes already like, when it can
afford it), so ``PowerConfig.item_value`` adds it to probe gains as a long-term prior —
scaling and economy items the one-encounter probe undervalues — rather than replacing them.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

DEFAULT_PATH = Path.home() / ".cursed_words_solver" / "sim_models" / "item_value.json"
RUN_LOG = DEFAULT_PATH.with_name("runs.jsonl")
PRIOR_WEIGHT = 20.0


def read_runs(path: Path = RUN_LOG) -> list[dict[str, Any]]:
    """Logged runs that played to the end without a model or a crash."""
    out = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue  # a line cut short by an interrupted write
        if not r.get("error") and not r.get("model"):
            out.append(r)
    return out


class ItemValue:
    def __init__(self, sums: dict[str, list[float]] | None = None) -> None:
        self.sums: dict[str, list[float]] = sums or {}  # key -> [purchases, sum of outcome − baseline]

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "ItemValue":
        try:
            return cls(json.loads(Path(path).read_text())["sums"])
        except (OSError, ValueError, KeyError):
            return cls()

    def save(self, path: Path = DEFAULT_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        top = {k: round(self.value_key(k), 3) for k in sorted(self.sums) if "@" not in k}
        path.write_text(json.dumps({"sums": self.sums, "value": top}, indent=1))

    @classmethod
    def build(cls, runs: Iterable[dict[str, Any]]) -> "ItemValue":
        runs = list(runs)
        base: dict[tuple[str, int], list[float]] = defaultdict(lambda: [0.0, 0.0])
        for r in runs:
            for st in {s for s, _ in r.get("shops") or ()}:
                b = base[(r["character"], st)]
                b[0] += 1
                b[1] += r["outcome"]
        sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for r in runs:
            for st, _node, cls_ in r.get("buys") or ():
                n, tot = base[(r["character"], st)]
                d = r["outcome"] - tot / n
                for k in (cls_, f"{cls_}@s{st}", f"{cls_}@s{st}#{r['character']}"):
                    sums[k][0] += 1
                    sums[k][1] += d
        return cls({k: v for k, v in sums.items()})

    def value_key(self, k: str) -> float:
        """The root key is its mean shrunk towards 0. A child adds its shrunk deviation from
        the parent's raw mean, so purchases already counted in the parent are not counted
        twice (a child holding all of its parent's purchases equals the parent)."""
        n, tot = self.sums.get(k, (0.0, 0.0))
        parent = k.split("#")[0] if "#" in k else k.split("@")[0] if "@" in k else None
        if parent is None:
            return tot / (n + PRIOR_WEIGHT)
        pv = self.value_key(parent)
        pn, ptot = self.sums.get(parent, (0.0, 0.0))
        if not n or not pn:
            return pv
        return pv + n / (n + PRIOR_WEIGHT) * (tot / n - ptot / pn)

    def value(self, game_class: str, stage: int | None = None, character: str | None = None) -> float:
        """Shrunk mean outcome gain (encounters) of buying ``game_class``."""
        if stage is None:
            return self.value_key(game_class)
        return self.value_key(f"{game_class}@s{stage}" + (f"#{character}" if character else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="rebuild the item-value table from logged runs")
    ap.add_argument("--runs", default=str(RUN_LOG))
    ap.add_argument("--out", default=str(DEFAULT_PATH))
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args(argv)
    runs = read_runs(Path(args.runs))
    table = ItemValue.build(runs)
    table.save(Path(args.out))
    items = sorted((k for k in table.sums if "@" not in k), key=table.value_key)
    for k in items[: args.top] + ["..."] + items[-args.top:]:
        if k == "...":
            print("  ...")
            continue
        n, _ = table.sums[k]
        print(f"{k:24s} bought {int(n):5d}  value {table.value_key(k):+.3f}")
    print(f"{len(runs)} runs -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
