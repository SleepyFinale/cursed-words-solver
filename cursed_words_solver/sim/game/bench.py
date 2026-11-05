"""Paired benchmark on fixed held-out seeds (P5): one scoreboard for every policy change.

    python -m cursed_words_solver.sim.game.bench run <arm> [--cfg JSON] [--model PATH] [--threshold X]
        [--char-tuning PATH] [--action-space full|advice] [--per 6] [--crowns 0-7]
        [--characters A,B] [--workers 8]
    python -m cursed_words_solver.sim.game.bench compare <base arm> <arm> [--crowns ...] [--characters ...]
    python -m cursed_words_solver.sim.game.bench show <arm>
    python -m cursed_words_solver.sim.game.bench gate <base arm> <arm> (--block K | --first-seed N)
        [--delta 0.2] [--searched N] [the options of run]

An arm is a policy: ``expert.NetPolicy`` (the benchmark policy) plus ``PowerConfig``
overrides, an optional learned model / margin, per-character settings and action space.
Every arm plays the same runs: each character x crown x ``per`` seeds, seed
8,000,000 + 1000 x character + 100 x crown + i (apart from the 7,000,000 tuning seeds and
the training seeds), so two arms are compared run by run (a paired difference has sd ~3.3:
528 runs detect about +0.3 outcome at t 2).

Runs are appended to ``<dir>/<arm>.jsonl`` as they finish (resumable at any point: rerun
the same command); ``<arm>.json`` holds the arm's settings, and a rerun with different
settings is refused. Each run records a fingerprint of the package source (``code``):
``compare`` warns when the two arms ran on different code, since then the difference is
not only the arm's.

``--keyed`` restarts the random stream before every action from where the run is, as
``expert.play_out`` does, so a change at one decision does not shift later grids and shops.
Arms must agree on it to be compared. ``--salt`` plays other games on the same seeds: base
against a salted base is the A/A check (independent runs), base against an identical base
must differ by exactly zero.

``gate`` is the promotion test. It plays both arms one block at a time (one seed per
character and crown, 88 runs) and stops on a sequential test of the mean outcome gain, then
reports the raw figures with a shrunk estimate and interval. To be promoted, an arm must also
hold its win rate and Michael wins (``GATE_FLOOR``), which takes about 10 blocks. Searching
for settings uses ``--first-seed`` (``SEARCH_SEED``); only a ``--block`` of seeds not used for
any other arm can promote (``seed_blocks.json`` in the results directory refuses a reuse), so
the winner of a search is not judged on the seeds that chose it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path.home() / ".cursed_words_solver" / "bench"
FIRST_SEED = 8_000_000  # the regression block
SEARCH_SEED = 7_000_000
BLOCK_SEED = 9_000_000  # single-use promotion blocks
BLOCK_STEP = 20_000  # a block's seeds span 1000 x 11 characters, so 10,000 would overlap
SALT_STEP = 1_000_000_007
ACCEPT_LLR, REJECT_LLR = 2.77, -1.56  # sequential test at 5% false positives, 80% power
CAP_FACTOR = 1.5  # a sequential test stops undecided at this many times the fixed-sample size
FIXED_Z = 1.645 + 0.842
GATE_FLOOR = -0.02  # a promotion's one-sided 95% lower bound on win and Michael win rate change
SHRINK_PRIOR_SD = 0.15  # most policy changes are worth little: the reported gain is pulled to 0
CHARS = ["BonesTheDog", "HayleyBayles", "NathaServo", "NinaNix", "Octacles", "PrismaticBean",
         "SamGambit", "SandySaguaro", "SockHead", "Spike", "WetDennis"]
SPEC_KEYS = ("cfg", "model", "threshold", "char_tuning", "action_space", "keyed", "salt")
SPEC_DEFAULTS = {"keyed": False, "salt": 0}  # arms made before these settings existed


def seeds(per: int = 6, crowns=range(8), chars=CHARS, first: int = FIRST_SEED) -> list[tuple[str, int, int]]:
    """(character, crown, seed) of the benchmark runs; the index ``i`` is ``seed % 100``."""
    return [(ch, cr, first + 1000 * CHARS.index(ch) + 100 * cr + i)
            for i in range(per) for ch in chars for cr in crowns]


def block_first_seed(block: int) -> int:
    return BLOCK_SEED + BLOCK_STEP * block


def code_fingerprint() -> str:
    """Short hash of every ``.py`` file in the package (what the runs were played with)."""
    root = Path(__file__).resolve().parents[2]
    h = hashlib.sha1()
    for f in sorted(root.rglob("*.py")):
        h.update(str(f.relative_to(root)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:10]


def spec(cfg: dict | None = None, model: str = "", threshold: float | None = None,
         char_tuning: str = "", action_space: str = "full", keyed: bool = False, salt: int = 0) -> dict[str, Any]:
    return {"cfg": dict(cfg or {}), "model": model or "", "threshold": threshold,
            "char_tuning": char_tuning or "", "action_space": action_space, "keyed": keyed, "salt": salt}


def _spec_settings(sp: dict[str, Any]) -> dict[str, Any]:
    return {k: sp.get(k, SPEC_DEFAULTS.get(k)) for k in SPEC_KEYS}


# -- playing -------------------------------------------------------------------------


def _lead_cursed(g) -> int:
    lead = 0
    for e in g.events:
        if e.kind == "boss":
            if not e.data.get("cursed"):
                break
            lead += 1
    return lead


def reseed_for(g, seed: int, salt: int, seen: dict[tuple, int], kind: str) -> None:
    """Restart ``g``'s stream from where the run is and the action about to be taken, so two runs
    at the same point draw the same grids, shops and restocks whatever else differs."""
    from cursed_words_solver.sim.game.expert import _point

    k = (*_point(g), kind)
    seen[k] = seen.get(k, 0) + 1
    g.rng.reseed(f"bench|{seed}|{salt}|{k}|{seen[k]}")


def job(j: dict[str, Any]) -> dict[str, Any]:
    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.agent import apply
    from cursed_words_solver.sim.game.features import outcome
    from cursed_words_solver.sim.game.policy import with_overrides

    t0 = time.time()
    s = j["spec"]
    salt = s.get("salt", 0)
    game_seed = j["seed"] + SALT_STEP * salt
    g = E._game({**j, "seed": game_seed})
    pol = E.NetPolicy(E._CANDS, E._MODEL, seed=game_seed, threshold=s["threshold"], boss_risk=str(E.BOSS_RISK_PATH),
                      char_tuning=s["char_tuning"], action_space=s["action_space"])
    if s["cfg"]:
        pol.cfg = with_overrides(pol.cfg, s["cfg"])
    error = ""
    keyed, seen = s.get("keyed", False), {}
    try:
        for _ in range(5000):
            if g.phase == "done":
                break
            a = pol.act(g)
            if keyed:
                reseed_for(g, j["seed"], salt, seen, a.kind)
            apply(g, a)
    except Exception as exc:  # a crash ends the run as a loss; recorded so it is not mistaken for one
        error = f"{type(exc).__name__}: {exc}"
    return {"char": j["character"], "crown": j["crown"], "seed": j["seed"], "won": bool(g.won),
            "reason": g.end_reason, "outcome": round(outcome(g), 4), "stage": g.player.run.stage,
            "lead_cursed": _lead_cursed(g), "secs": round(time.time() - t0, 1), "code": j["code"], "error": error}


def load(path: Path) -> dict[tuple[str, int, int], dict]:
    """Rows of a results file by (character, crown, seed); a line cut short by a restart is skipped."""
    rows = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows[(r["char"], r["crown"], r["seed"])] = r
    return rows


def run(arm: str, s: dict[str, Any], *, per: int = 6, crowns=range(8), chars=CHARS, workers: int = 8,
        out_dir: Path = DEFAULT_DIR, first: int = FIRST_SEED) -> Path:
    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.agent import spawn_pool

    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path, res_path = out_dir / f"{arm}.json", out_dir / f"{arm}.jsonl"
    if meta_path.is_file():
        old = json.loads(meta_path.read_text())["spec"]
        if _spec_settings(old) != _spec_settings(s):
            raise SystemExit(f"arm {arm!r} exists with other settings {old}; pick another name")
    else:
        meta_path.write_text(json.dumps({"spec": s, "created": time.strftime("%Y-%m-%d %H:%M")}, indent=1))
    have = load(res_path)
    code = code_fingerprint()
    todo = [{"character": ch, "crown": cr, "seed": sd, "spec": s, "code": code}
            for ch, cr, sd in seeds(per, crowns, chars, first) if (ch, cr, sd) not in have]
    print(f"{arm}: {len(have)} runs done, {len(todo)} to play (code {code})", flush=True)
    if not todo:
        return res_path
    t0 = time.time()
    with spawn_pool(workers, E._init, (None, s["model"] or None, E.EFFORT, True)) as pool:
        for k, r in enumerate(pool.imap_unordered(job, todo), 1):
            with res_path.open("a") as f:
                f.write(json.dumps(r) + "\n")
            if r["error"]:
                print(f"  crash {r['char']} c{r['crown']} {r['seed']}: {r['error']}", flush=True)
            if k % 24 == 0 or k == len(todo):
                left = (time.time() - t0) / k * (len(todo) - k)
                print(f"  {k}/{len(todo)} (~{left / 60:.0f} min left)", flush=True)
    return res_path


# -- reports -------------------------------------------------------------------------


def beat_michael(r: dict) -> bool:
    return r["reason"] == "michael"


def reached_michael(r: dict) -> bool:
    return r["reason"] in ("michael", "michael_lost") or r.get("stage", 0) >= 6


def paired(base: dict, arm: dict, keys) -> dict[str, Any]:
    keys = list(keys)
    d = [arm[k]["outcome"] - base[k]["outcome"] for k in keys]
    n = len(d)
    m = sum(d) / n if n else 0.0
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    return {"n": n, "mean": round(m, 3), "sd": round(sd, 3), "t": round(m / se, 2) if se else 0.0,
            "wins": (sum(base[k]["won"] for k in keys), sum(arm[k]["won"] for k in keys)),
            "michael_reached": (sum(reached_michael(base[k]) for k in keys), sum(reached_michael(arm[k]) for k in keys)),
            "michael_beaten": (sum(beat_michael(base[k]) for k in keys), sum(beat_michael(arm[k]) for k in keys)),
            "better": sum(x > 1e-9 for x in d), "worse": sum(x < -1e-9 for x in d)}


def compare(base: dict, arm: dict, *, per: int | None = None) -> dict[str, dict[str, Any]]:
    """Paired report on the runs both arms played: all, seed halves (first / second half of
    the seed indices, a replication check), per crown, per character."""
    keys = sorted(set(base) & set(arm))
    if not keys:
        return {}
    per = per or (max(k[2] % 100 for k in keys) + 1)
    out = {"all": paired(base, arm, keys),
           "first half": paired(base, arm, [k for k in keys if k[2] % 100 < per / 2]),
           "second half": paired(base, arm, [k for k in keys if k[2] % 100 >= per / 2])}
    for cr in sorted({k[1] for k in keys}):
        out[f"crown {cr}"] = paired(base, arm, [k for k in keys if k[1] == cr])
    for ch in sorted({k[0] for k in keys}):
        out[ch] = paired(base, arm, [k for k in keys if k[0] == ch])
    return out


def print_report(rep: dict[str, dict[str, Any]]) -> None:
    for label, st in rep.items():
        if not st["n"]:
            continue
        print(f"{label:14s} n {st['n']:3d}  {st['mean']:+.3f} (sd {st['sd']:.2f}, t {st['t']:+.2f})  wins {st['wins'][0]}->{st['wins'][1]}"
              f"  Michael reached {st['michael_reached'][0]}->{st['michael_reached'][1]}"
              f" beaten {st['michael_beaten'][0]}->{st['michael_beaten'][1]}  better {st['better']} worse {st['worse']}")


# -- promotion gate ------------------------------------------------------------------


def sequential(blocks: list[list[float]], delta: float = 0.2) -> dict[str, Any]:
    """Sequential test of "gain = 0" against "gain = ``delta``" on per-seed differences, one
    complete block at a time, with the variance seen so far: LLR = delta / var x (S - n delta / 2),
    stopping at the first block that crosses a bound, or undecided ("cap") at ``CAP_FACTOR`` times
    the runs a fixed-sample test would need."""
    done: list[float] = []
    out = {"decision": "continue", "blocks": 0, "n": 0, "llr": 0.0, "cap_n": 0}
    for i, block in enumerate(blocks, 1):
        done += block
        n, total = len(done), sum(done)
        mean = total / n
        var = sum((x - mean) ** 2 for x in done) / (n - 1) if n > 1 else 0.0
        if var <= 0.0:  # no difference at all so far: the arm's change never mattered
            llr = -math.inf if total == 0 else math.copysign(math.inf, total)
        else:
            llr = delta / var * (total - n * delta / 2)
        cap_n = math.ceil(CAP_FACTOR * FIXED_Z ** 2 * var / delta ** 2)
        out = {"decision": "continue", "blocks": i, "n": n, "llr": llr, "cap_n": cap_n}
        if llr >= ACCEPT_LLR:
            out["decision"] = "accept"
        elif llr <= REJECT_LLR:
            out["decision"] = "reject"
        elif n >= cap_n:
            out["decision"] = "cap"
        if out["decision"] != "continue":
            break
    return out


def shrunk(mean: float, se: float, prior_sd: float = SHRINK_PRIOR_SD) -> float:
    """Gain after pulling it toward 0 by how noisy it is (normal prior around no effect): what to
    expect on fresh seeds from the best of a search, where the raw figure runs high."""
    return mean * prior_sd ** 2 / (prior_sd ** 2 + se ** 2)


def rate_change(base: list[bool], arm: list[bool], floor_z: float = 1.645) -> dict[str, float]:
    """Paired change of a yes / no rate: the change, its se and one-sided 95% lower bound."""
    n = len(base)
    if not n:
        return {"change": 0.0, "se": 0.0, "lower": 0.0}
    only_arm = sum(a and not b for a, b in zip(arm, base))
    only_base = sum(b and not a for a, b in zip(arm, base))
    change = (only_arm - only_base) / n
    se = math.sqrt(max(0.0, only_arm + only_base - (only_arm - only_base) ** 2 / n)) / n
    return {"change": change, "se": se, "lower": change - floor_z * se}


def bootstrap_interval(diffs: dict[tuple[str, int], list[float]], draws: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% interval of the mean difference, resampling seeds within each character and crown."""
    import random

    rng = random.Random(seed)
    groups = [v for v in diffs.values() if v]
    n = sum(len(v) for v in groups)
    if not n:
        return 0.0, 0.0
    means = sorted(sum(sum(rng.choices(v, k=len(v))) for v in groups) / n for _ in range(draws))
    return means[int(0.025 * draws)], means[min(draws - 1, int(0.975 * draws))]


def gate_report(base: dict, arm: dict, *, delta: float = 0.2, searched: int = 1, single_use: bool = False) -> dict[str, Any]:
    """The promotion decision on the complete blocks both arms played, with the figures a promotion
    must report (see ``sim-game.md``). The decision is the first block to cross a bound; the figures
    use every complete block, since stopping at a crossing flatters the gain and the win floor
    needs more seeds than the mean."""
    keys = sorted(set(base) & set(arm))
    by_block: dict[int, list] = {}
    for k in keys:
        by_block.setdefault(k[2] % 100, []).append(k)
    cell_count = max((len(v) for v in by_block.values()), default=0)
    blocks = []
    for i in sorted(by_block):
        if i != len(blocks) or len(by_block[i]) < cell_count:
            break  # only an unbroken run of complete blocks counts
        blocks.append(by_block[i])
    seq = sequential([[arm[k]["outcome"] - base[k]["outcome"] for k in b] for b in blocks], delta)
    used = [k for b in blocks for k in b]
    if not used:
        return {"decision": "continue", "promote": False, "n": 0, "sequential": seq}
    st = paired(base, arm, used)
    se = st["sd"] / math.sqrt(st["n"])
    cells: dict[tuple[str, int], list[float]] = {}
    for k in used:
        cells.setdefault(k[:2], []).append(arm[k]["outcome"] - base[k]["outcome"])
    wins = rate_change([base[k]["won"] for k in used], [arm[k]["won"] for k in used])
    michael = rate_change([beat_michael(base[k]) for k in used], [beat_michael(arm[k]) for k in used])
    holds = wins["lower"] > GATE_FLOOR and michael["lower"] > GATE_FLOOR
    return {"decision": seq["decision"], "promote": seq["decision"] == "accept" and holds and single_use,
            "holds": holds, "single_use": single_use, "sequential": seq, "searched": searched,
            "n": st["n"], "blocks": seq["blocks"], "gain": st["mean"], "sd": st["sd"], "t": st["t"],
            "shrunk": round(shrunk(st["mean"], se), 3), "interval": tuple(round(v, 3) for v in bootstrap_interval(cells)),
            "wins": st["wins"], "win_change": wins, "michael_beaten": st["michael_beaten"], "michael_change": michael}


def print_gate(rep: dict[str, Any]) -> None:
    if not rep.get("n"):
        print("gate: no complete block yet")
        return
    print(f"gate: {rep['decision']} at block {rep['blocks']}; {rep['n']} seeds so far, {rep['searched']} candidates searched;"
          f" LLR {rep['sequential']['llr']:+.2f}, cap {rep['sequential']['cap_n']} seeds")
    print(f"  gain {rep['gain']:+.3f} (sd {rep['sd']:.2f}, t {rep['t']:+.2f}), shrunk {rep['shrunk']:+.3f},"
          f" 95% interval {rep['interval'][0]:+.3f} to {rep['interval'][1]:+.3f}")
    print(f"  wins {rep['wins'][0]}->{rep['wins'][1]}, change {100 * rep['win_change']['change']:+.1f} points"
          f" (lower bound {100 * rep['win_change']['lower']:+.1f}); Michael wins {rep['michael_beaten'][0]}->{rep['michael_beaten'][1]}"
          f" (lower bound {100 * rep['michael_change']['lower']:+.1f}); floor {100 * GATE_FLOOR:+.0f} points: {'holds' if rep['holds'] else 'not shown'}")
    single = "single-use seeds" if rep["single_use"] else "search seeds, cannot promote"
    print(f"  {'PROMOTE' if rep['promote'] else 'do not promote'} ({single})")


def _meta(arm: str, out_dir: Path) -> dict[str, Any] | None:
    path = out_dir / f"{arm}.json"
    return json.loads(path.read_text())["spec"] if path.is_file() else None


def same_stream(base: dict[str, Any] | None, arm: dict[str, Any] | None) -> None:
    """Keyed and unkeyed runs of one seed share nothing after the first draw: refuse to pair them."""
    if base and arm and bool(base.get("keyed")) != bool(arm.get("keyed")):
        raise SystemExit("one arm is keyed and the other is not: their runs cannot be paired")


def claim_block(block: int, base: str, arm: str, out_dir: Path) -> None:
    """A promotion block is for one candidate only; any other arm asking for it is refused."""
    path = out_dir / "seed_blocks.json"
    used = json.loads(path.read_text()) if path.is_file() else {}
    old = used.get(str(block))
    if old is not None and old["arm"] != arm:
        raise SystemExit(f"block {block} was used for arm {old['arm']!r}: pick an unused block")
    if old is None:
        used[str(block)] = {"arm": arm, "base": base, "when": time.strftime("%Y-%m-%d %H:%M")}
        out_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(used, indent=1))


def gate(base: str, arm: str, s: dict[str, Any], *, block: int | None = None, first: int = SEARCH_SEED, delta: float = 0.2,
         searched: int = 1, max_blocks: int = 100, workers: int = 8, out_dir: Path = DEFAULT_DIR) -> dict[str, Any]:
    """Play both arms one block at a time until the sequential test and the win floor settle it."""
    base_spec = _meta(base, out_dir)
    if base_spec is None:
        raise SystemExit(f"no base arm {base!r}: create it first with run")
    same_stream(base_spec, s)
    if block is not None:
        claim_block(block, base, arm, out_dir)
        first = block_first_seed(block)
    single_use = block is not None
    rep: dict[str, Any] = {}
    for per in range(1, max_blocks + 1):
        run(base, base_spec, per=per, workers=workers, out_dir=out_dir, first=first)
        run(arm, s, per=per, workers=workers, out_dir=out_dir, first=first)
        wanted = set(seeds(per, first=first))
        rep = gate_report({k: r for k, r in load(out_dir / f"{base}.jsonl").items() if k in wanted},
                          {k: r for k, r in load(out_dir / f"{arm}.jsonl").items() if k in wanted},
                          delta=delta, searched=searched, single_use=single_use)
        print_gate(rep)
        seq = rep["sequential"]
        if seq["decision"] in ("reject", "cap"):
            break
        if seq["decision"] == "accept" and (rep["holds"] or len(wanted) >= seq["cap_n"]):
            break
    return rep


def summary(rows: dict) -> dict[str, Any]:
    rs = list(rows.values())
    n = len(rs)
    return {"runs": n, "wins": sum(r["won"] for r in rs), "mean_outcome": round(sum(r["outcome"] for r in rs) / max(1, n), 3),
            "michael_reached": sum(reached_michael(r) for r in rs), "michael_beaten": sum(beat_michael(r) for r in rs),
            "crashes": sum(bool(r.get("error")) for r in rs), "code": sorted({r.get("code", "?") for r in rs}),
            "cpu_hours": round(sum(r.get("secs", 0) for r in rs) / 3600, 1)}


def _filter(rows: dict, crowns, chars) -> dict:
    return {k: r for k, r in rows.items() if k[1] in crowns and k[0] in chars}


def _crowns(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split(","):
        lo, _, hi = part.partition("-")
        out += list(range(int(lo), int(hi or lo) + 1))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="paired benchmark on fixed held-out seeds")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("arm")
    g = sub.add_parser("gate")
    g.add_argument("base")
    g.add_argument("arm")
    g.add_argument("--block", type=int, default=None, help="single-use seed block (can promote)")
    g.add_argument("--delta", type=float, default=0.2, help="smallest gain worth accepting")
    g.add_argument("--searched", type=int, default=1, help="candidates searched before this one (reported)")
    for p in (r, g):
        p.add_argument("--cfg", default="{}", help="PowerConfig overrides as JSON")
        p.add_argument("--model", default="")
        p.add_argument("--threshold", type=float, default=None)
        p.add_argument("--char-tuning", default="")
        p.add_argument("--action-space", default="full", choices=("full", "advice"))
        p.add_argument("--keyed", action="store_true", help="key the random stream to the point of the run")
        p.add_argument("--salt", type=int, default=0, help="play other games on the same seeds")
        p.add_argument("--workers", type=int, default=8)
    r.add_argument("--first-seed", type=int, default=FIRST_SEED)
    g.add_argument("--first-seed", type=int, default=SEARCH_SEED)
    for p in (r, sub.add_parser("compare"), sub.add_parser("show")):
        p.add_argument("--per", type=int, default=6, help="seeds per character and crown")
        p.add_argument("--crowns", default="0-7")
        p.add_argument("--characters", default=",".join(CHARS))
    c, s = sub.choices["compare"], sub.choices["show"]
    c.add_argument("base")
    c.add_argument("arm")
    s.add_argument("arm")
    args = ap.parse_args(argv)
    crowns, chars = _crowns(args.crowns), args.characters.split(",")
    if args.cmd in ("run", "gate"):
        sp = spec(json.loads(args.cfg), args.model, args.threshold, args.char_tuning, args.action_space, args.keyed, args.salt)
        if args.cmd == "gate":
            gate(args.base, args.arm, sp, block=args.block, first=args.first_seed, delta=args.delta, searched=args.searched,
                 workers=args.workers, out_dir=args.dir)
            return 0
        run(args.arm, sp, per=args.per, crowns=crowns, chars=chars, workers=args.workers, out_dir=args.dir, first=args.first_seed)
        return 0
    if args.cmd == "show":
        print(json.dumps(summary(_filter(load(args.dir / f"{args.arm}.jsonl"), crowns, chars)), indent=1))
        return 0
    base = _filter(load(args.dir / f"{args.base}.jsonl"), crowns, chars)
    arm = _filter(load(args.dir / f"{args.arm}.jsonl"), crowns, chars)
    same_stream(_meta(args.base, args.dir), _meta(args.arm, args.dir))
    codes = ({r.get("code") for r in base.values()}, {r.get("code") for r in arm.values()})
    if codes[0] != codes[1] or len(codes[0]) > 1:
        print(f"warning: runs from different code (base {sorted(map(str, codes[0]))}, arm {sorted(map(str, codes[1]))});"
              " the difference may not be the arm's alone")
    print_report(compare(base, arm, per=args.per))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
