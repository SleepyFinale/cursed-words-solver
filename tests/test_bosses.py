"""Tests for wiki Main Boss rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.boss_effects import (
    boss_context,
    boss_word_constraints,
    effective_target_score_multiplier,
    load_rules_catalog,
    resolve_boss_scaling,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import target_score_from_loadout
from cursed_words_solver.search import WordSearcher, _active_indices
from cursed_words_solver.dictionary import WordDictionary


RULES = load_rules_catalog()


def _tile(
    row: int,
    col: int,
    letter: str,
    score: float = 2,
    *,
    color: TileColor = TileColor.COLORLESS,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=letter,
        letter=letter,
        base_score=score,
        color=color,
        curse=CurseType.LETTER,
    )


def _board_letters(rows: list[str], money: int = 10) -> Board:
    tiles: list[list[Tile]] = []
    active = [False] * 25
    for r, row in enumerate(rows):
        row_tiles: list[Tile] = []
        for c, ch in enumerate(row):
            idx = r * 5 + c
            if ch == ".":
                row_tiles.append(
                    Tile(
                        row=r,
                        col=c,
                        char="",
                        letter="",
                        base_score=0,
                        curse=CurseType.ITEM,
                        metadata={"inactive": True},
                    )
                )
                active[idx] = False
            else:
                row_tiles.append(_tile(r, c, ch))
                active[idx] = True
        tiles.append(row_tiles)
    return Board(tiles=tiles, money=money, active=active)


def _loadout(**kwargs) -> Loadout:
    extras = kwargs.pop("extras", {})
    return Loadout(
        boss_id=kwargs.pop("boss_id", ""),
        boss_name=kwargs.pop("boss_name", ""),
        money=kwargs.pop("money", 10),
        extras=extras,
        **kwargs,
    )


def test_catalog_has_sixteen_main_bosses_no_no_vowels():
    bosses = RULES.get("bosses", {})
    assert "no_vowels" not in bosses
    assert len(bosses) >= 16
    assert bosses["axolotl"]["type"] == "custom"
    assert bosses["cobra"]["type"] == "boss_word_min_length"
    assert bosses["salamander"]["type"] == "boss_tile_penalty"


def test_resolve_boss_scaling_salamander_cursed():
    rule = RULES["bosses"]["salamander"]
    assert resolve_boss_scaling(rule, 3, False) == 5
    assert resolve_boss_scaling(rule, 3, True) == 7


def test_resolve_boss_scaling_robo_monkey_area5_na():
    rule = RULES["bosses"]["robo_monkey"]
    assert resolve_boss_scaling(rule, 5, False, field="multiplier") is None


def test_salamander_tile_penalty_in_pipeline():
    board = _board_letters(["cat..", ".....", ".....", ".....", "....."])
    loadout = _loadout(
        boss_id="salamander",
        extras={"boss_area_number": 1, "boss_cursed": False},
    )
    pipe = ScoringPipeline()
    _score, breakdown = pipe.score(board, [0, 1, 2], "cat", loadout)
    effects = breakdown.get("pipeline", {}).get("effects", [])
    assert any("per tile (boss)" in e for e in effects)


def test_robo_monkey_subtracts_word_score():
    board = _board_letters(["cat..", ".....", ".....", ".....", "....."])
    loadout = _loadout(
        boss_id="robo_monkey",
        money=10,
        extras={"boss_area_number": 1},
    )
    pipe = ScoringPipeline()
    _, base_bd = pipe.score(board, [0, 1, 2], "cat", Loadout(money=10))
    _, boss_bd = pipe.score(board, [0, 1, 2], "cat", loadout)
    assert boss_bd["word_score"] == base_bd["word_score"] - 10


def test_toothed_whale_target_multiplier():
    loadout = _loadout(
        boss_id="toothed_whale",
        extras={"boss_area_number": 1, "target_score": 100},
    )
    assert target_score_from_loadout(loadout) == 125


def test_cobra_min_length_constraint():
    loadout = _loadout(
        boss_id="cobra",
        extras={"boss_area_number": 1, "boss_cursed": True},
    )
    c = boss_word_constraints(loadout, RULES)
    assert c.min_len == 5


def test_wolf_max_length_constraint():
    loadout = _loadout(
        boss_id="wolf",
        extras={"boss_area_number": 5},
    )
    c = boss_word_constraints(loadout, RULES, default_max_len=15)
    assert c.max_len == 4


def test_michael_min_word_length_constraint_from_extras():
    loadout = _loadout(
        boss_id="michael",
        extras={"michael_min_word_length": 25},
    )
    c = boss_word_constraints(loadout, RULES)
    assert c.min_len == 25


def test_michael_min_word_length_does_not_require_copied_boss_effects():
    loadout = _loadout(
        boss_id="salamander",
        extras={"boss_modifiers": [], "michael_min_word_length": 25},
    )
    c = boss_word_constraints(loadout, RULES)
    assert c.min_len == 25


def test_michael_phase_three_empty_modifiers_falls_back_to_full_board_length():
    board = _board_letters(["aaaaa", "aaaaa", "aaaaa", "aaaaa", "aaaaa"])
    loadout = _loadout(
        boss_id="michael",
        extras={"michael_phase": 3, "boss_modifiers": []},
    )
    c = boss_word_constraints(loadout, RULES, default_max_len=sum(board.active))
    assert c.min_len == 25
    assert c.max_len == 25


def test_michael_finale_search_only_returns_25_letter_words(tmp_path: Path):
    board = _board_letters(["aaaaa", "aaaaa", "aaaaa", "aaaaa", "aaaaa"])
    loadout = _loadout(
        boss_id="michael",
        extras={"michael_phase": 3, "boss_modifiers": []},
    )
    constraints = boss_word_constraints(loadout, RULES, default_max_len=sum(board.active))
    wl = tmp_path / "words.txt"
    wl.write_text(
        "aaaaaaaaaaaaa\naaaaaaaaaaaaaaaaaaaaaaaaa\n",
        encoding="utf-8",
    )
    d = WordDictionary(wl)
    searcher = WordSearcher(
        dictionary=d,
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        time_budget=2.0,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=5)
    assert results
    assert all(len(r.word) >= 25 for r in results)


def test_default_word_constraints_use_min_one_and_passed_max():
    board = _board_letters(
        [
            "word.",
            "grid.",
            "....h",
            ".....",
            ".....",
        ]
    )
    loadout = _loadout()
    c = boss_word_constraints(loadout, RULES, default_max_len=sum(board.active))
    assert c.min_len == 1
    assert c.max_len == 9


def test_fox_steal_in_pipeline():
    board = _board_letters(["cat..", ".....", ".....", ".....", "....."])
    loadout = _loadout(
        boss_id="fox",
        money=10,
        extras={"boss_area_number": 1, "boss_floor_modification": 2},
    )
    pipe = ScoringPipeline()
    _, bd = pipe.score(board, [0, 1, 2], "cat", loadout)
    assert loadout.money < 10


def test_hyena_blocks_search():
    loadout = _loadout(extras={"hyena_blocked": True})
    c = boss_word_constraints(loadout, RULES)
    assert c.blocked
    board = _board_letters(["cat..", ".....", ".....", ".....", "....."])
    searcher = WordSearcher(
        dictionary=WordDictionary(),
        blocked=c.blocked,
        time_budget=1.0,
    )
    assert searcher.find_best_words(board, loadout=loadout) == []


def test_bat_inactive_cells_not_in_search_starts():
    board = _board_letters(
        [
            "cat..",
            ".....",
            ".....",
            ".....",
            ".....",
        ]
    )
    assert len(_active_indices(board)) == 3
    assert 3 not in _active_indices(board)


def test_bat_3x4_search_uses_column_four(tmp_path: Path):
    """Col 3 must be active so words like 'wet' / 'went' are reachable."""
    from cursed_words_solver.loadout import parse_board_from_run_state
    from tests.integration.test_run_state_board import _bat_3x4_run_state

    board = parse_board_from_run_state(_bat_3x4_run_state())
    assert board is not None
    assert 13 in _active_indices(board)  # row 2, col 3

    wl = tmp_path / "words.txt"
    wl.write_text(
        "wet\nwent\nteeth\n",
        encoding="utf-8",
    )
    d = WordDictionary(wl)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=2.0)
    results = searcher.find_best_words(board)
    words = {r.word for r in results}
    assert "wet" in words or "went" in words


def test_parse_board_inactive_from_run_state(tmp_path: Path):
    from cursed_words_solver.loadout import parse_board_from_run_state

    data = {
        "money": 5,
        "board": {
            "rows": 4,
            "cols": 4,
            "tiles": [
                {
                    "row": 4,
                    "col": c,
                    "char": "A",
                    "letter": "A",
                    "base_score": 1,
                    "color": "colorless",
                    "curse": "letter",
                    "active": True,
                }
                for c in range(4)
            ]
            + [
                {
                    "row": r,
                    "col": c,
                    "char": "",
                    "letter": "",
                    "base_score": 0,
                    "color": "colorless",
                    "curse": "inactive",
                    "active": False,
                }
                for r in range(3)
                for c in range(5)
            ],
        },
    }
    # Build full 25 tiles properly
    tiles = []
    for game_row in range(5):
        for col in range(5):
            solver_row = 4 - game_row
            in_4x4 = game_row < 4 and col < 4
            tiles.append(
                {
                    "row": game_row,
                    "col": col,
                    "char": "A" if in_4x4 else "",
                    "letter": "A" if in_4x4 else "",
                    "base_score": 1 if in_4x4 else 0,
                    "color": "colorless",
                    "curse": "letter" if in_4x4 else "inactive",
                    "active": in_4x4,
                }
            )
    data["board"]["tiles"] = tiles
    board = parse_board_from_run_state(data)
    assert board is not None
    assert board.rows == 4
    assert sum(board.active) == 16
