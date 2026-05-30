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


def test_michael_puzzle_grid_stale_modifiers_25_tile_word() -> None:
    """Regression: puzzle finale export clears yeti+whale even when boss_modifiers stale."""
    board = _board()
    loadout = Loadout(
        boss_id="yeti_crab",
        extras={
            "boss_modifiers": ["yeti_crab", "toothed_whale"],
            "boss_modifier_floor_mods": '{"yeti_crab": 4, "toothed_whale": 160}',
            "michael_puzzle_grid": True,
            "michael_min_word_length": 25,
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
