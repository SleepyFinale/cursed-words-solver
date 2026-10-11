"""One verification per TileType hook (game GetValue / ScoreCalculation parity)."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Tile, TileColor, tile_counts_as_color
from cursed_words_solver.rules.base_scoring import tile_base_contribution
from cursed_words_solver.rules.quest_movement import _white_portal_mask


def _letter(color: TileColor, *, base: float = 1, letter: str = "A") -> Tile:
    return Tile(0, 0, letter, letter, base, color, CurseType.LETTER)


def test_normal_scrabble_letter() -> None:
    assert tile_base_contribution(_letter(TileColor.COLORLESS, letter="Q", base=10)) == 10


def test_red_color_plus_one() -> None:
    assert tile_base_contribution(_letter(TileColor.RED)) == 2


def test_blue_color_plus_one() -> None:
    assert tile_base_contribution(_letter(TileColor.BLUE)) == 2


def test_shiny_flat_fifty_ocr() -> None:
    assert tile_base_contribution(_letter(TileColor.SHINY)) == 50


def test_void_negate_face() -> None:
    t = _letter(TileColor.VOID, letter="E")
    t.base_score = 0
    assert tile_base_contribution(t) == -1


def test_cactus_melmod_packet_authoritative() -> None:
    t = _letter(TileColor.CACTUS, base=5)
    t.metadata["source"] = "melmod"
    t.metadata["cactus_growth"] = 9
    assert tile_base_contribution(t) == 5


def test_gold_uses_player_money() -> None:
    board = Board(tiles=[[_letter(TileColor.GOLD)]], money=12)
    assert tile_base_contribution(board.tiles[0][0], board.money) == 12


def test_purple_counts_as_red_and_blue() -> None:
    t = _letter(TileColor.PURPLE)
    assert tile_counts_as_color(t, TileColor.RED)
    assert tile_counts_as_color(t, TileColor.BLUE)
    assert tile_base_contribution(t) == 3


def test_white_portal_teleport_mask() -> None:
    board = Board(
        tiles=[
            [_letter(TileColor.WHITE) for _ in range(5)]
            for _ in range(5)
        ]
    )
    active_mask = (1 << 25) - 1
    mask = _white_portal_mask(board, 0, 1 << 0, active_mask=active_mask)
    assert mask & (1 << 12)
