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
from cursed_words_solver.rules.chess_tiles import (
    DIRS_8,
    _ray_neighbors_mask,
    chess_neighbors,
    index_of,
    king_neighbors_mask,
    knight_neighbors_mask,
)
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


def test_neighbors_8_wrap_adds_cross_edge_neighbors():
    # Cell 0 (row 0, col 0): game adds (4, row-1), (4, row), (4, row+1) in bounds
    wrap_only = NEIGHBORS_8_WRAP[0] & ~NEIGHBORS_8[0]
    assert wrap_only == (1 << 4) | (1 << 9)


def test_neighbors_8_wrap_corner_24_reaches_15():
    # (4,4) -> (3,0) via Hungry Snake wrap diagonal (xylometers path step)
    wrap_only = NEIGHBORS_8_WRAP[24] & ~NEIGHBORS_8[24]
    assert 15 in iter_mask(wrap_only)
    assert 20 in iter_mask(wrap_only)


def test_knight_targets_center():
    # From center, all 8 knight jumps are in bounds
    assert KNIGHT_TARGETS[12].bit_count() == 8


def test_knight_targets_wrap_modulo_column():
    """Hungry Snake: knight col wrap uses modulo (game ChessPieces.GetKnightMoves)."""
    from cursed_words_solver.graph_bitboard import knight_targets_for_cell

    wrap = knight_targets_for_cell(19, rows=5, cols=5, horizontal_wrap=True)
    assert 21 in iter_mask(wrap), "white knight at index 19 must attack index 21 with wrap"
    assert 20 not in iter_mask(wrap)


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
        mask = neighbors_mask(
            board, visited, cell_id=cell, flags=flags, graph_ctx=ctx
        )
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
    for cell in range(25):
        path = [cell]
        visited = 1 << cell
        expected = neighbors_from_tile(board, path, visited, flags=flags)
        mask = neighbors_mask(
            board, visited, cell_id=cell, flags=flags, graph_ctx=ctx
        )
        assert sorted(expected) == sorted(iter_mask(mask))


def _chess_piece_board(
    center_curse: CurseType,
    *,
    center_side: str = "white",
    blockers: dict[int, tuple[CurseType, str]] | None = None,
) -> Board:
    blockers = blockers or {}
    rows = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            if idx in blockers:
                curse, side = blockers[idx]
                row.append(
                    Tile(
                        row=r,
                        col=c,
                        char="B",
                        letter="B",
                        base_score=1.0,
                        curse=curse,
                        metadata={"chess_color": side},
                    )
                )
            elif idx == 12:
                row.append(
                    Tile(
                        row=r,
                        col=c,
                        char="P",
                        letter="P",
                        base_score=1.0,
                        curse=center_curse,
                        metadata={"chess_color": center_side},
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
    return Board(tiles=rows)


def _assert_chess_mask_parity(board: Board, *, cell: int = 12) -> None:
    flags = stamp_search_flags_mask(Loadout())
    ctx = build_board_graph_context(board)
    path = [cell]
    visited_masks = (1 << cell, (1 << cell) | (1 << (cell - 1)))
    for visited in visited_masks:
        expected = chess_neighbors(board, path, visited, flags)
        mask = neighbors_mask(
            board, visited, cell_id=cell, flags=flags, graph_ctx=ctx
        )
        assert sorted(expected) == sorted(iter_mask(mask))


def test_chess_neighbors_mask_parity_rook():
    board = _chess_piece_board(CurseType.CHESS_ROOK)
    _assert_chess_mask_parity(board)


def test_chess_neighbors_mask_parity_knight():
    board = _chess_piece_board(
        CurseType.CHESS_KNIGHT,
        blockers={6: (CurseType.CHESS_PAWN, "black")},
    )
    _assert_chess_mask_parity(board)


def test_chess_neighbors_mask_parity_bishop():
    board = _chess_piece_board(
        CurseType.CHESS_BISHOP,
        blockers={21: (CurseType.CHESS_PAWN, "white")},
    )
    _assert_chess_mask_parity(board)


def test_chess_neighbors_mask_parity_queen():
    board = _chess_piece_board(
        CurseType.CHESS_QUEEN,
        blockers={8: (CurseType.CHESS_ROOK, "black")},
    )
    _assert_chess_mask_parity(board)


def test_chess_neighbors_mask_parity_king():
    board = _chess_piece_board(CurseType.CHESS_KING)
    _assert_chess_mask_parity(board)


def test_chess_fast_path_matches_legacy_masks():
    """Optimized graph_ctx paths must match board-lookup fallbacks."""
    cases = [
        (
            CurseType.CHESS_KNIGHT,
            "white",
            {},
            lambda b, vm, side, ctx: knight_neighbors_mask(
                b, 12, vm, moving_side=side, graph_ctx=None
            ),
            lambda b, vm, side, ctx: knight_neighbors_mask(
                b, 12, vm, moving_side=side, graph_ctx=ctx
            ),
        ),
        (
            CurseType.CHESS_KING,
            "white",
            {},
            lambda b, vm, side, ctx: king_neighbors_mask(
                b, 12, vm, moving_side=side, graph_ctx=None
            ),
            lambda b, vm, side, ctx: king_neighbors_mask(
                b, 12, vm, moving_side=side, graph_ctx=ctx
            ),
        ),
        (
            CurseType.CHESS_ROOK,
            "white",
            {14: (CurseType.CHESS_PAWN, "black")},
            lambda b, vm, side, ctx: _ray_neighbors_mask(
                b, 12, vm, moving_side=side, allies_can_take=False,
                straight=True, graph_ctx=None,
            ),
            lambda b, vm, side, ctx: _ray_neighbors_mask(
                b, 12, vm, moving_side=side, allies_can_take=False,
                straight=True, graph_ctx=ctx,
            ),
        ),
        (
            CurseType.CHESS_BISHOP,
            "white",
            {21: (CurseType.CHESS_PAWN, "white")},
            lambda b, vm, side, ctx: _ray_neighbors_mask(
                b, 12, vm, moving_side=side, allies_can_take=False,
                diagonal=True, graph_ctx=None,
            ),
            lambda b, vm, side, ctx: _ray_neighbors_mask(
                b, 12, vm, moving_side=side, allies_can_take=False,
                diagonal=True, graph_ctx=ctx,
            ),
        ),
        (
            CurseType.CHESS_QUEEN,
            "white",
            {8: (CurseType.CHESS_ROOK, "black")},
            lambda b, vm, side, ctx: _ray_neighbors_mask(
                b, 12, vm, moving_side=side, allies_can_take=False,
                straight=True, diagonal=True, graph_ctx=None,
            ),
            lambda b, vm, side, ctx: _ray_neighbors_mask(
                b, 12, vm, moving_side=side, allies_can_take=False,
                straight=True, diagonal=True, graph_ctx=ctx,
            ),
        ),
    ]
    visited_masks = (1 << 12, (1 << 12) | (1 << 11))
    for curse, side, blockers, legacy_fn, fast_fn in cases:
        board = _chess_piece_board(curse, center_side=side, blockers=blockers)
        ctx = build_board_graph_context(board)
        for vm in visited_masks:
            legacy = legacy_fn(board, vm, side, ctx)
            fast = fast_fn(board, vm, side, ctx)
            assert sorted(iter_mask(legacy)) == sorted(iter_mask(fast))


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
