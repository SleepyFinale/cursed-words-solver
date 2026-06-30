"""Michael stacked boss modifiers (draft pool + per-modifier floor scaling)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.boss_effects import (
    active_boss_ids,
    boss_word_constraints,
    floor_mod_for_rule,
    load_rules_catalog,
    michael_finale_active,
    michael_finale_export_expected,
    resolve_boss_scaling_for_rule,
)
from cursed_words_solver.rules.boss_grid_effects import apply_boss_grid_mutations
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import boss_display_name

RULES = load_rules_catalog()
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mismatches"


def _tile(letter: str = "A", color: TileColor = TileColor.COLORLESS) -> Tile:
    return Tile(0, 0, letter, letter, 2, color, CurseType.LETTER)


def _board() -> Board:
    tiles = [
        [_tile("A", TileColor.RED), _tile("B"), _tile("C"), _tile("D"), _tile("E")]
        + [_tile() for _ in range(20)]
    ]
    # 5x5
    grid: list[list[Tile]] = []
    for r in range(5):
        row: list[Tile] = []
        for c in range(5):
            idx = r * 5 + c
            row.append(_tile(chr(ord("A") + idx % 26), TileColor.RED if c == 0 else TileColor.COLORLESS))
        grid.append(row)
    active = [True] * 25
    return Board(tiles=grid, money=10, active=active)


def test_active_boss_ids_filters_meta_michael() -> None:
    loadout = Loadout(
        extras={"boss_modifiers": ["michael", "yeti_crab", "salamander"]},
    )
    assert active_boss_ids(loadout) == ["yeti_crab", "salamander"]


def test_floor_mod_for_rule_from_extras() -> None:
    loadout = Loadout(
        extras={
            "boss_modifier_floor_mods": '{"salamander": 9, "yeti_crab": 6}',
        },
    )
    sal = RULES["bosses"]["salamander"]
    assert floor_mod_for_rule(loadout, RULES, "salamander", sal) == 9
    assert resolve_boss_scaling_for_rule(loadout, RULES, "salamander", sal) == 9


def test_yeti_salamander_stacked_scoring_penalty() -> None:
    board = _board()
    path = list(range(7))
    # trim board to 7 tiles for simple path
    loadout = Loadout(
        boss_id="yeti_crab",
        money=2,
        extras={
            "boss_modifiers": ["yeti_crab", "salamander"],
            "boss_modifier_floor_mods": '{"salamander": 9}',
            "boss_area_number": 1,
            "run_seed": "t",
        },
    )
    pipe = ScoringPipeline()
    _, bd = pipe.score(board, path, "abcdefg", loadout)
    effects = bd.get("pipeline", {}).get("effects", [])
    assert any("-9 per tile (boss)" in e for e in effects)


def test_boss_display_name_stacked() -> None:
    loadout = Loadout(
        extras={"boss_modifiers": ["yeti_crab", "salamander"]},
    )
    name = boss_display_name(loadout, RULES)
    assert "Yeti Crab" in name
    assert "Salamander" in name


def test_boss_display_name_michael_draft_phase() -> None:
    loadout = Loadout(
        boss_id="michael",
        boss_name="Michael",
        extras={
            "michael_phase": 1,
            "boss_area_number": 6,
            "boss_modifiers": ["badger"],
        },
    )
    assert boss_display_name(loadout, RULES) == "Michael"


def test_badger_grid_level_when_boss_id_is_michael() -> None:
    from cursed_words_solver.rules.scoring_conditions import grid_path_sticker_level

    loadout = Loadout(
        boss_id="michael",
        extras={
            "michael_phase": 1,
            "boss_area_number": 6,
            "boss_modifiers": ["badger"],
            "grid_number": 4,
        },
    )
    level = grid_path_sticker_level(loadout, "lucky_scarf")
    assert level >= 4


def test_michael_finale_requires_all_active_tiles() -> None:
    board = _board()
    loadout = Loadout(
        extras={"michael_summoned_bosses_defeated": True},
    )
    c = boss_word_constraints(loadout, RULES, default_max_len=25)
    assert c.min_len == 25
    assert c.max_len == 25


def test_michael_finale_skips_boss_penalties_with_stale_modifiers() -> None:
    board = _board()
    loadout = Loadout(
        money=10,
        extras={
            "michael_summoned_bosses_defeated": True,
            "boss_modifiers": ["salamander"],
            "boss_modifier_floor_mods": '{"salamander": 9}',
        },
    )
    assert michael_finale_active(loadout)
    assert active_boss_ids(loadout) == []
    pipe = ScoringPipeline()
    _, bd = pipe.score(board, list(range(5)), "abcde", loadout)
    effects = bd.get("pipeline", {}).get("effects", [])
    assert not any("per tile (boss)" in e for e in effects)


def test_michael_encounter_finale_corrected_export() -> None:
    """Michael finale on encounter grid: cleared modifiers, 25-tile word only."""
    board = _board()
    loadout = Loadout(
        boss_id="michael",
        extras={
            "boss_modifiers": [],
            "michael_summoned_bosses_defeated": True,
            "michael_min_word_length": 25,
            "michael_phase": 4,
            "boss_area_number": 6,
            "encounter_mode": "encounter",
        },
    )
    assert michael_finale_active(loadout, default_max_len=25)
    assert active_boss_ids(loadout) == []
    c = boss_word_constraints(loadout, RULES, default_max_len=25)
    assert c.min_len == 25
    assert c.max_len == 25
    pipe = ScoringPipeline()
    _, bd = pipe.score(board, list(range(5)), "abcde", loadout)
    effects = bd.get("pipeline", {}).get("effects", [])
    assert not any("per tile (boss)" in e for e in effects)


def test_michael_encounter_finale_fallback_encounter_min_word_length() -> None:
    """Finale export with cleared modifiers and live encounter_min_word_length on area 6."""
    loadout = Loadout(
        boss_id="salamander",
        extras={
            "boss_modifiers": [],
            "boss_area_number": 6,
            "encounter_min_word_length": 25,
            "encounter_mode": "encounter",
            "michael_summoned_bosses_defeated": True,
        },
    )
    assert michael_finale_active(loadout, default_max_len=25)
    assert active_boss_ids(loadout) == []
    c = boss_word_constraints(loadout, RULES, default_max_len=25)
    assert c.min_len == 25
    assert c.max_len == 25


def test_encounter_min_word_length_pins_phase_four_without_summoned_flag() -> None:
    """Live encounter_min_word_length alone pins 25-tile search when phase 4 is exported."""
    loadout = Loadout(
        extras={
            "boss_area_number": 6,
            "encounter_min_word_length": 25,
            "michael_phase": 4,
            "run_stage": "6",
            "run_node_type": "Boss",
        },
    )
    c = boss_word_constraints(loadout, RULES, default_max_len=25)
    assert c.min_len == 25
    assert c.max_len == 25


def test_michael_phase_two_probe_vetoes_false_finale() -> None:
    """Phase 2 wordsmith: probe says draft bosses still active despite stomped finale extras."""
    loadout = Loadout(
        boss_id="michael",
        extras={
            "boss_modifiers": ["capybara", "cobra"],
            "boss_area_number": 6,
            "michael_phase": 4,
            "michael_summoned_bosses_defeated": True,
            "michael_min_word_length": 25,
            "encounter_min_word_length": 25,
            "michael_finale_probe": (
                "finale=1,michael_boss=1,summoned_defeated=0,live_min=25,active_tiles=25"
            ),
            "encounter_mode": "encounter",
        },
    )
    assert not michael_finale_active(loadout, default_max_len=25)
    assert active_boss_ids(loadout) == ["capybara", "cobra"]
    c = boss_word_constraints(loadout, RULES, default_max_len=25)
    assert c.min_len == 7
    assert c.max_len == 25


def test_michael_phase_one_badger_not_finale_expected() -> None:
    """Michael phase 1 wordsmith (badger): not finale; search 1–25."""
    loadout = Loadout(
        boss_id="badger",
        boss_name="FewerGrids",
        extras={
            "boss_area_number": 6,
            "run_stage": "6",
            "run_node_type": "Boss",
            "michael_phase": 1,
            "boss_modifiers": ["badger"],
            "boss_modifier_floor_mods": {"badger": 1},
            "michael_finale_probe": (
                "finale=0,michael_boss=1,summoned_defeated=0,live_min=-,active_tiles=25"
            ),
            "encounter_mode": "encounter",
        },
    )
    assert not michael_finale_export_expected(loadout, default_max_len=25)
    assert not michael_finale_active(loadout, default_max_len=25)
    c = boss_word_constraints(loadout, RULES, default_max_len=25)
    assert c.min_len == 1
    assert c.max_len == 25


def test_michael_finale_export_expected_true_when_defeated() -> None:
    loadout = Loadout(
        extras={
            "michael_summoned_bosses_defeated": True,
            "michael_min_word_length": 25,
            "encounter_min_word_length": 25,
            "michael_finale_probe": (
                "finale=1,michael_boss=1,summoned_defeated=1,live_min=25,active_tiles=25"
            ),
        },
    )
    assert michael_finale_export_expected(loadout, default_max_len=25)

    puzzle = Loadout(
        extras={
            "encounter_mode": "cursedle",
            "cursedle_active": True,
        },
    )
    assert not michael_finale_export_expected(puzzle, default_max_len=25)


def test_michael_phase_two_probe_vetoes_export_expected() -> None:
    """Stale finale extras with probe summoned_defeated=0 must not expect finale export."""
    loadout = Loadout(
        boss_id="michael",
        extras={
            "boss_modifiers": ["capybara", "cobra"],
            "boss_area_number": 6,
            "michael_phase": 4,
            "michael_summoned_bosses_defeated": True,
            "michael_min_word_length": 25,
            "encounter_min_word_length": 25,
            "michael_finale_probe": (
                "finale=1,michael_boss=1,summoned_defeated=0,live_min=25,active_tiles=25"
            ),
            "encounter_mode": "encounter",
        },
    )
    assert not michael_finale_export_expected(loadout, default_max_len=25)


def test_michael_phase_two_user_path_movement_and_word() -> None:
    """Regression: chess path 16-7-18-12-6-1-5 on exported Michael phase 2 board."""
    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.search import PathValidator, path_movement_ok, search_word_from_path
    from cursed_words_solver.dictionary import WordDictionary
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask

    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "michael_phase2_false_finale_export.json"
    if not fixture.is_file():
        pytest.skip(f"fixture not found: {fixture}")

    run_state = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None

    path = [16, 7, 18, 12, 6, 1, 5]
    flags = stamp_search_flags_mask(loadout)
    assert path_movement_ok(board, path, flags=flags)

    word = search_word_from_path(board, path, flags=flags)
    validator = PathValidator(WordDictionary(), min_len=7)
    assert validator.word_ok(board, path, word, flags)

    c = boss_word_constraints(loadout, RULES, default_max_len=25)
    assert c.min_len == 7
    assert c.max_len == 25


def test_michael_phase_two_cobra_min_without_probe() -> None:
    loadout = Loadout(
        boss_id="cobra",
        extras={
            "boss_modifiers": ["capybara", "cobra"],
            "boss_area_number": 5,
            "michael_phase": 2,
            "encounter_mode": "encounter",
        },
    )
    assert not michael_finale_active(loadout, default_max_len=25)
    c = boss_word_constraints(loadout, RULES, default_max_len=25)
    assert c.min_len == 7
    assert c.max_len == 25


def test_michael_puzzle_encounter_mode_stale_modifiers_25_tile_word() -> None:
    """Regression: puzzle encounter_mode clears yeti+whale when finale min length applies."""
    board = _board()
    loadout = Loadout(
        boss_id="yeti_crab",
        extras={
            "boss_modifiers": ["yeti_crab", "toothed_whale"],
            "boss_modifier_floor_mods": '{"yeti_crab": 4, "toothed_whale": 160}',
            "michael_min_word_length": 25,
            "michael_summoned_bosses_defeated": True,
            "encounter_mode": "puzzle",
        },
    )
    assert michael_finale_active(loadout, default_max_len=25)
    assert active_boss_ids(loadout) == []
    c = boss_word_constraints(loadout, RULES, default_max_len=25)
    assert c.min_len == 25
    assert c.max_len == 25
    name = boss_display_name(loadout, RULES)
    assert "Yeti Crab" not in name
    assert "Toothed Whale" not in name


def test_michael_finale_skips_boss_penalties() -> None:
    board = _board()
    loadout = Loadout(
        money=10,
        extras={
            "michael_summoned_bosses_defeated": True,
            "boss_modifiers": ["salamander"],
            "boss_modifier_floor_mods": '{"salamander": 9}',
        },
    )
    pipe = ScoringPipeline()
    _, bd = pipe.score(board, list(range(5)), "abcde", loadout)
    effects = bd.get("pipeline", {}).get("effects", [])
    assert not any("per tile (boss)" in e for e in effects)


def test_grid_stack_mole_and_yeti() -> None:
    board = _board()
    loadout = Loadout(
        extras={
            "boss_modifiers": ["mole", "yeti_crab"],
            "boss_modifier_floor_mods": '{"mole": 3, "yeti_crab": 2}',
            "boss_area_number": 1,
            "run_seed": "stack",
        },
    )
    out = apply_boss_grid_mutations(board, loadout, RULES, grid_number=1)
    voids = sum(1 for t in out.flat if t.color == TileColor.VOID)
    colorless = sum(
        1
        for t in out.flat
        if t.color == TileColor.COLORLESS and board.get_by_index(t.index).color == TileColor.RED
    )
    assert voids >= 1
    assert colorless >= 1


def test_wessand_michael_mismatch_replay() -> None:
    case_path = FIXTURES / "20260527_201129.json"
    if not case_path.is_file():
        pytest.skip("fixture 20260527_201129 not installed")
    from tests.regression.test_scoring_mismatches import _run_state_for_replay
    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    data = json.loads(case_path.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    extras = dict(run_state.get("extras") or {})
    extras["boss_modifier_floor_mods"] = json.dumps(
        {"salamander": 9, "yeti_crab": 6}
    )
    run_state["extras"] = extras
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    score, bd = ScoringPipeline().score(
        board, data["path"], data["word"], loadout
    )
    effects = bd.get("pipeline", {}).get("effects", [])
    assert any("-9 per tile (boss)" in e for e in effects)
    assert int(score) == int(data["actual_score"])
