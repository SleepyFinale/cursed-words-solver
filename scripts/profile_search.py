#!/usr/bin/env python3
"""Profile search time: scoring (pipeline) vs board exploration (DFS/extension).

Uses built-in SearchTiming counters from WordSearcher.find_best_words.
Helps decide whether Tier-2 two-phase search (cheap rank, then full score
on finalists) is worth implementing.

Examples (from repo root):

  python scripts/profile_search.py
  python scripts/profile_search.py --run-state
  python scripts/profile_search.py tests/fixtures/mismatches/ayms_board_snapshot.json --budget 12
  python scripts/profile_search.py --latest 8 --budget 15
  python scripts/profile_search.py --round-logs --budget 45
  python scripts/profile_search.py --round-logs --mismatches-only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cursed_words_solver.config import (
    CONFIG_PATH,
    GAME_WORDLIST_PATH,
    RUN_STATE_PATH,
    ensure_wordlist,
)
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.encounter_board import effective_board_for_loadout
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import WordSearcher

DEFAULT_FIXTURES = [
    ROOT / "tests" / "fixtures" / "mismatches" / "20260525_172555.json",
    ROOT / "tests" / "fixtures" / "mismatches" / "ayms_board_snapshot.json",
    ROOT / "tests" / "fixtures" / "mismatches" / "20260526_231923.json",
]
ROUND_LOG_DIR = Path.home() / ".cursed_words_solver" / "round_logs"
ROUND_LOG_INDEX = ROUND_LOG_DIR / "index.jsonl"


@dataclass
class ProfileRow:
    label: str
    wall_sec: float
    score_sec: float
    score_pct: float
    score_calls: int
    expansions: int
    dfs_sec: float
    extend_sec: float
    seed_sec: float
    sticker_count: int
    best_word: str
    best_score: float
    tier2: str
    score_cache_hit_pct: float = 0.0
    chess_cache_hit_pct: float = 0.0
    board_flat_calls: int = 0
    trie_steps: int = 0
    trie_prunes: int = 0
    trie_fast_accepts: int = 0
    tier2_screen_skips: int = 0
    tier2_screen_calls: int = 0


def _load_from_mismatch(path: Path) -> tuple:
    from tests.regression.test_scoring_mismatches import _run_state_for_replay

    data = json.loads(path.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    if board is None:
        raise ValueError(f"No board in {path}")
    pipeline = ScoringPipeline()
    board = effective_board_for_loadout(board, loadout, pipeline.rules)
    return board, loadout, path.name


def _load_from_run_state(path: Path) -> tuple:
    data = json.loads(path.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    if board is None:
        raise ValueError(f"No board in {path}")
    pipeline = ScoringPipeline()
    board = effective_board_for_loadout(board, loadout, pipeline.rules)
    return board, loadout, path.name


def _load_from_round_log(path: Path) -> tuple:
    data = json.loads(path.read_text(encoding="utf-8"))
    run_state = data.get("run_state")
    if not isinstance(run_state, dict):
        raise ValueError("missing run_state")
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    if board is None:
        raise ValueError("no board in run_state")
    pipeline = ScoringPipeline()
    board = effective_board_for_loadout(board, loadout, pipeline.rules)
    status = str(data.get("match_status") or "?")
    rid = str(data.get("round_id") or path.stem)
    label = f"{rid[:17]} ({status})"
    return board, loadout, label


def _resolve_wordlist(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    if GAME_WORDLIST_PATH.exists() and GAME_WORDLIST_PATH.stat().st_size > 1024:
        return GAME_WORDLIST_PATH
    return ensure_wordlist()


def _timing_to_row(
    label: str,
    loadout,
    results,
    timing,
    *,
    elapsed: float,
) -> ProfileRow:
    sticker_count = len(loadout.stickers) + len(loadout.stamps)
    total_score = timing.score_sec + timing.final_score_sec
    score_pct = 100.0 * total_score / elapsed if elapsed > 0 else 0.0
    best_word = results[0].word if results else ""
    best_score = results[0].score if results else 0.0
    # Temporarily adjust timing score_pct basis for recommendation
    timing_copy_wall = timing.wall_sec or elapsed
    from cursed_words_solver.search import SearchTiming

    rec_timing = SearchTiming(
        wall_sec=timing_copy_wall,
        score_sec=total_score,
        score_calls=timing.score_calls,
    )
    tier2 = rec_timing.tier2_recommendation(sticker_count=sticker_count)

    def _hit_pct(hits: int, misses: int) -> float:
        total = hits + misses
        return 100.0 * hits / total if total else 0.0

    return ProfileRow(
        label=label,
        wall_sec=elapsed,
        score_sec=total_score,
        score_pct=score_pct,
        score_calls=timing.score_calls,
        expansions=timing.dfs_expansions,
        dfs_sec=timing.dfs_sec,
        extend_sec=timing.extend_sec,
        seed_sec=timing.seed_sec,
        sticker_count=sticker_count,
        best_word=best_word,
        best_score=best_score,
        tier2=tier2,
        score_cache_hit_pct=_hit_pct(
            timing.score_cache_hits, timing.score_cache_misses
        ),
        chess_cache_hit_pct=_hit_pct(
            timing.chess_attack_cache_hits, timing.chess_attack_cache_misses
        ),
        board_flat_calls=timing.board_flat_calls,
        trie_steps=timing.trie_steps,
        trie_prunes=timing.trie_prunes,
        trie_fast_accepts=timing.trie_fast_accepts,
        tier2_screen_skips=timing.tier2_screen_skips,
        tier2_screen_calls=timing.tier2_screen_calls,
    )


def _run_one(
    label: str,
    board,
    loadout,
    *,
    dictionary: WordDictionary,
    wordlist_path: Path,
    budget: float,
    workers: int | str,
    top_n: int,
) -> ProfileRow:
    from cursed_words_solver.search_parallel import resolve_search_workers

    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=1,
        max_len=25,
        time_budget=budget,
        wordlist_path=wordlist_path,
        search_workers=resolve_search_workers(workers),
    )
    t0 = time.perf_counter()
    results = searcher.find_best_words(board, loadout, top_n=top_n)
    elapsed = time.perf_counter() - t0
    timing = searcher.last_search_timing
    if timing is None:
        raise RuntimeError("SearchTiming missing after find_best_words")
    return _timing_to_row(label, loadout, results, timing, elapsed=elapsed)


def _print_table(rows: list[ProfileRow]) -> None:
    if not rows:
        print("No results.")
        return
    print(
        f"{'fixture':<28} {'wall':>6} {'score%':>7} {'calls':>7} {'expand':>8} "
        f"{'prune':>7} {'fast':>6} {'dfs':>6} {'extend':>6} {'stk':>4} "
        f"{'sc%':>5} {'ch%':>5} {'flat':>7} {'t2skip':>7} "
        f"{'best':>10}  tier-2"
    )
    print("-" * 120)
    for r in rows:
        print(
            f"{r.label:<28} {r.wall_sec:6.2f}s {r.score_pct:6.1f}% "
            f"{r.score_calls:7d} {r.expansions:8d} "
            f"{r.trie_prunes:7d} {r.trie_fast_accepts:6d} "
            f"{r.dfs_sec:5.2f}s {r.extend_sec:5.2f}s {r.sticker_count:4d} "
            f"{r.score_cache_hit_pct:4.0f}% {r.chess_cache_hit_pct:4.0f}% "
            f"{r.board_flat_calls:7d} {r.tier2_screen_skips:7d} "
            f"{r.best_word!r:>10} {r.best_score:,.0f}  {r.tier2}"
        )
    avg_score = sum(r.score_pct for r in rows) / len(rows)
    likely = sum(1 for r in rows if r.score_pct >= 55.0)
    maybe = sum(1 for r in rows if 40.0 <= r.score_pct < 55.0)
    unlikely = sum(1 for r in rows if r.score_pct < 40.0)
    avg_calls = sum(r.score_calls for r in rows) / len(rows)
    avg_expand = sum(r.expansions for r in rows) / len(rows)
    print()
    print(
        f"Summary: {len(rows)} board(s), avg score time {avg_score:.1f}% of wall, "
        f"{likely} likely / {maybe} maybe / {unlikely} unlikely Tier-2, "
        f"avg {avg_calls:,.0f} pipeline calls, avg {avg_expand:,.0f} DFS expansions."
    )
    print()
    print("Interpretation:")
    print("  score%  = time in score_total_only (+ final breakdown for top-N)")
    print("  expand  = DFS node visits (higher => more exploration work)")
    print("  prune   = trie prefix dead-end cuts; fast = cursor_is_word fast accepts")
    print("  sc%     = score cache hit rate; ch% = chess attack cache hit rate")
    print("  flat    = direct Board.flat property accesses (get_by_index uses tiles[row][col])")
    print("  Tier-2  = two-phase: cheap base+mult rank on all words, full pipeline on finalists only")


def _collect_fixture_paths(
    *,
    paths: list[Path],
    count: int,
    mismatches_dir: Path,
) -> list[Path]:
    if paths:
        return paths
    if count > 0 and mismatches_dir.is_dir():
        all_json = sorted(
            mismatches_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return all_json[:count]
    return [p for p in DEFAULT_FIXTURES if p.exists()]


def _collect_round_log_paths(
    *,
    mismatches_only: bool,
    max_rounds: int,
    sample_every: int,
) -> list[Path]:
    """Load round log JSON paths from index.jsonl (solver F8 rounds)."""
    if not ROUND_LOG_INDEX.is_file():
        raise SystemExit(f"Round log index not found: {ROUND_LOG_INDEX}")
    paths: list[Path] = []
    for line in ROUND_LOG_INDEX.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        status = str(entry.get("match_status") or "")
        if mismatches_only and status != "score_mismatch":
            continue
        file_path = Path(str(entry.get("file") or ""))
        if not file_path.is_file():
            alt = ROUND_LOG_DIR / (entry.get("round_id", "") + ".json")
            if alt.is_file():
                file_path = alt
            else:
                continue
        paths.append(file_path)
    if sample_every > 1:
        paths = paths[::sample_every]
    if max_rounds > 0:
        paths = paths[:max_rounds]
    return paths


def _default_budget_from_config(fallback: float) -> float:
    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return float(data.get("search_time_budget_sec", fallback))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return fallback


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Mismatch JSON or run_state JSON paths",
    )
    parser.add_argument(
        "--run-state",
        action="store_true",
        help=f"Profile {RUN_STATE_PATH} from melmod",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=0,
        metavar="N",
        help="Profile N newest tests/fixtures/mismatches/*.json",
    )
    parser.add_argument("--budget", type=float, default=12.0)
    parser.add_argument("--wordlist", type=Path, default=None)
    parser.add_argument("--workers", default="1")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--json", action="store_true", help="Emit JSON rows")
    parser.add_argument(
        "--round-logs",
        action="store_true",
        help="Profile boards from ~/.cursed_words_solver/round_logs/ (your play sessions)",
    )
    parser.add_argument(
        "--mismatches-only",
        action="store_true",
        help="With --round-logs: only score_mismatch rounds",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=0,
        metavar="N",
        help="Cap number of round logs to profile (0 = all)",
    )
    parser.add_argument(
        "--sample-every",
        type=int,
        default=1,
        metavar="K",
        help="With --round-logs: profile every Kth round (1 = all)",
    )
    parser.add_argument(
        "--use-config-budget",
        action="store_true",
        help="Use search_time_budget_sec from config.json instead of --budget",
    )
    args = parser.parse_args()

    budget = (
        _default_budget_from_config(args.budget)
        if args.use_config_budget
        else args.budget
    )

    paths: list[Path] = list(args.paths)
    if args.run_state:
        if not RUN_STATE_PATH.exists():
            raise SystemExit(f"run_state not found: {RUN_STATE_PATH}")
        paths = [RUN_STATE_PATH]
    elif args.round_logs:
        paths = _collect_round_log_paths(
            mismatches_only=args.mismatches_only,
            max_rounds=args.max_rounds,
            sample_every=max(1, args.sample_every),
        )
        print(
            f"Round logs: profiling {len(paths)} board(s) at {budget}s each "
            f"(from {ROUND_LOG_INDEX})",
            file=sys.stderr,
        )
    else:
        paths = _collect_fixture_paths(
            paths=paths,
            count=args.latest,
            mismatches_dir=ROOT / "tests" / "fixtures" / "mismatches",
        )
    if not paths:
        raise SystemExit("No fixtures found; pass paths or use --run-state")

    wl = _resolve_wordlist(args.wordlist)
    dictionary = WordDictionary(wl)
    rows: list[ProfileRow] = []

    for path in paths:
        if not path.exists():
            print(f"skip (missing): {path}", file=sys.stderr)
            continue
        try:
            if args.round_logs:
                board, loadout, label = _load_from_round_log(path)
            else:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if "run_state_snapshot" in raw:
                    board, loadout, label = _load_from_mismatch(path)
                elif isinstance(raw.get("board"), dict) and "tiles" in raw["board"]:
                    board, loadout, label = _load_from_run_state(path)
                elif isinstance(raw.get("run_state"), dict):
                    board, loadout, label = _load_from_round_log(path)
                else:
                    board, loadout, label = _load_from_mismatch(path)
        except Exception as exc:
            print(f"skip ({path.name}): {exc}", file=sys.stderr)
            continue
        print(f"Profiling {label} (budget={budget}s)...", file=sys.stderr)
        row = _run_one(
            label,
            board,
            loadout,
            dictionary=dictionary,
            wordlist_path=wl,
            budget=budget,
            workers=args.workers,
            top_n=args.top_n,
        )
        rows.append(row)

    if args.json:
        print(
            json.dumps(
                [
                    {
                        **r.__dict__,
                    }
                    for r in rows
                ],
                indent=2,
            )
        )
    else:
        _print_table(rows)


if __name__ == "__main__":
    main()
