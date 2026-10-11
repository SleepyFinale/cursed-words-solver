"""Static topology bitboards and neighbor mask parity."""

from __future__ import annotations

from cursed_words_solver.graph_bitboard import KNIGHT_ADJACENCY, KNIGHT_TARGETS, KING_STEP_MASK, NEIGHBORS_8, NEIGHBORS_8_WRAP, RAY_LINES, STANDARD_ADJACENCY, STANDARD_ADJACENCY_WRAP, iter_mask, mask_from_indices
from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.rules.chess_tiles import DIRS_8, index_of


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


def test_ray_lines_for_board_6x6_bishop_diagonal():
    """6x6 boards must not reuse 5x5 RAY_LINES indices for sliding pieces."""
    from cursed_words_solver.graph_bitboard import ray_lines_for_board

    tiles = [
        [
            Tile(
                row=r,
                col=c,
                char="a",
                letter="A",
                base_score=1.0,
                curse=CurseType.LETTER,
                color=TileColor.COLORLESS,
            )
            for c in range(6)
        ]
        for r in range(6)
    ]
    board = Board(rows=6, cols=6, tiles=tiles)
    lines = ray_lines_for_board(board, horizontal_wrap=False)
    # DIRS_8 index 7 = (1, 1) southeast
    assert lines[0][7] == (7, 14, 21, 28, 35)
    # 5x5 diagonal indices would be (6, 12, 18, 24) — wrong on 6x6
    assert lines[0][7] != (6, 12, 18, 24)


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


def test_mask_from_indices_roundtrip():
    indices = [0, 5, 12, 24]
    m = mask_from_indices(indices)
    assert list(iter_mask(m)) == indices


def test_static_adjacency_aliases():
    assert STANDARD_ADJACENCY is NEIGHBORS_8
    assert STANDARD_ADJACENCY_WRAP is NEIGHBORS_8_WRAP
    assert KNIGHT_ADJACENCY is KNIGHT_TARGETS
    assert KING_STEP_MASK is NEIGHBORS_8
