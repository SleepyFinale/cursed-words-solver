"""Base tile and color scoring (wiki tile colors)."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.letter_values import SCRABBLE_VALUES


def _scrabble_value(letter: str) -> int:
    return SCRABBLE_VALUES.get((letter or "?").upper(), 1)


def _is_melmod_tile(tile: Tile) -> bool:
    return tile.metadata.get("source") == "melmod"


def _void_face_value(tile: Tile) -> int:
    """Magnitude to negate for void tiles when packet.Score is 0."""
    if tile.curse == CurseType.NUMBER:
        if tile.number_value is not None:
            return tile.number_value
        if tile.letter.isdigit():
            return int(tile.letter)
    return _scrabble_value(tile.letter)


def _color_bonus(tile: Tile, letter_base: int) -> int:
    """Add color bonus only when base_score is still the raw letter value.

    Melmod/game packet.Score already includes red/blue/cactus/purple modifiers.
    """
    if _is_melmod_tile(tile):
        return 0
    if letter_base > _scrabble_value(tile.letter):
        return 0

    color = tile.color
    if color == TileColor.RED:
        return 1
    if color in (TileColor.BLUE, TileColor.CACTUS):
        return 1
    if color == TileColor.PURPLE:
        return 2
    return 0


def tile_base_contribution(tile: Tile, money: int = 0) -> float:
    """Per-tile base score before stickers."""
    if tile.curse == CurseType.ITEM:
        return 0

    letter_base = tile.base_score
    if tile.curse == CurseType.CURRENCY:
        letter_base = 0

    color = tile.color

    if color == TileColor.SHINY:
        if _is_melmod_tile(tile):
            # packet.Score from melmod; OCR path uses flat 50 below
            pass
        else:
            # Shiny gives flat 50 base, not affected by letter manipulators
            return 50
    if color == TileColor.VOID:
        if letter_base == 0 or _is_melmod_tile(tile):
            letter_base = -abs(_void_face_value(tile))
        else:
            letter_base = -abs(letter_base)
    elif color == TileColor.GOLD:
        letter_base = money

    bonus = _color_bonus(tile, letter_base)
    return letter_base + bonus


def score_word_base(board: Board, path: list[int], word: str) -> tuple[float, dict]:
    """Sum base contributions along path."""
    total = 0
    breakdown: list[dict] = []
    for i, idx in enumerate(path):
        tile = board.get_by_index(idx)
        contrib = tile_base_contribution(tile, board.money)
        total += contrib
        breakdown.append(
            {
                "index": idx,
                "char": word[i] if i < len(word) else tile.letter,
                "color": tile.color.value,
                "curse": tile.curse.value,
                "contrib": contrib,
            }
        )
    return float(total), {"base_total": total, "tiles": breakdown}
