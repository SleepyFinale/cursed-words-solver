"""Shared helpers for loadout scoring conditions (wiki-aligned)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from cursed_words_solver.models import (
    CHESS_CURSES,
    CURRENCY_MAP,
    Board,
    CurseType,
    Loadout,
    Tile,
    TileColor,
    normalize_tile_glyph,
)
from cursed_words_solver.rules.base_scoring import _scrabble_value, tile_base_contribution
from cursed_words_solver.rules.chess_tiles import (
    chess_side,
    chess_side_known,
    identical_chess_piece,
    is_chess_capture_step,
    is_chess_piece,
)
from cursed_words_solver.rules.fraction_tiles import fraction_parts, is_fraction_tile

NON_COLOUR_FOR_NUMBER_BONUS = frozenset(
    {
        TileColor.COLORLESS,
        TileColor.UNKNOWN,
        TileColor.WHITE,
    }
)

VOWELS = frozenset("aeiou")
VWXYZ = frozenset("vwxyz")
RED_NOTES = frozenset("abcdefg")
STRAIGHT_RANK_ORDER = "23456789TJQKA"
FACE_CARD_RANKS = frozenset("JQK")
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


def scaled_pin_value(base: int, per_upgrade: int, upgrade_level: int) -> int:
    return int(base) + int(per_upgrade) * max(upgrade_level, 0)


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


def _melmod_number_colour_baked_into_score(tile: Tile) -> bool:
    """Melmod may export NUMBER tiles as colorless when GetTileType() is Normal.

    Red scatter often adds +2 to packet.Score above the face value; use that signal
    until BoardExporter reads colour from the tile packet.
    """
    if tile.metadata.get("source") != "melmod":
        return False
    if tile.curse != CurseType.NUMBER:
        return False
    if tile.color not in NON_COLOUR_FOR_NUMBER_BONUS:
        return False
    nv = tile.number_value
    if nv is None and tile.letter.isdigit():
        nv = int(tile.letter)
    if nv is None:
        return False
    return float(tile.base_score) - float(nv) == 2.0


def is_colored_number_tile(tile: Tile) -> bool:
    """NUMBER/FRACTION curse on a tile that counts as a colour (wiki: colourless is not a colour).

    VOID numbers are coloured (void is a tile colour). Only colourless/unknown/white
    number tiles are excluded unless melmod baked +2 implies red scatter.
    """
    if not is_number_like_tile(tile):
        return False
    if tile.color not in NON_COLOUR_FOR_NUMBER_BONUS:
        return True
    return _melmod_number_colour_baked_into_score(tile)


def is_consumable_tile(tile: Tile) -> bool:
    val = tile.metadata.get("consumable")
    return val is True or val == "true" or val == 1 or val == "1"


def is_cursed_tile(tile: Tile) -> bool:
    return tile.curse not in (CurseType.LETTER, CurseType.UNKNOWN)


def is_colourless_cursed_tile(tile: Tile) -> bool:
    return is_cursed_tile(tile) and tile.color in NON_COLOUR_FOR_NUMBER_BONUS


def curse_type_key(tile: Tile) -> str:
    return tile.curse.value


def word_starts_ends_different_curse_type(board: Board, path: list[int]) -> bool:
    if len(path) < 2:
        return False
    start = board.get_by_index(path[0])
    end = board.get_by_index(path[-1])
    if not is_cursed_tile(start) or not is_cursed_tile(end):
        return False
    return curse_type_key(start) != curse_type_key(end)


def word_all_cursed_tiles(board: Board, path: list[int]) -> bool:
    if not path:
        return False
    return all(is_cursed_tile(board.get_by_index(idx)) for idx in path)


def is_card_tile(tile: Tile) -> bool:
    if tile.curse == CurseType.CARD:
        return True
    return bool(tile.metadata.get("card_suit"))


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


def cards_on_path(board: Board, path: list[int]) -> list[Tile]:
    return [board.get_by_index(idx) for idx in path if is_card_tile(board.get_by_index(idx))]


def max_matching_rank_count(cards: list[Tile]) -> int:
    ranks = [card_rank(t) for t in cards if card_rank(t)]
    if not ranks:
        return 0
    return max(Counter(ranks).values())


def has_pair(cards: list[Tile]) -> bool:
    return max_matching_rank_count(cards) >= 2


def has_three_of_a_kind(cards: list[Tile]) -> bool:
    return max_matching_rank_count(cards) >= 3


def has_four_of_a_kind(cards: list[Tile]) -> bool:
    return max_matching_rank_count(cards) >= 4


def card_hand_min_size(loadout: Loadout | None) -> int:
    from cursed_words_solver.rules.stamp_behaviors import loadout_has_stamp

    if loadout_has_stamp(loadout, "martini"):
        return 3
    return 5


def has_flush(cards: list[Tile], min_size: int = 5) -> bool:
    suits = [card_suit(t) for t in cards if card_suit(t)]
    if len(suits) < min_size:
        return False
    return max(Counter(suits).values()) >= min_size


def _rank_index(rank: str) -> int | None:
    r = rank.upper()
    if len(r) != 1:
        return None
    try:
        return STRAIGHT_RANK_ORDER.index(r)
    except ValueError:
        return None


def has_straight(cards: list[Tile], min_size: int = 5) -> bool:
    indices = sorted(
        {idx for t in cards if (idx := _rank_index(card_rank(t) or "")) is not None}
    )
    if len(indices) < min_size:
        return False
    span = min_size - 1
    for i in range(len(indices) - span):
        if indices[i + span] - indices[i] == span:
            window = indices[i : i + min_size]
            if all(window[j + 1] - window[j] == 1 for j in range(span)):
                return True
    return False


def unused_cards_on_board(board: Board, path: list[int]) -> int:
    used = set(path)
    return sum(
        1 for tile in board.flat if is_card_tile(tile) and tile.index not in used
    )


def word_starts_with_face_card(board: Board, path: list[int]) -> bool:
    if not path:
        return False
    tile = board.get_by_index(path[0])
    rank = card_rank(tile)
    return is_card_tile(tile) and rank in FACE_CARD_RANKS and card_suit(tile) is not None


def word_starts_ends_different_suit(board: Board, path: list[int]) -> bool:
    if len(path) < 2:
        return False
    start = board.get_by_index(path[0])
    end = board.get_by_index(path[-1])
    if not is_card_tile(start) or not is_card_tile(end):
        return False
    s0, s1 = card_suit(start), card_suit(end)
    return bool(s0 and s1 and s0 != s1)


def detect_card_hand(
    hand: str,
    board: Board,
    path: list[int],
    loadout: Loadout | None = None,
) -> bool:
    cards = cards_on_path(board, path)
    min_size = card_hand_min_size(loadout)
    if hand == "pair":
        return has_pair(cards)
    if hand == "three_of_a_kind":
        return has_three_of_a_kind(cards)
    if hand == "four_of_a_kind":
        return has_four_of_a_kind(cards)
    if hand == "flush":
        return has_flush(cards, min_size)
    if hand == "straight":
        return has_straight(cards, min_size)
    return False


def is_chess_tile(tile: Tile) -> bool:
    return tile.curse in CHESS_CURSES


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


def is_take_tile(tile: Tile, *, strict: bool = False) -> bool:
    """Melmod take metadata on a tile (strict ignores non-metadata)."""
    if _has_take_metadata(tile):
        return True
    return False


def is_take_at_path_position(
    board: Board,
    path: list[int],
    pos: int,
    *,
    strict: bool = False,
    allies_can_take: bool = False,
) -> bool:
    """Whether path[pos] counts as a chess capture landing square."""
    tile = board.get_by_index(path[pos])
    if _has_take_metadata(tile):
        return True
    if strict or pos == 0:
        return False
    prefix = path[:pos]
    return is_chess_capture_step(
        board,
        path[pos - 1],
        path[pos],
        allies_can_take=allies_can_take,
        path_prefix=prefix,
        visited=set(prefix),
    )


def chess_take_path_positions(
    board: Board, path: list[int], *, strict: bool = False
) -> list[int]:
    """Indices into path for tiles that count as takes."""
    return [
        i
        for i in range(len(path))
        if is_take_at_path_position(board, path, i, strict=strict)
    ]


def chess_piece_value(tile: Tile) -> int:
    return CHESS_PIECE_VALUES.get(tile.curse, 0)


def _is_full_moon_chess_teleport_step(
    board: Board, path: list[int], pos: int
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
    return not is_chess_capture_step(
        board,
        from_idx,
        to_idx,
        path_prefix=prefix,
        visited=set(prefix),
    )


def movie_camera_take_piece_value_at(
    board: Board, path: list[int], pos: int
) -> int:
    """Movie Camera piece value for a capture landing at path[pos]."""
    landing = board.get_by_index(path[pos])
    if pos >= 2 and _is_full_moon_chess_teleport_step(board, path, pos - 1):
        from_tile = board.get_by_index(path[pos - 1])
        from_half = int(from_tile.base_score // 2)
        land_half = int(landing.base_score // 2)
        return max(from_half, land_half, chess_piece_value(landing))
    piece = chess_piece_value(landing)
    if is_chess_piece(landing):
        boosted = int(landing.base_score)
        if boosted > piece * 2:
            return boosted
    return piece


def _movie_camera_take_excluded(
    board: Board, path: list[int], take_pos: int, all_takes: list[int]
) -> bool:
    """Drop a capture superseded by a later take after a Full Moon chain across letter tiles."""
    for fm_pos in range(take_pos + 1, len(path)):
        if not _is_full_moon_chess_teleport_step(board, path, fm_pos):
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
    board: Board, path: list[int], *, strict: bool = False
) -> list[int]:
    """Path indices for captures that count toward Movie Camera's first-N takes."""
    all_takes = chess_take_path_positions(board, path, strict=strict)
    return [
        pos
        for pos in all_takes
        if not _movie_camera_take_excluded(board, path, pos, all_takes)
    ]


def first_n_movie_camera_piece_value_sum(
    board: Board,
    path: list[int],
    n: int,
    *,
    strict: bool = False,
) -> int:
    total = 0
    for pos in movie_camera_take_path_positions(board, path, strict=strict)[
        : max(n, 0)
    ]:
        total += movie_camera_take_piece_value_at(board, path, pos)
    return total


def first_n_take_piece_value_sum(
    board: Board,
    path: list[int],
    n: int,
    *,
    strict: bool = False,
    value_fn: Callable[[Board, list[int], int], int] | None = None,
) -> int:
    def _default_value(b: Board, p: list[int], pos: int) -> int:
        return chess_piece_value(b.get_by_index(p[pos]))

    fn = value_fn or _default_value
    total = 0
    for pos in chess_take_path_positions(board, path, strict=strict)[: max(n, 0)]:
        total += fn(board, path, pos)
    return total


def is_vowel_letter(ch: str) -> bool:
    return len(ch) == 1 and ch.lower() in VOWELS


def is_consonant_letter(ch: str) -> bool:
    return len(ch) == 1 and ch.isalpha() and ch.lower() not in VOWELS


def is_red_note_tile(tile: Tile) -> bool:
    return tile.color == TileColor.RED and tile.letter.lower() in RED_NOTES


def tile_number_value(tile: Tile) -> int:
    if tile.number_value is not None:
        return tile.number_value
    if tile.letter.isdigit():
        return int(tile.letter)
    return 0


def is_number_tile(tile: Tile) -> bool:
    return tile.curse == CurseType.NUMBER


def is_number_like_tile(tile: Tile) -> bool:
    return tile.curse in (CurseType.NUMBER, CurseType.FRACTION)


def tile_numeric_value(tile: Tile) -> float:
    """Face value for sums/ordering: integer for NUMBER, fraction float for FRACTION."""
    if is_fraction_tile(tile):
        if tile.fraction_value is not None:
            return float(tile.fraction_value)
        parts = fraction_parts(tile)
        if parts is not None:
            num, den = parts
            return num / den if den else 0.0
        return 0.0
    return float(tile_number_value(tile))


def word_all_numbers_on_path(board: Board, path: list[int]) -> bool:
    if not path:
        return False
    return all(is_number_like_tile(board.get_by_index(idx)) for idx in path)


def number_tile_count_on_path(board: Board, path: list[int]) -> int:
    return sum(
        1 for idx in path if is_number_like_tile(board.get_by_index(idx))
    )


def number_sum_on_path(board: Board, path: list[int]) -> float:
    total = 0.0
    for idx in path:
        tile = board.get_by_index(idx)
        if is_number_like_tile(tile):
            total += tile_numeric_value(tile)
    return total


def highest_number_on_path(board: Board, path: list[int]) -> float:
    values = [
        tile_numeric_value(board.get_by_index(idx))
        for idx in path
        if is_number_like_tile(board.get_by_index(idx))
    ]
    return max(values) if values else 0.0


def path_starts_ends_number(board: Board, path: list[int]) -> bool:
    if len(path) < 2:
        return False
    return is_number_like_tile(board.get_by_index(path[0])) and is_number_like_tile(
        board.get_by_index(path[-1])
    )


def path_contains_number_value(board: Board, path: list[int], target: int) -> bool:
    for idx in path:
        tile = board.get_by_index(idx)
        if is_number_like_tile(tile):
            if abs(tile_numeric_value(tile) - float(target)) < 1e-9:
                return True
    return False


def target_number_from_loadout(loadout: Loadout) -> int:
    try:
        return int((loadout.extras or {}).get("target_number", -1))
    except (TypeError, ValueError):
        return -1


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


def target_chess_curse_from_loadout(loadout: Loadout) -> CurseType | None:
    raw = str((loadout.extras or {}).get("target_chess_piece", "") or "").strip().lower()
    if not raw:
        return None
    if raw.startswith("chess_"):
        raw = raw[6:]
    return _CHESS_PIECE_SLUGS.get(raw)


def michael_book_bonus(loadout: Loadout) -> int:
    return max(0, _extra_int(loadout, "michael_book_bonus", 0))


def birthday_cake_accumulated(loadout: Loadout) -> int:
    """Runtime 'Get +X WORD SCORE' total exported from the Birthday Cake sticker."""
    return max(0, _extra_int(loadout, "birthday_cake_bonus", 0))


def card_count_on_path(board: Board, path: list[int]) -> int:
    return len(cards_on_path(board, path))


def colourless_adjacent_two_unique_colours(board: Board, tile: Tile) -> bool:
    """COLOURLESS tile with ≥2 orthogonally adjacent uniquely coloured neighbours."""
    if tile.color != TileColor.COLORLESS:
        return False
    neighbor_colors: set[TileColor] = set()
    for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        neighbor = board.get(tile.row + dr, tile.col + dc)
        if neighbor is None:
            continue
        if neighbor.color in NON_COLOUR_FOR_NUMBER_BONUS:
            continue
        neighbor_colors.add(neighbor.color)
    return len(neighbor_colors) >= 2


def grid_total_base_score(board: Board) -> int:
    return sum(
        tile_base_contribution(tile, board.money) for tile in board.flat
    )


def consecutive_number_run_path_positions(path: list[int], board: Board) -> list[int]:
    """Positions along path in runs of >=2 consecutive number-like tiles."""
    qualifying: list[int] = []
    start = 0
    while start < len(path):
        if not is_number_like_tile(board.get_by_index(path[start])):
            start += 1
            continue
        end = start
        while end < len(path) and is_number_like_tile(
            board.get_by_index(path[end])
        ):
            end += 1
        if end - start >= 2:
            qualifying.extend(range(start, end))
        start = end
    return qualifying


def unique_colours_on_path(board: Board, path: list[int]) -> set[str]:
    colours: set[str] = set()
    for idx in path:
        color = board.get_by_index(idx).color
        if color not in NON_COLOUR_FOR_NUMBER_BONUS:
            colours.add(color.value)
    return colours


def count_color_on_path(board: Board, path: list[int], color: str) -> int:
    return sum(
        1 for idx in path if board.get_by_index(idx).color.value == color
    )


def path_indices_set(path: list[int]) -> set[int]:
    return set(path)


def void_tiles_unused_in_word(board: Board, path: list[int]) -> int:
    used = path_indices_set(path)
    count = 0
    for tile in board.flat:
        if tile.color != TileColor.VOID:
            continue
        if tile.index in used:
            continue
        count += 1
    return count


def unused_red_tiles_on_board(board: Board, path: list[int]) -> int:
    used = path_indices_set(path)
    return sum(
        1
        for tile in board.flat
        if tile.color == TileColor.RED and tile.index not in used
    )


def unique_vowels_in_word(word: str) -> int:
    return len({c for c in word.lower() if c in VOWELS})


def has_double_letter(word: str) -> bool:
    w = word.lower()
    for i in range(len(w) - 1):
        if w[i] == w[i + 1] and w[i].isalpha():
            return True
    return False


def word_same_start_end_letter(word: str) -> bool:
    w = word.lower()
    if len(w) < 2:
        return False
    return w[0] == w[-1] and w[0].isalpha()


def consumable_rack_count(loadout: Loadout) -> int:
    return max(0, _extra_int(loadout, "consumable_rack_count", 0))


def rare_item_count(loadout: Loadout) -> int:
    return max(0, _extra_int(loadout, "rare_item_count", 0))


def level_one_sticker_count(loadout: Loadout) -> int:
    return sum(1 for s in loadout.stickers if s.level == 1)


def fairy_count(loadout: Loadout) -> int:
    return max(0, _extra_int(loadout, "fairy_count", 0))


def animal_stamp_count(loadout: Loadout) -> int:
    return max(0, _extra_int(loadout, "animal_stamp_count", 0))


def money_lost_encounter(loadout: Loadout) -> int:
    return max(0, _extra_int(loadout, "money_lost_encounter", 0))


def grid_number(loadout: Loadout) -> int:
    return max(0, _extra_int(loadout, "grid_number", 0))


def grid_number_half(loadout: Loadout) -> float:
    return grid_number(loadout) / 2.0


def consumable_count_on_path(board: Board, path: list[int]) -> int:
    return sum(
        1 for idx in path if is_consumable_tile(board.get_by_index(idx))
    )


def chess_piece_count_on_path(board: Board, path: list[int]) -> int:
    return sum(1 for idx in path if is_chess_tile(board.get_by_index(idx)))


def chess_balanced_colors(board: Board, path: list[int]) -> bool:
    black = white = 0
    for idx in path:
        tile = board.get_by_index(idx)
        if not is_chess_tile(tile) or not chess_side_known(tile):
            continue
        if chess_side(tile) == "white":
            white += 1
        else:
            black += 1
    return black > 0 and black == white


def currency_letter_value(tile: Tile) -> int:
    glyph = normalize_tile_glyph(tile.char or tile.letter or "")
    if glyph in CURRENCY_MAP:
        return _scrabble_value(CURRENCY_MAP[glyph])
    ch = (tile.letter or "").strip().upper()
    if len(ch) == 1 and ch.isalpha():
        return _scrabble_value(ch)
    return 0


def currency_value_on_path(board: Board, path: list[int]) -> int:
    total = 0
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.CURRENCY:
            total += currency_letter_value(tile)
    return total


def currency_on_path(board: Board, path: list[int]) -> bool:
    return any(board.get_by_index(idx).curse == CurseType.CURRENCY for idx in path)


def money_for_scoring(board: Board, path: list[int], loadout: Loadout) -> int:
    """Money for per-$ rules (Credit Card, etc.): in-run bank only, not path tiles."""
    return max(board.money, loadout.money, 0)


def path_all_non_adjacent(path: list[int]) -> bool:
    if len(path) <= 1:
        return True
    return non_adjacent_step_count(path) == len(path) - 1


def longest_red_run_on_path(board: Board, path: list[int]) -> int:
    best = cur = 0
    for idx in path:
        if board.get_by_index(idx).color == TileColor.RED:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def number_digits_ascending(word: str) -> bool:
    digits = [int(ch) for ch in word if ch.isdigit()]
    if len(digits) < 2:
        return True
    return all(digits[i] < digits[i + 1] for i in range(len(digits) - 1))


def max_qualifying_letter_half_multiplier(
    board: Board, path: list[int], min_count: int = 3
) -> float:
    counts = letter_counts_on_path(board, path)
    best = 1.0
    for count in counts.values():
        if count >= min_count:
            best = max(best, count / 2.0)
    return best


def red_tiles_used_encounter(loadout: Loadout) -> int:
    return max(0, _extra_int(loadout, "red_tiles_used_encounter", 0))


def subtotal_before_mult(state: dict) -> float:
    """Tile total + word score before word multipliers (Jigsaw Piece timing)."""
    return sum(state["tile_scores"]) + state["word_score"]


def adjacent_void_count(board: Board, tile: Tile) -> int:
    """Orthogonal neighbours on the 5×5 grid that are VOID."""
    count = 0
    for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        neighbor = board.get(tile.row + dr, tile.col + dc)
        if neighbor is not None and neighbor.color == TileColor.VOID:
            count += 1
    return count


def word_starts_ends_different_color(board: Board, path: list[int]) -> bool:
    if len(path) < 2:
        return False
    start = board.get_by_index(path[0]).color
    end = board.get_by_index(path[-1]).color
    if start in NON_COLOUR_FOR_NUMBER_BONUS or end in NON_COLOUR_FOR_NUMBER_BONUS:
        return False
    return start != end


def _path_step_adjacent(idx_a: int, idx_b: int) -> bool:
    r1, c1 = divmod(idx_a, 5)
    r2, c2 = divmod(idx_b, 5)
    return abs(r1 - r2) + abs(c1 - c2) == 1


def non_adjacent_step_count(path: list[int]) -> int:
    if len(path) < 2:
        return 0
    return sum(
        1
        for i in range(len(path) - 1)
        if not _path_step_adjacent(path[i], path[i + 1])
    )


def wildcard_count_on_path(board: Board, path: list[int]) -> int:
    count = 0
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.WILDCARD or tile.letter == "?":
            count += 1
    return count


def word_all_colourless_on_path(board: Board, path: list[int]) -> bool:
    if not path:
        return False
    return all(
        board.get_by_index(idx).color == TileColor.COLORLESS for idx in path
    )


def word_all_uncursed_on_path(board: Board, path: list[int]) -> bool:
    if not path:
        return False
    return all(
        board.get_by_index(idx).curse == CurseType.LETTER for idx in path
    )


def has_blue_red_and_colourless_on_path(board: Board, path: list[int]) -> bool:
    has_blue = has_red = has_colourless = False
    for idx in path:
        color = board.get_by_index(idx).color
        if color == TileColor.BLUE:
            has_blue = True
        elif color == TileColor.RED:
            has_red = True
        elif color == TileColor.COLORLESS:
            has_colourless = True
    return has_blue and has_red and has_colourless


def unique_colour_count_on_path(board: Board, path: list[int]) -> int:
    return len(unique_colours_on_path(board, path))


def distinct_curse_types_on_path(board: Board, path: list[int]) -> int:
    types = {
        curse_type_key(board.get_by_index(idx))
        for idx in path
        if is_cursed_tile(board.get_by_index(idx))
    }
    return len(types)


def unique_curse_type_count_on_path(board: Board, path: list[int]) -> int:
    """Distinct curse types among all tiles on the path (Oden)."""
    return len({curse_type_key(board.get_by_index(idx)) for idx in path})


def coloured_tile_count_on_grid(board: Board) -> int:
    return sum(
        1
        for tile in board.flat
        if tile.color not in NON_COLOUR_FOR_NUMBER_BONUS
    )


def distinct_card_suits_on_path(board: Board, path: list[int]) -> int:
    suits = {card_suit(board.get_by_index(idx)) for idx in path}
    suits.discard(None)
    return len(suits)


def distinct_pair_count_on_path(board: Board, path: list[int]) -> int:
    cards = cards_on_path(board, path)
    ranks = [card_rank(t) for t in cards if card_rank(t)]
    return sum(1 for count in Counter(ranks).values() if count >= 2)


def king_take_on_path(board: Board, path: list[int]) -> bool:
    for pos in chess_take_path_positions(board, path):
        tile = board.get_by_index(path[pos])
        if tile.curse == CurseType.CHESS_KING:
            return True
    return False


def chess_move_tile_count_on_path(
    board: Board, path: list[int], loadout: Loadout
) -> int:
    extra = _extra_int(loadout, "chess_move_tile_count", -1)
    if extra >= 0:
        return extra
    return sum(1 for idx in path if is_chess_tile(board.get_by_index(idx)))


def shop_restock_count(loadout: Loadout) -> int:
    return max(0, _extra_int(loadout, "shop_restock_count", 0))


def target_curse_type_from_loadout(loadout: Loadout) -> CurseType:
    raw = str((loadout.extras or {}).get("target_curse_type", "wildcard") or "wildcard")
    raw = raw.strip().lower()
    mapping = {
        "wildcard": CurseType.WILDCARD,
        "letter": CurseType.LETTER,
        "number": CurseType.NUMBER,
        "currency": CurseType.CURRENCY,
        "card": CurseType.CARD,
        "chess_pawn": CurseType.CHESS_PAWN,
        "chess_bishop": CurseType.CHESS_BISHOP,
        "chess_rook": CurseType.CHESS_ROOK,
        "chess_knight": CurseType.CHESS_KNIGHT,
        "chess_queen": CurseType.CHESS_QUEEN,
        "chess_king": CurseType.CHESS_KING,
    }
    return mapping.get(raw, CurseType.WILDCARD)


def path_has_wildcard_matching_target_curse(
    board: Board, path: list[int], loadout: Loadout
) -> bool:
    target = target_curse_type_from_loadout(loadout)
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse == target or (
            target == CurseType.WILDCARD
            and (tile.curse == CurseType.WILDCARD or tile.letter == "?")
        ):
            return True
    return False


def word_starts_ends_consumable(board: Board, path: list[int]) -> bool:
    if len(path) < 2:
        return False
    start = board.get_by_index(path[0])
    end = board.get_by_index(path[-1])
    return is_consumable_tile(start) and is_consumable_tile(end)


def shield_blue_base_from_loadout(loadout: Loadout, rules: dict) -> int | None:
    from cursed_words_solver.rules.rule_lookup import get_rule

    for sticker in loadout.stickers:
        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
        if rule and rule.get("type") == "blue_tile_base_override":
            return sticker_rule_int(sticker.level, rule)
    return None


def sticker_in_slot(loadout: Loadout, applying_sticker_id: str, slot: str) -> bool:
    from cursed_words_solver.rules.rule_lookup import slugify_name

    if not loadout.stickers or not applying_sticker_id:
        return False
    slug = slugify_name(applying_sticker_id)
    stickers = loadout.stickers
    if slot == "first":
        first = stickers[0]
        return slugify_name(first.id or first.name) == slug
    if slot == "last":
        last = stickers[-1]
        return slugify_name(last.id or last.name) == slug
    return False


def explain_sticker_condition(
    condition: str,
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    *,
    applying_sticker_id: str = "",
) -> tuple[bool, str]:
    """Evaluate a sticker condition and return (met, human-readable reason)."""
    if condition == "word_starts_vwxyz":
        first = word_first_letter(word)
        path_first = first_letter_on_path(board, path)
        if not first:
            return False, "skipped: no word first letter"
        if first not in VWXYZ:
            return False, f"skipped: word '{first}' not in vwxyz"
        if first != path_first:
            path_label = path_first or "?"
            return False, f"skipped: word '{first}' != path first letter '{path_label}'"
        return True, f"applied: word '{first}' matches path first letter '{path_first}'"

    if condition == "word_starts_same_as_previous":
        prev = _extra_letter(loadout, "previous_word_first_letter")
        first = _effective_word_start_letter(board, path, word)
        if not prev or not first:
            return False, f"skipped: missing previous or word first letter (prev={prev!r}, word={first!r})"
        if first != prev:
            return False, f"skipped: word starts '{first}', previous '{prev}'"
        return True, f"applied: word starts '{first}' same as previous"

    if condition == "word_starts_after_previous":
        prev = _extra_letter(loadout, "previous_word_first_letter")
        first = _effective_word_start_letter(board, path, word)
        if not prev or not first:
            return False, f"skipped: missing previous or word first letter (prev={prev!r}, word={first!r})"
        if first <= prev:
            return False, f"skipped: word starts '{first}', not after previous '{prev}'"
        return True, f"applied: word starts '{first}' after previous '{prev}'"

    met = _evaluate_sticker_condition(
        condition,
        board,
        path,
        word,
        loadout,
        applying_sticker_id=applying_sticker_id,
    )
    if not condition:
        return False, "skipped: empty condition"
    if met:
        return True, f"applied ({condition})"
    return False, f"skipped ({condition})"


def evaluate_sticker_condition(
    condition: str,
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    *,
    applying_sticker_id: str = "",
) -> bool:
    return explain_sticker_condition(
        condition,
        board,
        path,
        word,
        loadout,
        applying_sticker_id=applying_sticker_id,
    )[0]


def _evaluate_sticker_condition(
    condition: str,
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    *,
    applying_sticker_id: str = "",
) -> bool:
    if not condition:
        return False

    if condition == "always":
        return True

    w = word.lower()
    if not path and condition not in ("first_grid_of_encounter",):
        return False

    if condition == "ends_with_color:blue":
        return board.get_by_index(path[-1]).color == TileColor.BLUE
    if condition == "red_count_gte:3":
        return count_color_on_path(board, path, "red") >= 3
    if condition == "word_starts_vowel":
        first = word_first_letter(word)
        return bool(first) and is_vowel_letter(first)
    if condition == "word_starts_ends_red":
        if not path:
            return False
        return (
            board.get_by_index(path[0]).color == TileColor.RED
            and board.get_by_index(path[-1]).color == TileColor.RED
        )
    if condition == "no_colorless_on_path":
        return all(
            board.get_by_index(idx).color not in NON_COLOUR_FOR_NUMBER_BONUS
            for idx in path
        )
    if condition == "blue_count_eq:2":
        return count_color_on_path(board, path, "blue") == 2
    if condition == "word_starts_vwxyz":
        first = word_first_letter(word)
        if not first or first not in VWXYZ:
            return False
        return first == first_letter_on_path(board, path)
    if condition == "word_starts_same_as_previous":
        prev = _extra_letter(loadout, "previous_word_first_letter")
        first = _effective_word_start_letter(board, path, word)
        if not prev or not first:
            return False
        return first == prev
    if condition == "word_starts_after_previous":
        prev = _extra_letter(loadout, "previous_word_first_letter")
        first = _effective_word_start_letter(board, path, word)
        if not prev or not first:
            return False
        return first > prev
    if condition == "has_double_letter":
        return has_double_letter(word)
    if condition == "first_grid_of_encounter":
        return _extra_bool(loadout, "is_first_grid_of_encounter")
    if condition == "word_starts_ends_different_color":
        return word_starts_ends_different_color(board, path)
    if condition.startswith("unique_colours_gte:"):
        try:
            min_n = int(condition.split(":", 1)[1])
        except (ValueError, IndexError):
            return False
        return len(unique_colours_on_path(board, path)) >= min_n
    if condition == "word_starts_ends_number":
        return path_starts_ends_number(board, path)
    if condition == "contains_target_number":
        target = target_number_from_loadout(loadout)
        if target < 0:
            return False
        return path_contains_number_value(board, path, target)
    if condition.startswith("chess_takes_gte:"):
        try:
            min_n = int(condition.split(":", 1)[1])
        except (ValueError, IndexError):
            return False
        return chess_takes_on_path(board, path) >= min_n
    if condition == "word_starts_face_card":
        return word_starts_with_face_card(board, path)
    if condition == "word_starts_ends_different_suit":
        return word_starts_ends_different_suit(board, path)
    if condition.startswith("card_hand:"):
        hand = condition.split(":", 1)[1]
        return detect_card_hand(hand, board, path, loadout)
    if condition == "word_starts_ends_different_curse_type":
        return word_starts_ends_different_curse_type(board, path)
    if condition == "word_all_cursed":
        return word_all_cursed_tiles(board, path)
    if condition.startswith("card_count_eq:"):
        try:
            n = int(condition.split(":", 1)[1])
        except (ValueError, IndexError):
            return False
        return card_count_on_path(board, path) == n
    if condition.startswith("path_length_lte:"):
        try:
            n = int(condition.split(":", 1)[1])
        except (ValueError, IndexError):
            return False
        return len(path) <= n
    if condition.startswith("path_length_gte:"):
        try:
            n = int(condition.split(":", 1)[1])
        except (ValueError, IndexError):
            return False
        return len(path) >= n
    if condition.startswith("wildcard_count_eq:"):
        try:
            n = int(condition.split(":", 1)[1])
        except (ValueError, IndexError):
            return False
        return wildcard_count_on_path(board, path) == n
    if condition.startswith("unique_colours_eq:"):
        try:
            n = int(condition.split(":", 1)[1])
        except (ValueError, IndexError):
            return False
        return unique_colour_count_on_path(board, path) == n
    if condition.startswith("curse_types_gte:"):
        try:
            n = int(condition.split(":", 1)[1])
        except (ValueError, IndexError):
            return False
        return distinct_curse_types_on_path(board, path) >= n
    if condition.startswith("distinct_card_suits_gte:"):
        try:
            n = int(condition.split(":", 1)[1])
        except (ValueError, IndexError):
            return False
        return distinct_card_suits_on_path(board, path) >= n
    if condition.startswith("non_adjacent_steps_gte:"):
        try:
            n = int(condition.split(":", 1)[1])
        except (ValueError, IndexError):
            return False
        return non_adjacent_step_count(path) >= n
    if condition == "word_all_colourless":
        return word_all_colourless_on_path(board, path)
    if condition == "word_all_uncursed":
        return word_all_uncursed_on_path(board, path)
    if condition == "has_blue_red_and_colourless":
        return has_blue_red_and_colourless_on_path(board, path)
    if condition == "word_starts_ends_consumable":
        return word_starts_ends_consumable(board, path)
    if condition.startswith("requires_sticker_slot:"):
        slot = condition.split(":", 1)[1]
        return sticker_in_slot(loadout, applying_sticker_id, slot)
    if condition == "money_eq:0":
        return max(board.money, loadout.money, 0) == 0
    if condition == "path_all_non_adjacent":
        return path_all_non_adjacent(path)
    if condition == "chess_balanced_colors":
        return chess_balanced_colors(board, path)
    if condition == "currency_on_path":
        return currency_on_path(board, path)
    if condition == "frozen_in_shop":
        return _extra_bool(loadout, "frozen_in_shop")
    return False


def tile_matches_target(tile: Tile, target: str) -> bool:
    if target == "currency":
        return tile.curse == CurseType.CURRENCY
    if target == "red":
        return tile.color == TileColor.RED
    if target == "blue":
        return tile.color == TileColor.BLUE
    if target == "colored":
        return tile.color not in NON_COLOUR_FOR_NUMBER_BONUS
    if target == "wildcard":
        return tile.curse == CurseType.WILDCARD or tile.letter == "?"
    if target == "vowel":
        return is_vowel_letter(tile.letter)
    if target == "consonant":
        return is_consonant_letter(tile.letter)
    if target == "red_note":
        return is_red_note_tile(tile)
    if target == "void":
        return tile.color == TileColor.VOID
    if target == "shiny":
        return tile.color == TileColor.SHINY
    if target == "card":
        return is_card_tile(tile)
    if target == "cursed":
        return is_cursed_tile(tile)
    if target == "colourless_cursed":
        return is_colourless_cursed_tile(tile)
    if target == "all":
        return True
    if target.startswith("letter:"):
        want = target.split(":", 1)[1].strip().lower()
        return (tile.letter or "").strip().lower() == want
    return False


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


def chess_takes_on_path(board: Board, path: list[int], *, strict: bool = False) -> int:
    return len(chess_take_path_positions(board, path, strict=strict))


def abacus_colored_number_bonus(loadout: Loadout, rule: dict) -> int:
    """+N TILE SCORE per coloured number; N scales with right-side pin upgrades.

    Wiki Abacus right track: +10 at 0–1 upgrades, +20 at 2, +30 at 3, …
    """
    base = int(rule.get("value", 10))
    per_upgrade = int(rule.get("value_per_right_upgrade", 10))
    right = pin_right_level(loadout)
    return base + per_upgrade * max(0, right - 1)


def rainbow_per_colour_bonus(loadout: Loadout, rule: dict) -> int:
    base = int(rule.get("value", 5))
    per_upgrade = int(rule.get("value_per_right_upgrade", 5))
    return scaled_pin_value(base, per_upgrade, pin_right_level(loadout))


def mahjong_consumable_factor(loadout: Loadout, rule: dict) -> float:
    base = float(rule.get("factor_base", 2.0))
    per_right = float(rule.get("factor_per_pin_right", 1.0))
    return base + per_right * pin_right_level(loadout)


def super_8_take_word_bonus(loadout: Loadout, rule: dict) -> int:
    """Wiki Super 8 right track: +8 at even upgrade counts, +16/+24/+32 at odd.

    Pin levels from melmod are 1-indexed (Level 1 = base, no right upgrades yet).
    """
    base = int(rule.get("value", 8))
    right_upgrades = max(0, pin_right_level(loadout) - 1)
    if right_upgrades % 2 == 0:
        return base
    return base * ((right_upgrades + 1) // 2 + 1)


def bicycle_word_per_card(loadout: Loadout, rule: dict) -> int:
    base = int(rule.get("value", 0))
    per_upgrade = int(rule.get("value_per_right_upgrade", 1))
    return scaled_pin_value(base, per_upgrade, pin_right_level(loadout))


def cards_submitted_count(loadout: Loadout) -> int:
    try:
        return max(0, int((loadout.extras or {}).get("cards_submitted", 0)))
    except (TypeError, ValueError):
        return 0


def brain_multiplier(level: int, rule: dict) -> float:
    """Wiki: L1 ×1.5, L2 ×2, … → 1.0 + 0.5 × level."""
    base = float(rule.get("factor_base", 1.0))
    per_level = float(rule.get("factor_per_level", 0.5))
    return base + per_level * max(level, 1)


def tile_ninja_multiplier_bonus(loadout: Loadout) -> float:
    """Additive bonus on top of base ×WORD factor (wiki: +0.02 per consumable placed)."""
    try:
        return float((loadout.extras or {}).get("tile_ninja_bonus", 0))
    except (TypeError, ValueError):
        return 0.0


def scaled_word_multiplier(
    level: int,
    rule: dict,
    loadout: Loadout | None = None,
    path: list[int] | None = None,
) -> float:
    factor = sticker_rule_float(level, rule)
    if loadout is not None:
        scale = rule.get("scale_from_extras")
        if scale == "tile_ninja_bonus":
            factor += tile_ninja_multiplier_bonus(loadout)
        elif scale == "rare_item_count":
            factor += float(rare_item_count(loadout))
        elif scale == "level_one_sticker_count":
            factor += float(level_one_sticker_count(loadout))
        elif scale == "fairy_count":
            factor += float(fairy_count(loadout)) * float(
                rule.get("scale_per_extra", 0.5)
            )
        elif scale == "money_lost_encounter":
            factor += float(money_lost_encounter(loadout)) * float(
                rule.get("scale_per_extra", 0.01)
            )
        elif scale == "animal_stamp_count":
            factor += float(animal_stamp_count(loadout)) * float(
                rule.get("scale_per_extra", 1.0)
            )
    if path is not None and rule.get("scale_from_path") == "non_adjacent_steps":
        factor += non_adjacent_step_count(path) * float(rule.get("path_scale", 0.02))
    return factor


def path_letter_for_count(tile: Tile) -> str:
    """Lowercase letter used for Bubble Tea same-letter counts."""
    if tile.curse == CurseType.NUMBER:
        return ""
    ch = (tile.letter or "").strip().lower()
    if len(ch) == 1 and ch.isalpha():
        return ch
    return ""


def word_first_letter(word: str) -> str:
    """First alphabetic character of the submitted word (lowercase)."""
    w = (word or "").strip().lower()
    return w[0] if w and w[0].isalpha() else ""


def first_letter_on_path(board: Board, path: list[int]) -> str:
    """First A–Z letter tile along the path (skips currency, numbers, symbols)."""
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.CURRENCY:
            continue
        ch = path_letter_for_count(tile)
        if ch:
            return ch
    return ""


def _effective_word_start_letter(board: Board, path: list[int], word: str) -> str:
    """First letter for Bento/Chips-style conditions: path-first when currency leads."""
    path_first = first_letter_on_path(board, path)
    word_first = word_first_letter(word)
    if path_first and word_first and path_first != word_first:
        return path_first
    return word_first or path_first


def letter_counts_on_path(board: Board, path: list[int]) -> dict[str, int]:
    from collections import Counter

    letters = [path_letter_for_count(board.get_by_index(idx)) for idx in path]
    return dict(Counter(ch for ch in letters if ch))


def money_word_multiplier(level: int, rule: dict, money: int) -> float:
    rate = sticker_rule_float(level, rule)
    return 1.0 + rate * max(money, 0)


def consumable_rack_multiplier(level: int, rule: dict, loadout: Loadout) -> float:
    step = sticker_rule_float(level, rule)
    count = consumable_rack_count(loadout)
    return 1.0 + step * count


_BURRITO_LEVEL_EXCLUDE = frozenset({"burrito", "left_hand", "padlock_sticker"})


def other_sticker_levels_sum(loadout: Loadout, *, exclude_slug: str = "burrito") -> int:
    """Sum levels of equipped stickers except Burrito (RAM/pin_memory excluded)."""
    from cursed_words_solver.rules.rule_lookup import slugify_name

    skip = _BURRITO_LEVEL_EXCLUDE | {exclude_slug}
    return sum(
        s.level
        for s in loadout.stickers
        if slugify_name(s.id or s.name) not in skip
    )


def burrito_word_multiplier(level: int, rule: dict, loadout: Loadout) -> float:
    rate = sticker_rule_float(level, rule)
    extra = rate * other_sticker_levels_sum(loadout)
    return 1.0 + extra if extra else 1.0


def stamps_shop_price_total(loadout: Loadout, rules: dict | None = None) -> int:
    """Total shop price of stamps; extras override, else sum catalog shop_price."""
    if (loadout.extras or {}).get("stamps_shop_price_total") is not None:
        return max(0, _extra_int(loadout, "stamps_shop_price_total", 0))
    if not rules or not loadout.stamps:
        return 0
    from cursed_words_solver.rules.rule_lookup import get_rule

    total = 0
    for stamp in loadout.stamps:
        _key, stamp_rule = get_rule(rules, "stamps", stamp.id, stamp.name)
        if stamp_rule:
            try:
                total += max(0, int(stamp_rule.get("shop_price", 0)))
            except (TypeError, ValueError):
                pass
    return total
