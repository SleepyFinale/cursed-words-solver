"""Search must use Up and Up center tile (UpAndUp quest)."""

from __future__ import annotations

import json
from pathlib import Path

from cursed_words_solver.config import resolve_wordlist
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.quest_effects import quest_path_allowed
from cursed_words_solver.search import WordSearcher, search_word_from_path
from cursed_words_solver.solve_context import build_solve_context
from cursed_words_solver.suggestion import f8_should_block_save

_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260615_201534.json"
)
_RENDERS_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260615_211622_renders.json"
)
_POETCRAFT_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260615_215449_poetcraft.json"
)
_JUXTALITTORAL_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260615_231647_juxtalittoral.json"
)
_POETCRAFT_PATH = [8, 2, 7, 6, 11, 16, 22, 17, 12]
_JUXTALITTORAL_PATH = [16, 10, 6, 0, 1, 2, 17, 22, 23, 19, 13, 8, 12]
_RENDERS_PATH = [8, 9, 13, 18, 22, 17, 12]


def _tile(
    idx: int,
    *,
    letter: str = "x",
    curse: CurseType = CurseType.LETTER,
    meta: dict | None = None,
) -> Tile:
    row, col = divmod(idx, 5)
    return Tile(
        row=row,
        col=col,
        char=letter,
        letter=letter,
        base_score=1,
        color=TileColor.COLORLESS,
        curse=curse,
        metadata=meta or {},
    )


def _board_from_tiles(tiles: dict[int, Tile]) -> Board:
    grid: list[list[Tile]] = []
    for r in range(5):
        row: list[Tile] = []
        for c in range(5):
            idx = r * 5 + c
            row.append(tiles.get(idx, _tile(idx)))
        grid.append(row)
    return Board(tiles=grid, money=0)


def _simple_up_and_up_run_state() -> dict:
    """Row 2 spells CAT/S; row 0 spells CAT without the center column."""
    tiles = []
    for r in range(5):
        for c in range(5):
            entry = {
                "row": r,
                "col": c,
                "letter": "x",
                "char": "x",
                "color": "colorless",
                "curse": "letter",
                "active": True,
            }
            if r == 2:
                for col, ch in enumerate("cates"):
                    if c == col:
                        entry["letter"] = ch
                        entry["char"] = ch
                        if col == 2:
                            entry["is_up_and_up_center"] = True
            if r == 0 and c < 3:
                ch = "cat"[c]
                entry["letter"] = ch
                entry["char"] = ch
            tiles.append(entry)
    return {
        "character": "Test",
        "money": 0,
        "challenge_game_class": "UpAndUp",
        "challenge_name": "Up and Up",
        "stickers": [],
        "stamps": [],
        "extras": {
            "challenge_game_class": "UpAndUp",
            "up_and_up_center_index": "12",
        },
        "board": {
            "rows": 5,
            "cols": 5,
            "row_order": "top_first",
            "tiles": tiles,
        },
    }


def _fixture_run_state() -> dict:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return data["run_state_snapshot"]


def _renders_run_state() -> dict:
    return json.loads(_RENDERS_FIXTURE.read_text(encoding="utf-8"))


def _poetcraft_run_state() -> dict:
    data = json.loads(_POETCRAFT_FIXTURE.read_text(encoding="utf-8"))
    return data["run_state_snapshot"]


def _juxtalittoral_run_state() -> dict:
    data = json.loads(_JUXTALITTORAL_FIXTURE.read_text(encoding="utf-8"))
    return data["run_state_snapshot"]


def test_accept_path_bypass_rejects_up_and_up_without_center() -> None:
    data = _simple_up_and_up_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    searcher = WordSearcher(dictionary=dictionary, min_len=3)
    searcher.validator.quest_loadout = loadout
    path = [0, 1, 2]
    accepted, _ = searcher._accept_path_for_search(
        board,
        path,
        "cat",
        loadout,
        0,
        trie_compatible=True,
        prefix_cursor=dictionary.step_token_cursor(
            dictionary.root_cursor(), "cat"
        ),
    )
    assert not accepted
    assert not quest_path_allowed(board, path, loadout=loadout)


def test_partial_dict_resolve_extends_to_center() -> None:
    data = _fixture_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    searcher = WordSearcher(dictionary=dictionary, min_len=1)
    searcher.validator.quest_loadout = loadout
    flags = build_solve_context(loadout, {}).search_flags
    partial = [2, 1, 6]
    full = [2, 1, 6, 12, 18, 23]
    partial_word = search_word_from_path(board, partial, flags=flags)
    full_word = search_word_from_path(board, full, flags=flags)
    partial_ok, _ = searcher._accept_path_for_search(
        board, partial, partial_word, loadout, flags
    )
    full_ok, _ = searcher._accept_path_for_search(
        board, full, full_word, loadout, flags
    )
    assert not partial_ok
    assert full_ok
    assert 12 in full


def test_find_best_words_all_results_include_center() -> None:
    data = _simple_up_and_up_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    searcher = WordSearcher(
        dictionary=dictionary, min_len=3, time_budget=8, search_workers=1
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=5)
    assert results, "expected at least one word on simple Up and Up board"
    for result in results:
        assert 12 in result.path, (
            f"{result.word} path {result.path} omits center tile 12"
        )


def test_find_best_words_fixture_includes_center() -> None:
    data = _fixture_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    searcher = WordSearcher(
        dictionary=dictionary, min_len=1, time_budget=20, search_workers=1
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=5)
    assert results
    for result in results:
        assert 12 in result.path


def test_f8_should_block_save_up_and_up() -> None:
    data = _simple_up_and_up_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        board=board,
        path=[0, 1, 2],
        loadout=loadout,
    )
    assert blocked
    assert reason == "up_and_up_center_not_in_path"

    allowed, reason_ok = f8_should_block_save(
        gather_succeeded=True,
        board=board,
        path=[10, 11, 12],
        loadout=loadout,
    )
    assert not allowed
    assert reason_ok is None


def test_renders_path_accepted() -> None:
    data = _renders_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    searcher = WordSearcher(dictionary=dictionary, min_len=1)
    searcher.validator.quest_loadout = loadout
    flags = build_solve_context(loadout, {}).search_flags
    path = _RENDERS_PATH
    search_word = search_word_from_path(board, path, flags=flags)
    accepted, _ = searcher._accept_path_for_search(
        board, path, search_word, loadout, flags
    )
    assert accepted
    assert 12 in path
    assert quest_path_allowed(board, path, loadout=loadout)


def test_find_best_words_renders_board_includes_center() -> None:
    data = _renders_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=1,
        max_len=25,
        time_budget=20.0,
        search_workers=1,
        wordlist_path=resolve_wordlist("game"),
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=3)
    assert results, "expected center-using word on renders board"
    for result in results:
        assert 12 in result.path


def test_find_best_words_renders_board_parallel_includes_center() -> None:
    data = _renders_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    wl = resolve_wordlist("game")
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=1,
        max_len=25,
        time_budget=25.0,
        search_workers=8,
        wordlist_path=wl,
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=3)
    assert results, "expected center-using word with parallel workers"
    for result in results:
        assert 12 in result.path


def test_poetcraft_path_accepted() -> None:
    data = _poetcraft_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    searcher = WordSearcher(dictionary=dictionary, min_len=1)
    searcher.validator.quest_loadout = loadout
    flags = build_solve_context(loadout, {}).search_flags
    path = _POETCRAFT_PATH
    search_word = search_word_from_path(board, path, flags=flags)
    accepted, _ = searcher._accept_path_for_search(
        board, path, search_word, loadout, flags
    )
    assert accepted
    assert 12 in path
    assert quest_path_allowed(board, path, loadout=loadout)


def test_find_best_words_poetcraft_includes_center() -> None:
    data = _poetcraft_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    wl = resolve_wordlist("game")
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=1,
        max_len=25,
        time_budget=45.0,
        search_workers=1,
        wordlist_path=wl,
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=3)
    assert results, "expected center-using word on poetcraft board"
    for result in results:
        assert 12 in result.path


def test_juxtalittoral_path_accepted() -> None:
    data = _juxtalittoral_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    searcher = WordSearcher(dictionary=dictionary, min_len=1)
    searcher.validator.quest_loadout = loadout
    flags = build_solve_context(loadout, {}).search_flags
    path = _JUXTALITTORAL_PATH
    search_word = search_word_from_path(board, path, flags=flags)
    accepted, _ = searcher._accept_path_for_search(
        board, path, search_word, loadout, flags
    )
    assert accepted
    assert 12 in path
    assert quest_path_allowed(board, path, loadout=loadout)


def test_find_best_words_juxtalittoral_includes_center() -> None:
    data = _juxtalittoral_run_state()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    wl = resolve_wordlist("game")
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=1,
        max_len=25,
        time_budget=60.0,
        search_workers=1,
        wordlist_path=wl,
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=3)
    assert results, "expected center-using word on juxtalittoral board"
    for result in results:
        assert 12 in result.path
