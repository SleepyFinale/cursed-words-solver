"""Validate the run simulator (cursed_words_solver/sim/game) against real melmod captures.

    python scripts/sim_validate.py scoring    # capture → sim state → engine == game score
    python scripts/sim_validate.py dynamics   # consecutive captures: money / rack / counters / target
    python scripts/sim_validate.py grids      # real first grids vs simulated grids (z-scores)

Reads round logs with a ``capture`` block (melmod 1.4+) from
``~/.cursed_words_solver/round_logs`` (``--logs`` to override).
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
from pathlib import Path


def _captures(logs: Path):
    for f in sorted(logs.glob("2*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cap = d.get("capture")
        if isinstance(cap, dict) and isinstance(cap.get("pre_submit"), dict):
            yield f, d, cap


def _with_scoring_order(g, gs, cap):
    from cursed_words_solver.sim.game.importer import apply_player

    sc = cap.get("scoring_call") or {}
    if isinstance(sc.get("item_states"), dict):
        gs2 = dict(gs)
        gs2["player"] = {**gs["player"], **{k: v for k, v in sc["item_states"].items() if k in ("stickers", "stamps", "pin")}}
        apply_player(g.player, gs2)


def scoring(logs: Path) -> int:
    from cursed_words_solver.sim.game.importer import game_from_game_state

    n = ok = nd = 0
    bad = []
    for f, d, cap in _captures(logs):
        actual = (d.get("actual") or {}).get("score")
        if actual is None:
            continue
        n += 1
        g = game_from_game_state(cap["pre_submit"])
        _with_scoring_order(g, cap["pre_submit"], cap)
        sub = cap.get("submission") or {}
        path = [(int(t["x"]), int(t["y"])) for t in sub.get("tiles") or []]
        words = [str(w) for w in sub.get("words") or [] if str(w)]
        res = g.encounter.score_preview(path, words)
        score = int(res.int_score) * (-1 if g.player.run.challenge_is("TwoWrongs") else 1)
        if score == int(actual):
            ok += 1
        elif res.nondeterministic:
            nd += 1
        else:
            bad.append((f.name, score, actual))
    print(f"scoring: {ok}/{n} exact, {nd} nondeterministic, {len(bad)} wrong")
    for b in bad[:20]:
        print("  ", b)
    return 0 if not bad else 1


def dynamics(logs: Path) -> int:
    from cursed_words_solver.sim.game.importer import game_from_game_state

    caps = list(_captures(logs))
    stats = collections.Counter()
    for (f1, d1, c1), (_f2, _d2, c2) in zip(caps, caps[1:]):
        a, b = c1["pre_submit"], c2["pre_submit"]
        ra, rb, ea, eb = a["run"], b["run"], a["encounter"], b["encounter"]
        if not (ra.get("stage") == rb.get("stage") and ra.get("node_type") == rb.get("node_type")
                and eb.get("grids_generated") == ea.get("grids_generated", 0) + 1):
            continue
        stats["pairs"] += 1
        g = game_from_game_state(a)
        sub = c1.get("submission") or {}
        path = [(int(t["x"]), int(t["y"])) for t in sub.get("tiles") or []]
        words = [str(w) for w in sub.get("words") or [] if str(w)]
        g.encounter.submit(path, words)
        stats["money"] += g.player.money == b["player"]["money"]
        stats["remaining"] += g.encounter.remaining_target == eb["remaining_target"]
        stats["rack"] += sum(t is not None for t in g.player.consumables) == sum(1 for t in b["player"]["consumables"] if t)
    print("dynamics:", dict(stats))
    return 0


def grids(logs: Path, samples: int = 100) -> int:
    from cursed_words_solver.sim.game.agent import clone
    from cursed_words_solver.sim.game.core import Rng
    from cursed_words_solver.sim.game.grid_util import GenCtx
    from cursed_words_solver.sim.game.gridgen import generate_grid
    from cursed_words_solver.sim.game.importer import game_from_game_state

    def feats(tiles):
        c = collections.Counter()
        for t in tiles:
            if t.in_void or t.destroyed:
                continue
            c["type:" + t.tile_type] += 1
            c["glyph:" + t.glyph] += 1
            if t.suit != "none":
                c["suited"] += 1
        return c

    bad = collections.Counter()
    tot = collections.Counter()
    n = 0
    for _f, _d, cap in _captures(logs):
        gs = cap["pre_submit"]
        e = gs.get("encounter") or {}
        if e.get("grids_generated") != 1 or e.get("previous_words"):
            continue
        if any(b.get("class") == "DestroyGrid" for b in e.get("bosses") or []):
            continue  # the capture's boss already holds this grid's destroyed squares
        n += 1
        g = game_from_game_state(gs)
        real = feats(g.encounter.grid.tiles)
        sims = []
        for s in range(samples):
            g2 = clone(g)
            g2.rng = Rng(f"grids|{s}")
            enc = g2.encounter
            ctx = GenCtx(player=g2.player, rng=g2.rng, grid=enc.grid, grid_number=1,
                         number_of_grids=enc.total_grids, previous_words=[], word_source=lambda _n: "cacti")
            sims.append(feats(generate_grid(ctx, enc.grid.width, enc.grid.height, enc.bosses).tiles))
        for k in set(real) | set().union(*sims):
            vals = [s.get(k, 0) for s in sims]
            mu = statistics.mean(vals)
            sd = statistics.pstdev(vals) or 0.5
            tot[k] += 1
            if abs((real.get(k, 0) - mu) / sd) > 3:
                bad[k] += 1
    print(f"grids: {n} real first grids, {samples} simulated each; |z|>3 per feature:")
    for k in sorted(tot, key=lambda k: -bad[k]):
        if bad[k]:
            print(f"  {k:24s} {bad[k]}/{tot[k]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("check", choices=("scoring", "dynamics", "grids"))
    ap.add_argument("--logs", default=str(Path.home() / ".cursed_words_solver" / "round_logs"))
    args = ap.parse_args(argv)
    logs = Path(args.logs)
    return {"scoring": scoring, "dynamics": dynamics, "grids": grids}[args.check](logs)


if __name__ == "__main__":
    raise SystemExit(main())
