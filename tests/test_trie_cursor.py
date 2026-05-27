from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.search import WordSearcher


def _write_words(tmp_path: Path, words: list[str]) -> Path:
    p = tmp_path / "words.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p


def _board_catdog_stitch() -> Board:
    grid = [[Tile(r, c, "q", "Q", 1.0, TileColor.COLORLESS, CurseType.LETTER) for c in range(5)] for r in range(5)]
    grid[0][0] = Tile(0, 0, "c", "C", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[0][1] = Tile(0, 1, "a", "A", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[0][2] = Tile(0, 2, "t", "T", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[1][2] = Tile(1, 2, "d", "D", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[1][1] = Tile(1, 1, "o", "O", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[1][0] = Tile(1, 0, "g", "G", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    return Board(tiles=grid)


def test_dictionary_trie_cursor_helpers(tmp_path: Path):
    wl = _write_words(tmp_path, ["cat", "dog", "cater"])
    d = WordDictionary(wl)

    assert d.has_prefix("ca")
    assert d.has_prefix("cater")
    assert not d.has_prefix("cz")
    assert d.contains("cat")
    assert not d.contains("c")
    assert not d.contains("cats")

    cur = d.root_cursor()
    cur = d.step_cursor(cur, "c")
    cur = d.step_cursor(cur, "a")
    assert cur is not None
    assert not d.cursor_is_word(cur)
    cur = d.step_cursor(cur, "t")
    assert d.cursor_is_word(cur)


def test_search_word_stitch_uses_prefix_extension(tmp_path: Path):
    # "catdog" is not a dictionary word; it should still be accepted as cat + dog
    # when Honeypot (word_stitch) is active.
    wl = _write_words(tmp_path, ["cat", "dog", "cater", "cog"])
    d = WordDictionary(wl)
    board = _board_catdog_stitch()
    loadout = Loadout(
        stamps=[LoadoutItem(id="honeypot", name="Honeypot", level=1, kind="stamp")]
    )

    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=6,
        time_budget=2.0,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=20)
    words = {r.word for r in results}
    assert "catdog" in words
