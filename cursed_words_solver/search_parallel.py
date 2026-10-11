"""Process pool for the exact search: each worker holds the dictionary and
searches a share of the start tiles (``engine/solver.py:_mp_exact_task``)."""

from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

_mp_dictionary = None

_pool: ProcessPoolExecutor | None = None
_pool_key: tuple[str, int] | None = None
_pool_warm = False
_pool_shutdown_requested = False


def prebuild_shared_trie_cache(wordlist_path: Path) -> None:
    """Build the engine trie's disk cache once so workers load it instead of rebuilding."""
    from cursed_words_solver.dictionary import WordDictionary
    from cursed_words_solver.engine.solver import trie_for

    trie_for(WordDictionary(wordlist_path))


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
    if _pool_shutdown_requested:
        return None
    key = (str(wordlist_path), workers)
    if _pool is None or _pool_key != key:
        shutdown_search_pool(wait=True)
        prebuild_shared_trie_cache(wordlist_path)
        _pool = ProcessPoolExecutor(
            max_workers=workers,
            initializer=_mp_init,
            initargs=(str(wordlist_path),),
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
    global _pool, _pool_key, _pool_warm, _pool_shutdown_requested
    if _pool is not None:
        _pool.shutdown(wait=wait, cancel_futures=not wait)
        _pool = None
        _pool_key = None
        _pool_warm = False
    if wait:
        _pool_shutdown_requested = False
    else:
        _pool_shutdown_requested = True


def _mp_warmup(_: int) -> int:
    if _mp_dictionary is None:
        return 0
    from cursed_words_solver.engine.solver import trie_for

    trie_for(_mp_dictionary)  # build / load the engine trie before the first solve
    return len(_mp_dictionary.words)


def _mp_init(wordlist_path: str) -> None:
    import signal

    # Parent handles Ctrl+C; ignore in workers to avoid shutdown traceback spam.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)

    global _mp_dictionary
    from cursed_words_solver.dictionary import WordDictionary

    _mp_dictionary = WordDictionary(Path(wordlist_path))
