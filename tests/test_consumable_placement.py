from pathlib import Path

import pytest

from cursed_words_solver import consumable_placement as cp
from cursed_words_solver.consumable_placement import (
    ConsumablePlacement,
    _placement_cell_score,
    _placement_per_screen,
    _rank_placement_indices,
    _tile_ninja_used_count_from_extras,
    _tier_heap_cap,
    _top_variants_for_tier,
    apply_consumable_placements,
    consumable_rack_tiles,
    format_placement_instructions,
    format_placement_path_hints,
    has_exported_consumable_rack,
    has_mahjong_pin,
    iter_placement_variants_fewest_first,
    loadout_after_consumable_placements,
    mahjong_rack_placement_active,
    rack_placement_search_active,
    placement_variants_fewest_first,
    placements_to_records,
    rack_requires_export,
    rack_tile_from_entry,
    remaining_rack_tiles,
    sandy_placement_search_active,
    sandy_requires_rack_export,
    search_consumable_score_boost,
    search_consumable_placement_fallback,
    search_target_rescue,
    search_with_consumable_placements,
    _placement_screen_floor,
    _screen_variant_limit,
    _placement_hard_from_loadout,
    target_rescue_worth_trying,
    wait_for_rack_export,
    wait_for_sandy_rack_export,
)
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import (
    hydrate_tile_ninja_loadout_extras,
    load_run_state_raw,
    parse_board_from_run_state,
    parse_run_state,
)
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.boss_effects import load_rules_catalog
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    consumable_rack_count,
    placed_consumable_indices,
    tile_ninja_multiplier_bonus,
)
from cursed_words_solver.search import WordSearcher
from tests.test_search import _tile


def _sandy_loadout_with_rack() -> Loadout:
    return parse_run_state(
        {
            "character": "Cretaceous Meg",
            "boss_id": "sandy_saguaro",
            "boss_name": "Sandy Saguaro",
            "extras": {
                "consumable_rack": [
                    {
                        "rack_index": 0,
                        "letter": "S",
                        "char_display": "s",
                        "color": "cactus",
                        "curse": "letter",
                        "base_score": 2,
                        "cactus_growth": 1,
                    },
                    {
                        "rack_index": 1,
                        "letter": "T",
                        "char_display": "t",
                        "color": "cactus",
                        "curse": "letter",
                        "base_score": 2,
                        "cactus_growth": 1,
                    },
                ],
            },
            "stickers": [],
            "stamps": [],
        }
    )


def test_consumable_rack_tiles_parsed_cactus_only():
    loadout = _sandy_loadout_with_rack()
    loadout.extras["consumable_rack"].append(
        {
            "rack_index": 2,
            "letter": "A",
            "color": "red",
            "curse": "letter",
            "base_score": 1,
        }
    )
    tiles = consumable_rack_tiles(loadout, cactus_only=True)
    assert len(tiles) == 2
    assert all(t.color == TileColor.CACTUS for t in tiles)


def test_sandy_placement_search_active_when_rack_unplaced():
    loadout = _sandy_loadout_with_rack()
    rules = load_rules_catalog()
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    assert sandy_placement_search_active(loadout, board, rules)
    board.tiles[0][0] = _tile("a", 0, 0, was_consumable=True)
    assert not sandy_placement_search_active(loadout, board, rules)


def test_effective_board_does_not_grow_placed_consumable_cactus():
    from cursed_words_solver.encounter_board import effective_board_for_loadout
    from cursed_words_solver.rules.base_scoring import tile_base_contribution
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    rack = Tile(
        -1,
        -1,
        "L",
        "L",
        1,
        color=TileColor.CACTUS,
        curse=CurseType.LETTER,
        metadata={"source": "consumable_rack", "cactus_growth": 0, "rack_index": 0},
    )
    placed = apply_consumable_placements(board, [(11, rack)])
    loadout = Loadout(extras={"board_from_melmod": "true"})
    rules = ScoringPipeline().rules
    effective = effective_board_for_loadout(placed, loadout, rules)
    tile = effective.get_by_index(11)
    assert tile.metadata.get("cactus_growth") == 0
    assert tile_base_contribution(tile) == 1.0


def test_apply_consumable_placements_marks_was_consumable():
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    rack = Tile(
        0,
        0,
        "E",
        "E",
        2,
        color=TileColor.CACTUS,
        curse=CurseType.LETTER,
        metadata={"rack_index": 0},
    )
    placed = apply_consumable_placements(board, [(7, rack)])
    assert placed_consumable_indices(placed) == frozenset({7})
    tile = placed.get(1, 2)
    assert tile is not None
    assert tile.letter == "E"
    assert tile.metadata.get("was_consumable") is True


def test_search_with_consumable_placements_finds_cats(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("cats\n", encoding="utf-8")
    d = WordDictionary(wl)
    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _tile("c", 0, 0)
    tiles[0][1] = _tile("a", 0, 1)
    board = Board(tiles=tiles)
    rack = [
        Tile(
            -1,
            -1,
            "T",
            "T",
            2,
            color=TileColor.CACTUS,
            curse=CurseType.LETTER,
            metadata={"rack_index": 0},
        ),
        Tile(
            -1,
            -1,
            "S",
            "S",
            2,
            color=TileColor.CACTUS,
            curse=CurseType.LETTER,
            metadata={"rack_index": 1},
        ),
    ]
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=4.0)
    sim_board, records, results = search_with_consumable_placements(
        searcher,
        board,
        Loadout(),
        rack,
        time_budget=4.0,
        top_n=3,
    )
    assert len(records) == 2
    assert results
    assert results[0].word == "cats"
    placement_indices = frozenset(rec.index for rec in records)
    assert placed_consumable_indices(sim_board) == placement_indices
    assert placement_indices.issubset(results[0].path)
    assert format_placement_instructions(records)


def test_board_only_empty_rack_placement_enables_word(tmp_path):
    """Board-only search finds nothing; rack tiles unlock the word via placement."""
    wl = tmp_path / "words.txt"
    wl.write_text("cats\n", encoding="utf-8")
    d = WordDictionary(wl)
    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _tile("c", 0, 0)
    tiles[0][1] = _tile("a", 0, 1)
    board = Board(tiles=tiles)
    loadout = parse_run_state(
        {
            "character": "Octacles",
            "extras": {
                "consumable_rack": [
                    {
                        "rack_index": 0,
                        "letter": "T",
                        "char_display": "t",
                        "color": "blue",
                        "curse": "letter",
                        "base_score": 1.0,
                    },
                    {
                        "rack_index": 1,
                        "letter": "S",
                        "char_display": "s",
                        "color": "blue",
                        "curse": "letter",
                        "base_score": 1.0,
                    },
                ],
            },
            "stickers": [],
            "stamps": [],
        }
    )
    rack = consumable_rack_tiles(loadout)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=2.0)
    assert not searcher.find_best_words(board, top_n=1)
    rules = ScoringPipeline().rules
    assert rack_placement_search_active(loadout, board, rules)
    sim_board, records, results = search_with_consumable_placements(
        searcher,
        board,
        loadout,
        rack,
        time_budget=4.0,
        top_n=3,
        rules=rules,
    )
    assert len(records) == 2
    assert results
    assert results[0].word == "cats"
    placement_indices = frozenset(rec.index for rec in records)
    assert placed_consumable_indices(sim_board) == placement_indices
    assert placement_indices.issubset(results[0].path)


def test_placements_to_records():
    rack = Tile(-1, -1, "E", "E", 1, metadata={"rack_index": 3})
    records = placements_to_records([(12, rack)])
    assert records[0].row == 2
    assert records[0].col == 2
    assert records[0].index == 12
    assert records[0].rack_index == 3


def test_format_placement_path_hints_sorted_by_step():
    path = [10, 6, 12, 7, 8]
    records = [
        ConsumablePlacement(row=1, col=1, index=6, letter="G"),
        ConsumablePlacement(row=2, col=2, index=12, letter="U"),
    ]
    assert format_placement_path_hints(path, records) == (
        "First: Place G on 2; Place U on 3"
    )


def test_format_placement_path_hints_dict_records():
    path = [10, 6, 12]
    records = [
        {"row": 1, "col": 1, "index": 6, "letter": "g"},
        {"row": 2, "col": 2, "index": 12, "letter": "u"},
    ]
    assert format_placement_path_hints(path, records) == (
        "First: Place G on 2; Place U on 3"
    )


def test_format_placement_path_hints_omits_off_path():
    path = [0, 1, 2]
    records = [
        ConsumablePlacement(row=0, col=1, index=1, letter="A"),
        ConsumablePlacement(row=2, col=2, index=12, letter="Z"),
    ]
    assert format_placement_path_hints(path, records) == "First: Place A on 2"


def test_format_placement_path_hints_empty_when_no_match():
    assert format_placement_path_hints([], [{"index": 6, "letter": "G"}]) == ""
    assert (
        format_placement_path_hints(
            [0, 1],
            [ConsumablePlacement(row=2, col=2, index=12, letter="U")],
        )
        == ""
    )


def test_fraction_rack_placement_uses_glyph_not_decimal():
    entry = {
        "rack_index": 2,
        "letter": "0.4",
        "char_display": "⅖",
        "color": "colorless",
        "curse": "fraction",
        "base_score": 7.0,
        "fraction_value": 0.4,
    }
    tile = rack_tile_from_entry(entry)
    assert tile is not None
    assert tile.char == "⅖"
    records = placements_to_records([(6, tile)])
    assert records[0].letter == "⅖"
    assert format_placement_instructions(records) == "⅖ at row 2, col 2"
    assert format_placement_path_hints([0, 6], records) == "First: Place ⅖ on 2"


def test_format_placement_path_hints_decimal_fraction_dict():
    path = [0, 6]
    records = [{"row": 1, "col": 1, "index": 6, "letter": "0.4"}]
    assert format_placement_path_hints(path, records) == "First: Place ⅖ on 2"


def test_target_rescue_worth_trying_false_when_at_target():
    rack = [Tile(-1, -1, "A", "A", 1)]
    assert not target_rescue_worth_trying(500.0, 450, rack)
    assert not target_rescue_worth_trying(450.0, 450, rack)


def test_target_rescue_worth_trying_true_when_below_target():
    rack = [Tile(-1, -1, "A", "A", 1)]
    assert target_rescue_worth_trying(380.0, 450, rack)
    assert not target_rescue_worth_trying(380.0, 450, [])
    assert not target_rescue_worth_trying(380.0, 0, rack)


def test_placement_variants_fewest_first_orders_by_tile_count():
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    rack = [
        Tile(-1, -1, "A", "A", 1, metadata={"rack_index": 0}),
        Tile(-1, -1, "B", "B", 1, metadata={"rack_index": 1}),
    ]
    variants = placement_variants_fewest_first(board, rack, max_variants=50)
    assert variants
    one_tile = [v for v in variants if len(v) == 1]
    two_tile = [v for v in variants if len(v) == 2]
    assert one_tile
    assert two_tile
    first_two_idx = variants.index(two_tile[0])
    last_one_idx = max(variants.index(v) for v in one_tile)
    assert last_one_idx < first_two_idx


def test_search_target_rescue_adopts_only_when_score_meets_target(tmp_path, monkeypatch):
    wl = tmp_path / "words.txt"
    wl.write_text("cat\n", encoding="utf-8")
    d = WordDictionary(wl)
    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _tile("c", 0, 0)
    tiles[0][1] = _tile("a", 0, 1)
    board = Board(tiles=tiles)
    rack = [
        Tile(
            -1,
            -1,
            "T",
            "T",
            2,
            metadata={"rack_index": 0},
        ),
    ]
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=4.0)

    def fake_find(board_arg, loadout=None, top_n=1, **kwargs):
        word = "cat" if any(
            (board_arg.get_by_index(i) or _tile("x", 0, 0)).letter == "T"
            for i in range(25)
        ) else ""
        score = 500.0 if word else 100.0
        from cursed_words_solver.models import WordResult

        if not word:
            return []
        return [WordResult(word=word, path=[0, 1, 2], score=score, breakdown={})]

    monkeypatch.setattr(searcher, "find_best_words", fake_find)

    _, records, results = search_target_rescue(
        searcher,
        board,
        Loadout(),
        rack,
        target=450,
        time_budget=2.0,
        top_n=1,
    )
    assert results
    assert results[0].score >= 450
    assert len(records) == 1

    _, records_low, results_low = search_target_rescue(
        searcher,
        board,
        Loadout(),
        rack,
        target=900,
        time_budget=2.0,
        top_n=1,
    )
    assert not results_low
    assert not records_low


def test_consumable_rack_count_from_parsed_rack_without_count_extra():
    loadout = _sandy_loadout_with_rack()
    assert "consumable_rack_count" not in (loadout.extras or {})
    assert consumable_rack_count(loadout) == 2


def test_has_exported_consumable_rack():
    loadout = _sandy_loadout_with_rack()
    assert has_exported_consumable_rack(loadout)
    loadout.extras.pop("consumable_rack", None)
    assert not has_exported_consumable_rack(loadout)


def test_sandy_requires_rack_export_when_rack_missing():
    loadout = parse_run_state(
        {
            "boss_id": "sandy_saguaro",
            "boss_name": "Sandy Saguaro",
            "extras": {},
            "stickers": [],
            "stamps": [],
        }
    )
    rules = ScoringPipeline().rules
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    assert sandy_requires_rack_export(loadout, board, rules)


def test_sandy_requires_rack_export_false_when_rack_exported():
    loadout = _sandy_loadout_with_rack()
    rules = ScoringPipeline().rules
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    assert not sandy_requires_rack_export(loadout, board, rules)


def test_sandy_requires_rack_export_false_when_consumables_placed():
    loadout = parse_run_state(
        {
            "boss_id": "sandy_saguaro",
            "boss_name": "Sandy Saguaro",
            "extras": {},
            "stickers": [],
            "stamps": [],
        }
    )
    rules = ScoringPipeline().rules
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    board.tiles[0][0] = _tile("h", 0, 0, was_consumable=True)
    assert not sandy_requires_rack_export(loadout, board, rules)


def test_placement_search_sets_required_indices_per_variant(tmp_path, monkeypatch):
    wl = tmp_path / "words.txt"
    wl.write_text("cats\n", encoding="utf-8")
    d = WordDictionary(wl)
    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _tile("c", 0, 0)
    tiles[0][1] = _tile("a", 0, 1)
    board = Board(tiles=tiles)
    rack = [
        Tile(-1, -1, "T", "T", 2, color=TileColor.CACTUS, curse=CurseType.LETTER),
        Tile(-1, -1, "S", "S", 2, color=TileColor.CACTUS, curse=CurseType.LETTER),
    ]
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=4.0)
    recorded: list[frozenset[int]] = []
    real_find = searcher.find_best_words

    def wrapped(board_arg, loadout=None, top_n=1, **kwargs):
        recorded.append(frozenset(searcher.validator.required_consumable_indices))
        return real_find(board_arg, loadout=loadout, top_n=top_n)

    monkeypatch.setattr(searcher, "find_best_words", wrapped)
    search_with_consumable_placements(
        searcher, board, Loadout(), rack, time_budget=4.0, top_n=1
    )
    assert recorded
    assert any(len(req) == 2 for req in recorded)


def test_run_state_sandy_rack_regression():
    """User session: consumable_rack JSON without consumable_rack_count extra."""
    rack_json = (
        '[{"rack_index":0,"letter":"H","char_display":"h","color":"cactus",'
        '"curse":"letter","base_score":4.0,"cactus_growth":0},'
        '{"rack_index":1,"letter":"O","char_display":"o","color":"cactus",'
        '"curse":"letter","base_score":1.0,"cactus_growth":0}]'
    )
    loadout = parse_run_state(
        {
            "boss_id": "sandy_saguaro",
            "boss_name": "Sandy Saguaro",
            "extras": {"consumable_rack": rack_json},
            "stickers": [],
            "stamps": [],
        }
    )
    rules = ScoringPipeline().rules
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    assert consumable_rack_count(loadout) == 2
    assert sandy_placement_search_active(loadout, board, rules)
    assert not sandy_requires_rack_export(loadout, board, rules)


def test_wait_for_sandy_rack_export_finds_rack(monkeypatch):
    rules = ScoringPipeline().rules
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    loadout = parse_run_state(
        {
            "boss_id": "sandy_saguaro",
            "boss_name": "Sandy Saguaro",
            "extras": {},
            "stickers": [],
            "stamps": [],
        }
    )
    calls = {"n": 0}

    def reload():
        calls["n"] += 1
        if calls["n"] < 2:
            return loadout
        return _sandy_loadout_with_rack()

    import time as time_mod

    monkeypatch.setattr(time_mod, "sleep", lambda _sec: None)
    result = wait_for_sandy_rack_export(
        loadout,
        board,
        rules,
        reload_loadout=reload,
        timeout_sec=1.5,
        poll_sec=0.01,
    )
    assert has_exported_consumable_rack(result)
    assert calls["n"] >= 2


def test_run_state_file_sandy_rack_if_present():
    """Optional regression against live ~/.cursed_words_solver/run_state.json."""
    path = Path.home() / ".cursed_words_solver" / "run_state.json"
    if not path.is_file():
        return
    data = load_run_state_raw(path)
    if not data or data.get("boss_id") != "sandy_saguaro":
        return
    loadout = parse_run_state(data)
    rules = ScoringPipeline().rules
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    if has_exported_consumable_rack(loadout):
        assert sandy_placement_search_active(loadout, board, rules)
        assert consumable_rack_count(loadout) >= 1


def _mahjong_loadout_with_red_rack() -> Loadout:
    return parse_run_state(
        {
            "character": "Sandy Saguaro",
            "extras": {
                "pin_effect": "mahjong_red_dragon",
                "consumable_rack": [
                    {
                        "rack_index": 0,
                        "letter": "G",
                        "char_display": "g",
                        "color": "red",
                        "curse": "letter",
                        "base_score": 3,
                    },
                ],
            },
            "stickers": [],
            "stamps": [],
        }
    )


def test_has_mahjong_pin():
    rules = ScoringPipeline().rules
    loadout = _mahjong_loadout_with_red_rack()
    assert has_mahjong_pin(loadout, rules)
    other = Loadout(extras={"pin_effect": "abacus"})
    assert not has_mahjong_pin(other, rules)


def test_mahjong_rack_placement_active_with_red_rack():
    loadout = _mahjong_loadout_with_red_rack()
    rules = ScoringPipeline().rules
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    assert mahjong_rack_placement_active(loadout, board, rules)


def test_mahjong_rack_placement_inactive_during_sandy_boss():
    loadout = _sandy_loadout_with_rack()
    loadout.extras["pin_effect"] = "mahjong_red_dragon"
    rules = ScoringPipeline().rules
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    assert sandy_placement_search_active(loadout, board, rules)
    assert not mahjong_rack_placement_active(loadout, board, rules)


def _generic_loadout_with_rack() -> Loadout:
    return parse_run_state(
        {
            "character": "Cretaceous Meg",
            "extras": {
                "consumable_rack": [
                    {
                        "rack_index": 0,
                        "letter": "G",
                        "char_display": "g",
                        "color": "red",
                        "curse": "letter",
                        "base_score": 3,
                    },
                ],
            },
            "stickers": [],
            "stamps": [],
        }
    )


def test_rack_placement_search_active_generic_character():
    loadout = _generic_loadout_with_rack()
    rules = ScoringPipeline().rules
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    assert rack_placement_search_active(loadout, board, rules)
    assert mahjong_rack_placement_active(loadout, board, rules)


def test_rack_placement_search_active_false_when_sandy_boss():
    loadout = _sandy_loadout_with_rack()
    rules = ScoringPipeline().rules
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    assert sandy_placement_search_active(loadout, board, rules)
    assert not rack_placement_search_active(loadout, board, rules)


def test_remaining_rack_tiles_excludes_placed_by_rack_index():
    loadout = _mahjong_loadout_with_red_rack()
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    placed = _tile("g", 0, 0, was_consumable=True)
    placed.metadata["rack_index"] = 0
    board.tiles[0][0] = placed
    assert remaining_rack_tiles(loadout, board) == []


def test_currency_rack_tile_maps_symbol_to_letter():
    entry = {
        "rack_index": 0,
        "letter": "₲",
        "char_display": "₲",
        "color": "red",
        "curse": "currency",
        "base_score": 1.0,
    }
    tile = rack_tile_from_entry(entry)
    assert tile is not None
    assert tile.letter == "G"
    assert tile.char == "₲"
    assert tile.curse == CurseType.CURRENCY


def test_placement_cell_score_prefers_high_base_score():
    rules = ScoringPipeline().rules
    loadout = _mahjong_loadout_with_red_rack()
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    low = Tile(-1, -1, "A", "A", 1, metadata={"rack_index": 0})
    high = Tile(-1, -1, "Z", "Z", 10, metadata={"rack_index": 1})
    idx = 12
    low_score = _placement_cell_score(
        board, idx, low, loadout=loadout, rules=rules
    )
    high_score = _placement_cell_score(
        board, idx, high, loadout=loadout, rules=rules
    )
    assert high_score > low_score


def test_placement_per_screen_floor_investment():
    assert _placement_per_screen(3.0, 50, investment=True) >= 0.5
    assert _placement_per_screen(3.0, 50, investment=False) >= 0.25


def test_search_consumable_score_boost_adopts_when_improved(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("cat\n", encoding="utf-8")
    d = WordDictionary(wl)
    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _tile("c", 0, 0)
    tiles[0][1] = _tile("a", 0, 1)
    board = Board(tiles=tiles)
    rack = [
        Tile(
            -1,
            -1,
            "T",
            "T",
            5,
            color=TileColor.RED,
            curse=CurseType.LETTER,
            metadata={"rack_index": 0},
        ),
    ]
    loadout = _mahjong_loadout_with_red_rack()
    loadout.extras["consumable_rack"] = [
        {
            "rack_index": 0,
            "letter": "T",
            "color": "red",
            "curse": "letter",
            "base_score": 5,
        }
    ]
    rules = ScoringPipeline().rules
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=4.0)
    baseline_score = 10.0
    sim_board, records, results = search_consumable_score_boost(
        searcher,
        board,
        loadout,
        rack,
        baseline_score=baseline_score,
        time_budget=4.0,
        top_n=3,
        rules=rules,
    )
    assert results
    assert results[0].score > baseline_score
    assert results[0].word == "cat"
    assert len(records) == 1
    assert placed_consumable_indices(sim_board) == frozenset({rec.index for rec in records})
    assert results[0].breakdown.get("consumable_placements")


def test_search_consumable_score_boost_returns_empty_when_not_improved(
    tmp_path, monkeypatch
):
    wl = tmp_path / "words.txt"
    wl.write_text("cat\n", encoding="utf-8")
    d = WordDictionary(wl)
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    rack = [Tile(-1, -1, "Z", "Z", 1, metadata={"rack_index": 0})]
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=2.0)

    def fake_find(board_arg, loadout=None, top_n=1, **kwargs):
        from cursed_words_solver.models import WordResult

        return [WordResult(word="zzz", path=[0], score=500.0, breakdown={})]

    monkeypatch.setattr(searcher, "find_best_words", fake_find)
    _, records, results = search_consumable_score_boost(
        searcher,
        board,
        Loadout(),
        rack,
        baseline_score=500.0,
        time_budget=2.0,
        top_n=1,
    )
    assert not results
    assert not records


def test_rack_requires_export_when_count_without_rack_json():
    loadout = parse_run_state(
        {
            "extras": {
                "consumable_rack_count": "2",
            },
            "stickers": [],
            "stamps": [],
        }
    )
    rules = ScoringPipeline().rules
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    assert rack_requires_export(loadout, board, rules)


def _full_active_board() -> Board:
    return Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])


def _five_tile_rack() -> list[Tile]:
    return [
        Tile(-1, -1, letter, letter, 1, metadata={"rack_index": i})
        for i, letter in enumerate("ABCDE")
    ]


def test_dynamic_max_cells_for_large_rack():
    board = _full_active_board()
    rack = _five_tile_rack()
    cells = _rank_placement_indices(board, rack)
    assert len(cells) <= 10


def test_heap_cap_limits_k5_enumeration():
    board = _full_active_board()
    rack = _five_tile_rack()
    cells = _rank_placement_indices(board, rack)
    tier_cap = _tier_heap_cap(96)
    variants = _top_variants_for_tier(
        board,
        rack,
        cells,
        5,
        tier_cap=tier_cap,
    )
    assert len(variants) <= tier_cap
    assert len(variants) > 0


def test_iter_variants_stops_after_winning_k1_tier(tmp_path, monkeypatch):
    from cursed_words_solver.models import WordResult

    wl = tmp_path / "words.txt"
    wl.write_text("cat\n", encoding="utf-8")
    d = WordDictionary(wl)
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    rack = [
        Tile(-1, -1, "T", "T", 2, metadata={"rack_index": 0}),
        Tile(-1, -1, "Z", "Z", 2, metadata={"rack_index": 1}),
    ]
    searcher = WordSearcher(dictionary=d, min_len=1, max_len=5, time_budget=4.0)

    def qualify_single_placement(sim_board, loadout=None, top_n=1, **kwargs):
        placed = sum(
            1
            for i in range(25)
            if sim_board.get_by_index(i).metadata.get("was_consumable")
        )
        if placed == 1:
            return [WordResult(word="ok", path=[0], score=100.0, breakdown={})]
        return []

    monkeypatch.setattr(searcher, "find_best_words", qualify_single_placement)

    k_values_called: list[int] = []
    real_top_variants = cp._top_variants_for_tier

    def tracking_top_variants(board_arg, rack_arg, cells_arg, k, **kwargs):
        k_values_called.append(k)
        return real_top_variants(board_arg, rack_arg, cells_arg, k, **kwargs)

    monkeypatch.setattr(cp, "_top_variants_for_tier", tracking_top_variants)

    _, records, results = search_target_rescue(
        searcher,
        board,
        Loadout(),
        rack,
        target=50,
        time_budget=4.0,
        top_n=1,
    )
    assert results
    assert records
    assert k_values_called == [1]


def test_variant_gen_budget_limits_tier_generation(tmp_path, monkeypatch):
    wl = tmp_path / "words.txt"
    wl.write_text("a\n", encoding="utf-8")
    d = WordDictionary(wl)
    board = _full_active_board()
    rack = _five_tile_rack()
    k_values_called: list[int] = []
    real_top_variants = cp._top_variants_for_tier

    def tracking_top_variants(board_arg, rack_arg, cells_arg, k, **kwargs):
        k_values_called.append(k)
        return real_top_variants(board_arg, rack_arg, cells_arg, k, **kwargs)

    monkeypatch.setattr(cp, "_top_variants_for_tier", tracking_top_variants)

    searcher = WordSearcher(dictionary=d, min_len=1, max_len=5, time_budget=2.0)

    def never_qualify(board_arg, loadout=None, top_n=1, **kwargs):
        return []

    monkeypatch.setattr(searcher, "find_best_words", never_qualify)

    cp._run_tiered_placement_search(
        searcher,
        board,
        Loadout(),
        rack,
        time_budget=2.0,
        top_n=1,
        min_score=9999.0,
        prefer_fewest_tiles=True,
        variant_gen_budget=0.0,
    )
    assert k_values_called == [1]


def test_lazy_n5_variant_count_bounded():
    board = _full_active_board()
    rack = _five_tile_rack()
    count = sum(1 for _ in iter_placement_variants_fewest_first(board, rack))
    assert count <= 96
    assert count < 10_000


def test_global_solve_deadline_skips_mahjong_when_expired():
    search_budget = 45.0
    search_started = 1000.0
    solve_deadline = search_started + search_budget

    def solve_remaining(now: float) -> float:
        return max(0.0, solve_deadline - now)

    assert solve_remaining(search_started + 44.0) >= 1.0
    assert solve_remaining(search_started + 44.5) < 1.0


def test_swivets_placed_wildcard_no_color_bonus_scores_189():
    """Placed blue wildcard scores base 1 (no synthetic +1), so swivets is 189 not 201.

    Reconstructs the solver's placed board (apply_consumable_placements tags the
    rack tile source=consumable_rack) and confirms the color-bonus fix removes the
    12-point over-prediction captured in 20260605_202155.json.
    """
    import json

    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        prepare_run_state_dict_for_scoring,
    )

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260605_202155.json"
    )
    if not fixture.exists():
        return
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    wildcard = next(
        t for t in consumable_rack_tiles(loadout) if t.curse == CurseType.WILDCARD
    )
    placed = apply_consumable_placements(board, [(8, wildcard)])
    score, _ = ScoringPipeline().score(placed, data["path"], data["word"], loadout)
    assert int(score) == data["actual_score"] == 189


def test_loadout_after_consumable_placements_advances_tile_ninja():
    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={
            "tile_ninja_consumables_used": "10",
            "tile_ninja_bonus": "0",
            "consumable_rack_count": 5,
        },
    )
    after = loadout_after_consumable_placements(loadout, 1)
    assert after.extras["tile_ninja_consumables_used"] == "11"
    assert float(after.extras["tile_ninja_bonus"]) == pytest.approx(0.22)
    assert after.extras["consumable_rack_count"] == 4


def test_deviative_placement_simulation_scores_203():
    """F8 placement sim must not collapse Tile Ninja to ×1.22 (mismatch 20260610_193012)."""
    import json
    from copy import deepcopy

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260610_193012.json"
    )
    if not fixture.is_file():
        pytest.skip("fixture 20260610_193012 not installed")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    rs = deepcopy(data["run_state_snapshot"])
    extras = rs["extras"]
    extras["tile_ninja_bonus"] = "0"
    extras["tile_ninja_bonus_last_known"] = "0"
    extras["tile_ninja_consumables_used"] = "10"
    extras["consumable_rack"] = data["extras_diff"]["consumable_rack"]["f8"]
    board = parse_board_from_run_state(rs)
    loadout = hydrate_tile_ninja_loadout_extras(parse_run_state(rs), rs)
    rack_raw = json.loads(extras["consumable_rack"])
    bishop = rack_tile_from_entry(rack_raw[0])
    placed_board = apply_consumable_placements(board, [(11, bishop)])
    var_loadout = loadout_after_consumable_placements(loadout, 1)
    assert tile_ninja_multiplier_bonus(
        var_loadout, board=placed_board, path=data["path"]
    ) == pytest.approx(0.22)
    score, _ = ScoringPipeline().score(
        placed_board, data["path"], data["word"], var_loadout
    )
    assert int(score) == 203


def test_tile_ninja_used_count_ignores_false_zero_when_bonus_exported():
    assert _tile_ninja_used_count_from_extras(
        {"tile_ninja_consumables_used": "0", "tile_ninja_bonus": "0.2"}
    ) == 10


def test_reawaited_placement_simulation_scores_184():
    """F8 placement sim must not inflate Tile Ninja to ×1.46 (mismatch 20260610_201120)."""
    import json
    from copy import deepcopy

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260610_201120.json"
    )
    if not fixture.is_file():
        pytest.skip("fixture 20260610_201120 not installed")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    rs = deepcopy(data["run_state_snapshot"])
    for key, entry in (data.get("extras_diff") or {}).items():
        if isinstance(entry, dict) and entry.get("f8") not in (None, ""):
            rs["extras"][key] = entry["f8"]
    rs["extras"]["consumable_rack"] = data["extras_diff"]["consumable_rack"]["f8"]
    rs["extras"]["tile_ninja_consumables_used"] = "12"
    rs["extras"]["tile_ninja_bonus"] = "0.24"
    rs["extras"]["tile_ninja_bonus_last_known"] = "0.24"
    rs["extras"]["tile_ninja_bonus_at_grid_start"] = "0.2"
    board = parse_board_from_run_state(rs)
    loadout = hydrate_tile_ninja_loadout_extras(parse_run_state(rs), rs)
    rack_raw = json.loads(rs["extras"]["consumable_rack"])
    letter_a = rack_tile_from_entry(rack_raw[0])
    placed_board = apply_consumable_placements(board, [(11, letter_a)])
    var_loadout = loadout_after_consumable_placements(loadout, 1)
    assert tile_ninja_multiplier_bonus(
        var_loadout, board=placed_board, path=data["path"]
    ) == pytest.approx(0.22)
    score, _ = ScoringPipeline().score(
        placed_board, data["path"], data["word"], var_loadout
    )
    assert int(score) == 184


def test_ibogaine_placement_simulation_scores_154():
    """F8 placement sim must not inflate Tile Ninja to ×1.48 (mismatch 20260610_200505)."""
    import json
    from copy import deepcopy

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260610_200505.json"
    )
    if not fixture.is_file():
        pytest.skip("fixture 20260610_200505 not installed")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    rs = deepcopy(data["run_state_snapshot"])
    for key, entry in (data.get("extras_diff") or {}).items():
        if isinstance(entry, dict) and entry.get("f8") not in (None, ""):
            rs["extras"][key] = entry["f8"]
    rs["extras"]["consumable_rack"] = data["extras_diff"]["consumable_rack"]["f8"]
    rs["extras"]["tile_ninja_consumables_used"] = "13"
    rs["extras"]["tile_ninja_bonus"] = "0.26"
    rs["extras"]["tile_ninja_bonus_last_known"] = "0.26"
    rs["extras"]["tile_ninja_bonus_at_grid_start"] = "0.2"
    board = parse_board_from_run_state(rs)
    loadout = hydrate_tile_ninja_loadout_extras(parse_run_state(rs), rs)
    rack_raw = json.loads(rs["extras"]["consumable_rack"])
    wildcard = rack_tile_from_entry(rack_raw[0])
    placed_board = apply_consumable_placements(board, [(6, wildcard)])
    var_loadout = loadout_after_consumable_placements(loadout, 1)
    assert tile_ninja_multiplier_bonus(
        var_loadout, board=placed_board, path=data["path"]
    ) == pytest.approx(0.22)
    score, _ = ScoringPipeline().score(
        placed_board, data["path"], data["word"], var_loadout
    )
    assert int(score) == 154


def test_warehouse_placement_simulation_scores_286():
    """F8 placement sim must not collapse Tile Ninja to ×1.22 (mismatch 20260610_195716)."""
    import json
    from copy import deepcopy

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260610_195716.json"
    )
    if not fixture.is_file():
        pytest.skip("fixture 20260610_195716 not installed")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    rs = deepcopy(data["run_state_snapshot"])
    for key, entry in (data.get("extras_diff") or {}).items():
        if isinstance(entry, dict) and entry.get("f8") not in (None, ""):
            rs["extras"][key] = entry["f8"]
    rs["extras"]["consumable_rack"] = data["extras_diff"]["consumable_rack"]["f8"]
    rs["extras"]["tile_ninja_consumables_used"] = "10"
    board = parse_board_from_run_state(rs)
    loadout = hydrate_tile_ninja_loadout_extras(parse_run_state(rs), rs)
    rack_raw = json.loads(rs["extras"]["consumable_rack"])
    queen = rack_tile_from_entry(rack_raw[0])
    placed_board = apply_consumable_placements(board, [(11, queen)])
    var_loadout = loadout_after_consumable_placements(loadout, 1)
    assert tile_ninja_multiplier_bonus(
        var_loadout, board=placed_board, path=data["path"]
    ) == pytest.approx(0.22)
    score, _ = ScoringPipeline().score(
        placed_board, data["path"], data["word"], var_loadout
    )
    assert int(score) == 286


def test_live_octacles_up_and_up_rack_ready_for_placement_fallback():
    """Regression: rack wildcards exported and eligible when board-only search fails."""
    from cursed_words_solver.config import resolve_wordlist
    from cursed_words_solver.rules.quest_effects import quest_constraints

    run_state_path = Path.home() / ".cursed_words_solver" / "run_state.json"
    if not run_state_path.is_file():
        pytest.skip("live run_state.json not present")
    raw = load_run_state_raw(run_state_path)
    extras = raw.get("extras") or {}
    quest_class = raw.get("challenge_game_class") or extras.get("challenge_game_class")
    if quest_class != "UpAndUp":
        pytest.skip("run_state is not Up and Up")
    loadout = parse_run_state(raw)
    board = parse_board_from_run_state(raw)
    rules = ScoringPipeline().rules
    rack = remaining_rack_tiles(loadout, board)
    assert len(rack) >= 1
    assert all(t.curse == CurseType.WILDCARD for t in rack)
    assert rack_placement_search_active(loadout, board, rules)
    assert quest_constraints(loadout).require_center_index == 12

    wl_path = resolve_wordlist(None)
    searcher = WordSearcher(
        dictionary=WordDictionary(wl_path),
        min_len=5,
        max_len=25,
        time_budget=8.0,
        search_workers=1,
    )
    sim_board, records, placed_results = search_with_consumable_placements(
        searcher,
        board,
        loadout,
        rack,
        time_budget=12.0,
        top_n=1,
        rules=rules,
    )
    assert sim_board is not None
    if placed_results:
        assert records
        assert all(
            idx in placed_results[0].path
            for idx in placed_consumable_indices(sim_board)
        )


_WESTERNISATIONS_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260616_000741_westernisations.json"
)


def test_placement_screen_floor_hard_up_and_up():
    loadout = parse_run_state(
        {
            "challenge_game_class": "UpAndUp",
            "extras": {"up_and_up_center_index": "12"},
            "stickers": [],
            "stamps": [],
        }
    )
    assert _placement_hard_from_loadout(loadout)
    assert _placement_screen_floor(investment=False, hard=True) == 2.0
    assert _screen_variant_limit(10.0, 2.0, 24) == 5


def test_westernisations_placement_candidates_regression() -> None:
    """Round log 20260616_000741: placement pool must include winning consumable cells."""
    import json

    from cursed_words_solver.consumable_placement import (
        _placement_rank,
        _rank_placement_indices,
        _tier_heap_cap,
        _top_variants_for_tier,
    )
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    if not _WESTERNISATIONS_FIXTURE.is_file():
        pytest.skip("fixture 20260616_000741_westernisations not installed")
    data = json.loads(_WESTERNISATIONS_FIXTURE.read_text(encoding="utf-8"))
    rs = data["run_state_snapshot"]
    board = parse_board_from_run_state(rs)
    loadout = parse_run_state(rs)
    rules = ScoringPipeline().rules
    rack = consumable_rack_tiles(loadout)
    assert len(rack) == 2

    cells = _rank_placement_indices(board, rack, loadout=loadout, rules=rules)
    assert 12 not in cells, "Up and Up center must not be overwritten"
    for idx in data["expected_placement_indices"]:
        assert idx in cells

    tier_cap = _tier_heap_cap(128)
    tier2 = _top_variants_for_tier(
        board, rack, cells, 2, tier_cap=tier_cap, loadout=loadout, rules=rules
    )
    pair_set = {tuple(sorted(i for i, _ in pl)) for pl in tier2}
    expected_pair = tuple(sorted(data["expected_placement_indices"]))
    assert expected_pair in pair_set

    target_placements = [
        (data["expected_placement_indices"][0], rack[0]),
        (data["expected_placement_indices"][1], rack[1]),
    ]
    assert _placement_rank(
        board, target_placements, loadout=loadout, rules=rules
    ) > 0.0


@pytest.mark.slow
def test_westernisations_consumable_fallback_finds_center_word() -> None:
    """Fallback must return a center-using word on the westernisations board (not board-only)."""
    import json

    from cursed_words_solver.config import resolve_wordlist
    from cursed_words_solver.rules.boss_effects import boss_word_constraints
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    if not _WESTERNISATIONS_FIXTURE.is_file():
        pytest.skip("fixture 20260616_000741_westernisations not installed")
    data = json.loads(_WESTERNISATIONS_FIXTURE.read_text(encoding="utf-8"))
    rs = data["run_state_snapshot"]
    board = parse_board_from_run_state(rs)
    loadout = parse_run_state(rs)
    rules = ScoringPipeline().rules
    rack = consumable_rack_tiles(loadout)

    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    wl_path = resolve_wordlist(None)
    searcher = WordSearcher(
        dictionary=WordDictionary(wl_path),
        min_len=max(7, constraints.min_len),
        max_len=min(25, constraints.max_len or 25),
        time_budget=45.0,
        search_workers=1,
    )
    board_only = searcher.find_best_words(board, loadout=loadout, top_n=1)
    assert not board_only, "board-only search should not satisfy Up and Up on this grid"

    sim_board, records, results = search_consumable_placement_fallback(
        searcher,
        board,
        loadout,
        rack,
        time_budget=45.0,
        top_n=1,
        rules=rules,
    )
    assert results, "consumable placement fallback should find a center-using word"
    assert 12 in results[0].path, "Up and Up center tile must be in path"
    assert records
    assert all(idx in results[0].path for idx in (rec.index for rec in records))
