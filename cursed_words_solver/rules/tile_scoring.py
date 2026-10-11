"""Pre-item tile scoring: glitch settle, currency, pink, poison (game ScoreCalculation order)."""

from __future__ import annotations


from cursed_words_solver.models import (
    CurseType,
    TileColor,
)

# SettleGlitchTiles colour pool (excludes Glitch)
_GLITCH_COLOR_POOL: list[TileColor] = [
    TileColor.COLORLESS,
    TileColor.BLUE,
    TileColor.CACTUS,
    TileColor.GOLD,
    TileColor.GREEN,
    TileColor.PURPLE,
    TileColor.PINK,
    TileColor.WHITE,
    TileColor.RED,
    TileColor.VOID,
    TileColor.SHINY,
]

_CHESS_CURSES = (
    CurseType.CHESS_PAWN,
    CurseType.CHESS_BISHOP,
    CurseType.CHESS_ROOK,
    CurseType.CHESS_KNIGHT,
    CurseType.CHESS_QUEEN,
    CurseType.CHESS_KING,
)


