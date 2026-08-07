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


def test_spicy_pepper_plus_red_envelope_allows_face_s_and_e() -> None:
    """Both remaps stay optional when Spicy Pepper and Red Envelope are active."""
    tile = Tile(0, 0, "N", "N", 1, TileColor.RED, CurseType.LETTER)
    opts = set(
        resolve_letter_options(
            tile, 0, flags=FLAG_RED_AS_S | FLAG_RED_AS_E
        )
    )
    assert opts == {"e", "n", "s"}


def test_purple_spicy_pepper_counts_as_red() -> None:
    """Game IsTileType(red): purple letters get Spicy Pepper s option."""
    tile = Tile(0, 0, "W", "W", 1, TileColor.PURPLE, CurseType.LETTER)
    opts = set(resolve_letter_options(tile, 0, flags=FLAG_RED_AS_S))
    assert opts == {"s", "w"}


def test_spicy_pepper_alignment_pattern_wildcards_multi_option_reds() -> None:
    """Dictionary resolve must not lock Spicy Pepper reds to substitute-only 's'."""
    from cursed_words_solver.models import Board, Loadout, LoadoutItem
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
    from cursed_words_solver.suggestion import _alignment_pattern_for_path

    def letter(r: int, c: int, ch: str, *, color: TileColor = TileColor.RED) -> Tile:
        return Tile(r, c, ch.lower(), ch.upper(), 1.0, color, CurseType.LETTER)

    tiles = [[letter(r, c, "A") for c in range(5)] for r in range(5)]
    tiles[0][0] = letter(0, 0, "U")
    tiles[0][1] = letter(0, 1, "E")
    board = Board(tiles=tiles)
    loadout = Loadout(
        stamps=[LoadoutItem(id="spicy_pepper", name="Spicy Pepper", kind="stamp")]
    )
    flags = stamp_search_flags(loadout)
    pattern = _alignment_pattern_for_path(board, [0, 1], flags)
    assert pattern == "??"
    assert "s" not in pattern

