"""Curse/glyph catalog and base rules."""

from __future__ import annotations

import pytest

from cursed_words_solver.models import CurseType, Tile, TileColor, curse_type_from_key, normalize_glyph_curse
from cursed_words_solver.rules.base_scoring import tile_base_contribution
from tests.catalog.tiles._coverage import curse_entries


@pytest.mark.parametrize("entry", curse_entries(), ids=lambda e: e["game_glyph_type"])
def test_curse_catalog_maps_to_enum(entry: dict) -> None:
    key = entry["melmod_curse"].replace("chess_*", "chess_pawn")
    assert curse_type_from_key(key) != CurseType.UNKNOWN or entry["game_glyph_type"] == "None"


def test_item_zero_base() -> None:
    t = Tile(0, 0, "?", "?", 0, TileColor.RED, CurseType.ITEM)
    assert tile_base_contribution(t) == 0


def test_blank_normalizes_to_wildcard() -> None:
    assert normalize_glyph_curse(CurseType.BLANK) == CurseType.WILDCARD


def test_currency_zero_letter_base() -> None:
    t = Tile(0, 0, "$", "S", 0, TileColor.COLORLESS, CurseType.CURRENCY)
    assert tile_base_contribution(t) == 0
