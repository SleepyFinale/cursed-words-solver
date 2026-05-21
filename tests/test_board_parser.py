import numpy as np

from cursed_words_solver.models import CurseType
from cursed_words_solver.vision.board_parser import (
    SCRABBLE_VALUES,
    BoardParser,
    OcrDetection,
    _disambiguate_letter,
    _parse_char_and_score,
    _parse_score_override,
    _pick_primary_detection,
    format_board_grid,
    letter_roi,
    score_roi,
)
from cursed_words_solver.vision.color_detect import classify_tile_color
from cursed_words_solver.models import Board, Tile, TileColor


def test_scrabble_values():
    assert SCRABBLE_VALUES["Q"] == 10


def test_parse_char_letter():
    display, letter, score, curse, conf = _parse_char_and_score(["A", "1"], [0.9, 0.8])
    assert letter == "A"
    assert score >= 1


def test_parse_char_letter_with_score_override():
    display, letter, score, curse, conf = _parse_char_and_score(
        ["G"], [0.9], score_override=2
    )
    assert letter == "G"
    assert score == 2
    assert curse == CurseType.LETTER


def test_parse_k_not_chess():
    display, letter, score, curse, conf = _parse_char_and_score(["K"], [0.9])
    assert letter == "K"
    assert curse == CurseType.LETTER


def test_parse_k_with_subscript_score():
    display, letter, score, curse, conf = _parse_char_and_score(
        ["K"], [0.9], score_override=5
    )
    assert letter == "K"
    assert score == 5
    assert curse == CurseType.LETTER


def test_parse_number_tile():
    display, letter, score, curse, conf = _parse_char_and_score(["2"], [0.9])
    assert curse == CurseType.NUMBER
    assert letter == "2"


def test_parse_wildcard():
    display, letter, score, curse, conf = _parse_char_and_score(["?"], [0.9])
    assert curse == CurseType.WILDCARD


def test_chess_requires_full_word():
    display, letter, score, curse, conf = _parse_char_and_score(
        ["knight"], [0.9]
    )
    assert curse == CurseType.CHESS_KNIGHT
    assert letter == "?"


def test_single_k_not_chess():
    display, letter, score, curse, conf = _parse_char_and_score(["K"], [0.99])
    assert curse != CurseType.CHESS_KNIGHT


def test_parse_score_override():
    assert _parse_score_override(["4"]) == 4
    assert _parse_score_override(["12"]) == 10
    assert _parse_score_override([]) is None


def test_disambiguate_zero_to_o_with_subscript_one():
    assert _disambiguate_letter("0", 0.9, 1) == "O"


def test_disambiguate_skip_score_digit():
    assert _disambiguate_letter("5", 0.3, 5) == ""


def test_pick_primary_skips_small_subscript():
    roi_pixels = 10000
    detections = [
        OcrDetection("K", 0.95, 0.8, 8000, 0.35),
        OcrDetection("5", 0.7, 0.4, 400, 0.85),
    ]
    picked = _pick_primary_detection(detections, 5, roi_pixels)
    assert picked is not None
    assert picked[0] == "K"


def test_parse_o_not_number_when_score_is_one():
    display, letter, score, curse, conf = _parse_char_and_score(
        ["0"], [0.7], score_override=1
    )
    assert letter == "O"
    assert score == 1
    assert curse == CurseType.LETTER


def test_split_cells_inset():
    parser = BoardParser(cell_inset_ratio=0.1)
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cells = parser.split_cells(img)
    assert len(cells) == 25
    assert cells[0].shape[0] < 20
    assert cells[0].shape[1] < 20


def test_letter_and_score_roi_smaller_than_cell():
    cell = np.zeros((50, 50, 3), dtype=np.uint8)
    assert letter_roi(cell).shape[0] < 50
    assert score_roi(cell).shape[0] < 50


def test_format_board_grid():
    tile = lambda ch: Tile(
        row=0,
        col=0,
        char=ch,
        letter=ch,
        base_score=1,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )
    board = Board(
        tiles=[
            [tile("N"), tile("A"), tile("E"), tile("W"), tile("O")],
            [tile("U"), tile("G"), tile("K"), tile("1"), tile("E")],
            [tile("X"), tile("E"), tile("I"), tile("R"), tile("O")],
            [tile("E"), tile("S"), tile("E"), tile("I"), tile("K")],
            [tile("E"), tile("B"), tile("K"), tile("O"), tile("P")],
        ]
    )
    grid = format_board_grid(board)
    assert grid.split("\n")[0] == "N A E W O"


def test_classify_colorless():
    gray = np.full((50, 50, 3), 128, dtype=np.uint8)
    color = classify_tile_color(gray)
    assert color.value in ("colorless", "unknown")
