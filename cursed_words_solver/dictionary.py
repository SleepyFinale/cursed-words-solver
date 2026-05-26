"""Word list and prefix trie for search pruning."""

from __future__ import annotations

from pathlib import Path

from cursed_words_solver.config import ensure_wordlist


class WordDictionary:
    def __init__(self, path: Path | None = None) -> None:
        path = path or ensure_wordlist()
        self.path = path
        self.words: set[str] = set()
        self._build(path)

    def _build(self, path: Path) -> None:
        words: set[str] = set()
        prefixes: set[str] = set()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            w = line.strip().lower()
            if len(w) >= 2 and w.isalpha():
                words.add(w)
                for i in range(1, len(w) + 1):
                    prefixes.add(w[:i])
        self.words = words
        self.prefixes = prefixes

    def has_prefix(self, s: str) -> bool:
        if not s:
            return True
        return s.lower() in self.prefixes

    def contains(self, s: str) -> bool:
        return s.lower() in self.words

    def is_valid_word(self, s: str, min_len: int = 3) -> bool:
        return len(s) >= min_len and self.contains(s)
