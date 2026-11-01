"""Validate the run simulator (cursed_words_solver/sim/game) against real melmod captures.

    python scripts/sim_validate.py scoring    # capture → sim state → engine == game score
    python scripts/sim_validate.py dynamics   # consecutive captures: money / rack / counters / target
    python scripts/sim_validate.py grids      # real first grids vs simulated grids (z-scores)
    python scripts/sim_validate.py clears     # winning submit → next shop / boss reward (journals)
    python scripts/sim_validate.py shops      # shop prices, restock cost, stock vs simulated stock

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


def _journal_states(journal: Path) -> list[dict]:
    """Every ``record_run.py`` journal export with a game state, by capture time."""
    out = []
    for f in sorted(journal.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                gs = json.loads(line)["run_state"].get("game_state")
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
            if isinstance(gs, dict) and gs.get("run") and gs.get("player") and gs.get("captured_at"):
                out.append(gs)
    return sorted(out, key=lambda gs: gs["captured_at"])


_NEXT_NODE = {"EncounterFirst": "ShopOne", "EncounterSecond": "ShopTwo", "Boss": "BossReward"}


def _seconds(a: str, b: str) -> float:
    from datetime import datetime

    def t(x: str) -> datetime:
        return datetime.fromisoformat(x.rstrip("Z")[:26])

    return (t(b) - t(a)).total_seconds()


def _fields(f: dict) -> dict:
    """Item fields in one form for sim and game: Mutating DNA's letter keys as engine
    tokens, Rainbow's tile types in lower case, Random Access Memory's items by class (the
    sim keeps them on the item)."""
    from cursed_words_solver.engine.calc import game_srep_to_engine

    f = dict(f or {})
    if isinstance(f.get("LetterUseCounts"), dict):
        f["LetterUseCounts"] = {game_srep_to_engine(k): v for k, v in f["LetterUseCounts"].items()}
    for k in ("ItemToAddToMemory1", "ItemToAddToMemory2"):
        if k in f:
            f[k] = (f[k] or {}).get("class")
    if isinstance(f.get("ChosenTileTypes"), list):  # Rainbow: tile type names, any case
        f["ChosenTileTypes"] = [str(x).lower() for x in f["ChosenTileTypes"]]
    if "ItemsInMemory" in f:
        f["ItemsInMemory"] = [(x or {}).get("class") for x in f["ItemsInMemory"]]
    return f


def _items(rows, shuffled: bool = False) -> list:
    keep = ("class", "levels", "values", "fields", "money_invested", "foil")
    out = [None if r is None else {**{k: r.get(k) for k in keep}, "fields": _fields(r.get("fields"))} for r in rows or []]
    return sorted(out, key=lambda r: json.dumps(r, sort_keys=True)) if shuffled else out


def _diff(k: str, sim: dict, real: dict) -> str:
    if k == "money":
        return f"sim {sim['money']} real {real.get('money')}"
    if k == "rack":
        return f"sim {sum(t is not None for t in sim['consumables'])} real {sum(1 for t in real.get('consumables') or [] if t)}"
    a, b = (_items(sim[k]), _items(real.get(k))) if k != "pin" else (_items([sim["pin"]]), _items([real.get("pin")]))
    for x, y in zip(a, b):
        if x != y:
            if x and y:
                return f"{x['class']}: " + ", ".join(f"{f} sim {x[f]} real {y[f]}" for f in x if x[f] != y[f])
            return f"sim {x and x['class']} real {y and y['class']}"
    return f"{len(a)} vs {len(b)} slots"


def clears(logs: Path, journal: Path) -> int:
    """Each capture whose word clears its encounter, replayed in the sim through the
    payout into the next node, against the journal's first state there (before any shop
    action): money, rack size, sticker / stamp / pin rows (class, levels, values, fields,
    money invested, foil)."""
    import bisect

    from cursed_words_solver.sim.game.bridge import player_state
    from cursed_words_solver.sim.game.importer import game_from_game_state

    states = _journal_states(journal)
    times = [gs["captured_at"] for gs in states]
    stats = collections.Counter()
    bad = collections.defaultdict(list)
    for f, d, cap in _captures(logs):
        a = cap["pre_submit"]
        ra = a.get("run") or {}
        i = bisect.bisect_right(times, a.get("captured_at") or "")
        nxt = next((gs for gs in states[i:i + 40] if (gs["run"].get("stage"), gs["run"].get("node_type"))
                    != (ra.get("stage"), ra.get("node_type"))), None)
        if (nxt is None or nxt["player"].get("character") != a["player"].get("character")
                or _seconds(a["captured_at"], nxt["captured_at"]) > 300
                or nxt["run"].get("node_type") != _NEXT_NODE.get(ra.get("node_type"))):
            continue  # not the node right after this encounter (journal gap, new run, Michael)
        g = game_from_game_state(a)
        _with_scoring_order(g, a, cap)
        sub = cap.get("submission") or {}
        path = [(int(t["x"]), int(t["y"])) for t in sub.get("tiles") or []]
        words = [str(w) for w in sub.get("words") or [] if str(w)]
        try:
            g.submit(path, words)
        except Exception as e:  # noqa: BLE001 - report, keep validating
            bad["error"].append((f.name, repr(e)[:80]))
            continue
        if g.encounter is not None and not g.encounter.won:
            continue  # not the clearing word (the journal skipped states in between)
        stats["clears"] += 1
        sim, real = player_state(g.player), nxt["player"]
        for kind, items in (("stickers", g.player.stickers), ("stamps", g.player.stamps), ("pin", [g.player.pin])):
            rows = sim[kind] if kind != "pin" else [sim["pin"]]
            for row, it in zip(rows, items):  # the engine export leaves these out
                if row is not None:
                    row.update(money_invested=list(it.money_invested), foil=bool(it.is_foil))
                    if it.game_class == "RandomAccessMemory":
                        row["fields"] = {**row["fields"], "ItemsInMemory": [{"class": m.game_class} for m in it.memory],
                                         "ItemToAddToMemory1": it.next_items[0] and {"class": it.next_items[0].game_class},
                                         "ItemToAddToMemory2": it.next_items[1] and {"class": it.next_items[1].game_class}}
        # Randomise Item Order shuffles slots when its fight ends (the game's RNG): compare as sets.
        shuffled = any(b.game_class == "RandomiseItemOrder" for b in g.player.active_bosses or []) or any(
            (b.get("class") == "RandomiseItemOrder") for b in (a.get("encounter") or {}).get("bosses") or [])
        for k, eq in (("money", sim["money"] == real.get("money")),
                      ("rack", sum(t is not None for t in sim["consumables"]) == sum(1 for t in real.get("consumables") or [] if t)),
                      ("stickers", _items(sim["stickers"], shuffled) == _items(real.get("stickers"), shuffled)),
                      ("stamps", _items(sim["stamps"], shuffled) == _items(real.get("stamps"), shuffled)),
                      ("pin", _items([sim["pin"]]) == _items([real.get("pin")]))):
            stats[k] += eq
            if not eq:
                bad[k].append((f.name, nxt["run"].get("node_type"), _diff(k, sim, real)))
    print("clears:", dict(stats))
    for k, v in bad.items():
        print(f"  {k} mismatches ({len(v)}):")
        for row in v[:12]:
            print("    ", *row)
    return 0


def _journal_exports(journal: Path) -> list[dict]:
    """Journal ``run_state`` exports that carry a game state, by capture time."""
    out = []
    for f in sorted(journal.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rs = json.loads(line)["run_state"]
            except (json.JSONDecodeError, KeyError):
                continue
            gs = rs.get("game_state") if isinstance(rs, dict) else None
            if isinstance(gs, dict) and gs.get("run") and gs.get("player") and gs.get("captured_at"):
                out.append(rs)
    return sorted(out, key=lambda rs: rs["game_state"]["captured_at"])


def _offer_feats(player, kind: str, item, foil: bool) -> collections.Counter:
    owned = {i.game_class for i in player.all_items(for_comparison=True)}
    tags = {t for i in player.all_items(for_comparison=True) for t in i.tags}
    c = collections.Counter({f"{kind}s": 1})
    c[f"{kind}:{item.rarity}"] += 1
    c[f"{kind}:upgrade"] += item.game_class in owned
    c[f"{kind}:tag match"] += bool(tags & set(item.tags))
    c[f"{kind}:foil"] += foil
    return c


def shop_stats(journal: Path, samples: int = 50) -> dict:
    """Shop exports (``record_run.py`` journals) against the sim: every offer's base price
    (``GetCost``), the restock price on entry, and the stock generated on entry against
    ``samples`` shops the sim generates from the same state. The export's ``price`` is
    always 0 and its ``restock_cost`` is ``_rerollPrice`` before Fried Shrimp, so the shown
    price is not checked and the restock check uses ``Shop.reroll_price``. Frozen slots
    (carried over, not generated) are left out on both sides."""
    from cursed_words_solver.sim.game.core import Rng
    from cursed_words_solver.sim.game.importer import game_from_game_state, item_from_row
    from cursed_words_solver.sim.game.shop import Shop

    exports = [rs for rs in _journal_exports(journal) if isinstance(rs.get("shop"), dict)
               and str(rs["game_state"]["run"].get("node_type", "")).startswith("Shop")]
    out = {"stats": collections.Counter(), "bad": collections.defaultdict(list), "obs": collections.Counter(),
           "exp": collections.Counter(), "var": collections.Counter(), "class_obs": collections.Counter(),
           "class_exp": collections.Counter()}
    stats, bad = out["stats"], out["bad"]
    prev = None
    for rs in exports:
        gs, snap = rs["game_state"], rs["shop"]
        p = game_from_game_state(gs).player
        offers = [o for o in snap.get("offers") or [] if o.get("slot") in ("sticker", "stamp")
                  and isinstance(o.get("item_state"), dict)]
        for o in offers:
            if o.get("sold"):
                continue
            it = item_from_row(o["item_state"])
            if it is None:
                continue
            it.is_foil = bool(o.get("foil"))
            stats["offers"] += 1
            ok = it.get_cost(p) == int(o.get("base_price") or 0)
            stats["base price"] += ok
            if not ok:
                bad["base price"].append((it.game_class, f"sim {it.get_cost(p)} real {o.get('base_price')}", p.character))
        key = (gs["player"].get("character"), gs["run"].get("stage"), gs["run"].get("node_type"))
        entry = key != prev and not any(o.get("sold") for o in offers)
        prev = key
        if not entry:
            continue
        stats["shop entries"] += 1
        ok = Shop(p, Rng(0)).reroll_price == int(snap.get("restock_cost") or 0)
        stats["restock price"] += ok
        if not ok:
            bad["restock price"].append((key, f"sim {Shop(p, Rng(0)).reroll_price} real {snap.get('restock_cost')}"))
        frozen = {(o["slot"], int(o.get("index", 0))) for o in offers if o.get("frozen")}
        real = collections.Counter()
        for o in offers:
            if (o["slot"], int(o.get("index", 0))) in frozen:
                continue
            it = item_from_row(o["item_state"])
            if it is not None:
                real += _offer_feats(p, o["slot"], it, bool(o.get("foil")))
                out["class_obs"][it.game_class] += 1
        sims = []
        for n in range(samples):
            p2 = game_from_game_state(gs).player
            sh = Shop(p2, Rng(f"shops|{gs['captured_at']}|{n}"))
            c = collections.Counter()
            for kind, arr in (("sticker", sh.stickers), ("stamp", sh.stamps)):
                for k, so in enumerate(arr):
                    if so is not None and (kind, k) not in frozen:
                        c += _offer_feats(p2, kind, so.item, so.item.is_foil)
                        out["class_exp"][so.item.game_class] += 1 / samples
            sims.append(c)
        for k in set(real).union(*sims):
            vals = [c.get(k, 0) for c in sims]
            out["obs"][k] += real.get(k, 0)
            out["exp"][k] += statistics.mean(vals)
            out["var"][k] += statistics.pvariance(vals)
    return out


def shops(journal: Path, samples: int = 50) -> int:
    r = shop_stats(journal, samples)
    print("shops:", dict(r["stats"]))
    for k, v in r["bad"].items():
        print(f"  {k} mismatches ({len(v)}):", collections.Counter(v).most_common(10))
    obs, exp, var = r["obs"], r["exp"], r["var"]
    print("  stock on entry, observed vs simulated (z; counts of offers, and per kind):")
    for k in sorted(obs, key=lambda k: (k.split(":")[0], k)):
        z = (obs[k] - exp[k]) / var[k] ** 0.5 if var[k] > 1e-9 else 0.0
        print(f"    {k:22s} {obs[k]:5d} vs {exp[k]:7.1f}   z {z:+.1f}")
    co, ce = r["class_obs"], r["class_exp"]
    never = sorted((c for c in ce if co[c] == 0 and ce[c] >= 2.5), key=lambda c: -ce[c])
    print(f"  {sum(co.values())} generated offers; never offered though the sim expects >= 2.5 ({len(never)}):")
    print("    " + ", ".join(f"{c} {ce[c]:.1f}" for c in never))
    unknown = sorted(c for c in co if ce[c] < 0.05)
    print(f"  offered but (almost) never by the sim ({len(unknown)}):", ", ".join(f"{c} {co[c]}" for c in unknown))
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
    n = placed = 0
    for _f, _d, cap in _captures(logs):
        gs = cap["pre_submit"]
        e = gs.get("encounter") or {}
        if e.get("grids_generated") != 1 or e.get("previous_words"):
            continue
        if any(b.get("class") == "DestroyGrid" for b in e.get("bosses") or []):
            continue  # the capture's boss already holds this grid's destroyed squares
        g = game_from_game_state(gs)
        if any(t.was_consumable and not t.in_void for t in g.encounter.grid.tiles):
            placed += 1  # rack tiles placed before the first word replaced grid squares
            continue
        n += 1
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
    print(f"grids: {n} real first grids ({placed} skipped: rack tiles already placed), {samples} simulated each; |z|>3 per feature:")
    for k in sorted(tot, key=lambda k: -bad[k]):
        if bad[k]:
            print(f"  {k:24s} {bad[k]}/{tot[k]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("check", choices=("scoring", "dynamics", "grids", "clears", "shops"))
    ap.add_argument("--logs", default=str(Path.home() / ".cursed_words_solver" / "round_logs"))
    ap.add_argument("--journal", default=str(Path.home() / ".cursed_words_solver" / "run_journal"))
    args = ap.parse_args(argv)
    logs = Path(args.logs)
    if args.check == "clears":
        return clears(logs, Path(args.journal))
    if args.check == "shops":
        return shops(Path(args.journal))
    return {"scoring": scoring, "dynamics": dynamics, "grids": grids}[args.check](logs)


if __name__ == "__main__":
    raise SystemExit(main())
