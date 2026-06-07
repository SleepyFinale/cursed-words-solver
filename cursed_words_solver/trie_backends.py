"""Trie backends for WordDictionary (array, marisa-trie, optional datrie)."""

from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

TrieCursor = int | str


@dataclass(slots=True)
class TrieNode:
    children: list[int | None] = field(default_factory=lambda: [None] * 26)
    is_word: bool = False


def _char_index(ch: str) -> int:
    return ord(ch.lower()) - ord("a")


def _digit_index(ch: str) -> int:
    if len(ch) == 1 and ch.isdigit():
        return 26 + ord(ch) - ord("0")
    raise ValueError(f"not a digit: {ch!r}")


@runtime_checkable
class TrieBackend(Protocol):
    """Incremental prefix cursor API used by DFS."""

    def root_cursor(self) -> TrieCursor: ...

    def step_cursor(self, cursor: TrieCursor | None, ch: str) -> TrieCursor | None: ...

    def step_token_cursor(
        self, cursor: TrieCursor | None, token: str
    ) -> TrieCursor | None: ...

    def cursor_is_word(self, cursor: TrieCursor | None) -> bool: ...

    def has_prefix(self, s: str) -> bool: ...

    def contains(self, s: str) -> bool: ...

    @property
    def backend_name(self) -> str: ...


class ArrayLetterTrieBackend:
    """Pure-Python 26-way letter trie (default)."""

    backend_name = "array"

    def __init__(self, words: set[str]) -> None:
        self._nodes: list[TrieNode] = [TrieNode()]
        for w in sorted(words):
            if not w.isalpha():
                continue
            node_idx = 0
            for ch in w:
                slot = _char_index(ch)
                child = self._nodes[node_idx].children[slot]
                if child is None:
                    child = len(self._nodes)
                    self._nodes.append(TrieNode())
                    self._nodes[node_idx].children[slot] = child
                node_idx = child
            self._nodes[node_idx].is_word = True

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    def root_cursor(self) -> TrieCursor:
        return 0

    def step_cursor(self, cursor: TrieCursor | None, ch: str) -> TrieCursor | None:
        if cursor is None or not isinstance(cursor, int):
            return None
        if len(ch) != 1 or not ch.isalpha():
            return None
        slot = _char_index(ch)
        if slot < 0 or slot >= 26:
            return None
        return self._nodes[cursor].children[slot]

    def step_token_cursor(
        self, cursor: TrieCursor | None, token: str
    ) -> TrieCursor | None:
        node = cursor
        for c in token:
            node = self.step_cursor(node, c)
            if node is None:
                return None
        return node

    def cursor_is_word(self, cursor: TrieCursor | None) -> bool:
        return isinstance(cursor, int) and self._nodes[cursor].is_word

    def has_prefix(self, s: str) -> bool:
        return self.step_token_cursor(0, s.lower()) is not None

    def contains(self, s: str) -> bool:
        node = self.step_token_cursor(0, s.lower())
        return self.cursor_is_word(node)

    def pickle_path_suffix(self) -> str:
        return ".array_trie.pkl"

    def save_pickle(self, path: Path) -> None:
        path.write_bytes(pickle.dumps(self._nodes, protocol=pickle.HIGHEST_PROTOCOL))

    @classmethod
    def load_pickle(cls, path: Path, words: set[str]) -> ArrayLetterTrieBackend:
        inst = cls.__new__(cls)
        inst._nodes = pickle.loads(path.read_bytes())
        return inst


class ArrayMixedTrieBackend:
    """Letter + digit alphabet (a-z, 0-9) for mixed-segment prefix tracking."""

    backend_name = "array_mixed"
    _SIZE = 36

    def __init__(self, words: set[str]) -> None:
        self._nodes: list[TrieNode] = [TrieNode()]
        # Mixed trie stores alpha words; digit slots used only during DFS steps.
        for w in sorted(words):
            if not w.isalpha():
                continue
            node_idx = 0
            for ch in w:
                slot = _char_index(ch)
                child = self._nodes[node_idx].children[slot]
                if child is None:
                    while len(self._nodes[node_idx].children) < self._SIZE:
                        self._nodes[node_idx].children.append(None)
                    child = len(self._nodes)
                    self._nodes.append(TrieNode())
                    while len(self._nodes[node_idx].children) < self._SIZE:
                        self._nodes[node_idx].children.append(None)
                    self._nodes[node_idx].children[slot] = child
                node_idx = child
            self._nodes[node_idx].is_word = True

    def _slot(self, ch: str) -> int | None:
        if len(ch) != 1:
            return None
        if ch.isalpha():
            return _char_index(ch)
        if ch.isdigit():
            return _digit_index(ch)
        return None

    def root_cursor(self) -> TrieCursor:
        return 0

    def step_cursor(self, cursor: TrieCursor | None, ch: str) -> TrieCursor | None:
        if cursor is None or not isinstance(cursor, int):
            return None
        slot = self._slot(ch.lower())
        if slot is None:
            return None
        children = self._nodes[cursor].children
        while len(children) < self._SIZE:
            children.append(None)
        return children[slot]

    def step_token_cursor(
        self, cursor: TrieCursor | None, token: str
    ) -> TrieCursor | None:
        node = cursor
        for c in token:
            node = self.step_cursor(node, c)
            if node is None:
                return None
        return node

    def cursor_is_word(self, cursor: TrieCursor | None) -> bool:
        return isinstance(cursor, int) and self._nodes[cursor].is_word

    def has_prefix(self, s: str) -> bool:
        node: TrieCursor | None = 0
        for ch in s.lower():
            node = self.step_cursor(node, ch)
            if node is None:
                return False
        return True

    def contains(self, s: str) -> bool:
        return self.cursor_is_word(self.step_token_cursor(0, s.lower()))


class MarisaTrieBackend:
    """Compact read-only trie via marisa-trie (mmap-friendly for worker sharing)."""

    backend_name = "marisa"

    def __init__(self, words: set[str]) -> None:
        import marisa_trie

        alpha = sorted(w for w in words if w.isalpha())
        self._trie = marisa_trie.Trie(alpha)

    @classmethod
    def load_file(cls, path: Path) -> MarisaTrieBackend:
        import marisa_trie

        inst = cls.__new__(cls)
        inst._trie = marisa_trie.Trie()
        inst._trie.load(str(path))
        return inst

    def save_file(self, path: Path) -> None:
        self._trie.save(str(path))

    def root_cursor(self) -> TrieCursor:
        return ""

    def step_cursor(self, cursor: TrieCursor | None, ch: str) -> TrieCursor | None:
        if cursor is None or not isinstance(cursor, str):
            return None
        if len(ch) != 1 or not ch.isalpha():
            return None
        nxt = cursor + ch.lower()
        if self._prefix_exists(nxt):
            return nxt
        return None

    def step_token_cursor(
        self, cursor: TrieCursor | None, token: str
    ) -> TrieCursor | None:
        if cursor is None or not isinstance(cursor, str):
            return None
        nxt = cursor + token.lower()
        if self._prefix_exists(nxt):
            return nxt
        return None

    def cursor_is_word(self, cursor: TrieCursor | None) -> bool:
        return isinstance(cursor, str) and bool(cursor) and cursor in self._trie

    def _prefix_exists(self, prefix: str) -> bool:
        if not prefix:
            return True
        return next(self._trie.iterkeys(prefix), None) is not None

    def has_prefix(self, s: str) -> bool:
        return self._prefix_exists(s.lower())

    def contains(self, s: str) -> bool:
        return s.lower() in self._trie


class DatrieBackend:
    """Optional datrie double-array backend (requires native build)."""

    backend_name = "datrie"

    def __init__(self, words: set[str]) -> None:
        import datrie

        self._trie = datrie.Trie(datrie.DATrie.alphabet.ASCII.lower())
        for w in sorted(words):
            if w.isalpha():
                self._trie[w] = 1

    def root_cursor(self) -> TrieCursor:
        return ""

    def step_cursor(self, cursor: TrieCursor | None, ch: str) -> TrieCursor | None:
        if cursor is None or not isinstance(cursor, str):
            return None
        if len(ch) != 1 or not ch.isalpha():
            return None
        nxt = cursor + ch.lower()
        if self._has_prefix(nxt):
            return nxt
        return None

    def _has_prefix(self, prefix: str) -> bool:
        if not prefix:
            return True
        return self._trie.has_keys_with_prefix(prefix)

    def step_token_cursor(
        self, cursor: TrieCursor | None, token: str
    ) -> TrieCursor | None:
        if cursor is None or not isinstance(cursor, str):
            return None
        nxt = cursor + token.lower()
        if self._has_prefix(nxt):
            return nxt
        return None

    def cursor_is_word(self, cursor: TrieCursor | None) -> bool:
        return isinstance(cursor, str) and bool(cursor) and cursor in self._trie

    def has_prefix(self, s: str) -> bool:
        return self._has_prefix(s.lower())

    def contains(self, s: str) -> bool:
        return s.lower() in self._trie


def resolve_backend_name(requested: str) -> str:
    name = (requested or "auto").strip().lower()
    if name in ("array", "marisa", "datrie", "array_mixed"):
        return name
    if name != "auto":
        return "array"
    try:
        import marisa_trie  # noqa: F401

        return "marisa"
    except ImportError:
        pass
    try:
        import datrie  # noqa: F401

        return "datrie"
    except ImportError:
        pass
    return "array"


def build_backend(name: str, words: set[str]) -> TrieBackend:
    if name == "marisa":
        return MarisaTrieBackend(words)
    if name == "datrie":
        return DatrieBackend(words)
    if name == "array_mixed":
        return ArrayMixedTrieBackend(words)
    return ArrayLetterTrieBackend(words)


def trie_cache_meta_path(wordlist_path: Path, backend: str) -> Path:
    return wordlist_path.with_suffix(f".{backend}_trie.meta.json")


def trie_cache_data_path(wordlist_path: Path, backend: str) -> Path:
    if backend == "marisa":
        return wordlist_path.with_suffix(".marisa")
    if backend == "array":
        return wordlist_path.with_suffix(".array_trie.pkl")
    return wordlist_path.with_suffix(f".{backend}_trie.cache")


def _wordlist_fingerprint(wordlist_path: Path) -> dict[str, object]:
    stat = wordlist_path.stat()
    digest = hashlib.sha256(wordlist_path.read_bytes()).hexdigest()
    return {
        "path": str(wordlist_path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": digest,
    }


def cache_is_valid(wordlist_path: Path, backend: str) -> bool:
    meta_path = trie_cache_meta_path(wordlist_path, backend)
    data_path = trie_cache_data_path(wordlist_path, backend)
    if not meta_path.is_file() or not data_path.is_file():
        return False
    if not wordlist_path.is_file():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if meta.get("backend") != backend:
        return False
    return meta.get("source") == _wordlist_fingerprint(wordlist_path)


def save_trie_cache(
    wordlist_path: Path, backend: TrieBackend, *, backend_name: str
) -> Path:
    data_path = trie_cache_data_path(wordlist_path, backend_name)
    meta_path = trie_cache_meta_path(wordlist_path, backend_name)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    if backend_name == "marisa" and isinstance(backend, MarisaTrieBackend):
        backend.save_file(data_path)
    elif backend_name == "array" and isinstance(backend, ArrayLetterTrieBackend):
        backend.save_pickle(data_path)
    else:
        raise ValueError(f"cannot cache backend {backend_name}")
    meta_path.write_text(
        json.dumps(
            {
                "backend": backend_name,
                "source": _wordlist_fingerprint(wordlist_path),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return data_path


def load_backend_from_cache(
    wordlist_path: Path, backend_name: str, words: set[str]
) -> TrieBackend | None:
    if not cache_is_valid(wordlist_path, backend_name):
        return None
    data_path = trie_cache_data_path(wordlist_path, backend_name)
    if backend_name == "marisa":
        return MarisaTrieBackend.load_file(data_path)
    if backend_name == "array":
        return ArrayLetterTrieBackend.load_pickle(data_path, words)
    return None


def load_or_build_backend(
    wordlist_path: Path,
    words: set[str],
    *,
    backend: str = "auto",
    use_cache: bool = True,
) -> TrieBackend:
    name = resolve_backend_name(backend)
    if use_cache:
        cached = load_backend_from_cache(wordlist_path, name, words)
        if cached is not None:
            return cached
    built = build_backend(name, words)
    if use_cache and name in ("marisa", "array"):
        try:
            save_trie_cache(wordlist_path, built, backend_name=name)
        except OSError:
            pass
    return built
