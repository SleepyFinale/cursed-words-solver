"""Effective board for search/scoring after encounter/grid sticker mutations."""

from __future__ import annotations

from cursed_words_solver.models import Board, Loadout, TileColor
from cursed_words_solver.rules.boss_grid_effects import apply_boss_grid_mutations
from cursed_words_solver.rules.grid_effects import (
    apply_start_of_encounter_mutations,
    apply_start_of_grid_mutations,
)


def _board_from_melmod(board: Board, loadout: Loadout | None) -> bool:
    if loadout and str((loadout.extras or {}).get("board_from_melmod", "")).lower() == "true":
        return True
    return any(
        board.is_active_index(t.index) and t.metadata.get("source") == "melmod"
        for t in board.flat
    )


def _skip_cactus_grid_growth(tile) -> bool:
    if tile.metadata.get("was_consumable") is True:
        return True
    return tile.metadata.get("source") == "consumable_rack"


def apply_cactus_grid_growth(board: Board, loadout: Loadout | None) -> Board:
    """Increment CactusGrowth on each cactus tile at grid start (+1 per grid)."""
    if not loadout or _board_from_melmod(board, loadout):
        return board
    first = loadout.extras.get("is_first_grid_of_encounter")
    if first is False or str(first).lower() == "false":
        pass
    for tile in board.flat:
        if not board.is_active_index(tile.index):
            continue
        if tile.color != TileColor.CACTUS:
            continue
        if _skip_cactus_grid_growth(tile):
            continue
        try:
            growth = int(tile.metadata.get("cactus_growth", 1))
        except (TypeError, ValueError):
            growth = 1
        tile.metadata["cactus_growth"] = growth + 1
    return board


def effective_board_for_loadout(
    board: Board,
    loadout: Loadout | None,
    rules: dict,
) -> Board:
    """
    Return board state used for DFS and scoring.

    Melmod exports post-scatter tiles (metadata source=melmod); simulation runs only
    when extras omit board_from_melmod and scatter stickers are present.
    """
    if not loadout:
        return board
    if any(
        board.is_active_index(t.index) and t.metadata.get("source") == "melmod"
        for t in board.flat
    ):
        loadout.extras.setdefault("board_from_melmod", "true")
        b = board
    else:
        b = apply_start_of_encounter_mutations(board, loadout, rules)
        grid_num = int(loadout.extras.get("grid_number") or 1)
        b = apply_boss_grid_mutations(b, loadout, rules, grid_number=grid_num)
        b = apply_start_of_grid_mutations(b, loadout, rules)
    return apply_cactus_grid_growth(b, loadout)
