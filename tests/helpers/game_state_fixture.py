"""Build melmod ``game_state/1`` captures from legacy captures (tests only).

Real ``capture`` blocks come from ``GameStateSerializer.cs``. To test the
Python side without the game, a legacy round log is first resolved to its
pre-submit state (``prepare_replay``), then re-expressed with the same field
names the serializer writes.
"""

from __future__ import annotations

import json
from typing import Any

from cursed_words_solver.game_state import BOSS_IDS
from cursed_words_solver.models import Board, CurseType

_PIECES = {
    CurseType.CHESS_PAWN: "Pawn",
    CurseType.CHESS_KNIGHT: "Knight",
    CurseType.CHESS_BISHOP: "Bishop",
    CurseType.CHESS_ROOK: "Rook",
    CurseType.CHESS_QUEEN: "Queen",
    CurseType.CHESS_KING: "King",
}
_TYPES = {
    "normal": "Normal", "red": "Red", "blue": "Blue", "purple": "Purple", "gold": "Gold",
    "shiny": "Shiny", "void": "Void", "white": "White", "pink": "Pink", "green": "Green",
    "cactus": "Cactus", "glitch": "Glitch",
}
_GLYPHS = {
    "blank": "Blank", "letter": "Letter", "number": "Number", "fraction": "Fraction",
    "chess": "Chess", "bespoke_card": "BespokeCard", "currency": "Currency", "arrow": "Arrow",
    "scattered_item": "ScatteredItem", "none": "None",
}


def _raw_tile(board: Board, idx: int) -> dict[str, Any]:
    """Serializer-shaped tile from the engine's view of a legacy board tile."""
    from cursed_words_solver.engine.model import EGrid

    et = EGrid(board).tiles[idx]
    tile = board.get_by_index(idx) if board.is_active_index(idx) else None
    meta = (tile.metadata if tile is not None else {}) or {}
    raw: dict[str, Any] = {
        "x": board.coords_at(idx)[1],
        "y": board.storage_rows - 1 - board.coords_at(idx)[0],
        "glyph": _GLYPHS[et.glyph],
        "type": _TYPES[et.tile_type],
        "letter": et.symbol if et.glyph == "currency" else et.letter.upper(),
        "number": et.number if et.number is not None else -1000,
        "fraction": list(et.fraction) if et.fraction else [],
        "suit": et.suit.capitalize() if et.suit != "none" else "None",
        "piece": _PIECES.get(tile.curse, "None") if tile is not None else "None",
        "white": et.white,
        "value": et.value,
        "value_modifier": int(meta.get("value_modifier") or 0),
        "available": not et.in_void,
        "flags": [f for f, on in (("was_consumable", et.was_consumable), ("was_glitch", et.was_glitch),
                                  ("crossed_out", et.crossed_out)) if on],
    }
    if et.glyph == "scattered_item":
        state = meta.get("scattered_item_state")
        if isinstance(state, dict):
            raw["item"] = state
        else:
            from cursed_words_solver.engine.item_data import ITEMS

            info = ITEMS.get(et.item)
            raw["item"] = {"id": et.item, "class": info.cls if info else "", "levels": [et.item_level or 1]}
    return raw


def _json(raw: Any, default: Any) -> Any:
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default
    return default


def capture_from_legacy(data: dict[str, Any]) -> dict[str, Any] | None:
    """A round log with a synthetic ``capture`` block equivalent to ``data``."""
    from cursed_words_solver.sim.replay import prepare_replay

    prep, _err = prepare_replay(data)
    if prep is None or prep.expected is None:
        return None
    board, loadout = prep.board, prep.loadout
    extras = loadout.extras
    if extras.get("item_states") in (None, ""):
        return None  # legacy item levels: not expressible exactly
    states = _json(extras["item_states"], {})
    ids = _json(extras.get("boss_modifiers"), [])
    floor = _json(extras.get("boss_modifier_floor_mods"), {})
    classes = {v: k for k, v in BOSS_IDS.items()}
    bosses = []
    for bid in ids:
        fields: dict[str, Any] = {"FloorAdjustedModification": int(floor.get(bid, extras.get("boss_floor_modification") or 0) or 0)}
        if bid == "michael":
            fields["SummonedBossesDefeated"] = str(extras.get("michael_summoned_bosses_defeated")).lower() == "true"
        bosses.append({"class": classes.get(bid, bid), "fields": fields})
    from cursed_words_solver.engine.calc import _historic_words

    prev = []
    for i, hw in enumerate(_historic_words(extras)):
        types = ["Red"] * hw.red_count + ["Green"] * hw.green_count
        first = {"glyph": "Letter", "type": "Normal", "letter": hw.first_srep.upper()} if hw.first_is_letter else None
        tiles = ([first] if first else []) + [{"glyph": "Letter", "type": t, "letter": "X"} for t in types]
        prev.append({"words": ["x"], "skipped": hw.skipped, "score": hw.score, "tiles": tiles})
    width = board.playable_max_col - board.playable_min_col + 1
    height = board.playable_max_row - board.playable_min_row + 1
    rack = int(extras.get("consumable_rack_count") or 0)
    gs = {
        "schema": "game_state/1",
        "trigger": "test",
        "grid": {
            "width": width,
            "height": height,
            "tiles": [_raw_tile(board, i) for i in range(board.cell_count) if board.is_active_index(i)],
        },
        "encounter": {
            "grids_generated": int(extras.get("grid_number") or 1),
            "bosses": bosses,
            "previous_words": prev,
        },
        "player": {
            "money": loadout.money,
            "stickers": states.get("stickers") or [],
            "stamps": states.get("stamps") or [],
            **({"pin": states["pin"]} if isinstance(states.get("pin"), dict) else {}),
            "consumables": [{"glyph": "Letter"}] * rack,
            "accumulator_words": _json(extras.get("accumulator_words"), []),
        },
        "run": {
            "challenge": {"class": extras.get("challenge_game_class") or "", "fields": {}} if extras.get("challenge_game_class") else None,
            "cursed_bosses_defeated": [0] * int(extras.get("cursed_bosses_defeated_count") or 0),
        },
    }
    tiles = []
    for idx in prep.submission.path:
        r, c = board.coords_at(idx)
        tiles.append({"x": c, "y": board.storage_rows - 1 - r, "method": "Adjacent"})
    actual_word = str((data.get("actual") or {}).get("word") or "").lower()
    words = actual_word.split() if actual_word.isalpha() else prep.submission.effective_scoring_word.split()
    return {
        "round_id": data.get("round_id", ""),
        "actual": {"score": prep.expected, "word": " ".join(words)},
        "capture": {"pre_submit": gs, "submission": {"words": words, "tiles": tiles}, "scoring_call": {"grid_number": int(extras.get("grid_number") or 1)}},
    }
