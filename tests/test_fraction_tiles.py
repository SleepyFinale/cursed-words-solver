"""Fraction tile parsing, search, and scoring (wiki: Tiles — Fractions)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursed_words_solver.models import Board, CurseType, Tile
from cursed_words_solver.rules.fraction_tiles import format_fraction_parts, format_fraction_text, format_fraction_tile, format_fraction_value, parse_fraction_parts_from_float, parse_fraction_parts_from_text
from cursed_words_solver.search import PathValidator, WordSearcher
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
