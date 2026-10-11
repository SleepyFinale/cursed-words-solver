"""Per-colour base score parity (OCR path without melmod packet)."""

from __future__ import annotations

import pytest

from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.rules.base_scoring import tile_base_contribution
from tests.catalog.tiles._coverage import color_entries


def _tile(color: TileColor, letter: str = "A", base: float = 1) -> Tile:
    return Tile(
        row=0,
        col=0,
        char=letter,
        letter=letter,
        base_score=base,
        color=color,
        curse=CurseType.LETTER,
    )


@pytest.mark.parametrize("entry", color_entries(), ids=lambda e: e["solver_color"])
def test_color_catalog_has_solver_enum(entry: dict) -> None:
    assert hasattr(TileColor, entry["solver_color"].upper())


def test_red_plus_one() -> None:
    assert tile_base_contribution(_tile(TileColor.RED)) == 2


def test_blue_plus_one() -> None:
    assert tile_base_contribution(_tile(TileColor.BLUE)) == 2


def test_purple_plus_two() -> None:
    assert tile_base_contribution(_tile(TileColor.PURPLE)) == 3


def test_shiny_flat_fifty() -> None:
    assert tile_base_contribution(_tile(TileColor.SHINY)) == 50


def test_void_negates_letter() -> None:
    t = _tile(TileColor.VOID, "Q")
    t.base_score = 0
    assert tile_base_contribution(t) == -10


def test_cactus_uses_growth_metadata() -> None:
    t = _tile(TileColor.CACTUS)
    t.metadata["cactus_growth"] = 3
    assert tile_base_contribution(t) == 4


def test_cactus_melmod_uses_packet_only() -> None:
    t = _tile(TileColor.CACTUS, base=3)
    t.metadata["source"] = "melmod"
    t.metadata["cactus_growth"] = 2
    assert tile_base_contribution(t) == 3


def test_cactus_consumable_rack_uses_packet_only() -> None:
    t = _tile(TileColor.CACTUS, base=1)
    t.metadata["source"] = "consumable_rack"
    t.metadata["cactus_growth"] = 0
    assert tile_base_contribution(t) == 1


def test_cactus_was_consumable_uses_packet_only() -> None:
    t = _tile(TileColor.CACTUS, base=1)
    t.metadata["source"] = "melmod"
    t.metadata["was_consumable"] = True
    t.metadata["cactus_growth"] = 2
    assert tile_base_contribution(t) == 1


def test_gold_uses_money() -> None:
    board = Board(tiles=[[_tile(TileColor.GOLD)]], money=7)
    assert tile_base_contribution(board.tiles[0][0], board.money) == 7
