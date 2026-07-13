"""Cursedle Test Tube: NUMBER/fraction wildcards and item letter hints."""

from __future__ import annotations

import json
import re
from pathlib import Path

from cursed_words_solver.cursedle_solver import (
    _narrow_candidates_to_dictionary,
    _path_dictionary_word_any_resolution,
    _pick_solution_path,
    filter_candidates,
    parse_cursedle_guesses,
    run_cursedle_solver,
)
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "cursedle" / "20260712_test_tube.json"
)

VEINS_PATH = [11, 10, 9, 8, 7]
VACANT_PATH = [11, 10, 9, 8, 7, 6]


class _FakeDictionary:
    def __init__(self, words: set[str]) -> None:
        self._words = {w.lower() for w in words}

    def contains(self, word: str) -> bool:
        return word.lower() in self._words

    def enumerate_pattern_matches(
        self,
        pattern: str,
        *,
        limit: int | None = None,
        deadline_check=None,
    ) -> list[str]:
        if not pattern:
            return []
        rx = re.compile("^" + re.escape(pattern).replace(r"\?", ".") + "$")
        out: list[str] = []
        for word in sorted(self._words):
            if rx.match(word):
                out.append(word)
                if limit is not None and len(out) >= limit:
                    break
        return out


def _letter_tile(row: int, col: int, letter: str) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=letter.lower(),
        letter=letter,
        base_score=1.0,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )


def _number_tile(row: int, col: int, value: int) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=str(value),
        letter=str(value),
        base_score=float(value),
        color=TileColor.COLORLESS,
        curse=CurseType.NUMBER,
        number_value=value,
    )


def _fraction_tile(row: int, col: int, glyph: str = "⅔") -> Tile:
    return Tile(
        row=row,
        col=col,
        char=glyph,
        letter=glyph,
        base_score=0.0,
        color=TileColor.COLORLESS,
        curse=CurseType.FRACTION,
        fraction_value=2.0 / 3.0,
    )


def _test_tube_item_tile(row: int, col: int, letter: str) -> Tile:
    return Tile(
        row=row,
        col=col,
        char="🧪",
        letter=letter,
        base_score=0.0,
        color=TileColor.COLORLESS,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "test_tube", "scattered_item_level": 1},
    )


def _blank_board_with(*placed: Tile) -> Board:
    tiles: list[list[Tile]] = [
        [_letter_tile(r, c, "A") for c in range(6)] for r in range(6)
    ]
    for tile in placed:
        tiles[tile.row][tile.col] = tile
    return Board(tiles=tiles, rows=6, cols=6)


def test_number_at_matching_position_spells_dictionary_word() -> None:
    """NUMBER value matching 1-based path index is a letter wildcard."""
    board = _blank_board_with(
        _letter_tile(0, 0, "C"),
        _number_tile(0, 1, 2),
        _letter_tile(0, 2, "T"),
    )
    dictionary = _FakeDictionary({"cat"})
    word = _path_dictionary_word_any_resolution(board, [0, 1, 2], dictionary)
    assert word == "cat"


def test_number_at_wrong_position_does_not_resolve() -> None:
    """NUMBER that fails IsNumericWildcard stays a digit and cannot match."""
    board = _blank_board_with(
        _number_tile(0, 0, 2),
        _letter_tile(0, 1, "A"),
        _letter_tile(0, 2, "T"),
    )
    dictionary = _FakeDictionary({"cat", "bat", "hat"})
    word = _path_dictionary_word_any_resolution(board, [0, 1, 2], dictionary)
    assert word is None


def test_test_tube_on_path_allows_number_plus_minus_one() -> None:
    """Scattered Test Tube on the path enables ±1 number positions."""
    board = _blank_board_with(
        _test_tube_item_tile(0, 0, "C"),
        _number_tile(0, 1, 3),
        _letter_tile(0, 2, "T"),
    )
    dictionary = _FakeDictionary({"cat"})
    word = _path_dictionary_word_any_resolution(board, [0, 1, 2], dictionary)
    assert word == "cat"

    board_no_tube = _blank_board_with(
        _letter_tile(0, 0, "C"),
        _number_tile(0, 1, 3),
        _letter_tile(0, 2, "T"),
    )
    assert (
        _path_dictionary_word_any_resolution(board_no_tube, [0, 1, 2], dictionary)
        is None
    )


def test_emoji_item_letter_does_not_constrain_pattern() -> None:
    """ScatteredItem emoji is always a wildcard (game IsWildcard) — ignore letter field."""
    board = _blank_board_with(
        _letter_tile(1, 5, "V"),
        _fraction_tile(1, 4),
        _test_tube_item_tile(1, 3, "I"),
        _number_tile(1, 2, 5),
        _number_tile(1, 1, 5),
        _letter_tile(1, 0, "T"),
    )
    dictionary = _FakeDictionary({"veins", "vacant", "vails", "vail"})
    assert _path_dictionary_word_any_resolution(board, VEINS_PATH, dictionary) in {
        "veins",
        "vails",
    }
    # Vacant can spell with emoji wildcard, but ranking must not prefer it.
    assert _path_dictionary_word_any_resolution(board, VACANT_PATH, dictionary) == "vacant"


def test_alpha_item_face_letter_hint_is_hard_constraint() -> None:
    """Alphabetic item faces fix a letter; no unconstrained pattern fallback."""
    board = _blank_board_with(
        _letter_tile(0, 0, "C"),
        Tile(
            row=0,
            col=1,
            char="a",
            letter="A",
            base_score=0.0,
            color=TileColor.COLORLESS,
            curse=CurseType.ITEM,
            metadata={"scattered_item_id": "card_shark"},
        ),
        _letter_tile(0, 2, "T"),
    )
    dictionary = _FakeDictionary({"cat", "cot"})
    assert _path_dictionary_word_any_resolution(board, [0, 1, 2], dictionary) == "cat"


def test_pick_solution_path_drops_letter_suffix_extension() -> None:
    """VEINS→VACANT via plain LETTER T must lose to the theme-tile path."""
    board = _blank_board_with(
        _letter_tile(1, 5, "V"),
        _fraction_tile(1, 4),
        _test_tube_item_tile(1, 3, "I"),
        _number_tile(1, 2, 5),
        _number_tile(1, 1, 5),
        _letter_tile(1, 0, "T"),
    )
    dictionary = _FakeDictionary({"veins", "vail", "vacant"})
    pick = _pick_solution_path(
        board,
        [[11, 10, 9, 8], VEINS_PATH, VACANT_PATH],
        dictionary,
        prefer_longer_paths=False,
    )
    assert pick is not None
    path, word = pick
    assert path == VEINS_PATH
    assert word == "veins"
    assert word != "vacant"


def test_20260712_test_tube_final_guess_is_veins_path() -> None:
    """After OWE, final guess must be the veins path — not vacant."""
    assert FIXTURE.exists(), f"missing fixture {FIXTURE}"
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(payload)
    extras = payload.get("extras") or {}
    loadout = Loadout(extras=dict(extras))
    guesses = parse_cursedle_guesses(loadout.extras)
    assert len(guesses) == 4
    assert int(extras.get("cursedle_guesses_remaining") or 0) == 1

    dictionary = WordDictionary()
    feedback_paths = filter_candidates(board, guesses)
    dict_paths = _narrow_candidates_to_dictionary(board, feedback_paths, dictionary)
    assert VEINS_PATH in dict_paths

    advice = run_cursedle_solver(board, loadout, dictionary)
    assert advice.path == VEINS_PATH
    assert advice.word.lower() != "vacant"
    assert "Final guess" in advice.reason or "candidates" in advice.reason.lower()
