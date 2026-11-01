"""Paired benchmark on fixed held-out seeds (P5): one scoreboard for every policy change.

    python -m cursed_words_solver.sim.game.bench run <arm> [--cfg JSON] [--model PATH] [--threshold X]
        [--char-tuning PATH] [--action-space full|advice] [--per 6] [--crowns 0-7]
        [--characters A,B] [--workers 8]
    python -m cursed_words_solver.sim.game.bench compare <base arm> <arm> [--crowns ...] [--characters ...]
    python -m cursed_words_solver.sim.game.bench show <arm>

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
FIRST_SEED = 8_000_000
CHARS = ["BonesTheDog", "HayleyBayles", "NathaServo", "NinaNix", "Octacles", "PrismaticBean",
         "SamGambit", "SandySaguaro", "SockHead", "Spike", "WetDennis"]
SPEC_KEYS = ("cfg", "model", "threshold", "char_tuning", "action_space")


def seeds(per: int = 6, crowns=range(8), chars=CHARS) -> list[tuple[str, int, int]]:
    """(character, crown, seed) of the benchmark runs; the index ``i`` is ``seed % 100``."""
    return [(ch, cr, FIRST_SEED + 1000 * CHARS.index(ch) + 100 * cr + i)
            for i in range(per) for ch in chars for cr in crowns]


def code_fingerprint() -> str:
    """Short hash of every ``.py`` file in the package (what the runs were played with)."""
    root = Path(__file__).resolve().parents[2]
    h = hashlib.sha1()
    for f in sorted(root.rglob("*.py")):
        h.update(str(f.relative_to(root)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:10]


def spec(cfg: dict | None = None, model: str = "", threshold: float | None = None,
         char_tuning: str = "", action_space: str = "full") -> dict[str, Any]:
    return {"cfg": dict(cfg or {}), "model": model or "", "threshold": threshold,
            "char_tuning": char_tuning or "", "action_space": action_space}


# -- playing -------------------------------------------------------------------------


def _lead_cursed(g) -> int:
    lead = 0
    for e in g.events:
        if e.kind == "boss":
            if not e.data.get("cursed"):
                break
            lead += 1
    return lead


def job(j: dict[str, Any]) -> dict[str, Any]:
    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.agent import apply
    from cursed_words_solver.sim.game.features import outcome
    from cursed_words_solver.sim.game.policy import with_overrides

    t0 = time.time()
    s = j["spec"]
    g = E._game(j)
    pol = E.NetPolicy(E._CANDS, E._MODEL, seed=j["seed"], threshold=s["threshold"], boss_risk=str(E.BOSS_RISK_PATH),
                      char_tuning=s["char_tuning"], action_space=s["action_space"])
    if s["cfg"]:
        pol.cfg = with_overrides(pol.cfg, s["cfg"])
    error = ""
    try:
        for _ in range(5000):
            if g.phase == "done":
                break
            apply(g, pol.act(g))
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
        out_dir: Path = DEFAULT_DIR) -> Path:
    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.agent import spawn_pool

    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path, res_path = out_dir / f"{arm}.json", out_dir / f"{arm}.jsonl"
    if meta_path.is_file():
        old = json.loads(meta_path.read_text())["spec"]
        if {k: old.get(k) for k in SPEC_KEYS} != {k: s.get(k) for k in SPEC_KEYS}:
            raise SystemExit(f"arm {arm!r} exists with other settings {old}; pick another name")
    else:
        meta_path.write_text(json.dumps({"spec": s, "created": time.strftime("%Y-%m-%d %H:%M")}, indent=1))
    have = load(res_path)
    code = code_fingerprint()
    todo = [{"character": ch, "crown": cr, "seed": sd, "spec": s, "code": code}
            for ch, cr, sd in seeds(per, crowns, chars) if (ch, cr, sd) not in have]
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
    return {"n": n, "mean": round(m, 3), "t": round(m / se, 2) if se else 0.0,
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
        print(f"{label:14s} n {st['n']:3d}  {st['mean']:+.3f} (t {st['t']:+.2f})  wins {st['wins'][0]}->{st['wins'][1]}"
              f"  Michael reached {st['michael_reached'][0]}->{st['michael_reached'][1]}"
              f" beaten {st['michael_beaten'][0]}->{st['michael_beaten'][1]}  better {st['better']} worse {st['worse']}")


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
    r.add_argument("--cfg", default="{}", help="PowerConfig overrides as JSON")
    r.add_argument("--model", default="")
    r.add_argument("--threshold", type=float, default=None)
    r.add_argument("--char-tuning", default="")
    r.add_argument("--action-space", default="full", choices=("full", "advice"))
    r.add_argument("--workers", type=int, default=8)
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
    if args.cmd == "run":
        sp = spec(json.loads(args.cfg), args.model, args.threshold, args.char_tuning, args.action_space)
        run(args.arm, sp, per=args.per, crowns=crowns, chars=chars, workers=args.workers, out_dir=args.dir)
        return 0
    if args.cmd == "show":
        print(json.dumps(summary(_filter(load(args.dir / f"{args.arm}.jsonl"), crowns, chars)), indent=1))
        return 0
    base = _filter(load(args.dir / f"{args.base}.jsonl"), crowns, chars)
    arm = _filter(load(args.dir / f"{args.arm}.jsonl"), crowns, chars)
    codes = ({r.get("code") for r in base.values()}, {r.get("code") for r in arm.values()})
    if codes[0] != codes[1] or len(codes[0]) > 1:
        print(f"warning: runs from different code (base {sorted(map(str, codes[0]))}, arm {sorted(map(str, codes[1]))});"
              " the difference may not be the arm's alone")
    print_report(compare(base, arm, per=args.per))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
