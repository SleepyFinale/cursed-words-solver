"""Shared helpers for loadout scoring conditions (wiki-aligned)."""

from __future__ import annotations

import json
from typing import Any

from cursed_words_solver.models import (
    tile_counts_as_color,
    CHESS_CURSES,
    CURRENCY_MAP,
    Board,
    CurseType,
    Loadout,
    Tile,
    TileColor,
    normalize_tile_glyph,
)
from cursed_words_solver.rules.base_scoring import _scrabble_value
from cursed_words_solver.rules.chess_tiles import (
    chess_side,
    chess_side_known,
    identical_chess_piece,
    is_chess_capture_step,
    is_chess_piece,
    solve_has_chess_pieces,
)
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_CARD_SUIT_FIRST_LETTER,
    FLAG_CHESS_ALLIES_CAN_TAKE,
    FLAG_J_AS_H_OR_Y,
    FLAG_RED_AS_E,
    FLAG_RED_AS_S,
    FLAG_RED_LETTER_PLUS_MINUS_ONE,
    FLAG_Z_AS_S,
    SearchFlagsMask,
    flag_set,
    flag_test,
    stamp_search_flags_mask,
)
from cursed_words_solver.rules.fraction_tiles import fraction_parts, is_fraction_tile

NON_COLOUR_FOR_NUMBER_BONUS = frozenset(
    {
        TileColor.COLORLESS,
        TileColor.UNKNOWN,
        TileColor.WHITE,
    }
)

# Rainbow, Dango, Artist's Palette, etc.: WHITE is a distinct tile colour.
NON_COLOUR_FOR_UNIQUE_COUNT = frozenset(
    {
        TileColor.COLORLESS,
        TileColor.UNKNOWN,
    }
)

NON_COLOUR_FOR_NEAPOLITAN = frozenset(
    {
        TileColor.COLORLESS,
        TileColor.UNKNOWN,
        TileColor.WHITE,
        TileColor.VOID,
    }
)

VOWELS = frozenset("aeiou")
VWXYZ = frozenset("vwxyz")
RED_NOTES = frozenset("abcdefg")
STRAIGHT_RANK_ORDER = "23456789TJQKA"
FACE_CARD_RANKS = frozenset("JQK")
POKER_RANKS = frozenset("A23456789TJQK")
CARD_SUIT_FIRST_LETTER: dict[str, str] = {
    "hearts": "h",
    "spades": "s",
    "clubs": "c",
    "diamonds": "d",
}

def sticker_scaled_int(level: int, base: int, upgrade: int) -> int:
    """Wiki: base + upgrade × (level − 1)."""
    return int(base) + int(upgrade) * max(int(level) - 1, 0)


def sticker_scaled_float(level: int, base: float, upgrade: float) -> float:
    return float(base) + float(upgrade) * max(int(level) - 1, 0)


def sticker_rule_int(level: int, rule: dict) -> int:
    if "base" in rule:
        return sticker_scaled_int(level, int(rule["base"]), int(rule.get("upgrade", 0)))
    return int(rule.get("value", 0)) * max(level, 1)


def sticker_rule_float(level: int, rule: dict) -> float:
    if "base" in rule:
        return sticker_scaled_float(level, float(rule["base"]), float(rule.get("upgrade", 0)))
    return float(rule.get("value", 0)) * max(level, 1)


def pin_left_level(loadout: Loadout) -> int:
    try:
        return int((loadout.extras or {}).get("pin_left_level", 0))
    except (TypeError, ValueError):
        return 0


def pin_right_level(loadout: Loadout) -> int:
    try:
        return int((loadout.extras or {}).get("pin_right_level", 0))
    except (TypeError, ValueError):
        return 0


def pin_left_variable(loadout: Loadout) -> int | None:
    try:
        return int((loadout.extras or {}).get("pin_left_variable"))
    except (TypeError, ValueError):
        return None


def pin_right_variable(loadout: Loadout) -> int | None:
    try:
        return int((loadout.extras or {}).get("pin_right_variable"))
    except (TypeError, ValueError):
        return None


def _extra_bool(loadout: Loadout, key: str) -> bool:
    val = (loadout.extras or {}).get(key)
    if val is True or val == "true" or val == "1" or val == 1:
        return True
    if isinstance(val, str) and val.lower() in ("true", "yes", "1"):
        return True
    return False


def _extra_int(loadout: Loadout, key: str, default: int = 0) -> int:
    try:
        return int((loadout.extras or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def _extra_letter(loadout: Loadout, key: str) -> str:
    val = (loadout.extras or {}).get(key, "")
    if not val:
        return ""
    return str(val).strip().lower()[:1]


def is_consumable_tile(tile: Tile) -> bool:
    val = tile.metadata.get("consumable")
    return val is True or val == "true" or val == 1 or val == "1"


def is_placed_consumable_tile(tile: Tile) -> bool:
    return tile.metadata.get("was_consumable") is True


def placed_consumable_indices(board: Board) -> frozenset[int]:
    return frozenset(
        i
        for i, tile in enumerate(board.flat)
        if board.active[i] and is_placed_consumable_tile(tile)
    )


def is_cursed_tile(tile: Tile) -> bool:
    """Mirror game Tile.IsCursed(): non-letter glyphs, any CardSuit, or wobbly letters."""
    if tile.curse not in (CurseType.LETTER, CurseType.UNKNOWN):
        return True
    # CardSuit != 0. Suit.Joker on a letter glyph is cleared to None in
    # Tile.SetGlyphType; melmod may still export stale joker suit after placing a
    # letter consumable on a former joker card — ignore that for curse checks.
    suit = card_suit(tile)
    if suit and suit not in ("none", "joker"):
        return True
    if is_joker_tile(tile):
        return True
    # IsDisplayingAsVariableLetter parity when melmod already set live is_wobbly.
    if tile.metadata.get("is_wobbly"):
        return True
    return False


def tile_is_wobbly_from_loadout(tile: Tile, loadout: Loadout | None) -> bool:
    """Mirror TileSelection.IsWobbly from stamp letter-behavior flags.

    Game ``TileSelection.IsCursed()`` returns true when ``IsWobbly`` (set at
    selection from ``IsDisplayingAsVariableLetter``). Melmod often omits
    ``is_wobbly`` metadata, so Lexographer must infer wobbliness from equipped
    stamps the same way search resolves alternate letters.
    """
    if tile.metadata.get("is_wobbly"):
        return True
    if not loadout or tile.curse not in (CurseType.LETTER, CurseType.UNKNOWN):
        return False
    flags = stamp_search_flags_mask(loadout)
    if not flags:
        return False
    face = (tile.letter or tile.char or "").strip().lower()
    if len(face) != 1 or not face.isalpha():
        face = ""
    # Suspension Bridge: all red letters behave as ±1 → wobbly.
    if (
        flag_test(flags, FLAG_RED_LETTER_PLUS_MINUS_ONE)
        and tile_counts_as_color(tile, TileColor.RED)
        and tile.curse == CurseType.LETTER
    ):
        return True
    # Red Envelope: non-"e" red letters wobble toward E.
    if (
        flag_test(flags, FLAG_RED_AS_E)
        and tile_counts_as_color(tile, TileColor.RED)
        and face
        and face != "e"
    ):
        return True
    # Spicy Pepper: non-"s" red letters wobble toward S.
    if (
        flag_test(flags, FLAG_RED_AS_S)
        and tile_counts_as_color(tile, TileColor.RED)
        and face
        and face != "s"
    ):
        return True
    if flag_test(flags, FLAG_Z_AS_S) and face == "z":
        return True
    if flag_test(flags, FLAG_J_AS_H_OR_Y) and face == "j":
        return True
    # Card Shark: suited letter whose face ≠ suit letter is wobbly
    # (Tile.IsDisplayingAsVariableLetter CardShark branch).
    if flag_test(flags, FLAG_CARD_SUIT_FIRST_LETTER) and is_card_tile(tile):
        suit = card_suit(tile)
        suit_letter = {
            "clubs": "c",
            "diamonds": "d",
            "hearts": "h",
            "spades": "s",
        }.get(suit or "")
        if suit_letter and face and face != suit_letter:
            # Game: Spades + Letter "$" is not wobbly.
            if suit == "spades" and (tile.letter or tile.char or "") == "$":
                return False
            return True
    return False


def tile_is_cursed_for_lexographer(tile: Tile, loadout: Loadout | None) -> bool:
    """TileSelection.IsCursed for Lexographer: base cursed OR loadout-inferred wobbly."""
    if is_cursed_tile(tile):
        return True
    return tile_is_wobbly_from_loadout(tile, loadout)


def is_joker_tile(tile: Tile) -> bool:
    """True for melmod is_joker flag or live Suit.Joker on non-letter glyphs.

    path_tiles often export card_suit=joker without is_joker on wildcard tiles.
    Stale card_suit=joker on plain LETTER tiles is cleared in-game (SetGlyphType)
    and must not count as a joker.
    """
    val = tile.metadata.get("is_joker")
    if val is True or val == "true" or val == 1 or val == "1":
        return True
    raw = tile.metadata.get("card_suit")
    if raw and str(raw).strip().lower() == "joker":
        if tile.curse in (CurseType.LETTER, CurseType.UNKNOWN):
            return False
        return True
    return False


def is_card_tile(tile: Tile) -> bool:
    if is_joker_tile(tile):
        return False
    if tile.curse == CurseType.CARD:
        return True
    raw = tile.metadata.get("card_suit")
    if not raw:
        return False
    suit = str(raw).strip().lower()
    # Stale Suit.Joker on letters is not a real card (game clears to None).
    if suit in ("", "joker", "none"):
        return False
    return True


def card_suit(tile: Tile) -> str | None:
    raw = tile.metadata.get("card_suit")
    if raw:
        return str(raw).strip().lower()
    return None


def card_rank(tile: Tile) -> str | None:
    raw = tile.metadata.get("card_rank")
    if raw:
        return str(raw).strip().upper()[:1]
    if is_card_tile(tile) and tile.letter and tile.letter != "?":
        return tile.letter.strip().upper()[:1]
    return None


CHESS_PIECE_VALUES: dict[CurseType, int] = {
    CurseType.CHESS_KING: 15,
    CurseType.CHESS_QUEEN: 9,
    CurseType.CHESS_ROOK: 5,
    CurseType.CHESS_BISHOP: 3,
    CurseType.CHESS_KNIGHT: 3,
    CurseType.CHESS_PAWN: 1,
}


def _has_take_metadata(tile: Tile) -> bool:
    val = tile.metadata.get("take") or tile.metadata.get("is_take")
    return val is True or val == "true" or val == 1 or val == "1"


def _chess_take_search_flags(
    loadout: Loadout | None,
    *,
    allies_can_take: bool = False,
    search_flags: SearchFlagsMask = 0,
) -> SearchFlagsMask:
    flags = search_flags
    if not flags and loadout is not None:
        flags = stamp_search_flags_mask(loadout)
    if allies_can_take:
        return flag_set(
            flags,
            FLAG_CHESS_ALLIES_CAN_TAKE,
        )
    return flags


def is_take_at_path_position(
    board: Board,
    path: list[int],
    pos: int,
    *,
    strict: bool = False,
    allies_can_take: bool = False,
    loadout: Loadout | None = None,
    search_flags: SearchFlagsMask = 0,
) -> bool:
    """Whether path[pos] counts as a chess capture landing square."""
    tile = board.get_by_index(path[pos])
    if _has_take_metadata(tile) and is_chess_piece(tile):
        if pos > 0 or strict:
            return True
    if strict or pos == 0:
        return False
    prefix = path[:pos]
    flags = _chess_take_search_flags(
        loadout,
        allies_can_take=allies_can_take,
        search_flags=search_flags,
    )
    if is_chess_capture_step(
        board,
        path[pos - 1],
        path[pos],
        allies_can_take=allies_can_take,
        path_prefix=prefix,
        visited=set(prefix),
        flags=flags,
        loadout=loadout,
    ):
        return True
    # White free-move tiles can step onto opponents without a legal chess attack
    # (e.g. king walking onto a checked square). Super 8 still counts those takes.
    from_tile = board.get_by_index(path[pos - 1])
    if (
        from_tile.color == TileColor.WHITE
        and is_chess_piece(from_tile)
        and is_chess_piece(tile)
        and chess_side_known(from_tile)
        and chess_side_known(tile)
    ):
        if chess_side(from_tile) != chess_side(tile):
            return True
        return bool(allies_can_take)
    return False


def chess_take_path_positions(
    board: Board,
    path: list[int],
    *,
    strict: bool = False,
    loadout: Loadout | None = None,
    search_flags: SearchFlagsMask = 0,
) -> list[int]:
    """Indices into path for tiles that count as takes."""
    if not solve_has_chess_pieces():
        return []
    return [
        i
        for i in range(len(path))
        if is_take_at_path_position(
            board,
            path,
            i,
            strict=strict,
            loadout=loadout,
            search_flags=search_flags,
        )
    ]


def chess_piece_value(tile: Tile) -> int:
    return CHESS_PIECE_VALUES.get(tile.curse, 0)


def _is_full_moon_chess_teleport_step(
    board: Board,
    path: list[int],
    pos: int,
    *,
    loadout: Loadout | None = None,
) -> bool:
    """True when path step pos is a Full Moon jump between identical chess pieces."""
    if pos < 1:
        return False
    from_idx, to_idx = path[pos - 1], path[pos]
    from_tile = board.get_by_index(from_idx)
    to_tile = board.get_by_index(to_idx)
    if not is_chess_piece(from_tile) or not is_chess_piece(to_tile):
        return False
    if not identical_chess_piece(from_tile, to_tile):
        return False
    prefix = path[:pos]
    flags = _chess_take_search_flags(loadout)
    return not is_chess_capture_step(
        board,
        from_idx,
        to_idx,
        path_prefix=prefix,
        visited=set(prefix),
        flags=flags,
        loadout=loadout,
    )


def _carousel_horse_level(loadout: Loadout | None) -> int:
    if not loadout:
        return 0
    for item in loadout.stickers:
        key = (item.id or item.name or "").lower().replace(" ", "_")
        if key == "carousel_horse":
            return max(int(item.level), 0)
    return 0


def _chess_prefix_score_on_path(board: Board, path: list[int], pos: int) -> int:
    """Sum chess tile base scores along path[0..pos]."""
    total = 0
    for i in range(pos + 1):
        tile = board.get_by_index(path[i])
        if is_chess_piece(tile):
            total += int(tile.base_score)
    return total


def _first_full_moon_path_index(board: Board, path: list[int]) -> int | None:
    for i in range(1, len(path)):
        if _is_full_moon_chess_teleport_step(board, path, i):
            return i
    return None


def _letter_gap_since_prev_take(
    board: Board, path: list[int], pos: int, take_positions: list[int]
) -> bool:
    prev = [t for t in take_positions if t < pos]
    if not prev:
        return False
    start = prev[-1] + 1
    for p in range(start, pos):
        if not is_chess_piece(board.get_by_index(path[p])):
            return True
    return False


def _movie_camera_sticker_level(loadout: Loadout | None) -> int:
    if not loadout:
        return 0
    for item in loadout.stickers:
        key = (item.id or item.name or "").lower().replace(" ", "_")
        if key == "movie_camera":
            return max(int(item.level), 0)
    return 0


def movie_camera_take_piece_value_at(
    board: Board,
    path: list[int],
    pos: int,
    *,
    loadout: Loadout | None = None,
    strict: bool = False,
) -> int:
    """Movie Camera piece value for a capture landing at path[pos]."""
    landing = board.get_by_index(path[pos])
    from_tile = board.get_by_index(path[pos - 1])
    piece = chess_piece_value(landing)
    base = int(landing.base_score)
    from_piece = chess_piece_value(from_tile) if is_chess_piece(from_tile) else 0
    from_base = int(from_tile.base_score) if is_chess_piece(from_tile) else 0
    take_positions = movie_camera_take_path_positions(
        board, path, strict=strict, loadout=loadout
    )
    multi_take = len(take_positions) >= 2
    carousel = _carousel_horse_level(loadout) >= 3
    mc_limit = _movie_camera_sticker_level(loadout)
    overflow = mc_limit > 0 and len(take_positions) > mc_limit
    if pos >= 2 and _is_full_moon_chess_teleport_step(
        board, path, pos - 1, loadout=loadout
    ):
        if overflow and carousel and multi_take:
            return _chess_prefix_score_on_path(board, path, pos)
        if from_base > from_piece * 4:
            return max(from_base, base, piece)
        if (
            not identical_chess_piece(from_tile, landing)
            and from_base > from_piece * 2
            and landing.curse
            in (CurseType.CHESS_QUEEN, CurseType.CHESS_ROOK, CurseType.CHESS_KING)
        ):
            return max(from_base, base, piece)
        from_half = from_base // 2
        land_half = base // 2
        fm_val = max(from_half, land_half, piece)
        if (
            is_chess_piece(landing)
            and base == piece * 2
            and landing.curse in (CurseType.CHESS_ROOK, CurseType.CHESS_QUEEN)
        ):
            return max(fm_val, base)
        return fm_val
    if strict:
        return piece
    if is_chess_piece(landing):
        if (
            overflow
            and carousel
            and multi_take
            and _letter_gap_since_prev_take(board, path, pos, take_positions)
        ):
            fm_idx = _first_full_moon_path_index(board, path)
            if fm_idx is not None:
                gap_val = (
                    _chess_prefix_score_on_path(board, path, pos)
                    - _chess_prefix_score_on_path(board, path, fm_idx)
                    + from_base
                    - 1
                )
                return max(from_base + base, gap_val)
        if (
            overflow
            and carousel
            and multi_take
            and is_chess_piece(from_tile)
            and from_base + base > piece
        ):
            if identical_chess_piece(from_tile, landing) and from_base >= base:
                return from_base
            return from_base + base
        if carousel and multi_take and base > piece * 2:
            if identical_chess_piece(from_tile, landing) and from_base >= base:
                return from_base
            return from_base + base
        if carousel and multi_take and is_chess_piece(from_tile) and base < piece * 2:
            if identical_chess_piece(from_tile, landing):
                return from_base
            if from_base > piece * 2:
                return from_base + base
        if base > piece * 2:
            if multi_take:
                return min(base, piece * 2 + 4)
            return base
        if base == piece * 2 and landing.curse in (
            CurseType.CHESS_ROOK,
            CurseType.CHESS_QUEEN,
        ):
            if (
                is_chess_piece(from_tile)
                and chess_side_known(from_tile)
                and chess_side_known(landing)
                and chess_side(from_tile) != chess_side(landing)
            ):
                return base + from_piece
            return base
        if (
            base > piece
            and landing.curse
            in (CurseType.CHESS_QUEEN, CurseType.CHESS_ROOK, CurseType.CHESS_KING)
            and is_chess_piece(from_tile)
        ):
            prefix = path[:pos]
            flags = _chess_take_search_flags(loadout)
            if is_chess_capture_step(
                board,
                path[pos - 1],
                path[pos],
                path_prefix=prefix,
                visited=set(prefix),
                flags=flags,
                loadout=loadout,
            ):
                return from_base + from_piece + (base - piece)
        if landing.curse == CurseType.CHESS_ROOK and base == piece:
            return piece * 2
    prefix = path[:pos] if pos > 0 else []
    flags = _chess_take_search_flags(loadout)
    is_capture = (
        pos > 0
        and is_chess_capture_step(
            board,
            path[pos - 1],
            path[pos],
            path_prefix=prefix,
            visited=set(prefix),
            flags=flags,
            loadout=loadout,
        )
    )
    if (
        is_capture
        and is_chess_piece(landing)
        and landing.curse == CurseType.CHESS_PAWN
    ):
        if base > piece:
            return base
        if is_chess_piece(from_tile):
            from_val = chess_piece_value(from_tile)
            if from_val > piece:
                return from_val
    if (
        pos > 0
        and is_chess_piece(landing)
        and not is_chess_piece(from_tile)
        and not is_capture
    ):
        return max(piece, base)
    return piece


def movie_camera_chess_entry_landing_positions(
    board: Board, path: list[int]
) -> list[int]:
    """Path indices where the word first steps onto a chess tile (no capture)."""
    return [
        i
        for i in range(1, len(path))
        if is_chess_piece(board.get_by_index(path[i]))
        and not is_chess_piece(board.get_by_index(path[i - 1]))
    ]


def movie_camera_credit_positions(
    board: Board,
    path: list[int],
    *,
    strict: bool = False,
    loadout: Loadout | None = None,
) -> list[int]:
    """Positions that count toward Movie Camera's first-N take piece values."""
    if strict and path_has_melmod_take_metadata(board, path):
        return [
            i
            for i in range(len(path))
            if _has_take_metadata(board.get_by_index(path[i]))
        ]
    captures = movie_camera_take_path_positions(
        board, path, strict=strict, loadout=loadout
    )
    if captures:
        return captures
    return movie_camera_chess_entry_landing_positions(board, path)


def _movie_camera_take_excluded(
    board: Board,
    path: list[int],
    take_pos: int,
    all_takes: list[int],
    loadout: Loadout | None = None,
) -> bool:
    """Drop a capture superseded by a later take after a Full Moon chain across letter tiles."""
    landing = board.get_by_index(path[take_pos])
    if (
        take_pos == all_takes[-1]
        and len(all_takes) >= 3
        and take_pos > 0
        and landing.curse == CurseType.CHESS_ROOK
        and int(landing.base_score) == chess_piece_value(landing)
    ):
        from_tile = board.get_by_index(path[take_pos - 1])
        if from_tile.curse == CurseType.CHESS_QUEEN:
            return True
    if landing.curse in (CurseType.CHESS_ROOK, CurseType.CHESS_QUEEN):
        return False
    for fm_pos in range(take_pos + 1, len(path)):
        if not _is_full_moon_chess_teleport_step(
            board, path, fm_pos, loadout=loadout
        ):
            continue
        if not any(t > fm_pos for t in all_takes):
            continue
        if any(take_pos < t < fm_pos for t in all_takes):
            continue
        has_letter_gap = any(
            not is_chess_piece(board.get_by_index(path[p]))
            for p in range(take_pos + 1, fm_pos)
        )
        if has_letter_gap:
            return True
    return False


def movie_camera_take_path_positions(
    board: Board,
    path: list[int],
    *,
    strict: bool = False,
    loadout: Loadout | None = None,
) -> list[int]:
    """Path indices for captures that count toward Movie Camera's first-N takes."""
    all_takes = chess_take_path_positions(
        board, path, strict=strict, loadout=loadout
    )
    return [
        pos
        for pos in all_takes
        if not _movie_camera_take_excluded(
            board, path, pos, all_takes, loadout=loadout
        )
    ]


def first_n_movie_camera_piece_value_sum(
    board: Board,
    path: list[int],
    n: int,
    *,
    strict: bool = False,
    loadout: Loadout | None = None,
) -> int:
    positions = movie_camera_credit_positions(
        board, path, strict=strict, loadout=loadout
    )
    if not positions or n <= 0:
        return 0
    values = [
        movie_camera_take_piece_value_at(
            board, path, pos, loadout=loadout, strict=strict
        )
        for pos in positions
    ]
    has_captures = bool(
        movie_camera_take_path_positions(
            board, path, strict=strict, loadout=loadout
        )
    )
    if not has_captures:
        return sum(values[:n])
    if len(values) > n:
        values.sort(reverse=True)
        values = values[:n]
    return sum(values)


def tile_number_value(tile: Tile) -> int:
    if tile.number_value is not None:
        return tile.number_value
    if tile.letter.isdigit():
        return int(tile.letter)
    return 0


def is_number_tile(tile: Tile) -> bool:
    return tile.curse == CurseType.NUMBER


def target_score_from_loadout(loadout: Loadout) -> int:
    """Dartboard target base score (default 1), scaled by Toothed Whale boss."""
    try:
        base = int((loadout.extras or {}).get("target_score", 1))
    except (TypeError, ValueError):
        base = 1
    try:
        from cursed_words_solver.rules.boss_effects import (
            effective_target_score_multiplier,
            load_rules_catalog,
        )

        mult = effective_target_score_multiplier(loadout, load_rules_catalog())
        if mult != 1.0:
            import math

            return max(1, int(math.floor(base * mult)))
    except Exception:
        pass
    return base


_CHESS_PIECE_SLUGS: dict[str, CurseType] = {
    "pawn": CurseType.CHESS_PAWN,
    "bishop": CurseType.CHESS_BISHOP,
    "rook": CurseType.CHESS_ROOK,
    "knight": CurseType.CHESS_KNIGHT,
    "queen": CurseType.CHESS_QUEEN,
    "king": CurseType.CHESS_KING,
}


def birthday_cake_accumulated(loadout: Loadout) -> int:
    """Runtime 'Get +X WORD SCORE' total exported from the Birthday Cake sticker."""
    extras = loadout.extras or {}
    if "birthday_cake_bonus" in extras:
        return max(0, _extra_int(loadout, "birthday_cake_bonus", 0))
    from cursed_words_solver.rules.ram_memory import birthday_cake_bonus_from_pin_memory

    from_ram = birthday_cake_bonus_from_pin_memory(loadout)
    if from_ram is not None:
        return from_ram
    return 0


_GRID_PATH_SCATTER_SLUGS = frozenset(
    {"tombstone", "down_under", "dusty_coffin", "deep_sea_horror"}
)


def normalize_scoring_path(path: list[int]) -> list[int]:
    """Drop consecutive duplicate indices (game scores one step per letter)."""
    if not path:
        return []
    out = [path[0]]
    for idx in path[1:]:
        if idx != out[-1]:
            out.append(idx)
    return out


def consumable_rack_count(loadout: Loadout) -> int:
    count = _extra_int(loadout, "consumable_rack_count", -1)
    if count >= 0:
        return count
    from cursed_words_solver.consumable_placement import consumable_rack_tiles

    return len(consumable_rack_tiles(loadout))


def grid_number(loadout: Loadout) -> int:
    return max(0, _extra_int(loadout, "grid_number", 0))


def _limnophila_previous_word_available(loadout: Loadout) -> bool:
    """Prior word on this grid exists (melmod scoring previousWords cache, not encounter historic)."""
    if _extra_bool(loadout, "is_first_grid_of_encounter"):
        return False
    if grid_number(loadout) == 1:
        return False
    extras = loadout.extras or {}
    source = str(extras.get("encounter_historic_source", "") or "").strip().lower()
    if source == "grid_start_cleared":
        return False
    raw = extras.get("scoring_previous_words_count")
    if raw is not None and str(raw).strip() != "":
        try:
            return int(str(raw).strip()) > 0
        except (ValueError, TypeError):
            return False
    if source == "grid_advanced":
        return False
    return bool(_extra_letter(loadout, "previous_word_first_letter"))


def consumable_count_on_path(board: Board, path: list[int]) -> int:
    return sum(
        1 for idx in path if is_consumable_tile(board.get_by_index(idx))
    )


def currency_letter_value(tile: Tile) -> int:
    glyph = normalize_tile_glyph(tile.char or tile.letter or "")
    if glyph in CURRENCY_MAP:
        return _scrabble_value(CURRENCY_MAP[glyph])
    ch = (tile.letter or "").strip().upper()
    if len(ch) == 1 and ch.isalpha():
        return _scrabble_value(ch)
    return 0


def red_tiles_used_encounter(loadout: Loadout) -> int:
    return max(0, _extra_int(loadout, "red_tiles_used_encounter", 0))


def parse_historic_words(loadout: Loadout | None) -> list[dict]:
    """Parse melmod ``historic_words`` extra (list of prior submitted words)."""
    if not loadout:
        return []
    raw = (loadout.extras or {}).get("historic_words")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [row for row in parsed if isinstance(row, dict)]
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    return []


def movie_camera_prior_from_historic(loadout: Loadout | None) -> int:
    """Encounter Movie Camera WordScoreBonus before the current word."""
    total = 0
    for row in parse_historic_words(loadout):
        try:
            total += max(0, int(row.get("chess_take_value", 0)))
        except (TypeError, ValueError):
            continue
    return total


def movie_camera_word_score_bonus_exported(loadout: Loadout | None) -> int | None:
    """Live WordScoreBonus from melmod (pre-submit on F7; may be post-submit after score)."""
    if not loadout:
        return None
    raw = (loadout.extras or {}).get("movie_camera_word_score_bonus")
    if raw is None or raw == "":
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


def movie_camera_accumulated(loadout: Loadout | None) -> int:
    """Encounter Movie Camera WordScoreBonus before this word's capture improvement."""
    exported = movie_camera_word_score_bonus_exported(loadout)
    if exported is not None:
        return exported
    return movie_camera_prior_from_historic(loadout)


def movie_camera_improve_for_path(
    board: Board,
    path: list[int],
    level: int,
    *,
    strict: bool = False,
    loadout: Loadout | None = None,
) -> int:
    """Piece values for the first N Movie Camera credits on this path."""
    if _carousel_horse_level(loadout) >= 2:
        return first_n_movie_camera_piece_value_sum(
            board, path, level, strict=strict, loadout=loadout
        )
    return first_n_movie_camera_game_take_value_sum(
        board, path, level, strict=strict, loadout=loadout
    )


def is_movie_camera_take_at_path_position(
    board: Board,
    path: list[int],
    pos: int,
    *,
    strict: bool = False,
    loadout: Loadout | None = None,
) -> bool:
    """True when path[pos] is a ChessTake/EnPassant landing (Movie Camera parity)."""
    return is_take_at_path_position(
        board, path, pos, strict=strict, loadout=loadout
    )


def movie_camera_game_take_path_positions(
    board: Board,
    path: list[int],
    *,
    strict: bool = False,
    loadout: Loadout | None = None,
) -> list[int]:
    """Path indices for ChessTake/EnPassant landings (first-N order, no sorting)."""
    return [
        i
        for i in range(len(path))
        if is_movie_camera_take_at_path_position(
            board, path, i, strict=strict, loadout=loadout
        )
    ]


def first_n_movie_camera_game_take_value_sum(
    board: Board,
    path: list[int],
    n: int,
    *,
    strict: bool = False,
    loadout: Loadout | None = None,
) -> int:
    """Sum chess piece values for the first N Movie Camera takes in path order."""
    if n <= 0:
        return 0
    positions = movie_camera_game_take_path_positions(
        board, path, strict=strict, loadout=loadout
    )
    total = 0
    for pos in positions[:n]:
        total += chess_piece_value(board.get_by_index(path[pos]))
    return total


_VOID_NEIGHBOR_DELTAS = (
    (0, 1),
    (0, -1),
    (1, 0),
    (-1, 0),
    (1, 1),
    (1, -1),
    (-1, 1),
    (-1, -1),
)

_DUSTY_TOMBSTONE_ADJACENT_DELTAS = (
    (0, 1),
    (0, -1),
    (1, 0),
    (-1, 0),
)


def _path_step_adjacent(idx_a: int, idx_b: int) -> bool:
    """Match GridUtilitySingleton.AreAdjacentTiles (8-dir, incl. diagonal)."""
    if idx_a == idx_b:
        return False
    r1, c1 = divmod(idx_a, 5)
    r2, c2 = divmod(idx_b, 5)
    return abs(r1 - r2) <= 1 and abs(c1 - c2) <= 1


def non_adjacent_step_count(path: list[int]) -> int:
    if len(path) < 2:
        return 0
    return sum(
        1
        for i in range(len(path) - 1)
        if not _path_step_adjacent(path[i], path[i + 1])
    )


def loadout_has_ruler(loadout: Loadout | None) -> bool:
    if loadout is None:
        return False
    from cursed_words_solver.rules.rule_lookup import slugify_name

    for stamp in loadout.stamps or []:
        if slugify_name(str(stamp.id or stamp.name)) == "ruler":
            return True
    return False


def ruler_distance_from_loadout(loadout: Loadout | None) -> int:
    """Stamp ``Distance`` before scoring the candidate word (melmod ``ruler_distance``)."""
    if loadout is None:
        return 0
    return max(0, _extra_int(loadout, "ruler_distance", 0))


def ruler_effective_distance(loadout: Loadout | None, path: list[int] | None) -> int:
    """Game ``Distance`` after adding this word's non-adjacent steps."""
    base = ruler_distance_from_loadout(loadout)
    if not path:
        return base
    return base + non_adjacent_step_count(path)


def advance_ruler_distance_after_submit(loadout: Loadout, path: list[int]) -> None:
    """Post-submit: mirror ``Ruler.Distance += non_adjacent_steps``."""
    if not loadout_has_ruler(loadout):
        return
    extras = loadout.extras
    if not isinstance(extras, dict):
        loadout.extras = {}
        extras = loadout.extras
    extras["ruler_distance"] = str(ruler_effective_distance(loadout, path))


# Oden — mirrors Oden.ApplyWordBonus + Tile.GetCurseTypes (+ TileSelection wobbly).
# Ref: scripts/decompile_type/out_stamps/Oden.decompiled.cs, Tile.decompiled.cs

_ODEN_CHESS_CURSES = frozenset(
    {
        CurseType.CHESS_PAWN,
        CurseType.CHESS_BISHOP,
        CurseType.CHESS_ROOK,
        CurseType.CHESS_KNIGHT,
        CurseType.CHESS_QUEEN,
        CurseType.CHESS_KING,
    }
)


def word_starts_ends_consumable(board: Board, path: list[int]) -> bool:
    if len(path) < 2:
        return False
    start = board.get_by_index(path[0])
    end = board.get_by_index(path[-1])

    def _endpoint_consumable(tile: Tile) -> bool:
        return is_consumable_tile(tile) or is_placed_consumable_tile(tile)

    return _endpoint_consumable(start) and _endpoint_consumable(end)


def path_has_melmod_take_metadata(board: Board, path: list[int]) -> bool:
    """True when melmod marked any path tile as a capture landing square."""
    for idx in path:
        if _has_take_metadata(board.get_by_index(idx)):
            return True
    return False


def chess_take_strict_mode(
    board: Board, path: list[int], *, strict_requested: bool
) -> bool:
    """Whether to require melmod take metadata for strict-take sticker rules.

    Pre-play board exports usually lack take flags; infer captures unless melmod
    confirmed captures on this path (post-submit mismatch validation).
    """
    if not strict_requested:
        return False
    return path_has_melmod_take_metadata(board, path)


def mahjong_consumable_factor(loadout: Loadout, rule: dict) -> float:
    var = pin_right_variable(loadout)
    if var is not None:
        return float(var)
    base = float(rule.get("factor_base", 2.0))
    per_right = float(rule.get("factor_per_pin_right", 1.0))
    return base + per_right * pin_right_level(loadout)


def bicycle_word_per_card(loadout: Loadout, rule: dict) -> int:
    """Bicycle right UpgradeableComponent.VariableValue (+1 per suited card on path)."""
    var = pin_right_variable(loadout)
    if var is not None:
        return var
    base = int(rule.get("value", 1))
    per_upgrade = int(rule.get("value_per_right_upgrade", 1))
    right_upgrades = max(0, pin_right_level(loadout) - 1)
    return base + per_upgrade * right_upgrades


def bicycle_word_score_accumulator(loadout: Loadout) -> int:
    """Running WordScoreBonus on the Bicycle pin before this word is scored."""
    extras = loadout.extras or {}
    for key in ("bicycle_word_score_bonus", "cards_submitted"):
        if key not in extras:
            continue
        try:
            return max(0, int(extras[key]))
        except (TypeError, ValueError):
            continue
    return 0


def bicycle_pin_accumulator_from_fingerprint(fp: str) -> int | None:
    """Pre-submit Bicycle pin bonus from melmod loadout fingerprint (``bicycle:left|22``)."""
    if not fp:
        return None
    marker = "bicycle:"
    idx = fp.find(marker)
    if idx < 0:
        return None
    tail = fp[idx + len(marker) :]
    if "|" not in tail:
        return None
    bonus_part = tail.split("|", 1)[1]
    try:
        return max(0, int(bonus_part))
    except (TypeError, ValueError):
        return None


def _is_joker_glyph_char(tile: Tile) -> bool:
    ch = str(tile.char or "")
    return "🃏" in ch


def _bicycle_joker_path_tile(tile: Tile) -> bool:
    """True when tile is a joker for Bicycle suited credit (CardSuit joker / is_joker / glyph)."""
    if is_joker_tile(tile):
        return True
    suit = card_suit(tile)
    if suit and suit.lower() == "joker":
        return True
    if _is_joker_glyph_char(tile):
        return True
    return False


def _bicycle_suited_path_tile(tile: Tile) -> bool:
    """True when ``Tile.CardSuit != 0`` for Bicycle (incl. joker glyph on board)."""
    if is_joker_tile(tile):
        return False
    suit = card_suit(tile)
    if suit and suit not in ("none", "joker"):
        return True
    # Joker glyph without card_suit in F8 export still has in-game CardSuit.
    if _is_joker_glyph_char(tile) and not is_joker_tile(tile):
        return True
    return False


def _letter_occurrences_on_path(board: Board, path: list[int], letter: str) -> int:
    ch = (letter or "").strip().lower()[:1]
    if not ch:
        return 0
    return sum(
        1
        for idx in path
        if (board.get_by_index(idx).letter or "").strip().lower()[:1] == ch
    )


def suited_tiles_on_path_count(board: Board, path: list[int]) -> int:
    """Suited playing-card tiles on the path (Bicycle: ``CardSuit != 0`` tiles).

    Note: keep parity with `_bicycle_suited_path_tile`, including joker-glyph tiles
    that may be missing `card_suit` in melmod exports.
    """
    return sum(
        1 for idx in path if _bicycle_suited_path_tile(board.get_by_index(idx))
    )


def bicycle_suited_on_path_from_extras(loadout: Loadout) -> int:
    """Melmod scoring-time count when board export lacks card_suit metadata."""
    try:
        return max(0, int((loadout.extras or {}).get("bicycle_suited_on_path", 0)))
    except (TypeError, ValueError):
        return 0


def _bicycle_multi_suit_suited_credit(board: Board, path: list[int]) -> int:
    """Multi-suit Bicycle credit: unique suited card ranks (duplicate rank → once).

    Empty ``card_rank`` falls back to the path letter so chess/glyph tiles that
    share a letter collapse with that letter's rank (howdied W♥ + chess → 1).
    Melmod submit ``bicycle_suited_on_path`` matches this unique-rank count.
    """
    entries: list[tuple[int, str, str]] = []
    for path_index, idx in enumerate(path):
        tile = board.get_by_index(idx)
        if not _bicycle_suited_path_tile(tile):
            continue
        suit = (card_suit(tile) or "").strip().lower()
        if not suit or suit in ("none", "joker"):
            continue
        rank = card_rank(tile)
        letter = path_letter_for_count(tile)
        rank_key = (rank or "").strip().upper()[:1]
        if not rank_key:
            rank_key = (letter or "").strip().upper()[:1]
        if not rank_key:
            continue
        entries.append((path_index, rank_key, letter))

    if not entries:
        return 0

    last_rank_index: dict[str, int] = {
        rank_key: path_index for path_index, rank_key, _letter in entries
    }

    credited: set[str] = set()
    for path_index, rank_key, letter in entries:
        letter_count = (
            _letter_occurrences_on_path(board, path, letter) if letter else 0
        )
        if letter_count > 2 and last_rank_index.get(rank_key) != path_index:
            continue
        credited.add(rank_key)
    return len(credited)


def bicycle_suited_credit_on_path(board: Board, path: list[int]) -> int:
    """Bicycle suited credit: mono-suit → 1; multi-suit + non-end joker → per-tile; else unique ranks.

    Board-only heuristic (see effective_suited_cards_on_path).
    """
    if not path:
        return 0
    path_end = path[-1]
    suits: set[str] = set()
    joker_not_at_end = False
    suited_tile_count = 0
    non_joker_suited = 0
    for idx in path:
        tile = board.get_by_index(idx)
        real_suited = _bicycle_suited_path_tile(tile)
        joker_suited = _bicycle_joker_path_tile(tile)
        # Tiles with CardSuit == Suit.None (e.g. a joker played as a plain letter,
        # whose suit was cleared) contribute nothing to Bicycle's per-tile credit.
        if not real_suited and not joker_suited:
            continue
        if joker_suited and idx != path_end:
            joker_not_at_end = True
        if joker_suited and idx == path_end:
            continue
        suited_tile_count += 1
        if real_suited:
            non_joker_suited += 1
            suit = card_suit(tile)
            if suit and suit not in ("none", "joker"):
                suits.add(suit)
    if suited_tile_count == 0:
        return 0
    if joker_not_at_end and non_joker_suited >= 2:
        return suited_tile_count
    if len(suits) <= 1:
        return 1
    if joker_not_at_end:
        return suited_tile_count
    return _bicycle_multi_suit_suited_credit(board, path)


def effective_suited_cards_on_path(
    board: Board, path: list[int], loadout: Loadout
) -> int:
    """Suited tiles credit for Bicycle from board card metadata only."""
    return bicycle_suited_credit_on_path(board, path)


def birthday_cake_improve_high_on_path(
    board: Board, path: list[int], word: str | None = None
) -> float:
    """Highest value driving Birthday Cake improve (NUMBER face or ceil of fraction).

    Game (BirthdayCake.ApplyWordBonus): max GetNumberFloat among path tiles where
    IsNumber() — includes playing-card NUMBER tiles (e.g. spades 8 on zareebas).

    Unit fractions with denominator >= 8 (e.g. 1/8 on morat) do not contribute;
    num >= 2 or den <= 7 still use ceil(num/den).

    NUMBER tiles used to spell letters (wildcard-style) do not contribute when a
    qualifying fraction is on the path.
    """
    import math

    steps = normalize_scoring_path(path)
    w = (word or "").lower()
    high = 0.0
    has_qualifying_fraction = False
    for idx in steps:
        tile = board.get_by_index(idx)
        if is_fraction_tile(tile):
            parts = fraction_parts(tile)
            if parts is not None:
                num, den = parts
                if den > 0 and (num >= 2 or den <= 7):
                    has_qualifying_fraction = True
                    break
    for pos, idx in enumerate(steps):
        tile = board.get_by_index(idx)
        if is_number_tile(tile):
            if (
                w
                and (pos >= len(w) or not w[pos].isdigit())
                and has_qualifying_fraction
            ):
                continue
            high = max(high, float(tile_number_value(tile)))
        elif is_fraction_tile(tile):
            parts = fraction_parts(tile)
            if parts is not None:
                num, den = parts
                if den > 0 and (num >= 2 or den <= 7):
                    high = max(high, float(math.ceil(num / den)))
    return high


def birthday_cake_improve_for_path(
    board: Board, path: list[int], level: int, rule: dict, word: str | None = None
) -> int:
    """Improve term added to birthday_cake_bonus after this submit."""
    import math

    high = birthday_cake_improve_high_on_path(board, path, word)
    if not high:
        return 0
    level_factor = sticker_rule_int(level, rule)
    return int(math.floor(level_factor * high + 0.5))


def rewind_birthday_cake_pre_word_extras(
    loadout: Loadout,
    board: Board,
    path: list[int],
    level: int,
    rule: dict,
    word: str | None = None,
) -> None:
    """Subtract this word's improve from extras when snapshot is post-submit."""
    improve = birthday_cake_improve_for_path(board, path, level, rule, word)
    if improve <= 0:
        return
    bonus = birthday_cake_accumulated(loadout)
    if bonus < improve:
        return
    extras = dict(loadout.extras or {})
    pre = bonus - improve
    extras["birthday_cake_bonus"] = str(pre)
    loadout.extras = extras


def rewind_movie_camera_pre_word_extras(
    loadout: Loadout,
    board: Board,
    path: list[int],
    level: int,
    *,
    strict: bool = False,
) -> None:
    """Subtract this word's improve from extras when snapshot is post-submit."""
    improve = movie_camera_improve_for_path(
        board, path, level, strict=strict, loadout=loadout
    )
    if improve <= 0:
        return
    bonus = movie_camera_accumulated(loadout)
    prior = movie_camera_prior_from_historic(loadout)
    if prior + improve == bonus:
        pre = prior
    elif bonus > prior + improve:
        pre = bonus - improve
    else:
        return
    extras = dict(loadout.extras or {})
    extras["movie_camera_word_score_bonus"] = str(pre)
    loadout.extras = extras


def rewind_setup_extras(
    loadout: Loadout,
    board: Board,
    path: list[int] | None = None,
    *,
    pin_rule: dict | None = None,
    birthday_rule: dict | None = None,
    movie_camera_rule: dict | None = None,
    post_bicycle_bonus: int | None = None,
) -> list[str]:
    """Normalize extras before F8 search or regression replay."""
    notes: list[str] = []
    extras = dict(loadout.extras or {})
    if extras.pop("bicycle_suited_on_path", None) is not None:
        notes.append("cleared stale bicycle_suited_on_path")
        loadout.extras = extras

    if path and pin_rule is not None:
        before = bicycle_word_score_accumulator(loadout)
        rewind_bicycle_pre_word_extras(
            loadout, board, path, pin_rule, post_bonus=post_bicycle_bonus
        )
        after = bicycle_word_score_accumulator(loadout)
        if after != before:
            notes.append(f"bicycle accumulator {before}→{after}")

    if path and birthday_rule is not None:
        before = birthday_cake_accumulated(loadout)
        level = int(birthday_rule.get("level", 1))
        rewind_birthday_cake_pre_word_extras(loadout, board, path, level, birthday_rule)
        after = birthday_cake_accumulated(loadout)
        if after != before:
            notes.append(f"birthday cake bonus {before}→{after}")

    if path and movie_camera_rule is not None:
        before = movie_camera_accumulated(loadout)
        level = int(movie_camera_rule.get("level", 1))
        strict = chess_take_strict_mode(
            board,
            path,
            strict_requested=movie_camera_rule.get("strict_takes", False),
        )
        rewind_movie_camera_pre_word_extras(
            loadout, board, path, level, strict=strict
        )
        after = movie_camera_accumulated(loadout)
        if after != before:
            notes.append(f"movie camera bonus {before}→{after}")

    return notes


def rewind_bicycle_pre_word_extras(
    loadout: Loadout,
    board: Board,
    path: list[int],
    rule: dict,
    *,
    post_bonus: int | None = None,
) -> None:
    """Set extras to pre-submit accumulator when post_bonus includes this path's suited cards."""
    extras = dict(loadout.extras or {})
    pin_effect = str(extras.get("pin_effect", "") or "").strip().lower()
    if pin_effect not in ("bicycle", "bones_the_dog", "bones"):
        return
    per_card = bicycle_word_per_card(loadout, rule)
    suited = effective_suited_cards_on_path(board, path, loadout)
    if per_card <= 0 or suited <= 0:
        return
    pin_acc = bicycle_pin_accumulator_from_fingerprint(
        str(extras.get("loadout_fingerprint", "") or "")
    )
    post: int | None = post_bonus
    if post is None:
        try:
            post = int(extras.get("bicycle_word_score_bonus", -1))
        except (TypeError, ValueError):
            post = -1
    if pin_acc is not None and post == pin_acc:
        return
    if pin_acc is not None and post == pin_acc + per_card * suited:
        extras["bicycle_word_score_bonus"] = str(pin_acc)
        extras["cards_submitted"] = str(pin_acc)
        loadout.extras = extras
        return
    if post < 0:
        return
    pre = max(0, post - per_card * suited)
    extras["bicycle_word_score_bonus"] = str(pre)
    extras["cards_submitted"] = str(pre)
    loadout.extras = extras


def _extra_positive_int(extras: dict[str, Any], key: str) -> int | None:
    if key not in extras:
        return None
    raw = extras.get(key)
    try:
        val = int(raw) if isinstance(raw, bool) is False else 0
    except (TypeError, ValueError):
        try:
            val = int(float(raw))
        except (TypeError, ValueError):
            return None
    return val if val > 0 else None


def neapolitan_has_live_percent(loadout: Loadout | None) -> bool:
    """True when melmod exported the stamp's current multiplicative percent."""
    if loadout is None:
        return False
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    return _extra_positive_int(extras, "neapolitan_percent") is not None


def neapolitan_base_percent_from_loadout(loadout: Loadout | None) -> tuple[int, str]:
    """Resolve baseline Neapolitan percent; F8 gather polls live export before solve."""
    extras = (
        loadout.extras
        if loadout is not None and isinstance(loadout.extras, dict)
        else {}
    )
    live_percent = _extra_positive_int(extras, "neapolitan_percent")
    if live_percent is not None:
        return live_percent, "live"
    return 100, "default"


def path_letter_for_count(tile: Tile) -> str:
    """Face key for Bubble Tea / Banana same-letter counts.

    Matches game GetStringRepresentation grouping: A–Z faces, chess face chars,
    currency map, and non-alpha display glyphs (ITEM emoji, ``?``, etc.).
    NUMBER faces are excluded (they do not count as letter keys).
    """
    if tile.curse == CurseType.NUMBER:
        return ""
    if tile.curse in CHESS_CURSES:
        raw = (tile.char or "").strip().lower()
        return raw if len(raw) == 1 and raw.isalpha() else ""
    if tile.curse == CurseType.CURRENCY:
        glyph = normalize_tile_glyph(tile.char or tile.letter or "")
        if glyph in CURRENCY_MAP:
            return CURRENCY_MAP[glyph].lower()
        ch = (tile.letter or "").strip().lower()
        return ch if len(ch) == 1 and ch.isalpha() else ""
    ch = (tile.letter or "").strip().lower()
    if len(ch) == 1 and ch.isalpha():
        return ch
    # ITEM / blank / other faces: keep full display glyph (👻, 🧦, ?, …)
    raw = normalize_tile_glyph(tile.char or tile.letter or "").strip()
    if not raw:
        return ""
    if len(raw) == 1 and raw.isalpha():
        return raw.lower()
    return raw


def _is_alpha_face_key(ch: str) -> bool:
    return len(ch) == 1 and ch.isalpha()


def word_first_letter(word: str) -> str:
    """First alphabetic character of the submitted word (lowercase)."""
    w = (word or "").strip().lower()
    return w[0] if w and w[0].isalpha() else ""


def first_letter_on_path(board: Board, path: list[int]) -> str:
    """First A–Z letter along the path (currency via CURRENCY_MAP; skips numbers/emoji)."""
    for idx in path:
        tile = board.get_by_index(idx)
        ch = path_letter_for_count(tile)
        if ch and _is_alpha_face_key(ch):
            return ch
    return ""


def _assigned_glyph_before_first_letter_tile(board: Board, path: list[int]) -> bool:
    """True when wildcard/item/chess precedes the first LETTER curse on the path.

    Those glyphs contribute assigned letters (word spelling), not a path face that
    chips/bento should treat as the word start. Chess face chars (e.g. king ``l``)
    must not override the dictionary first letter.
    """
    seen_lead = False
    for idx in path:
        tile = board.get_by_index(idx)
        if (
            tile.curse == CurseType.WILDCARD
            or tile.curse == CurseType.ITEM
            or tile.curse in CHESS_CURSES
        ):
            seen_lead = True
            continue
        if tile.curse == CurseType.LETTER:
            return seen_lead
    return False


def _effective_word_start_letter(board: Board, path: list[int], word: str) -> str:
    """First letter for Bento/Chips-style conditions (melmod path-first parity).

    When currency/symbols lead the path but the dictionary word starts elsewhere, the
    game uses the path's first letter tile (see ScoringContextCapture). Wildcard/item/
    chess-leading paths use the submitted word's first letter (assigned glyph), not
    the first literal letter face after those leads.
    """
    word_first = word_first_letter(word)
    if _assigned_glyph_before_first_letter_tile(board, path):
        return word_first or first_letter_on_path(board, path)
    if path:
        lead = board.get_by_index(path[0])
        glyph = normalize_tile_glyph(lead.letter or lead.char or "")
        is_currency_lead = lead.curse == CurseType.CURRENCY or glyph in CURRENCY_MAP
        if is_currency_lead and glyph:
            mapped = CURRENCY_MAP.get(glyph, "").lower()
            if not mapped and len(glyph) == 1 and glyph.isalpha():
                mapped = glyph.lower()
            # Currency-leading path uses dictionary first letter when it maps to word-first
            if mapped and word_first and mapped == word_first:
                return word_first
    path_first = first_letter_on_path(board, path)
    if path_first and word_first and path_first != word_first:
        return path_first
    return word_first or path_first


_BURRITO_LEVEL_EXCLUDE = frozenset(
    {"burrito", "left_hand", "padlock_sticker", "snapshot"}
)

# Bosses whose FloorAdjustedModification is not scatter sticker tier (voids/Qs,
# min/max word length, etc.).
_SCATTER_TIER_IGNORE_FLOOR_BOSSES = frozenset({"mole", "cobra", "wolf"})


def _active_boss_modifier_slugs(loadout: Loadout | None) -> list[str]:
    if loadout is None:
        return []
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    raw = extras.get("boss_modifiers")
    mods: list[str] = []
    if isinstance(raw, list):
        mods = [str(entry or "").strip().lower() for entry in raw if str(entry or "").strip()]
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                mods = [
                    str(entry or "").strip().lower()
                    for entry in parsed
                    if str(entry or "").strip()
                ]
        except json.JSONDecodeError:
            mods = [s.strip().lower() for s in raw.split(",") if s.strip()]
    if not mods and loadout.boss_id:
        mods = [str(loadout.boss_id).strip().lower()]
    return mods


def _scatter_tier_floor_mod(loadout: Loadout | None, grid: int) -> int:
    """Floor reduction for scattered sticker tier (not void count / currency)."""
    if loadout is None:
        return max(0, grid - 1)
    from cursed_words_solver.rules.boss_effects import _parse_boss_modifier_floor_mods

    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    floor_mods = _parse_boss_modifier_floor_mods(loadout)
    mods = _active_boss_modifier_slugs(loadout)
    if floor_mods or mods:
        reducing = 0
        for slug in mods:
            if slug in _SCATTER_TIER_IGNORE_FLOOR_BOSSES:
                continue
            reducing = max(reducing, floor_mods.get(slug, 0))
        if reducing > 0:
            return reducing
        if mods and all(slug in _SCATTER_TIER_IGNORE_FLOOR_BOSSES for slug in mods):
            return 0

    raw_floor = extras.get("boss_floor_modification")
    if raw_floor is None or raw_floor == "":
        return max(0, grid - 1)
    try:
        total = max(0, int(raw_floor))
    except (TypeError, ValueError):
        return max(0, grid - 1)
    boss_id = str(loadout.boss_id or "").strip().lower()
    slugs = list(mods) if mods else []
    if not slugs and boss_id in _SCATTER_TIER_IGNORE_FLOOR_BOSSES:
        slugs = [boss_id]
    if slugs and all(slug in _SCATTER_TIER_IGNORE_FLOOR_BOSSES for slug in slugs):
        return 0
    return total


def scattered_grid_item_level(loadout: Loadout | None) -> int:
    """Encounter-effective level for scattered grid stickers (grid − boss floor mod)."""
    if loadout is None:
        return 1
    grid = grid_number(loadout)
    if grid <= 0:
        grid = 1
    floor_mod = _scatter_tier_floor_mod(loadout, grid)
    return max(1, grid - floor_mod)


def melmod_would_inflate_scatter_to_equipped(
    loadout: Loadout | None,
    slug: str,
    exported: int,
    equipped: int,
) -> bool:
    """Whether melmod ApplyEquippedScatterLevels would raise export toward equipped."""
    del exported
    if loadout is None:
        return True
    if slug in ("dusty_coffin", "mysterious_amulet"):
        return False
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    # Melmod 1.4+ exports the live UpgradeableComponents level; no inflation.
    if extras.get("item_levels_exact") in (True, "true", "1"):
        return False
    if extras.get("boss_floor_modification") in (None, ""):
        return True
    encounter_tier = scattered_grid_item_level(loadout)
    if encounter_tier > 0 and equipped > encounter_tier:
        return False
    return True


def grid_path_encounter_level(loadout: Loadout | None) -> int:
    """Sticker level for scattered grid items on the path (not void penalty / inventory)."""
    if loadout is None:
        return 1
    grid = grid_number(loadout)
    if grid <= 0:
        grid = 1
    extras = loadout.extras or {}
    raw_floor = extras.get("boss_floor_modification")
    if raw_floor is None or raw_floor == "":
        return max(1, grid)
    return scattered_grid_item_level(loadout)


_GRID_PATH_IMMEDIATE_WORD_MULT_IDS = frozenset({"ferris_wheel", "ornate_key"})


_SNAPSHOT_PROXY_SCORING_TYPES = frozenset(
    {
        "add_tile_score",
        "tile_multiply",
        "multiply_word_scaled",
        "add_word_score",
    }
)

_SNAPSHOT_COPY_POOL_SLUGS = frozenset(
    {
        "artist_s_palette",
        "tombstone",
        "dusty_coffin",
        "down_under",
        "deep_sea_horror",
    }
)

_SNAPSHOT_COPY_PRIORITY = (
    "dusty_coffin",
    "down_under",
    "deep_sea_horror",
    "tombstone",
    "artist_s_palette",
)


_GRID_PATH_INVENTORY_BLEEDTHROUGH_EXCLUDE = frozenset(
    {"tombstone", "down_under", "dusty_coffin", "deep_sea_horror"}
)


# ScatteredItemPools.VoidBuildItems — Retro Raider's scatter pool.
_VOID_POOL_STICKERS = frozenset(
    {"dusty_coffin", "deep_sea_horror", "queen_of_spades", "tombstone"}
)


_PATH_SCATTER_SKIP_TYPES = frozenset(
    {
        "scatter_start_grid",
        "scatter_start_encounter",
        "unmodeled",
        "custom",
    }
)


