"""Card suit, joker, and stacked-curse behavior."""

from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile
from cursed_words_solver.rules.scoring_conditions import (
    detect_card_hand,
    effective_suited_cards_on_path,
    is_card_tile,
    is_joker_tile,
    suited_cards_on_path_count,
)
from cursed_words_solver.search import _is_wildcard_tile
from cursed_words_solver.vision.board_parser import _detect_card_overlay


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


def test_suited_cards_deduplicate_duplicate_ranks_on_path():
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


def test_effective_suited_uses_melmod_extra_when_board_lacks_suits():
    board = _empty_board()
    board.tiles[0][0] = _plain(0, 0, "A", 1)
    board.tiles[0][1] = _plain(0, 1, "B", 1)
    loadout = Loadout(extras={"bicycle_suited_on_path": 2})
    assert suited_cards_on_path_count(board, [0, 1]) == 0
    assert effective_suited_cards_on_path(board, [0, 1], loadout) == 2


def test_detect_card_overlay_symbols_and_joker():
    assert _detect_card_overlay("K♥") == ("hearts", "K", False)
    assert _detect_card_overlay("JOKER tile") == (None, None, True)
    assert _detect_card_overlay("7 of clubs") == ("clubs", "7", False)
