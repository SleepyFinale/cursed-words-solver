"""Process-pool parallelization for fair-start DFS slices."""

from __future__ import annotations

import os
import sys
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cursed_words_solver.models import Board, Loadout

if TYPE_CHECKING:
    from cursed_words_solver.search import _CandidateHeap

_mp_dictionary = None
_mp_pipeline = None

_pool: ProcessPoolExecutor | None = None
_pool_key: tuple[str, int, str] | None = None
_pool_warm = False
_worker_errors: list[str] = []


def _trie_backend_from_env() -> str:
    return os.environ.get("CWS_TRIE_BACKEND", "auto")


def prebuild_shared_trie_cache(wordlist_path: Path, *, backend: str | None = None) -> None:
    """Build on-disk trie cache once so worker processes mmap-load instead of rebuilding."""
    from cursed_words_solver.dictionary import WordDictionary

    WordDictionary(
        wordlist_path,
        trie_backend=backend or _trie_backend_from_env(),
        use_trie_cache=True,
    )


def drain_parallel_worker_errors() -> list[str]:
    """Return and clear recent parallel worker error summaries (for terminal logging)."""
    global _worker_errors
    out = list(_worker_errors)
    _worker_errors.clear()
    return out


def resolve_search_workers(requested: int | str) -> int:
    """Map config value to worker count (1 = disabled)."""
    if requested == 1 or requested == "1":
        return 1
    if isinstance(requested, str) and requested.lower() == "auto":
        return max(1, min(os.cpu_count() or 1, 8))
    try:
        n = int(requested)
    except (TypeError, ValueError):
        return 1
    return max(1, min(n, 16))


def get_search_pool(
    wordlist_path: Path | None,
    workers: int,
) -> ProcessPoolExecutor | None:
    """Return a reused process pool (created once per wordlist + worker count)."""
    global _pool, _pool_key
    if workers <= 1 or wordlist_path is None:
        return None
    backend = _trie_backend_from_env()
    key = (str(wordlist_path), workers, backend)
    if _pool is None or _pool_key != key:
        shutdown_search_pool(wait=True)
        prebuild_shared_trie_cache(wordlist_path, backend=backend)
        _pool = ProcessPoolExecutor(
            max_workers=workers,
            initializer=_mp_init,
            initargs=(str(wordlist_path), backend),
        )
        _pool_key = key
        global _pool_warm
        _pool_warm = False
    return _pool


def is_search_pool_warm() -> bool:
    return _pool_warm


def warmup_search_pool(wordlist_path: Path | None, workers: int) -> float:
    """Spawn workers and load dictionary/pipeline once; returns warmup seconds."""
    pool = get_search_pool(wordlist_path, workers)
    if pool is None:
        return 0.0
    global _pool_warm
    if _pool_warm:
        return 0.0
    t0 = time.monotonic()
    list(pool.map(_mp_warmup, range(min(workers, 8))))
    _pool_warm = True
    return time.monotonic() - t0


def shutdown_search_pool(*, wait: bool = True) -> None:
    """Shut down the shared pool (app exit or tests)."""
    global _pool, _pool_key, _pool_warm
    if _pool is not None:
        _pool.shutdown(wait=wait, cancel_futures=not wait)
        _pool = None
        _pool_key = None
        _pool_warm = False


def _mp_warmup(_: int) -> int:
    if _mp_dictionary is None or _mp_pipeline is None:
        return 0
    return len(_mp_dictionary.words)


def _mp_init(wordlist_path: str, trie_backend: str = "auto") -> None:
    import signal

    # Parent handles Ctrl+C; ignore in workers to avoid shutdown traceback spam.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)

    global _mp_dictionary, _mp_pipeline
    from cursed_words_solver.dictionary import WordDictionary
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    _mp_dictionary = WordDictionary(
        Path(wordlist_path),
        trie_backend=trie_backend,
        use_trie_cache=True,
    )
    _mp_pipeline = ScoringPipeline()


def _mp_collect_chunk(payload: dict[str, Any]) -> list[tuple[float, str, tuple[int, ...]]]:
    from cursed_words_solver.graph_bitboard import build_board_graph_context
    from cursed_words_solver.mult_search import (
        build_mult_neighbor_hints,
        loadout_mult_rules,
    )
    from cursed_words_solver.search import WordSearcher, _CandidateHeap, _active_indices
    from cursed_words_solver.solve_context import build_solve_context

    if _mp_dictionary is None:
        raise RuntimeError("parallel search worker: dictionary not initialized")
    board: Board = payload["board"]
    loadout: Loadout = payload["loadout"]
    starts: list[int] = payload["starts"]
    budget_sec: float = float(payload["budget_sec"])
    pass_deadline: float = float(payload["pass_deadline"])
    max_len: int = payload["max_len"]
    min_len: int = payload["min_len"]
    heap_k: int = payload["heap_k"]
    digits_only: bool = payload["digits_only"]
    setup_weight: float = payload["setup_weight"]
    setup_discount: float = payload["setup_discount"]
    use_fast_rank: bool = payload["use_fast_rank"]
    use_tier2_screen: bool = payload["use_tier2_screen"]
    use_dfs_bb: bool = payload.get("use_dfs_bb", False)
    required_raw = payload.get("required_consumable_indices") or []

    now = time.monotonic()
    local_deadline = min(pass_deadline, now + budget_sec)
    budget_sec = max(0.0, local_deadline - now)
    if budget_sec <= 0 or not starts:
        return []
    searcher = WordSearcher(
        dictionary=_mp_dictionary,
        min_len=min_len,
        max_len=max_len,
        time_budget=budget_sec,
        setup_weight=setup_weight,
        setup_discount=setup_discount,
        use_fast_rank=use_fast_rank,
        use_tier2_screen=use_tier2_screen,
        use_dfs_bb=use_dfs_bb,
        search_workers=1,
    )
    if _mp_pipeline is not None:
        searcher.scoring = _mp_pipeline
    searcher.validator.required_consumable_indices = frozenset(
        int(idx) for idx in required_raw
    )
    active = _active_indices(board)
    searcher._mult_rules = loadout_mult_rules(
        loadout,
        searcher.scoring.rules,
        board=board,
        path=[active[0]] if active else [],
    )
    searcher._mult_hints = (
        build_mult_neighbor_hints(searcher._mult_rules)
        if searcher._mult_rules
        else None
    )
    searcher._solve_ctx = build_solve_context(loadout, searcher.scoring.rules)
    searcher._graph_ctx = build_board_graph_context(board)
    from cursed_words_solver.fingerprints import board_fingerprint
    from cursed_words_solver.rules.chess_tiles import clear_chess_attack_cache

    clear_chess_attack_cache(
        has_chess_pieces=searcher._graph_ctx.has_chess_pieces,
        board_fingerprint=(
            board_fingerprint(board) if searcher._graph_ctx.has_chess_pieces else None
        ),
    )
    mini = _CandidateHeap(heap_k)
    searcher._collect_words_fair_starts(
        board,
        loadout,
        mini,
        local_deadline,
        max_len,
        starts,
        digits_only=digits_only,
    )
    return mini.best_sorted()


def parallel_collect_fair_starts(
    *,
    executor: ProcessPoolExecutor,
    workers: int,
    board: Board,
    loadout: Loadout,
    candidates: Any,
    deadline: float,
    max_len: int,
    min_len: int,
    starts: list[int],
    digits_only: bool,
    setup_weight: float,
    setup_discount: float,
    use_fast_rank: bool,
    use_tier2_screen: bool,
    use_dfs_bb: bool = False,
    required_consumable_indices: frozenset[int] | None = None,
) -> None:
    """Run start slices on a reused process pool and merge into candidates."""
    if time.monotonic() >= deadline:
        return
    if workers <= 1 or len(starts) <= 1:
        return

    n = min(workers, len(starts))
    chunk_size = (len(starts) + n - 1) // n
    chunks = [starts[i : i + chunk_size] for i in range(0, len(starts), chunk_size)]
    remaining = max(0.0, deadline - time.monotonic())
    if remaining <= 0:
        return

    base_payload = {
        "board": board,
        "loadout": loadout,
        "budget_sec": remaining,
        "pass_deadline": deadline,
        "max_len": max_len,
        "min_len": min_len,
        "heap_k": candidates._k,
        "digits_only": digits_only,
        "setup_weight": setup_weight,
        "setup_discount": setup_discount,
        "use_fast_rank": use_fast_rank,
        "use_tier2_screen": use_tier2_screen,
        "use_dfs_bb": use_dfs_bb,
        "required_consumable_indices": sorted(required_consumable_indices or ()),
    }
    payloads = [{**base_payload, "starts": chunk} for chunk in chunks]

    # Grace for process IPC / teardown (workers honor pass_deadline internally).
    collect_timeout = remaining + min(5.0, max(1.0, remaining * 0.15))
    collect_end = time.monotonic() + collect_timeout
    futures = [executor.submit(_mp_collect_chunk, p) for p in payloads]
    pending = set(futures)
    while pending and time.monotonic() < collect_end:
        wait_sec = max(0.01, collect_end - time.monotonic())
        done, pending = wait(pending, timeout=wait_sec, return_when=FIRST_COMPLETED)
        for fut in done:
            try:
                entries = fut.result()
            except Exception as exc:
                global _worker_errors
                if len(_worker_errors) < 3:
                    _worker_errors.append(f"{type(exc).__name__}: {exc}")
                    traceback.print_exc(file=sys.stderr)
                continue
            for score, word, path in entries:
                candidates.consider(score, word, list(path))
    for fut in pending:
        fut.cancel()
