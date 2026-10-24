"""Learned boss difficulty: how often each boss ends a run, from simulated runs.

    python -m cursed_words_solver.sim.game.bossrisk --runs 512      # add 512 runs to the table
    python -m cursed_words_solver.sim.game.bossrisk --from-log      # add the newly logged runs

Every finished ``Game`` contributes (boss faced, run ended there) counts per boss class
(cursed bosses separately). Risk is the Beta-smoothed death rate, shrunk towards the
average boss, so rare bosses start near the mean and sharpen as runs accumulate.
``FastAdvicePolicy`` uses it for the boss draft when ``PowerConfig.boss_risk`` names a table.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from cursed_words_solver.sim.game.player import Node

DEFAULT_PATH = Path.home() / ".cursed_words_solver" / "sim_models" / "boss_risk.json"
PRIOR_WEIGHT = 20.0  # pseudo-encounters of the average boss


def key(game_class: str, cursed: bool) -> str:
    return f"{game_class}{'*' if cursed else ''}"


def boss_outcomes(game) -> list[tuple[str, bool]]:
    """(boss key, ended the run) for each boss the finished run fought."""
    chosen = [key(e.data["boss"], bool(e.data.get("cursed"))) for e in game.events if e.kind == "boss"]
    if not chosen:
        return []
    node = game.player.run.node
    if not game.won and node in (Node.BOSS_DRAFT, Node.MEG_SHOP):
        chosen = chosen[:-1]  # drafted but never fought
    died = game.won is False and node == Node.BOSS
    return [(b, died and i == len(chosen) - 1) for i, b in enumerate(chosen)]


class BossRisk:
    def __init__(self, counts: dict[str, list[int]] | None = None, logged: int = 0) -> None:
        self.counts: dict[str, list[int]] = counts or {}  # key -> [faced, died]
        self.logged = logged  # lines of the run log already counted

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "BossRisk":
        try:
            d = json.loads(Path(path).read_text())
            return cls(d["counts"], d.get("logged", 0))
        except (OSError, ValueError, KeyError):
            return cls()

    def save(self, path: Path = DEFAULT_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"counts": self.counts, "logged": self.logged,
                                    "risk": {k: round(self.risk_key(k), 4) for k in sorted(self.counts)}}, indent=1))

    def add_log(self, path: Path) -> int:
        """Count the bosses of run-log lines (``expert.evaluate``) added since the last call;
        the log is append-only, so ``logged`` marks where to resume. Returns runs added."""
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0
        added = 0
        for line in lines[self.logged:]:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not r.get("error") and r.get("bosses") is not None:
                self.record([(b, bool(d)) for b, d in r["bosses"]], r["crown"], r["character"])
                added += 1
        self.logged = len(lines)
        return added

    def add(self, game) -> None:
        self.record(boss_outcomes(game), game.player.run.ascension, game.player.character)

    def record(self, outcomes: list[tuple[str, bool]], crown: int, character: str | None = None) -> None:
        """Counts per boss over everything, per crown (``Class*@c3``) and per crown and
        character (``Class*@c3#WetDennis``)."""
        for b, died in outcomes:
            keys = [b, f"{b}@c{crown}"] + ([f"{b}@c{crown}#{character}"] if character else [])
            for k in keys:
                c = self.counts.setdefault(k, [0, 0])
                c[0] += 1
                c[1] += int(died)

    def mean(self, cursed: bool | None = None) -> float:
        """Average death rate over bosses (of one cursedness when it has data)."""
        rows = [c for k, c in self.counts.items() if "@" not in k
                and (cursed is None or k.endswith("*") == cursed)]
        f = sum(c[0] for c in rows)
        if cursed is not None and f < 50:
            return self.mean(None)
        d = sum(c[1] for c in rows)
        return (d + 1) / (f + 10) if f else 0.1

    def _shrunk(self, k: str, prior: float) -> float:
        f, d = self.counts.get(k, (0, 0))
        return (d + PRIOR_WEIGHT * prior) / (f + PRIOR_WEIGHT)

    def risk_key(self, k: str) -> float:
        """Smoothed death rate down the chain average boss → boss → boss at this crown →
        boss at this crown for this character; each level shrinks towards the one above."""
        base, _, rest = k.partition("@")
        r = self._shrunk(base, self.mean(base.endswith("*")))
        if not rest:
            return r
        crown, _, char = rest.partition("#")
        r = self._shrunk(f"{base}@{crown}", r)
        return self._shrunk(k, r) if char else r

    def risk(self, boss, crown: int | None = None, character: str | None = None) -> float:
        k = key(boss.game_class, bool(boss.cursed))
        if crown is None:
            return self.risk_key(k)
        return self.risk_key(f"{k}@c{crown}" + (f"#{character}" if character else ""))


# ---------------------------------------------------------------------------- collection


def _job(job: dict[str, Any]) -> tuple[int, str, list[tuple[str, bool]]]:
    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.agent import apply

    g = E._game(job)
    pol = E.NetPolicy(E._CANDS, E._MODEL, seed=job["seed"])
    try:
        for _ in range(4000):
            if g.phase == "done":
                break
            apply(g, pol.act(g))
    except Exception:
        return job["crown"], g.player.character, []
    return job["crown"], g.player.character, boss_outcomes(g)


def main(argv: list[str] | None = None) -> int:
    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.agent import spawn_pool

    ap = argparse.ArgumentParser(description="add simulated runs to the boss-risk table")
    ap.add_argument("--runs", type=int, default=256)
    ap.add_argument("--seed", type=int, default=3000)
    ap.add_argument("--characters", default="WetDennis")
    ap.add_argument("--crowns", default="0")
    ap.add_argument("--model", default=None, help="policy model (default: Fast Advice)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=str(DEFAULT_PATH))
    ap.add_argument("--from-log", nargs="?", const=str(DEFAULT_PATH.with_name("runs.jsonl")), default=None,
                    help="add the run log's new runs instead of simulating")
    args = ap.parse_args(argv)
    table = BossRisk.load(Path(args.out))
    if args.from_log:
        n = table.add_log(Path(args.from_log))
        table.save(Path(args.out))
        print(f"{n} logged runs added -> {args.out}")
        return 0
    jobs = E.make_jobs(args.runs, args.seed, args.characters.split(","), [int(c) for c in args.crowns.split(",")])
    t0 = time.time()
    with spawn_pool(args.workers, E._init, (None, args.model)) as pool:
        for crown, char, res in pool.imap_unordered(_job, jobs):
            table.record(res, crown, char)
    table.save(Path(args.out))
    for k in sorted((k for k in table.counts if "@" not in k), key=table.risk_key, reverse=True):
        f, d = table.counts[k]
        print(f"{k:24s} faced {f:5d} ended run {d:4d}  risk {table.risk_key(k):.3f}")
    print(f"{args.runs} runs in {time.time() - t0:.0f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
