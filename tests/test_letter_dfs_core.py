"""Letter DFS core and cursor-native pattern prefixes."""

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.graph_bitboard import build_board_graph_context
from cursed_words_solver.letter_dfs_core import letter_neighbor_indices
from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.trie_backends import resolve_backend_name


def test_resolve_backend_auto_prefers_array() -> None:
    assert resolve_backend_name("auto") == "array"
    assert resolve_backend_name("marisa") == "marisa"


def test_letter_neighbor_indices_excludes_visited() -> None:
    tiles = [
        [
            Tile(r, c, "a", "A", 1, TileColor.COLORLESS, CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    board = Board(tiles=tiles)
    graph = build_board_graph_context(board)
    visited = 1 << 1  # cell (0,1)
    nbrs = letter_neighbor_indices(graph, 0, visited)
    assert 1 not in nbrs
    assert 5 in nbrs or 6 in nbrs


def test_pattern_has_prefix_cursor_native() -> None:
    d = WordDictionary.__new__(WordDictionary)
    # Minimal letter trie via a tiny embedded wordlist
    from cursed_words_solver.trie_backends import ArrayLetterTrieBackend

    words = {"cat", "car", "dog"}
    d._letter_trie = ArrayLetterTrieBackend(words)  # type: ignore[attr-defined]
    d._pattern_trie = d._letter_trie  # type: ignore[attr-defined]
    assert d.pattern_has_prefix("c?t")
    assert d.pattern_has_prefix("ca")
    assert not d.pattern_has_prefix("zz")
