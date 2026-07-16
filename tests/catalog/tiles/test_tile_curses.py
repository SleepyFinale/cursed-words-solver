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


def test_currency_ocr_red_gets_color_bonus() -> None:
    """OCR/synthetic: glyph face 0 + red +1 (Tile.GetValue parity)."""
    t = Tile(0, 0, "₱", "P", 0, TileColor.RED, CurseType.CURRENCY)
    assert tile_base_contribution(t) == 1


def test_currency_ocr_purple_gets_color_bonus() -> None:
    t = Tile(0, 0, "₱", "P", 0, TileColor.PURPLE, CurseType.CURRENCY)
    assert tile_base_contribution(t) == 2


def test_currency_placed_consumable_uses_packet_base_score() -> None:
    """Rack/placed packets already include color; do not zero then skip bonus."""
    t = Tile(0, 0, "₱", "P", 1.0, TileColor.RED, CurseType.CURRENCY)
    t.metadata["source"] = "consumable_rack"
    t.metadata["was_consumable"] = True
    assert tile_base_contribution(t) == 1.0


def test_currency_melmod_uses_packet_base_score() -> None:
    t = Tile(0, 0, "₱", "P", 1.0, TileColor.RED, CurseType.CURRENCY)
    t.metadata["source"] = "melmod"
    assert tile_base_contribution(t) == 1.0
