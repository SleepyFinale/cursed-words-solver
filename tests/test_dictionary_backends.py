"""Tests for trie backends, pattern prefix, and shared cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.dictionary import WordDictionary, resolve_trie_backend
from cursed_words_solver.trie_backends import (
    ArrayLetterTrieBackend,
    MarisaTrieBackend,
    build_backend,
    cache_is_valid,
    load_or_build_backend,
    save_trie_cache,
    trie_cache_data_path,
)


def _write_words(tmp_path: Path, words: list[str]) -> Path:
    p = tmp_path / "words.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p


def test_resolve_trie_backend_array_explicit():
    assert resolve_trie_backend("array") == "array"


def test_array_backend_cursor_api():
    words = {"cat", "car", "dog"}
    backend = ArrayLetterTrieBackend(words)
    cur = backend.root_cursor()
    cur = backend.step_cursor(cur, "c")
    cur = backend.step_cursor(cur, "a")
    assert cur is not None
    cur = backend.step_cursor(cur, "t")
    assert backend.cursor_is_word(cur)
    assert not backend.has_prefix("cz")


@pytest.mark.parametrize("backend", ["array", "marisa"])
def test_word_dictionary_backends_equivalent(tmp_path: Path, backend: str):
    marisa = pytest.importorskip("marisa_trie") if backend == "marisa" else None
    del marisa
    wl = _write_words(tmp_path, ["cat", "car", "dog", "cater"])
    d = WordDictionary(wl, trie_backend=backend, use_trie_cache=False)
    assert d.contains("cat")
    assert d.has_prefix("ca")
    assert not d.has_prefix("cz")
    cur = d.root_cursor()
    cur = d.step_cursor(cur, "c")
    cur = d.step_cursor(cur, "a")
    cur = d.step_cursor(cur, "t")
    assert d.cursor_is_word(cur)


def test_pattern_has_prefix_with_digit_slots(tmp_path: Path):
    wl = _write_words(tmp_path, ["cat", "cot", "car"])
    d = WordDictionary(wl, trie_backend="array", use_trie_cache=False)
    assert d.pattern_has_prefix("c?t")
    assert d.pattern_has_prefix("c?")
    assert not d.pattern_has_prefix("c?z")


def test_pattern_cursor_wrappers(tmp_path: Path):
    wl = _write_words(tmp_path, ["cat", "car"])
    d = WordDictionary(wl, trie_backend="array", use_trie_cache=False)
    cur = d.pattern_root_cursor()
    cur = d.mixed_step_cursor(cur, "c")
    cur = d.mixed_step_cursor(cur, "a")
    assert cur is not None
    cur = d.mixed_step_cursor(cur, "t")
    assert d.pattern_cursor_is_word(cur)


def test_pattern_from_chars_maps_digits_to_wildcards(tmp_path: Path):
    wl = _write_words(tmp_path, ["cat"])
    d = WordDictionary(wl, trie_backend="array", use_trie_cache=False)
    assert d.pattern_from_chars(["v", "2", "o", "4"]) == "v?o?"


def test_trie_cache_roundtrip_marisa(tmp_path: Path):
    marisa_trie = pytest.importorskip("marisa_trie")
    del marisa_trie
    wl = _write_words(tmp_path, ["alpha", "beta", "cat"])
    words = {"alpha", "beta", "cat"}
    backend = build_backend("marisa", words)
    save_trie_cache(wl, backend, backend_name="marisa")
    assert cache_is_valid(wl, "marisa")
    loaded = load_or_build_backend(wl, words, backend="marisa", use_cache=True)
    assert loaded.contains("cat")
    assert not loaded.contains("missing")
    meta = json.loads(
        wl.with_suffix(".marisa_trie.meta.json").read_text(encoding="utf-8")
    )
    assert meta["backend"] == "marisa"
    assert trie_cache_data_path(wl, "marisa").is_file()


def test_trie_cache_roundtrip_array_pickle(tmp_path: Path):
    wl = _write_words(tmp_path, ["cat", "dog"])
    words = {"cat", "dog"}
    backend = build_backend("array", words)
    save_trie_cache(wl, backend, backend_name="array")
    assert cache_is_valid(wl, "array")
    loaded = load_or_build_backend(wl, words, backend="array", use_cache=True)
    assert loaded.contains("cat")


def test_auto_backend_prefers_array_for_hot_path():
    """Single-thread F8 prefers array cursor steps; set CWS_TRIE_BACKEND=marisa for workers."""
    assert resolve_trie_backend("auto") == "array"
    assert resolve_trie_backend("marisa") == "marisa"
