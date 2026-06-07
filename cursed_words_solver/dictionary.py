"""Word list and prefix trie for search pruning."""

from __future__ import annotations

from pathlib import Path

from cursed_words_solver.config import ensure_wordlist
from cursed_words_solver.trie_backends import (
    ArrayLetterTrieBackend,
    ArrayMixedTrieBackend,
    TrieBackend,
    TrieCursor,
    load_or_build_backend,
    resolve_backend_name,
)

__all__ = [
    "TrieCursor",
    "WordDictionary",
    "resolve_trie_backend",
]


def resolve_trie_backend(requested: str = "auto") -> str:
    return resolve_backend_name(requested)


def _chars_to_pattern(chars: list[str]) -> str:
    """Map DFS char tokens to a dictionary pattern (digits -> wildcard slots)."""
    out: list[str] = []
    for token in chars:
        for ch in token.lower():
            if ch.isdigit():
                out.append("?")
            elif ch.isalpha():
                out.append(ch)
    return "".join(out)


class WordDictionary:
    def __init__(
        self,
        path: Path | None = None,
        *,
        trie_backend: str = "auto",
        use_trie_cache: bool = True,
    ) -> None:
        path = path or ensure_wordlist()
        self.path = path
        self.trie_backend_name = resolve_backend_name(trie_backend)
        self.words: set[str] = set()
        self.words_by_length: dict[int, tuple[str, ...]] = {}
        self._letter_trie: TrieBackend
        self._pattern_trie: TrieBackend
        self._build(path, use_cache=use_trie_cache)

    @property
    def trie_node_count(self) -> int:
        if isinstance(self._letter_trie, ArrayLetterTrieBackend):
            return self._letter_trie.node_count
        return len(self.words)

    def _build(self, path: Path, *, use_cache: bool) -> None:
        words: set[str] = set()
        by_length: dict[int, list[str]] = {}
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            w = line.strip().lower()
            if len(w) >= 2 and w.isalpha():
                words.add(w)
                by_length.setdefault(len(w), []).append(w)
        self.words = words
        self.words_by_length = {n: tuple(sorted(ws)) for n, ws in by_length.items()}
        self._letter_trie = load_or_build_backend(
            path,
            words,
            backend=self.trie_backend_name,
            use_cache=use_cache,
        )
        # Pattern/digit companion trie for mixed letter+digit DFS segments.
        if self.trie_backend_name == "array":
            self._pattern_trie = self._letter_trie
        else:
            self._pattern_trie = ArrayMixedTrieBackend(words)

    def words_of_length(self, length: int) -> tuple[str, ...]:
        return self.words_by_length.get(length, ())

    def root_cursor(self) -> TrieCursor:
        return self._letter_trie.root_cursor()

    def step_cursor(self, cursor: TrieCursor | None, ch: str) -> TrieCursor | None:
        return self._letter_trie.step_cursor(cursor, ch)

    def step_token_cursor(
        self, cursor: TrieCursor | None, token: str
    ) -> TrieCursor | None:
        return self._letter_trie.step_token_cursor(cursor, token)

    def cursor_is_word(self, cursor: TrieCursor | None) -> bool:
        return self._letter_trie.cursor_is_word(cursor)

    def has_prefix(self, s: str) -> bool:
        return self._letter_trie.has_prefix(s)

    def contains(self, s: str) -> bool:
        return self._letter_trie.contains(s)

    def is_valid_word(self, s: str, min_len: int = 3) -> bool:
        return len(s) >= min_len and self.contains(s)

    def pattern_has_prefix(self, pattern: str) -> bool:
        """Prefix check for patterns with '?' (number-tile / wildcard slots)."""
        if not pattern:
            return True
        if "?" not in pattern and pattern.isalpha():
            return self.has_prefix(pattern)
        return self._pattern_prefix_ok(pattern, 0)

    def pattern_from_chars(self, chars: list[str]) -> str:
        return _chars_to_pattern(chars)

    def _pattern_prefix_ok(self, pattern: str, pos: int) -> bool:
        if pos == len(pattern):
            return True
        ch = pattern[pos]
        if ch == "?":
            base = pattern[:pos]
            for c in "abcdefghijklmnopqrstuvwxyz":
                if not self.has_prefix(base + c):
                    continue
                resolved = base + c + pattern[pos + 1 :]
                if self._pattern_prefix_ok(resolved, pos + 1):
                    return True
            return False
        if not ch.isalpha():
            return False
        if not self.has_prefix(pattern[: pos + 1]):
            return False
        return self._pattern_prefix_ok(pattern, pos + 1)

    def pattern_root_cursor(self) -> TrieCursor:
        return self._pattern_trie.root_cursor()

    def pattern_step_cursor(
        self, cursor: TrieCursor | None, ch: str
    ) -> TrieCursor | None:
        return self._pattern_trie.step_cursor(cursor, ch)

    def pattern_step_token_cursor(
        self, cursor: TrieCursor | None, token: str
    ) -> TrieCursor | None:
        return self._pattern_trie.step_token_cursor(cursor, token)

    def pattern_cursor_is_word(self, cursor: TrieCursor | None) -> bool:
        return self._pattern_trie.cursor_is_word(cursor)

    def mixed_step_cursor(
        self, cursor: TrieCursor | None, token: str
    ) -> TrieCursor | None:
        """Step the digit-capable companion trie (letters + literal digit faces)."""
        node = cursor if cursor is not None else self._pattern_trie.root_cursor()
        for ch in token.lower():
            node = self._pattern_trie.step_cursor(node, ch)
            if node is None:
                return None
        return node
