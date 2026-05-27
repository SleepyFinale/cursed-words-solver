"""Search heuristics for multiplicative loadouts."""

from pathlib import Path

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.mult_search import optimistic_mult_factor, search_rank_score
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import WordSearcher
from tests.helpers.boards import _make_wordlist


def _letter(
    r: int,
    c: int,
    ch: str,
    *,
    color: TileColor = TileColor.COLORLESS,
    base: float = 2.0,
) -> Tile:
    return Tile(
        row=r,
        col=c,
        char=ch,
        letter=ch,
        base_score=base,
        color=color,
        curse=CurseType.LETTER,
    )


def _board_blueberries() -> Board:
    """CAT on row 0; end on blue scores higher with Blueberries ×2."""
    tiles = [
        [_letter(0, 0, "c"), _letter(0, 1, "a"), _letter(0, 2, "t", color=TileColor.BLUE)],
        [_letter(1, 0, "x"), _letter(1, 1, "x"), _letter(1, 2, "x")],
        [_letter(2, 0, "x"), _letter(2, 1, "x"), _letter(2, 2, "x")],
        [_letter(3, 0, "x"), _letter(3, 1, "x"), _letter(3, 2, "x")],
        [_letter(4, 0, "x"), _letter(4, 1, "x"), _letter(4, 2, "x")],
    ]
    for r in range(5):
        for c in range(3, 5):
            tiles[r].append(
                Tile(r, c, "Q", "Q", 0, TileColor.COLORLESS, CurseType.ITEM)
            )
    active = [r * 5 + c < 9 for r in range(5) for c in range(5)]
    return Board(tiles=tiles, active=active)


def test_search_rank_score_mult_bonus() -> None:
    rank = search_rank_score(100.0, 2.0, mult_weight=0.5, setup_bonus=0.0)
    assert rank == 150.0


def test_optimistic_mult_blueberries(tmp_path: Path) -> None:
    board = _board_blueberries()
    loadout = Loadout(
        stickers=[LoadoutItem(id="blueberries", name="Blueberries", level=1, kind="sticker")]
    )
    pipe = ScoringPipeline()
    path_end_blue = [0, 1, 2]
    path_no_blue = [0, 1, 4]
    f_blue = optimistic_mult_factor(
        loadout, board, path_end_blue, "cat", pipe.rules
    )
    f_plain = optimistic_mult_factor(
        loadout, board, path_no_blue, "caq", pipe.rules
    )
    assert f_blue >= 2.0
    assert f_plain < f_blue


@pytest.mark.slow
def test_search_blueberries_prefers_blue_end(tmp_path: Path) -> None:
    wl = _make_wordlist(tmp_path)
    wl.write_text(
        "\n".join(["cat", "car", "tar", "rat", "art", "caq", "cax"]),
        encoding="utf-8",
    )
    d = WordDictionary(wl)
    board = _board_blueberries()
    loadout = Loadout(
        stickers=[LoadoutItem(id="blueberries", name="Blueberries", level=1, kind="sticker")]
    )
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=5,
        time_budget=3.0,
        mult_search_weight=0.5,
        mult_search_passes=True,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=1)
    assert results
    assert results[0].word == "cat"
    assert results[0].score >= 12


def test_search_bone_always_mult(tmp_path: Path) -> None:
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    from tests.helpers.boards import _board_cat_horizontal

    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[LoadoutItem(id="bone", name="Bone", level=1, kind="sticker")]
    )
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=5,
        time_budget=2.0,
        mult_search_weight=0.4,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=1)
    assert results
    assert results[0].word == "cat"
    assert results[0].score >= 4
