"""Cursedle probe selection: dedup prior guesses and information-gain probing."""

from __future__ import annotations

import json
from unittest.mock import patch

from cursed_words_solver.cursedle_solver import (
    CursedleAdvice,
    CursedleGuess,
    _guessed_words,
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


def test_information_gain_prefers_splitting_probe() -> None:
    board = _board_6x6(["A"] * 36)
    candidates = [[0, 1, 2, 3], [0, 6, 12, 18], [5, 11, 17, 23]]
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


def test_probe_skips_prior_suggested_word(
    tmp_path,
    monkeypatch,
) -> None:
    suggestion_path = tmp_path / "last_suggestion.json"
    session_path = tmp_path / "cursedle_session.json"
    monkeypatch.setattr("cursed_words_solver.config.LAST_SUGGESTION_PATH", suggestion_path)
    monkeypatch.setattr("cursed_words_solver.config.CURSEDLE_SESSION_PATH", session_path)
    monkeypatch.setattr("cursed_words_solver.cursedle_solver.LAST_SUGGESTION_PATH", suggestion_path)
    monkeypatch.setattr("cursed_words_solver.cursedle_solver.CURSEDLE_SESSION_PATH", session_path)

    board = _word_board()
    tiles_fp = board_fingerprint(board)
    suggestion_path.write_text(
        json.dumps(
            {
                "mode": "cursedle",
                "word": "test",
                "board_fingerprint": f"{tiles_fp}|0",
                "cursedle_prior_words": ["test"],
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
    )
    assert picked is not None
    _path, word = picked
    assert word.lower() == "best"


def test_prior_words_accumulate_on_save(tmp_path, monkeypatch) -> None:
    suggestion_path = tmp_path / "last_suggestion.json"
    session_path = tmp_path / "cursedle_session.json"
    monkeypatch.setattr("cursed_words_solver.config.LAST_SUGGESTION_PATH", suggestion_path)
    monkeypatch.setattr("cursed_words_solver.config.CURSEDLE_SESSION_PATH", session_path)
    monkeypatch.setattr("cursed_words_solver.cursedle_solver.LAST_SUGGESTION_PATH", suggestion_path)
    monkeypatch.setattr("cursed_words_solver.cursedle_solver.CURSEDLE_SESSION_PATH", session_path)

    board = _word_board()
    tiles_fp = board_fingerprint(board)
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
    save_cursedle_suggestion(
        board=board,
        loadout=loadout,
        advice=CursedleAdvice(
            word="best",
            path=[6, 7, 8, 9],
            candidates=2,
            guesses_used=0,
            guesses_remaining=5,
            reason="probe",
            warnings=[],
        ),
        run_state_snapshot=run_state,
    )

    saved = json.loads(suggestion_path.read_text(encoding="utf-8"))
    assert saved["cursedle_prior_words"] == ["test", "best"]
    session = json.loads(session_path.read_text(encoding="utf-8"))
    assert session[tiles_fp]["prior_words"] == ["test", "best"]


def test_prior_words_survive_suggestion_clear(tmp_path, monkeypatch) -> None:
    suggestion_path = tmp_path / "last_suggestion.json"
    session_path = tmp_path / "cursedle_session.json"
    monkeypatch.setattr("cursed_words_solver.config.LAST_SUGGESTION_PATH", suggestion_path)
    monkeypatch.setattr("cursed_words_solver.config.CURSEDLE_SESSION_PATH", session_path)
    monkeypatch.setattr("cursed_words_solver.cursedle_solver.LAST_SUGGESTION_PATH", suggestion_path)
    monkeypatch.setattr("cursed_words_solver.cursedle_solver.CURSEDLE_SESSION_PATH", session_path)

    board = _word_board()
    tiles_fp = board_fingerprint(board)
    session_path.write_text(
        json.dumps({tiles_fp: {"prior_words": ["test"]}}),
        encoding="utf-8",
    )
    assert not suggestion_path.exists()

    dictionary = _FakeDictionary({"test", "best"})
    candidates = [[0, 1, 2, 3], [6, 7, 8, 9]]
    picked = _pick_probe_path(
        board,
        candidates,
        dictionary,
        [],
        tiles_only_fp=tiles_fp,
    )
    assert picked is not None
    _path, word = picked
    assert word.lower() == "best"


def test_guessed_words_raw_path_fallback() -> None:
    board = _word_board()
    dictionary = _FakeDictionary({"best"})
    guesses = [
        CursedleGuess(path=[0, 1, 2, 3], feedback=["grey"] * 4),
    ]
    words = _guessed_words(board, guesses, dictionary)
    assert "test" in words
