"""Word list path resolution tests."""

from pathlib import Path

from cursed_words_solver.config import (
    GAME_WORDLIST_MIN_BYTES,
    GAME_WORDLIST_PATH,
    WORDLIST_PATH,
    describe_wordlist,
    resolve_wordlist,
)


def _write_game_words(path: Path, words: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(words) + "\n"
    pad_lines = max(0, (GAME_WORDLIST_MIN_BYTES - len(content)) // 2 + 1)
    path.write_text(content + ("x\n" * pad_lines), encoding="utf-8")
    assert path.stat().st_size > GAME_WORDLIST_MIN_BYTES


def test_resolve_prefers_game_wordlist(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "cursed_words_solver.config.CONFIG_DIR", tmp_path
    )
    monkeypatch.setattr(
        "cursed_words_solver.config.GAME_WORDLIST_PATH",
        tmp_path / "game_words.txt",
    )
    monkeypatch.setattr(
        "cursed_words_solver.config.GAME_WORDLIST_META_PATH",
        tmp_path / "game_words_meta.json",
    )
    monkeypatch.setattr(
        "cursed_words_solver.config.WORDLIST_PATH",
        tmp_path / "enable1.txt",
    )

    _write_game_words(tmp_path / "game_words.txt", ["cat", "dog"])
    (tmp_path / "enable1.txt").write_text("spaz\n", encoding="utf-8")

    path = resolve_wordlist("game")
    assert path == tmp_path / "game_words.txt"


def test_resolve_enable1_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "cursed_words_solver.config.CONFIG_DIR", tmp_path
    )
    monkeypatch.setattr(
        "cursed_words_solver.config.GAME_WORDLIST_PATH",
        tmp_path / "game_words.txt",
    )
    monkeypatch.setattr(
        "cursed_words_solver.config.GAME_WORDLIST_META_PATH",
        tmp_path / "game_words_meta.json",
    )
    monkeypatch.setattr(
        "cursed_words_solver.config.WORDLIST_PATH",
        tmp_path / "enable1.txt",
    )

    _write_game_words(tmp_path / "game_words.txt", ["cat"])
    enable1 = tmp_path / "enable1.txt"
    enable1.write_text("spaz\n", encoding="utf-8")

    path = resolve_wordlist("enable1")
    assert path == enable1


def test_resolve_falls_back_without_game_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "cursed_words_solver.config.CONFIG_DIR", tmp_path
    )
    monkeypatch.setattr(
        "cursed_words_solver.config.GAME_WORDLIST_PATH",
        tmp_path / "game_words.txt",
    )
    monkeypatch.setattr(
        "cursed_words_solver.config.GAME_WORDLIST_META_PATH",
        tmp_path / "game_words_meta.json",
    )
    enable1 = tmp_path / "enable1.txt"
    monkeypatch.setattr(
        "cursed_words_solver.config.WORDLIST_PATH", enable1
    )
    enable1.write_text("cat\nspaz\n", encoding="utf-8")

    path = resolve_wordlist("game")
    assert path == enable1
    label = describe_wordlist(path, preference="game")
    assert "enable1 fallback" in label
