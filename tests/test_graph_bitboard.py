"""Static topology bitboards and neighbor mask parity."""

from __future__ import annotations

from cursed_words_solver.graph_bitboard import (
    KNIGHT_ADJACENCY,
    KNIGHT_TARGETS,
    KING_STEP_MASK,
    NEIGHBORS_8,
    NEIGHBORS_8_WRAP,
    RAY_LINES,
    STANDARD_ADJACENCY,
    STANDARD_ADJACENCY_WRAP,
    build_board_graph_context,
    collect_mask_indices,
    iter_mask,
    mask_from_indices,
)
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile
from cursed_words_solver.rules.chess_tiles import DIRS_8, chess_neighbors, index_of
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_HORIZONTAL_WRAP,
    stamp_search_flags_mask,
)
from cursed_words_solver.search import neighbors_from_tile, neighbors_mask


def _empty_board() -> Board:
    tiles = [
        [
            Tile(
                row=r,
                col=c,
                char="A",
                letter="A",
                base_score=1.0,
                curse=CurseType.LETTER,
            )
            for c in range(5)
        ]
        for r in range(5)
    ]
    return Board(tiles=tiles)


def test_neighbors_8_center_has_eight_neighbors():
    # Center cell 12 (2,2) has 8 in-bounds neighbors
    assert NEIGHBORS_8[12].bit_count() == 8


def test_neighbors_8_corner_has_three_neighbors():
    assert NEIGHBORS_8[0].bit_count() == 3
    assert NEIGHBORS_8[24].bit_count() == 3


def test_neighbors_8_wrap_adds_horizontal_partner():
    # Cell 0 (row 0, col 0) wrap partner is col 4 same row -> index 4
    wrap_only = NEIGHBORS_8_WRAP[0] & ~NEIGHBORS_8[0]
    assert wrap_only == (1 << 4)


def test_knight_targets_center():
    # From center, all 8 knight jumps are in bounds
    assert KNIGHT_TARGETS[12].bit_count() == 8


def test_ray_lines_exclude_start():
    for cell in range(25):
        for d, (dr, dc) in enumerate(DIRS_8):
            line = RAY_LINES[cell][d]
            assert cell not in line
            row, col = divmod(cell, 5)
            r, c = row, col
            for idx in line:
                r += dr
                c += dc
                if not (0 <= r < 5 and 0 <= c < 5):
                    break
                assert idx == index_of(r, c)


def test_board_graph_context_active_mask():
    board = _empty_board()
    board.active[12] = False
    ctx = build_board_graph_context(board)
    assert ctx.is_active(11)
    assert not ctx.is_active(12)
    assert ctx.active_mask & (1 << 12) == 0


def test_neighbors_mask_matches_neighbors_from_tile_standard():
    board = _empty_board()
    flags = stamp_search_flags_mask(Loadout())
    ctx = build_board_graph_context(board)
    for cell in range(25):
        if not board.is_active_index(cell):
            continue
        path = [cell]
        visited = 1 << cell
        expected = neighbors_from_tile(board, path, visited, flags=flags)
        mask = neighbors_mask(board, path, visited, flags=flags, graph_ctx=ctx)
        assert sorted(expected) == sorted(iter_mask(mask))


def test_neighbors_mask_parity_with_hungry_snake():
    board = _empty_board()
    loadout = Loadout(
        stamps=[
            LoadoutItem(
                id="hungry_snake", name="Hungry Snake", level=1, kind="stamp"
            )
        ]
    )
    flags = stamp_search_flags_mask(loadout)
    assert flags & FLAG_HORIZONTAL_WRAP
    ctx = build_board_graph_context(board)
    for cell in (0, 4, 10, 14):
        path = [cell]
        visited = 1 << cell
        expected = neighbors_from_tile(board, path, visited, flags=flags)
        mask = neighbors_mask(board, path, visited, flags=flags, graph_ctx=ctx)
        assert sorted(expected) == sorted(iter_mask(mask))


def test_chess_neighbors_mask_parity_rook():
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            if idx == 12:
                row.append(
                    Tile(
                        row=r,
                        col=c,
                        char="R",
                        letter="R",
                        base_score=1.0,
                        curse=CurseType.CHESS_ROOK,
                        metadata={"chess_color": "white"},
                    )
                )
            else:
                row.append(
                    Tile(
                        row=r,
                        col=c,
                        char="X",
                        letter="X",
                        base_score=1.0,
                        curse=CurseType.LETTER,
                    )
                )
        rows.append(row)
    board = Board(tiles=rows)
    flags = stamp_search_flags_mask(Loadout())
    ctx = build_board_graph_context(board)
    path = [12]
    visited = 1 << 12
    expected = chess_neighbors(board, path, visited, flags)
    mask = neighbors_mask(board, path, visited, flags=flags, graph_ctx=ctx)
    assert sorted(expected) == sorted(iter_mask(mask))


def test_mask_from_indices_roundtrip():
    indices = [0, 5, 12, 24]
    m = mask_from_indices(indices)
    assert list(iter_mask(m)) == indices


def test_static_adjacency_aliases():
    assert STANDARD_ADJACENCY is NEIGHBORS_8
    assert STANDARD_ADJACENCY_WRAP is NEIGHBORS_8_WRAP
    assert KNIGHT_ADJACENCY is KNIGHT_TARGETS
    assert KING_STEP_MASK is NEIGHBORS_8


def test_collect_mask_indices_matches_iter_mask():
    scratch = [0] * 25
    for mask in (0, 1, 1 << 12, NEIGHBORS_8[12], (1 << 0) | (1 << 24)):
        expected = list(iter_mask(mask))
        n = collect_mask_indices(mask, scratch)
        assert scratch[:n] == expected
