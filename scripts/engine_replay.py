#!/usr/bin/env python3
"""Replay real game captures through the engine: score accuracy + path validity.

Each capture (round log or scoring-mismatch bundle) holds the board, loadout,
the path the player submitted and the score the game gave it. For every one:

- score: ``EnginePlan.score`` must equal the game's score;
- valid: the path must be legal movement that spells the submitted word.

Examples (repo root):

  python scripts/engine_replay.py                       # your round logs + mismatches + repo fixtures
  python scripts/engine_replay.py --since 20261001      # only recent captures
  python scripts/engine_replay.py path/to/capture.json  # specific files or directories
  python scripts/engine_replay.py --failures 20         # list the first 20 failures
  python scripts/engine_replay.py --write-lists         # regenerate tests/engine/engine_*_captures.txt
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"
EXACT_LIST = ROOT / "tests" / "engine" / "engine_exact_captures.txt"
VALID_LIST = ROOT / "tests" / "engine" / "engine_valid_captures.txt"


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "run_state_snapshot" in data and "run_state" not in data:  # mismatch bundle
        data = dict(data)
        data["run_state"] = data["run_state_snapshot"]
        data["actual"] = {"word": data.get("word", ""), "path": data.get("path", []), "score": data.get("actual_score")}
    return data


def replay_one(path_str: str) -> dict:
    """Score + validity for one capture (runs in a worker process)."""
    from cursed_words_solver.engine import EnginePlan
    from cursed_words_solver.engine.search import ExactSearch
    from cursed_words_solver.engine.solver import _moves_ok
    from cursed_words_solver.engine.trie import CsrTrie
    from cursed_words_solver.sim.replay import prepare_replay

    out: dict = {"file": path_str}
    try:
        data = _load(Path(path_str))
        out["match_status"] = data.get("match_status")
        prep, err = prepare_replay(data)
        if prep is None:
            out["score"] = out["valid"] = "skip"
            out["error"] = err
            return out
        plan = EnginePlan.build(prep.board, prep.loadout)
        path = list(prep.submission.path)
        if any(not (0 <= i < len(plan.grid.tiles)) for i in path) or len(set(path)) != len(path):
            out["score"] = out["valid"] = "bad_capture"
            return out
        if prep.expected is None:
            out["score"] = "skip"
        else:
            got = plan.score(path, prep.submission.effective_scoring_word).int_score
            got = -got if prep.two_wrongs else got
            out["got"], out["expected"] = got, prep.expected
            out["score"] = "ok" if got == prep.expected else "diff"
        # Two-word submits: ``actual.word`` holds only the last word; the capture has both.
        sub_words = ((data.get("capture") or {}).get("submission") or {}).get("words")
        words = ([str(w).lower() for w in sub_words] if sub_words else
                 str((data.get("actual") or {}).get("word") or "").lower().replace(";", " ").split())
        if not words or not all(w.isalpha() for w in words):
            out["valid"] = "skip"
        else:
            search = ExactSearch(plan, CsrTrie.from_words(words))
            tpath = tuple(path)
            if not _moves_ok(search, tpath):
                out["valid"] = "movement"
            elif not search.path_allowed(tpath):
                out["valid"] = "challenge"
            elif search.valid_word(tpath) is None:
                out["valid"] = "word"
            else:
                out["valid"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report and keep going
        out["score"] = out["valid"] = "error"
        out["error"] = repr(exc)[:200]
        out["traceback"] = traceback.format_exc()[-1200:]
    return out


def _collect(args: argparse.Namespace) -> list[Path]:
    from cursed_words_solver.config import ROUND_LOG_DIR, SCORING_MISMATCHES_DIR

    sources = [Path(p) for p in args.paths] or [
        ROUND_LOG_DIR, SCORING_MISMATCHES_DIR, FIXTURES / "round_logs", FIXTURES / "mismatches",
    ]
    files: list[Path] = []
    for src in sources:
        if src.is_dir():
            files.extend(sorted(p for p in src.glob("*.json") if p.name != "index.jsonl"))
        elif src.is_file():
            files.append(src)
    if args.since:
        files = [f for f in files if f.name[:8] >= args.since or not f.name[:8].isdigit()]
    return files


def _bucket(path: Path) -> str:
    where = "fixture" if FIXTURES in path.parents else "local"
    month = path.name[:6] if path.name[:6].isdigit() else "other"
    return f"{where}:{month}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="capture files or directories (default: all known)")
    parser.add_argument("--since", help="only captures named YYYYMMDD... on or after this date")
    parser.add_argument("--failures", type=int, default=10, help="failures to list (0 = none)")
    parser.add_argument("--jsonl", type=Path, help="write per-capture results here")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--write-lists", action="store_true", help="regenerate the engine_*_captures.txt test lists")
    args = parser.parse_args(argv)

    files = _collect(args)
    if not files:
        print("No captures found.")
        return 1
    t0 = time.time()
    with ProcessPoolExecutor(max(1, args.workers)) as pool:
        rows = list(pool.map(replay_one, [str(f) for f in files], chunksize=8))
    if args.jsonl:
        args.jsonl.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    by_bucket: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in rows:
        b = _bucket(Path(r["file"]))
        by_bucket[b][f"score:{r['score']}"] += 1
        by_bucket[b][f"valid:{r['valid']}"] += 1
    print(f"{len(rows)} captures in {time.time() - t0:.0f}s\n")
    print(f"{'bucket':<16} {'score ok':>9} {'diff':>6} {'valid ok':>9} {'invalid':>8} {'other':>6}")
    for b in sorted(by_bucket):
        c = by_bucket[b]
        invalid = c["valid:movement"] + c["valid:challenge"] + c["valid:word"]
        other = c["score:error"] + c["score:bad_capture"]
        print(f"{b:<16} {c['score:ok']:>9} {c['score:diff']:>6} {c['valid:ok']:>9} {invalid:>8} {other:>6}")

    failures = [r for r in rows if r["score"] in ("diff", "error") or r["valid"] in ("movement", "challenge", "word", "error")]
    if args.failures and failures:
        print(f"\nFailures ({len(failures)}; showing {min(args.failures, len(failures))}, newest first):")
        for r in sorted(failures, key=lambda r: Path(r["file"]).name, reverse=True)[: args.failures]:
            detail = r.get("error") or (f"got {r.get('got')} expected {r.get('expected')}" if r["score"] == "diff" else "")
            print(f"  {Path(r['file']).name}: score={r['score']} valid={r['valid']} {detail}")

    if args.write_lists:
        def rel(r: dict) -> str | None:
            p = Path(r["file"]).resolve()
            return p.relative_to(FIXTURES).as_posix() if FIXTURES in p.parents else None

        exact = sorted(x for r in rows if r["score"] == "ok" and (x := rel(r)))
        valid = sorted(x for r in rows if r["valid"] == "ok" and (x := rel(r)))
        EXACT_LIST.write_text(
            "# Repo captures the engine scores exactly (scripts/engine_replay.py --write-lists).\n"
            + "\n".join(exact) + "\n", encoding="utf-8")
        VALID_LIST.write_text(
            "# Captured submissions the engine accepts: legal movement + the submitted word spelled\n"
            "# under the game's Vocabulary rules (scripts/engine_replay.py --write-lists).\n"
            + "\n".join(valid) + "\n", encoding="utf-8")
        print(f"\nWrote {len(exact)} exact / {len(valid)} valid captures to tests/engine/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
