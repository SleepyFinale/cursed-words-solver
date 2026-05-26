import json
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.rules.base_scoring import score_word_base, tile_base_contribution

DEBUG_DIR = Path.home() / ".cursed_words_solver" / "debug"


def _board_from_letters(rows: list[str]) -> Board:
    tiles = []
    for r, row in enumerate(rows):
        row_tiles = []
        for c, ch in enumerate(row):
            row_tiles.append(
                Tile(
                    row=r,
                    col=c,
                    char=ch,
                    letter=ch,
                    base_score=1,
                    color=TileColor.COLORLESS,
                    curse=CurseType.LETTER,
                )
            )
        tiles.append(row_tiles)
    return Board(tiles=tiles)


def test_shiny_tile_flat_50_ocr():
    """OCR boards without melmod metadata use wiki flat 50 shiny base."""
    t = Tile(0, 0, "A", "A", 1, TileColor.SHINY, CurseType.LETTER)
    assert tile_base_contribution(t) == 50


def test_melmod_shiny_uses_packet_score():
    t = Tile(
        0,
        0,
        "A",
        "A",
        1,
        TileColor.SHINY,
        CurseType.LETTER,
        metadata={"source": "melmod"},
    )
    assert tile_base_contribution(t) == 1


def test_melmod_red_no_extra_color_bonus_when_base_equals_scrabble():
    """Melmod packet.Score on colored tile must not get +1 again (BOOH-style bug)."""
    t = Tile(
        0,
        0,
        "H",
        "H",
        4,
        TileColor.RED,
        CurseType.LETTER,
        metadata={"source": "melmod"},
    )
    assert tile_base_contribution(t) == 4


def test_void_negates_letter():
    t = Tile(0, 0, "E", "E", 1, TileColor.VOID, CurseType.LETTER)
    assert tile_base_contribution(t) == -1


def test_melmod_void_letter_zero_base_score():
    t = Tile(
        0,
        0,
        "O",
        "O",
        0,
        TileColor.VOID,
        CurseType.LETTER,
        metadata={"source": "melmod"},
    )
    assert tile_base_contribution(t) == -1


def test_melmod_void_number_zero_base_score():
    t = Tile(
        0,
        0,
        "9",
        "9",
        0,
        TileColor.VOID,
        CurseType.NUMBER,
        number_value=9,
        metadata={"source": "melmod"},
    )
    assert tile_base_contribution(t) == -9


def test_melmod_void_chess_queen_zero_base_score():
    t = Tile(
        0,
        0,
        "w",
        "?",
        0,
        TileColor.VOID,
        CurseType.CHESS_QUEEN,
        metadata={"source": "melmod", "chess_color": "black"},
    )
    assert tile_base_contribution(t) == -9


def test_melmod_void_chess_king_zero_base_score():
    t = Tile(
        0,
        0,
        "k",
        "?",
        0,
        TileColor.VOID,
        CurseType.CHESS_KING,
        metadata={"source": "melmod", "chess_color": "white"},
    )
    assert tile_base_contribution(t) == -15


def test_red_bonus():
    t = Tile(0, 0, "A", "A", 1, TileColor.RED, CurseType.LETTER)
    assert tile_base_contribution(t) == 2  # 1 + 1


def test_red_r_baked_in_base_score_virge():
    """Melmod exports packet.Score; red bonus already included (virge R)."""
    t = Tile(0, 0, "R", "R", 2, TileColor.RED, CurseType.LETTER)
    assert tile_base_contribution(t) == 2


def test_blue_r_baked_in_base_score_foxtrot():
    """Melmod exports packet.Score; blue bonus already included (foxtrot R)."""
    t = Tile(0, 0, "R", "R", 2, TileColor.BLUE, CurseType.LETTER)
    assert tile_base_contribution(t) == 2


def test_red_m_manipulated_and_color_baked():
    t = Tile(0, 0, "M", "M", 4, TileColor.RED, CurseType.LETTER)
    assert tile_base_contribution(t) == 4


def test_score_word_path():
    board = _board_from_letters(["cat", "xxx", "xxx", "xxx", "xxx"])
    # c at 0,0 -> index 0; a at 0,1 -> 1; t at 0,2 -> 2
    score, _ = score_word_base(board, [0, 1, 2], "cat")
    assert score == 3.0


def _board_from_debug_parse(name: str) -> Board | None:
    path = DEBUG_DIR / name
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    tiles = data.get("tiles", [])
    if len(tiles) != 25:
        return None
    run_state = {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "money": 6,
            "tiles": [
                {
                    "row": t["row"],
                    "col": t["col"],
                    "char": t["char"],
                    "letter": t["letter"],
                    "base_score": t["base_score"],
                    "color": t["color"],
                    "curse": t["curse"],
                }
                for t in tiles
            ],
        }
    }
    return parse_board_from_run_state(run_state)


def test_foxtrot_word_score_from_debug_board():
    board = _board_from_debug_parse("parse_20260521_155907.json")
    if board is None:
        return
    score, _ = score_word_base(board, [10, 6, 11, 12, 13, 19, 24], "foxtrot")
    assert score == 18.0


def test_virge_word_score_from_debug_board():
    board = _board_from_debug_parse("parse_20260521_160425.json")
    if board is None:
        return
    score, _ = score_word_base(board, [21, 16, 17, 18, 24], "virge")
    assert score == 10.0
