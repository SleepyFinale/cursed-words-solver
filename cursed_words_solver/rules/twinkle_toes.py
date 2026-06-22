"""Twinkle Toes stamp: simulate mandatory tile-swap before word submission."""

from __future__ import annotations

import time
from dataclasses import dataclass
from itertools import combinations
from typing import Iterator

from cursed_words_solver.models import Board, Loadout, Tile, WordResult
from cursed_words_solver.rules.grid_effects import _clone_board
from cursed_words_solver.rules.quest_effects import tile_is_crossed_out
from cursed_words_solver.rules.stamp_behaviors import loadout_has_stamp
from cursed_words_solver.search import WordSearcher

_SCREEN_VARIANT_CAP = 16
_FINALIST_CAP = 12
_MIN_SWAP_SCREEN_SEC = 2.0
_MIN_SWAP_REFINE_SEC = 2.0


@dataclass(frozen=True)
class TwinkleToesSwap:
    row_a: int
    col_a: int
    row_b: int
    col_b: int

    def index_a_at(self, cols: int) -> int:
        return self.row_a * cols + self.col_a

    def index_b_at(self, cols: int) -> int:
        return self.row_b * cols + self.col_b


def twinkle_toes_equipped(loadout: Loadout | None) -> bool:
    return loadout_has_stamp(loadout, "twinkle_toes")


def twinkle_toes_swap_pending(loadout: Loadout | None) -> bool:
    if not twinkle_toes_equipped(loadout):
        return False
    raw = str((loadout.extras or {}).get("twinkle_toes_swap_available", "")).strip().lower()
    return raw in ("true", "1", "yes")


def twinkle_swap_eligible_indices(board: Board) -> list[int]:
    indices: list[int] = []
    for idx in range(board.cell_count):
        if not board.is_active_index(idx):
            continue
        tile = board.get_by_index(idx)
        if tile_is_crossed_out(tile):
            continue
        if str(tile.curse).endswith("inactive") or tile.letter == "":
            continue
        indices.append(idx)
    return indices


def _tile_with_content(src: Tile, row: int, col: int) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=src.char,
        letter=src.letter,
        base_score=src.base_score,
        color=src.color,
        curse=src.curse,
        number_value=src.number_value,
        fraction_value=src.fraction_value,
        ocr_confidence=src.ocr_confidence,
        metadata=dict(src.metadata),
    )


def swap_tile_contents(board: Board, idx_a: int, idx_b: int) -> Board:
    """Swap tile content at two indices; coordinates stay fixed (game SetAsCopy)."""
    if idx_a == idx_b:
        return _clone_board(board)
    out = _clone_board(board)
    cols = board.storage_cols
    row_a, col_a = divmod(idx_a, cols)
    row_b, col_b = divmod(idx_b, cols)
    tile_a = board.tiles[row_a][col_a]
    tile_b = board.tiles[row_b][col_b]
    out.tiles[row_a][col_a] = _tile_with_content(tile_b, row_a, col_a)
    out.tiles[row_b][col_b] = _tile_with_content(tile_a, row_b, col_b)
    out._rebuild_flat_cache()
    return out


def iter_swap_pairs(board: Board) -> Iterator[tuple[int, int]]:
    eligible = twinkle_swap_eligible_indices(board)
    yield from combinations(eligible, 2)


def swap_to_record(idx_a: int, idx_b: int, *, cols: int = 5) -> TwinkleToesSwap:
    row_a, col_a = divmod(idx_a, cols)
    row_b, col_b = divmod(idx_b, cols)
    return TwinkleToesSwap(row_a=row_a, col_a=col_a, row_b=row_b, col_b=col_b)


def format_swap_instructions(
    swap: TwinkleToesSwap | None,
    board: Board | None = None,
) -> str:
    if swap is None:
        return ""
    suffix_a = suffix_b = ""
    if board is not None:
        tile_a = board.get(swap.row_a, swap.col_a)
        tile_b = board.get(swap.row_b, swap.col_b)
        if tile_a is not None and tile_a.letter:
            suffix_a = f" {tile_a.letter.upper()}"
        if tile_b is not None and tile_b.letter:
            suffix_b = f" {tile_b.letter.upper()}"
    return (
        f"Twinkle Toes: swap ({swap.row_a},{swap.col_a}){suffix_a} "
        f"\u2194 ({swap.row_b},{swap.col_b}){suffix_b}"
    )


def _result_rank_score(result: WordResult) -> float:
    if result.rank_score > 0:
        return result.rank_score
    return result.score + result.setup_bonus


def _swap_screen_rank(board: Board, idx_a: int, idx_b: int) -> float:
    """Cheap pre-screen: prefer pairs involving high-value tiles."""
    ta = board.get_by_index(idx_a)
    tb = board.get_by_index(idx_b)
    return float(ta.base_score) + float(tb.base_score)


def _cap_swap_pairs(
    board: Board,
    pairs: list[tuple[int, int]],
    *,
    max_screen: int,
) -> list[tuple[int, int]]:
    if len(pairs) <= max_screen:
        return pairs
    ranked = sorted(
        pairs,
        key=lambda pair: -_swap_screen_rank(board, pair[0], pair[1]),
    )
    return ranked[:max_screen]


def _min_swap_screen_sec(total_budget: float, screen_share: float) -> float:
    if total_budget >= 10.0:
        return _MIN_SWAP_SCREEN_SEC
    return min(_MIN_SWAP_SCREEN_SEC, max(0.5, screen_share / 2))


def _min_swap_refine_sec(
    total_budget: float, refine_share: float, finalists: int
) -> float:
    if total_budget >= 10.0:
        return _MIN_SWAP_REFINE_SEC
    return min(
        _MIN_SWAP_REFINE_SEC,
        max(0.5, refine_share / max(1, finalists)),
    )


def _swap_phase_deadline(solve_deadline: float, phase_sec: float) -> float:
    """Per-call deadline capped by the overall F8 solve deadline."""
    return min(time.monotonic() + phase_sec, solve_deadline)


def _swap_budget_shares(total_budget: float) -> tuple[float, float]:
    """Split budget between screening and refinement; reserve refine time."""
    min_refine = (
        _MIN_SWAP_REFINE_SEC
        if total_budget >= 4.0
        else min(_MIN_SWAP_REFINE_SEC, max(0.5, total_budget * 0.25))
    )
    screen_share = min(12.0, total_budget * 0.35)
    refine_share = total_budget - screen_share
    if refine_share < min_refine and total_budget > min_refine + 0.5:
        refine_share = min_refine
        screen_share = total_budget - refine_share
    return screen_share, refine_share


def search_with_twinkle_toes_swap(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    *,
    time_budget: float,
    top_n: int,
    solve_deadline: float | None = None,
) -> tuple[Board, TwinkleToesSwap | None, list[WordResult]]:
    pairs = list(iter_swap_pairs(board))
    if not pairs:
        return (
            board,
            None,
            searcher.find_best_words(
                board,
                loadout=loadout,
                top_n=top_n,
                deadline=solve_deadline,
            ),
        )

    total_budget = max(2.0, float(time_budget))
    deadline = (
        solve_deadline
        if solve_deadline is not None
        else time.monotonic() + total_budget
    )
    screen_share, refine_share = _swap_budget_shares(total_budget)
    min_screen = _min_swap_screen_sec(total_budget, screen_share)
    budget_limited_pairs = max(1, int(screen_share / min_screen))
    max_screen_pairs = min(_SCREEN_VARIANT_CAP, len(pairs), budget_limited_pairs)
    if len(pairs) <= _SCREEN_VARIANT_CAP and total_budget < 10.0:
        max_screen_pairs = len(pairs)
    screen_pairs = _cap_swap_pairs(board, pairs, max_screen=max_screen_pairs)
    per_screen = max(
        min_screen,
        screen_share / max(1, len(screen_pairs)),
    )

    screened: list[tuple[float, tuple[int, int], Board, WordResult]] = []
    prev_budget = searcher.time_budget
    try:
        searcher.time_budget = per_screen
        for idx_a, idx_b in screen_pairs:
            if time.monotonic() >= deadline:
                break
            swapped = swap_tile_contents(board, idx_a, idx_b)
            results = searcher.find_best_words(
                swapped,
                loadout=loadout,
                top_n=1,
                deadline=_swap_phase_deadline(deadline, per_screen),
            )
            if not results:
                continue
            result = results[0]
            screened.append(
                (_result_rank_score(result), (idx_a, idx_b), swapped, result)
            )
    finally:
        searcher.time_budget = prev_budget

    if not screened:
        return board, None, []

    screened.sort(key=lambda row: -row[0])
    best_rank, best_pair, best_board, best_result = screened[0]
    best_swap = swap_to_record(best_pair[0], best_pair[1], cols=board.storage_cols)
    best_results: list[WordResult] = [best_result]

    if time.monotonic() >= deadline:
        return best_board, best_swap, best_results

    finalists = screened[: min(_FINALIST_CAP, len(screened))]
    min_refine = _min_swap_refine_sec(total_budget, refine_share, len(finalists))
    per_refine = max(min_refine, refine_share / len(finalists))

    try:
        searcher.time_budget = per_refine
        for rank, pair, swapped, _screen_result in finalists:
            if time.monotonic() >= deadline:
                break
            results = searcher.find_best_words(
                swapped,
                loadout=loadout,
                top_n=top_n,
                deadline=_swap_phase_deadline(deadline, per_refine),
            )
            if not results:
                continue
            refine_rank = _result_rank_score(results[0])
            if refine_rank > best_rank:
                best_rank = refine_rank
                best_board = swapped
                best_swap = swap_to_record(pair[0], pair[1], cols=board.storage_cols)
                best_results = results
    finally:
        searcher.time_budget = prev_budget

    return best_board, best_swap, best_results
