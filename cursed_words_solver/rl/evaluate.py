"""Evaluate a policy on a fixed seed set; results are cached per run (resumable) and
compared paired (same character / crown / quest / seed) against another arm.

    python -m cursed_words_solver.rl.evaluate run --arm bc1 --policy ~/.cursed_words_solver/rl/bc/best.pt
    python -m cursed_words_solver.rl.evaluate run --arm teacher --policy teacher
    python -m cursed_words_solver.rl.evaluate compare bc1 teacher
    python -m cursed_words_solver.rl.evaluate run --arm cond --policy ~/.cursed_words_solver/rl/ppo2/champion.pt --targets own
    python -m cursed_words_solver.rl.evaluate targets cond                 # win tables by build target
    python -m cursed_words_solver.rl.evaluate pick cond --out ~/.cursed_words_solver/rl/target_table.json
    (or a ppo gate cache: pick ~/.cursed_words_solver/rl/ppo2/eval/champion_u<N>.jsonl, see champion_eval_path)
    python -m cursed_words_solver.rl.evaluate run --arm champ_br6 --policy ~/.cursed_words_solver/rl/ppo2/champion.pt --boss-rule 6
    python -m cursed_words_solver.rl.evaluate table --set SockHead:5-7=Curse --set SamGambit:5-7=Curse --out deploy.json
    python -m cursed_words_solver.rl.evaluate run --arm champ_deploy --policy ~/.cursed_words_solver/rl/ppo2/champion.pt --target-table deploy.json --boss-rule 6

ARM is a name in rl/eval (``<arm>.jsonl``) or a path to a .jsonl of eval rows. Rows carry a
build ``target`` ("" = FREE); ``key`` includes it, so rows from before targets match FREE jobs.
Pivot runs (``--targets free,pivot:2,pivot:3``: start FREE, from stage S re-read the build at
each shop entry, ``targets.pivot_update``) carry ``pivot_stage``; their row ``target`` is the
FINAL target, so ``key`` uses (FREE, pivot_stage) for them and reports group them as the arm
"pivot:S" (``arm_of``), paired vs the FREE row of the same seed.

``--boss-rule N`` (``rules``: at crown >= N a cursed boss pick becomes an uncursed option) is
stored in the rows (``boss_rule``) and is part of the run cache key (``cache_key``) but not of
the pairing ``key``, so a boss-rule arm pairs with a plain arm on the same seeds. Use a separate
arm name per setting (``compare`` / ``targets`` read every row of the file).
``--target-table PATH`` gives every job the target the live assistant would choose from that
table (``targets.table_target``; quest runs FREE, as the assistant); format: ``targets``.

Seed sets: ``main`` = 11 characters Ã— crowns 0-7 Ã— ``--per`` seeds (block 40,000,000) plus
26 quests Ã— ``--per-quest``. ``fresh<K>`` = a different block for confirmation.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from cursed_words_solver.rl import store
from cursed_words_solver.rl.teacher import CHARS

EVAL_HOME = store.RL_HOME / "eval"


# playable crowns: GameStatics.HighestCrownAvailable = 7. AscensionLevel 8 (HarderBosses: every boss
# at the next floor's strength) exists in code only, so no run is ever played or scored there.
CROWNS = range(8)


def eval_jobs(per: int = 3, per_quest: int = 1, block: int = 0, crowns=CROWNS, targets=None) -> list[dict[str, Any]]:
    """``targets``: None = no target key (FREE, the old job list); "own" = every job once FREE and
    once per ``targets.THEMES`` build of its character; a list = every job once per listed target
    ("pivot:S" = a pivot run from stage S).
    Crossed jobs keep their seed, so the targets of one seed are paired with each other."""
    from cursed_words_solver.sim.game.challenges import QUESTS

    base = 40_000_000 + 1_000_000 * block
    out = []
    for ci, ch in enumerate(CHARS):
        for cr in crowns:
            for i in range(per):
                out.append({"character": ch, "crown": cr, "quest": None, "seed": base + 10_000 * ci + 100 * cr + i})
    for qi, q in enumerate(sorted(QUESTS)):
        for i in range(per_quest):
            ch = CHARS[(qi + i) % len(CHARS)]
            out.append({"character": ch, "crown": 0, "quest": q, "seed": base + 500_000 + 100 * qi + i})
    return out if targets is None else cross_targets(out, targets)


def cross_targets(jobs: list[dict], targets) -> list[dict[str, Any]]:
    """Each job once per target (``"own"`` = FREE + the character's THEMES; "pivot:S" = FREE
    start + ``pivot_stage`` S; pivot runs only for non-quest jobs), same seed."""
    from cursed_words_solver.rl.targets import FREE, THEMES, canonical, parse_pivot_label

    out = []
    for j in jobs:
        ts = (FREE, *THEMES.get(j["character"], ())) if targets == "own" else targets
        for t in ts:
            ps = parse_pivot_label(t) if t else None
            if ps is not None:
                if not j.get("quest"):
                    out.append({**j, "target": FREE, "pivot_stage": ps})
            else:
                out.append({**j, "target": canonical(t) if t else FREE})
    return out


def themed_gate_jobs() -> list[dict[str, Any]]:
    """Build-target gate block: 11 characters x 8 crowns x 1 seed (the first seed of each gate
    slice, block 1) x each of the character's ``targets.THEMES`` (144 runs). Their FREE twins are
    the first-seed rows of ``gate_jobs``, so themed rows pair with FREE ones on the same seed."""
    from cursed_words_solver.rl.targets import THEMES

    return [{**j, "target": t} for j in eval_jobs(per=1, per_quest=0, block=1) for t in THEMES.get(j["character"], ())]


def key(r: dict) -> tuple:
    """Pairing key: character, crown, quest, seed, build target ("" = FREE; old rows lack it),
    pivot stage (0 = not a pivot run; a pivot run's key target is FREE, its start)."""
    ps = int(r.get("pivot_stage") or 0)
    return (r["character"], r["crown"], r.get("quest") or "", r["seed"], "" if ps else (r.get("target") or ""), ps)


def cache_key(r: dict) -> tuple:
    """``run_arm`` cache key: ``key`` plus the boss rule (0 = off), so rows played with another
    boss rule are not reused."""
    from cursed_words_solver.rl.rules import parse_boss_rule

    return (*key(r), parse_boss_rule(r.get("boss_rule")))


def load_table(path) -> dict:
    """A target table file (``targets`` documents the format)."""
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("table", {}), dict):
        raise ValueError(f"{path}: not a target table ({{'version': 1, 'table': {{character: {{band: target}}}}}})")
    return data


def table_jobs(jobs: list[dict], data: dict) -> list[dict[str, Any]]:
    """Each job with the target the assistant picks from target table ``data``
    (``targets.table_target``): a plan, FREE, or a pivot run ("pivot:S" -> FREE start +
    ``pivot_stage``). Quest jobs are FREE (the assistant plays quests FREE)."""
    from cursed_words_solver.rl.targets import FREE, parse_pivot_label, table_target

    out = []
    for j in jobs:
        j = {k: v for k, v in j.items() if k not in ("target", "pivot_stage")}
        t = FREE if j.get("quest") else table_target(data, j["character"], j["crown"])
        ps = parse_pivot_label(t) if t else None
        out.append({**j, "target": FREE, "pivot_stage": ps} if ps is not None else {**j, "target": t})
    return out


def parse_set(spec: str) -> tuple[str, str, str]:
    """``"SockHead:4-7=Curse"`` -> (character, crown key, target); the crown key may be "lo-hi",
    one crown "5", or "all" (= "0-7"); the target a plan ("Red+Blue" / "Red-Blue"), "free", or
    "pivot:S". Validated."""
    from cursed_words_solver.rl.targets import canonical, parse_pivot_label, pivot_label

    try:
        left, target = spec.split("=", 1)
        ch, band = left.split(":", 1)
    except ValueError:
        raise ValueError(f"--set {spec!r}: expected CHARACTER:CROWNS=TARGET, e.g. SockHead:4-7=Curse") from None
    ch, band, target = ch.strip(), band.strip().lower(), target.strip()
    if ch not in CHARS:
        raise ValueError(f"--set {spec!r}: unknown character {ch!r}; known: {', '.join(CHARS)}")
    band = "0-7" if band == "all" else band
    lo, sep, hi = band.partition("-")
    if not (lo.isdigit() and (not sep or hi.isdigit())) or (sep and int(lo) > int(hi)):
        raise ValueError(f"--set {spec!r}: crowns must be 'lo-hi', one crown or 'all'")
    if target.lower() in ("", "free", "none"):
        return ch, band, ""
    ps = parse_pivot_label(target)
    if ps is not None:
        return ch, band, pivot_label(ps)
    try:
        return ch, band, canonical(target.replace("-", "+"))
    except ValueError as exc:
        raise ValueError(f"--set {spec!r}: {exc}") from None


def make_table(sets: list[str], base: dict | None = None, source: str = "rules") -> dict:
    """A target table (``targets`` format) from ``--set`` rules, on top of ``base`` (a loaded
    table) if given. The assistant takes the FIRST key matching the crown, so each rule's key
    is (re)inserted at the front of its character's row: a rule wins over the base table's
    overlapping bands (e.g. --set SockHead:5-7=Curse over a 'pick' "4-7"), and a later rule
    wins over an earlier one where they overlap."""
    tab = {ch: dict(row) for ch, row in ((base or {}).get("table") or {}).items()}
    for spec in sets:
        ch, band, t = parse_set(spec)
        row = tab.get(ch) or {}
        tab[ch] = {band: t, **{k: v for k, v in row.items() if k != band}}
    return {"version": 1, "source": source, "table": tab}


def arm_of(r: dict) -> str:
    """The row's target arm for reports / the target table: its target ("" = FREE), or
    "pivot:S" for a pivot run."""
    from cursed_words_solver.rl.targets import pivot_label

    ps = int(r.get("pivot_stage") or 0)
    return pivot_label(ps) if ps else (r.get("target") or "")


def arm_display(arm: str) -> str:
    """"Free", "Red + Blue", "Pivot from stage 2"."""
    from cursed_words_solver.rl.targets import display, parse_pivot_label

    ps = parse_pivot_label(arm) if arm else None
    return f"Pivot from stage {ps}" if ps is not None else display(arm)


def run_arm(arm: str, policy: str, jobs: list[dict], workers: int = 7, *, greedy: bool = True, search=None,
            out_dir: Path = EVAL_HOME, pool=None, verbose: bool = True, boss_rule: int = 0) -> list[dict]:
    """Play the jobs not cached in ``<out_dir>/<arm>.jsonl`` (by ``cache_key``) and return the
    rows of ``jobs``. ``boss_rule``: crown threshold of the uncursed-boss rule (0 = off; a
    job's own "boss_rule" wins)."""
    from cursed_words_solver.rl.rules import parse_boss_rule

    br = parse_boss_rule(boss_rule)
    if br:
        jobs = [j if "boss_rule" in j else {**j, "boss_rule": br} for j in jobs]
    path = Path(out_dir) / f"{arm}.jsonl"
    done = {cache_key(r): r for r in store.read_jsonl(path) if not r.get("error")}
    todo = [j for j in jobs if cache_key(j) not in done]
    if todo:
        from cursed_words_solver.rl.play import init_worker, play
        from cursed_words_solver.sim.game.agent import spawn_pool

        own = pool is None
        pool = pool or spawn_pool(workers, init_worker, ())
        t0 = time.time()
        try:
            for n, r in enumerate(pool.imap_unordered(play, [{**j, "policy": policy, "greedy": greedy, "search": search} for j in todo]), 1):
                r.pop("traj", None)
                store.append_jsonl(path, r)
                if not r.get("error"):
                    done[cache_key(r)] = r
                elif verbose:
                    print("ERROR", r["error"], r.get("trace", "")[-300:], flush=True)
                if verbose and n % 25 == 0:
                    print(f"[{arm}] {n}/{len(todo)} {n / (time.time() - t0) * 3600:.0f} runs/h", flush=True)
        finally:
            if own:
                pool.terminate()
    return [done[cache_key(j)] for j in jobs if cache_key(j) in done]


# the game's Michael bonus (sim.game.features.MICHAEL_BONUS): eval rows' "outcome" carries it (win 16,
# Michael win 24); a PPO trained with another bonus (rl.ppo --michael-bonus) compares by row_outcome
from cursed_words_solver.sim.game.features import MICHAEL_BONUS  # noqa: E402


def row_outcome(r: dict, michael_bonus: float = MICHAEL_BONUS) -> float:
    """The row's outcome with a Michael win worth 16 + ``michael_bonus`` instead of the recorded
    16 + MICHAEL_BONUS (= ``r["outcome"]`` when ``michael_bonus`` is MICHAEL_BONUS)."""
    o = float(r["outcome"])
    if michael_bonus != MICHAEL_BONUS and r.get("won") and r.get("reason") == "michael":
        o -= MICHAEL_BONUS - float(michael_bonus)
    return o


def summarize(rows: list[dict], michael_bonus: float = MICHAEL_BONUS) -> dict:
    """``michael_bonus`` other than MICHAEL_BONUS adds ``train_outcome`` (mean ``row_outcome``);
    ``outcome`` stays the true game outcome."""
    n = len(rows)
    if not n:
        return {"n": 0}
    wins = sum(bool(r["won"]) for r in rows)
    mich = sum(r.get("reason") == "michael" for r in rows)
    out = sum(r["outcome"] for r in rows) / n
    res = {"n": n, "wins": wins, "win_rate": round(wins / n, 4), "michael_wins": mich, "outcome": round(out, 3)}
    if michael_bonus != MICHAEL_BONUS:
        res["train_outcome"] = round(sum(row_outcome(r, michael_bonus) for r in rows) / n, 3)
    return res


def paired(a: list[dict], b: list[dict], michael_bonus: float = MICHAEL_BONUS) -> dict:
    """Paired a - b by ``key``. ``outcome_diff`` / ``t`` compare ``row_outcome(r, michael_bonus)``
    (the default: the recorded outcome); a ``michael_bonus`` other than MICHAEL_BONUS is echoed
    in the result."""
    bk = {key(r): r for r in b}
    pairs = [(r, bk[key(r)]) for r in a if key(r) in bk]
    if not pairs:
        return {"n": 0}
    d = [row_outcome(x, michael_bonus) - row_outcome(y, michael_bonus) for x, y in pairs]
    n = len(d)
    mean = sum(d) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in d) / max(1, n - 1))
    only_a = sum(bool(x["won"]) and not bool(y["won"]) for x, y in pairs)
    only_b = sum(bool(y["won"]) and not bool(x["won"]) for x, y in pairs)
    wa = sum(bool(x["won"]) for x, _ in pairs)
    wb = sum(bool(y["won"]) for _, y in pairs)
    disc = only_a + only_b
    # win-rate difference with McNemar-style SE
    se_w = math.sqrt(max(1, disc)) / n
    res = {"n": n, "wins_a": wa, "wins_b": wb, "win_diff": round((wa - wb) / n, 4),
           "win_diff_lb90": round((wa - wb) / n - 1.645 * se_w, 4), "only_a": only_a, "only_b": only_b,
           "win_z": round((only_a - only_b) / math.sqrt(disc), 2) if disc else 0.0,
           "outcome_diff": round(mean, 3), "t": round(mean / (sd / math.sqrt(n)) if sd > 0 else 0.0, 2)}
    if michael_bonus != MICHAEL_BONUS:
        res["michael_bonus"] = float(michael_bonus)
    return res


# PPO gate: block 1, 4 seeds per character x crown + 2 per quest = 404 runs. eval_jobs seeds are
# prefix-stable in per / per_quest, so the earlier 202-run gate (2 / 1) rows are reused.
GATE_PER, GATE_PER_QUEST = 4, 2


def gate_jobs(per: int = GATE_PER, per_quest: int = GATE_PER_QUEST) -> list[dict[str, Any]]:
    return eval_jobs(per=per, per_quest=per_quest, block=1)


def promote_ok(cmp: dict, min_z: float = 1.0) -> bool:
    """Candidate beats the champion paired: more wins and more outcome, and at least one of the
    two differences is >= ``min_z`` standard errors (outcome t, or win z = win_diff / (sqrt(disc) / n)).
    The outcome is whatever ``paired`` compared: rl.ppo passes its training ``michael_bonus``, so a
    Michael win counts what training values it at (unchanged at the game's 8)."""
    if not cmp.get("n"):
        return False
    return cmp["win_diff"] > 0 and cmp["outcome_diff"] > 0 and max(cmp["t"], cmp.get("win_z", 0.0)) >= min_z


def _field(r: dict, by: str):
    if by == "quest":
        return r.get("quest") or "-"
    if by == "target":
        return arm_of(r)
    if by == "band":
        return crown_band(r["crown"])
    return r[by]


def table(rows: list[dict], by) -> dict:
    """Summary per value of ``by`` (a field, or a tuple of fields -> tuple keys). Fields: any row
    key, "quest" ("-" = none), "target" ("" = FREE), "band" (crowns "0-3" / "4-7")."""
    groups: dict = {}
    for r in rows:
        k = tuple(_field(r, b) for b in by) if isinstance(by, tuple) else _field(r, by)
        groups.setdefault(k, []).append(r)
    return {k: summarize(v) for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))}


# ------------------------------------------------------------------ build targets

BANDS = ("0-3", "4-7")


def crown_band(crown: int) -> str:
    return BANDS[0] if int(crown) <= 3 else BANDS[1]


def vs_free(rows: list[dict], by=()) -> dict:
    """``paired`` per (group..., target) for every non-FREE target: a = the target's rows, b = the
    FREE rows of the same character / crown / quest / seed. ``by``: fields to split on (``table``)."""
    by = tuple(by) if isinstance(by, (tuple, list)) else (by,)
    free = {key(r)[:4]: r for r in rows if not arm_of(r)}
    groups: dict = {}
    for r in rows:
        t = arm_of(r)
        if t and key(r)[:4] in free:
            groups.setdefault((*(_field(r, b) for b in by), t), []).append(r)
    out = {}
    for k, rs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        out[k] = paired(rs, [{**free[key(r)[:4]], "target": r.get("target"), "pivot_stage": r.get("pivot_stage", 0)}
                             for r in rs])
    return out


def pick_ok(cmp: dict, min_z: float = 1.0) -> bool:
    """A target beats FREE: more paired wins with win_z >= ``min_z``, and outcome_diff > 0."""
    return bool(cmp.get("n")) and cmp["win_diff"] > 0 and cmp.get("win_z", 0.0) >= min_z and cmp["outcome_diff"] > 0


def _best(cmps: dict, min_z: float) -> str | None:
    ok = [(c["win_diff"], c["outcome_diff"], t) for t, c in cmps.items() if pick_ok(c, min_z)]
    return max(ok)[2] if ok else None


def pick_table(rows: list[dict], min_z: float = 1.0) -> dict[str, dict[str, str]]:
    """Per character (non-quest rows): the target arm t != FREE (a plan, or "pivot:S" when pivot
    rows are present) with the largest paired win_diff vs
    FREE among those passing ``pick_ok``, else FREE (""). Each crown band (0-3, 4-7) gets the
    pick on its own rows if one passes; otherwise the all-crowns pick, but only if it does not
    lose to FREE on that band's rows (win_diff >= 0 and outcome_diff >= 0), else FREE. Every
    character gets both bands."""
    from cursed_words_solver.rl.teacher import CHARS

    rows = [r for r in rows if not r.get("error") and not r.get("quest") and r["crown"] in CROWNS]
    out = {}
    for ch in CHARS:
        mine = [r for r in rows if r["character"] == ch]
        overall = _best({k[-1]: v for k, v in vs_free(mine).items()}, min_z) or ""
        out[ch] = {}
        for b in BANDS:
            cmps = {k[-1]: v for k, v in vs_free([r for r in mine if crown_band(r["crown"]) == b]).items()}
            own = _best(cmps, min_z)
            if own:
                out[ch][b] = own
            else:
                c = cmps.get(overall, {})
                ok = bool(overall) and (not c.get("n") or (c["win_diff"] >= 0 and c["outcome_diff"] >= 0))
                out[ch][b] = overall if ok else ""
    return out


def load_rows(arm: str) -> list[dict]:
    """Rows of an arm name in rl/eval, or of a .jsonl path."""
    p = Path(arm).expanduser()
    if not (arm.endswith(".jsonl") or p.is_file()):
        p = EVAL_HOME / f"{arm}.jsonl"
    return [x for x in store.read_jsonl(p) if not x.get("error") and x["crown"] in CROWNS]


def champion_eval_path(ppo_dir) -> Path | None:
    """``<ppo_dir>/eval/champion_u{cu}.jsonl`` of the current champion (the last gate row names it:
    its update when it promoted, else its champion_update), else the highest champion_u*.jsonl."""
    ppo_dir = Path(ppo_dir).expanduser()
    gates = store.read_jsonl(ppo_dir / "gates.jsonl")
    if gates:
        g = gates[-1]
        p = ppo_dir / "eval" / f"champion_u{g['update'] if g.get('promoted') else g['champion_update']}.jsonl"
        if p.is_file():
            return p
    cands = []
    for f in (ppo_dir / "eval").glob("champion_u*.jsonl"):
        try:
            cands.append((int(f.stem[len("champion_u"):]), f))
        except ValueError:
            pass
    return max(cands)[1] if cands else None


def _fmt(s: dict) -> str:
    return f"n={s['n']:4d} win={s.get('win_rate', 0):.3f} out={s.get('outcome', 0):6.2f}" if s.get("n") else "n=0"


def _fmt_d(c: dict) -> str:
    return (f"vs FREE n={c['n']:4d} win_diff={c['win_diff']:+.3f} win_z={c['win_z']:+.2f} "
            f"out_diff={c['outcome_diff']:+.2f} t={c['t']:+.2f}") if c.get("n") else ""


def print_targets(rows: list[dict]) -> None:
    display = arm_display
    print("== by target")
    d = vs_free(rows)
    for t, s in table(rows, "target").items():
        print(f"  {display(t):28s} {_fmt(s)}  {_fmt_d(d.get((t,), {}))}")
    for by in ("character", "crown"):
        print(f"== {by} x target")
        d = vs_free(rows, by)
        for k, s in table(rows, (by, "target")).items():
            print(f"  {str(k[0]) + ' | ' + display(k[1]):40s} {_fmt(s)}  {_fmt_d(d.get(k, {}))}")


def pivot_report(rows: list[dict]) -> list[str]:
    """Lines per pivot arm: final-target shares and mean switches."""
    from cursed_words_solver.rl.targets import display

    out = []
    for arm in sorted({arm_of(r) for r in rows if r.get("pivot_stage")}):
        rs = [r for r in rows if arm_of(r) == arm]
        groups: dict[str, list[dict]] = {}
        for r in rs:
            groups.setdefault(r.get("target") or "", []).append(r)
        sw = sum(r.get("pivot_switches", len(r.get("targets_seen") or ())) for r in rs) / len(rs)
        out.append(f"{arm_display(arm)}: n={len(rs)} mean switches {sw:.2f}")
        for t, v in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            out.append(f"   ends {display(t):20s} {_fmt(summarize(v))}")
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--arm", required=True)
    r.add_argument("--policy", required=True, help="'teacher' or a policy .pt file")
    r.add_argument("--per", type=int, default=3)
    r.add_argument("--per-quest", type=int, default=1)
    r.add_argument("--block", type=int, default=0)
    r.add_argument("--workers", type=int, default=7)
    r.add_argument("--sample", action="store_true", help="sample actions instead of greedy")
    r.add_argument("--search", default="", help="decision-time look-ahead: JSON SearchConfig, e.g. '{}' or '{\"sims\": 2}'")
    r.add_argument("--targets", default="", help="build targets per job: 'own' (FREE + the character's themes) "
                   "or a comma list ('free,Cards,Red+Blue,pivot:2'; pivot:S = start FREE, pivot from stage S); "
                   "default: FREE only")
    r.add_argument("--target-table", default="", help="per job the target the live assistant would pick from this "
                   "target_table.json (FREE where it has no entry; quests FREE); replaces --targets")
    r.add_argument("--boss-rule", type=int, default=0, help="crown N: at crown >= N take an uncursed boss over a "
                   "cursed pick (after policy / search); 0 = off")
    r.add_argument("--out-dir", default=str(EVAL_HOME), help="where <arm>.jsonl is cached")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    s = sub.add_parser("show")
    s.add_argument("arm")
    t = sub.add_parser("targets", help="win tables by build target, paired vs FREE")
    t.add_argument("arm")
    pk = sub.add_parser("pick", help="per character (and crown band) build target to use, from paired wins vs FREE")
    pk.add_argument("arm")
    pk.add_argument("--out", default=str(store.RL_HOME / "target_table.json"))
    pk.add_argument("--min-z", type=float, default=1.0)
    tb = sub.add_parser("table", help="write a target table from rules (the format the assistant reads)")
    tb.add_argument("--set", action="append", default=[], metavar="CHAR:CROWNS=TARGET",
                    help="e.g. SockHead:4-7=Curse, SamGambit:5-7=Curse, NinaNix:all=pivot:2, Spike:6=free (repeatable)")
    tb.add_argument("--base", default="", help="start from this table (e.g. a 'pick' output) instead of empty")
    tb.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    EVAL_HOME.mkdir(parents=True, exist_ok=True)
    if args.cmd == "run":
        pol = args.policy if args.policy == "teacher" else str(Path(args.policy).expanduser())
        tg = None
        if args.targets.strip():
            tg = "own" if args.targets.strip().lower() == "own" else \
                ["" if t.strip().lower() == "free" else t.strip() for t in args.targets.split(",")]
        out_dir = Path(args.out_dir).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.target_table and tg is not None:
            ap.error("--target-table and --targets are exclusive")
        jobs = eval_jobs(args.per, args.per_quest, args.block, targets=tg)
        if args.target_table:
            jobs = table_jobs(jobs, load_table(args.target_table))
        rows = run_arm(args.arm, pol, jobs, args.workers, greedy=not args.sample,
                       search=json.loads(args.search) if args.search else None, out_dir=out_dir,
                       boss_rule=args.boss_rule)
        print(summarize(rows))
    elif args.cmd == "targets":
        print_targets(load_rows(args.arm))
        pv = pivot_report(load_rows(args.arm))
        if pv:
            print("== pivot runs: final target")
            for line in pv:
                print("  " + line)
    elif args.cmd == "pick":
        tab = pick_table(load_rows(args.arm), args.min_z)
        store.atomic_write_json(Path(args.out).expanduser(), {"version": 1, "source": args.arm, "table": tab})
        print(json.dumps(tab, indent=1))
    elif args.cmd == "table":
        try:
            data = make_table(args.set, load_table(args.base) if args.base else None,
                              source=" ".join(f"--set {x}" for x in args.set) or "rules")
        except ValueError as exc:
            ap.error(str(exc))
        store.atomic_write_json(Path(args.out).expanduser(), data)
        print(json.dumps(data, indent=1))
    elif args.cmd == "compare":
        a = store.read_jsonl(EVAL_HOME / f"{args.a}.jsonl")
        b = store.read_jsonl(EVAL_HOME / f"{args.b}.jsonl")
        a = [x for x in a if not x.get("error") and x["crown"] in CROWNS]
        b = [x for x in b if not x.get("error") and x["crown"] in CROWNS]
        print("A", summarize(a), "\nB", summarize(b), "\npaired", paired(a, b))
    else:
        rows = [x for x in store.read_jsonl(EVAL_HOME / f"{args.arm}.jsonl")
                if not x.get("error") and x["crown"] in CROWNS]
        print(summarize(rows))
        for by in ("crown", "character", "quest"):
            print(by, table(rows, by))


if __name__ == "__main__":
    main()
