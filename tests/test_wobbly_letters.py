"""Wobbly / variable letter resolution during search."""

from __future__ import annotations

from cursed_words_solver.models import CurseType, Tile, TileColor
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_J_AS_H_OR_Y,
    FLAG_RED_AS_E,
    FLAG_RED_AS_S,
    FLAG_RED_LETTER_PLUS_MINUS_ONE,
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


def test_red_envelope_only_allows_face_and_e() -> None:
    tile = Tile(0, 0, "V", "V", 1, TileColor.RED, CurseType.LETTER)
    assert set(resolve_letter_options(tile, 0, flags=FLAG_RED_AS_E)) == {"e", "v"}


def test_suspension_bridge_only_allows_face_plus_minus_one() -> None:
    tile = Tile(0, 0, "V", "V", 1, TileColor.RED, CurseType.LETTER)
    assert set(
        resolve_letter_options(tile, 0, flags=FLAG_RED_LETTER_PLUS_MINUS_ONE)
    ) == {"u", "v", "w"}


def test_red_envelope_plus_suspension_bridge_does_not_plus_minus_e() -> None:
    """Bridge ±1 is vs face only; envelope adds e without inventing d/f."""
    tile = Tile(0, 0, "V", "V", 1, TileColor.RED, CurseType.LETTER)
    opts = set(
        resolve_letter_options(
            tile, 0, flags=FLAG_RED_AS_E | FLAG_RED_LETTER_PLUS_MINUS_ONE
        )
    )
    assert opts == {"e", "u", "v", "w"}
    assert "d" not in opts
    assert "f" not in opts


def test_spicy_pepper_plus_suspension_bridge_does_not_plus_minus_s() -> None:
    tile = Tile(0, 0, "V", "V", 1, TileColor.RED, CurseType.LETTER)
    opts = set(
        resolve_letter_options(
            tile, 0, flags=FLAG_RED_AS_S | FLAG_RED_LETTER_PLUS_MINUS_ONE
        )
    )
    assert opts == {"s", "u", "v", "w"}
    assert "r" not in opts
    assert "t" not in opts
