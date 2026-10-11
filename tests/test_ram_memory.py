"""Random Access Memory: pin_memory search flags, scoring replay, blacklist, order."""

from __future__ import annotations

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.engine.scorer import EngineScorer
from cursed_words_solver.rules.ram_memory import pin_memory_entries
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import WordSearcher


def _tile(row: int, col: int, ch: str, score: int = 1, **kwargs) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=kwargs.get("color", TileColor.COLORLESS),
        curse=kwargs.get("curse", CurseType.LETTER),
        metadata=kwargs.get("metadata", {"source": "melmod"}),
    )


def _ram_loadout(*memory: dict, stickers: list[LoadoutItem] | None = None) -> Loadout:
    return Loadout(
        stickers=stickers or [],
        extras={
            "pin_effect": "random_access_memory",
            "pin_memory": list(memory),
        },
    )


def _make_wordlist(tmp_path, words: list[str]):
    p = tmp_path / "words.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p


@pytest.mark.parametrize(
    "slug,flag_attr",
    [
        ("hungry_snake", "horizontal_wrap"),
        ("full_moon", "double_letter_teleport"),
        ("queenie", "q_as_qu"),
        ("red_envelope", "red_as_e"),
        ("sluggish_zombie", "z_as_s"),
    ],
)
def test_ram_search_flags_from_pin_memory(slug, flag_attr):
    loadout = _ram_loadout(
        {"id": slug, "name": slug.replace("_", " ").title(), "kind": "stamp", "level": 1},
    )
    flags = stamp_search_flags(loadout)
    assert getattr(flags, flag_attr) is True


def test_ram_mixed_memory_merges_flags():
    loadout = _ram_loadout(
        {"id": "hungry_snake", "name": "Hungry Snake", "kind": "stamp", "level": 1},
        {"id": "queenie", "name": "Queenie", "kind": "stamp", "level": 1},
    )
    flags = stamp_search_flags(loadout)
    assert flags.horizontal_wrap is True
    assert flags.q_as_qu is True


def test_hungry_snake_ram_no_scoring_replay():
    grid = [[_tile(r, c, "A", 5) for c in range(5)] for r in range(5)]
    board = Board(tiles=grid)
    pipeline = EngineScorer()
    lo = _ram_loadout(
        {"id": "hungry_snake", "name": "Hungry Snake", "kind": "stamp", "level": 1},
    )
    base, _ = pipeline.score(board, [0], "a", Loadout())
    score, bd = pipeline.score(board, [0], "a", lo)
    assert score == base
    assert not any(e.startswith("RAM:") for e in bd["pipeline"]["effects"])


def test_hungry_snake_ram_finds_wrapped_word(tmp_path):
    words = ["arc", "car"]
    wl = _make_wordlist(tmp_path, words)
    d = WordDictionary(wl)
    grid = [[_tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = _tile(0, 0, "A", 1)
    grid[0][4] = _tile(0, 4, "R", 1)
    grid[1][4] = _tile(1, 4, "C", 1)
    board = Board(tiles=grid)
    loadout = _ram_loadout(
        {"id": "hungry_snake", "name": "Hungry Snake", "kind": "stamp", "level": 1},
    )
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=3.0)
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert any(r.word == "arc" for r in results)


def test_pin_memory_entries_parsed():
    lo = Loadout(extras={"pin_memory": [{"id": "a", "name": "A", "kind": "stamp"}]})
    assert len(pin_memory_entries(lo)) == 1


def test_pin_memory_entries_parses_json_string():
    lo = Loadout(
        extras={
            "pin_memory": '[{"id":"sunflower","name":"Sunflower","level":1,"kind":"sticker"}]'
        }
    )
    entries = pin_memory_entries(lo)
    assert len(entries) == 1
    assert entries[0]["id"] == "sunflower"
