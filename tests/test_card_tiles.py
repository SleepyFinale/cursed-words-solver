"""Card suit, joker, and stacked-curse behavior."""

from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile
from cursed_words_solver.rules.scoring_conditions import (
    bicycle_suited_credit_on_path,
    detect_card_hand,
    effective_suited_cards_on_path,
    is_card_tile,
    is_joker_tile,
    suited_cards_on_path_count,
)
from cursed_words_solver.search import _is_wildcard_tile
from cursed_words_solver.rules.card_overlay import detect_card_overlay as _detect_card_overlay


def _card(row: int, col: int, rank: str, suit: str, score: int = 2) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=rank,
        letter=rank,
        base_score=score,
        curse=CurseType.CARD,
        metadata={"card_suit": suit, "card_rank": rank},
    )


def _joker(row: int, col: int) -> Tile:
    return Tile(
        row=row,
        col=col,
        char="?",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
        metadata={"is_joker": True},
    )


def _empty_board() -> Board:
    grid = [
        [
            Tile(row=r, col=c, char="X", letter="X", base_score=1)
            for c in range(5)
        ]
        for r in range(5)
    ]
    return Board(tiles=grid, money=0)


def test_parse_board_suited_letter_keeps_letter_curse():
    data = {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "tiles": [
                {
                    "row": 0,
                    "col": 0,
                    "char": "K",
                    "letter": "K",
                    "base_score": 5,
                    "color": "red",
                    "curse": "letter",
                    "card_suit": "hearts",
                    "card_rank": "K",
                },
            ]
            + [
                {
                    "row": r,
                    "col": c,
                    "char": "X",
                    "letter": "X",
                    "curse": "letter",
                }
                for r in range(5)
                for c in range(5)
                if not (r == 0 and c == 0)
            ],
        }
    }
    board = parse_board_from_run_state(data)
    assert board is not None
    tile = board.get(0, 0)
    assert tile is not None
    assert tile.curse == CurseType.LETTER
    assert tile.metadata.get("card_suit") == "hearts"
    assert is_card_tile(tile)


def test_parse_board_number_with_suit_keeps_number_curse():
    data = {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "tiles": [
                {
                    "row": 0,
                    "col": 0,
                    "char": "4",
                    "letter": "4",
                    "base_score": 4,
                    "curse": "number",
                    "number_value": 4,
                    "card_suit": "spades",
                    "card_rank": "4",
                },
            ]
            + [
                {
                    "row": r,
                    "col": c,
                    "char": "X",
                    "letter": "X",
                    "curse": "letter",
                }
                for r in range(5)
                for c in range(5)
                if not (r == 0 and c == 0)
            ],
        }
    }
    board = parse_board_from_run_state(data)
    assert board is not None
    tile = board.get(0, 0)
    assert tile is not None
    assert tile.curse == CurseType.NUMBER
    assert tile.number_value == 4
    assert tile.metadata.get("card_suit") == "spades"
    assert is_card_tile(tile)


def test_parse_board_is_joker_metadata():
    data = {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "tiles": [
                {
                    "row": 0,
                    "col": 0,
                    "char": "?",
                    "letter": "?",
                    "base_score": 0,
                    "curse": "wildcard",
                    "is_joker": True,
                },
            ]
            + [
                {
                    "row": r,
                    "col": c,
                    "char": "X",
                    "letter": "X",
                    "curse": "letter",
                }
                for r in range(5)
                for c in range(5)
                if not (r == 0 and c == 0)
            ],
        }
    }
    board = parse_board_from_run_state(data)
    assert board is not None
    tile = board.get(0, 0)
    assert tile is not None
    assert is_joker_tile(tile)
    assert not is_card_tile(tile)
    assert _is_wildcard_tile(tile)


def test_joker_plus_rank_makes_pair():
    board = _empty_board()
    board.tiles[0][0] = _joker(0, 0)
    board.tiles[0][1] = _card(0, 1, "7", "hearts")
    assert detect_card_hand("pair", board, [0, 1], Loadout())


def test_two_jokers_make_pair():
    board = _empty_board()
    board.tiles[0][0] = _joker(0, 0)
    board.tiles[0][1] = _joker(0, 1)
    assert detect_card_hand("pair", board, [0, 1], Loadout())


def test_joker_fills_flush_with_martini():
    board = _empty_board()
    path = []
    board.tiles[0][0] = _joker(0, 0)
    for c, rank in enumerate("23", start=1):
        board.tiles[0][c] = _card(0, c, rank, "hearts")
        path.append(c)
    path.insert(0, 0)
    loadout = Loadout(
        stamps=[LoadoutItem(id="martini", name="Martini", kind="stamp")]
    )
    assert detect_card_hand("flush", board, path, loadout)


def test_joker_fills_straight_gap():
    board = _empty_board()
    path = []
    board.tiles[0][0] = _card(0, 0, "2", "hearts")
    board.tiles[0][1] = _joker(0, 1)
    board.tiles[0][2] = _card(0, 2, "4", "hearts")
    path = [0, 1, 2]
    loadout = Loadout(
        stamps=[LoadoutItem(id="martini", name="Martini", kind="stamp")]
    )
    assert detect_card_hand("straight", board, path, loadout)


def _plain(row: int, col: int, rank: str, score: int = 2) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=rank,
        letter=rank,
        base_score=score,
        curse=CurseType.LETTER,
        metadata={"source": "melmod"},
    )


def test_suited_cards_on_path_counts_letter_tiles_with_suit_metadata():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "K", "hearts")
    board.tiles[0][1] = _card(0, 1, "7", "spades")
    board.tiles[0][2] = _plain(0, 2, "Q", 1)
    loadout = Loadout()
    assert suited_cards_on_path_count(board, [0, 1, 2]) == 2
    assert effective_suited_cards_on_path(board, [0, 1, 2], loadout) == 2


def test_suited_cards_deduplicate_same_suit_on_path():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "K", "hearts")
    board.tiles[0][1] = _card(0, 1, "Q", "hearts")
    board.tiles[0][2] = _plain(0, 2, "Z", 1)
    assert suited_cards_on_path_count(board, [0, 1, 2]) == 1


def test_bicycle_nebbish_only_real_card_on_path_counts_one():
    """Regression: nebbish — only N♥ is a playing card; plain S/H letters are not suited."""
    board = _empty_board()
    path: list[int] = []
    layout = [
        (0, 1, "N", 1, {"card_suit": "hearts", "card_rank": "N"}),
        (1, 1, "E", 1, {}),
        (2, 0, "B", 3, {}),
        (3, 1, "B", 3, {}),
        (3, 2, "I", 1, {}),
        (4, 3, "S", 4, {}),
        (3, 4, "H", 1, {}),
    ]
    for row, col, ch, score, meta in layout:
        if meta:
            board.tiles[row][col] = Tile(
                row=row,
                col=col,
                char=ch,
                letter=ch,
                base_score=float(score),
                curse=CurseType.LETTER,
                metadata={"source": "melmod", **meta},
            )
        else:
            board.tiles[row][col] = _plain(row, col, ch, score)
        path.append(row * 5 + col)
    assert bicycle_suited_credit_on_path(board, path) == 1
    loadout = Loadout(
        extras={
            "pin_effect": "bicycle",
            "pin_right_level": "1",
            "pin_right_variable": "1",
            "bicycle_word_score_bonus": "0",
        }
    )
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    score, bd = ScoringPipeline().score(board, path, "nebbish", loadout)
    assert bd["pipeline"]["word_score"] == 1.0
    assert int(score) == 15


def test_suited_cards_count_duplicate_ranks_on_multi_suit_path():
    """Multi-suit paths credit unique suited ranks (duplicate rank counts once)."""
    board = _empty_board()
    board.tiles[0][0] = Tile(
        row=0, col=0, char="D", letter="D", base_score=2, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "diamonds", "card_rank": "D"},
    )
    board.tiles[0][1] = _plain(0, 1, "O", 1)
    board.tiles[0][2] = Tile(
        row=0, col=2, char="T", letter="T", base_score=1, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "diamonds", "card_rank": "T"},
    )
    board.tiles[0][3] = Tile(
        row=0, col=3, char="D", letter="D", base_score=2, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "hearts", "card_rank": "D"},
    )
    board.tiles[0][4] = Tile(
        row=0, col=4, char="M", letter="M", base_score=3, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "spades", "card_rank": "M"},
    )
    path = [0, 1, 2, 3, 4]
    assert suited_cards_on_path_count(board, path) == 3


def test_effective_suited_prefers_board_count_over_stale_extras():
    board = _empty_board()
    board.tiles[0][0] = Tile(
        row=0, col=0, char="D", letter="D", base_score=2, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "diamonds", "card_rank": "D"},
    )
    board.tiles[0][1] = Tile(
        row=0, col=1, char="T", letter="T", base_score=1, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "diamonds", "card_rank": "T"},
    )
    board.tiles[0][2] = Tile(
        row=0, col=2, char="D", letter="D", base_score=2, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "hearts", "card_rank": "D"},
    )
    loadout = Loadout(extras={"bicycle_suited_on_path": 4})
    assert effective_suited_cards_on_path(board, [0, 1, 2], loadout) == 2


def test_effective_suited_uses_board_only_when_board_lacks_suits():
    board = _empty_board()
    board.tiles[0][0] = _plain(0, 0, "A", 1)
    board.tiles[0][1] = _plain(0, 1, "B", 1)
    loadout = Loadout(extras={"bicycle_suited_on_path": 2})
    assert suited_cards_on_path_count(board, [0, 1]) == 0
    assert effective_suited_cards_on_path(board, [0, 1], loadout) == 0


def test_effective_suited_ignores_stale_low_melmod_extra():
    """Board metadata wins when melmod submit extra under-counts (ashy regression)."""
    board = _empty_board()
    board.tiles[0][1] = Tile(
        row=0,
        col=1,
        char="🃏",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
        metadata={"source": "melmod", "is_joker": True, "card_suit": "joker"},
    )
    board.tiles[1][0] = Tile(
        row=1,
        col=0,
        char="W",
        letter="W",
        base_score=4,
        curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "spades", "card_rank": "W"},
    )
    board.tiles[1][4] = Tile(
        row=1,
        col=4,
        char="S",
        letter="S",
        base_score=4,
        curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "hearts", "card_rank": "S"},
    )
    board.tiles[2][4] = Tile(
        row=2,
        col=4,
        char="Y",
        letter="Y",
        base_score=4,
        curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "spades", "card_rank": "Y"},
    )
    path = [1, 5, 9, 14]
    loadout = Loadout(extras={"bicycle_suited_on_path": 2})
    assert bicycle_suited_credit_on_path(board, path) == 4
    assert effective_suited_cards_on_path(board, path, loadout) == 4


def test_bicycle_joker_multi_suit_adds_joker_to_rank_credit():
    """Regression 20260530_005432 ashy: joker + W♠ + S♥ + Y♠ → 4 suited credit."""
    board = _empty_board()
    board.tiles[0][1] = Tile(
        row=0,
        col=1,
        char="🃏",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
        metadata={"source": "melmod", "is_joker": True, "card_suit": "joker"},
    )
    board.tiles[1][0] = _card(1, 0, "W", "spades", 4)
    board.tiles[1][4] = _card(1, 4, "S", "hearts", 4)
    board.tiles[2][4] = _card(2, 4, "Y", "spades", 4)
    path = [1, 5, 9, 14]
    assert bicycle_suited_credit_on_path(board, path) == 4
    assert suited_cards_on_path_count(board, path) == 4


def test_bicycle_joker_at_path_end_multi_suit_does_not_add_credit():
    """Regression scourers: path-end joker does not add to multi-suit rank credit."""
    board = _empty_board()
    board.tiles[0][1] = _card(0, 1, "J", "spades", 1)
    board.tiles[0][2] = _card(0, 2, "O", "clubs", 1)
    board.tiles[1][4] = Tile(
        row=1,
        col=4,
        char="?",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
        metadata={"source": "melmod", "is_joker": True},
    )
    path = [1, 2, 9]
    assert bicycle_suited_credit_on_path(board, path) == 2


def test_bicycle_two_jokers_multi_suit_per_tile_credit():
    """Regression 20260530_010221 godsons: two non-end jokers + 3 suited → credit 5."""
    board = _empty_board()
    board.tiles[3][2] = Tile(
        row=3,
        col=2,
        char="?",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
        metadata={"source": "melmod", "is_joker": True, "card_suit": "joker"},
    )
    board.tiles[2][3] = Tile(
        row=2,
        col=3,
        char="?",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
        metadata={"source": "melmod", "is_joker": True, "card_suit": "joker"},
    )
    board.tiles[2][4] = _card(2, 4, "E", "diamonds", 1)
    board.tiles[1][1] = _card(1, 1, "E", "spades", 1)
    board.tiles[0][0] = _card(0, 0, "M", "spades", 3)
    path = [17, 13, 14, 6, 10, 5, 0]
    assert bicycle_suited_credit_on_path(board, path) == 5


def test_bicycle_multi_suit_counts_unique_suited_ranks():
    """Multi-suit paths: dedupe (rank,suit); duplicate I♦ counts once (serenities parity)."""
    board = _empty_board()
    board.tiles[0][4] = Tile(
        row=0, col=4, char="A", letter="A", base_score=1, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "spades", "card_rank": "A"},
    )
    board.tiles[1][4] = _plain(1, 4, "P", 1)
    board.tiles[2][4] = Tile(
        row=2, col=4, char="P", letter="P", base_score=1, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "hearts", "card_rank": "P"},
    )
    board.tiles[3][1] = Tile(
        row=3, col=1, char="A", letter="A", base_score=3, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "clubs", "card_rank": "A"},
    )
    board.tiles[3][2] = Tile(
        row=3, col=2, char="L", letter="L", base_score=1, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "diamonds", "card_rank": "L"},
    )
    board.tiles[3][3] = Tile(
        row=3, col=3, char="L", letter="L", base_score=1, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "hearts", "card_rank": "L"},
    )
    board.tiles[4][1] = Tile(
        row=4, col=1, char="S", letter="S", base_score=1, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "spades", "card_rank": "S"},
    )
    path = [4, 9, 14, 16, 17, 18, 21]
    assert bicycle_suited_credit_on_path(board, path) == 4


def test_bicycle_styte_same_rank_different_suit_counts_both():
    """Regression styte: T♥ + T♣ on 5-letter path with T×2 → credit 2."""
    board = _empty_board()
    board.tiles[0][2] = _plain(0, 2, "S", 0)
    board.tiles[1][2] = Tile(
        row=1, col=2, char="T", letter="T", base_score=0, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "hearts", "card_rank": "T"},
    )
    board.tiles[1][1] = _plain(1, 1, "Y", 0)
    board.tiles[1][0] = Tile(
        row=1, col=0, char="T", letter="T", base_score=0, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "clubs", "card_rank": "T"},
    )
    board.tiles[0][0] = _plain(0, 0, "E", 0)
    path = [2, 7, 6, 5, 0]
    assert bicycle_suited_credit_on_path(board, path) == 2


def test_bicycle_mono_suit_joker_two_non_joker_per_tile_credit():
    """Regression ass: joker + E♠ + Q♠ mono-suit → per-tile credit 3."""
    board = _empty_board()
    board.tiles[2][4] = Tile(
        row=2,
        col=4,
        char="?",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
        metadata={"source": "melmod", "is_joker": True, "card_suit": "joker"},
    )
    board.tiles[1][4] = _card(1, 4, "E", "spades", 1)
    board.tiles[0][3] = _card(0, 3, "Q", "spades", 10)
    assert bicycle_suited_credit_on_path(board, [14, 9, 3]) == 3


def test_detect_card_overlay_symbols_and_joker():
    assert _detect_card_overlay("K♥") == ("hearts", "K", False)
    assert _detect_card_overlay("JOKER tile") == (None, None, True)
    assert _detect_card_overlay("7 of clubs") == ("clubs", "7", False)
