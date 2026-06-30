"""Cursedle probe selection: dedup prior guesses and information-gain probing."""

from __future__ import annotations

import json
from unittest.mock import patch

from cursed_words_solver.cursedle_solver import (
    CursedleAdvice,
    CursedleGuess,
    CURSEDLE_SOLUTION_COMMIT_THRESHOLD,
    _guessed_words,
    _is_near_duplicate_word,
    _pick_probe_path,
    _probe_entropy_score,
    run_cursedle_solver,
    save_cursedle_suggestion,
)
from cursed_words_solver.fingerprints import board_fingerprint
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor


class _FakeDictionary:
    def __init__(self, words: set[str]) -> None:
        self._words = {w.lower() for w in words}

    def contains(self, word: str) -> bool:
        return word.lower() in self._words

    def has_prefix(self, prefix: str) -> bool:
        stem = prefix.lower()
        return any(word.startswith(stem) for word in self._words)

    def is_valid_word(self, word: str, min_len: int = 3) -> bool:
        key = word.lower()
        return len(key) >= min_len and key in self._words


def _tile(row: int, col: int, letter: str) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=letter.lower(),
        letter=letter,
        base_score=1.0,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )


def _board_6x6(letters: list[str]) -> Board:
    tiles = [
        [_tile(r, c, letters[r * 6 + c]) for c in range(6)]
        for r in range(6)
    ]
    return Board(tiles=tiles, rows=6, cols=6)


def _word_board() -> Board:
    # Row0 TESTAA, row1 BESTAA — paths [0,1,2,3]=test and [6,7,8,9]=best
    letters = list("TESTAA" + "BESTAA" + "AAAAAA" + "AAAAAA" + "AAAAAA" + "AAAAAA")
    return _board_6x6(letters)


def _cursedle_extras(
    *,
    guesses: list[dict] | None = None,
    guesses_used: int = 0,
    guesses_remaining: int = 5,
) -> dict:
    return {
        "encounter_mode": "cursedle",
        "cursedle_guesses": json.dumps(guesses or []),
        "cursedle_guesses_used": str(guesses_used),
        "cursedle_guesses_remaining": str(guesses_remaining),
    }


def test_probe_skips_prior_guess_path() -> None:
    board = _word_board()
    dictionary = _FakeDictionary({"test", "best"})
    guess_path = [0, 1, 2, 3]
    guesses = [
        CursedleGuess(path=guess_path, feedback=["grey"] * len(guess_path)),
    ]
    candidates = [[0, 1, 2, 3], [6, 7, 8, 9]]
    picked = _pick_probe_path(board, candidates, dictionary, guesses)
    assert picked is not None
    path, _word = picked
    assert tuple(path) != tuple(guess_path)


def test_probe_skips_prior_guess_word() -> None:
    board = _word_board()
    dictionary = _FakeDictionary({"test", "best"})
    guess_path = [0, 1, 2, 3]
    guesses = [
        CursedleGuess(path=guess_path, feedback=["grey"] * len(guess_path)),
    ]
    candidates = [[0, 1, 2, 3], [6, 7, 8, 9]]
    picked = _pick_probe_path(board, candidates, dictionary, guesses)
    assert picked is not None
    _path, word = picked
    assert word.lower() == "best"


@patch("cursed_words_solver.cursedle_solver._enumerate_dictionary_probe_paths")
def test_information_gain_prefers_splitting_probe(mock_enum) -> None:
    board = _board_6x6(["A"] * 36)
    candidates = [[0, 1, 2, 3], [0, 6, 12, 18], [5, 11, 17, 23]]
    mock_enum.return_value = [
        ("aaaa", [0, 1, 2, 3]),
        ("aaaa", [0, 6, 12, 18]),
        ("aaaa", [5, 11, 17, 23]),
    ]
    scored = [
        (_probe_entropy_score(board, path, candidates), tuple(path))
        for path in candidates
    ]
    best_entropy = max(score for score, _ in scored)
    worst_entropy = min(score for score, _ in scored)
    assert best_entropy >= worst_entropy

    dictionary = _FakeDictionary({"aaaa"})
    path, _word = _pick_probe_path(board, candidates, dictionary, []) or (None, "")
    assert path is not None
    picked_entropy = _probe_entropy_score(board, path, candidates)
    assert picked_entropy >= worst_entropy


@patch("cursed_words_solver.cursedle_solver.filter_candidates")
def test_last_guess_picks_solution(mock_filter) -> None:
    mock_filter.return_value = [[0, 1, 2, 3], [6, 7, 8, 9]]
    board = _word_board()
    dictionary = _FakeDictionary({"test", "best"})
    loadout = Loadout(
        extras=_cursedle_extras(
            guesses_used=4,
            guesses_remaining=1,
        )
    )
    advice = run_cursedle_solver(board, loadout, dictionary)
    assert advice.word
    assert "Final guess" in advice.reason
    assert "Probe" not in advice.reason


def test_pick_probe_excludes_guess_objects() -> None:
    board = _word_board()
    dictionary = _FakeDictionary({"test", "best"})
    guess_path = [0, 1, 2, 3]
    guesses = [
        CursedleGuess(
            path=guess_path,
            feedback=["grey"] * len(guess_path),
        )
    ]
    candidates = [[0, 1, 2, 3], [6, 7, 8, 9]]
    picked = _pick_probe_path(board, candidates, dictionary, guesses)
    assert picked is not None
    path, word = picked
    assert tuple(path) != tuple(guess_path)
    assert word.lower() == "best"


def test_probe_skips_inflight_suggestion_word(
    tmp_path,
    monkeypatch,
) -> None:
    suggestion_path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr("cursed_words_solver.config.LAST_SUGGESTION_PATH", suggestion_path)
    monkeypatch.setattr("cursed_words_solver.cursedle_solver.LAST_SUGGESTION_PATH", suggestion_path)

    board = _word_board()
    tiles_fp = board_fingerprint(board)
    suggestion_path.write_text(
        json.dumps(
            {
                "mode": "cursedle",
                "word": "test",
                "board_fingerprint": f"{tiles_fp}|0",
                "run_state_snapshot": {
                    "extras": _cursedle_extras(guesses_used=0),
                },
            }
        ),
        encoding="utf-8",
    )
    dictionary = _FakeDictionary({"test", "best"})
    candidates = [[0, 1, 2, 3], [6, 7, 8, 9]]
    picked = _pick_probe_path(
        board,
        candidates,
        dictionary,
        [],
        tiles_only_fp=tiles_fp,
        guesses_used=0,
    )
    assert picked is not None
    _path, word = picked
    assert word.lower() == "best"


def test_save_cursedle_suggestion_no_prior_words_list(tmp_path, monkeypatch) -> None:
    suggestion_path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr("cursed_words_solver.config.LAST_SUGGESTION_PATH", suggestion_path)
    monkeypatch.setattr("cursed_words_solver.cursedle_solver.LAST_SUGGESTION_PATH", suggestion_path)

    board = _word_board()
    loadout = Loadout(extras=_cursedle_extras())
    run_state = {
        "character": "",
        "money": 0,
        "stickers": [],
        "stamps": [],
        "boss": {},
        "board": {"money": board.money, "tiles": []},
        "extras": loadout.extras,
    }

    save_cursedle_suggestion(
        board=board,
        loadout=loadout,
        advice=CursedleAdvice(
            word="test",
            path=[0, 1, 2, 3],
            candidates=2,
            guesses_used=0,
            guesses_remaining=5,
            reason="probe",
            warnings=[],
        ),
        run_state_snapshot=run_state,
    )

    saved = json.loads(suggestion_path.read_text(encoding="utf-8"))
    assert "cursedle_prior_words" not in saved
    assert saved["word"] == "test"


def test_guessed_words_raw_path_fallback() -> None:
    board = _word_board()
    dictionary = _FakeDictionary({"best"})
    guesses = [
        CursedleGuess(
            path=[30, 31, 32, 33],
            feedback=["grey"] * 4,
        ),
    ]
    words = _guessed_words(board, guesses, dictionary)
    assert "test" in words


def test_near_duplicate_word_rejects_prefix() -> None:
    assert _is_near_duplicate_word("foyer", {"foyers"})
    assert _is_near_duplicate_word("foyers", {"foyer"})
    assert _is_near_duplicate_word("hayey", {"hayers"})
    assert not _is_near_duplicate_word("best", {"test"})


@patch("cursed_words_solver.cursedle_solver._enumerate_dictionary_probe_paths")
def test_probe_rejects_foyer_after_foyers_guessed(mock_enum) -> None:
    foyers_storage = [34, 29, 23, 28, 33, 26]
    foyers_melmod = [4, 11, 17, 10, 3, 8]
    letters = ["A"] * 36
    for idx, ch in zip(foyers_storage, "FOYERS"):
        row, col = divmod(idx, 6)
        letters[row * 6 + col] = ch
    letters[6:11] = list("FOYER")
    board = _board_6x6(letters)
    dictionary = _FakeDictionary({"foyers", "foyer", "zzzzzz"})
    guesses = [
        CursedleGuess(
            path=foyers_melmod,
            feedback=["grey"] * len(foyers_melmod),
        ),
    ]
    candidates = [
        foyers_storage,
        foyers_storage[:5],
        [12, 13, 14, 15, 16, 17],
    ]
    mock_enum.return_value = [
        ("foyers", foyers_storage),
        ("foyer", foyers_storage[:5]),
        ("zzzzzz", [12, 13, 14, 15, 16, 17]),
    ]
    picked = _pick_probe_path(board, candidates, dictionary, guesses)
    assert picked is not None
    _path, word = picked
    assert word.lower() == "zzzzzz"


@patch("cursed_words_solver.cursedle_solver._enumerate_dictionary_probe_paths")
@patch("cursed_words_solver.cursedle_solver.filter_candidates")
@patch("cursed_words_solver.cursedle_solver._narrow_candidates_to_dictionary")
def test_single_length_many_candidates_still_probes(
    mock_narrow, mock_filter, mock_enum
) -> None:
    length_five = [[i, i + 1, i + 2, i + 3, i + 4] for i in range(0, 50, 6)]
    mock_filter.return_value = length_five
    mock_narrow.side_effect = lambda _board, candidates, _dictionary: candidates
    mock_enum.return_value = [("aaaaa", [0, 1, 2, 3, 4]), ("aaa", [6, 7, 8])]
    board = _board_6x6(["A"] * 36)
    dictionary = _FakeDictionary({"aaaaa", "aaaa"})
    loadout = Loadout(
        extras=_cursedle_extras(
            guesses_used=2,
            guesses_remaining=3,
        )
    )
    advice = run_cursedle_solver(board, loadout, dictionary)
    assert advice.word
    assert "Probe" in advice.reason
    assert len(length_five) > CURSEDLE_SOLUTION_COMMIT_THRESHOLD


@patch("cursed_words_solver.cursedle_solver._path_dictionary_word_any_resolution")
@patch("cursed_words_solver.cursedle_solver.filter_candidates")
def test_final_guess_exploratory_when_no_dict_valid_paths(
    mock_filter,
    mock_dict_word,
) -> None:
    mock_filter.return_value = [[0, 1, 2, 3], [6, 7, 8, 9]]
    mock_dict_word.return_value = None
    board = _word_board()
    dictionary = _FakeDictionary({"test", "best"})
    loadout = Loadout(
        extras=_cursedle_extras(
            guesses_used=4,
            guesses_remaining=1,
        )
    )
    advice = run_cursedle_solver(board, loadout, dictionary)
    assert advice.word
    assert advice.path
    assert advice.candidates == 0
    assert "No consistent solution candidates" in advice.reason


@patch("cursed_words_solver.cursedle_solver._enumerate_dictionary_probe_paths")
def test_probe_prefers_untested_tiles(mock_enum) -> None:
    board = _board_6x6(
        list("TESTAA" + "BESTAA" + "ZZZZZZ" + "ZZZZZZ" + "ZZZZZZ" + "ZZZZZZ")
    )
    mock_enum.return_value = [
        ("test", [0, 1, 2, 3]),
        ("best", [6, 7, 8, 9]),
        ("zzzzzz", [12, 13, 14, 15, 16, 17]),
    ]
    dictionary = _FakeDictionary({"test", "best", "zzzzzz"})
    tested_storage = [0, 1, 2, 3]
    guesses = [
        CursedleGuess(
            path=[30, 31, 32, 33],
            feedback=["grey"] * 4,
        ),
    ]
    candidates = [[0, 1, 2, 3], [6, 7, 8, 9], [12, 13, 14, 15, 16, 17]]
    picked = _pick_probe_path(board, candidates, dictionary, guesses)
    assert picked is not None
    path, _word = picked
    overlap = len(set(path) & set(tested_storage)) / len(path)
    assert overlap <= 0.5
