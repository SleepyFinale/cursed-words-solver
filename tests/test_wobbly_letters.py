"""Wobbly / variable letter resolution during search."""

from __future__ import annotations

from cursed_words_solver.models import CurseType, Tile, TileColor
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_J_AS_H_OR_Y,
    FLAG_RED_AS_E,
)
from cursed_words_solver.search import resolve_letter_options


def test_wobbly_tile_includes_physical_and_transformed() -> None:
    tile = Tile(
        0, 0, "r", "r", 1, TileColor.RED, CurseType.LETTER, metadata={"is_wobbly": True}
    )
    opts = resolve_letter_options(tile, 0, flags=FLAG_RED_AS_E)
    assert "r" in opts
    assert "e" in opts


def test_jellyfish_branches_j_to_h_or_y() -> None:
    tile = Tile(0, 0, "j", "j", 1, TileColor.COLORLESS, CurseType.LETTER)
    opts = resolve_letter_options(tile, 0, flags=FLAG_J_AS_H_OR_Y)
    assert set(opts) == {"h", "y"}
