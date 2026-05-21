"""Word dictionary loading tests."""

from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary


def _write_wordlist(path: Path, words: list[str]) -> None:
    path.write_text("\n".join(words) + "\n", encoding="utf-8")


def test_wordlist_excludes_spaz(tmp_path: Path) -> None:
    wl = tmp_path / "words.txt"
    _write_wordlist(wl, ["cat", "dog", "spa", "the"])
    d = WordDictionary(wl)
    assert d.contains("cat")
    assert not d.contains("spaz")
    assert not d.is_valid_word("spaz")


def test_wordlist_min_length(tmp_path: Path) -> None:
    wl = tmp_path / "words.txt"
    _write_wordlist(wl, ["at", "cat"])
    d = WordDictionary(wl)
    assert d.contains("at")
    assert not d.is_valid_word("at", min_len=3)
    assert d.is_valid_word("cat", min_len=3)
