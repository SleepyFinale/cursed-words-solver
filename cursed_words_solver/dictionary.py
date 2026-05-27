"""Word list and prefix trie for search pruning."""

from __future__ import annotations

from pathlib import Path

from cursed_words_solver.config import ensure_wordlist

END_SENTINEL = "$"


class WordDictionary:
    def __init__(self, path: Path | None = None) -> None:
        path = path or ensure_wordlist()
        self.path = path
        self.words: set[str] = set()
        self.trie: dict[str, dict] = {}
        self._build(path)

    def _build(self, path: Path) -> None:
        words: set[str] = set()
        trie: dict[str, dict] = {}
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            w = line.strip().lower()
            if len(w) >= 2 and w.isalpha():
                words.add(w)
                node = trie
                for ch in w:
                    node = node.setdefault(ch, {})
                node[END_SENTINEL] = {}
        self.words = words
        self.trie = trie

    def root_cursor(self) -> dict[str, dict]:
        return self.trie

    def step_cursor(
        self, cursor: dict[str, dict] | None, ch: str
    ) -> dict[str, dict] | None:
        if cursor is None:
            return None
        return cursor.get(ch.lower())

    def cursor_is_word(self, cursor: dict[str, dict] | None) -> bool:
        return bool(cursor) and END_SENTINEL in cursor

    def has_prefix(self, s: str) -> bool:
        if not s:
            return True
        node: dict[str, dict] | None = self.trie
        for ch in s.lower():
            if node is None:
                return False
            node = node.get(ch)
            if node is None:
                return False
        return True

    def contains(self, s: str) -> bool:
        node: dict[str, dict] | None = self.trie
        for ch in s.lower():
            if node is None:
                return False
            node = node.get(ch)
            if node is None:
                return False
        return END_SENTINEL in node

    def is_valid_word(self, s: str, min_len: int = 3) -> bool:
        return len(s) >= min_len and self.contains(s)
