"""Shared helpers for loadout scoring conditions (wiki-aligned)."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable

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
from cursed_words_solver.rules.base_scoring import _scrabble_value, tile_base_contribution
from cursed_words_solver.rules.chess_tiles import (
    chess_side,
    chess_side_known,
    identical_chess_piece,
    is_chess_capture_step,
    is_chess_piece,
)
from cursed_words_solver.rules.stamp_behaviors import StampSearchFlags, stamp_search_flags
from cursed_words_solver.rules.fraction_tiles import fraction_parts, is_fraction_tile

NON_COLOUR_FOR_NUMBER_BONUS = frozenset(
    {
        TileColor.COLORLESS,
        TileColor.UNKNOWN,
        TileColor.WHITE,
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


def human_hands_stamp_extra_apps(loadout: Loadout) -> int:
    """Game: favourite stamp scored (right.VariableValue - 1) extra times after stamps."""
    var = pin_right_variable(loadout)
    if var is not None:
        return max(0, var - 1)
    return max(0, pin_right_level(loadout))


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


def is_placed_consumable_tile(tile: Tile) -> bool:
    return tile.metadata.get("was_consumable") is True


def placed_consumable_indices(board: Board) -> frozenset[int]:
    return frozenset(
        i
        for i, tile in enumerate(board.flat)
        if board.active[i] and is_placed_consumable_tile(tile)
    )


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

    # The game groups related curses into broader categories for this condition.
    # - All chess pieces count as a single "chess" curse family.
    # - NUMBER + FRACTION are treated as the same "number" family.
    def curse_category(tile: Tile) -> str:
        if tile.curse in CHESS_CURSES:
            return "chess"
        if tile.curse in (CurseType.NUMBER, CurseType.FRACTION):
            return "number"
        return curse_type_key(tile)

    return curse_category(start) != curse_category(end)


def word_all_cursed_tiles(board: Board, path: list[int]) -> bool:
    if not path:
        return False
    return all(is_cursed_tile(board.get_by_index(idx)) for idx in path)


def cursed_word_played(_board: Board, path: list[int], word: str) -> bool:
    """Jack-o'-Lantern: every submitted word counts as a cursed word."""
    return bool(path and word)


def is_joker_tile(tile: Tile) -> bool:
    val = tile.metadata.get("is_joker")
    return val is True or val == "true" or val == 1 or val == "1"


def effective_is_face_card_start(tile: Tile) -> bool:
    """Whether this tile can satisfy Poker Face's 'starts with suited face card'.

    Joker tiles count as any face card at word start; Bicycle uses real suits only.
    Wrestlers: suited start + joker at end qualifies; joker at start + suited end does not.
    """
    if is_joker_tile(tile):
        return True
    rank = card_rank(tile)
    return bool(is_card_tile(tile) and rank in FACE_CARD_RANKS and card_suit(tile))


def is_card_tile(tile: Tile) -> bool:
    if is_joker_tile(tile):
        return False
    if tile.curse == CurseType.CARD:
        return True
    return bool(tile.metadata.get("card_suit"))


def is_poker_card_tile(tile: Tile) -> bool:
    return is_card_tile(tile) or is_joker_tile(tile)


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
    return [
        board.get_by_index(idx)
        for idx in path
        if is_poker_card_tile(board.get_by_index(idx))
    ]


def _joker_count(cards: list[Tile]) -> int:
    return sum(1 for t in cards if is_joker_tile(t))


def _suited_cards(cards: list[Tile]) -> list[Tile]:
    return [t for t in cards if is_card_tile(t)]


def max_matching_rank_count(cards: list[Tile]) -> int:
    ranks = [card_rank(t) for t in _suited_cards(cards) if card_rank(t)]
    if not ranks:
        return 0
    return max(Counter(ranks).values())


def has_pair(cards: list[Tile]) -> bool:
    jokers = _joker_count(cards)
    if jokers >= 2:
        return True
    best = max_matching_rank_count(cards)
    return best + jokers >= 2


def has_three_of_a_kind(cards: list[Tile]) -> bool:
    jokers = _joker_count(cards)
    return max_matching_rank_count(cards) + jokers >= 3


def has_four_of_a_kind(cards: list[Tile]) -> bool:
    jokers = _joker_count(cards)
    return max_matching_rank_count(cards) + jokers >= 4


def card_hand_min_size(loadout: Loadout | None) -> int:
    from cursed_words_solver.rules.stamp_behaviors import loadout_has_stamp

    if loadout_has_stamp(loadout, "martini"):
        return 3
    return 5


def has_flush(cards: list[Tile], min_size: int = 5) -> bool:
    jokers = _joker_count(cards)
    suits = [card_suit(t) for t in _suited_cards(cards) if card_suit(t)]
    if not suits:
        return jokers >= min_size
    if len(suits) + jokers < min_size:
        return False
    return max(Counter(suits).values()) + jokers >= min_size


def _rank_index(rank: str) -> int | None:
    r = rank.upper()
    if len(r) != 1:
        return None
    try:
        return STRAIGHT_RANK_ORDER.index(r)
    except ValueError:
        return None


def has_straight(cards: list[Tile], min_size: int = 5) -> bool:
    jokers = _joker_count(cards)
    indices = sorted(
        {
            idx
            for t in _suited_cards(cards)
            if (idx := _rank_index(card_rank(t) or "")) is not None
        }
    )
    if len(indices) + jokers < min_size:
        return False
    order_len = len(STRAIGHT_RANK_ORDER)
    for start in range(order_len - min_size + 1):
        window = set(range(start, start + min_size))
        have = len(window.intersection(indices))
        if have + jokers >= min_size:
            return True
    return False


def hanafuda_x_required(sticker_level: int) -> int:
    """Matching suited letters required (Pair=2, Three=3, Four=4)."""
    return min(4, sticker_level + 1)


def _poker_hand_joker(tile: Tile) -> bool:
    """In-game ``Suit.Joker`` for ``PokerHands.GetXOfAKind`` (Hanafuda hand detection only)."""
    if is_joker_tile(tile):
        return True
    if card_suit(tile) == "joker":
        return True
    if _is_joker_glyph_char(tile):
        return True
    return False


def _hanafuda_suited_non_joker(tile: Tile) -> bool:
    """Tiles that participate in Hanafuda letter groups (CardSuit set, not Joker)."""
    if _poker_hand_joker(tile):
        return False
    suit = card_suit(tile)
    return bool(suit and suit not in ("joker", "none"))


def _tile_string_representation(tile: Tile) -> str:
    """Mirror ``Tile.GetStringRepresentation()`` for Hanafuda / poker grouping."""
    ch = path_letter_for_count(tile)
    if ch:
        return ch
    if tile.letter:
        return str(tile.letter)
    return str(tile.char or "")


def get_x_of_a_kind_letters(cards: list[Tile], x: int) -> list[Tile] | None:
    """Mirror ``PokerHands.GetXOfAKind`` (groups by letter, jokers fill)."""
    suited = [t for t in cards if _hanafuda_suited_non_joker(t)]
    jokers = [t for t in cards if _poker_hand_joker(t)]
    if len(jokers) >= x:
        return jokers[:x]
    by_letter: dict[str, list[Tile]] = {}
    for tile in suited:
        key = _tile_string_representation(tile)
        if not key:
            continue
        group = by_letter.setdefault(key, [])
        group.append(tile)
        if len(group) + len(jokers) == x:
            hand = list(group)
            need = x - len(group)
            hand.extend(jokers[:need])
            return hand
    return None


def hanafuda_hand_satisfied(
    board: Board, path: list[int], sticker_level: int
) -> bool:
    """True when path has the Hanafuda hand for this sticker level."""
    x = hanafuda_x_required(sticker_level)
    path_tiles = [board.get_by_index(i) for i in path]
    return get_x_of_a_kind_letters(path_tiles, x) is not None


def _hanafuda_tile_has_suit(tile: Tile) -> bool:
    """``CardSuit != 0`` from board export (excludes bare wildcard without suit)."""
    suit = card_suit(tile)
    if suit and suit not in ("none",):
        if suit == "joker":
            return not (
                tile.curse == CurseType.LETTER and tile.color == TileColor.VOID
            )
        return True
    # Melmod can export joker glyph tiles without card_suit, but in-game they still
    # have CardSuit != 0 for Hanafuda unused-card credit.
    if _is_joker_glyph_char(tile) and not suit and not is_joker_tile(tile):
        return True
    return False


def _hanafuda_counts_as_unused(tile: Tile, path: list[int]) -> bool:
    """Unused card credit for Hanafuda (CardSuit != 0, not in submitted path).

    Off-path suited tiles count. Chess on path can count. Short words may count a
    path-end joker glyph with no exported suit (cly/ja captures); melmod wildcard
    tiles on the path never count (game excludes submitted tiles).
    """
    if not path:
        return False
    used = set(path)
    if tile.index not in used:
        return _hanafuda_tile_has_suit(tile)
    if is_chess_piece(tile) and _hanafuda_tile_has_suit(tile):
        return True
    if tile.index == path[-1] and len(path) <= 3:
        if is_joker_tile(tile) or (
            _is_joker_glyph_char(tile) and not card_suit(tile)
        ):
            return True
    return False


def unused_cards_on_board(board: Board, path: list[int]) -> int:
    """Tiles that grant Hanafuda +WORD per unused card (Hanafuda.ApplyWordBonus)."""
    return sum(1 for tile in board.flat if _hanafuda_counts_as_unused(tile, path))


def word_starts_with_face_card(board: Board, path: list[int]) -> bool:
    if not path:
        return False
    tile = board.get_by_index(path[0])
    return effective_is_face_card_start(tile)


def wrestlers_endpoint_tile(tile: Tile) -> bool:
    """True when a path endpoint qualifies for Wrestlers (CARD or suited letter card)."""
    if tile.curse == CurseType.CARD:
        return True
    return card_suit(tile) is not None


def wrestlers_endpoint_rank_qualifies(tile: Tile) -> bool:
    """Suited endpoint rank counts for Wrestlers (poker rank or high-value letter card)."""
    rank = card_rank(tile)
    if not rank:
        return False
    if rank.upper() in POKER_RANKS:
        return True
    return float(tile.base_score) >= 8.0


def _wrestlers_real_suit(tile: Tile) -> str | None:
    """Playing-card suit for Wrestlers (excludes joker tiles and pseudo-suit ``joker``)."""
    if is_joker_tile(tile):
        return None
    suit = card_suit(tile)
    if not suit or suit in ("joker", "none"):
        return None
    return suit


def _first_last_suited_path_positions(
    board: Board, path: list[int]
) -> tuple[int, int] | None:
    """First and last path indices with a real playing-card suit (Wrestlers endpoints)."""
    first: int | None = None
    last: int | None = None
    for i, idx in enumerate(path):
        tile = board.get_by_index(idx)
        if _wrestlers_real_suit(tile) is None:
            continue
        if first is None:
            first = i
        last = i
    if first is None or last is None or first == last:
        return None
    return first, last


def _first_last_different_suited_path_positions(
    board: Board, path: list[int]
) -> tuple[int, int] | None:
    """First suited tile and last suited tile whose suit differs from the first."""
    first: int | None = None
    first_suit: str | None = None
    last: int | None = None
    for i, idx in enumerate(path):
        tile = board.get_by_index(idx)
        suit = _wrestlers_real_suit(tile)
        if suit is None:
            continue
        if first is None:
            first = i
            first_suit = suit
            continue
        if suit != first_suit:
            last = i
    if first is None or last is None or first == last:
        return None
    return first, last


def _wrestlers_letter_endpoints_qualify(
    board: Board, path: list[int], start: Tile, end: Tile
) -> bool:
    """LETTER-curse suited pair qualifies for Wrestlers (already different suits)."""
    start_ch = path_letter_for_count(start)
    end_ch = path_letter_for_count(end)
    if start_ch == end_ch:
        if start.base_score != end.base_score:
            return False
        letter_count = sum(
            1
            for idx in path
            if path_letter_for_count(board.get_by_index(idx)) == start_ch
        )
        if float(start.base_score) >= 2.0 or float(end.base_score) >= 2.0:
            # Higher-value tiles require both to carry a valid poker rank; plain
            # letters that happen to have a scattered suit (e.g. Bicycle D-tiles
            # with base_score=2) do not qualify under same-letter matching.
            if not all(
                wrestlers_endpoint_rank_qualifies(t) for t in (start, end)
            ):
                return False
            return letter_count >= 3
        return letter_count >= 2
    if any(float(tile.base_score) >= 8.0 for tile in (start, end)):
        return True
    q0 = wrestlers_endpoint_rank_qualifies(start)
    q1 = wrestlers_endpoint_rank_qualifies(end)
    if not q0 and not q1:
        return False
    if q0 != q1:
        return start.base_score == end.base_score
    if q0 and q1 and start.base_score != end.base_score:
        return False
    return all(wrestlers_endpoint_rank_qualifies(tile) for tile in (start, end))


def word_starts_ends_different_suit(board: Board, path: list[int]) -> bool:
    """First/last suited tiles on path use different suits (CARD or letter cards)."""
    if len(path) < 2:
        return False
    path_start = board.get_by_index(path[0])
    path_end = board.get_by_index(path[-1])
    start_suit = _wrestlers_real_suit(path_start)
    end_suit = _wrestlers_real_suit(path_end)

    # Suited start + joker at path end qualifies (Wrestlers endpoint shortcut).
    if start_suit and is_joker_tile(path_end):
        return True

    # Joker at start: proc when path end is suited and ≥2 non-joker suited tiles on path.
    if is_joker_tile(path_start):
        non_joker_suited = sum(
            1
            for idx in path
            if _wrestlers_real_suit(board.get_by_index(idx)) is not None
        )
        if non_joker_suited < 2:
            return False
        if end_suit is not None:
            return True
        if not is_joker_tile(path_end):
            return False
        endpoints = _first_last_different_suited_path_positions(board, path)
        if endpoints is None:
            return False
        first_i, last_i = endpoints
        start = board.get_by_index(path[first_i])
        end = board.get_by_index(path[last_i])
        if start.curse == CurseType.LETTER and end.curse == CurseType.LETTER:
            if path_letter_for_count(start) == path_letter_for_count(end):
                return _wrestlers_letter_endpoints_qualify(
                    board, path, start, end
                )
        return True

    if start_suit and end_suit:
        if start_suit == end_suit:
            return False
        if (
            path_start.curse == CurseType.LETTER
            and path_end.curse == CurseType.LETTER
        ):
            return _wrestlers_letter_endpoints_qualify(
                board, path, path_start, path_end
            )
        return True

    if bool(start_suit) != bool(end_suit) and not is_joker_tile(path_start):
        return False

    endpoints = _first_last_suited_path_positions(board, path)
    if endpoints is None:
        return False
    first_i, last_i = endpoints
    start = board.get_by_index(path[first_i])
    end = board.get_by_index(path[last_i])
    s0, s1 = _wrestlers_real_suit(start), _wrestlers_real_suit(end)
    if not (s0 and s1 and s0 != s1):
        return False
    if start.curse == CurseType.LETTER and end.curse == CurseType.LETTER:
        if path_letter_for_count(start) != path_letter_for_count(end):
            return False
        return _wrestlers_letter_endpoints_qualify(board, path, start, end)
    return True


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


def _chess_take_search_flags(
    loadout: Loadout | None,
    *,
    allies_can_take: bool = False,
) -> StampSearchFlags:
    if loadout is None:
        return StampSearchFlags(chess_allies_can_take=allies_can_take)
    flags = stamp_search_flags(loadout)
    if allies_can_take:
        return StampSearchFlags(
            horizontal_wrap=flags.horizontal_wrap,
            chess_allies_can_take=True,
            chess_king_queen_item_movement=flags.chess_king_queen_item_movement,
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
) -> bool:
    """Whether path[pos] counts as a chess capture landing square."""
    tile = board.get_by_index(path[pos])
    if _has_take_metadata(tile) and is_chess_piece(tile):
        if pos > 0 or strict:
            return True
    if strict or pos == 0:
        return False
    prefix = path[:pos]
    flags = _chess_take_search_flags(loadout, allies_can_take=allies_can_take)
    return is_chess_capture_step(
        board,
        path[pos - 1],
        path[pos],
        allies_can_take=allies_can_take,
        path_prefix=prefix,
        visited=set(prefix),
        flags=flags,
    )


def chess_take_path_positions(
    board: Board,
    path: list[int],
    *,
    strict: bool = False,
    loadout: Loadout | None = None,
) -> list[int]:
    """Indices into path for tiles that count as takes."""
    return [
        i
        for i in range(len(path))
        if is_take_at_path_position(
            board, path, i, strict=strict, loadout=loadout
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
    if tile.curse == CurseType.ITEM:
        return False
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


def infer_lucky_dice_target_number(
    board: Board,
    path: list[int],
    *,
    expected_bonus: int = 50,
    observed_bonus: int | None = None,
) -> int | None:
    """Infer Lucky Dice grid target when melmod omitted extras.target_number.

    Conservative: only returns a value when the path (or path∩board uniqueness)
    unambiguously identifies one number tile face value.
    """
    if observed_bonus is not None and observed_bonus != expected_bonus:
        return None

    path_values: list[int] = []
    for idx in path:
        tile = board.get_by_index(idx)
        if is_number_like_tile(tile):
            path_values.append(int(tile_numeric_value(tile)))
    if not path_values:
        return None

    unique_on_path = sorted(set(path_values))
    if len(unique_on_path) == 1:
        return unique_on_path[0]

    board_counts: Counter[int] = Counter()
    for tile in board.flat:
        if is_number_like_tile(tile):
            board_counts[int(tile_numeric_value(tile))] += 1

    singletons = [value for value in unique_on_path if board_counts.get(value, 0) == 1]
    if len(singletons) == 1:
        return singletons[0]

    return None


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


def unique_colours_for_neapolitan_improve(board: Board, path: list[int]) -> set[str]:
    """Distinct tile colours that count toward Neapolitan +5% improve on submit."""
    colours: set[str] = set()
    for idx in path:
        color = board.get_by_index(idx).color
        if color not in NON_COLOUR_FOR_NEAPOLITAN:
            colours.add(color.value)
    return colours


def count_color_on_path(board: Board, path: list[int], color: str) -> int:
    try:
        want = TileColor(color)
    except ValueError:
        want = TileColor.UNKNOWN
    return sum(
        1 for idx in path if tile_counts_as_color(board.get_by_index(idx), want)
    )


def path_indices_set(path: list[int]) -> set[int]:
    return set(path)


def void_tile_face_for_dusty_coffin(tile: Tile) -> str:
    """Face character on a VOID tile for Dusty Coffin (letter or number digit)."""
    if tile.curse == CurseType.CURRENCY:
        return (tile.letter or tile.char or "").strip()
    if tile.curse == CurseType.NUMBER:
        if tile.number_value is not None:
            return str(tile.number_value)
        raw = (tile.letter or tile.char or "").strip()
        if raw.isdigit():
            return raw
        return ""
    if tile.curse != CurseType.LETTER:
        return ""
    return path_letter_for_count(tile)


def void_letter_tile_count(board: Board) -> int:
    """Active VOID letter tiles on the board."""
    return sum(
        1
        for tile in board.flat
        if tile.color == TileColor.VOID and tile.curse == CurseType.LETTER
    )


def snapshot_dusty_void_units(board: Board) -> int:
    """VOID letters plus VOID items with a face (Snapshot copy of Dusty Coffin)."""
    count = void_letter_tile_count(board)
    for tile in board.flat:
        if tile.color != TileColor.VOID or tile.curse != CurseType.ITEM:
            continue
        if void_tile_face_for_dusty_coffin(tile):
            count += 1
    return count


def dusty_coffin_scattered_on_path(board: Board, path: list[int]) -> bool:
    """True when a scattered Dusty Coffin sticker tile is on the word path."""
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse != CurseType.ITEM:
            continue
        slug = str((tile.metadata or {}).get("scattered_item_id", "")).strip().lower()
        if slug == "dusty_coffin":
            return True
    return False


def dusty_coffin_void_units(
    board: Board,
    word: str,
    loadout: Loadout | None,
    *,
    applying_sticker_id: str = "",
    path: list[int] | None = None,
) -> int:
    """Void units for Dusty Coffin / Snapshot copy (per_void_unused × level factor)."""
    applying = (applying_sticker_id or "").strip().lower()
    if loadout is not None:
        extras = loadout.extras or {}
        if applying == "dusty_coffin":
            raw = extras.get("dusty_void_units_override")
            if raw not in (None, ""):
                try:
                    return max(0, int(raw))
                except (TypeError, ValueError):
                    pass
        if applying == "snapshot":
            raw = extras.get("snapshot_void_units_override")
            if raw not in (None, ""):
                try:
                    return max(0, int(raw))
                except (TypeError, ValueError):
                    pass
    count = void_tiles_letter_not_in_word(board, word, path=path)
    copy_is_dusty = (
        loadout is not None
        and snapshot_copy_slug(loadout) == "dusty_coffin"
    )
    if path is not None and dusty_coffin_scattered_on_path(board, path):
        if applying == "dusty_coffin" or (applying == "snapshot" and copy_is_dusty):
            letters_in_word = set((word or "").lower())
            for idx in path:
                tile = board.get_by_index(idx)
                slug = str((tile.metadata or {}).get("scattered_item_id") or "").strip().lower()
                if slug == "dusty_coffin":
                    face = path_letter_for_count(tile)
                    if face and face.lower() not in letters_in_word:
                        count += 1
                    continue
                if tile.color != TileColor.VOID or tile.curse != CurseType.LETTER:
                    continue
                face = path_letter_for_count(tile)
                if face and face.lower() in letters_in_word:
                    count += 1
    return count


def void_tiles_letter_not_in_word(
    board: Board, word: str, *, path: list[int] | None = None
) -> int:
    """VOID tiles on the grid whose face is not in the submitted word (Dusty Coffin).

    When ``path`` is provided, void tiles on the word path are excluded (game
    treats path voids separately via dusty_coffin_void_units additive logic).
    """
    letters_in_word = set((word or "").lower())
    on_path = path_indices_set(path) if path else None
    count = 0
    for tile in board.flat:
        if tile.color != TileColor.VOID:
            continue
        if on_path is not None and tile.index in on_path:
            continue
        if tile.curse == CurseType.ITEM:
            scattered = str((tile.metadata or {}).get("scattered_item_id", "")).strip().lower()
            if scattered == "rainbow_sprinkles":
                count += 1
                continue
            face = path_letter_for_count(tile)
            if face and face.lower() not in letters_in_word:
                count += 1
            continue
        face = void_tile_face_for_dusty_coffin(tile)
        if not face:
            continue
        if (
            tile.curse == CurseType.CURRENCY
            and (face.lower() == "b" or face == "฿")
            and "b" in letters_in_word
        ):
            continue
        if tile.curse != CurseType.CURRENCY and face.lower() in letters_in_word:
            continue
        count += 1
    return count


def unused_red_tiles_on_board(board: Board, path: list[int]) -> int:
    used = path_indices_set(path)
    return sum(
        1
        for tile in board.flat
        if tile_counts_as_color(tile, TileColor.RED) and tile.index not in used
    )


def unique_vowels_in_word(word: str) -> int:
    return len({c for c in word.lower() if c in VOWELS})


def unique_vowels_on_path(board: Board, path: list[int]) -> int:
    """Unique vowels on letter tiles along the path (Pneumonia; skips currency/numbers)."""
    seen: set[str] = set()
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse in (CurseType.CURRENCY, CurseType.NUMBER):
            continue
        ch = path_letter_for_count(tile)
        if ch in VOWELS:
            seen.add(ch)
    return len(seen)


def has_double_letter(word: str) -> bool:
    w = word.lower()
    for i in range(len(w) - 1):
        if w[i] == w[i + 1] and w[i].isalpha():
            return True
    return False


def normalize_scoring_path(path: list[int]) -> list[int]:
    """Drop consecutive duplicate indices (game scores one step per letter)."""
    if not path:
        return []
    out = [path[0]]
    for idx in path[1:]:
        if idx != out[-1]:
            out.append(idx)
    return out


def path_letter_for_double_letter(tile: Tile) -> str:
    """Letter for Yellow Glasses path doubles; uses submit char when letter is unresolved."""
    if tile.curse == CurseType.CURRENCY:
        return ""
    ch = path_letter_for_count(tile)
    if ch:
        return ch
    raw = (tile.char or "").strip().lower()
    if len(raw) == 1 and raw.isalpha():
        return raw
    return ""


def _double_letter_char_at_path_step(
    board: Board, idx: int, step: int, word: str
) -> tuple[str, str] | None:
    """Resolved letter and source ('currency'|'letter') for Yellow Glasses doubles."""
    tile = board.get_by_index(idx)
    w = word.lower()
    if tile.curse == CurseType.ITEM:
        return None
    if tile.curse == CurseType.CURRENCY:
        if w and step < len(w):
            cand = w[step]
            if cand.isalpha():
                return cand, "currency"
        return None
    ch = path_letter_for_double_letter(tile)
    if ch:
        return ch, "letter"
    return None


def has_consecutive_double_letter_on_path(
    board: Board, path: list[int], word: str = ""
) -> bool:
    """Yellow Glasses: consecutive path tiles with the same letter (game behavior).

    Currency tiles use the submitted word character at that path step; letter tiles
    use their path letter. Scattered sticker (ITEM) path tiles are ignored.
    A double counts only when both consecutive steps resolve to the same letter
    **and** the same source (both currency or both letter).
    """
    w = word.lower()
    steps = normalize_scoring_path(path) if w else path
    prev: tuple[str, str] | None = None
    for i, idx in enumerate(steps):
        resolved = _double_letter_char_at_path_step(board, idx, i, w)
        if resolved is None:
            prev = None
            continue
        ch, source = resolved
        if prev is not None and ch == prev[0] and source == prev[1]:
            return True
        prev = (ch, source)
    return False


def tile_on_consecutive_double_letter_path(
    board: Board, path: list[int], path_index: int
) -> bool:
    """True when this path tile's letter matches an adjacent path tile's letter."""
    tile = board.get_by_index(path[path_index])
    ch = path_letter_for_double_letter(tile)
    if not ch:
        return False
    if path_index > 0:
        prev = path_letter_for_double_letter(board.get_by_index(path[path_index - 1]))
        if prev and prev == ch:
            return True
    if path_index + 1 < len(path):
        nxt = path_letter_for_double_letter(board.get_by_index(path[path_index + 1]))
        if nxt and nxt == ch:
            return True
    return False


def consecutive_letter_run_length_at(
    board: Board, path: list[int], path_index: int
) -> int:
    """Length of the consecutive same-letter run on the path containing path_index."""
    ch = path_letter_for_double_letter(board.get_by_index(path[path_index]))
    if not ch:
        return 0
    start = path_index
    while start > 0:
        prev = path_letter_for_double_letter(board.get_by_index(path[start - 1]))
        if not prev or prev != ch:
            break
        start -= 1
    end = path_index
    while end + 1 < len(path):
        nxt = path_letter_for_double_letter(board.get_by_index(path[end + 1]))
        if not nxt or nxt != ch:
            break
        end += 1
    return end - start + 1


def word_same_start_end_letter(word: str) -> bool:
    w = word.lower()
    if len(w) < 2:
        return False
    return w[0] == w[-1] and w[0].isalpha()


def consumable_rack_count(loadout: Loadout) -> int:
    count = _extra_int(loadout, "consumable_rack_count", -1)
    if count >= 0:
        return count
    from cursed_words_solver.consumable_placement import consumable_rack_tiles

    return len(consumable_rack_tiles(loadout))


def rare_item_count(loadout: Loadout) -> int:
    """Prefer live F8 export; fall back to last-known submit capture."""
    live = _extra_int(loadout, "rare_item_count", -1)
    if live >= 0:
        return live
    cached = _extra_int(loadout, "rare_item_count_last_known", -1)
    if cached >= 0:
        return cached
    return 0


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


def money_for_scoring(
    board: Board,
    path: list[int],
    loadout: Loadout,
    *,
    state: dict | None = None,
) -> int:
    """Bank for per-$ rules plus currency earned this word (tile_init money_bonus)."""
    base = max(board.money, loadout.money, 0)
    if state is not None:
        base += int(state.get("money_bonus", 0))
    return base


def path_all_non_adjacent(path: list[int]) -> bool:
    if len(path) <= 1:
        return True
    return non_adjacent_step_count(path) == len(path) - 1


def longest_red_run_on_path(board: Board, path: list[int]) -> int:
    best = cur = 0
    for idx in path:
        if tile_counts_as_color(board.get_by_index(idx), TileColor.RED):
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


def encounter_red_tiles_before_current_word(loadout: Loadout | None) -> int:
    """RED tiles from prior submitted words this encounter (Telescope historic list)."""
    total = 0
    for row in parse_historic_words(loadout):
        try:
            total += max(0, int(row.get("red_tile_count", 0)))
        except (TypeError, ValueError):
            continue
    if total:
        return total
    return max(0, red_tiles_used_encounter(loadout))


def telescope_running_red_count(
    loadout: Loadout | None,
    board: Board,
    path: list[int],
    path_index: int,
) -> int:
    """Running RED count for Telescope at path index (game: historic reds + path prefix).

    When a red tile on the path is not immediately preceded by another red tile,
    the game adds +1 to the running count (gap-separated reds on the word path).
    """
    prior = encounter_red_tiles_before_current_word(loadout)
    prefix_reds = sum(
        1
        for j in range(path_index + 1)
        if board.get_by_index(path[j]).color == TileColor.RED
    )
    reds_before = sum(
        1
        for j in range(path_index)
        if board.get_by_index(path[j]).color == TileColor.RED
    )
    has_gap = (
        reds_before > 0
        and board.get_by_index(path[path_index - 1]).color != TileColor.RED
    )
    return prior + prefix_reds + (1 if has_gap else 0)


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


def movie_camera_encounter_word_bonus(
    board: Board,
    path: list[int],
    level: int,
    loadout: Loadout | None,
    *,
    strict: bool = False,
) -> int:
    """Word bonus for this Movie Camera application (matches in-game WordScoreBonus)."""
    improve = movie_camera_improve_for_path(
        board, path, level, strict=strict, loadout=loadout
    )
    accumulated = movie_camera_accumulated(loadout)
    prior = movie_camera_prior_from_historic(loadout)
    if improve > 0 and prior + improve == accumulated:
        return accumulated
    return accumulated + improve


def subtotal_before_mult(state: dict) -> float:
    """Tile total + word score before word multipliers (Jigsaw Piece timing)."""
    return sum(state["tile_scores"]) + state["word_score"]


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


def _void_tiles_within_void_hops(
    board: Board,
    tile: Tile,
    *,
    max_hops: int,
    exclude_indices: set[int],
) -> int:
    """VOID tiles reachable in <= max_hops steps through 8-dir VOID-only moves."""
    start = tile.index
    exclude = set(exclude_indices)
    exclude.add(start)
    visited = {start}
    frontier = {start}
    counted: set[int] = set()
    for _ in range(max_hops):
        next_frontier: set[int] = set()
        for idx in frontier:
            row, col = divmod(idx, 5)
            for dr, dc in _VOID_NEIGHBOR_DELTAS:
                neighbor = board.get(row + dr, col + dc)
                if neighbor is None or neighbor.color != TileColor.VOID:
                    continue
                nidx = neighbor.index
                if nidx in visited:
                    continue
                visited.add(nidx)
                next_frontier.add(nidx)
                if nidx not in exclude:
                    counted.add(nidx)
        frontier = next_frontier
        if not frontier:
            break
    return len(counted)


def _orthogonal_void_neighbor_count(board: Board, tile: Tile) -> int:
    """VOID neighbours sharing an edge (not diagonal-only)."""
    count = 0
    for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        neighbor = board.get(tile.row + dr, tile.col + dc)
        if neighbor is not None and neighbor.color == TileColor.VOID:
            count += 1
    return count


def _earlier_void_on_path(board: Board, path: list[int], path_index: int) -> bool:
    return any(
        board.get_by_index(idx).color == TileColor.VOID for idx in path[:path_index]
    )


def adjacent_void_count(
    board: Board,
    tile: Tile,
    *,
    loadout: Loadout | None = None,
    path: list[int] | None = None,
    path_index: int | None = None,
) -> int:
    """VOID tiles that grant Tombstone +TILE SCORE for this path tile."""
    horizontal_wrap = False
    if loadout is not None:
        from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags

        horizontal_wrap = stamp_search_flags(loadout).horizontal_wrap
    count = 0
    scattered = str((tile.metadata or {}).get("scattered_item_id") or "").strip().lower()
    if path is not None and len(path) == 1:
        if tile.color == TileColor.VOID or scattered == "tombstone":
            count += 1
    cols = getattr(board, "cols", 5) or 5
    for dr, dc in _VOID_NEIGHBOR_DELTAS:
        nr = tile.row + dr
        nc = tile.col + dc
        if horizontal_wrap:
            nc = nc % int(cols)
        neighbor = board.get(nr, nc)
        if neighbor is not None and neighbor.color == TileColor.VOID:
            count += 1
    return count


def word_starts_ends_different_color(board: Board, path: list[int]) -> bool:
    if len(path) < 2:
        return False
    start_tile = board.get_by_index(path[0])
    end_tile = board.get_by_index(path[-1])
    if start_tile.curse == CurseType.ITEM or end_tile.curse == CurseType.ITEM:
        return False
    start = start_tile.color
    end = end_tile.color
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
        tile = board.get_by_index(idx)
        if tile_counts_as_color(tile, TileColor.BLUE):
            has_blue = True
        if tile_counts_as_color(tile, TileColor.RED):
            has_red = True
        if tile.color == TileColor.COLORLESS:
            has_colourless = True
    return has_blue and has_red and has_colourless


def unique_colour_count_on_path(board: Board, path: list[int]) -> int:
    return len(unique_colours_on_path(board, path))


_ODEN_CURSE_CATEGORIES: dict[CurseType, str] = {
    CurseType.WILDCARD: "wildcard",
    CurseType.BLANK: "wildcard",
    CurseType.ITEM: "item",
    CurseType.CARD: "card",
    CurseType.CURRENCY: "currency",
    CurseType.NUMBER: "number",
    CurseType.FRACTION: "number",
    CurseType.CHESS_PAWN: "chess",
    CurseType.CHESS_BISHOP: "chess",
    CurseType.CHESS_ROOK: "chess",
    CurseType.CHESS_KNIGHT: "chess",
    CurseType.CHESS_QUEEN: "chess",
    CurseType.CHESS_KING: "chess",
}


def _oden_category_for_tile(tile: Tile) -> str | None:
    """Single Oden bucket for a tile (wiki: joker wilds are Cards, other ? are Wild Tiles)."""
    if tile.curse in (CurseType.WILDCARD, CurseType.BLANK):
        if is_joker_tile(tile) or card_suit(tile) == "joker":
            return "card"
        return "wildcard"
    return _ODEN_CURSE_CATEGORIES.get(tile.curse)


def unique_curse_type_count_on_path(board: Board, path: list[int]) -> int:
    """Distinct Oden curse categories on the path (wiki buckets, not per-piece chess)."""
    categories: set[str] = set()
    for idx in path:
        category = _oden_category_for_tile(board.get_by_index(idx))
        if category:
            categories.add(category)
    return len(categories)


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
        if _extra_bool(loadout, "is_first_grid_of_encounter"):
            return False, "skipped: no previous word on first grid"
        if grid_number(loadout) == 1:
            return False, "skipped: no previous word on first grid"
        prev = _extra_letter(loadout, "previous_word_first_letter")
        first = _effective_word_start_letter(board, path, word)
        if not prev or not first:
            return False, f"skipped: missing previous or word first letter (prev={prev!r}, word={first!r})"
        if first != prev:
            return False, f"skipped: word starts '{first}', previous '{prev}'"
        return True, f"applied: word starts '{first}' same as previous"

    if condition == "word_starts_after_previous":
        if not _limnophila_previous_word_available(loadout):
            return False, "skipped: no previous word on this grid"
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
        return tile_counts_as_color(board.get_by_index(path[-1]), TileColor.BLUE)
    if condition == "red_count_gte:3":
        return count_color_on_path(board, path, "red") >= 3
    if condition == "word_starts_vowel":
        first = word_first_letter(word)
        return bool(first) and is_vowel_letter(first)
    if condition == "word_starts_ends_red":
        if not path:
            return False
        return (
            tile_counts_as_color(board.get_by_index(path[0]), TileColor.RED)
            and tile_counts_as_color(board.get_by_index(path[-1]), TileColor.RED)
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
        if _extra_bool(loadout, "is_first_grid_of_encounter"):
            return False
        if grid_number(loadout) == 1:
            return False
        prev = _extra_letter(loadout, "previous_word_first_letter")
        first = _effective_word_start_letter(board, path, word)
        if not prev or not first:
            return False
        return first == prev
    if condition == "word_starts_after_previous":
        if not _limnophila_previous_word_available(loadout):
            return False
        prev = _extra_letter(loadout, "previous_word_first_letter")
        first = _effective_word_start_letter(board, path, word)
        if not prev or not first:
            return False
        return first > prev
    if condition == "has_double_letter":
        return has_consecutive_double_letter_on_path(board, path, word)
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
        return chess_takes_on_path(board, path, loadout=loadout) >= min_n
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
    if condition == "cursed_word":
        return cursed_word_played(board, path, word)
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
        return unique_curse_type_count_on_path(board, path) >= n
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
        return tile_counts_as_color(tile, TileColor.RED)
    if target == "blue":
        return tile_counts_as_color(tile, TileColor.BLUE)
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


def super_8_uses_melmod_take_metadata(board: Board, path: list[int]) -> bool:
    """Super 8 pin: post-submit ``take`` flags replace inferred capture count.

    Partial exports (one flagged tile during animation) still infer; a small
    set of melmod takes below the inference count signals a submit snapshot.
    """
    if not path_has_melmod_take_metadata(board, path):
        return False
    strict_count = chess_takes_on_path(board, path, strict=True)
    inferred_count = chess_takes_on_path(board, path, strict=False)
    if strict_count < 2:
        return False
    return strict_count < inferred_count


def chess_takes_on_path(
    board: Board,
    path: list[int],
    *,
    strict: bool = False,
    loadout: Loadout | None = None,
) -> int:
    return len(
        chess_take_path_positions(board, path, strict=strict, loadout=loadout)
    )


def abacus_colored_number_bonus(loadout: Loadout, rule: dict) -> int:
    """+N TILE SCORE per coloured number; N = right UpgradeableComponent.VariableValue."""
    var = pin_right_variable(loadout)
    if var is not None:
        return var
    base = int(rule.get("value", 10))
    per_upgrade = int(rule.get("value_per_right_upgrade", 10))
    right = pin_right_level(loadout)
    return base + per_upgrade * max(0, right - 1)


def rainbow_per_colour_bonus(loadout: Loadout, rule: dict) -> int:
    var = pin_right_variable(loadout)
    if var is not None:
        return var
    base = int(rule.get("value", 5))
    per_upgrade = int(rule.get("value_per_right_upgrade", 5))
    return scaled_pin_value(base, per_upgrade, pin_right_level(loadout))


def mahjong_consumable_factor(loadout: Loadout, rule: dict) -> float:
    var = pin_right_variable(loadout)
    if var is not None:
        return float(var)
    base = float(rule.get("factor_base", 2.0))
    per_right = float(rule.get("factor_per_pin_right", 1.0))
    return base + per_right * pin_right_level(loadout)


def super_8_take_word_bonus(loadout: Loadout, rule: dict) -> int:
    """Per take: UpgradeableComponents[1].VariableValue (melmod pin_right_variable)."""
    var = pin_right_variable(loadout)
    if var is not None:
        return var
    base = int(rule.get("value", 8))
    right_upgrades = max(0, pin_right_level(loadout) - 1)
    if right_upgrades % 2 == 0:
        return base
    return base * ((right_upgrades + 1) // 2 + 1)


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


def bicycle_word_score_accumulator_for_submit(
    loadout: Loadout, board: Board, path: list[int], rule: dict
) -> int:
    """Pre-word accumulator; rewinds when extras hold post-submit applied bonus."""
    acc = bicycle_word_score_accumulator(loadout)
    per_card = bicycle_word_per_card(loadout, rule)
    if per_card <= 0:
        return acc
    pin_acc = bicycle_pin_accumulator_from_fingerprint(
        str((loadout.extras or {}).get("loadout_fingerprint", "") or "")
    )
    if pin_acc is not None and acc == pin_acc:
        return acc
    suited_extra = bicycle_suited_on_path_from_extras(loadout)
    if pin_acc is not None and suited_extra > 0:
        post_pattern = pin_acc + per_card * suited_extra
        if acc == post_pattern:
            suited_board = bicycle_suited_credit_on_path(board, path)
            if (
                acc > pin_acc
                and suited_board > 0
                and pin_acc + per_card * suited_board
                < acc + per_card * suited_board
            ):
                # Stale pin fingerprint: live pre-word acc equals pin + export lag.
                return acc
            return pin_acc
        double_pattern = pin_acc + 2 * per_card * suited_extra
        if acc == double_pattern and acc > post_pattern:
            # Stale fingerprint (F8 lag): acc is live pre-word, not post-submit.
            return acc
        if acc > post_pattern:
            pre = acc - per_card * suited_extra
            if 0 <= pre <= acc:
                return pre
    suited_board = bicycle_suited_credit_on_path(board, path)
    if suited_extra > 0 and suited_board != suited_extra:
        pre = acc - per_card * suited_extra
        if 0 <= pre < acc:
            return pre
    return acc


def last_path_index_per_card_rank(board: Board, path: list[int]) -> dict[str, int]:
    """For each suited card rank on path, the last path position with that rank."""
    last: dict[str, int] = {}
    for i, idx in enumerate(path):
        tile = board.get_by_index(idx)
        if not card_suit(tile):
            continue
        rank = card_rank(tile)
        if not rank:
            continue
        last[rank.upper()] = i
    return last


def unique_suited_card_ranks_on_path_count(board: Board, path: list[int]) -> int:
    """Unique suited card ranks on the word path (duplicate ranks count once)."""
    return len(last_path_index_per_card_rank(board, path))


def unique_suited_suits_on_path_count(board: Board, path: list[int]) -> int:
    """Distinct playing-card suits on the word path (e.g. Las Vegas)."""
    suits: set[str] = set()
    for idx in path:
        suit = card_suit(board.get_by_index(idx))
        if suit and suit not in ("none",):
            suits.add(suit)
    return len(suits)


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


def suited_tiles_on_path_count(board: Board, path: list[int]) -> int:
    """Path tiles with ``CardSuit != 0`` (Bicycle.ApplyWordBonus per-tile credit)."""
    return sum(
        1 for idx in path if _bicycle_suited_path_tile(board.get_by_index(idx))
    )


def is_last_card_rank_on_path(board: Board, path: list[int], path_index: int) -> bool:
    """True when path_index is the last occurrence of its card rank on the path."""
    tile = board.get_by_index(path[path_index])
    if not card_suit(tile):
        return False
    rank = card_rank(tile)
    if not rank:
        return False
    last = last_path_index_per_card_rank(board, path)
    return last.get(rank.upper()) == path_index


def is_last_suited_letter_on_path(
    board: Board, path: list[int], path_index: int
) -> bool:
    """True when path_index is the last suited tile with this letter on the path."""
    tile = board.get_by_index(path[path_index])
    if not card_suit(tile):
        return False
    letter = (tile.letter or "").strip().lower()[:1]
    if not letter:
        return False
    last: int | None = None
    for i, idx in enumerate(path):
        other = board.get_by_index(idx)
        if not card_suit(other):
            continue
        if (other.letter or "").strip().lower()[:1] == letter:
            last = i
    return last == path_index


def _letter_occurrences_on_path(board: Board, path: list[int], letter: str) -> int:
    ch = (letter or "").strip().lower()[:1]
    if not ch:
        return 0
    return sum(
        1
        for idx in path
        if (board.get_by_index(idx).letter or "").strip().lower()[:1] == ch
    )


def _first_path_index_for_letter(
    board: Board, path: list[int], letter: str
) -> int | None:
    ch = (letter or "").strip().lower()[:1]
    if not ch:
        return None
    for i, idx in enumerate(path):
        if path_letter_for_count(board.get_by_index(idx)) == ch:
            return i
    return None


def _is_last_suited_letter_for_suit_on_path(
    board: Board, path: list[int], path_index: int
) -> bool:
    """True when path_index is the last suited tile with this letter and suit."""
    tile = board.get_by_index(path[path_index])
    suit = card_suit(tile)
    if not suit:
        return False
    letter = path_letter_for_count(tile)
    if not letter:
        return False
    last: int | None = None
    for i, idx in enumerate(path):
        other = board.get_by_index(idx)
        if card_suit(other) != suit:
            continue
        if path_letter_for_count(other) == letter:
            last = i
    return last == path_index


def celestial_body_tile_eligible(
    board: Board,
    path: list[int],
    path_index: int,
    level: int = 1,
    *,
    loadout: Loadout | None = None,
) -> bool:
    """+tile for cards: poker ranks, value-3 tiles, path duplicate letters; L2+ value-2."""
    tile = board.get_by_index(path[path_index])
    letter = (tile.letter or "").strip().lower()[:1]
    letter_count = _letter_occurrences_on_path(board, path, letter)
    if level >= 3 and card_suit(tile) and tile.base_score < 2:
        if letter_count >= 2:
            first = _first_path_index_for_letter(board, path, letter)
            if (
                first is not None
                and path_index == first
            ):
                return True
            if _is_last_suited_letter_for_suit_on_path(
                board, path, path_index
            ):
                return True
            return False
        if letter_count == 1:
            rank = card_rank(tile)
            if (
                rank
                and rank.upper() == "I"
                and is_last_card_rank_on_path(board, path, path_index)
            ):
                return True
            if (
                path_index == len(path) - 1
                and is_last_suited_letter_on_path(board, path, path_index)
            ):
                return True
            return False
        return False
    if not tile_matches_target(tile, "card"):
        return False
    if not card_suit(tile):
        return False
    rank = card_rank(tile)
    path_end = len(path) - 1
    boss_id = (loadout.boss_id or "").strip().lower() if loadout else ""
    salamander = boss_id == "salamander" or "bosslesspoints" in boss_id

    if rank and rank.upper() in POKER_RANKS:
        return is_last_card_rank_on_path(board, path, path_index)

    if tile.base_score == 3:
        if salamander and path_index == 0:
            return False
        return is_last_card_rank_on_path(board, path, path_index)
    if (
        salamander
        and level >= 2
        and has_consecutive_double_letter_on_path(board, path)
        and tile.base_score == 2
        and path_index not in (0, path_end)
    ):
        return is_last_card_rank_on_path(board, path, path_index)
    if (
        salamander
        and level >= 2
        and has_consecutive_double_letter_on_path(board, path)
        and tile.base_score >= 8
        and letter_count >= 2
    ):
        return True
    if (
        salamander
        and level >= 2
        and has_consecutive_double_letter_on_path(board, path)
        and letter_count == 1
        and rank
        and rank.upper() == "I"
    ):
        return False
    if (
        salamander
        and level >= 2
        and has_consecutive_double_letter_on_path(board, path)
        and tile.base_score < 2
        and tile_on_consecutive_double_letter_path(board, path, path_index)
    ):
        suited_same_letter = sum(
            1
            for idx in path
            if card_suit(board.get_by_index(idx))
            and path_letter_for_count(board.get_by_index(idx)) == letter
        )
        if suited_same_letter < 2:
            return True
        if consecutive_letter_run_length_at(board, path, path_index) >= 3:
            return True
    if tile.base_score >= 10:
        return is_last_suited_letter_on_path(board, path, path_index)
    if tile.base_score == 4 and (
        path_index == 0 or path_index == path_end
    ):
        return True
    if letter_count >= 2:
        if tile.base_score < 2:
            if (
                salamander
                and consecutive_letter_run_length_at(board, path, path_index)
                < 3
            ):
                return False
            return True
        if tile.base_score == 2:
            return is_last_suited_letter_on_path(board, path, path_index)
    if tile.base_score == 2 and level >= 2:
        if letter_count >= 2:
            return is_last_suited_letter_on_path(board, path, path_index)
        if path_index in (0, path_end):
            return False
        return is_last_card_rank_on_path(board, path, path_index)
    if (
        level < 2
        and has_consecutive_double_letter_on_path(board, path)
        and tile.base_score not in (2, 4)
    ):
        return True
    if (
        salamander
        and letter_count == 1
        and not (rank and rank.upper() == "I")
    ):
        return is_last_card_rank_on_path(board, path, path_index)
    return False


def suited_tiles_on_path_count(board: Board, path: list[int]) -> int:
    """Suited playing-card tiles on the path (Bicycle: ``CardSuit != 0`` tiles).

    Note: keep parity with `_bicycle_suited_path_tile`, including joker-glyph tiles
    that may be missing `card_suit` in melmod exports.
    """
    return sum(
        1 for idx in path if _bicycle_suited_path_tile(board.get_by_index(idx))
    )


def suited_cards_on_path_count(board: Board, path: list[int]) -> int:
    """Bicycle suited credit on path (single-suit paths credit 1, else unique ranks)."""
    return bicycle_suited_credit_on_path(board, path)


def bicycle_suited_on_path_from_extras(loadout: Loadout) -> int:
    """Melmod scoring-time count when board export lacks card_suit metadata."""
    try:
        return max(0, int((loadout.extras or {}).get("bicycle_suited_on_path", 0)))
    except (TypeError, ValueError):
        return 0


def bicycle_suited_credit_on_path(board: Board, path: list[int]) -> int:
    """Bicycle suited credit: mono-suit → 1; multi-suit + non-end joker → per-tile; else unique ranks."""
    if not path:
        return 0
    path_end = path[-1]
    suits: set[str] = set()
    joker_not_at_end = False
    suited_tile_count = 0
    non_joker_suited = 0
    for idx in path:
        tile = board.get_by_index(idx)
        is_joker = _bicycle_joker_path_tile(tile)
        if not is_joker and not _bicycle_suited_path_tile(tile):
            continue
        if is_joker and idx != path_end:
            joker_not_at_end = True
        if is_joker and idx == path_end:
            continue
        suited_tile_count += 1
        if not is_joker:
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
    return unique_suited_card_ranks_on_path_count(board, path)


def effective_suited_cards_on_path(
    board: Board, path: list[int], loadout: Loadout
) -> int:
    """Suited tiles credit for Bicycle (board when metadata present, else melmod extra)."""
    board_credit = bicycle_suited_credit_on_path(board, path)
    from_extras = bicycle_suited_on_path_from_extras(loadout)
    if board_credit > 0:
        return board_credit
    return from_extras


def bicycle_suited_tiles_on_path(board: Board, path: list[int], loadout: Loadout) -> int:
    """Deprecated alias; use effective_suited_cards_on_path for Bicycle."""
    return effective_suited_cards_on_path(board, path, loadout)


def bicycle_word_bonus(
    board: Board, path: list[int], loadout: Loadout, rule: dict
) -> int:
    """Total +WORD from Bicycle this submit (accumulator + suited credit on path × rate)."""
    per_card = bicycle_word_per_card(loadout, rule)
    if per_card <= 0:
        return bicycle_word_score_accumulator_for_submit(loadout, board, path, rule)
    suited = effective_suited_cards_on_path(board, path, loadout)
    acc = bicycle_word_score_accumulator_for_submit(loadout, board, path, rule)
    return acc + per_card * suited


def birthday_cake_improve_for_path(
    board: Board, path: list[int], level: int, rule: dict
) -> int:
    """Improve term added to birthday_cake_bonus after this submit."""
    import math

    high = highest_number_on_path(board, path)
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
) -> None:
    """Subtract this word's improve from extras when snapshot is post-submit."""
    improve = birthday_cake_improve_for_path(board, path, level, rule)
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

    from cursed_words_solver.rules.stamp_behaviors import loadout_has_stamp

    if loadout_has_stamp(loadout, "neapolitan"):
        extras = dict(loadout.extras or {})
        live_neapolitan = _extra_int(loadout, "neapolitan_percent", -1)
        if live_neapolitan > 0 and extras.get("neapolitan_percent_last_known") != str(
            live_neapolitan
        ):
            extras["neapolitan_percent_last_known"] = str(live_neapolitan)
            loadout.extras = extras
            notes.append(f"neapolitan baseline cached at {live_neapolitan}%")

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


def cards_submitted_count(loadout: Loadout) -> int:
    """Deprecated alias; use bicycle_word_score_accumulator."""
    return bicycle_word_score_accumulator(loadout)


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


def _is_neapolitan_rule(rule: dict) -> bool:
    slug = str(rule.get("id") or rule.get("slug") or "").strip().lower()
    name = str(rule.get("name") or "").strip().lower()
    game_class = str(rule.get("game_class") or "").strip().lower()
    return slug == "neapolitan" or name == "neapolitan" or game_class == "neapolitan"


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


def neapolitan_grid_cap_percent(loadout: Loadout | None) -> int:
    """Per-grid ceiling for Neapolitan percent (165 + 5×grid)."""
    if loadout is None:
        return 170
    return 165 + 5 * max(1, grid_number(loadout))


def neapolitan_base_percent_from_loadout(loadout: Loadout | None) -> tuple[int, str]:
    """Resolve baseline Neapolitan percent and source.

    Neapolitan only increases within a run. Prefer melmod ``neapolitan_percent``
    (live) when exported — the game applies that value this submit. Only fall
    back to higher ``neapolitan_percent_last_known`` when live is a stale ×1.00
    (100) reflection that under-reports the run baseline (e.g. 110).
    """
    extras = (
        loadout.extras
        if loadout is not None and isinstance(loadout.extras, dict)
        else {}
    )
    live_percent = _extra_positive_int(extras, "neapolitan_percent")
    cached_percent = _extra_positive_int(extras, "neapolitan_percent_last_known")
    if live_percent is not None:
        if (
            cached_percent is not None
            and live_percent <= 100
            and cached_percent > live_percent
        ):
            result: tuple[int, str] = (cached_percent, "cached")
        elif (
            cached_percent is not None
            and live_percent > cached_percent
            and cached_percent >= 145
        ):
            result = (cached_percent, "cached")
        else:
            result = (live_percent, "live")
    elif cached_percent is not None:
        result = (cached_percent, "cached")
    else:
        result = (100, "default")
    return result


def _neapolitan_multiplier_from_extras(
    loadout: Loadout | None,
    rule: dict,
    *,
    improve_on_submit: bool = False,
    board: Board | None = None,
    path: list[int] | None = None,
) -> float | None:
    """Neapolitan is a live, multiplicative WordBonus percent exported by melmod.

    When present in `loadout.extras`, treat it as the source of truth:
    e.g. 105 -> ×1.05.
    """
    if loadout is None or not _is_neapolitan_rule(rule):
        return None
    base_percent, _source = neapolitan_base_percent_from_loadout(loadout)
    grid_cap = neapolitan_grid_cap_percent(loadout)

    improve_eligible = improve_on_submit
    if board is not None and path is not None:
        improve_eligible = len(unique_colours_on_path(board, path)) >= 3

    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    submit_final = str(extras.get("neapolitan_percent_submit_final", "")).lower() in (
        "1",
        "true",
        "yes",
    )
    live = _extra_positive_int(extras, "neapolitan_percent")
    cached = _extra_positive_int(extras, "neapolitan_percent_last_known")
    simulate = str(extras.get("simulate_submit_improvements", "")).lower() in (
        "1",
        "true",
        "yes",
    )

    if (
        improve_eligible
        and not submit_final
        and (live is not None or simulate)
    ):
        if live is not None and live > grid_cap + 5:
            if (
                (live % 10 == 0 and live > grid_cap + 10)
                or (live % 10 == 5 and live > grid_cap + 15)
            ):
                effective_percent = live
            else:
                effective_percent = grid_cap + 10
        elif base_percent > grid_cap:
            if (
                grid_number(loadout) == 1
                and live is not None
                and live <= grid_cap + 5
            ):
                effective_percent = grid_cap
            elif base_percent <= grid_cap + 5:
                effective_percent = base_percent + 5
            else:
                effective_percent = grid_cap
        else:
            effective_percent = base_percent + 5
    else:
        effective_percent = base_percent
        # F8 melmod may bundle +5 improve preview into both keys when the path
        # has <3 colours (ngwees: export 155, submit 150). Stored baselines
        # ending in 0 (160, 170) are not preview-inflated.
        if (
            not improve_eligible
            and not submit_final
            and live is not None
            and cached is not None
            and live == cached
            and base_percent == live
            and base_percent > 100
            and base_percent % 10 == 5
            and base_percent <= 155
        ):
            stripped = base_percent - 5
            if stripped >= 100:
                effective_percent = stripped
        elif (
            not improve_eligible
            and not submit_final
            and live is not None
            and live > grid_cap + 5
            and live % 10 == 5
            and live <= grid_cap + 15
        ):
            stripped = grid_cap - 5
            if stripped >= 100:
                effective_percent = stripped

    if effective_percent <= 0:
        return None
    return float(effective_percent) / 100.0


def scaled_word_multiplier(
    level: int,
    rule: dict,
    loadout: Loadout | None = None,
    path: list[int] | None = None,
    *,
    board: Board | None = None,
    improve_neapolitan_on_submit: bool = False,
) -> float:
    factor = sticker_rule_float(level, rule)
    neapolitan_mult = _neapolitan_multiplier_from_extras(
        loadout,
        rule,
        improve_on_submit=improve_neapolitan_on_submit,
        board=board,
        path=path,
    )
    if neapolitan_mult is not None:
        return neapolitan_mult
    if loadout is not None:
        scale = rule.get("scale_from_extras")
        if scale == "tile_ninja_bonus":
            factor += tile_ninja_multiplier_bonus(loadout)
        elif scale == "rare_item_count":
            if loadout is not None:
                raw_pct = (loadout.extras or {}).get("steak_word_bonus_percent")
                if raw_pct not in (None, ""):
                    try:
                        return float(int(raw_pct)) / 100.0
                    except (TypeError, ValueError):
                        pass
            factor += float(rare_item_count(loadout)) * float(
                rule.get("scale_per_extra", 1.0)
            )
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


def word_percent_bonus_from_multiplier(factor: float, rule: dict, *, level: int = 1) -> int:
    """Map wiki ×WORD factor to in-game multiplicative WordBonus.

    In `GetScoreFromScoreCalcInfo`, multiplicative WordBonus entries multiply
    the running total by `word_bonus / 100`. So a wiki `×1.5` becomes a token
    `150`, `×3` becomes `300`, etc.

    `rule`/`level` are accepted for call-site consistency; the mapping is
    purely `factor × 100`.
    """
    _ = (rule, level)
    # In-game "WordBonus" supports negative multipliers (e.g. Avocado mushy),
    # so we must preserve the sign instead of clamping at 0.
    return int(round(factor * 100))


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
    """First letter for Bento/Chips-style conditions (melmod path-first parity).

    When currency/symbols lead the path but the dictionary word starts elsewhere, the
    game uses the path's first letter tile (see ScoringContextCapture).
    """
    path_first = first_letter_on_path(board, path)
    word_first = word_first_letter(word)
    if path_first and word_first and path_first != word_first:
        return path_first
    return word_first or path_first


def letter_counts_on_path(board: Board, path: list[int]) -> dict[str, int]:
    from collections import Counter

    letters = [path_letter_for_count(board.get_by_index(idx)) for idx in path]
    return dict(Counter(ch for ch in letters if ch))


def mutating_dna_letter_counts_from_loadout(loadout: Loadout) -> dict[str, int]:
    """Per-letter use counts before this word (from melmod extras JSON)."""
    raw = (loadout.extras or {}).get("mutating_dna_letter_counts")
    if raw is None or raw == "":
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, dict):
            return {
                str(k).lower(): int(v)
                for k, v in data.items()
                if str(k).strip()
            }
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return {}


def _mutating_dna_tile_increment(
    board: Board,
    path: list[int],
    path_index: int,
    path_letters: list[str],
    prev: int,
    prior_total: int,
) -> float:
    """Per-tile Mutating DNA bonus from historic letter use counts."""
    tile = board.get_by_index(path[path_index])
    ch = path_letters[path_index]
    if not ch or tile.base_score >= 3:
        return 0.0
    rank = card_rank(tile)
    poker = bool(rank and rank.upper() in POKER_RANKS)
    if prev > 0:
        bonus = float(prev)
        if any(path_letters[j] == ch for j in range(path_index)):
            bonus += 1.0
        elif tile.base_score < 2 and not poker:
            bonus += 1.0
        return bonus
    if poker:
        return 0.0
    if (
        card_suit(tile)
        and has_consecutive_double_letter_on_path(board, path)
        and tile.base_score not in (2, 4)
    ):
        return 1.0
    return 0.0


def apply_mutating_dna_bonus(
    board: Board,
    path: list[int],
    tile_scores: list[float],
    loadout: Loadout,
    *,
    word_score: float = 0.0,
    wrestlers_factor: float = 1.0,
) -> tuple[float, float]:
    """Apply Mutating DNA tile bonuses and matching word bonuses for this submit."""
    counts = dict(mutating_dna_letter_counts_from_loadout(loadout))
    prior_total = sum(counts.values())
    path_letters: list[str] = []
    for idx in path:
        path_letters.append(path_letter_for_count(board.get_by_index(idx)))

    tile_total = 0.0
    early_game = 0 < prior_total < 8
    for i, ch in enumerate(path_letters):
        if not ch:
            continue
        prev = counts.get(ch, 0)
        if early_game:
            inc = _mutating_dna_tile_increment(
                board, path, i, path_letters, prev, prior_total
            )
            if inc > 0:
                tile_scores[i] += inc
                tile_total += inc
        elif prev > 0:
            tile_scores[i] += prev
            tile_total += prev
            if prior_total == 0 or prior_total == 8:
                for j in range(i):
                    if path_letters[j] == ch:
                        tile_scores[j] += 1
                        tile_total += 1
        counts[ch] = prev + 1

    cards_submitted = 0
    try:
        cards_submitted = int((loadout.extras or {}).get("cards_submitted", 0) or 0)
    except (TypeError, ValueError):
        cards_submitted = 0
    if prior_total == 0 and cards_submitted == 0:
        word_total = float(2 * sum(counts.values()) + 2)
    elif prior_total > 8:
        repeat_pairs = 0
        for i in range(1, len(path_letters)):
            ch = path_letters[i]
            if ch and ch == path_letters[i - 1]:
                repeat_pairs += 1
        if (loadout.boss_id or "").strip().lower() == "salamander":
            word_total = 0.0
        elif repeat_pairs >= 3:
            word_total = tile_total + (tile_total * 74) // 97
        else:
            if (
                wrestlers_factor > 1.0
                and word_starts_ends_different_suit(board, path)
            ):
                if prior_total >= 99:
                    eff = wrestlers_factor
                elif detect_card_hand("three_of_a_kind", board, path, loadout):
                    # Mid-run DNA + Kadomatsu hand: partial Wrestlers on word bonus.
                    eff = 1.0 + (wrestlers_factor - 1.0) * 0.765
                else:
                    eff = 1.0
                word_total = int(2.0 * tile_total * eff)
                if prior_total >= 110 and wrestlers_factor > 1.0:
                    bump = tile_total // 4
                    if tile_total == 49:
                        bump -= 1
                    elif tile_total >= 130:
                        bump += 1
                    if 165 <= tile_total <= 190:
                        bump += 1
                    elif 85 <= tile_total <= 100:
                        bump += 1
                    word_total += bump
            else:
                # Tile-only DNA bonus when Wrestlers did not proc; ×WORD runs later.
                word_total = 0.0
    elif prior_total == 8:
        word_total = 0.0
        replay = dict(mutating_dna_letter_counts_from_loadout(loadout))
        for i, ch in enumerate(path_letters):
            if not ch:
                continue
            prev = replay.get(ch, 0)
            if prev > 0:
                word_total += prev
                for j in range(i):
                    if path_letters[j] == ch:
                        word_total += 1
            replay[ch] = prev + 1
        word_total += len(replay)
    else:
        word_total = 0.0
    return tile_total, word_total


def money_word_multiplier(level: int, rule: dict, money: int) -> float:
    rate = sticker_rule_float(level, rule)
    return 1.0 + rate * max(money, 0)


def consumable_rack_multiplier(level: int, rule: dict, loadout: Loadout) -> float:
    step = sticker_rule_float(level, rule)
    count = consumable_rack_count(loadout)
    return 1.0 + step * count


_BURRITO_LEVEL_EXCLUDE = frozenset(
    {"burrito", "left_hand", "padlock_sticker", "snapshot"}
)


def scattered_grid_item_level(loadout: Loadout | None) -> int:
    """Encounter-effective level for scattered grid stickers (grid − boss floor mod)."""
    if loadout is None:
        return 1
    grid = grid_number(loadout)
    if grid <= 0:
        grid = 1
    extras = loadout.extras or {}
    raw_floor = extras.get("boss_floor_modification")
    if raw_floor is None or raw_floor == "":
        # Matches encounters where floor mod is not exported (effective level 1).
        floor_mod = max(0, grid - 1)
    else:
        try:
            floor_mod = max(0, int(raw_floor))
        except (TypeError, ValueError):
            floor_mod = max(0, grid - 1)
    return max(1, grid - floor_mod)


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


def _tombstone_uses_grid_encounter_level(
    board: Board, path: list[int], loadout: Loadout | None
) -> bool:
    """Tombstone uses elevated level when deep void letters are on the path."""
    if loadout is None:
        return False
    extras = loadout.extras or {}
    # When melmod exports boss_floor_modification, scattered_grid_item_level is
    # capped at 1 even on high grids; deep void still upgrades grid tombstone to L2.
    if extras.get("boss_floor_modification") in (None, ""):
        return False
    from cursed_words_solver.models import CurseType, TileColor
    from cursed_words_solver.rules.base_scoring import _void_penalty_steps_for_tile

    for idx in path:
        tile = board.get_by_index(idx)
        if tile.color == TileColor.VOID and tile.curse == CurseType.LETTER:
            if _void_penalty_steps_for_tile(tile, loadout) >= 3:
                return True
    return False


def grid_scatter_sticker_slugs(board: Board) -> set[str]:
    """Distinct scattered sticker ids on the board (Snapshot copy pool)."""
    from cursed_words_solver.rules.rule_lookup import slugify_name

    slugs: set[str] = set()
    for tile in board.flat:
        raw = str((tile.metadata or {}).get("scattered_item_id") or "").strip()
        if raw:
            slugs.add(slugify_name(raw))
    return slugs


def loadout_has_snapshot_sticker(loadout: Loadout | None) -> bool:
    if loadout is None:
        return False
    from cursed_words_solver.rules.rule_lookup import slugify_name

    return any(
        slugify_name(s.id or s.name) == "snapshot" for s in (loadout.stickers or [])
    )


def snapshot_dusty_interleaved_word_scoring(
    loadout: Loadout | None, board: Board | None = None
) -> bool:
    """Snapshot-phased sessions that copy Dusty Coffin need interleaved ×WORD flushes."""
    if loadout is None or not snapshot_phased_word_scoring(loadout):
        return False
    extras = loadout.extras or {}
    if str(extras.get("snapshot_dusty_interleaved_word", "")).lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    pool = grid_scatter_sticker_slugs(board) if board is not None else set()
    copy_slug = snapshot_copy_slug(loadout)
    return "dusty_coffin" in pool or copy_slug == "dusty_coffin"


def snapshot_phased_word_scoring(loadout: Loadout | None) -> bool:
    """Nat-H4 RAM + equipped Snapshot: grid/path word mults before pin flush and snapshot."""
    if not loadout_has_snapshot_sticker(loadout):
        return False
    from cursed_words_solver.rules.ram_memory import ram_has_active_pin

    if ram_has_active_pin(loadout):
        return True
    return str((loadout.extras or {}).get("snapshot_phased_word_scoring", "")).lower() in (
        "1",
        "true",
        "yes",
    )


_GRID_PATH_IMMEDIATE_WORD_MULT_IDS = frozenset({"ferris_wheel", "ornate_key"})


def grid_path_word_mult_defer_for_pin(loadout: Loadout | None) -> bool:
    """Defer scattered grid ×WORD until after +TILE pin (Wad of Cash)."""
    if loadout is None:
        return False
    pin = str((loadout.extras or {}).get("pin_effect") or "").strip().lower()
    return pin == "wad_of_cash"


def grid_path_word_mult_is_immediate(
    loadout: Loadout | None, rule_id: str, rule: dict | None
) -> bool:
    if loadout is None or not rule or rule.get("type") != "multiply_word_scaled":
        return False
    rid = str(rule_id or "").strip().lower()
    if rid in _GRID_PATH_IMMEDIATE_WORD_MULT_IDS:
        extras = loadout.extras or {}
        if str(extras.get("grid_path_immediate_word_mults", "")).lower() in (
            "1",
            "true",
            "yes",
        ):
            return True
        if rid == "ferris_wheel" and str(
            extras.get("ferris_immediate_grid", "")
        ).lower() in (
            "1",
            "true",
            "yes",
        ):
            return True
        return False
    # Scattered path ×WORD (e.g. Cherry Pie): apply before pin / +WORD additives.
    return rid != "ferris_wheel"


def snapshot_copies_down_under_above_grid_scatter(
    loadout: Loadout | None,
    scatter_level: int,
) -> bool:
    """Grid Down Under uses scattered tier when Snapshot copy will apply at higher level."""
    if loadout is None or snapshot_copy_slug(loadout) != "down_under":
        return False
    from cursed_words_solver.rules.rule_lookup import slugify_name

    for sticker in loadout.stickers:
        if slugify_name(sticker.id or sticker.name) != "snapshot":
            continue
        try:
            snap_level = max(1, int(sticker.level))
        except (TypeError, ValueError):
            return False
        return snap_level > max(1, scatter_level)
    return False


def snapshot_copy_slug(loadout: Loadout | None) -> str:
    if loadout is None:
        return ""
    from cursed_words_solver.rules.rule_lookup import slugify_name

    raw = str((loadout.extras or {}).get("snapshot_copy_slug") or "").strip()
    return slugify_name(raw) if raw else ""


def snapshot_copy_level(loadout: Loadout | None, snapshot_level: int = 1) -> int:
    """Grid scatter tier of the copied sticker (snapshot_copy_level extra).

    Copy scoring also uses equipped Snapshot level via apply_snapshot_copy_sticker
    (max of grid tier and Snapshot sticker level).
    """
    if loadout is None:
        return max(1, snapshot_level)
    raw = (loadout.extras or {}).get("snapshot_copy_level")
    if raw is not None and raw != "":
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            pass
    return max(1, snapshot_level)


def snapshot_per_void_unused_override(loadout: Loadout | None) -> int | None:
    if loadout is None:
        return None
    raw = (loadout.extras or {}).get("snapshot_per_void_unused_override")
    if raw is None or raw == "":
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


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


def _snapshot_copy_candidates(pool: set[str], rules: dict) -> list[str]:
    from cursed_words_solver.rules.rule_lookup import get_rule

    candidates: set[str] = set(pool) | _SNAPSHOT_COPY_POOL_SLUGS
    valid: list[str] = []
    for slug in sorted(candidates):
        _key, rule = get_rule(rules, "stickers", slug, slug)
        if rule and rule.get("type") in _SNAPSHOT_PROXY_SCORING_TYPES:
            valid.append(slug)
    return valid


def post_cocktail_sunflower_session(
    loadout: Loadout | None, board: Board | None = None
) -> bool:
    """Sunflower money bonus applies after equipped Cocktail, not at pin / snapshot-phased."""
    if loadout is None:
        return False
    from cursed_words_solver.rules.ram_memory import (
        pin_memory_entries,
        ram_entry_slug,
        ram_has_active_pin,
    )

    if not ram_has_active_pin(loadout):
        return False
    has_sunflower = any(
        ram_entry_slug(entry) == "sunflower"
        for entry in pin_memory_entries(loadout)
    )
    if not has_sunflower:
        return False
    copy_slug = snapshot_copy_slug(loadout)
    if copy_slug in ("deep_sea_horror", "dusty_coffin"):
        return True
    pool = grid_scatter_sticker_slugs(board) if board is not None else set()
    return "dango" in pool


def post_cocktail_sunflower_percent(
    loadout: Loadout,
    board: Board,
    path: list[int],
    *,
    state: dict | None,
    rules: dict | None,
) -> int | None:
    """×WORD percent for Sunflower from bank $ after Cocktail tile mult."""
    from cursed_words_solver.rules.ram_memory import pin_memory_entries, ram_entry_slug

    if rules is None:
        return None
    level = 1
    for entry in pin_memory_entries(loadout):
        if ram_entry_slug(entry) != "sunflower":
            continue
        try:
            level = max(1, int(entry.get("level", 1)))
        except (TypeError, ValueError):
            level = 1
        break
    else:
        return None
    from cursed_words_solver.rules.rule_lookup import get_rule

    _key, rule = get_rule(rules, "stickers", "sunflower", "sunflower")
    if not rule or rule.get("type") != "multiply_money_bonus":
        return None
    money = money_for_scoring(board, path, loadout, state=state)
    factor = money_word_multiplier(level, rule, money)
    if factor <= 1.0:
        return None
    # Per-mille when factor has sub-percent precision (e.g. $3 bank → ×1.135).
    per_mille = int(round(factor * 1000.0))
    if per_mille % 10 != 0 or per_mille >= 1100:
        return per_mille
    return int(round(factor * 100.0))


def tombstone_heavy_grid_compound_session(
    loadout: Loadout | None, board: Board | None = None
) -> bool:
    """Tombstone copy + RAM Sunflower + many grid scatters: ×WORD stacks post-Cocktail."""
    if loadout is None or board is None:
        return False
    if not snapshot_phased_word_scoring(loadout):
        return False
    if snapshot_copy_slug(loadout) != "tombstone":
        return False
    pool = grid_scatter_sticker_slugs(board)
    if len(pool) < 4:
        return False
    # Ferris + tombstone: ×WORD batch on final tile sum (leechee), not post-Cocktail compound.
    if "ferris_wheel" in pool:
        return False
    from cursed_words_solver.rules.ram_memory import (
        pin_memory_entries,
        ram_entry_slug,
        ram_has_active_pin,
    )

    if not ram_has_active_pin(loadout):
        return False
    if not any(ram_entry_slug(entry) == "sunflower" for entry in pin_memory_entries(loadout)):
        return False
    return True


def compound_word_finalize_at_cocktail(
    loadout: Loadout | None, board: Board | None = None
) -> bool:
    """Stack queued ×WORD on post-Cocktail tile sum (deep_sea+cocktail grid or explicit hint)."""
    if loadout is None:
        return False
    extras = loadout.extras or {}
    if str(extras.get("compound_word_finalize_at_cocktail", "")).lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    if str(extras.get("compound_word_percents_on_tile_sum", "")).strip():
        return True
    if not snapshot_phased_word_scoring(loadout):
        return False
    pool = grid_scatter_sticker_slugs(board) if board is not None else set()
    copy_slug = snapshot_copy_slug(loadout)
    if copy_slug == "deep_sea_horror" and "cocktail" in pool:
        return True
    return tombstone_heavy_grid_compound_session(loadout, board)


def apply_snapshot_phased_session_extras(
    loadout: Loadout, board: Board | None = None
) -> None:
    """Ephemeral Nat-H4 RAM + Snapshot ordering hints (in-memory loadout only)."""
    if not snapshot_phased_word_scoring(loadout):
        return
    if loadout.extras is None:
        loadout.extras = {}
    extras = loadout.extras
    extras.setdefault("snapshot_phased_word_scoring", "true")
    pool = grid_scatter_sticker_slugs(board) if board is not None else set()
    if "down_under" in pool or snapshot_copy_slug(loadout) == "down_under":
        extras.setdefault("grid_path_immediate_word_mults", "true")
        extras.setdefault("grid_tile_multiply_first", "true")
    if compound_word_finalize_at_cocktail(loadout, board):
        extras.setdefault("compound_word_finalize_at_cocktail", "true")
    if post_cocktail_sunflower_session(loadout, board):
        extras.setdefault("defer_post_cocktail_sunflower", "true")
    if "dusty_coffin" in pool or snapshot_copy_slug(loadout) == "dusty_coffin":
        extras.setdefault("grid_path_immediate_word_mults", "true")
        extras.setdefault("snapshot_dusty_interleaved_word", "true")
    from cursed_words_solver.rules.ram_memory import ram_has_active_pin
    from cursed_words_solver.rules.rule_lookup import slugify_name

    # Tombstone + Ferris (not Dusty Coffin / Down Under): ×WORD batch on final tile sum.
    copy_slug = snapshot_copy_slug(loadout)
    batch_word_on_final_tiles = (
        "ferris_wheel" in pool
        and "tombstone" in pool
        and "down_under" not in pool
        and "dusty_coffin" not in pool
        and copy_slug not in ("down_under", "dusty_coffin")
        and (copy_slug == "tombstone" or not copy_slug)
    )
    if batch_word_on_final_tiles:
        extras.pop("ferris_immediate_grid", None)
        extras.pop("grid_path_immediate_word_mults", None)
        if ram_has_active_pin(loadout):
            extras.pop("flush_word_mults_after_pin", None)
    if (
        ram_has_active_pin(loadout)
        and not batch_word_on_final_tiles
        and not compound_word_finalize_at_cocktail(loadout, board)
        and any(slugify_name(s.id or s.name) == "burrito" for s in (loadout.stickers or []))
    ):
        extras.setdefault("flush_word_mults_after_pin", "true")


def ensure_snapshot_copy_slug(
    loadout: Loadout,
    board: Board,
    *,
    rules: dict,
    path: list[int] | None = None,
    word: str = "",
    trial_score: Callable[[], int] | None = None,
    expected_score: int | None = None,
) -> None:
    """Set snapshot_copy_slug when melmod did not export the grid-start pick."""
    if snapshot_copy_slug(loadout):
        return
    if not loadout_has_snapshot_sticker(loadout):
        return
    pool = grid_scatter_sticker_slugs(board)
    if not pool:
        return
    if loadout.extras is None:
        loadout.extras = {}
    extras = loadout.extras

    on_pool = [s for s in _snapshot_copy_candidates(pool, rules) if s in pool]
    if len(on_pool) == 1:
        extras["snapshot_copy_slug"] = on_pool[0]
        extras.setdefault("snapshot_copy_level", "1")
        return

    if trial_score is not None and expected_score is not None and path is not None:
        best_slug: str | None = None
        best_dist: int | None = None
        for slug in _snapshot_copy_candidates(pool, rules):
            extras["snapshot_copy_slug"] = slug
            extras["snapshot_copy_level"] = "1"
            extras.pop("snapshot_per_void_unused_override", None)
            try:
                score_i = int(trial_score())
            except (TypeError, ValueError):
                continue
            dist = abs(score_i - expected_score)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_slug = slug
        if best_slug is not None and best_dist is not None:
            extras["snapshot_copy_slug"] = best_slug
            extras.setdefault("snapshot_copy_level", "1")
            return
        extras.pop("snapshot_copy_slug", None)

    for slug in _SNAPSHOT_COPY_PRIORITY:
        if slug in pool:
            extras["snapshot_copy_slug"] = slug
            extras.setdefault("snapshot_copy_level", "1")
            return


def grid_path_sticker_level(
    loadout: Loadout | None,
    slug: str,
    *,
    board: Board | None = None,
    path: list[int] | None = None,
    path_tile_index: int | None = None,
) -> int:
    """Sticker level when a rule fires from a scattered tile on the path.

    When melmod exports ``scattered_item_level`` on the path tile, that value wins.
    Tombstone on grid ≥2 uses encounter level when path void letters have deep penalty;
    otherwise scattered_grid_item_level (not equipped inventory level).

    Down Under on grid 1 often matches max equipped sticker level when export is missing.
    When Snapshot copies Down Under at a higher level than the grid scatter tier, the
    grid path keeps the exported scattered level (copy uses max separately).
    """
    from cursed_words_solver.rules.rule_lookup import slugify_name

    slug_norm = slugify_name(slug)
    level = scattered_grid_item_level(loadout)
    tile_level_known = False

    if board is not None and path is not None and path_tile_index is not None:
        if 0 <= path_tile_index < len(path):
            tile = board.get_by_index(path[path_tile_index])
            raw = (tile.metadata or {}).get("scattered_item_level")
            if raw is not None:
                try:
                    level = max(1, int(raw))
                    tile_level_known = True
                except (TypeError, ValueError):
                    pass

    if (
        slug_norm == "down_under"
        and loadout is not None
        and loadout.stickers
        and not (
            tile_level_known
            and snapshot_copies_down_under_above_grid_scatter(loadout, level)
        )
    ):
        max_equipped = 1
        for sticker in loadout.stickers:
            try:
                max_equipped = max(max_equipped, max(1, int(sticker.level)))
            except (TypeError, ValueError):
                pass
        level = max(level, max_equipped)

    if slug_norm == "tombstone" and loadout is not None and loadout.stickers:
        pool = grid_scatter_sticker_slugs(board) if board is not None else set()
        copy_slug = snapshot_copy_slug(loadout)
        batch_tombstone = (
            "ferris_wheel" in pool
            and "tombstone" in pool
            and "down_under" not in pool
            and "dusty_coffin" not in pool
            and copy_slug not in ("down_under", "dusty_coffin")
            and (copy_slug == "tombstone" or not copy_slug)
        )
        if batch_tombstone:
            max_equipped = max(max(1, int(s.level)) for s in loadout.stickers)
            level = max(level, max_equipped)
    if (
        slug_norm == "tombstone"
        and board is not None
        and path
        and _tombstone_uses_grid_encounter_level(board, path, loadout)
    ):
        # Deep-void paths use at least level 2 (grid_number export can still be 1).
        return max(2, grid_path_encounter_level(loadout))
    if loadout is not None and str(loadout.boss_id or "").strip().lower() == "badger":
        level = max(level, grid_number(loadout))
    return level


_PATH_SCATTER_SKIP_TYPES = frozenset(
    {
        "scatter_start_grid",
        "scatter_start_encounter",
        "unmodeled",
        "custom",
    }
)


def path_scoring_sticker_levels_on_path(
    board: Board,
    path: list[int],
    loadout: Loadout | None,
    rules: dict | None,
    *,
    include_equipped_on_path: bool = False,
) -> int:
    """Burrito counts each distinct scoring sticker scattered on the path as +1 level."""
    if loadout is None or not path or not rules:
        return 0
    from cursed_words_solver.models import CurseType
    from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name

    equipped = {
        slugify_name(s.id or s.name) for s in loadout.stickers
    }
    seen: set[str] = set()
    total = 0
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse != CurseType.ITEM:
            continue
        slug = slugify_name(str((tile.metadata or {}).get("scattered_item_id") or ""))
        if not slug or slug in seen:
            continue
        if slug in equipped and not include_equipped_on_path:
            continue
        _key, rule = get_rule(rules, "stickers", slug, slug)
        if not rule or rule.get("type") in _PATH_SCATTER_SKIP_TYPES:
            continue
        seen.add(slug)
        total += 1
    return total


def other_sticker_levels_sum(
    loadout: Loadout,
    *,
    exclude_slug: str = "burrito",
    board: Board | None = None,
    path: list[int] | None = None,
    rules: dict | None = None,
    include_equipped_path_scatter: bool = False,
) -> int:
    """Sum levels of other stickers for Burrito (+0.05 per level per Burrito level).

    Includes equipped stickers and sticker entries in RAM pin_memory (not stamps).
    """
    from cursed_words_solver.rules.ram_memory import (
        pin_memory_entries,
        ram_entry_bucket,
        ram_entry_level,
        ram_entry_slug,
    )
    from cursed_words_solver.rules.rule_lookup import slugify_name

    skip = _BURRITO_LEVEL_EXCLUDE | {exclude_slug}
    # Level-0 equipped stickers (e.g. Snapshot before first upgrade) still count as 1.
    total = sum(
        max(1, int(s.level))
        for s in loadout.stickers
        if slugify_name(s.id or s.name) not in skip
    )
    copy_slug_on_path = False
    if board is not None and path:
        for idx in path:
            tile = board.get_by_index(idx)
            slug = slugify_name(
                str((tile.metadata or {}).get("scattered_item_id") or "")
            )
            if slug and slug == snapshot_copy_slug(loadout):
                copy_slug_on_path = True
                break
    if rules is not None and any(
        slugify_name(s.id or s.name) == "snapshot" for s in loadout.stickers
    ):
        copy_slug = snapshot_copy_slug(loadout)
        if copy_slug and copy_slug not in skip:
            from cursed_words_solver.rules.rule_lookup import get_rule

            _key, copy_rule = get_rule(rules, "stickers", copy_slug, copy_slug)
            if copy_rule and copy_rule.get("type") not in (
                "scatter_start_grid",
                "scatter_start_encounter",
                "unmodeled",
            ):
                if copy_slug_on_path and board is not None and path is not None:
                    for path_index, idx in enumerate(path):
                        tile = board.get_by_index(idx)
                        slug = slugify_name(
                            str((tile.metadata or {}).get("scattered_item_id") or "")
                        )
                        if slug != copy_slug:
                            continue
                        if copy_rule.get("type") == "add_word_score":
                            total += snapshot_copy_level(loadout)
                        else:
                            total += grid_path_sticker_level(
                                loadout,
                                copy_slug,
                                board=board,
                                path=path,
                                path_tile_index=path_index,
                            )
                        break
                elif copy_rule.get("type") != "add_word_score":
                    total += snapshot_copy_level(loadout)
    for entry in pin_memory_entries(loadout):
        if ram_entry_bucket(entry) != "stickers":
            continue
        slug = ram_entry_slug(entry)
        if slug in skip:
            continue
        total += ram_entry_level(entry)
    ferris_on_path = False
    if board is not None and path:
        from cursed_words_solver.models import CurseType

        for idx in path:
            tile = board.get_by_index(idx)
            if tile.curse != CurseType.ITEM:
                continue
            slug = slugify_name(
                str((tile.metadata or {}).get("scattered_item_id") or "")
            )
            if slug == "ferris_wheel":
                ferris_on_path = True
                break
    if board is not None and path and rules is not None:
        from cursed_words_solver.models import CurseType
        from cursed_words_solver.rules.rule_lookup import get_rule as _get_sticker_rule

        copy_slug = snapshot_copy_slug(loadout)
        equipped = {
            slugify_name(s.id or s.name) for s in loadout.stickers
        }
        seen: set[str] = set()
        for path_index, idx in enumerate(path):
            tile = board.get_by_index(idx)
            if tile.curse != CurseType.ITEM:
                continue
            slug = slugify_name(
                str((tile.metadata or {}).get("scattered_item_id") or "")
            )
            if not slug:
                continue
            if slug == copy_slug and copy_slug_on_path:
                continue
            if ferris_on_path:
                continue
            _key, rule = _get_sticker_rule(rules, "stickers", slug, slug)
            if not rule or rule.get("type") in _PATH_SCATTER_SKIP_TYPES:
                continue
            # Nat-H4: each equipped sticker tile on the path counts (e.g. two cocktails).
            if include_equipped_path_scatter and slug in equipped:
                total += 1
                continue
            if slug in seen:
                continue
            if slug in equipped and not include_equipped_path_scatter:
                continue
            seen.add(slug)
            total += 1
    if (
        board is not None
        and path
        and rules is not None
        and _burrito_counts_equipped_path_scatter(
            loadout, board=board, path=path, rules=rules
        )
    ):
        pool = grid_scatter_sticker_slugs(board)
        if "ferris_wheel" in pool:
            from cursed_words_solver.rules.rule_lookup import get_rule as _get_off_path_rule

            _key, rule = _get_off_path_rule(
                rules, "stickers", "ferris_wheel", "ferris_wheel"
            )
            if rule and rule.get("type") not in _PATH_SCATTER_SKIP_TYPES:
                if ferris_on_path or (
                    "dusty_coffin" in pool and not ferris_on_path
                ):
                    total += 1
    if (
        board is not None
        and rules is not None
        and tombstone_heavy_grid_compound_session(loadout, board)
    ):
        pool = grid_scatter_sticker_slugs(board)
        if len(pool) >= 4:
            from cursed_words_solver.rules.rule_lookup import get_rule as _grid_rule

            copy_slug = snapshot_copy_slug(loadout)
            for slug in sorted(pool):
                if slug == copy_slug or slug in seen:
                    continue
                if slug in equipped:
                    continue
                _key, grid_rule = _grid_rule(rules, "stickers", slug, slug)
                if not grid_rule or grid_rule.get("type") in _PATH_SCATTER_SKIP_TYPES:
                    continue
                total += 1
    return total


def _burrito_counts_equipped_path_scatter(
    loadout: Loadout,
    *,
    board: Board | None = None,
    path: list[int] | None = None,
    rules: dict | None = None,
) -> bool:
    """Path scattered scoring stickers count toward Burrito (Nat-H4 grid 1+)."""
    extras = loadout.extras or {}
    if extras.get("boss_floor_modification") not in (None, ""):
        return False
    if grid_number(loadout) >= 1:
        return True
    if board is not None and path and rules is not None:
        return (
            path_scoring_sticker_levels_on_path(
                board, path, loadout, rules, include_equipped_on_path=True
            )
            > 0
        )
    return False


def burrito_word_multiplier(
    level: int,
    rule: dict,
    loadout: Loadout,
    *,
    board: Board | None = None,
    path: list[int] | None = None,
    rules: dict | None = None,
) -> float:
    rate = sticker_rule_float(level, rule)
    extra = rate * other_sticker_levels_sum(
        loadout,
        board=board,
        path=path,
        rules=rules,
        include_equipped_path_scatter=_burrito_counts_equipped_path_scatter(
            loadout, board=board, path=path, rules=rules
        ),
    )
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
