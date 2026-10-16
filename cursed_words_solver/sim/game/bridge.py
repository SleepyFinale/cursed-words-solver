"""Simulator state → melmod ``game_state/1`` → solver ``Board`` / ``Loadout``.

The engine replays real captures exactly from ``game_state``, so the simulator
speaks the same format: score and search go through ``game_state.board_from_game_state``
/ ``loadout_from_game_state`` with no simulator-specific paths in the engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cursed_words_solver.game_state import board_from_game_state, loadout_from_game_state
from cursed_words_solver.sim.game import core as C
from cursed_words_solver.sim.game.core import Tile, to_game_state_tile

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.models import Board, Loadout
    from cursed_words_solver.sim.game.encounter import Encounter
    from cursed_words_solver.sim.game.player import HistoricWord, Player

_ASCENSION_NAMES = (
    "None", "CursedBosses", "UnkindShops", "LowerTileScores", "LockedStampSlots",
    "HarderGridGeneration", "LockedStickerSlots", "OneFewerGrid", "HarderBosses",
)


def _item_rows(items: list, player: "Player") -> list[dict[str, Any] | None]:
    out: list[dict[str, Any] | None] = []
    for slot, it in enumerate(items):
        if it is None:
            out.append(None)
            continue
        row = it.to_state()
        row["slot"] = slot
        out.append(row)
    return out


def _tile_row(t: Tile | None, player: "Player") -> dict[str, Any] | None:
    return to_game_state_tile(t, player) if t is not None else None


def _historic_row(w: "HistoricWord", player: "Player") -> dict[str, Any]:
    tiles = []
    for i, t in enumerate(w.tiles):
        row = to_game_state_tile(t, player)
        if i < len(w.values):
            row["value"] = w.values[i]
        tiles.append(row)
    return {
        "words": list(w.words),
        "skipped": w.skipped,
        "score": w.score,
        "remainder": w.remainder,
        "round": w.submitted_round,
        "dims": list(w.dims),
        "tiles": tiles,
    }


def player_state(player: "Player") -> dict[str, Any]:
    return {
        "money": player.money,
        "character": player.character,
        "stickers": _item_rows(player.stickers, player),
        "stamps": _item_rows(player.stamps, player),
        "pin": player.pin.to_state() if player.pin is not None else None,
        "consumables": [_tile_row(t, player) for t in player.consumables],
        "accumulator_words": player.accumulator_words(),
        "accumulator_pairs": [],
    }


def run_state(player: "Player") -> dict[str, Any]:
    run = player.run
    out: dict[str, Any] = {
        "stage": run.stage,
        "node_type": run.node.name.title().replace("_", ""),
        "ascension": _ASCENSION_NAMES[min(run.ascension, 8)],
        "cactus_growth_level": run.cactus_growth_level,
        "cursed_bosses_defeated": list(run.cursed_bosses_defeated),
        "available_colours": [C.GAME_TYPE_NAMES.get(c, c) for c in run.available_colours],
        "embargoed_items": sorted(run.embargoed),
    }
    if run.challenge is not None:
        out["challenge"] = {"class": run.challenge.game_class}
    return out


def game_state(enc: "Encounter") -> dict[str, Any]:
    player = enc.player
    grid = enc.grid
    gs: dict[str, Any] = {
        "schema": "game_state/1",
        "captured_at": "",
        "trigger": "sim",
        "grid": {
            "width": grid.width,
            "height": grid.height,
            "grid_number": grid.grid_number,
            "tiles": [to_game_state_tile(t, player) for t in grid.tiles],
        },
        "encounter": {
            "grids_generated": enc.grids_generated,
            "total_target": enc.total_target,
            "remaining_target": enc.remaining_target,
            "remaining_grids": enc.remaining_grids,
            "total_grids": enc.total_grids,
            "rerolls": enc.rerolls,
            "bosses": [b.to_state() for b in enc.bosses],
            "previous_words": [_historic_row(w, player) for w in enc.previous_words],
        },
        "player": player_state(player),
        "run": run_state(player),
    }
    return gs


def board_and_loadout(enc: "Encounter") -> tuple["Board", "Loadout"]:
    gs = game_state(enc)
    board = board_from_game_state(gs)
    loadout = loadout_from_game_state(gs)
    assert board is not None
    return board, loadout


def storage_size(enc: "Encounter") -> int:
    return 6 if max(enc.grid.width, enc.grid.height) > 5 else 5


def coords_to_index(enc: "Encounter", x: int, y: int) -> int:
    s = storage_size(enc)
    return (s - 1 - y) * s + x


def index_to_coords(enc: "Encounter", idx: int) -> tuple[int, int]:
    s = storage_size(enc)
    row, col = divmod(int(idx), s)
    return col, s - 1 - row
