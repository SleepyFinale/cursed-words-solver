"""Boss grid mutations (simulated board)."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.boss_effects import load_rules_catalog
from cursed_words_solver.rules.boss_grid_effects import apply_boss_grid_mutations


def _colorless_board() -> Board:
    tiles = [
        [Tile(r, c, "A", "A", 1, TileColor.COLORLESS, CurseType.LETTER) for c in range(5)]
        for r in range(5)
    ]
    return Board(tiles=tiles, money=10)


def test_mole_scatters_void() -> None:
    rules = load_rules_catalog()
    loadout = Loadout(boss_id="mole", extras={"boss_area_number": 1, "run_seed": "t"})
    out = apply_boss_grid_mutations(_colorless_board(), loadout, rules)
    voids = sum(1 for t in out.flat if t.color == TileColor.VOID)
    assert voids >= 1


def test_axolotl_sets_q() -> None:
    rules = load_rules_catalog()
    loadout = Loadout(boss_id="axolotl", extras={"boss_area_number": 1, "run_seed": "t"})
    out = apply_boss_grid_mutations(_colorless_board(), loadout, rules)
    assert any(t.letter == "Q" for t in out.flat)
