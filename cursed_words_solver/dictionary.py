"""The game's word list (``game_words.txt`` exported by melmod, or ENABLE1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cursed_words_solver.config import ensure_wordlist

__all__ = ["WordDictionary"]


class WordDictionary:
    """Lower-case words from a word list; the engine builds its trie from ``words``."""

    def __init__(self, path: Path | None = None, **_legacy: Any) -> None:
        path = path or ensure_wordlist()
        self.path = path
        self.words: set[str] = set()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            w = line.strip().lower()
            # One-letter words ("a", "i", "o") are valid in-game (Vocabulary length-1 trie).
            if w and w.isalpha():
                self.words.add(w)

    @property
    def trie(self):
        """The engine ``CsrTrie`` for these words (built / cached on first use)."""
        from cursed_words_solver.engine.solver import trie_for

        return trie_for(self)

    def contains(self, word: str) -> bool:
        return word.lower() in self.words

    def is_valid_word(self, word: str, min_len: int = 1) -> bool:
        return len(word) >= min_len and word.lower() in self.words

    def has_prefix(self, prefix: str) -> bool:
        return self.trie.walk(0, prefix.lower()) >= 0

    def __len__(self) -> int:
        return len(self.words)
