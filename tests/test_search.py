from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import WordSearcher, neighbors_standard


def _make_wordlist(tmp_path: Path) -> Path:
    words = ["cat", "car", "tar", "rat", "art", "the", "buy", "game"]
    p = tmp_path / "words.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p


def _board_cat_horizontal() -> Board:
    tiles = []
    letters = [
        list("catxx"),
        list("xxxxx"),
        list("xxxxx"),
        list("xxxxx"),
        list("xxxxx"),
    ]
    for r in range(5):
        row = []
        for c in range(5):
            ch = letters[r][c] if letters[r][c] != "x" else "Q"
            row.append(
                Tile(
                    row=r,
                    col=c,
                    char=ch,
                    letter=ch,
                    base_score=1,
                    color=TileColor.COLORLESS,
                    curse=CurseType.LETTER,
                )
            )
        tiles.append(row)
    return Board(tiles=tiles)


def test_neighbors_standard():
    board = _board_cat_horizontal()
    nbrs = neighbors_standard(board, [0], {0})
    assert 1 in nbrs
    assert 5 in nbrs  # down-left from (0,0) is (1,0) idx 5


def test_finds_cat(tmp_path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=8, time_budget=5.0)
    board = _board_cat_horizontal()
    results = searcher.find_best_words(board, top_n=1)
    assert results
    assert results[0].word == "cat"


def test_red_sticker_bonus(tmp_path):
    wl = _make_wordlist(tmp_path)
    board = _board_cat_horizontal()
    board.tiles[0][0].color = TileColor.RED
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="red_rider", name="Red Rider", level=1, kind="sticker")
        ]
    )
    pipeline = ScoringPipeline()
    score, _ = pipeline.score(board, [0, 1, 2], "cat", loadout)
    assert score > 3
