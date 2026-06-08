"""Fraction tile parsing, search, and scoring (wiki: Tiles — Fractions)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.fraction_tiles import (
    format_fraction_parts,
    format_fraction_text,
    format_fraction_tile,
    format_fraction_value,
    fraction_parts,
    fraction_position_valid,
    parse_fraction_parts_from_float,
    parse_fraction_parts_from_text,
)
from cursed_words_solver.rules.scoring_conditions import (
    is_number_like_tile,
    number_sum_on_path,
    tile_numeric_value,
)
from cursed_words_solver.search import (
    PathValidator,
    WordSearcher,
    _legal_word_start_indices,
    resolve_letter,
)
from cursed_words_solver.dictionary import WordDictionary


def _tile(
    row: int,
    col: int,
    letter: str,
    base: float,
    *,
    curse: CurseType = CurseType.LETTER,
    char: str | None = None,
    fraction_value: float | None = None,
    number_value: int | None = None,
    metadata: dict | None = None,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=char or letter,
        letter=letter,
        base_score=base,
        curse=curse,
        fraction_value=fraction_value,
        number_value=number_value,
        metadata=dict(metadata or {}),
    )


def test_parse_fraction_parts_text():
    assert parse_fraction_parts_from_text("3/5") == (3, 5)
    assert parse_fraction_parts_from_text("⅗") == (3, 5)
    assert parse_fraction_parts_from_text("⅒") == (1, 10)
    assert parse_fraction_parts_from_text("0.1") == (1, 10)
    assert parse_fraction_parts_from_float(0.1666667) == (1, 6)


def test_format_fraction_display_vulgar_first():
    assert format_fraction_value(0.8) == "⅘"
    assert format_fraction_parts(1, 7) == "⅐"
    assert format_fraction_text("0.6666667") == "⅔"
    assert format_fraction_text("4/5") == "⅘"


def test_format_fraction_display_slash_fallback():
    assert format_fraction_parts(2, 9) == "2/9"


def test_format_fraction_tile_prefers_char_glyph():
    tile = _tile(
        0,
        0,
        "0.8",
        9,
        curse=CurseType.FRACTION,
        char="⅘",
        fraction_value=0.8,
        metadata={"fraction_num": 4, "fraction_den": 5},
    )
    assert format_fraction_tile(tile) == "⅘"


def test_format_fraction_tile_from_decimal_letter():
    tile = _tile(
        0,
        0,
        "0.4",
        7,
        curse=CurseType.FRACTION,
        char="⅖",
        fraction_value=0.4,
    )
    assert format_fraction_tile(tile) == "⅖"


def test_fraction_position_valid_3_5():
    tile = _tile(
        0,
        0,
        "?",
        8,
        curse=CurseType.FRACTION,
        char="⅗",
        fraction_value=0.6,
        metadata={"fraction_num": 3, "fraction_den": 5},
    )
    assert fraction_position_valid(tile, 2, relaxed=False)  # 1-based pos 3
    assert fraction_position_valid(tile, 4, relaxed=False)  # 1-based pos 5
    assert not fraction_position_valid(tile, 1, relaxed=False)  # 1-based pos 2
    assert not fraction_position_valid(tile, 0, relaxed=False)
    assert not fraction_position_valid(tile, 3, relaxed=False)


def test_tile_numeric_value_uses_fraction_float():
    tile = _tile(
        0,
        0,
        "?",
        8,
        curse=CurseType.FRACTION,
        char="3/5",
        fraction_value=0.6,
        metadata={"fraction_num": 3, "fraction_den": 5},
    )
    assert tile_numeric_value(tile) == pytest.approx(0.6)


def test_number_sum_includes_fraction_numeric_value():
    board = Board(
        tiles=[[_tile(0, c, "x", 1) for c in range(5)] for _ in range(5)],
        money=0,
    )
    board.tiles[0][0] = _tile(
        0, 0, "1", 1, curse=CurseType.NUMBER, number_value=1
    )
    board.tiles[0][1] = _tile(
        0,
        1,
        "?",
        8,
        curse=CurseType.FRACTION,
        char="3/5",
        fraction_value=0.6,
        metadata={"fraction_num": 3, "fraction_den": 5},
    )
    board.tiles[0][2] = _tile(
        0, 2, "4", 4, curse=CurseType.NUMBER, number_value=4
    )
    path = [0, 1, 2]
    assert number_sum_on_path(board, path) == pytest.approx(5.6)


def test_resolve_letter_fraction_is_wildcard():
    tile = _tile(0, 0, "0.6", 8, curse=CurseType.FRACTION, fraction_value=0.6)
    assert resolve_letter(tile, 0) == "?"


def test_fraction_word_via_path_validator(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("ace\n")
    d = WordDictionary(wl)
    board = Board(
        tiles=[[_tile(0, c, "x", 1) for c in range(5)] for _ in range(5)],
        money=0,
    )
    board.tiles[0][0] = _tile(0, 0, "A", 1)
    board.tiles[0][1] = _tile(0, 1, "C", 3)
    board.tiles[0][2] = _tile(
        0,
        2,
        "?",
        8,
        curse=CurseType.FRACTION,
        char="3/5",
        fraction_value=0.6,
        metadata={"fraction_num": 3, "fraction_den": 5},
    )
    path = [0, 1, 2]
    v = PathValidator(d, min_len=3)
    assert v.word_ok(board, path, "ac?", None)


def test_search_finds_word_through_fraction(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("ace\n")
    d = WordDictionary(wl)
    board = Board(
        tiles=[[_tile(0, c, "x", 1) for c in range(5)] for _ in range(5)],
        money=0,
    )
    board.tiles[0][0] = _tile(0, 0, "A", 1)
    board.tiles[0][1] = _tile(0, 1, "C", 3)
    board.tiles[0][2] = _tile(
        0,
        2,
        "?",
        8,
        curse=CurseType.FRACTION,
        char="3/5",
        fraction_value=0.6,
        metadata={"fraction_num": 3, "fraction_den": 5},
    )
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=2.0)
    results = searcher.find_best_words(board, top_n=3)
    words = {r.word for r in results}
    assert "ace" in words or "ac?" in words


def test_number_tile_multiply_includes_fraction():
    board = Board(
        tiles=[[_tile(0, c, "x", 1) for c in range(5)] for _ in range(5)],
        money=0,
    )
    board.tiles[0][0] = _tile(
        0,
        0,
        "?",
        8,
        curse=CurseType.FRACTION,
        char="3/5",
        fraction_value=0.6,
        metadata={"fraction_num": 3, "fraction_den": 5},
    )
    assert is_number_like_tile(board.tiles[0][0])


def test_brain_number_sum_includes_fraction_value():
    board = Board(
        tiles=[[_tile(0, c, "x", 1) for c in range(5)] for _ in range(5)],
        money=0,
    )
    board.tiles[0][0] = _tile(
        0, 0, "4", 4, curse=CurseType.NUMBER, number_value=4
    )
    board.tiles[0][1] = _tile(
        0,
        1,
        "?",
        8,
        curse=CurseType.FRACTION,
        char="3/5",
        fraction_value=0.6,
        metadata={"fraction_num": 3, "fraction_den": 5},
    )
    board.tiles[0][2] = _tile(
        0, 2, "4", 4, curse=CurseType.NUMBER, number_value=4
    )
    path = [0, 1, 2]
    loadout = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=1, kind="sticker")]
    )
    score, bd = ScoringPipeline().score(board, path, "4?4", loadout)
    assert number_sum_on_path(board, path) == pytest.approx(8.6)
    effects = " ".join(bd.get("pipeline", {}).get("effects", []) or [])
    assert "8.6" in effects or "≥ 7" in effects
    assert score >= 12.0


def test_mixed_digit_fraction_word_valid(tmp_path):
    """Regression: 1?245fe uses _number_word_valid; 3/5 fraction is not at num/den slots."""
    from cursed_words_solver.config import GAME_WORDLIST_PATH
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
    from tests.helpers.boards import _board_1_fraction_245fe_fixture

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    board = _board_1_fraction_245fe_fixture()
    path = [9, 13, 17, 21, 22, 16, 10]
    word = "1?245fe"
    loadout = Loadout(
        stickers=[LoadoutItem(id="test_tube", name="Test Tube", level=1, kind="sticker")]
    )
    flags = stamp_search_flags(loadout)
    d = WordDictionary(GAME_WORDLIST_PATH)
    v = PathValidator(d, min_len=3)

    assert not v._wildcard_valid(word)
    assert not v._number_word_valid(board, path, word, flags)
    assert not v.word_ok(board, path, word, flags)


def test_three_eighths_cannot_start_word():
    """⅜ (3/8) at path index 0 is illegal; digits elsewhere must not relax that."""
    board = Board(
        tiles=[[_tile(0, c, "x", 1) for c in range(5)] for _ in range(5)],
        money=0,
    )
    frac = _tile(
        0,
        0,
        "?",
        11,
        curse=CurseType.FRACTION,
        char="⅜",
        fraction_value=3 / 8,
        metadata={"fraction_num": 3, "fraction_den": 8},
    )
    board.tiles[0][0] = frac
    board.tiles[0][1] = _tile(0, 1, "A", 1)
    board.tiles[0][2] = _tile(0, 2, "6", 6, curse=CurseType.NUMBER, number_value=6)
    path = [0, 1, 2]
    wl = Path(__file__).resolve().parent / "_tmp_frac_words.txt"
    try:
        wl.write_text("aa6\n", encoding="utf-8")
        v = PathValidator(WordDictionary(wl), min_len=3)
        assert not v.word_ok(board, path, "?a6", None)
    finally:
        wl.unlink(missing_ok=True)


def test_legal_word_start_indices_fraction_slots():
    board = Board(
        tiles=[[_tile(0, c, "x", 1) for c in range(5)] for _ in range(5)],
        money=0,
    )
    three_eighths = _tile(
        0,
        0,
        "?",
        11,
        curse=CurseType.FRACTION,
        char="⅜",
        fraction_value=3 / 8,
        metadata={"fraction_num": 3, "fraction_den": 8},
    )
    one_eighth = _tile(
        0,
        1,
        "?",
        9,
        curse=CurseType.FRACTION,
        char="⅛",
        fraction_value=0.125,
        metadata={"fraction_num": 1, "fraction_den": 8},
    )
    board.tiles[0][0] = three_eighths
    board.tiles[0][1] = one_eighth
    starts = _legal_word_start_indices(board)
    assert 0 not in starts
    assert 1 in starts


def test_fraction_parts_from_melmod_tenth_glyph():
    tile = _tile(
        0,
        0,
        "?",
        11,
        curse=CurseType.FRACTION,
        char="⅒",
        fraction_value=0.1,
    )
    assert fraction_parts(tile) == (1, 10)
    assert not fraction_position_valid(tile, 1, relaxed=False)  # 1-based pos 2
    assert fraction_position_valid(tile, 0, relaxed=False)  # 1-based pos 1


def test_invalid_trovers_path_rejected(tmp_path):
    """Regression: ??ov??? path with ⅒ at illegal positions must not validate."""
    import json
    from pathlib import Path

    from cursed_words_solver.config import GAME_WORDLIST_PATH
    from cursed_words_solver.loadout import parse_board_from_run_state

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    fixture = Path(__file__).resolve().parent / "fixtures" / "fraction_ov_run_state.json"
    run_state = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(run_state)
    assert board is not None

    path = [18, 23, 17, 11, 7, 6, 10]
    word = "??ov???"
    d = WordDictionary(GAME_WORDLIST_PATH)
    v = PathValidator(d, min_len=3)

    assert not v.word_ok(board, path, word, None)
