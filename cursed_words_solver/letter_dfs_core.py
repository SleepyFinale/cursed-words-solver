"""Tight letter-path expansion helpers (Python hot path; optional native later).

Keeps visited bitset + adjacency masks in locals for DFS/beam letter cases.
Chess / number / wildcard / quest still expand via search.py neighbors_mask.
"""

from __future__ import annotations

from cursed_words_solver.graph_bitboard import BoardGraphContext, iter_mask


def letter_neighbor_indices(
    graph_ctx: BoardGraphContext,
    cell: int,
    visited_mask: int,
) -> list[int]:
    """Standard 8-neighbor expansions excluding visited (no chess/white/quest)."""
    if cell < 0 or cell >= graph_ctx.cell_count:
        return []
    cand = graph_ctx.neighbors_8[cell] & graph_ctx.active_mask & ~visited_mask
    return list(iter_mask(cand))


def popcount_mask(mask: int) -> int:
    return mask.bit_count()
