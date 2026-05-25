"""Start-of-grid boss mutations (when board is not from melmod)."""

from __future__ import annotations

import hashlib
import random

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.boss_effects import (
    boss_context,
    boss_is_cursed,
    boss_rule_applies,
    get_active_boss_rule,
    resolve_boss_scaling,
)
from cursed_words_solver.rules.grid_effects import _clone_board


def _boss_rng(loadout: Loadout, grid_number: int) -> random.Random:
    seed = f"{loadout.boss_id}|{loadout.extras.get('run_seed', '')}|{grid_number}"
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _active_tiles(board: Board) -> list[Tile]:
    return [t for t in board.flat if board.is_active_index(t.index)]


def _scatter_void(board: Board, count: int, rng: random.Random) -> int:
    tiles = _active_tiles(board)
    rng.shuffle(tiles)
    changed = 0
    for tile in tiles[:count]:
        if tile.color != TileColor.VOID:
            tile.color = TileColor.VOID
            changed += 1
    return changed


def _scatter_q(board: Board, count: int, rng: random.Random) -> int:
    tiles = _active_tiles(board)
    rng.shuffle(tiles)
    changed = 0
    for tile in tiles[:count]:
        tile.letter = "Q"
        tile.char = "Q"
        tile.curse = CurseType.LETTER
        changed += 1
    return changed


def _scatter_numbers(board: Board, max_val: int, count: int, rng: random.Random) -> int:
    tiles = _active_tiles(board)
    rng.shuffle(tiles)
    changed = 0
    for tile in tiles[:count]:
        n = rng.randint(max(1, max_val - 3), max_val)
        tile.curse = CurseType.NUMBER
        tile.number_value = n
        tile.letter = str(n)
        tile.char = str(n)
        changed += 1
    return changed


def _yeti_colorless(board: Board, count: int, rng: random.Random) -> int:
    colored = [
        t
        for t in _active_tiles(board)
        if t.color not in (TileColor.COLORLESS, TileColor.UNKNOWN)
    ]
    rng.shuffle(colored)
    changed = 0
    for tile in colored[:count]:
        tile.color = TileColor.COLORLESS
        changed += 1
    return changed


def _robo_eel_eat(board: Board, count: int, rng: random.Random) -> int:
    tiles = _active_tiles(board)
    rng.shuffle(tiles)
    eaten = 0
    for tile in tiles[:count]:
        idx = tile.index
        board.active[idx] = False
        tile.metadata["inactive"] = True
        tile.curse = CurseType.ITEM
        eaten += 1
    return eaten


def _bat_shrink(board: Board, rows: int, cols: int) -> None:
    board.rows = rows
    board.cols = cols
    for tile in board.flat:
        idx = tile.index
        r, c = tile.row, tile.col
        in_play = r < rows and c < cols
        board.active[idx] = in_play
        if not in_play:
            tile.metadata["inactive"] = True


def _fox_grid_steal(board: Board, loadout: Loadout, amount: int) -> None:
    if amount <= 0:
        return
    stolen = min(amount, max(board.money, loadout.money, 0))
    board.money = max(0, board.money - stolen)
    loadout.money = max(0, loadout.money - stolen)
    loadout.extras["fox_stolen_this_grid"] = str(stolen)


def apply_boss_grid_mutations(
    board: Board,
    loadout: Loadout | None,
    rules: dict,
    *,
    grid_number: int = 1,
) -> Board:
    if not loadout or not (loadout.boss_id or loadout.boss_name):
        return board
    if str(loadout.extras.get("board_from_melmod", "")).lower() in ("1", "true"):
        return board
    _key, boss = get_active_boss_rule(rules, loadout)
    if not boss:
        return board
    handler = boss.get("grid_handler") or ""
    if not handler and boss.get("effect_class") != "grid_start":
        return board
    ctx = boss_context(loadout, rules)
    if not boss_rule_applies(boss, ctx):
        return board

    out = _clone_board(board)
    rng = _boss_rng(loadout, grid_number)
    cursed = boss_is_cursed(loadout)

    if handler == "mole_void":
        n = resolve_boss_scaling(boss, ctx.area, ctx.cursed)
        if n is not None:
            _scatter_void(out, int(n), rng)
    elif handler == "axolotl_q":
        n = resolve_boss_scaling(boss, ctx.area, ctx.cursed)
        if n is not None:
            _scatter_q(out, int(n), rng)
    elif handler == "bison_numbers":
        max_n = resolve_boss_scaling(boss, ctx.area, ctx.cursed)
        if max_n is not None:
            _scatter_numbers(out, int(max_n), min(5, int(max_n) - 5), rng)
    elif handler == "yeti_colorless":
        n = resolve_boss_scaling(boss, ctx.area, ctx.cursed)
        if n is not None:
            _yeti_colorless(out, int(n), rng)
    elif handler == "robo_eel_eat":
        n = resolve_boss_scaling(boss, ctx.area, ctx.cursed)
        if n is not None:
            _robo_eel_eat(out, int(n), rng)
    elif handler == "bat_shrink":
        row = None
        col = None
        for entry in boss.get("scaling") or []:
            if entry.get("area") != ctx.area:
                continue
            if cursed:
                row = entry.get("cursed_rows", entry.get("rows"))
                col = entry.get("cursed_cols", entry.get("cols"))
            else:
                row = entry.get("rows")
                col = entry.get("cols")
            break
        if row and col:
            _bat_shrink(out, int(row), int(col))
    elif handler == "fox_grid_steal":
        n = resolve_boss_scaling(boss, ctx.area, ctx.cursed)
        if n is not None:
            _fox_grid_steal(out, loadout, int(n))

    return out
