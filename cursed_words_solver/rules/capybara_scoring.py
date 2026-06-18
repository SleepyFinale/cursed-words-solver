"""Capybara non-deterministic scoring: permutation EV and min/max range."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from itertools import permutations
from typing import TYPE_CHECKING, Any, Iterator

from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.boss_effects import boss_is_cursed, get_active_boss_rules
from cursed_words_solver.rules.scoring_order import (
    _inventory_item_refs,
    capybara_shuffles_loadout,
)

if TYPE_CHECKING:
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from cursed_words_solver.solve_context import SolveContext

MAX_EXHAUSTIVE_PERMS = 720
MAX_EXHAUSTIVE_ITEM_COUNT = 6
SAMPLED_PERM_COUNT = 256


@dataclass(frozen=True)
class CapybaraScope:
    shuffles_stickers: bool
    shuffles_stamps: bool


@dataclass(frozen=True)
class CapybaraScoreStats:
    ev: float
    min_score: float
    max_score: float
    perm_count: int
    exhaustive: bool
    best_loadout: Loadout | None = None
    best_score: float | None = None


def capybara_shuffle_scope(loadout: Loadout | None, rules: dict) -> CapybaraScope:
    """Which inventory arrays the game randomizes before scoring."""
    if not loadout or not capybara_shuffles_loadout(loadout, rules):
        return CapybaraScope(False, False)
    for _key, boss in get_active_boss_rules(rules, loadout):
        if boss and boss.get("type") == "shuffle_loadout_order":
            return CapybaraScope(True, boss_is_cursed(loadout))
    return CapybaraScope(True, False)


def capybara_active_warning(loadout: Loadout | None, rules: dict) -> str | None:
    scope = capybara_shuffle_scope(loadout, rules)
    if not scope.shuffles_stickers:
        return None
    if scope.shuffles_stamps:
        return (
            "Capybara active — sticker and stamp order randomized, "
            "score estimate may be off"
        )
    return "Capybara active — sticker order randomized, score estimate may be off"


def capybara_sampling_warning(exhaustive: bool, perm_count: int) -> str | None:
    if exhaustive:
        return None
    return (
        f"Capybara permutations sampled ({perm_count} of "
        f"{SAMPLED_PERM_COUNT}) — score range is approximate"
    )


def capybara_perm_count(loadout: Loadout, scope: CapybaraScope) -> int:
    if scope.shuffles_stickers and len(loadout.stickers) > 1:
        sticker_n = math.factorial(len(loadout.stickers))
    else:
        sticker_n = 1
    if scope.shuffles_stamps and len(loadout.stamps) > 1:
        stamp_n = math.factorial(len(loadout.stamps))
    else:
        stamp_n = 1
    return sticker_n * stamp_n


def _capybara_exhaustive(perm_total: int, loadout: Loadout) -> bool:
    if perm_total <= MAX_EXHAUSTIVE_PERMS:
        return True
    item_count = len(loadout.stickers) + len(loadout.stamps)
    return item_count <= MAX_EXHAUSTIVE_ITEM_COUNT and perm_total <= MAX_EXHAUSTIVE_PERMS


def _sample_seed(path: list[int], loadout: Loadout) -> int:
    extras = loadout.extras or {}
    raw = extras.get("capybara_shuffle_seed")
    if raw is not None and str(raw).strip() != "":
        try:
            return int(raw) & 0xFFFFFFFF
        except (TypeError, ValueError):
            pass
    material = ",".join(str(i) for i in path)
    material += f"|{extras.get('run_seed', '')}|{loadout.boss_id}"
    return hash(material) & 0xFFFFFFFF


def _capybara_rng(path: list[int], loadout: Loadout) -> random.Random:
    return random.Random(_sample_seed(path, loadout))


def _sticker_permutation_lists(
    stickers: list,
    scope: CapybaraScope,
) -> list[list]:
    if not scope.shuffles_stickers or len(stickers) <= 1:
        return [list(stickers)]
    return [list(p) for p in permutations(stickers)]


def _stamp_permutation_lists(
    stamps: list,
    scope: CapybaraScope,
) -> list[list]:
    if not scope.shuffles_stamps or len(stamps) <= 1:
        return [list(stamps)]
    return [list(p) for p in permutations(stamps)]


def _sample_permutation_pairs(
    loadout: Loadout,
    scope: CapybaraScope,
    path: list[int],
    *,
    sample_count: int,
) -> list[tuple[list, list]]:
    rng = _capybara_rng(path, loadout)
    stickers = list(loadout.stickers)
    stamps = list(loadout.stamps)
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    pairs: list[tuple[list, list]] = []
    sticker_lists = _sticker_permutation_lists(stickers, scope)
    stamp_lists = _stamp_permutation_lists(stamps, scope)
    for s_perm in sticker_lists:
        for t_perm in stamp_lists:
            key = (
                tuple(item.id or item.name or "" for item in s_perm),
                tuple(item.id or item.name or "" for item in t_perm),
            )
            if key not in seen:
                seen.add(key)
                pairs.append((s_perm, t_perm))
    if len(pairs) <= sample_count:
        return pairs
    rng.shuffle(pairs)
    return pairs[:sample_count]


def iter_capybara_loadout_permutations(
    loadout: Loadout,
    scope: CapybaraScope,
    *,
    path: list[int] | None = None,
    exhaustive: bool | None = None,
) -> Iterator[Loadout]:
    """Yield loadout copies for each sticker/stamp order the game may pick."""
    sticker_lists = _sticker_permutation_lists(list(loadout.stickers), scope)
    stamp_lists = _stamp_permutation_lists(list(loadout.stamps), scope)
    total = len(sticker_lists) * len(stamp_lists)
    use_exhaustive = (
        exhaustive
        if exhaustive is not None
        else _capybara_exhaustive(total, loadout)
    )
    if use_exhaustive:
        for s_perm in sticker_lists:
            for t_perm in stamp_lists:
                yield replace(loadout, stickers=s_perm, stamps=t_perm)
        return
    if path is None:
        path = []
    for s_perm, t_perm in _sample_permutation_pairs(
        loadout, scope, path, sample_count=SAMPLED_PERM_COUNT
    ):
        yield replace(loadout, stickers=s_perm, stamps=t_perm)


def _perm_scoring_context(
    ctx: SolveContext,
    perm_loadout: Loadout,
    rules: dict,
) -> SolveContext:
    from cursed_words_solver.solve_context import _slot_order

    return replace(
        ctx,
        capybara_shuffles=False,
        inventory_refs=tuple(_inventory_item_refs(perm_loadout, rules)),
        sticker_slot_order=_slot_order(
            len(perm_loadout.stickers), hourglass=ctx.hourglass_reversed
        ),
        stamp_slot_order=_slot_order(
            len(perm_loadout.stamps), hourglass=ctx.hourglass_reversed
        ),
    )


def score_capybara_distribution(
    pipeline: ScoringPipeline,
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    rules: dict,
    *,
    solve_context: SolveContext | None = None,
    with_trace: bool = False,
    grid_refs_cache: dict[tuple[int, ...], tuple] | None = None,
    grid_refs_timing: object | None = None,
) -> CapybaraScoreStats:
    """Score over Capybara permutations; return EV, min, max."""
    from cursed_words_solver.solve_context import build_solve_context

    scope = capybara_shuffle_scope(loadout, rules)
    ctx = solve_context or build_solve_context(loadout, rules)
    perm_total = capybara_perm_count(loadout, scope)
    exhaustive = _capybara_exhaustive(perm_total, loadout)
    scores: list[float] = []
    best_loadout: Loadout | None = None
    best_score: float | None = None
    for perm_loadout in iter_capybara_loadout_permutations(
        loadout, scope, path=path, exhaustive=exhaustive
    ):
        perm_ctx = _perm_scoring_context(ctx, perm_loadout, rules)
        score = pipeline.score_total_only(
            board,
            path,
            word,
            perm_loadout,
            solve_context=perm_ctx,
            grid_refs_cache=grid_refs_cache,
            grid_refs_timing=grid_refs_timing,
        )
        scores.append(score)
        if best_score is None or score > best_score:
            best_score = score
            best_loadout = perm_loadout
    if not scores:
        single = pipeline.score_total_only(
            board, path, word, loadout, solve_context=ctx
        )
        return CapybaraScoreStats(
            ev=single,
            min_score=single,
            max_score=single,
            perm_count=1,
            exhaustive=True,
            best_loadout=loadout,
            best_score=single,
        )
    ev = sum(scores) / len(scores)
    return CapybaraScoreStats(
        ev=ev,
        min_score=min(scores),
        max_score=max(scores),
        perm_count=len(scores),
        exhaustive=exhaustive,
        best_loadout=best_loadout,
        best_score=best_score,
    )


def score_capybara_ev(
    pipeline: ScoringPipeline,
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    rules: dict,
    *,
    solve_context: SolveContext | None = None,
    grid_refs_cache: dict[tuple[int, ...], tuple] | None = None,
    grid_refs_timing: object | None = None,
) -> float:
    """Expected score over Capybara permutations (search hot path)."""
    return score_capybara_distribution(
        pipeline,
        board,
        path,
        word,
        loadout,
        rules,
        solve_context=solve_context,
        grid_refs_cache=grid_refs_cache,
        grid_refs_timing=grid_refs_timing,
    ).ev


def score_capybara_with_trace(
    pipeline: ScoringPipeline,
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    rules: dict,
    *,
    solve_context: SolveContext | None = None,
    grid_refs_cache: dict[tuple[int, ...], tuple] | None = None,
) -> tuple[float, dict[str, Any], list[dict[str, Any]], CapybaraScoreStats]:
    """Full distribution plus trace from the highest-scoring permutation."""
    from cursed_words_solver.solve_context import build_solve_context

    stats = score_capybara_distribution(
        pipeline,
        board,
        path,
        word,
        loadout,
        rules,
        solve_context=solve_context,
        grid_refs_cache=grid_refs_cache,
    )
    ctx = solve_context or build_solve_context(loadout, rules)
    trace_loadout = stats.best_loadout or loadout
    perm_ctx = _perm_scoring_context(ctx, trace_loadout, rules)
    score, bd, trace = pipeline.score_with_trace(
        board, path, word, trace_loadout, solve_context=perm_ctx
    )
    bd = dict(bd)
    bd["capybara"] = {
        "ev": stats.ev,
        "min": stats.min_score,
        "max": stats.max_score,
        "perm_count": stats.perm_count,
        "exhaustive": stats.exhaustive,
    }
    return stats.ev, bd, trace, stats
