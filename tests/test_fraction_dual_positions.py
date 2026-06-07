"""Fraction tiles: dual numerator/denominator position slots in search and validation."""

from __future__ import annotations

from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.rules.fraction_tiles import (
    fraction_position_valid,
    tile_fraction_position_values,
)
from cursed_words_solver.search import (
    PathValidator,
    WordSearcher,
    _interleaved_number_starts,
)


def _letter(r: int, c: int, ch: str) -> Tile:
    return Tile(
        row=r,
        col=c,
        char=ch,
        letter=ch.upper(),
        base_score=1.0,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )


def _number(r: int, c: int, face: int) -> Tile:
    s = str(face)
    return Tile(
        row=r,
        col=c,
        char=s,
        letter=s,
        base_score=float(face),
        color=TileColor.COLORLESS,
        curse=CurseType.NUMBER,
        number_value=face,
    )


def _fraction(r: int, c: int, num: int, den: int) -> Tile:
    return Tile(
        row=r,
        col=c,
        char="?",
        letter="?",
        base_score=float(num + den),
        color=TileColor.COLORLESS,
        curse=CurseType.FRACTION,
        fraction_value=num / den,
        metadata={"fraction_num": num, "fraction_den": den},
    )


def _empty_board() -> Board:
    return Board(
        tiles=[[_letter(r, c, "x") for c in range(5)] for r in range(5)]
    )


def _path_indices(count: int) -> list[int]:
    """Snake path of `count` tiles across the 5×5 grid (4-connected)."""
    rows: list[list[int]] = []
    for r in range(5):
        if r % 2 == 0:
            rows.append([r * 5 + c for c in range(5)])
        else:
            rows.append([r * 5 + c for c in range(4, -1, -1)])
    flat: list[int] = []
    for row in rows:
        flat.extend(row)
    return flat[:count]


def _wordlist(tmp_path: Path, *words: str) -> Path:
    p = tmp_path / "words.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p


def _place_path_tiles(
    board: Board,
    path: list[int],
    *,
    letters: str,
    frac_path_index: int,
    frac: Tile,
    number_path_index: int | None = None,
    number_face: int | None = None,
) -> str:
    """Place letters and special tiles; return the search word string."""
    parts: list[str] = []
    letter_idx = 0
    for i, idx in enumerate(path):
        r, c = divmod(idx, 5)
        if i == frac_path_index:
            board.tiles[r][c] = frac
            parts.append("?")
        elif number_path_index is not None and i == number_path_index:
            board.tiles[r][c] = _number(r, c, number_face or 0)
            parts.append(str(number_face))
        else:
            ch = letters[letter_idx]
            letter_idx += 1
            board.tiles[r][c] = _letter(r, c, ch)
            parts.append(ch)
    return "".join(parts)


def test_tile_fraction_position_values():
    half = _fraction(0, 0, 1, 2)
    assert tile_fraction_position_values(half) == [1, 2]
    three_quarters = _fraction(0, 0, 3, 4)
    assert tile_fraction_position_values(three_quarters) == [3, 4]
    three_fifths = _fraction(0, 0, 3, 5)
    assert tile_fraction_position_values(three_fifths) == [3, 5]


def test_three_quarters_valid_at_both_slots(tmp_path: Path):
    wl = _wordlist(tmp_path, "abcxdefghj", "abcxxefghj")
    d = WordDictionary(wl)
    v = PathValidator(d, min_len=10)
    frac = _fraction(0, 0, 3, 4)
    path = _path_indices(10)

    # Numerator slot: ¾ at tile ordinal 3 (path index 2)
    board_num = _empty_board()
    word_num = _place_path_tiles(
        board_num,
        path,
        letters="abxdefgh",
        frac_path_index=2,
        frac=frac,
        number_path_index=9,
        number_face=10,
    )
    assert word_num == "ab?xdefgh10"
    assert fraction_position_valid(frac, 2, relaxed=False)
    assert v.word_ok(board_num, path, word_num, None)

    # Denominator slot: ¾ at tile ordinal 4 (path index 3)
    board_den = _empty_board()
    word_den = _place_path_tiles(
        board_den,
        path,
        letters="abcxefgh",
        frac_path_index=3,
        frac=frac,
        number_path_index=9,
        number_face=10,
    )
    assert word_den == "abc?xefgh10"
    assert fraction_position_valid(frac, 3, relaxed=False)
    assert v.word_ok(board_den, path, word_den, None)


def test_search_finds_denominator_slot_path(tmp_path: Path):
    """WordSearcher must reach 3/5 at tile ordinal 5 (denominator), not only ordinal 3."""
    wl = _wordlist(tmp_path, "abcdxxe")
    d = WordDictionary(wl)
    board = _empty_board()
    frac = _fraction(0, 0, 3, 5)
    path = _path_indices(7)
    word = _place_path_tiles(
        board,
        path,
        letters="abcdxef",
        frac_path_index=4,
        frac=frac,
    )
    assert word == "abcd?xe"
    v = PathValidator(d, min_len=5)
    assert v.word_ok(board, path, word, None)

    searcher = WordSearcher(dictionary=d, min_len=5, max_len=7, time_budget=3.0)
    results = searcher.find_best_words(board, top_n=5)
    words = {r.word for r in results}
    assert word in words or "abcdxxe" in words


def test_search_finds_ten_tile_denominator_slot(tmp_path: Path):
    """WordSearcher reaches ¾ at tile ordinal 4 on a 10-tile snake path."""
    wl = _wordlist(tmp_path, "abcxxefghi")
    d = WordDictionary(wl)
    board = _empty_board()
    frac = _fraction(0, 0, 3, 4)
    path = _path_indices(10)
    word = _place_path_tiles(
        board,
        path,
        letters="abcxefghi",
        frac_path_index=3,
        frac=frac,
    )
    assert word == "abc?xefghi"
    v = PathValidator(d, min_len=10)
    assert v.word_ok(board, path, word, None)

    searcher = WordSearcher(dictionary=d, min_len=10, max_len=10, time_budget=10.0)
    results = searcher.find_best_words(board, top_n=3)
    assert any(r.word == word for r in results)


def test_bison_style_three_quarters_at_denominator_with_ten(tmp_path: Path):
    """Bison: ¾ at tile ordinal 4 and NUMBER 10 at ordinal 10 validates via PathValidator."""
    wl = _wordlist(tmp_path, "abcxxefghj")
    d = WordDictionary(wl)
    board = _empty_board()
    frac = _fraction(0, 0, 3, 4)
    path = _path_indices(10)
    word = _place_path_tiles(
        board,
        path,
        letters="abcxefgh",
        frac_path_index=3,
        frac=frac,
        number_path_index=9,
        number_face=10,
    )
    assert word == "abc?xefgh10"

    v = PathValidator(d, min_len=10)
    assert fraction_position_valid(frac, 3, relaxed=False)
    assert v.word_ok(board, path, word, None)


def test_interleaved_number_starts_registers_both_fraction_slots():
    board = _empty_board()
    board.tiles[0][0] = _fraction(0, 0, 3, 5)
    board.tiles[0][1] = _number(0, 1, 1)
    starts = _interleaved_number_starts(board)
    assert 0 in starts
    assert starts.count(0) == 1
