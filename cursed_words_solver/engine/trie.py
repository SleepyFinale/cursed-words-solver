"""Compact (CSR) letter trie for the exact search.

Node ``n`` owns child slots ``starts[n] .. starts[n] + counts[n]``; ``chars`` holds
each slot's letter (one byte) so ``bytes.find`` does the per-node child lookup in C,
and ``childs`` holds the child node id. ~840k nodes for the 359k-word game list.
"""

from __future__ import annotations

import hashlib
import pickle
from array import array
from pathlib import Path

_CACHE_VERSION = 2


class CsrTrie:
    # ``_np``: numpy views built on demand by ``engine.search._numpy_trie``.
    __slots__ = ("starts", "counts", "chars", "childs", "is_word", "node_count", "word_depths", "_np")

    def __init__(self, starts: array, counts: array, chars: bytes, childs: array, is_word: bytes) -> None:
        self.starts = starts
        self.counts = counts
        self.chars = chars
        self.childs = childs
        self.is_word = is_word
        self.node_count = len(starts)
        self.word_depths = self._word_depths()

    def _word_depths(self) -> list[int]:
        """Bit k of ``word_depths[n]`` set when a word ends k letters below ``n``."""
        n = len(self.starts)
        masks = [0] * n
        starts, counts, childs, is_word = self.starts, self.counts, self.childs, self.is_word
        for node in range(n - 1, -1, -1):  # BFS ids: children come after parents
            m = 1 if is_word[node] else 0
            s = starts[node]
            for k in range(s, s + counts[node]):
                m |= masks[childs[k]] << 1
            masks[node] = m
        return masks

    @classmethod
    def from_words(cls, words) -> "CsrTrie":
        root: dict = {}
        for w in words:
            if not w or not w.isalpha() or not w.isascii():
                continue
            node = root
            for ch in w.lower():
                node = node.setdefault(ch, {})
            node["$"] = True
        starts = array("i")
        counts = array("i")
        chars = bytearray()
        childs = array("i")
        is_word = bytearray()
        queue = [root]
        i = 0
        while i < len(queue):
            node = queue[i]
            i += 1
            keys = sorted(k for k in node if k != "$")
            starts.append(len(chars))
            counts.append(len(keys))
            is_word.append(1 if "$" in node else 0)
            for k in keys:
                chars.append(ord(k))
                childs.append(len(queue))
                queue.append(node[k])
        return cls(starts, counts, bytes(chars), childs, bytes(is_word))

    def child(self, node: int, c: int) -> int:
        """Child of ``node`` for letter code ``c`` (-1 if absent)."""
        s = self.starts[node]
        k = self.chars.find(c, s, s + self.counts[node])
        return -1 if k < 0 else self.childs[k]

    def walk(self, node: int, text: str) -> int:
        for ch in text:
            node = self.child(node, ord(ch))
            if node < 0:
                return -1
        return node

    def contains(self, word: str) -> bool:
        node = self.walk(0, word.lower())
        return node >= 0 and bool(self.is_word[node])


_MEMO: dict[str, CsrTrie] = {}
_MEMO_SIZE = 4
# Small word lists build in milliseconds; only real dictionaries are cached on disk.
_DISK_CACHE_MIN_WORDS = 20_000
# Cached tries kept on disk (newest first); older dictionaries are pruned.
_DISK_CACHE_KEEP = 3


def _remember(digest: str, trie: CsrTrie) -> CsrTrie:
    _MEMO.pop(digest, None)
    _MEMO[digest] = trie
    while len(_MEMO) > _MEMO_SIZE:
        _MEMO.pop(next(iter(_MEMO)))
    return trie


def _prune_disk_cache(cache_dir: Path, keep: Path) -> None:
    """Drop stale trie pickles (old cache versions, superseded word lists)."""
    try:
        files = sorted(cache_dir.glob("engine_trie_v*.pkl"), key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return
    current = [f for f in files if f.name.startswith(f"engine_trie_v{_CACHE_VERSION}_")]
    stale = [f for f in files if f not in current] + [f for f in current[_DISK_CACHE_KEEP:] if f != keep]
    for f in stale:
        try:
            f.unlink()
        except OSError:
            pass


def load_trie(words, cache_dir: Path | None = None) -> CsrTrie:
    """Build (or load a cached) trie for ``words``; keyed by content hash."""
    word_list = sorted(words)
    digest = hashlib.sha1("\n".join(word_list).encode("utf-8")).hexdigest()[:16]
    if digest in _MEMO:
        return _remember(digest, _MEMO[digest])
    path = None
    if cache_dir is not None and len(word_list) >= _DISK_CACHE_MIN_WORDS:
        path = cache_dir / f"engine_trie_v{_CACHE_VERSION}_{digest}.pkl"
        if path.exists():
            try:
                trie = pickle.loads(path.read_bytes())
                path.touch()
                return _remember(digest, trie)
            except Exception:  # noqa: BLE001 - rebuild on any cache problem
                pass
    trie = CsrTrie.from_words(word_list)
    if path is not None:
        try:
            path.write_bytes(pickle.dumps(trie, protocol=pickle.HIGHEST_PROTOCOL))
            _prune_disk_cache(path.parent, path)
        except OSError:
            pass
    return _remember(digest, trie)
