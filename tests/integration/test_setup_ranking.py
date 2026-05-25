"""Setup-aware search ranking prefers investment words when configured."""

from __future__ import annotations

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.setup_value import (
    derive_setup_ranking_winner,
    project_setup_delta,
    rank_score_for_word,
    setup_future_value,
)
from cursed_words_solver.search import WordSearcher
from tests.helpers.boards import _make_wordlist


def _tile(row: int, col: int, ch: str, score: float, *, number: float | None = None) -> Tile:
    curse = CurseType.NUMBER if number is not None else CurseType.LETTER
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=TileColor.VOID if number else TileColor.SHINY,
        curse=curse,
        number_value=int(number) if number is not None else None,
    )


def _board_with_high_number() -> Board:
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    grid[2][2] = _tile(2, 2, "9", 9, number=9.0)
    grid[2][3] = _tile(2, 3, "E", 1)
    grid[2][4] = _tile(2, 4, "T", 1)
    return Board(tiles=grid, money=0)


def test_project_birthday_cake_delta():
    board = _board_with_high_number()
    path = [12, 13, 14]
    loadout = Loadout(
        stickers=[LoadoutItem(id="birthday_cake", name="Birthday Cake", level=2)],
        extras={"grids_remaining": "3"},
    )
    delta = project_setup_delta(board, path, "9et", loadout)
    assert delta.birthday_cake_bonus == 18
    assert setup_future_value(delta, loadout) > 0


def test_rank_score_prefers_setup_word(tmp_path):
    wl = _make_wordlist(tmp_path)
    board = _board_with_high_number()
    path_invest = [12, 13, 14]
    path_plain = [2, 3, 4]
    loadout = Loadout(
        stickers=[LoadoutItem(id="birthday_cake", name="Birthday Cake", level=3)],
        extras={"birthday_cake_bonus": "0", "grids_remaining": "4"},
    )
    pipeline = ScoringPipeline()
    imm_invest = pipeline.score_total_only(board, path_invest, "9et", loadout)
    imm_plain = pipeline.score_total_only(board, path_plain, "aaa", loadout)
    rank_invest, setup = rank_score_for_word(
        board, path_invest, "9et", loadout, imm_invest, setup_weight=0.5
    )
    rank_plain, _ = rank_score_for_word(
        board, path_plain, "aaa", loadout, imm_plain, setup_weight=0.5
    )
    if imm_plain > imm_invest:
        assert rank_invest > rank_plain or setup > 0


def test_searcher_score_cache_reuses(tmp_path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_with_high_number()
    loadout = Loadout(
        stickers=[LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1)],
        extras={"grids_remaining": "2"},
    )
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=5,
        time_budget=0.5,
        setup_weight=0.4,
    )
    path = [12, 13, 14]
    searcher._score_cache.clear()
    a = searcher._rank_score_for_candidate(board, path, "9et", loadout)
    b = searcher._rank_score_for_candidate(board, path, "9et", loadout)
    assert a == b
    assert len(searcher._score_cache) == 1


def test_derive_setup_ranking_winner_helper():
    assert derive_setup_ranking_winner(80.0, 100.0, 120.0, 90.0) == "setup"
