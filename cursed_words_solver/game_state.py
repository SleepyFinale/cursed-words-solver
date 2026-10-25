"""Melmod ``game_state`` (raw game objects) -> solver ``Board`` / ``Loadout``.

The companion mod dumps the live game objects the engine needs as
``game_state/1`` (``melmod/.../GameStateSerializer.cs``): grid tiles (glyph,
type, letter, number, suit, piece, value, flags, scattered item), every item's
components and fields, boss modifiers, the challenge, previous words with their
tiles, encounter counters, the consumable rack and the Vocabulary accumulator
words. Round logs capture it in the ``SubmitWord`` prefix, so a capture is the
exact state the word was scored against -- nothing to rewind.

- ``extras_from_game_state``: the engine's inputs as exact ``extras`` keys
  (overrides the derived keys of a live ``run_state.json``).
- ``board_from_game_state`` / ``loadout_from_game_state``: a complete solver
  board + loadout (round-log replay, tests).
- ``replay_from_capture``: (board, loadout, path, words, expected score) for a
  round log carrying ``capture``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor

SCHEMA = "game_state/1"

# BossModifier subclass -> wiki boss id (BossResolver.WikiBossIdFromRuntimeType).
BOSS_IDS = {
    "MaxWordLength": "wolf",
    "MinWordLength": "cobra",
    "ReducedLetterValue": "salamander",
    "NegativeMoney": "robo_monkey",
    "StealsMoney": "fox",
    "ExtraVoids": "mole",
    "ExtraQs": "axolotl",
    "AddNumbers": "bison",
    "DiscolourTiles": "yeti_crab",
    "DestroyGrid": "robo_eel",
    "SmallGrid": "bat",
    "FewerGrids": "badger",
    "ForcedSell": "hyena",
    "RandomiseItemOrder": "capybara",
    "BigBoss": "toothed_whale",
    "CretaceousMegBoss": "cretaceous_meg",
    "SandySaguaroBoss": "sandy_saguaro",
    "PrismaticBeanBoss": "prismatic_bean",
    "HumanBoyBoss": "human_boy_boss",
    "MichaelBoss": "michael",
}

_GLYPH_CURSE = {
    "Blank": CurseType.WILDCARD,
    "Letter": CurseType.LETTER,
    "Number": CurseType.NUMBER,
    "Fraction": CurseType.FRACTION,
    "BespokeCard": CurseType.WILDCARD,
    "Currency": CurseType.CURRENCY,
    "Arrow": CurseType.ARROW,
    "ScatteredItem": CurseType.ITEM,
}
_PIECE_CURSE = {
    "Pawn": CurseType.CHESS_PAWN,
    "Knight": CurseType.CHESS_KNIGHT,
    "Bishop": CurseType.CHESS_BISHOP,
    "Rook": CurseType.CHESS_ROOK,
    "Queen": CurseType.CHESS_QUEEN,
    "King": CurseType.CHESS_KING,
}
_TYPE_COLOR = {
    "Normal": TileColor.COLORLESS,
    "Red": TileColor.RED,
    "Blue": TileColor.BLUE,
    "Purple": TileColor.PURPLE,
    "Gold": TileColor.GOLD,
    "Shiny": TileColor.SHINY,
    "Void": TileColor.VOID,
    "White": TileColor.WHITE,
    "Pink": TileColor.PINK,
    "Green": TileColor.GREEN,
    "Cactus": TileColor.CACTUS,
    "Glitch": TileColor.GLITCH,
}


def is_game_state(data: Any) -> bool:
    return isinstance(data, dict) and str(data.get("schema") or "").startswith("game_state/")


def _int(raw: Any, default: int = 0) -> int:
    if raw == "inf":
        return (1 << 63) - 1
    if raw == "-inf":
        return -(1 << 63)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------- board


def _layout(gs: dict[str, Any]) -> tuple[int, int, int]:
    grid = gs.get("grid") or {}
    width = _int(grid.get("width"), 5) or 5
    height = _int(grid.get("height"), 5) or 5
    storage = 6 if max(width, height) > 5 else 5
    return width, height, storage


def storage_index(gs: dict[str, Any], x: int, y: int) -> int:
    """Storage index of game coordinate (x, y), same layout as melmod's board export:
    row ``storage - 1 - y`` (game y = 0 is the bottom row), column ``x``."""
    _width, _height, storage = _layout(gs)
    return (storage - 1 - y) * storage + x


def _tile_from_game(raw: dict[str, Any], row: int, col: int) -> Tile:
    glyph = str(raw.get("glyph") or "Letter")
    piece = str(raw.get("piece") or "None")
    curse = _PIECE_CURSE.get(piece, CurseType.CHESS_PAWN) if glyph == "Chess" else _GLYPH_CURSE.get(glyph, CurseType.LETTER)
    letter = str(raw.get("letter") or "")
    display = str(raw.get("srep") or letter)
    number = _int(raw.get("number"), 0) if glyph == "Number" else None
    fraction = raw.get("fraction") if glyph == "Fraction" else None
    meta: dict[str, Any] = {"source": "melmod", "value_exact": True, "game_tile": raw}
    if glyph == "Chess":
        meta["chess_color"] = "white" if raw.get("white") else "black"
    suit = str(raw.get("suit") or "None")
    if suit != "None":
        meta["card_suit"] = suit.lower()
    if glyph == "BespokeCard":
        meta["is_joker"] = True
    item = raw.get("item") if isinstance(raw.get("item"), dict) else None
    if item is not None:
        from cursed_words_solver.engine.item_data import CLASS_TO_SLUG

        meta["scattered_item_id"] = CLASS_TO_SLUG.get(str(item.get("class") or ""), str(item.get("id") or ""))
        meta["scattered_item_state"] = item
        levels = item.get("levels") or []
        if levels:
            meta["scattered_item_level"] = int(levels[0])
    flags = set(raw.get("flags") or ())
    if "was_consumable" in flags:
        meta["was_consumable"] = True
    if "was_glitch" in flags:
        meta["was_glitch"] = True
    if "crossed_out" in flags:
        meta["is_crossed_out"] = True
    meta["value_modifier"] = _int(raw.get("value_modifier"), 0)
    meta["cactus_growth"] = _int(raw.get("cactus_growth"), 0)
    tile = Tile(
        row=row,
        col=col,
        char=display if glyph != "Letter" else letter.lower(),
        letter=letter.upper() if glyph in ("Letter", "Arrow") else ("?" if curse == CurseType.WILDCARD else letter),
        base_score=float(_int(raw.get("value"), 0)),
        color=_TYPE_COLOR.get(str(raw.get("type") or "Normal"), TileColor.COLORLESS),
        curse=curse,
        number_value=number,
        metadata=meta,
    )
    if isinstance(fraction, list) and len(fraction) >= 2 and fraction[1]:
        tile.fraction_value = float(fraction[0]) / float(fraction[1])
    return tile


def board_from_game_state(gs: dict[str, Any]) -> Board | None:
    """Solver ``Board`` for the captured grid (melmod board-export layout)."""
    grid = gs.get("grid") if isinstance(gs, dict) else None
    if not isinstance(grid, dict) or not isinstance(grid.get("tiles"), list):
        return None
    width, height, storage = _layout(gs)
    cells: list[list[Tile | None]] = [[None] * storage for _ in range(storage)]
    active = [False] * (storage * storage)
    for raw in grid["tiles"]:
        if not isinstance(raw, dict) or "x" not in raw or "y" not in raw:
            continue
        x, y = int(raw["x"]), int(raw["y"])
        if not (0 <= x < width and 0 <= y < height):
            continue
        row, col = storage - 1 - y, x
        tile = _tile_from_game(raw, row, col)
        cells[row][col] = tile
        flags = set(raw.get("flags") or ())
        active[row * storage + col] = raw.get("available", True) is not False and not (flags & {"in_void", "destroyed", "gone"})
    for r in range(storage):
        for c in range(storage):
            if cells[r][c] is None:
                cells[r][c] = Tile(r, c, "", "", 0.0, metadata={"source": "melmod", "inactive": True})
    player = gs.get("player") or {}
    board = Board(tiles=cells, money=_int(player.get("money"), 0), rows=height, cols=width)
    board.active = active
    board.playable_origin = "full" if (width, height) == (storage, storage) else "bottom_left"
    board.playable_min_row, board.playable_max_row = storage - height, storage - 1
    board.playable_min_col, board.playable_max_col = 0, width - 1
    board.captured_at = str(gs.get("captured_at") or "") or None
    return board


# ---------------------------------------------------------------------- extras


def _historic_rows(gs: dict[str, Any]) -> list[dict[str, Any]]:
    """``HistoricWord`` rows in the engine's ``historic_words`` format (exact tile types)."""
    from cursed_words_solver.engine.model import etile_from_game

    rows: list[dict[str, Any]] = []
    for word in (gs.get("encounter") or {}).get("previous_words") or ():
        if not isinstance(word, dict):
            continue
        tiles = [t for t in word.get("tiles") or () if isinstance(t, dict)]
        types = [str(t.get("type") or "Normal").lower() for t in tiles]
        first = etile_from_game(tiles[0], 0, 0, 0).srep if tiles else ""
        rows.append(
            {
                "word": " ".join(str(w) for w in word.get("words") or ()),
                "score": _int(word.get("score"), 0),
                "skipped": bool(word.get("skipped")),
                "tile_types": types,
                "first_srep": first,
                "red_tile_count": sum(1 for t in types if t in ("red", "purple")),
                "green_tile_count": sum(1 for t in types if t == "green"),
            }
        )
    return rows


def extras_from_game_state(gs: dict[str, Any]) -> dict[str, str]:
    """Exact engine inputs from ``game_state`` as ``extras`` (string values, like melmod's)."""
    out: dict[str, str] = {"game_state_schema": str(gs.get("schema") or "")}
    player = gs.get("player") or {}
    encounter = gs.get("encounter") or {}
    run = gs.get("run") or {}
    grid = gs.get("grid") or {}

    if "stickers" in player or "stamps" in player:
        states = {"stickers": player.get("stickers") or [], "stamps": player.get("stamps") or []}
        if isinstance(player.get("pin"), dict):
            states["pin"] = player["pin"]
        out["item_states"] = json.dumps(states)
        out["item_levels_exact"] = "true"
    if "accumulator_words" in player:
        out["accumulator_words"] = json.dumps(list(player.get("accumulator_words") or []))
    consumables = player.get("consumables")
    if isinstance(consumables, list):
        out["consumable_rack_count"] = str(sum(1 for t in consumables if t))

    bosses = [b for b in encounter.get("bosses") or () if isinstance(b, dict)]
    ids: list[str] = []
    floor_mods: dict[str, int] = {}
    for boss in bosses:
        cls = str(boss.get("class") or "")
        fields = boss.get("fields") or {}
        bid = BOSS_IDS.get(cls, cls)
        ids.append(bid)
        floor_mods[bid] = _int(fields.get("FloorAdjustedModification"), 0)
        if cls == "MinWordLength":
            out["encounter_min_word_length"] = str(floor_mods[bid])
            out["cobra_min_length"] = str(floor_mods[bid])
        elif cls == "MaxWordLength":
            out["wolf_max_length"] = str(floor_mods[bid])
        elif cls == "MichaelBoss":
            out["michael_summoned_bosses_defeated"] = "true" if fields.get("SummonedBossesDefeated") else "false"
    out["boss_modifiers"] = json.dumps(ids)
    out["boss_modifier_floor_mods"] = json.dumps(floor_mods)
    if bosses:
        out["boss_floor_modification"] = str(floor_mods.get(ids[0], 0))
    if out.get("michael_summoned_bosses_defeated") == "true":
        out["encounter_min_word_length"] = "25"

    if "grids_generated" in encounter:
        out["grid_number"] = str(_int(encounter.get("grids_generated"), 1))
        out["grid_number_exact"] = out["grid_number"]
    if "remaining_target" in encounter:
        out["encounter_remaining_target"] = str(_int(encounter.get("remaining_target"), 0))
        out["encounter_total_target"] = str(_int(encounter.get("total_target"), 0))
    rows = _historic_rows(gs)
    out["historic_words"] = json.dumps(rows)
    out["historic_words_exact"] = out["historic_words"]
    out["scoring_previous_words_count"] = str(len(rows))
    out["encounter_historic_source"] = "game_state"

    challenge = run.get("challenge") if isinstance(run.get("challenge"), dict) else None
    out["challenge_game_class"] = str(challenge.get("class") or "") if challenge else ""
    if challenge and challenge.get("class") == "UpAndUp":
        width = _int(grid.get("width"), 5)
        height = _int(grid.get("height"), 5)
        out["up_and_up_center_index"] = str(storage_index(gs, width // 2, height // 2))
    if "cursed_bosses_defeated" in run:
        out["cursed_bosses_defeated_count"] = str(len(run.get("cursed_bosses_defeated") or ()))
    if "stage" in run:
        out["run_stage"] = str(run.get("stage"))
        out["run_node_type"] = str(run.get("node_type") or "")
    return out


def loadout_from_game_state(gs: dict[str, Any]) -> Loadout:
    """Solver ``Loadout`` (item ids/levels for display, exact engine extras)."""
    player = gs.get("player") or {}

    def items(key: str, kind: str) -> list[LoadoutItem]:
        out = []
        for row in player.get(key) or ():
            if isinstance(row, dict):
                levels = row.get("levels") or [1]
                out.append(LoadoutItem(str(row.get("id") or ""), str(row.get("class") or ""), int(levels[0] or 1), kind))
        return out

    extras: dict[str, Any] = extras_from_game_state(gs)
    ids = json.loads(extras.get("boss_modifiers") or "[]")
    loadout = Loadout(
        character=str(player.get("character") or ""),
        money=_int(player.get("money"), 0),
        stickers=items("stickers", "sticker"),
        stamps=items("stamps", "stamp"),
        boss_id=ids[0] if ids else "",
        extras=extras,
    )
    return loadout


def attach_game_tiles(board: Board, gs: dict[str, Any]) -> int:
    """Give each live board tile its raw ``game_state`` tile (``metadata["game_tile"]``).

    The engine then reads glyph / type / letter / value exactly instead of
    inferring them from display characters. Returns how many tiles matched.
    """
    grid = gs.get("grid") if isinstance(gs, dict) else None
    if not isinstance(grid, dict):
        return 0
    storage = board.storage_rows
    matched = 0
    for raw in grid.get("tiles") or ():
        if not isinstance(raw, dict) or "x" not in raw or "y" not in raw:
            continue
        row, col = storage - 1 - int(raw["y"]), int(raw["x"])
        if not (0 <= row < storage and 0 <= col < board.storage_cols):
            continue
        tile = board.tiles[row][col]
        if tile is None or not board.is_active_index(row * board.storage_cols + col):
            continue
        tile.metadata["game_tile"] = raw
        matched += 1
    return matched


def sync_game_state_grid_with_board(gs: dict[str, Any], board: Board) -> int:
    """Make ``game_state.grid`` agree with a solver-edited board (inverse of attach).

    Simulated consumable placements replace board tiles but leave the export's
    raw grid tile underneath; re-parsing would re-attach that stale tile and the
    engine would score it instead. Each active cell takes the board tile's own
    ``game_tile`` (re-positioned), or loses its raw entry when it has none so
    the engine reads the board tile. Returns how many raw entries changed.
    """
    grid = gs.get("grid") if isinstance(gs, dict) else None
    if not isinstance(grid, dict) or not isinstance(grid.get("tiles"), list):
        return 0
    storage = board.storage_rows
    changed = 0
    out: list[Any] = []
    for raw in grid["tiles"]:
        if not isinstance(raw, dict) or "x" not in raw or "y" not in raw:
            out.append(raw)
            continue
        row, col = storage - 1 - int(raw["y"]), int(raw["x"])
        if not (0 <= row < storage and 0 <= col < board.storage_cols):
            out.append(raw)
            continue
        tile = board.tiles[row][col]
        if tile is None or not board.is_active_index(row * board.storage_cols + col):
            out.append(raw)
            continue
        own = (tile.metadata or {}).get("game_tile")
        if own is raw:
            out.append(raw)
        elif isinstance(own, dict):
            out.append({**own, "x": raw["x"], "y": raw["y"]})
            changed += own != raw
        else:
            changed += 1
    grid["tiles"] = out
    return changed


def apply_game_state(run_state: dict[str, Any]) -> dict[str, Any]:
    """Live ``run_state.json``: add the engine's exact inputs from its ``game_state``.

    The legacy board (screen layout for the overlay) and the legacy extras stay;
    exact item states, accumulator words, previous words and grid number are
    added under keys only the engine reads. Without ``game_state`` the run
    state is returned unchanged.
    """
    gs = run_state.get("game_state") if isinstance(run_state, dict) else None
    if not is_game_state(gs) or not isinstance(gs.get("player"), dict):
        return run_state
    out = dict(run_state)
    extras = dict(out.get("extras") or {})
    exact = extras_from_game_state(gs)
    # Only keys the engine alone reads: the legacy F8 / staleness code keeps its own.
    for key in _LIVE_KEYS:
        if key in exact:
            extras[key] = exact[key]
    out["extras"] = extras
    return out


_LIVE_KEYS = (
    "game_state_schema",
    "item_states",
    "item_levels_exact",
    "accumulator_words",
    "historic_words_exact",
    "grid_number_exact",
)


# ---------------------------------------------------------------------- replay


@dataclass
class CaptureReplay:
    board: Board
    loadout: Loadout
    path: list[int]
    words: list[str]
    expected: int | None
    two_wrongs: bool
    item_order: list[str]


def replay_from_capture(data: dict[str, Any]) -> tuple[CaptureReplay | None, str]:
    """Round log with ``capture`` (pre-submit game_state + submission) -> replay inputs."""
    capture = data.get("capture") if isinstance(data, dict) else None
    if not isinstance(capture, dict):
        return None, "no capture block"
    gs = capture.get("pre_submit")
    submission = capture.get("submission") or {}
    if not is_game_state(gs):
        return None, "no pre_submit game_state"
    board = board_from_game_state(gs)
    if board is None:
        return None, "no grid in game_state"
    loadout = loadout_from_game_state(gs)
    scoring = capture.get("scoring_call") or {}
    if "grid_number" in scoring:
        loadout.extras["grid_number"] = str(_int(scoring.get("grid_number"), 1))
    if isinstance(scoring.get("item_states"), dict):
        # Slots as CalculateOverallScore saw them (after Capybara's shuffle).
        loadout.extras["item_states"] = json.dumps(scoring["item_states"])
    path = [
        storage_index(gs, int(t["x"]), int(t["y"]))
        for t in submission.get("tiles") or ()
        if isinstance(t, dict) and "x" in t and "y" in t
    ]
    words = [str(w).lower() for w in submission.get("words") or () if str(w)]
    actual = data.get("actual") if isinstance(data.get("actual"), dict) else {}
    expected = _int(actual["score"]) if "score" in actual else None
    challenge = loadout.extras.get("challenge_game_class")
    order = [str(i.get("id") or "") for i in scoring.get("items") or () if isinstance(i, dict)]
    return (
        CaptureReplay(
            board=board,
            loadout=loadout,
            path=path,
            words=words,
            expected=expected,
            two_wrongs=challenge == "TwoWrongs",
            item_order=order,
        ),
        "",
    )
