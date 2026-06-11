"""Board helpers for simulator (wraps models.Board)."""

from __future__ import annotations

import copy

from cursed_words_solver.models import Board, Tile


def clone_board(board: Board) -> Board:
    """Deep-copy board tiles and metadata."""
    tiles = [
        [
            Tile(
                row=t.row,
                col=t.col,
                char=t.char,
                letter=t.letter,
                base_score=t.base_score,
                color=t.color,
                curse=t.curse,
                number_value=t.number_value,
                fraction_value=t.fraction_value,
                ocr_confidence=t.ocr_confidence,
                metadata=dict(t.metadata),
            )
            for t in row
        ]
        for row in board.tiles
    ]
    return Board(
        tiles=tiles,
        money=board.money,
        rows=board.rows,
        cols=board.cols,
        active=list(board.active),
        playable_origin=board.playable_origin,
        playable_min_row=board.playable_min_row,
        playable_max_row=board.playable_max_row,
        playable_min_col=board.playable_min_col,
        playable_max_col=board.playable_max_col,
    )


def board_snapshot_dict(board: Board) -> dict:
    """Compact board summary for canonical state."""
    active_count = sum(1 for i in range(25) if board.is_active_index(i))
    return {
        "money": board.money,
        "rows": board.rows,
        "cols": board.cols,
        "active_count": active_count,
        "playable_origin": board.playable_origin,
    }
