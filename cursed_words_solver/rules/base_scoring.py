"""Base tile and color scoring (wiki tile colors)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cursed_words_solver.models import Board, CurseType, Tile, TileColor, normalize_tile_glyph
from cursed_words_solver.letter_values import SCRABBLE_VALUES

if TYPE_CHECKING:
    from cursed_words_solver.models import Loadout


def _scrabble_value(letter: str) -> int:
    return SCRABBLE_VALUES.get((letter or "?").upper(), 1)


def _is_melmod_tile(tile: Tile) -> bool:
    return tile.metadata.get("source") == "melmod"


_CHESS_VOID_VALUES: dict[CurseType, int] = {
    CurseType.CHESS_KING: 15,
    CurseType.CHESS_QUEEN: 9,
    CurseType.CHESS_ROOK: 5,
    CurseType.CHESS_BISHOP: 3,
    CurseType.CHESS_KNIGHT: 3,
    CurseType.CHESS_PAWN: 1,
}


def _void_penalty_steps_for_tile(tile: Tile, loadout: Loadout | None) -> int:
    """Per-tile void penalty steps from melmod export, else encounter-effective grid."""
    raw = (tile.metadata or {}).get("void_penalty_steps")
    if raw is not None and raw != "":
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            pass
    if loadout is None:
        return 1
    from cursed_words_solver.models import CurseType, TileColor
    from cursed_words_solver.rules.scoring_conditions import grid_path_encounter_level

    if tile.color == TileColor.VOID and tile.curse == CurseType.LETTER:
        return grid_path_encounter_level(loadout)
    return 1


def _axolotl_in_boss_modifiers(loadout: Loadout) -> bool:
    """True when axolotl is an active stacked boss (not mole floor-mod alone)."""
    if loadout.boss_id == "axolotl":
        return True
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    raw = extras.get("boss_modifiers")
    mods: list[str] = []
    if isinstance(raw, list):
        mods = [str(entry or "").strip().lower() for entry in raw]
    elif isinstance(raw, str) and raw.strip():
        import json

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                mods = [str(entry or "").strip().lower() for entry in parsed]
        except json.JSONDecodeError:
            mods = [s.strip().lower() for s in raw.split(",") if s.strip()]
    return "axolotl" in mods


def _axolotl_floor_modification(loadout: Loadout) -> int | None:
    from cursed_words_solver.rules.boss_effects import _parse_boss_modifier_floor_mods

    floor_mods = _parse_boss_modifier_floor_mods(loadout)
    if "axolotl" in floor_mods:
        return floor_mods["axolotl"]
    if loadout.boss_id == "axolotl":
        extras = loadout.extras if isinstance(loadout.extras, dict) else {}
        raw = extras.get("boss_floor_modification")
        if raw not in (None, ""):
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                return None
    return None


def _void_currency_face_value(tile: Tile, loadout: Loadout | None = None) -> int:
    """Void currency penalty magnitude (melmod packet.Score is 0 pre-negation)."""
    from cursed_words_solver.rules.scoring_conditions import (
        currency_letter_value,
        grid_number,
    )

    cv = currency_letter_value(tile)
    if loadout is not None and _axolotl_in_boss_modifiers(loadout):
        floor_mod = _axolotl_floor_modification(loadout)
        if floor_mod is not None:
            grid = grid_number(loadout) or 1
            scattered_level = max(1, grid - floor_mod)
            extras = loadout.extras if isinstance(loadout.extras, dict) else {}
            raw_mods = extras.get("boss_modifiers")
            boss_count = 1
            if isinstance(raw_mods, list):
                boss_count = len([m for m in raw_mods if str(m or "").strip()])
            elif loadout.boss_id:
                boss_count = 1
            grid_ok = (1 < grid <= 3) or (
                grid == 1 and boss_count > 1 and floor_mod >= grid
            )
            row_ok = tile.row < 3
            if grid == 1 and boss_count > 1:
                # top_first grid 1: bottom row (4) void currency also waived when stacked bosses.
                row_ok = row_ok or tile.row > 3
            if (
                floor_mod >= grid
                and scattered_level <= 1
                and grid_ok
                and row_ok
            ):
                return 0
    if cv >= 3:
        return 15
    return 5 * max(3, cv + 1)


def _void_face_value(tile: Tile, loadout: Loadout | None = None) -> int:
    """Magnitude to negate for void tiles when packet.Score is 0."""
    if tile.curse == CurseType.CURRENCY:
        return _void_currency_face_value(tile, loadout)
    if tile.curse == CurseType.NUMBER:
        if tile.number_value is not None:
            return tile.number_value
        if tile.letter.isdigit():
            return int(tile.letter)
    chess_val = _CHESS_VOID_VALUES.get(tile.curse)
    if chess_val is not None:
        return chess_val
    face = _scrabble_value(tile.letter)
    if (
        loadout is not None
        and tile.color == TileColor.VOID
        and tile.curse == CurseType.LETTER
    ):
        face += 10 * _void_penalty_steps_for_tile(tile, loadout)
    return face


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
    if color in (TileColor.BLUE,):
        return 1
    if color == TileColor.PURPLE:
        return 2
    return 0


def _cactus_growth_bonus(tile: Tile) -> int:
    raw = tile.metadata.get("cactus_growth", 1)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 1


def tile_base_contribution(
    tile: Tile, money: int = 0, loadout: Loadout | None = None
) -> float:
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
        if _is_melmod_tile(tile):
            # packet.Score 0 on void letters/numbers/chess is pre-negation;
            # wildcards and currency stay 0 (melmod export is final for currency).
            if (
                letter_base == 0
                and tile.curse != CurseType.WILDCARD
                and tile.curse != CurseType.CURRENCY
                and not tile.metadata.get("is_joker")
            ):
                letter_base = -abs(_void_face_value(tile, loadout))
        elif letter_base == 0:
            letter_base = -abs(_void_face_value(tile, loadout))
        else:
            letter_base = -abs(letter_base)
    elif color == TileColor.GOLD:
        letter_base = money

    if color == TileColor.CACTUS:
        return letter_base + _cactus_growth_bonus(tile)

    bonus = _color_bonus(tile, letter_base)
    return letter_base + bonus


def microscope_init_contribution(
    tile: Tile, money: int = 0, loadout: Loadout | None = None
) -> float:
    """Microscope init: packet base_score, except VOID where 0 means pre-negation."""
    if tile.color == TileColor.VOID:
        return tile_base_contribution(tile, money, loadout)
    return float(tile.base_score)


def score_word_base(
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout | None = None,
) -> tuple[float, dict]:
    """Sum base contributions along path."""
    total = 0
    breakdown: list[dict] = []
    for i, idx in enumerate(path):
        tile = board.get_by_index(idx)
        contrib = tile_base_contribution(tile, board.money, loadout)
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
