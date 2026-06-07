"""Random Access Memory: pin_memory search flags, scoring replay, blacklist, order."""

from __future__ import annotations

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.ram_memory import (
    RAM_NON_GENERATABLE_SLUGS,
    pin_memory_entries,
    should_skip_ram_scoring,
)
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import (
    WordSearcher,
    neighbors_standard,
    resolve_letter,
)


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


def test_hungry_snake_ram_horizontal_wrap_neighbors():
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = _tile(0, 0, "A", 1)
    board = Board(tiles=grid)
    loadout = _ram_loadout(
        {"id": "hungry_snake", "name": "Hungry Snake", "kind": "stamp", "level": 1},
    )
    flags = stamp_search_flags(loadout)
    nbrs = neighbors_standard(board, [0], {0}, flags=flags)
    assert 4 in nbrs


def test_hungry_snake_ram_no_scoring_replay():
    grid = [[_tile(r, c, "A", 5) for c in range(5)] for r in range(5)]
    board = Board(tiles=grid)
    pipeline = ScoringPipeline()
    lo = _ram_loadout(
        {"id": "hungry_snake", "name": "Hungry Snake", "kind": "stamp", "level": 1},
    )
    base, _ = pipeline.score(board, [0], "a", Loadout())
    score, bd = pipeline.score(board, [0], "a", lo)
    assert score == base
    assert not any(e.startswith("RAM:") for e in bd["pipeline"]["effects"])


def test_ram_replays_scoring_sticker():
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    for i in range(3):
        grid[0][i] = _tile(0, i, "A", 1)
    board = Board(tiles=grid)
    lo = _ram_loadout(
        {"id": "graduation_cap", "name": "Graduation Cap", "kind": "sticker", "level": 1},
    )
    score, bd = pipeline.score(board, [0, 1, 2], "aaa", lo)
    assert any("RAM:" in e for e in bd["pipeline"]["effects"])
    assert bd["word_score"] >= 9


@pytest.mark.parametrize("slug", sorted(RAM_NON_GENERATABLE_SLUGS))
def test_wiki_blacklist_skipped_for_ram_scoring(slug):
    pipeline = ScoringPipeline()
    entry = {"id": slug, "name": slug, "kind": "sticker", "level": 1}
    assert should_skip_ram_scoring(pipeline.rules, entry)


def test_ram_acquisition_order_in_effects():
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    path = list(range(5))
    board = Board(tiles=grid)
    lo = _ram_loadout(
        {"id": "graduation_cap", "name": "Graduation Cap", "kind": "sticker", "level": 1},
        {"id": "tombstone", "name": "Tombstone", "kind": "sticker", "level": 1},
    )
    _, bd = pipeline.score(board, path, "aaaaa", lo)
    ram_effects = [e for e in bd["pipeline"]["effects"] if e.startswith("RAM:")]
    assert len(ram_effects) == 2
    assert "Graduation Cap" in ram_effects[0]
    assert "Tombstone" in ram_effects[1]


def test_ram_hourglass_reverses_memory_replay_order():
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    path = list(range(5))
    board = Board(tiles=grid)
    lo = Loadout(
        stamps=[LoadoutItem(id="hourglass", name="Hourglass", kind="stamp")],
        extras={
            "pin_effect": "random_access_memory",
            "pin_memory": [
                {
                    "id": "graduation_cap",
                    "name": "Graduation Cap",
                    "kind": "sticker",
                    "level": 1,
                },
                {
                    "id": "tombstone",
                    "name": "Tombstone",
                    "kind": "sticker",
                    "level": 1,
                },
            ],
            "hourglass_count": "1",
        },
    )
    _, bd = pipeline.score(board, path, "aaaaa", lo)
    ram_effects = [e for e in bd["pipeline"]["effects"] if e.startswith("RAM:")]
    assert len(ram_effects) == 2
    assert "Tombstone" in ram_effects[0]
    assert "Graduation Cap" in ram_effects[1]


def test_ram_scoring_trace_order_grid_before_pin_before_sticker(tmp_path):
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = Tile(
        row=0,
        col=0,
        char="s",
        letter="S",
        base_score=0,
        color=TileColor.VOID,
        curse=CurseType.ITEM,
        metadata={"source": "melmod", "scattered_item_id": "cocktail"},
    )
    grid[0][1] = _tile(0, 1, "A", 1)
    grid[0][2] = _tile(0, 2, "A", 1)
    board = Board(tiles=grid)
    lo = Loadout(
        stickers=[LoadoutItem(id="graduation_cap", name="Graduation Cap", level=1)],
        extras={
            "pin_effect": "random_access_memory",
            "pin_memory": [
                {
                    "id": "tombstone",
                    "name": "Tombstone",
                    "kind": "sticker",
                    "level": 1,
                },
            ],
        },
    )
    _, _, trace = pipeline.score_with_trace(board, [0, 1, 2], "aaa", lo)
    grid_rule_idx = next(
        (
            i
            for i, t in enumerate(trace)
            if t.get("phase") == "rule" and str(t.get("rule_id", "")).lower() == "cocktail"
        ),
        None,
    )
    ram_rule_idx = next(
        (
            i
            for i, t in enumerate(trace)
            if t.get("phase") == "rule"
            and str(t.get("rule_id", "")).lower() in ("tombstone", "tomb stone")
        ),
        None,
    )
    inv_rule_idx = next(
        (
            i
            for i, t in enumerate(trace)
            if t.get("phase") == "rule"
            and str(t.get("rule_id", "")).lower() == "graduation_cap"
        ),
        None,
    )
    assert grid_rule_idx is not None and ram_rule_idx is not None and inv_rule_idx is not None
    assert grid_rule_idx < ram_rule_idx < inv_rule_idx


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


def test_red_envelope_ram_resolve():
    tile = _tile(0, 0, "X", 1, color=TileColor.RED)
    loadout = _ram_loadout(
        {"id": "red_envelope", "name": "Red Envelope", "kind": "stamp", "level": 1},
    )
    flags = stamp_search_flags(loadout)
    assert resolve_letter(tile, 0, flags=flags) == "e"


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
