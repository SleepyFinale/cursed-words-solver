"""Adapter: run the exact engine search behind ``WordSearcher.find_best_words``.

Returns ``None`` for situations the exact search does not model yet (Cursedle,
Michael's 25-tile finale, Honeypot two-word submits) so the legacy search runs.
"""

from __future__ import annotations

import itertools
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cursed_words_solver.engine import packet as P
from cursed_words_solver.engine.calc import EnginePlan
from cursed_words_solver.engine.search import Candidate, ExactSearch
from cursed_words_solver.engine.trie import CsrTrie, load_trie
from cursed_words_solver.models import Board, Loadout, WordResult

_CAPYBARA_SAMPLES = 120


def unsupported_reason(plan: EnginePlan, loadout: Loadout) -> str:
    extras = loadout.extras or {}
    if str(extras.get("encounter_mode") or "").lower() == "cursedle":
        return "cursedle"
    if str(extras.get("michael_summoned_bosses_defeated") or "").lower() == "true":
        return "michael_finale"
    if "Honeypot" in plan.item_classes:
        return "honeypot"
    return ""


def _moves_ok(search: ExactSearch, path) -> bool:
    n = len(search.tiles)
    if any(not (0 <= i < n) for i in path) or len(set(path)) != len(path):
        return False
    for k in range(len(path) - 1):
        prefix = tuple(path[: k + 1])
        if path[k + 1] not in search.next_tiles(prefix, set(prefix), search.inventory_for(prefix)):
            return False
    return True


def _submittable(search: ExactSearch, path) -> bool:
    path = tuple(path)
    return _moves_ok(search, path) and search.path_allowed(path) and search.valid_word(path) is not None


def engine_path_movement_ok(board: Board, path: list[int], loadout: Loadout) -> bool | None:
    """Every step follows ``GetValidNextTiles``; None when the engine can't model the board."""
    try:
        plan = EnginePlan.build(board, loadout)
        if unsupported_reason(plan, loadout):
            return None
        return _moves_ok(ExactSearch(plan, CsrTrie.from_words(())), path)
    except Exception:  # noqa: BLE001 - caller falls back to the legacy check
        return None


def engine_path_submittable(board: Board, path: list[int], loadout: Loadout, dictionary, *, min_len: int = 1) -> bool | None:
    """Game accepts some word on ``path`` (movement + vocabulary + challenge rules); None if unmodeled."""
    try:
        plan = EnginePlan.build(board, loadout)
        if unsupported_reason(plan, loadout):
            return None
        search = ExactSearch(plan, trie_for(dictionary))
        search.min_len = max(search.min_len, int(min_len or 1))
        return _submittable(search, path)
    except Exception:  # noqa: BLE001 - caller falls back to the legacy check
        return None


def engine_path_score(board: Board, path: list[int], word: str, loadout: Loadout) -> int | None:
    """Exact game-port score for one path; None when the engine can't model the board."""
    try:
        plan = EnginePlan.build(board, loadout)
        if unsupported_reason(plan, loadout):
            return None
        mode = _capybara_mode(loadout)
        if mode:
            # Same expected value over shuffled item orders as the prediction.
            return int(capybara_score_range(plan, path, word, mode)[0])
        return int(plan.score(list(path), word).int_score)
    except Exception:  # noqa: BLE001 - caller falls back to the legacy pipeline
        return None


def trie_for(dictionary) -> CsrTrie:
    words = getattr(dictionary, "words", None) or ()
    cache_dir = Path.home() / ".cursed_words_solver"
    return load_trie(words, cache_dir if cache_dir.exists() else None)


def _capybara_mode(loadout: Loadout) -> int:
    """0 = no shuffle, 1 = stickers shuffle, 2 = stickers + stamps (FloorAdjustedModification)."""
    import json

    extras = loadout.extras or {}
    raw = extras.get("boss_modifiers")
    try:
        mods = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or [])
    except json.JSONDecodeError:
        mods = []
    ids = [str(m).lower() for m in mods] if isinstance(mods, list) else []
    if not ids and loadout.boss_id:
        ids = [loadout.boss_id.lower()]
    if "capybara" not in ids:
        return 0
    floor_mods = extras.get("boss_modifier_floor_mods")
    try:
        fm = json.loads(floor_mods) if isinstance(floor_mods, str) and floor_mods.strip() else (floor_mods or {})
    except json.JSONDecodeError:
        fm = {}
    level = fm.get("capybara") if isinstance(fm, dict) else None
    if level is None:
        level = extras.get("boss_floor_modification")
    try:
        return 2 if int(level) == 2 else 1
    except (TypeError, ValueError):
        return 1


def _orderings(plan: EnginePlan, mode: int, rng: random.Random, limit: int = _CAPYBARA_SAMPLES) -> list[tuple[list, list]]:
    """Slot orderings for Player.RandomiseItemOrder (5-slot arrays incl. empty slots);
    a random sample of ``limit`` when there are more."""
    stickers = list(plan.stickers) + [None] * max(0, 5 - len(plan.stickers))
    stamps = list(plan.stamps) + [None] * max(0, 5 - len(plan.stamps))
    sticker_perms = list(dict.fromkeys(tuple(map(id, p)) for p in itertools.permutations(stickers)))
    by_id = {id(s): s for s in stickers}
    sticker_orders = [[by_id[i] for i in perm] for perm in sticker_perms]
    if mode == 2:
        by_id_st = {id(s): s for s in stamps}
        stamp_orders = [[by_id_st[i] for i in perm] for perm in dict.fromkeys(tuple(map(id, p)) for p in itertools.permutations(stamps))]
    else:
        stamp_orders = [stamps]
    combos = [(a, b) for a in sticker_orders for b in stamp_orders]
    if len(combos) > limit:
        combos = rng.sample(combos, limit)
    return combos


# Every ordering for one suggestion's score range (5 stickers x 5 stamps = 14,400).
_CAPYBARA_EXACT_LIMIT = 20_000


def capybara_score_range(plan: EnginePlan, path, word: str, mode: int) -> tuple[float, int, int, int, bool]:
    """(mean, min, max, orderings scored, exhaustive) over the shuffles Capybara can roll."""
    orderings = _orderings(plan, mode, random.Random(0), limit=10**9)
    exhaustive = len(orderings) <= _CAPYBARA_EXACT_LIMIT
    if not exhaustive:
        orderings = random.Random(0).sample(orderings, _CAPYBARA_EXACT_LIMIT)
    ev, lo, hi = _expected_score(plan, tuple(path), word, orderings)
    return ev, lo, hi, len(orderings), exhaustive


def _expected_score(plan: EnginePlan, path: tuple[int, ...], word: str, orderings) -> tuple[float, int, int]:
    saved = (plan.stickers, plan.stamps)
    scores = []
    try:
        for stickers, stamps in orderings:
            plan.stickers, plan.stamps = stickers, stamps
            scores.append(P.to_int(plan.score(list(path), word).score))
    finally:
        plan.stickers, plan.stamps = saved
    return sum(scores) / len(scores), min(scores), max(scores)


def _distinct(candidates: list[Candidate], required_indices: frozenset[int], limit: int | None = None) -> list[Candidate]:
    """Suggestions are distinct words, each on its best-ranked path (input already sorted)."""
    seen_words: set[str] = set()
    out: list[Candidate] = []
    for c in candidates:
        if c.word in seen_words or (required_indices and not required_indices.issubset(c.path)):
            continue
        seen_words.add(c.word)
        out.append(c)
        if limit is not None and len(out) >= limit:
            break
    return out


@dataclass
class ParallelSpec:
    """Process pool for spreading start tiles (``search_parallel.get_search_pool``)."""

    executor: Any
    workers: int
    quest_target: float | None = None


# Seconds past the deadline to wait for in-flight worker tasks before giving up on them.
_LATE_TASK_GRACE_SEC = 5.0


def _run_parallel(
    spec: ParallelSpec,
    search: ExactSearch,
    board: Board,
    loadout: Loadout,
    *,
    deadline: float | None,
    cancel_check: Callable[[], bool] | None,
    required_indices: frozenset[int],
    keep: int,
    words: int,
) -> tuple[list[Candidate] | None, dict]:
    """One task per start tile, ``workers`` in flight, each with a fair share of the
    time left. Returns (None, {}) if the pool fails so the caller runs serially."""
    from concurrent.futures import FIRST_COMPLETED, Future, wait

    starts = list(search._available_allowed)
    if spec.workers <= 1 or len(starts) <= 1:
        return None, {}
    # Workers see wall-clock time; perf_counter is per process.
    end_wall = None if deadline is None else time.time() + max(0.0, deadline - time.perf_counter())
    solve_id = f"{os.getpid()}-{time.perf_counter_ns()}"
    base = {
        "solve_id": solve_id, "board": board, "loadout": loadout,
        "min_len": search.min_len, "max_len": search.max_len,
        "quest_target": spec.quest_target, "required": sorted(required_indices),
        "keep": keep, "words": words, "n_starts": len(starts),
    }
    pending = list(starts)
    in_flight: dict = {}
    out: list[Candidate] = []
    agg = {"nodes": 0, "paths": 0, "scored": 0, "enum_sec": 0.0, "score_sec": 0.0}
    exhaustive = True
    cancelled = False
    try:
        while pending or in_flight:
            while pending and len(in_flight) < spec.workers and not cancelled:
                task_end = None
                if end_wall is not None:
                    left = max(0.0, end_wall - time.time())
                    unfinished = len(pending) + len(in_flight)
                    task_end = time.time() + left * min(spec.workers, unfinished) / unfinished
                start = pending.pop(0)
                fut = spec.executor.submit(_mp_exact_task, {**base, "starts": [start], "end_wall": task_end})
                if not isinstance(fut, Future):
                    raise RuntimeError("pool did not return a future")
                in_flight[fut] = start
            if end_wall is not None and time.time() > end_wall + _LATE_TASK_GRACE_SEC:
                # A stuck worker must not hang the solve: keep what finished.
                for fut in in_flight:
                    fut.cancel()
                in_flight.clear()
                exhaustive = False
                break
            done, _ = wait(list(in_flight), timeout=0.25, return_when=FIRST_COMPLETED)
            for fut in done:
                in_flight.pop(fut)
                res = fut.result()
                if res is None:
                    raise RuntimeError("worker could not run the exact search")
                cands, st = res
                out.extend(Candidate(tuple(p), w, sc, nd) for p, w, sc, nd in cands)
                for k in agg:
                    agg[k] += st.get(k, 0)
                exhaustive = exhaustive and st.get("exhaustive", True)
            if not cancelled and cancel_check is not None and cancel_check():
                cancelled = True
                exhaustive = False
                pending.clear()
    except Exception as exc:  # noqa: BLE001 - serial search still works
        for fut in in_flight:
            fut.cancel()
        print(f"  Parallel exact search failed ({exc}); running serially.", flush=True)
        return None, {}
    info = {
        "engine": "exact",
        "parallel_workers": spec.workers,
        "nodes": agg["nodes"],
        "paths": agg["paths"],
        "scored": agg["scored"],
        "timed_out": not exhaustive,
        "enum_sec": round(agg["enum_sec"], 3),
        "score_sec": round(agg["score_sec"], 3),
        "exhaustive": exhaustive,
    }
    return out, info


_WORKER_SEARCH: tuple[str, ExactSearch] | None = None


def _mp_exact_task(payload: dict) -> tuple[list[tuple], dict] | None:
    """Pool worker: exact search over ``payload["starts"]``; best ``keep`` distinct words."""
    global _WORKER_SEARCH
    from cursed_words_solver import search_parallel
    from cursed_words_solver.engine.search import SearchStats
    from cursed_words_solver.rules.quest_scoring import search_rank_for_quest

    dictionary = search_parallel._mp_dictionary
    if dictionary is None or len(dictionary.words) != payload["words"]:
        return None
    loadout: Loadout = payload["loadout"]
    if _WORKER_SEARCH is None or _WORKER_SEARCH[0] != payload["solve_id"]:
        search = ExactSearch(EnginePlan.build(payload["board"], loadout), trie_for(dictionary))
        search.min_len = payload["min_len"]
        search.max_len = payload["max_len"]
        _WORKER_SEARCH = (payload["solve_id"], search)
    search = _WORKER_SEARCH[1]
    search.stats = SearchStats()
    end_wall = payload["end_wall"]
    if end_wall is None:
        # No deadline: this start gets its share of the whole-board work budgets.
        n = max(1, payload["n_starts"])
        search.exhaustive_node_budget = max(search.min_start_node_budget, ExactSearch.exhaustive_node_budget // n)
        search.subset_path_budget = max(search.min_start_node_budget, ExactSearch.subset_path_budget // n)
    deadline = None if end_wall is None else time.perf_counter() + (end_wall - time.time())
    qt = payload["quest_target"]

    def rank(s):
        return search_rank_for_quest(float(P.to_int(s)), loadout, quest_target=qt)

    cands = search.run(top_n=0, deadline=deadline, rank=rank, starts=payload["starts"])
    best = _distinct(cands, frozenset(payload["required"]), limit=payload["keep"])
    st = search.stats
    stats = {
        "nodes": st.nodes, "paths": st.paths, "scored": st.valid_paths,
        "enum_sec": st.enum_sec, "score_sec": st.score_sec,
        "exhaustive": bool(st.extra.get("exhaustive", True)),
    }
    return [(c.path, c.word, c.score, c.nondeterministic) for c in best], stats


def exact_find_best_words(
    dictionary,
    board: Board,
    loadout: Loadout,
    *,
    top_n: int = 3,
    min_len: int = 1,
    max_len: int = 25,
    required_indices: frozenset[int] = frozenset(),
    deadline: float | None = None,
    cancel_check: Callable[[], bool] | None = None,
    rank: Callable[[float], float] | None = None,
    parallel: ParallelSpec | None = None,
) -> tuple[list[WordResult] | None, dict]:
    """Best ``top_n`` words by exact game score, or (None, info) when unsupported.

    With ``parallel``, start tiles are spread over the search process pool; each
    worker ranks with ``search_rank_for_quest`` (``rank`` must be that function
    for ``parallel.quest_target``).
    """
    t0 = time.perf_counter()
    if cancel_check is not None and cancel_check():
        return [], {"engine": "exact", "cancelled": True}
    plan = EnginePlan.build(board, loadout)
    reason = unsupported_reason(plan, loadout)
    if reason:
        return None, {"unsupported": reason}
    search = ExactSearch(plan, trie_for(dictionary))
    search.min_len = max(search.min_len, int(min_len or 1))
    search.max_len = min(search.max_len, int(max_len or 25))
    rank_fn = rank or (lambda s: s)
    keep = max(top_n * 10, 30)
    candidates: list[Candidate] | None = None
    if parallel is not None:
        candidates, info = _run_parallel(
            parallel, search, board, loadout, deadline=deadline, cancel_check=cancel_check,
            required_indices=required_indices, keep=keep, words=len(getattr(dictionary, "words", ()) or ()),
        )
        if candidates is not None:
            candidates.sort(key=lambda c: rank_fn(P.to_int(c.score)), reverse=True)
            candidates = _distinct(candidates, frozenset())
    if candidates is None:
        candidates = search.run(
            top_n=0, deadline=deadline, cancel_check=cancel_check, rank=lambda s: rank_fn(P.to_int(s))
        )
        candidates = _distinct(candidates, required_indices)
        info = {
            "engine": "exact",
            "nodes": search.stats.nodes,
            "paths": search.stats.paths,
            "scored": search.stats.valid_paths,
            "timed_out": search.stats.timed_out,
            "enum_sec": round(search.stats.enum_sec, 3),
            "score_sec": round(search.stats.score_sec, 3),
            **search.stats.extra,
        }
    mode = _capybara_mode(loadout)
    results: list[WordResult] = []
    if mode:
        # Item order is shuffled at submit: rank the leading candidates by EV.
        orderings = _orderings(plan, mode, random.Random(0))
        evs = []
        for c in candidates[: max(top_n * 10, 30)]:
            ev, lo, hi = _expected_score(plan, c.path, c.word, orderings)
            evs.append((rank_fn(ev), ev, lo, hi, c))
        evs.sort(key=lambda r: r[0], reverse=True)
        for _r, ev, lo, hi, c in evs[:top_n]:
            results.append(
                WordResult(
                    word=c.word,
                    path=list(c.path),
                    score=float(ev),
                    dictionary_word=c.word,
                    breakdown={"engine": "exact", "nondeterministic": True, "score_min": lo, "score_max": hi},
                    rank_score=float(ev),
                )
            )
        info["capybara_orderings"] = len(orderings)
    else:
        for c in candidates[:top_n]:
            s = float(P.to_int(c.score))
            results.append(
                WordResult(
                    word=c.word,
                    path=list(c.path),
                    score=s,
                    dictionary_word=c.word,
                    breakdown={"engine": "exact", "nondeterministic": c.nondeterministic},
                    rank_score=float(rank_fn(s)),
                )
            )
    info["wall_sec"] = round(time.perf_counter() - t0, 3)
    info["exhaustive"] = bool(search.stats.extra.get("exhaustive", True))
    info["plan"] = plan
    info["capybara_mode"] = mode
    return results, info


def rescore_results(
    plan: EnginePlan,
    results: list[WordResult],
    *,
    capybara_mode: int = 0,
    rank: Callable[[float], float] | None = None,
) -> list[WordResult]:
    """Exact engine scores for candidates found by another search (legacy fallback)."""
    rank_fn = rank or (lambda s: s)
    orderings = _orderings(plan, capybara_mode, random.Random(0)) if capybara_mode else None
    out: list[WordResult] = []
    for r in results:
        path = tuple(r.path)
        if any(i >= len(plan.grid.tiles) for i in path):
            continue
        word = r.dictionary_word or r.word
        if orderings:
            ev, lo, hi = _expected_score(plan, path, word, orderings)
            score, bd = float(ev), {"engine": "exact", "nondeterministic": True, "score_min": lo, "score_max": hi}
        else:
            res = plan.score(list(path), word)
            score = float(P.to_int(res.score))
            bd = {"engine": "exact", "nondeterministic": res.nondeterministic}
        merged = dict(r.breakdown or {})
        merged.update(bd)
        merged["source"] = "legacy_search"
        out.append(
            WordResult(
                word=r.word,
                path=list(path),
                score=score,
                breakdown=merged,
                dictionary_word=r.dictionary_word,
                rank_score=float(rank_fn(score)),
            )
        )
    return out
