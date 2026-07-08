"""Loadout capture: MelonLoader JSON and manual UI."""

from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path
from typing import Any

from cursed_words_solver.config import RUN_STATE_PATH
from cursed_words_solver.rules.rule_lookup import slugify_name
from cursed_words_solver.rules.fraction_tiles import attach_fraction_metadata
from cursed_words_solver.models import (
    CURRENCY_MAP,
    DEFAULT_GRID_SIZE,
    MAX_GRID_SIZE,
    Board,
    CurseType,
    EncounterGridRerollState,
    Loadout,
    LoadoutItem,
    SellCandidate,
    ShopOffer,
    ShopState,
    Tile,
    TileColor,
    curse_type_from_key,
    normalize_tile_glyph,
)

_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "game" / "tile_taxonomy.json"
_VALID_COLORS: set[str] | None = None
_VALID_CURSES: set[str] | None = None


def _taxonomy_sets() -> tuple[set[str], set[str]]:
    global _VALID_COLORS, _VALID_CURSES
    if _VALID_COLORS is not None and _VALID_CURSES is not None:
        return _VALID_COLORS, _VALID_CURSES
    colors: set[str] = {c.value for c in TileColor}
    curses: set[str] = {c.value for c in CurseType}
    if _TAXONOMY_PATH.is_file():
        try:
            tax = json.loads(_TAXONOMY_PATH.read_text(encoding="utf-8"))
            colors = {r["solver_color"] for r in tax.get("colors", [])} | colors
            curses = {r["solver_curse"] for r in tax.get("curses", [])} | curses
            curses |= {"wildcard", "chess_pawn", "chess_rook", "chess_bishop", "chess_knight", "chess_queen", "chess_king"}
        except (json.JSONDecodeError, KeyError):
            pass
    _VALID_COLORS, _VALID_CURSES = colors, curses
    return _VALID_COLORS, _VALID_CURSES


def _read_run_state_json(
    path: Path,
    *,
    retries: int = 12,
    delay_sec: float = 0.04,
) -> dict[str, Any] | None:
    """Parse run_state.json (melmod writes UTF-8 with BOM on Windows).

    Retries briefly when melmod replaces the file atomically (Windows can lock or
    remove the path for a moment between delete and move).
    """
    for attempt in range(max(1, retries)):
        try:
            if not path.exists():
                raise FileNotFoundError(path)
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            if attempt + 1 >= retries:
                return None
            time.sleep(delay_sec)
    return None


def load_run_state_raw(path: Path | None = None) -> dict[str, Any] | None:
    """Load raw run_state.json dict from companion mod or manual edit."""
    path = path or RUN_STATE_PATH
    return _read_run_state_json(path)


_BICYCLE_POST_EXTRAS = frozenset({"bicycle_word_score_bonus", "cards_submitted"})


def merge_extras_diff_submit(extras: dict[str, Any], data: dict[str, Any]) -> None:
    """Apply melmod submit-time extras when F8 snapshot lagged."""
    diff = data.get("extras_diff")
    if not isinstance(diff, dict):
        return
    for key, entry in diff.items():
        if not isinstance(entry, dict):
            continue
        submit_val = entry.get("submit")
        if submit_val in (None, ""):
            continue
        extras[key] = submit_val


BOSS_RECONCILE_EXTRA_KEYS = (
    "boss_modifiers",
    "boss_modifier_floor_mods",
    "boss_cursed",
    "boss_area_number",
    "boss_floor_modification",
)

FINALE_BOSS_EMBED_KEYS = (
    "michael_phase",
    "michael_min_word_length",
    "encounter_min_word_length",
    "michael_finale_probe",
    "michael_summoned_bosses_defeated",
)


def _boss_modifiers_active(raw: Any) -> bool:
    if raw is None:
        return False
    if isinstance(raw, list):
        return len(raw) > 0
    text = str(raw).strip()
    return bool(text) and text not in ("[]", "")


def reconcile_boss_extras_from_extras_diff(
    extras: dict[str, Any],
    data: dict[str, Any],
    *,
    run_state: dict[str, Any] | None = None,
) -> None:
    """Drop stale F8 boss fields when submit-time scoring used no boss modifiers."""
    diff = data.get("extras_diff")
    if not isinstance(diff, dict):
        return
    for key in ("boss_modifiers", "boss_modifier_floor_mods"):
        entry = diff.get(key)
        if not isinstance(entry, dict):
            continue
        f8_val = str(entry.get("f8") or "").strip()
        submit_val = str(entry.get("submit") or "").strip()
        if not f8_val or submit_val:
            continue
        for boss_key in BOSS_RECONCILE_EXTRA_KEYS:
            extras.pop(boss_key, None)
        if isinstance(run_state, dict):
            run_state["boss_id"] = ""
            run_state["boss_name"] = ""
            run_state["boss_effect"] = ""
        return


def reconcile_boss_extras_for_f8_embed(
    run_state: dict[str, Any],
    *,
    allow_disk_reconcile: bool = False,
    fresh_run_state: dict[str, Any] | None = None,
) -> None:
    """Prefer live boss projection when F8 embed carries stale boss from a prior fight."""
    if not isinstance(run_state, dict):
        return
    extras = run_state.get("extras")
    if not isinstance(extras, dict):
        return
    fresh: dict[str, Any] | None = (
        fresh_run_state if isinstance(fresh_run_state, dict) else None
    )
    if fresh is None:
        if not allow_disk_reconcile:
            return
        fresh = load_run_state_raw()
    if not isinstance(fresh, dict):
        return
    fresh_extras = fresh.get("extras")
    if not isinstance(fresh_extras, dict):
        fresh_extras = {}
    embed_has = _boss_modifiers_active(extras.get("boss_modifiers")) or bool(
        str(run_state.get("boss_id") or "").strip()
    )
    fresh_has = _boss_modifiers_active(fresh_extras.get("boss_modifiers")) or bool(
        str(fresh.get("boss_id") or "").strip()
    )
    fresh_mods = str(fresh_extras.get("boss_modifiers") or "").strip()
    embed_mods = str(extras.get("boss_modifiers") or "").strip()
    if (
        _boss_modifiers_active(fresh_extras.get("boss_modifiers"))
        and fresh_mods != embed_mods
    ):
        for key in BOSS_RECONCILE_EXTRA_KEYS:
            if key in fresh_extras:
                extras[key] = fresh_extras[key]
            else:
                extras.pop(key, None)
        for field in ("boss_id", "boss_name", "boss_effect"):
            if field in fresh:
                run_state[field] = fresh[field]
            else:
                run_state[field] = ""
        return
    if not embed_has or fresh_has:
        return
    for key in BOSS_RECONCILE_EXTRA_KEYS:
        extras.pop(key, None)
    run_state["boss_id"] = ""
    run_state["boss_name"] = ""
    run_state["boss_effect"] = ""


def merge_extras_snapshot_into(extras: dict[str, Any], snapshot: dict[str, Any]) -> None:
    """Merge submit-time extras_snapshot (skip Bicycle post-submit counters)."""
    if not isinstance(snapshot, dict):
        return
    for key, value in snapshot.items():
        if key in _BICYCLE_POST_EXTRAS:
            continue
        if value in (None, ""):
            continue
        extras[key] = value


def merge_submit_board_tile_state(run_state: dict[str, Any], data: dict[str, Any]) -> None:
    """Apply submit-time board tile fields when F8 snapshot predates melmod merge."""
    submit_tiles = data.get("submit_board_tiles")
    if not isinstance(submit_tiles, list):
        return
    board = run_state.get("board")
    if not isinstance(board, dict):
        return
    tiles = board.get("tiles")
    if not isinstance(tiles, list):
        return
    submit_at: dict[tuple[int, int], dict[str, Any]] = {}
    for entry in submit_tiles:
        if not isinstance(entry, dict):
            continue
        try:
            key = (int(entry["row"]), int(entry["col"]))
        except (KeyError, TypeError, ValueError):
            continue
        submit_at[key] = entry
    if not submit_at:
        return
    merge_fields = (
        "color",
        "curse",
        "letter",
        "char",
        "base_score",
        "void_penalty_steps",
        "scattered_item_id",
        "scattered_item_level",
        "cactus_growth",
    )
    for tile in tiles:
        if not isinstance(tile, dict):
            continue
        key = (int(tile.get("row", -1)), int(tile.get("col", -1)))
        submit = submit_at.get(key)
        if submit is None:
            continue
        if submit.get("take"):
            tile["take"] = True
        if submit.get("was_consumable") in (True, "true", "True", "1", 1):
            tile["was_consumable"] = True
        if submit.get("consumable") in (True, "true", "True", "1", 1):
            tile["consumable"] = True
        for field in merge_fields:
            if field not in submit:
                continue
            value = submit[field]
            if value is not None and value != "":
                tile[field] = value
            elif field == "cactus_growth" and submit.get(field) == 0:
                tile[field] = 0
            elif field == "base_score" and submit.get(field) == 0:
                tile[field] = 0.0


def merge_submit_board_take_flags(run_state: dict[str, Any], data: dict[str, Any]) -> None:
    """Backward-compatible alias for submit-time board merge."""
    merge_submit_board_tile_state(run_state, data)


def prepare_run_state_dict_for_scoring(data: dict[str, Any]) -> dict[str, Any]:
    """Merge submit-time fields into run_state before scoring (live or replay)."""
    run_state = dict(data)
    extras = dict(run_state.get("extras") or {})
    merge_extras_snapshot_into(extras, data.get("extras_snapshot") or {})
    merge_extras_diff_submit(extras, data)
    reconcile_boss_extras_from_extras_diff(extras, data, run_state=run_state)
    if extras:
        run_state["extras"] = extras
    merge_submit_board_tile_state(run_state, data)
    if isinstance(run_state.get("extras"), dict):
        board = parse_board_from_run_state(run_state)
        reconcile_encounter_historic_for_scoring(
            run_state["extras"],
            board=board,
        )
        loadout = parse_run_state(run_state)
        align_bicycle_extras_from_fingerprint(run_state["extras"], loadout)
    return run_state


def load_run_state(path: Path | None = None) -> Loadout | None:
    """Load run state exported by companion mod or manual JSON."""
    data = load_run_state_raw(path)
    if data is None:
        return None
    return parse_run_state(prepare_run_state_dict_for_scoring(data))


def mod_money_from_run_state(data: dict[str, Any] | None) -> int:
    """Player money from melmod export (top-level or board snapshot)."""
    if not data:
        return 0
    board = data.get("board")
    if isinstance(board, dict):
        board_money = board.get("money")
        if board_money is not None:
            return int(board_money)
    return int(data.get("money", 0))


_COLOR_MAP: dict[str, TileColor] = {
    "colorless": TileColor.COLORLESS,
    "red": TileColor.RED,
    "blue": TileColor.BLUE,
    "shiny": TileColor.SHINY,
    "void": TileColor.VOID,
    "purple": TileColor.PURPLE,
    "white": TileColor.WHITE,
    "gold": TileColor.GOLD,
    "pink": TileColor.PINK,
    "green": TileColor.GREEN,
    "cactus": TileColor.CACTUS,
    "glitch": TileColor.GLITCH,
    "unknown": TileColor.UNKNOWN,
}

_CURSE_MAP: dict[str, CurseType] = {
    "letter": CurseType.LETTER,
    "wildcard": CurseType.WILDCARD,
    "currency": CurseType.CURRENCY,
    "number": CurseType.NUMBER,
    "fraction": CurseType.FRACTION,
    "chess_pawn": CurseType.CHESS_PAWN,
    "chess_bishop": CurseType.CHESS_BISHOP,
    "chess_rook": CurseType.CHESS_ROOK,
    "chess_knight": CurseType.CHESS_KNIGHT,
    "chess_queen": CurseType.CHESS_QUEEN,
    "chess_king": CurseType.CHESS_KING,
    "item": CurseType.ITEM,
    "card": CurseType.CARD,
    "arrow": CurseType.ARROW,
    "blank": CurseType.BLANK,
    "unknown": CurseType.UNKNOWN,
}


def _resolve_letter_for_word(char: str, letter: str, curse: CurseType) -> str:
    if curse in {
        CurseType.CHESS_PAWN,
        CurseType.CHESS_BISHOP,
        CurseType.CHESS_ROOK,
        CurseType.CHESS_KNIGHT,
        CurseType.CHESS_QUEEN,
        CurseType.CHESS_KING,
    }:
        return "?"
    if curse == CurseType.WILDCARD:
        return "?"
    if curse == CurseType.CURRENCY:
        sym = normalize_tile_glyph(char or letter)
        if sym in CURRENCY_MAP:
            return CURRENCY_MAP[sym]
        if len(letter) == 1 and letter.isalpha():
            return letter.upper()
        return "?"
    if curse == CurseType.NUMBER:
        return letter if letter else char
    if curse == CurseType.FRACTION:
        return "?"
    if curse == CurseType.CARD:
        ch = (letter or char or "?").strip().upper()
        return ch[:1] if ch else "?"
    ch = (letter or char or "?").strip().upper()
    if len(ch) == 1 and (ch.isalpha() or ch.isdigit() or ch == "?"):
        return ch
    return "?"


def _melmod_row_to_solver(board_data: dict[str, Any], game_row: int) -> int:
    """Map melmod row index to solver row (0 = top of screen)."""
    if board_data.get("row_order") == "top_first":
        return game_row
    # Legacy exports: Unity grid row 0 is the bottom row on screen.
    return 4 - game_row


def melmod_board_available(data: dict[str, Any] | None) -> bool:
    """True when run_state.json contains a valid melmod board export."""
    return parse_board_from_run_state(data) is not None


def melmod_install_hint() -> str:
    """User-facing steps when the companion mod export is missing."""
    from cursed_words_solver.f8_messages import F8_RETRY_HINT

    return (
        "Install the MelonLoader companion mod (see melmod/README.md in the repo), "
        f"start a run in-game, then {F8_RETRY_HINT}."
    )


def is_run_state_template(data: dict[str, Any] | None) -> bool:
    if not data:
        return True
    if data.get("character") == "Example":
        return True
    board = data.get("board")
    if isinstance(board, dict) and board.get("source") != "melmod":
        return not melmod_board_available(data)
    return not melmod_board_available(data) and not (
        data.get("stickers") or data.get("extras", {}).get("pin_effect")
    )


def parse_board_from_run_state(data: dict[str, Any] | None) -> Board | None:
    """Build Board from melmod board export in run_state.json."""
    if not data:
        return None
    board_data = data.get("board")
    if not isinstance(board_data, dict):
        return None
    tiles_raw = board_data.get("tiles")
    if not isinstance(tiles_raw, list) or len(tiles_raw) not in (25, 36):
        return None

    storage = 6 if len(tiles_raw) == 36 else DEFAULT_GRID_SIZE
    max_row = storage - 1
    max_col = storage - 1

    money = mod_money_from_run_state(data)
    grid: list[list[Tile | None]] = [[None] * storage for _ in range(storage)]
    active = [False] * (storage * storage)

    try:
        board_rows = int(board_data.get("rows", storage))
        board_cols = int(board_data.get("cols", storage))
    except (TypeError, ValueError):
        board_rows, board_cols = storage, storage
    board_rows = max(1, min(storage, board_rows))
    board_cols = max(1, min(storage, board_cols))

    for entry in tiles_raw:
        if not isinstance(entry, dict):
            return None
        game_row = int(entry.get("row", -1))
        col = int(entry.get("col", -1))
        if game_row < 0 or game_row > max_row or col < 0 or col > max_col:
            return None
        row = _melmod_row_to_solver(board_data, game_row)
        idx = row * storage + col

        curse_key = str(entry.get("curse", "letter") or "letter").lower()
        is_active = entry.get("active", True)
        if curse_key == "inactive":
            is_active = False
        if is_active in (False, "false", "False", "0", 0):
            is_active = False
        else:
            is_active = True
        active[idx] = bool(is_active)

        raw_char_display = str(entry.get("char", entry.get("char_display", "?")) or "?")
        raw_letter_display = str(entry.get("letter", raw_char_display) or raw_char_display)

        # Joker tiles can be exported inconsistently across game/mod versions.
        # Prefer explicit `is_joker`; fall back to 🃏 glyph only when the tile does not
        # carry a stable letter face (some non-joker tiles can still render the glyph).
        is_joker_glyph = "🃏" in (raw_char_display + raw_letter_display)
        is_joker_exported = entry.get("is_joker") in (True, "true", "True", "1", 1)

        char = normalize_tile_glyph(raw_char_display)
        letter_raw = normalize_tile_glyph(raw_letter_display)
        color_key = str(entry.get("color", "colorless") or "colorless").lower()
        if not is_active:
            curse_key = "inactive"
            char = ""
            letter_raw = ""
            color_key = "colorless"

        treat_as_joker = bool(is_joker_exported)
        if (
            not treat_as_joker
            and is_active
            and is_joker_glyph
            and curse_key != "inactive"
        ):
            # Only coerce 🃏 glyph tiles to wildcard when the export does not provide a
            # stable letter. Otherwise, keep the letter tile semantics (the glyph can
            # appear for other effects).
            if (letter_raw or "").strip() in ("", "?"):
                treat_as_joker = True
            elif curse_key in ("wildcard", "blank"):
                treat_as_joker = True
            else:
                # VOID + base_score 0 joker-glyph tiles behave like wildcards in scoring
                # (e.g. Wrestlers endpoint shortcut).
                try:
                    base_score = float(entry.get("base_score", 0) or 0)
                except (TypeError, ValueError):
                    base_score = 0.0
                if color_key == "void" or base_score == 0.0:
                    treat_as_joker = True
                # Some joker-glyph tiles export with a letter face but behave as
                # wildcards; empirically these tend to be low-score non-red tiles.
                elif base_score == 1.0 and color_key != "red":
                    treat_as_joker = True
        if treat_as_joker and is_active and curse_key != "inactive":
            curse_key = "wildcard"
            letter_raw = "?"

        valid_colors, valid_curses = _taxonomy_sets()
        if color_key not in valid_colors and color_key != "inactive":
            color_key = "unknown"
        if curse_key not in valid_curses and curse_key != "inactive":
            curse_key = "unknown"
        color = _COLOR_MAP.get(color_key, TileColor.UNKNOWN)
        curse = curse_type_from_key(curse_key)
        if curse == CurseType.UNKNOWN:
            curse = _CURSE_MAP.get(curse_key, CurseType.UNKNOWN)
        letter = _resolve_letter_for_word(char, letter_raw, curse) if is_active else ""

        number_value = entry.get("number_value")
        fraction_value = entry.get("fraction_value")

        meta: dict[str, Any] = {"source": "melmod"}
        if not is_active:
            meta["inactive"] = True
        if entry.get("consumable"):
            meta["consumable"] = True
        if entry.get("was_consumable") in (True, "true", "True", "1", 1):
            meta["was_consumable"] = True
        if entry.get("take"):
            meta["take"] = True
        chess_color = entry.get("chess_color")
        if chess_color:
            meta["chess_color"] = str(chess_color).strip().lower()
        card_suit = entry.get("card_suit")
        if card_suit:
            meta["card_suit"] = str(card_suit).strip().lower()
        card_rank = entry.get("card_rank")
        if card_rank is not None:
            meta["card_rank"] = str(card_rank).strip().upper()[:1]
        if treat_as_joker:
            meta["is_joker"] = True
        if entry.get("was_glitch") in (True, "true", "True", "1", 1):
            meta["was_glitch"] = True
        cactus_growth = entry.get("cactus_growth")
        if cactus_growth is not None:
            try:
                meta["cactus_growth"] = int(cactus_growth)
            except (TypeError, ValueError):
                pass
        scattered = entry.get("scattered_item_id") or entry.get("scattered_item")
        if scattered:
            meta["scattered_item_id"] = slugify_name(str(scattered))
        scattered_level = entry.get("scattered_item_level")
        if scattered_level is not None:
            try:
                meta["scattered_item_level"] = max(1, int(scattered_level))
            except (TypeError, ValueError):
                pass
        if entry.get("is_crossed_out") in (True, "true", "True", "1", 1):
            meta["is_crossed_out"] = True
        if is_active:
            meta["melmod_fp_letter"] = str(entry.get("letter") or "")
            meta["melmod_fp_curse"] = str(entry.get("curse") or "")
            meta["melmod_fp_color"] = str(entry.get("color") or "")
            if meta.get("is_crossed_out"):
                meta["melmod_fp_crossed_out"] = True
        if entry.get("is_up_and_up_center") in (True, "true", "True", "1", 1):
            meta["is_up_and_up_center"] = True
        void_steps = entry.get("void_penalty_steps")
        if void_steps is not None:
            try:
                meta["void_penalty_steps"] = int(void_steps)
            except (TypeError, ValueError):
                pass
        elif (
            is_active
            and color == TileColor.VOID
            and curse == CurseType.LETTER
        ):
            try:
                raw_void_base = float(entry.get("base_score", 0) or 0)
            except (TypeError, ValueError):
                raw_void_base = 0.0
            if raw_void_base < 0:
                from cursed_words_solver.letter_values import SCRABBLE_VALUES

                face = SCRABBLE_VALUES.get((letter or "?").upper(), 1)
                meta["void_penalty_steps"] = max(
                    1, (int(abs(raw_void_base)) - face + 9) // 10
                )

        tile_obj = Tile(
            row=row,
            col=col,
            char=char,
            letter=letter,
            base_score=float(entry.get("base_score", 0)) if is_active else 0.0,
            color=color,
            curse=CurseType.ITEM if not is_active else curse,
            number_value=int(number_value) if number_value is not None else None,
            fraction_value=float(fraction_value) if fraction_value is not None else None,
            ocr_confidence=1.0,
            metadata=meta,
        )
        if is_active and curse == CurseType.FRACTION:
            attach_fraction_metadata(tile_obj)
        grid[row][col] = tile_obj

    if any(grid[r][c] is None for r in range(storage) for c in range(storage)):
        return None

    tiles = [[grid[r][c] for c in range(storage)] for r in range(storage)]

    playable_origin = str(board_data.get("playable_origin") or "").strip().lower()
    has_bounds = "playable_min_row" in board_data
    try:
        pmin_r = int(board_data.get("playable_min_row", 0))
        pmax_r = int(board_data.get("playable_max_row", max_row))
        pmin_c = int(board_data.get("playable_min_col", 0))
        pmax_c = int(board_data.get("playable_max_col", max_col))
    except (TypeError, ValueError):
        pmin_r, pmax_r, pmin_c, pmax_c = 0, max_row, 0, max_col

    if not has_bounds and (board_rows < storage or board_cols < storage):
        min_r, max_r, min_c, max_c = storage, -1, storage, -1
        for r in range(storage):
            for c in range(storage):
                if active[r * storage + c]:
                    min_r = min(min_r, r)
                    max_r = max(max_r, r)
                    min_c = min(min_c, c)
                    max_c = max(max_c, c)
        if max_r >= 0:
            pmin_r, pmax_r, pmin_c, pmax_c = min_r, max_r, min_c, max_c
            if not playable_origin:
                if min_r == 0:
                    playable_origin = "top_left"
                elif max_r == max_row:
                    playable_origin = "bottom_left"
                else:
                    playable_origin = "bottom_left"

    return Board(
        tiles=tiles,
        money=money,
        rows=board_rows,
        cols=board_cols,
        active=active,
        playable_origin=playable_origin,
        playable_min_row=pmin_r,
        playable_max_row=pmax_r,
        playable_min_col=pmin_c,
        playable_max_col=pmax_c,
    )


def _solver_row_to_melmod(board_data: dict[str, Any], solver_row: int, storage: int) -> int:
    """Inverse of _melmod_row_to_solver for embedding scored boards."""
    if board_data.get("row_order") == "top_first":
        return solver_row
    return (storage - 1) - solver_row


def _tile_curse_key(tile: Tile, *, active: bool) -> str:
    if not active:
        return "inactive"
    curse = tile.curse
    if curse == CurseType.WILDCARD:
        return "wildcard"
    if curse == CurseType.BLANK:
        return "wildcard"
    if curse == CurseType.CURRENCY:
        return "currency"
    if curse == CurseType.NUMBER:
        return "number"
    if curse == CurseType.FRACTION:
        return "fraction"
    if curse == CurseType.ITEM:
        return "item"
    if curse == CurseType.CARD:
        return "card"
    if curse == CurseType.ARROW:
        return "arrow"
    if curse in (
        CurseType.CHESS_PAWN,
        CurseType.CHESS_BISHOP,
        CurseType.CHESS_ROOK,
        CurseType.CHESS_KNIGHT,
        CurseType.CHESS_QUEEN,
        CurseType.CHESS_KING,
    ):
        return curse.value
    return "letter"


def board_tile_to_melmod_dict(
    tile: Tile,
    *,
    board_data: dict[str, Any],
    storage: int,
    active: bool,
) -> dict[str, Any]:
    """Serialize one solver Tile to melmod board export shape."""
    game_row = _solver_row_to_melmod(board_data, tile.row, storage)
    entry: dict[str, Any] = {
        "row": game_row,
        "col": tile.col,
        "active": bool(active),
    }
    if not active:
        entry.update(
            {
                "char_display": "",
                "char": "",
                "letter": "",
                "base_score": 0,
                "color": "colorless",
                "curse": "inactive",
            }
        )
        return entry

    meta = tile.metadata or {}
    curse_key = _tile_curse_key(tile, active=True)
    color_key = tile.color.value if tile.color != TileColor.UNKNOWN else "unknown"
    char_display = str(tile.char or tile.letter or "?")
    letter = str(tile.letter or tile.char or "?")
    fp_letter = meta.get("melmod_fp_letter")
    fp_curse = meta.get("melmod_fp_curse")
    fp_color = meta.get("melmod_fp_color")
    if (
        fp_letter is not None
        and not meta.get("consumable")
        and str(fp_letter).strip()
    ):
        letter = str(fp_letter)
        if fp_curse is not None and str(fp_curse).strip():
            curse_key = str(fp_curse).strip().lower()
        if fp_color is not None and str(fp_color).strip():
            color_key = str(fp_color).strip().lower()
    entry.update(
        {
            "char_display": char_display,
            "char": char_display,
            "letter": letter,
            "base_score": float(tile.base_score),
            "color": color_key,
            "curse": curse_key,
        }
    )
    if meta.get("is_joker"):
        entry["is_joker"] = True
    if meta.get("consumable"):
        entry["consumable"] = True
    if meta.get("was_consumable"):
        entry["was_consumable"] = True
    if meta.get("take"):
        entry["take"] = True
    if meta.get("was_glitch"):
        entry["was_glitch"] = True
    if meta.get("is_crossed_out"):
        entry["is_crossed_out"] = True
    elif meta.get("melmod_fp_crossed_out"):
        entry["is_crossed_out"] = True
    if meta.get("is_up_and_up_center"):
        entry["is_up_and_up_center"] = True
    if meta.get("chess_color"):
        entry["chess_color"] = meta["chess_color"]
    if meta.get("card_suit"):
        entry["card_suit"] = meta["card_suit"]
    if meta.get("card_rank"):
        entry["card_rank"] = meta["card_rank"]
    if tile.number_value is not None:
        entry["number_value"] = tile.number_value
    if tile.fraction_value is not None:
        entry["fraction_value"] = tile.fraction_value
    if meta.get("cactus_growth") is not None:
        entry["cactus_growth"] = meta["cactus_growth"]
    scattered = meta.get("scattered_item_id")
    if scattered:
        entry["scattered_item_id"] = str(scattered)
    scattered_level = meta.get("scattered_item_level")
    if scattered_level is not None:
        try:
            entry["scattered_item_level"] = max(1, int(scattered_level))
        except (TypeError, ValueError):
            pass
    void_steps = meta.get("void_penalty_steps")
    if void_steps is not None:
        try:
            entry["void_penalty_steps"] = int(void_steps)
        except (TypeError, ValueError):
            pass
    return entry


def board_to_run_state_board(
    board: Board,
    *,
    source_run_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Embed the exact Board used for F8 scoring into run_state snapshot form."""
    storage = board.storage_rows
    template = (
        source_run_state.get("board")
        if isinstance(source_run_state, dict)
        and isinstance(source_run_state.get("board"), dict)
        else {}
    )
    board_data: dict[str, Any] = {
        "source": "melmod",
        "money": board.money,
        "rows": board.rows,
        "cols": board.cols,
        "playable_origin": board.playable_origin or template.get("playable_origin", ""),
        "playable_min_row": board.playable_min_row,
        "playable_max_row": board.playable_max_row,
        "playable_min_col": board.playable_min_col,
        "playable_max_col": board.playable_max_col,
    }
    if template.get("row_order"):
        board_data["row_order"] = template["row_order"]
    source_tiles = (
        template.get("tiles") if isinstance(template.get("tiles"), list) else []
    )
    solver_at: dict[tuple[int, int], Tile] = {}
    active_at: dict[tuple[int, int], bool] = {}
    for idx in range(board.cell_count):
        row, col = board.coords_at(idx)
        solver_at[(row, col)] = board.tiles[row][col]
        active_at[(row, col)] = board.is_active_index(idx)

    tiles: list[dict[str, Any]] = []
    seen_solver: set[tuple[int, int]] = set()
    if source_tiles:
        for src in source_tiles:
            if not isinstance(src, dict):
                continue
            try:
                game_row = int(src.get("row", -1))
                col = int(src.get("col", -1))
            except (TypeError, ValueError):
                continue
            if game_row < 0 or col < 0:
                continue
            solver_row = _melmod_row_to_solver(board_data, game_row)
            key = (solver_row, col)
            tile = solver_at.get(key)
            if tile is None:
                continue
            seen_solver.add(key)
            tiles.append(
                board_tile_to_melmod_dict(
                    tile,
                    board_data=board_data,
                    storage=storage,
                    active=active_at.get(key, True),
                )
            )
    for idx in range(board.cell_count):
        row, col = board.coords_at(idx)
        if (row, col) in seen_solver:
            continue
        tile = board.tiles[row][col]
        tiles.append(
            board_tile_to_melmod_dict(
                tile,
                board_data=board_data,
                storage=storage,
                active=board.is_active_index(idx),
            )
        )
    board_data["tiles"] = tiles
    return board_data


_FONT_TAG_RE = re.compile(r"<font[^>]*>|</font>", re.IGNORECASE)


def _plain_word_from_historic_field(word: str) -> str:
    """Strip Unity rich-text tags so Limnophila does not read 'f' from '<font'."""
    w = (word or "").strip()
    if "<font" not in w.lower():
        return w
    return _FONT_TAG_RE.sub("", w)


def _first_alphabetic_letter(word: str) -> str:
    """First A–Z letter in a submitted word (lowercase), matching game/melmod capture."""
    for ch in _plain_word_from_historic_field(word).strip().lower():
        if ch.isalpha():
            return ch
    return ""


def _parse_historic_words_rows(raw: Any) -> list[dict[str, Any]]:
    """Parse melmod historic_words JSON into a list of row dicts."""
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [row for row in parsed if isinstance(row, dict)]
        return []
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    return []


def _historic_row_metadata_matches(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    """True when melmod-style historic row metadata matches (paths ignored)."""
    if not left or not right:
        return False
    for key in (
        "word",
        "score",
        "red_tile_count",
        "green_tile_count",
        "chess_take_value",
    ):
        if key not in left and key not in right:
            continue
        lv = left.get(key)
        rv = right.get(key)
        if lv is None and rv is None:
            continue
        if lv is None or rv is None:
            return False
        if str(lv).strip().lower() != str(rv).strip().lower():
            return False
    return True


def historic_metadata_matches_json(f8_json: str, auth_json: str) -> bool:
    """True when F8 metadata-only historic matches authoritative rows (paths ignored)."""
    f8_json = (f8_json or "").strip()
    auth_json = (auth_json or "").strip()
    if not f8_json or not auth_json:
        return False
    if f8_json == auth_json:
        return True
    f8_rows = _parse_historic_words_rows(f8_json)
    auth_rows = _parse_historic_words_rows(auth_json)
    if not f8_rows or not auth_rows or len(f8_rows) != len(auth_rows):
        return False
    return all(
        _historic_row_metadata_matches(f8_rows[i], auth_rows[i])
        for i in range(len(f8_rows))
    )


def _encounter_score_earned_from_extras(extras: dict[str, Any]) -> float:
    try:
        return float(extras.get("encounter_score_earned") or 0)
    except (TypeError, ValueError):
        return 0.0


def _fresh_encounter_grid_one(extras: dict[str, Any]) -> bool:
    """Grid 1 with no points scored yet (remaining still equals total target)."""
    if _grid_number_from_extras(extras) != 1:
        return False
    if _scoring_previous_words_count_from_extras(extras) > 0:
        return False
    rows = _parse_historic_words_rows(extras.get("historic_words"))
    if any(
        isinstance(row, dict) and float(row.get("score") or 0) > 0 for row in rows
    ):
        return False
    if _encounter_score_earned_from_extras(extras) > 0:
        return False
    try:
        total = float(extras.get("encounter_total_target") or 0)
        remaining = float(extras.get("encounter_remaining_target") or 0)
    except (TypeError, ValueError):
        return False
    return total > 0 and remaining == total


def _encounter_historic_trusted_for_poison(extras: dict[str, Any]) -> bool:
    """True when historic_words is from the live encounter (not stale cross-encounter bleed)."""
    hist = str(extras.get("historic_words", "") or "").strip()
    if not hist or hist == "[]":
        return False
    source = str(extras.get("encounter_historic_source", "") or "").strip().lower()
    if source in ("live", "green_poison_only"):
        return True
    if source in (
        "grid1_no_scoring_cache",
        "historic_paths_stale",
        "grid_advanced",
        "grid_advanced_disk",
        "grid_start_cleared",
    ):
        return False
    return False


def _green_poison_row_contribution(row: dict[str, Any]) -> float:
    try:
        green_count = int(row.get("green_tile_count") or 0)
    except (TypeError, ValueError):
        green_count = 0
    if green_count <= 0:
        return 0.0
    try:
        word_score = float(row.get("score") or 0)
    except (TypeError, ValueError):
        word_score = 0.0
    if word_score <= 0:
        return 0.0
    return green_count * round(word_score * 0.1)


def green_poison_from_historic_words(extras: dict[str, Any] | None) -> float:
    """ApplyPoisonEffect parity: sum green_tile_count × 10% of each prior word score."""
    if not isinstance(extras, dict):
        return 0.0
    raw = extras.get("historic_words")
    rows = _parse_historic_words_rows(raw)
    if not rows:
        return 0.0
    if _fresh_encounter_grid_one(extras):
        return 0.0
    if _encounter_historic_trusted_for_poison(extras):
        return sum(_green_poison_row_contribution(row) for row in rows if isinstance(row, dict))

    enc_earned = _encounter_score_earned_from_extras(extras)
    if enc_earned <= 0:
        raw_enc = extras.get("encounter_score_earned")
        enc_missing = raw_enc is None or str(raw_enc).strip() == ""
        grid = _grid_number_from_extras(extras)
        spc = _scoring_previous_words_count_from_extras(extras)
        if enc_missing and grid >= 2 and spc > 0:
            enc_earned = sum(
                float(row.get("score") or 0)
                for row in rows
                if isinstance(row, dict)
            )
        if enc_earned <= 0:
            return 0.0
    total = 0.0
    score_used = 0.0
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        try:
            green_count = int(row.get("green_tile_count") or 0)
        except (TypeError, ValueError):
            green_count = 0
        if green_count <= 0:
            continue
        try:
            word_score = float(row.get("score") or 0)
        except (TypeError, ValueError):
            word_score = 0.0
        if word_score <= 0:
            continue
        if score_used + word_score > enc_earned + 1e-6:
            continue
        score_used += word_score
        total += _green_poison_row_contribution(row)
    return total


def _previous_letter_from_historic_words(raw: Any) -> str:
    """Last historic word's first letter (Bento Box / Limnophila parity with melmod)."""
    rows: list[Any]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        rows = parsed if isinstance(parsed, list) else []
    elif isinstance(raw, list):
        rows = raw
    else:
        return ""

    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        word = str(row.get("word") or "").strip()
        letter = _first_alphabetic_letter(word)
        if letter:
            return letter
    return ""


def _normalize_pin_extras(extras: dict[str, Any]) -> dict[str, Any]:
    """Parse melmod string extras into structures the scoring pipeline uses."""
    out = dict(extras)
    raw_boss_modifiers = out.get("boss_modifiers")
    if isinstance(raw_boss_modifiers, str) and raw_boss_modifiers.strip():
        parsed_list: list[str] = []
        try:
            parsed = json.loads(raw_boss_modifiers)
            rows = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            rows = [s.strip() for s in raw_boss_modifiers.split(",") if s.strip()]
        for entry in rows:
            item = str(entry or "").strip().lower()
            if item and item not in parsed_list:
                parsed_list.append(item)
        out["boss_modifiers"] = parsed_list
    elif isinstance(raw_boss_modifiers, list):
        normalized: list[str] = []
        for entry in raw_boss_modifiers:
            item = str(entry or "").strip().lower()
            if item and item not in normalized:
                normalized.append(item)
        out["boss_modifiers"] = normalized
    raw_consumable_rack = out.get("consumable_rack")
    if isinstance(raw_consumable_rack, str) and raw_consumable_rack.strip():
        try:
            parsed_rack = json.loads(raw_consumable_rack)
            if isinstance(parsed_rack, list):
                out["consumable_rack"] = parsed_rack
        except json.JSONDecodeError:
            pass
    elif isinstance(raw_consumable_rack, list):
        out["consumable_rack"] = [
            entry for entry in raw_consumable_rack if isinstance(entry, dict)
        ]
    raw_floor_mods = out.get("boss_modifier_floor_mods")
    if isinstance(raw_floor_mods, str) and raw_floor_mods.strip():
        try:
            parsed_fm = json.loads(raw_floor_mods)
            out["boss_modifier_floor_mods"] = (
                parsed_fm if isinstance(parsed_fm, dict) else {}
            )
        except json.JSONDecodeError:
            out["boss_modifier_floor_mods"] = {}
    elif isinstance(raw_floor_mods, dict):
        out["boss_modifier_floor_mods"] = raw_floor_mods
    raw_memory = out.get("pin_memory")
    if isinstance(raw_memory, str):
        try:
            parsed = json.loads(raw_memory)
            out["pin_memory"] = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            out["pin_memory"] = []
    elif raw_memory is None:
        out.setdefault("pin_memory", [])
    raw_stitched = out.get("stitched_sticker_ids")
    if isinstance(raw_stitched, str) and raw_stitched.strip():
        try:
            parsed = json.loads(raw_stitched)
            out["stitched_sticker_ids"] = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            out["stitched_sticker_ids"] = [
                s.strip() for s in raw_stitched.split(",") if s.strip()
            ]
    for int_key in (
        "cards_submitted",
        "bicycle_word_score_bonus",
        "movie_camera_word_score_bonus",
        "neapolitan_percent",
        "ruler_distance",
        "pin_left_level",
        "pin_right_level",
        "pin_left_variable",
        "pin_right_variable",
        "overhand_level",
        "grid_number",
    ):
        if int_key in out:
            try:
                out[int_key] = int(out[int_key])
            except (TypeError, ValueError):
                out[int_key] = 0
    for embargo_key in ("embargoed_item_types", "embargoed_item_slugs"):
        raw_embargo = out.get(embargo_key)
        if raw_embargo is not None and not isinstance(raw_embargo, str):
            out[embargo_key] = str(raw_embargo)
        elif isinstance(raw_embargo, str):
            out[embargo_key] = ",".join(
                s.strip() for s in raw_embargo.split(",") if s.strip()
            )
    for key in (
        "boss_floor_modification",
        "fox_stolen_this_grid",
        "fox_stolen_this_word",
    ):
        if key in out:
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError):
                out[key] = 0
    for key in ("green_poison_bonus", "pink_saved_this_word"):
        if key in out:
            try:
                out[key] = float(out[key])
            except (TypeError, ValueError):
                out[key] = 0.0
    for key in (
        "red_tiles_used_encounter",
        "consumable_rack_count",
        "rare_item_count",
        "rare_item_count_last_known",
        "fairy_count",
        "cursed_bosses_defeated_count",
        "animal_stamp_count",
        "money_lost_encounter",
        "grids_total",
        "target_number",
        "target_score",
        "michael_book_bonus",
        "birthday_cake_bonus",
        "stamps_shop_price_total",
        "shop_restock_count",
        "chess_move_tile_count",
        "rack_overflow",
        "run_seed",
        "wolf_max_length",
        "cobra_min_length",
        "michael_min_word_length",
        "michael_phase",
        "encounter_min_word_length",
        "run_stage",
        "encounter_score_earned",
        "encounter_remaining_target",
        "encounter_total_target",
    ):
        if key in out:
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError):
                out[key] = 0
    for key in ("michael_summoned_bosses_defeated", "michael_puzzle_grid"):
        if key in out:
            out[key] = out[key] in (True, "true", "True", "1", 1)
    if "target_chess_piece" in out and out["target_chess_piece"]:
        out["target_chess_piece"] = str(out["target_chess_piece"]).strip().lower()
    if "target_curse_type" in out and out["target_curse_type"]:
        out["target_curse_type"] = str(out["target_curse_type"]).strip().lower()
    if "is_first_grid_of_encounter" in out:
        val = out["is_first_grid_of_encounter"]
        out["is_first_grid_of_encounter"] = val in (
            True,
            "true",
            "True",
            "1",
            1,
        )
    reconcile_previous_word_first_letter_from_historic(out)
    for key in ("boss_area_number", "grids_remaining"):
        if key in out:
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError):
                out[key] = 0
    if "boss_cursed" in out:
        out["boss_cursed"] = out["boss_cursed"] in (True, "true", "True", "1", 1)
    if "hyena_blocked" in out:
        out["hyena_blocked"] = out["hyena_blocked"] in (
            True,
            "true",
            "True",
            "1",
            1,
        )
    if "tile_ninja_bonus" in out:
        try:
            out["tile_ninja_bonus"] = float(out["tile_ninja_bonus"])
        except (TypeError, ValueError):
            out["tile_ninja_bonus"] = 0.0
    if "tile_ninja_bonus_last_known" in out:
        try:
            out["tile_ninja_bonus_last_known"] = float(out["tile_ninja_bonus_last_known"])
        except (TypeError, ValueError):
            out["tile_ninja_bonus_last_known"] = 0.0
    if "tile_ninja_bonus_at_grid_start" in out:
        try:
            out["tile_ninja_bonus_at_grid_start"] = float(
                out["tile_ninja_bonus_at_grid_start"]
            )
        except (TypeError, ValueError):
            out["tile_ninja_bonus_at_grid_start"] = 0.0
    if "avocado_mushy" in out:
        out["avocado_mushy"] = out["avocado_mushy"] in (
            True,
            "true",
            "True",
            "1",
            1,
        )
    for key in ("kokeshi_dolls", "frozen_in_shop", "board_from_melmod"):
        if key in out:
            out[key] = out[key] in (True, "true", "True", "1", 1)
    out.pop("bicycle_suited_on_path", None)
    return out


_SESSION_EXTRA_KEYS = (
    "snapshot_copy_slug",
    "snapshot_copy_level",
    "snapshot_copy_export_note",
    "grid_path_immediate_word_mults",
    "flush_word_mults_after_pin",
    "flush_word_mults_before_cocktail",
    "compound_word_percents_on_tile_sum",
    "compound_word_finalize_at_cocktail",
    "defer_post_cocktail_sunflower",
    "post_cocktail_word_percent",
    "grid_tile_multiply_first",
)


def export_diagnostics_from_run_state(data: dict[str, Any] | None) -> dict[str, Any]:
    """Top-level export_diagnostics block from melmod run_state.json."""
    if not data:
        return {}
    diag = data.get("export_diagnostics")
    return dict(diag) if isinstance(diag, dict) else {}


def solver_session_extras_from_loadout(loadout: Loadout | None) -> dict[str, Any]:
    """Phasing/session keys the scoring pipeline applied (for F8 replay/debug)."""
    if loadout is None:
        return {}
    extras = loadout.extras or {}
    return {key: extras[key] for key in _SESSION_EXTRA_KEYS if key in extras}


def encounter_implies_active_boss(loadout: Loadout | None) -> bool:
    """True when run_state suggests a boss fight (not a normal encounter grid)."""
    if loadout is None:
        return False
    extras = loadout.extras or {}
    if extras.get("encounter_has_boss") in (True, "true", "True", "1", 1):
        return True
    if extras.get("boss_cursed") in (True, "true", "True", "1", 1):
        return True
    node = str(extras.get("run_node_type") or "").strip().lower()
    if "boss" in node:
        return True
    mods = extras.get("boss_modifiers")
    if isinstance(mods, list) and any(str(m).strip() for m in mods):
        return True
    if isinstance(mods, str) and mods.strip() not in ("", "[]"):
        return True
    return False


def encounter_missing_boss_should_warn(loadout: Loadout | None) -> bool:
    """Warn only when export looks like a boss fight but boss_id/name are absent."""
    if loadout is None:
        return False
    if loadout.boss_id or loadout.boss_name:
        return False
    return encounter_implies_active_boss(loadout)


def validate_run_state_for_scoring(
    loadout: Loadout | None,
    *,
    board: Board | None = None,
    raw: dict[str, Any] | None = None,
) -> list[str]:
    """Python-side checks mirroring melmod ExportCompleteness."""
    if loadout is None:
        return ["loadout missing"]

    warnings: list[str] = []
    extras = loadout.extras or {}
    diag = export_diagnostics_from_run_state(raw) if raw else {}
    for key in diag.get("missing_keys") or []:
        if isinstance(key, str) and key.strip():
            warnings.append(f"melmod export missing: {key.strip()}")

    sticker_ids = {str(s.id or "").strip().lower() for s in loadout.stickers}
    stamp_ids = {str(s.id or "").strip().lower() for s in loadout.stamps}
    pin = str(extras.get("pin_effect") or "").strip().lower()

    if "snapshot" in sticker_ids:
        note = str(extras.get("snapshot_copy_export_note") or "").strip().lower()
        slug = str(extras.get("snapshot_copy_slug") or "").strip()
        if not slug and note not in ("no_copy_yet",):
            warnings.append("snapshot equipped but snapshot_copy_slug is missing")

    if pin == "random_access_memory":
        memory = extras.get("pin_memory")
        note = str(extras.get("pin_memory_export_note") or "").strip()
        if note == "field_missing":
            warnings.append("RAM pin: pin_memory unreadable (ItemsInMemory)")
        elif memory in (None, "", "[]"):
            if note not in ("empty_valid", "no_pin"):
                warnings.append("RAM pin: pin_memory empty (rebuild melmod if missing after boss picks)")

    if any("lucky" in sid and "dice" in sid for sid in sticker_ids):
        if extras.get("target_number") in (None, ""):
            if extras.get("lucky_dice_target_missing") not in (True, "true", "True", "1", 1):
                warnings.append("Lucky Dice equipped but target_number missing")

    if "steak" in stamp_ids:
        has_pct = False
        raw_pct = extras.get("steak_word_bonus_percent")
        if raw_pct not in (None, ""):
            try:
                has_pct = int(raw_pct) >= 100
            except (TypeError, ValueError):
                has_pct = False
        has_rare = extras.get("rare_item_count") not in (None, "")
        if not has_pct and not has_rare:
            warnings.append("Steak equipped but steak_word_bonus_percent missing")

    if "twinkle_toes" in stamp_ids:
        if extras.get("twinkle_toes_swap_available") in (None, ""):
            warnings.append(
                "twinkle_toes equipped but swap state not exported — "
                "rebuild melmod and press F8 again"
            )

    if board is None and extras.get("encounter_mode") == "encounter":
        warnings.append("encounter active but board could not be parsed")

    if encounter_missing_boss_should_warn(loadout):
        warnings.append(
            "boss fight active but boss_id/boss_name missing (press F8 again)"
        )

    if board is not None:
        scattered = [
            t
            for t in board.flat
            if board.is_active_index(t.index)
            and t.curse == CurseType.ITEM
            and str((t.metadata or {}).get("scattered_item_id") or "").strip()
        ]
        if scattered and not extras.get("grid_scattered_items"):
            warnings.append("grid has scattered items but grid_scattered_items extra missing")

    return warnings


def _parse_inventory_order_ids(raw: object) -> list[str] | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, list):
        order = [str(x).strip() for x in raw if str(x).strip()]
        return order or None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list):
            order = [str(x).strip() for x in parsed if str(x).strip()]
            return order or None
    return None


def _reorder_items_by_id_order(
    items: list[LoadoutItem],
    order_ids: list[str],
) -> list[LoadoutItem]:
    if not order_ids or not items:
        return items
    pools: dict[str, list[LoadoutItem]] = {}
    for item in items:
        key = slugify_name(item.id or item.name)
        pools.setdefault(key, []).append(item)
    ordered: list[LoadoutItem] = []
    for raw_id in order_ids:
        key = slugify_name(raw_id)
        pool = pools.get(key)
        if pool:
            ordered.append(pool.pop(0))
    if len(ordered) != len(items):
        return items
    return ordered


def reorder_inventory_from_extras(loadout: Loadout) -> Loadout:
    """Reorder stickers/stamps to melmod sticker_order / stamp_order extras."""
    extras = loadout.extras or {}
    stickers = list(loadout.stickers)
    stamps = list(loadout.stamps)
    sticker_order = _parse_inventory_order_ids(extras.get("sticker_order"))
    stamp_order = _parse_inventory_order_ids(extras.get("stamp_order"))
    new_stickers = (
        _reorder_items_by_id_order(stickers, sticker_order)
        if sticker_order
        else stickers
    )
    new_stamps = (
        _reorder_items_by_id_order(stamps, stamp_order) if stamp_order else stamps
    )
    if new_stickers == stickers and new_stamps == stamps:
        return loadout
    from dataclasses import replace

    return replace(loadout, stickers=new_stickers, stamps=new_stamps)


def parse_run_state(data: dict[str, Any]) -> Loadout:
    stickers = [
        LoadoutItem(
            id=s.get("id", s.get("name", "unknown")),
            name=s.get("name", ""),
            level=int(s.get("level", 1)),
            kind="sticker",
        )
        for s in data.get("stickers", [])
    ]
    stamps = [
        LoadoutItem(
            id=s.get("id", s.get("name", "unknown")),
            name=s.get("name", ""),
            level=1,
            kind="stamp",
        )
        for s in data.get("stamps", [])
    ]
    boss = data.get("boss") if isinstance(data.get("boss"), dict) else {}
    boss_id = str(data.get("boss_id") or boss.get("id") or "")
    boss_name = str(data.get("boss_name") or boss.get("name") or "")
    extras = _normalize_pin_extras(data.get("extras", {}) or {})
    diag = data.get("export_diagnostics")
    if isinstance(diag, dict):
        fp = str(diag.get("fingerprint") or "").strip()
        if fp:
            extras.setdefault("export_diagnostics_fingerprint", fp)
    if data.get("challenge_game_class"):
        extras["challenge_game_class"] = str(data["challenge_game_class"])
    if not extras.get("challenge_game_class"):
        from cursed_words_solver.rules.quest_effects import (
            challenge_game_class_from_fingerprint,
        )

        derived = challenge_game_class_from_fingerprint(
            str(extras.get("export_diagnostics_fingerprint") or "")
        )
        if derived:
            extras["challenge_game_class"] = derived
    if data.get("challenge_name"):
        extras["challenge_name"] = str(data["challenge_name"])
    if data.get("challenge_elite") in (True, "true", "True", "1", 1):
        extras["challenge_elite"] = "true"
    fav_stickers: list[str] = []
    for sticker in data.get("stickers", []):
        if not isinstance(sticker, dict):
            continue
        if sticker.get("is_human_boy_favourite") in (True, "true", "True", "1", 1):
            sid = str(sticker.get("id") or sticker.get("name") or "").strip().lower()
            if sid:
                fav_stickers.append(sid)
    if fav_stickers and not extras.get("favourite_sticker_ids"):
        extras["favourite_sticker_ids"] = ",".join(fav_stickers)
    if fav_stickers and not extras.get("favourite_sticker_id"):
        extras["favourite_sticker_id"] = fav_stickers[0]
    fav_stamps: list[str] = []
    for stamp in data.get("stamps", []):
        if not isinstance(stamp, dict):
            continue
        if stamp.get("is_human_boy_favourite") in (True, "true", "True", "1", 1):
            sid = str(stamp.get("id") or stamp.get("name") or "").strip().lower()
            if sid:
                fav_stamps.append(sid)
    if fav_stamps and not extras.get("favourite_stamp_ids"):
        extras["favourite_stamp_ids"] = ",".join(fav_stamps)
    if fav_stamps and not extras.get("favourite_stamp_id"):
        extras["favourite_stamp_id"] = fav_stamps[0]
    pin_effect = str(extras.get("pin_effect", "") or "").strip().lower()
    if pin_effect in ("human_boy", "human_hands") and not extras.get("favourite_stamp_id"):
        order: list[str] = []
        raw_order = extras.get("stamp_order")
        if isinstance(raw_order, list):
            order = [slugify_name(str(x)) for x in raw_order if str(x).strip()]
        elif isinstance(raw_order, str) and raw_order.strip():
            try:
                parsed = json.loads(raw_order)
                if isinstance(parsed, list):
                    order = [slugify_name(str(x)) for x in parsed if str(x).strip()]
            except json.JSONDecodeError:
                pass
        if not order:
            order = [
                slugify_name(str(s.get("id") or s.get("name") or ""))
                for s in data.get("stamps", [])
                if isinstance(s, dict)
            ]
        for i, slug in enumerate(order):
            if slug == "right_hand" and i + 1 < len(order):
                extras["favourite_stamp_id"] = order[i + 1]
                if not extras.get("favourite_stamp_ids"):
                    extras["favourite_stamp_ids"] = order[i + 1]
                break
    return reorder_inventory_from_extras(
        Loadout(
        character=data.get("character", ""),
        pin_branch=data.get("pin_branch", ""),
        stickers=stickers,
        stamps=stamps,
        boss_id=boss_id,
        boss_name=boss_name,
        boss_effect=data.get("boss_effect", ""),
        money=int(data.get("money", 0)),
        extras=extras,
    )
    )


def save_run_state_template(path: Path | None = None) -> Path:
    """Write example run_state.json for MelonLoader mod integration."""
    path = path or RUN_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    example = {
        "character": "Example",
        "pin_branch": "left",
        "money": 42,
        "stickers": [
            {"id": "sticky_plaster", "name": "Sticky Plaster", "level": 2},
            {"id": "tombstone", "name": "Tombstone", "level": 1},
        ],
        "stamps": [{"id": "newspaper", "name": "Newspaper"}],
        "boss_id": "mole",
        "boss_name": "Mole",
        "boss_effect": "",
        "extras": {"pin_effect": ""},
    }
    path.write_text(json.dumps(example, indent=2), encoding="utf-8")
    return path


def loadout_to_dict(loadout: Loadout) -> dict[str, Any]:
    """Serialize loadout to melmod-compatible run_state.json shape."""
    return {
        "character": loadout.character,
        "pin_branch": loadout.pin_branch,
        "money": loadout.money,
        "stickers": [
            {"id": s.id, "name": s.name, "level": s.level}
            for s in loadout.stickers
        ],
        "stamps": [{"id": s.id, "name": s.name} for s in loadout.stamps],
        "boss_id": loadout.boss_id,
        "boss_name": loadout.boss_name,
        "boss_effect": loadout.boss_effect,
        "challenge_game_class": (loadout.extras or {}).get("challenge_game_class", ""),
        "challenge_name": (loadout.extras or {}).get("challenge_name", ""),
        "challenge_elite": (loadout.extras or {}).get("challenge_elite", "") in (
            True,
            "true",
            "True",
            "1",
            1,
        ),
        "extras": dict(loadout.extras),
    }


def save_loadout(loadout: Loadout, path: Path | None = None) -> Path:
    """Write full run_state.json (preserves all melmod fields)."""
    path = path or RUN_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(loadout_to_dict(loadout), indent=2),
        encoding="utf-8",
    )
    return path


_BICYCLE_PIN_IDS = frozenset({"bicycle", "bones_the_dog", "bones"})


def _is_bicycle_pin(loadout: Loadout) -> bool:
    pin = str((loadout.extras or {}).get("pin_effect", "") or "").strip().lower()
    return pin in _BICYCLE_PIN_IDS


def _has_neapolitan_stamp(loadout: Loadout) -> bool:
    return any(
        str((s.id or "")).strip().lower() == "neapolitan" for s in (loadout.stamps or [])
    )


def _has_ruler_stamp(loadout: Loadout) -> bool:
    return any(
        str((s.id or "")).strip().lower() == "ruler" for s in (loadout.stamps or [])
    )


def _has_mutating_dna_stamp(loadout: Loadout) -> bool:
    return any(
        "mutating" in (stamp.id or "").lower()
        or "dna" in (stamp.id or "").lower()
        or "mutating" in (stamp.name or "").lower()
        for stamp in (loadout.stamps or [])
    )


def _has_steak_stamp(loadout: Loadout) -> bool:
    return any(
        str((s.id or "")).strip().lower() == "steak" for s in (loadout.stamps or [])
    )


def _has_snapshot_sticker(loadout: Loadout) -> bool:
    return any(
        str((s.id or "")).strip().lower() == "snapshot"
        for s in (loadout.stickers or [])
    )


def _encounter_historic_intentionally_cleared(extras: dict[str, Any]) -> bool:
    source = str(extras.get("encounter_historic_source", "") or "").strip().lower()
    return source == "grid_start_cleared"


def _is_grid_advanced_historic_source(extras: dict[str, Any]) -> bool:
    source = str(extras.get("encounter_historic_source", "") or "").strip().lower()
    return source in ("grid_advanced", "grid_advanced_disk")


def _copy_grid_advance_extras_from_fresh(
    extras: dict[str, Any],
    fresh_extras: dict[str, Any],
) -> None:
    for key in (
        "grid_number",
        "grid_scattered_items",
        "encounter_historic_source",
        "previous_word_first_letter",
        "scoring_previous_words_count",
    ):
        val = fresh_extras.get(key)
        if val is not None:
            extras[key] = val


def _historic_words_count(raw: str) -> int:
    """Parse melmod historic_words JSON array length safely."""
    raw = (raw or "").strip()
    if not raw or raw == "[]":
        return 0
    try:
        arr = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return 0
    return len(arr) if isinstance(arr, list) else 0


def project_previous_word_first_letter_from_round_log(
    run_state: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Project round-log submit letter when melmod export lags one cycle after submit."""
    from cursed_words_solver.round_log import last_submit_effective_first_letter

    if not isinstance(run_state, dict):
        return run_state
    expected = last_submit_effective_first_letter()
    if not expected:
        return run_state
    extras = run_state.get("extras")
    if not isinstance(extras, dict):
        extras = {}
        run_state["extras"] = extras
    exp = expected.lower()[:1]
    cur = str(extras.get("previous_word_first_letter") or "").strip().lower()[:1]
    if cur != exp:
        extras["previous_word_first_letter"] = exp
    return run_state


def reconcile_previous_word_first_letter_from_historic(
    extras: dict[str, Any],
) -> None:
    """Normalize previous_word_first_letter (mirror melmod scoring-cache vs historic)."""
    grid = _grid_number_from_extras(extras)
    hist = str(extras.get("historic_words", "") or "").strip()
    if grid >= 2 and (not hist or hist == "[]"):
        if _scoring_previous_words_count_from_extras(extras) == 0:
            extras.pop("previous_word_first_letter", None)
        return
    spc = _scoring_previous_words_count_from_extras(extras)
    last_from_hist = _previous_letter_from_historic_words(hist)
    if spc == 0:
        if last_from_hist:
            extras["previous_word_first_letter"] = last_from_hist
        else:
            extras.pop("previous_word_first_letter", None)
        return
    prev = str(extras.get("previous_word_first_letter") or "").strip().lower()[:1]
    if prev:
        extras["previous_word_first_letter"] = prev
    elif "previous_word_first_letter" in extras:
        extras.pop("previous_word_first_letter", None)


def _apply_fresh_encounter_historic_to_extras(
    extras: dict[str, Any],
    fresh_extras: dict[str, Any],
    fresh_hist: str,
) -> None:
    extras["historic_words"] = fresh_hist
    for key in (
        "red_tiles_used_encounter",
        "previous_word_first_letter",
        "grid_number",
        "encounter_historic_source",
        "scoring_previous_words_count",
    ):
        val = fresh_extras.get(key)
        if val is not None and str(val).strip() != "":
            extras[key] = val
    reconcile_previous_word_first_letter_from_historic(extras)


def _grid_number_from_extras(extras: dict[str, Any]) -> int:
    try:
        return int(str(extras.get("grid_number") or "0"))
    except (TypeError, ValueError):
        return 0


def _scoring_previous_words_count_from_extras(extras: dict[str, Any]) -> int:
    try:
        return int(str(extras.get("scoring_previous_words_count") or "0").strip())
    except (TypeError, ValueError):
        return 0


def clear_grid_one_stale_encounter_historic(extras: dict[str, Any]) -> bool:
    """Mirror melmod ClearGridOneStaleEncounterHistoric (grid 1, empty scoring cache)."""
    if _grid_number_from_extras(extras) != 1:
        return False
    if _scoring_previous_words_count_from_extras(extras) != 0:
        return False
    hist = str(extras.get("historic_words", "") or "").strip()
    if not hist or hist == "[]":
        return False
    extras.pop("historic_words", None)
    extras.pop("red_tiles_used_encounter", None)
    extras["encounter_historic_source"] = "grid1_no_scoring_cache"
    return True


_STALE_ENCOUNTER_HISTORIC_SOURCES = frozenset(
    {
        "grid1_no_scoring_cache",
        "historic_paths_stale",
    }
)

_TRUSTED_ENCOUNTER_HISTORIC_SOURCES = frozenset(
    {
        "live",
        "grid2_disk_fallback",
        "grid_advanced",
        "grid_advanced_disk",
        "historic_metadata_only",
    }
)


def _should_infer_spc_from_historic(extras: dict[str, Any]) -> bool:
    """True when historic_words should backfill an empty scoring cache."""
    if (
        _grid_number_from_extras(extras) >= 2
        and _scoring_previous_words_count_from_extras(extras) == 0
    ):
        # Melmod: grid 2+ empty scoring cache is authoritative; do not infer from
        # encounter-wide historic (prior-grid bleed).
        return False
    source = str(extras.get("encounter_historic_source", "") or "").strip().lower()
    if source in _STALE_ENCOUNTER_HISTORIC_SOURCES:
        return False
    if source in _TRUSTED_ENCOUNTER_HISTORIC_SOURCES:
        return True
    return _grid_number_from_extras(extras) >= 2 and bool(source)


def reconcile_scoring_previous_words_count(extras: dict[str, Any]) -> None:
    """Cap or infer scoring_previous_words_count when historic JSON is present."""
    hist = str(extras.get("historic_words", "") or "").strip()
    hist_count = _historic_words_count(hist)
    spc = _scoring_previous_words_count_from_extras(extras)
    if hist_count > 0 and spc > hist_count:
        source = str(
            extras.get("encounter_historic_source", "") or ""
        ).strip().lower()
        if source in (
            "live",
            "live_cache",
            "historic_metadata_only",
            "green_poison_only",
        ):
            return
        extras["scoring_previous_words_count"] = str(hist_count)
        return
    if hist_count > 0 and spc == 0 and _should_infer_spc_from_historic(extras):
        extras["scoring_previous_words_count"] = str(hist_count)


def reconcile_historic_after_grid_advance(extras: dict[str, Any]) -> bool:
    """Drop prior-grid encounter historic when scoring cache indicates a fresh grid."""
    source = str(extras.get("encounter_historic_source", "") or "").strip().lower()
    hist_count = _historic_words_count(
        str(extras.get("historic_words", "") or "").strip()
    )
    spc = _scoring_previous_words_count_from_extras(extras)
    grid = _grid_number_from_extras(extras)

    if source == "grid1_no_scoring_cache":
        if spc > 0:
            extras.pop("encounter_historic_source", None)
            return False
        return clear_grid_one_stale_encounter_historic(extras)

    if source in ("grid_advanced", "grid_advanced_disk"):
        if hist_count > 0 and spc == 0:
            extras.pop("historic_words", None)
            extras.pop("red_tiles_used_encounter", None)
            return True

    if (
        grid >= 2
        and spc == 0
        and hist_count > 0
        and source in ("grid_advanced", "grid_advanced_disk")
    ):
        extras.pop("historic_words", None)
        extras.pop("red_tiles_used_encounter", None)
        extras["encounter_historic_source"] = "grid_advanced_disk"
        return True

    if (
        grid >= 2
        and hist_count == 0
        and spc > 0
        and source in ("grid_advanced", "grid_advanced_disk")
    ):
        extras["scoring_previous_words_count"] = "0"
        extras.pop("previous_word_first_letter", None)
        return True

    return False


def _historic_entry_matches_board(board: Board, row: dict[str, Any]) -> bool:
    """True when a historic word path still spells the same letters on this board."""
    path = row.get("path")
    word = str(row.get("word", "") or "")
    plain = _plain_word_from_historic_field(word).lower()
    alpha = [c for c in plain if c.isalpha()]
    if not isinstance(path, list) or not alpha:
        return False
    letters_from_board: list[str] = []
    for raw_idx in path:
        try:
            tile = board.get_by_index(int(raw_idx))
        except (TypeError, ValueError, IndexError):
            return False
        if tile is None or not board.is_active_index(int(raw_idx)):
            return False
        ch = (tile.letter or tile.char or "").strip().lower()[:1]
        letters_from_board.append(ch if ch.isalpha() else "?")
    if len(alpha) != len(letters_from_board):
        return False
    for expected, actual in zip(alpha, letters_from_board, strict=True):
        if expected != actual and actual != "?":
            return False
    return True


def prune_historic_incompatible_with_board(
    board: Board | None,
    extras: dict[str, Any],
) -> bool:
    """Clear encounter historic when no exported word path matches the current board."""
    if board is None:
        return False
    if str(extras.get("encounter_historic_source", "") or "").strip() == "green_poison_only":
        return False
    if str(extras.get("encounter_historic_source", "") or "").strip() == "historic_metadata_only":
        return False
    if (
        _grid_number_from_extras(extras) == 1
        and _scoring_previous_words_count_from_extras(extras) == 0
    ):
        # Grid-1 word 1: embed historic still toggles Telescope running mode (prior=0).
        return False
    hist_raw = str(extras.get("historic_words", "") or "").strip()
    if not hist_raw or hist_raw == "[]":
        return False
    try:
        arr = json.loads(hist_raw)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(arr, list) or not arr:
        return False
    for row in arr:
        if isinstance(row, dict) and _historic_entry_matches_board(board, row):
            return False
    grid = _grid_number_from_extras(extras)
    spc = _scoring_previous_words_count_from_extras(extras)
    source = str(extras.get("encounter_historic_source", "") or "").strip().lower()
    try:
        enc_earned = int(extras.get("encounter_score_earned") or 0)
    except (TypeError, ValueError):
        enc_earned = 0
    if grid == 1 and enc_earned == 0 and spc == 0 and source != "live":
        extras.pop("historic_words", None)
        extras.pop("red_tiles_used_encounter", None)
        extras["scoring_previous_words_count"] = "0"
        extras.pop("previous_word_first_letter", None)
        extras["encounter_historic_source"] = "grid1_no_scoring_cache"
        return True
    if grid >= 2 and spc == 0:
        extras.pop("historic_words", None)
        extras.pop("red_tiles_used_encounter", None)
        extras["encounter_historic_source"] = "grid_start_cleared"
        return True
    poison_rows = [
        {
            "word": row.get("word"),
            "score": row.get("score"),
            "green_tile_count": int(row.get("green_tile_count") or 0),
        }
        for row in arr
        if isinstance(row, dict) and int(row.get("green_tile_count") or 0) > 0
    ]
    metadata_rows: list[dict[str, Any]] = []
    for row in arr:
        if not isinstance(row, dict):
            continue
        meta: dict[str, Any] = {}
        for key in (
            "word",
            "score",
            "red_tile_count",
            "green_tile_count",
            "chess_take_value",
        ):
            if key in row and row[key] is not None:
                meta[key] = row[key]
        if meta:
            metadata_rows.append(meta)
    if poison_rows and len(poison_rows) < spc and len(poison_rows) < len(arr):
        if metadata_rows:
            extras["historic_words"] = json.dumps(metadata_rows, ensure_ascii=False)
            extras["encounter_historic_source"] = "historic_metadata_only"
            return True
    if poison_rows:
        extras["historic_words"] = json.dumps(poison_rows, ensure_ascii=False)
        extras["encounter_historic_source"] = "green_poison_only"
        return True
    if metadata_rows:
        extras["historic_words"] = json.dumps(metadata_rows, ensure_ascii=False)
        extras["encounter_historic_source"] = "historic_metadata_only"
        return True
    extras.pop("historic_words", None)
    extras.pop("red_tiles_used_encounter", None)
    grid = _grid_number_from_extras(extras)
    if grid >= 2:
        extras["encounter_historic_source"] = "historic_paths_stale"
    else:
        extras["scoring_previous_words_count"] = "0"
        extras["encounter_historic_source"] = "grid1_no_scoring_cache"
    return True


def reconcile_encounter_historic_for_scoring(
    extras: dict[str, Any],
    *,
    board: Board | None = None,
) -> None:
    """Normalize encounter historic / scoring cache before F8 or replay scoring."""
    reconcile_scoring_previous_words_count(extras)
    reconcile_historic_after_grid_advance(extras)
    reconcile_grid_one_no_scoring_cache_sentinel(extras)
    prune_historic_incompatible_with_board(board, extras)


def reconcile_grid_one_no_scoring_cache_sentinel(extras: dict[str, Any]) -> bool:
    """Grid 1 word 1: mark empty historic as intentionally cleared (not stale bleed)."""
    source = str(extras.get("encounter_historic_source", "") or "").strip()
    if source == "grid1_no_scoring_cache" and _scoring_previous_words_count_from_extras(extras) > 0:
        extras.pop("encounter_historic_source", None)
        return False
    if _grid_number_from_extras(extras) != 1:
        return False
    if _scoring_previous_words_count_from_extras(extras) != 0:
        return False
    if encounter_submit_signals_imply_prior_words(extras):
        return False
    hist = str(extras.get("historic_words", "") or "").strip()
    if hist and hist != "[]":
        return False
    source = str(extras.get("encounter_historic_source", "") or "").strip()
    if source:
        return False
    extras["encounter_historic_source"] = "grid1_no_scoring_cache"
    return True


def _historic_words_json_prefer_fresh(
    embed_hist: str,
    fresh_hist: str,
    *,
    embed_grid: int,
    fresh_grid: int,
) -> str | None:
    """Pick disk/live historic for F8 embed (mirrors melmod PickBestHistoricWordList shrink)."""
    embed_hist = (embed_hist or "").strip()
    fresh_hist = (fresh_hist or "").strip()
    if not fresh_hist or fresh_hist == "[]":
        return None
    if not embed_hist or embed_hist == "[]":
        return fresh_hist

    embed_count = _historic_words_count(embed_hist)
    fresh_count = _historic_words_count(fresh_hist)

    if fresh_grid > embed_grid >= 1:
        return fresh_hist

    if embed_grid == fresh_grid and embed_grid >= 1:
        if fresh_count < embed_count:
            return fresh_hist
        if fresh_count > embed_count:
            return fresh_hist
        if embed_hist != fresh_hist:
            return fresh_hist
        return None

    if embed_grid >= 2 and embed_grid == fresh_grid:
        if embed_count == 0 or fresh_count != embed_count:
            return fresh_hist
        if embed_hist != fresh_hist:
            return fresh_hist
        return None

    if embed_grid >= 2 and (embed_count == 0 or fresh_count != embed_count):
        return fresh_hist

    return None


def describe_f8_historic_catchup(
    embed_hist: str,
    merged_hist: str,
    *,
    grid_number: int = 0,
) -> str | None:
    """Human-readable note when F8 embed historic was refreshed from a fresher disk export."""
    embed_hist = (embed_hist or "").strip()
    merged_hist = (merged_hist or "").strip()
    if not merged_hist or merged_hist == embed_hist:
        return None
    embed_count = _historic_words_count(embed_hist)
    merged_count = _historic_words_count(merged_hist)
    grid_part = f" on grid {grid_number}" if grid_number >= 1 else ""
    if merged_count > embed_count:
        return (
            f"Encounter historic caught up from disk "
            f"({embed_count}→{merged_count} words{grid_part}) — F8 embed refreshed."
        )
    if merged_count < embed_count:
        return (
            f"Encounter historic replaced from disk "
            f"({embed_count}→{merged_count} words{grid_part}) — F8 embed refreshed."
        )
    return (
        f"Encounter historic updated from disk "
        f"({embed_count} words{grid_part}) — F8 embed refreshed."
    )


def f8_historic_stale_after_merge_warning(
    extras: dict[str, Any] | None,
) -> str | None:
    """Warn when merged extras still disagree on previous word letter vs historic list."""
    data = extras if isinstance(extras, dict) else {}
    prev = str(data.get("previous_word_first_letter", "") or "").strip().lower()
    hist = str(data.get("historic_words", "") or "").strip()
    last_letter = _previous_letter_from_historic_words(hist)
    if not prev or not last_letter or prev == last_letter:
        return None
    return (
        f"run_state previous_word_first_letter ({prev}) does not match "
        f"last historic word ({last_letter}) — press F8 again."
    )


def merge_encounter_historic_for_f8_snapshot(
    run_state: dict | None,
) -> dict | None:
    """Return F8 gather state unchanged (live export only; no disk historic merge)."""
    if run_state is None:
        return None
    return copy.deepcopy(run_state)


F8_HISTORIC_CATCHUP_RETRIES = 6
F8_HISTORIC_CATCHUP_DELAY_SEC = 0.15


def _force_apply_disk_historic_when_ahead(
    run_state: dict | None,
) -> dict | None:
    """Disabled — live export only."""
    if run_state is None:
        return None
    return copy.deepcopy(run_state)


def merge_encounter_historic_for_f8_with_retry(
    run_state: dict | None,
    *,
    max_retries: int = F8_HISTORIC_CATCHUP_RETRIES,
    delay_sec: float = F8_HISTORIC_CATCHUP_DELAY_SEC,
) -> tuple[dict | None, str | None]:
    """Return F8 gather state unchanged (live export only; no disk historic merge)."""
    del max_retries, delay_sec
    if run_state is None:
        return None, None
    return copy.deepcopy(run_state), None


def raw_disk_historic_count_on_grid(grid: int) -> int:
    """Historic word count on disk for a grid (before reconcile)."""
    if grid < 1:
        return 0
    fresh = load_run_state_raw()
    if not isinstance(fresh, dict):
        return 0
    fresh_extras = fresh.get("extras")
    if not isinstance(fresh_extras, dict):
        return 0
    if _grid_number_from_extras(fresh_extras) != grid:
        return 0
    fresh_hist = str(fresh_extras.get("historic_words", "") or "").strip()
    return _historic_words_count(fresh_hist)


def encounter_historic_stale_pruned_on_disk(
    grid: int,
    *,
    board: Board | None = None,
) -> bool:
    """True when disk historic remains but reconcile clears it on the current board."""
    if grid < 1:
        return False
    raw_count = raw_disk_historic_count_on_grid(grid)
    if raw_count <= 0:
        return False
    reconciled_count = reconciled_disk_historic_count_on_grid(grid, board=board)
    return reconciled_count == 0


def reconciled_disk_historic_count_on_grid(
    grid: int,
    *,
    board: Board | None = None,
) -> int:
    """Historic word count on disk after reconcile_encounter_historic_for_scoring."""
    if grid < 1:
        return 0
    fresh = load_run_state_raw()
    if not isinstance(fresh, dict):
        return 0
    fresh_extras = fresh.get("extras")
    if not isinstance(fresh_extras, dict):
        return 0
    if _grid_number_from_extras(fresh_extras) != grid:
        return 0
    fresh_extras_cmp = copy.deepcopy(fresh_extras)
    reconcile_board = board
    if reconcile_board is None:
        reconcile_board = parse_board_from_run_state(fresh)
    reconcile_encounter_historic_for_scoring(
        fresh_extras_cmp,
        board=reconcile_board,
    )
    fresh_hist = str(fresh_extras_cmp.get("historic_words", "") or "").strip()
    return _historic_words_count(fresh_hist)


def f8_historic_still_behind_disk_warning(
    embed_extras: dict[str, Any] | None,
    *,
    board: Board | None = None,
) -> str | None:
    """Disabled — live export only; no disk historic lag warnings."""
    del embed_extras, board
    return None


def encounter_submit_signals_imply_prior_words(
    extras: dict[str, Any] | None,
    *,
    loadout: Loadout | None = None,
    board: Board | None = None,
) -> bool:
    """True when live export signals words were played but historic may be missing."""
    if not isinstance(extras, dict):
        return False
    if _scoring_previous_words_count_from_extras(extras) > 0:
        return True
    prev = str(extras.get("previous_word_first_letter", "") or "").strip()
    if prev:
        return True
    try:
        words_run = int(str(extras.get("words_submitted_this_run_count") or "0"))
    except (TypeError, ValueError):
        words_run = 0
    if words_run > 0:
        return True
    return False


def infer_submit_historic_projection(
    extras: dict[str, Any] | None,
    *,
    loadout: Loadout | None = None,
    board: Board | None = None,
) -> dict[str, Any]:
    """Minimal submit projection when historic is empty but other signals imply prior words."""
    if not isinstance(extras, dict):
        return {}
    hist = str(extras.get("historic_words", "") or "").strip()
    if hist and hist != "[]":
        return {}
    if not encounter_submit_signals_imply_prior_words(
        extras, loadout=loadout, board=board
    ):
        return {}
    from cursed_words_solver.suggestion import loadout_needs_historic_words_gather

    if not loadout_needs_historic_words_gather(loadout, board, extras):
        return {}
    spc = _scoring_previous_words_count_from_extras(extras)
    overlay: dict[str, Any] = {
        "scoring_previous_words_count": str(max(spc, 1)),
        "historic_words": json.dumps([{"word": "_inferred_submit_", "score": 0}]),
    }
    prev = str(extras.get("previous_word_first_letter", "") or "").strip()
    if prev:
        overlay["previous_word_first_letter"] = prev
    return overlay


def project_workflow_extras_for_f8_embed(
    extras: dict[str, Any],
    *,
    board: Board | None = None,
) -> None:
    """Path-stale reconcile on in-memory embed extras only (no disk re-read)."""
    reconcile_encounter_historic_for_scoring(extras, board=board)
    hist = str(extras.get("historic_words", "") or "").strip()
    last_from_hist = _previous_letter_from_historic_words(hist)
    spc = _scoring_previous_words_count_from_extras(extras)
    if last_from_hist and spc > 0:
        extras["previous_word_first_letter"] = last_from_hist
    else:
        reconcile_previous_word_first_letter_from_historic(extras)


TILE_NINJA_LIVE_EXTRA_KEYS = (
    "tile_ninja_bonus",
    "tile_ninja_bonus_last_known",
    "tile_ninja_bonus_at_grid_start",
    "tile_ninja_consumables_used",
    "tile_ninja_word_bonus_percent",
)

# Workflow extras embedded in last_suggestion.json (must match F8 scoring loadout).
F8_EMBED_WORKFLOW_EXTRA_KEYS = (
    "historic_words",
    "previous_word_first_letter",
    "red_tiles_used_encounter",
    "scoring_previous_words_count",
    "encounter_score_earned",
    "encounter_total_target",
    "encounter_remaining_target",
    "mutating_dna_letter_counts",
    "encounter_historic_source",
    "birthday_cake_bonus",
    "pin_memory",
    "pin_memory_count",
    "consumable_rack_count",
    "movie_camera_word_score_bonus",
    *TILE_NINJA_LIVE_EXTRA_KEYS,
)


def loadout_has_birthday_cake(loadout: Loadout | None) -> bool:
    """True when Birthday Cake is equipped or present in RAM pin memory."""
    if loadout is None:
        return False
    if any(
        (s.id or "").lower() == "birthday_cake"
        or "birthday" in (s.name or "").lower()
        for s in loadout.stickers
    ):
        return True
    from cursed_words_solver.rules.ram_memory import pin_memory_has_birthday_cake

    return pin_memory_has_birthday_cake(loadout)


def merge_f8_workflow_extras_into(
    dest: dict[str, Any],
    loadout_extras: dict[str, Any] | None,
) -> None:
    """Copy scoring loadout workflow fields into F8 embed extras (no disk read)."""
    if not isinstance(dest, dict) or not isinstance(loadout_extras, dict):
        return
    for key in F8_EMBED_WORKFLOW_EXTRA_KEYS:
        val = loadout_extras.get(key)
        if val is None or str(val).strip() == "":
            continue
        dest[key] = str(val) if not isinstance(val, str) else val


def align_embed_with_scoring_loadout(
    extras: dict[str, Any],
    scoring_extras: dict[str, Any] | None,
    *,
    board: Board | None = None,
) -> None:
    """Overlay scoring-truth workflow fields when melmod export lagged behind gather."""
    if not isinstance(extras, dict) or not isinstance(scoring_extras, dict):
        return

    reconciled = copy.deepcopy(scoring_extras)
    reconcile_encounter_historic_for_scoring(reconciled, board=board)

    embed_hist = str(extras.get("historic_words", "") or "").strip()
    rec_hist = str(reconciled.get("historic_words", "") or "").strip()
    embed_count = _historic_words_count(embed_hist)
    rec_count = _historic_words_count(rec_hist)

    if rec_count > embed_count and rec_hist:
        extras["historic_words"] = rec_hist
        for key in ("encounter_historic_source", "red_tiles_used_encounter"):
            val = reconciled.get(key)
            if val is not None and str(val).strip() != "":
                extras[key] = str(val) if not isinstance(val, str) else val
        embed_hist = rec_hist
        embed_count = rec_count

    if rec_count < embed_count:
        if rec_hist:
            extras["historic_words"] = rec_hist
            for key in ("encounter_historic_source", "red_tiles_used_encounter"):
                val = reconciled.get(key)
                if val is not None and str(val).strip() != "":
                    extras[key] = str(val) if not isinstance(val, str) else val
        elif _scoring_previous_words_count_from_extras(reconciled) <= 0:
            extras.pop("historic_words", None)
            extras.pop("red_tiles_used_encounter", None)
            src = str(reconciled.get("encounter_historic_source", "") or "").strip()
            if src:
                extras["encounter_historic_source"] = src
            else:
                extras.pop("encounter_historic_source", None)
        embed_hist = rec_hist
        embed_count = rec_count

    if embed_hist == rec_hist:
        embed_spc = _scoring_previous_words_count_from_extras(extras)
        rec_spc = _scoring_previous_words_count_from_extras(reconciled)
        if rec_spc > embed_spc:
            extras["scoring_previous_words_count"] = str(rec_spc)
        rec_letter = str(reconciled.get("previous_word_first_letter", "") or "").strip()
        spc = _scoring_previous_words_count_from_extras(extras)
        if rec_letter and spc > 0:
            extras["previous_word_first_letter"] = rec_letter
        elif spc == 0:
            extras.pop("previous_word_first_letter", None)

    skip = frozenset(
        {
            "historic_words",
            "previous_word_first_letter",
            "scoring_previous_words_count",
            "encounter_historic_source",
            "red_tiles_used_encounter",
            "mutating_dna_letter_counts",
            "birthday_cake_bonus",
            "movie_camera_word_score_bonus",
        }
    )
    cap_keys = ("birthday_cake_bonus", "movie_camera_word_score_bonus")
    for key in F8_EMBED_WORKFLOW_EXTRA_KEYS:
        if key in skip:
            continue
        val = reconciled.get(key)
        if val is None or str(val).strip() == "":
            continue
        extras[key] = str(val) if not isinstance(val, str) else val

    for cap_key in cap_keys:
        rec_val = reconciled.get(cap_key)
        if rec_val is None or str(rec_val).strip() == "":
            continue
        try:
            rec_i = int(str(rec_val).strip())
        except (TypeError, ValueError):
            extras[cap_key] = str(rec_val) if not isinstance(rec_val, str) else rec_val
            continue
        embed_i: int | None = None
        if cap_key in extras:
            try:
                embed_i = int(str(extras[cap_key]).strip())
            except (TypeError, ValueError):
                embed_i = None
        if embed_i is not None:
            # Prefer live F8 export when melmod is ahead of a lagging scoring loadout.
            extras[cap_key] = str(max(rec_i, embed_i))
        else:
            extras[cap_key] = str(rec_i)


def birthday_cake_embed_post_word_stale_note(
    embed_extras: dict[str, Any] | None,
    scoring_loadout: Loadout | None,
    board: Board | None,
    path: list[int] | None,
    word: str | None,
) -> str | None:
    """Warn when F8 embed birthday_cake_bonus is post-word total, not pre-word accumulated."""
    if not isinstance(embed_extras, dict) or scoring_loadout is None:
        return None
    if not loadout_has_birthday_cake(scoring_loadout):
        return None
    if board is None or not path:
        return None
    try:
        embed_val = int(str(embed_extras.get("birthday_cake_bonus") or "0"))
    except (TypeError, ValueError):
        return None
    if embed_val <= 0:
        return None
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    from cursed_words_solver.rules.scoring_conditions import (
        birthday_cake_accumulated,
        birthday_cake_improve_for_path,
    )

    acc = birthday_cake_accumulated(scoring_loadout)
    if embed_val <= acc:
        return None
    pipeline = ScoringPipeline()
    rule = pipeline.rules.get("stickers", {}).get("birthday_cake") or {}
    level = 1
    for sticker in scoring_loadout.stickers or []:
        if (sticker.id or "").lower() == "birthday_cake":
            level = max(1, int(sticker.level))
            break
    improve = birthday_cake_improve_for_path(
        board, list(path), level, rule, word or ""
    )
    if improve > 0 and embed_val == acc + improve:
        return (
            f"birthday_cake_bonus embed ({embed_val}) equals pre-word {acc} + "
            f"improve {improve} — export is post-word; press F8 again"
        )
    return None


def merge_tile_ninja_extras_into(
    dest: dict[str, Any],
    src: dict[str, Any] | None,
) -> None:
    """Overlay live melmod Tile Ninja fields into F8 embed / loadout extras."""
    if not isinstance(dest, dict) or not isinstance(src, dict):
        return
    src_extras = src.get("extras") if "extras" in src else src
    if not isinstance(src_extras, dict):
        return
    for key in TILE_NINJA_LIVE_EXTRA_KEYS:
        val = src_extras.get(key)
        if val is None or str(val).strip() == "":
            continue
        if key == "tile_ninja_consumables_used":
            try:
                int(val)
            except (TypeError, ValueError):
                dest[key] = val
                continue
            dest[key] = str(val)
            continue
        try:
            float(val)
        except (TypeError, ValueError):
            dest[key] = val
            continue
        dest[key] = val
    _backfill_tile_ninja_at_grid_start(dest)
    _backfill_tile_ninja_from_consumables_used(dest)


def hydrate_tile_ninja_loadout_extras(
    loadout: Loadout,
    run_state: dict[str, Any] | None = None,
) -> Loadout:
    """Merge live Tile Ninja counters into loadout before F8 search/scoring."""
    from dataclasses import replace

    from cursed_words_solver.rules.stamp_behaviors import loadout_has_stamp

    if not loadout_has_stamp(loadout, "tile_ninja"):
        return loadout
    extras = dict(loadout.extras or {})
    if isinstance(run_state, dict):
        merge_tile_ninja_extras_into(extras, run_state)
    else:
        _backfill_tile_ninja_from_consumables_used(extras)
    return replace(loadout, extras=extras)


def tile_ninja_placement_baseline_used(extras: dict[str, Any]) -> int:
    """Cumulative consumables-used anchor for placement sim."""
    if not isinstance(extras, dict):
        return 0
    raw = extras.get("tile_ninja_consumables_used")
    if raw not in (None, ""):
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    try:
        grid_start = float(extras.get("tile_ninja_bonus_at_grid_start", 0) or 0)
    except (TypeError, ValueError):
        grid_start = 0.0
    if grid_start > 0:
        return round(grid_start / 0.02)
    return infer_tile_ninja_used_from_extras(extras)


def infer_tile_ninja_used_from_extras(extras: dict[str, Any]) -> int:
    """Best-effort cumulative Tile Ninja consumables-used from melmod extras."""
    if not isinstance(extras, dict):
        return 0

    raw = extras.get("tile_ninja_consumables_used")
    try:
        exported = int(raw) if raw not in (None, "") else -1
    except (TypeError, ValueError):
        exported = -1

    bonus_derived = 0
    for key in (
        "tile_ninja_bonus",
        "tile_ninja_bonus_last_known",
        "tile_ninja_bonus_at_grid_start",
    ):
        try:
            bonus = float(extras.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue
        if bonus > 0:
            bonus_derived = max(bonus_derived, round(bonus / 0.02))

    if exported > 0:
        return max(exported, bonus_derived)
    if exported == 0:
        return bonus_derived if bonus_derived > 0 else 0
    return bonus_derived if bonus_derived > 0 else 0


def _backfill_tile_ninja_from_consumables_used(dest: dict[str, Any]) -> None:
    """When live bonus export is zero, derive from melmod consumables-used counter."""
    if not isinstance(dest, dict):
        return
    try:
        live = float(dest.get("tile_ninja_bonus", 0))
    except (TypeError, ValueError):
        live = 0.0
    try:
        last_known = float(dest.get("tile_ninja_bonus_last_known", 0))
    except (TypeError, ValueError):
        last_known = 0.0
    if max(live, last_known) > 0:
        return
    used = infer_tile_ninja_used_from_extras(dest)
    if used <= 0:
        return
    bonus = used * 0.02
    serialized = str(bonus)
    dest["tile_ninja_bonus"] = serialized
    dest["tile_ninja_bonus_last_known"] = serialized


def _backfill_tile_ninja_at_grid_start(dest: dict[str, Any]) -> None:
    """Seed at_grid_start from last_known when live export still carries zero."""
    if not isinstance(dest, dict):
        return
    try:
        grid_start = float(dest.get("tile_ninja_bonus_at_grid_start", 0))
    except (TypeError, ValueError):
        grid_start = 0.0
    if grid_start > 0:
        return
    seed = 0.0
    seed_key = ""
    for key in ("tile_ninja_bonus_last_known", "tile_ninja_bonus"):
        try:
            val = float(dest.get(key, 0))
        except (TypeError, ValueError):
            continue
        if val > seed:
            seed = val
            seed_key = key
    if seed <= 0 or not seed_key:
        return
    raw = dest.get(seed_key)
    if isinstance(raw, str) and raw.strip():
        dest["tile_ninja_bonus_at_grid_start"] = raw.strip()
    else:
        dest["tile_ninja_bonus_at_grid_start"] = str(seed)


def _michael_finale_embed_context(run_state: dict[str, Any]) -> bool:
    """True when run_state carries Michael finale metadata (submit clears boss reconcile keys)."""
    if not isinstance(run_state, dict):
        return False
    extras = run_state.get("extras")
    if not isinstance(extras, dict):
        extras = {}
    probe = str(extras.get("michael_finale_probe") or "").strip()
    if "finale=1" in probe.lower():
        return True
    try:
        phase = int(extras.get("michael_phase") or 0)
    except (TypeError, ValueError):
        phase = 0
    if phase >= 4:
        return True
    defeated = str(extras.get("michael_summoned_bosses_defeated") or "").strip().lower()
    if defeated in ("1", "true", "yes"):
        return True
    boss_id = str(run_state.get("boss_id") or "").strip().lower()
    return boss_id == "michael"


def _strip_non_scoring_boss_embed(run_state: dict[str, Any]) -> None:
    """Drop boss reconcile keys that Michael finale scoring does not use at submit."""
    if not isinstance(run_state, dict):
        return
    extras = run_state.get("extras")
    if not isinstance(extras, dict):
        return
    if _boss_modifiers_active(extras.get("boss_modifiers")):
        return
    if not _michael_finale_embed_context(run_state):
        return
    for key in BOSS_RECONCILE_EXTRA_KEYS:
        extras.pop(key, None)


def sanitize_run_state_snapshot_for_f8(
    run_state: dict | None,
    loadout: Loadout,
    *,
    fresh_run_state: dict[str, Any] | None = None,
) -> dict | None:
    """Trim unequipped-item extras from the F8 embed; game export is otherwise as-is."""
    if run_state is None:
        return None

    snapshot = copy.deepcopy(run_state)
    extras = snapshot.get("extras")
    if not isinstance(extras, dict):
        return snapshot

    if not _is_bicycle_pin(loadout):
        extras.pop("bicycle_word_score_bonus", None)
        extras.pop("cards_submitted", None)
        extras.pop("bicycle_suited_on_path", None)

    if not _has_mutating_dna_stamp(loadout):
        extras.pop("mutating_dna_letter_counts", None)

    if not _has_neapolitan_stamp(loadout):
        extras.pop("neapolitan_percent", None)
        extras.pop("neapolitan_percent_last_known", None)

    if not _has_ruler_stamp(loadout):
        extras.pop("ruler_distance", None)
        extras.pop("ruler_distance_last_known", None)

    if not _has_steak_stamp(loadout):
        extras.pop("steak_word_bonus_percent", None)
        extras.pop("rare_item_count", None)
        extras.pop("rare_item_count_last_known", None)

    if not _has_snapshot_sticker(loadout):
        for key in (
            "snapshot_copy_slug",
            "snapshot_copy_level",
            "snapshot_copy_captured_at",
            "snapshot_copy_source",
        ):
            extras.pop(key, None)

    from cursed_words_solver.fingerprints import loadout_fingerprint as _loadout_fp

    extras["loadout_fingerprint"] = _loadout_fp(loadout)
    _strip_non_scoring_boss_embed(snapshot)
    reconcile_boss_extras_for_f8_embed(
        snapshot,
        fresh_run_state=fresh_run_state,
    )
    _strip_finale_boss_embed_for_non_boss_node(snapshot)
    snapshot["extras"] = extras
    return snapshot


def _strip_finale_boss_embed_for_non_boss_node(run_state: dict[str, Any]) -> None:
    """Drop Michael finale boss metadata when F8 embed is not on a boss node."""
    if not isinstance(run_state, dict):
        return
    extras = run_state.get("extras")
    if not isinstance(extras, dict):
        return
    node = str(extras.get("run_node_type") or "").strip().lower()
    if "boss" in node:
        return
    for key in BOSS_RECONCILE_EXTRA_KEYS + FINALE_BOSS_EMBED_KEYS:
        extras.pop(key, None)
    run_state["boss_id"] = ""
    run_state["boss_name"] = ""
    run_state["boss_effect"] = ""


def loadout_fingerprint_stale_warning(
    loadout: Loadout | None,
    run_state_extras: dict[str, Any] | None = None,
) -> str | None:
    """Warn when melmod extras.loadout_fingerprint disagrees with parsed loadout."""
    if loadout is None:
        return None
    from cursed_words_solver.fingerprints import loadout_fingerprint

    computed = loadout_fingerprint(loadout)
    extras = run_state_extras if isinstance(run_state_extras, dict) else (loadout.extras or {})
    exported = str(extras.get("loadout_fingerprint", "") or "").strip()
    if not exported or exported == computed:
        return None
    return (
        "run_state loadout_fingerprint disagrees with parsed loadout "
        f"({exported} vs {computed}) — press F8 again."
    )


def align_bicycle_extras_from_fingerprint(
    extras: dict[str, Any],
    loadout: Loadout,
    *,
    export_fingerprint: str | None = None,
) -> None:
    """Prefer live pin acc from melmod loadout_fingerprint over lagging export fields."""
    if not isinstance(extras, dict) or not _is_bicycle_pin(loadout):
        return
    from cursed_words_solver.rules.scoring_conditions import (
        bicycle_pin_accumulator_from_fingerprint,
    )

    fp = str(export_fingerprint or "").strip()
    if not fp:
        fp = str(extras.get("loadout_fingerprint", "") or "").strip()
    if not fp and isinstance(loadout.extras, dict):
        fp = str(loadout.extras.get("loadout_fingerprint", "") or "").strip()
    pin_acc = bicycle_pin_accumulator_from_fingerprint(fp)
    if pin_acc is None:
        return
    extras["bicycle_word_score_bonus"] = str(pin_acc)
    extras["cards_submitted"] = str(pin_acc)


def bicycle_extras_stale_warning(loadout: Loadout | None) -> str | None:
    """Warn when run_state may under-count Bicycle word score at F8."""
    if loadout is None or not _is_bicycle_pin(loadout):
        return None
    extras = loadout.extras or {}
    bonus_raw = extras.get("bicycle_word_score_bonus")
    cards_raw = extras.get("cards_submitted")
    if bonus_raw is None and cards_raw is None:
        return (
            "Bicycle pin: bicycle_word_score_bonus missing from run_state — "
            "press F8 again or rebuild melmod before trusting Bicycle scores."
        )
    try:
        bonus = int(bonus_raw) if bonus_raw is not None else -1
    except (TypeError, ValueError):
        bonus = -1
    try:
        cards = int(cards_raw) if cards_raw is not None else 0
    except (TypeError, ValueError):
        cards = 0
    if bonus_raw is None and cards > 0:
        return (
            f"Bicycle pin: bicycle_word_score_bonus missing but cards_submitted={cards} — "
            "press F8 again or wait for melmod refresh."
        )
    if bonus == 0 and cards > 0:
        return (
            f"Bicycle pin: bicycle_word_score_bonus is 0 but cards_submitted={cards} — "
            "press F8 again or wait for melmod refresh."
        )
    from cursed_words_solver.rules.scoring_conditions import (
        bicycle_pin_accumulator_from_fingerprint,
    )

    fp = str(extras.get("loadout_fingerprint", "") or "")
    pin_acc = bicycle_pin_accumulator_from_fingerprint(fp)
    acc = bonus if bonus >= 0 else cards
    if pin_acc is not None and acc >= 0 and pin_acc != acc:
        return (
            f"Bicycle pin: run_state bonus={acc} but loadout fingerprint has {pin_acc} — "
            "press F8 again or wait for melmod refresh."
        )
    return None


def steak_extras_stale_warning(loadout: Loadout | None) -> str | None:
    """Warn when Steak is equipped but scoring extras were never captured."""
    if loadout is None:
        return None
    from cursed_words_solver.rules.stamp_behaviors import loadout_has_stamp

    if not loadout_has_stamp(loadout, "steak"):
        return None
    extras = loadout.extras or {}
    raw_pct = extras.get("steak_word_bonus_percent")
    if raw_pct not in (None, ""):
        try:
            if int(raw_pct) >= 100:
                return None
        except (TypeError, ValueError):
            pass
    if _extra_int_positive(extras, "rare_item_count_last_known") is not None:
        return None
    if _extra_int_positive(extras, "rare_item_count") is not None:
        return None
    return (
        "Steak: steak_word_bonus_percent and rare_item_count missing from run_state — "
        "press F8 again or submit a word so melmod can export Steak scoring."
    )


def _extra_int_positive(extras: dict, key: str) -> int | None:
    raw = extras.get(key)
    if raw is None or raw == "":
        return None
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    return val if val >= 0 else None


def neapolitan_extras_stale_warning(loadout: Loadout | None) -> str | None:
    """Warn when Neapolitan's live percent is missing and fallback is used."""
    if loadout is None or not _has_neapolitan_stamp(loadout):
        return None
    from cursed_words_solver.rules.scoring_conditions import (
        neapolitan_base_percent_from_loadout,
    )

    _base_percent, source = neapolitan_base_percent_from_loadout(loadout)
    if source == "live":
        return None
    return (
        "Neapolitan: live baseline missing from run_state, defaulting to 100% — "
        "press F8 so melmod can export neapolitan_percent."
    )


def format_loadout_summary(loadout: Loadout | None) -> str:
    """Short human-readable loadout line for console/overlay."""
    if loadout is None:
        return (
            "loadout: none (F9 to edit, or install melmod + F7 in the game — "
            "not in this terminal)"
        )
    parts = []
    if loadout.character:
        parts.append(loadout.character)
    if loadout.stickers:
        parts.append(f"{len(loadout.stickers)} sticker(s)")
    if loadout.stamps:
        parts.append(f"{len(loadout.stamps)} stamp(s)")
    from cursed_words_solver.rules.boss_effects import (
        active_boss_ids,
        michael_encounter_active,
    )

    if michael_encounter_active(loadout):
        parts.append("boss=Michael")
        mods = active_boss_ids(loadout)
        if mods:
            parts.append(f"modifiers=[{', '.join(mods)}]")
    elif loadout.boss_id or loadout.boss_name:
        bid = (loadout.boss_id or "").strip()
        bname = (loadout.boss_name or "").strip()
        if bid:
            if bname and slugify_name(bname) == bid.lower():
                parts.append(f"boss={bname}")
            else:
                parts.append(f"boss={bid}")
        elif bname:
            parts.append(f"boss={bname}")
        mods = loadout.extras.get("boss_modifiers")
        if isinstance(mods, list) and len(mods) > 1:
            parts.append(f"modifiers=[{', '.join(str(m) for m in mods)}]")
    pin = loadout.extras.get("pin_effect")
    if pin:
        branch = f" ({loadout.pin_branch})" if loadout.pin_branch else ""
        left = loadout.extras.get("pin_left_level")
        right = loadout.extras.get("pin_right_level")
        levels = ""
        if left is not None or right is not None:
            levels = f" L{left or 0}/R{right or 0}"
        parts.append(f"pin={pin}{levels}{branch}")
    memory = loadout.extras.get("pin_memory")
    if isinstance(memory, list) and memory:
        parts.append(f"RAM={len(memory)}")
    if _is_bicycle_pin(loadout):
        bonus = loadout.extras.get("bicycle_word_score_bonus")
        if bonus is not None:
            parts.append(f"Bicycle={int(bonus)}")
        else:
            cards = loadout.extras.get("cards_submitted")
            if cards is not None:
                parts.append(f"Bicycle=? (cards_submitted={cards}; F7 if stale)")
    else:
        cards = loadout.extras.get("cards_submitted")
        if cards:
            parts.append(f"cards={cards}")
    has_birthday = any(
        (s.id or "").lower() == "birthday_cake"
        or "birthday" in (s.name or "").lower()
        for s in loadout.stickers
    )
    if not has_birthday:
        from cursed_words_solver.rules.ram_memory import pin_memory_has_birthday_cake

        has_birthday = pin_memory_has_birthday_cake(loadout)
    if has_birthday:
        bday = loadout.extras.get("birthday_cake_bonus")
        if bday is not None and int(bday) > 0:
            parts.append(f"Birthday={int(bday)}")
        else:
            parts.append("Birthday=? (press F8 again; rebuild melmod if stuck at 0)")
    has_movie_camera = any(
        (s.id or "").lower() == "movie_camera"
        for s in loadout.stickers
    )
    if has_movie_camera:
        mc = loadout.extras.get("movie_camera_word_score_bonus")
        if mc is not None and int(mc) > 0:
            parts.append(f"Movie Camera={int(mc)}")
        else:
            parts.append("Movie Camera=? (press F8 again; rebuild melmod if stuck at 0)")
    if loadout.money:
        parts.append(f"${loadout.money}")
    return "loadout: " + (", ".join(parts) if parts else "empty")


def parse_board_from_prepared_run_state(data: dict[str, Any]) -> Board | None:
    """Parse board after submit-time merge (take flags, etc.)."""
    return parse_board_from_run_state(prepare_run_state_dict_for_scoring(data))


def merge_loadout_with_board(
    loadout: Loadout | None,
    board_money: int,
    *,
    mod_money: int | None = None,
) -> Loadout:
    lo = loadout or Loadout()
    preferred = mod_money if mod_money is not None and mod_money > 0 else board_money
    if preferred > 0:
        lo.money = preferred
    elif board_money > 0 and not lo.money:
        lo.money = board_money
    return lo


def _parse_shop_offer(raw: dict[str, Any]) -> ShopOffer:
    return ShopOffer(
        slot=str(raw.get("slot", "")),
        index=int(raw.get("index", 0)),
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        level=max(1, int(raw.get("level", 1))),
        foil=bool(raw.get("foil", False)),
        price=int(raw.get("price", 0)),
        base_price=int(raw.get("base_price", raw.get("price", 0))),
        frozen=bool(raw.get("frozen", False)),
        free=bool(raw.get("free", False)),
        sold=bool(raw.get("sold", False)),
        hippo_eligible=bool(raw.get("hippo_eligible", False)),
        color=str(raw.get("color", "")),
        curse=str(raw.get("curse", "")),
        letter=str(raw.get("letter", "")),
        base_score=float(raw.get("base_score", 0) or 0),
    )


def parse_shop_from_run_state(data: dict[str, Any] | None) -> ShopState | None:
    if not isinstance(data, dict):
        return None
    shop_raw = data.get("shop")
    if not isinstance(shop_raw, dict):
        return None
    offers = [
        _parse_shop_offer(o)
        for o in shop_raw.get("offers", [])
        if isinstance(o, dict)
    ]
    return ShopState(
        restock_cost=int(shop_raw.get("restock_cost", 0)),
        free_item_available=bool(shop_raw.get("free_item_available", False)),
        angel_investment_available=bool(shop_raw.get("angel_investment_available", False)),
        hungry_hippo_equipped=bool(shop_raw.get("hungry_hippo_equipped", False)),
        offers=offers,
    )


def parse_inventory_sell(data: dict[str, Any] | None) -> list[SellCandidate]:
    if not isinstance(data, dict):
        return []
    rows = data.get("inventory_sell")
    if not isinstance(rows, list):
        return []
    result: list[SellCandidate] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        result.append(
            SellCandidate(
                kind=str(raw.get("kind", "")),
                slot=int(raw.get("slot", 0)),
                id=str(raw.get("id", "")),
                name=str(raw.get("name", "")),
                level=max(1, int(raw.get("level", 1))),
                foil=bool(raw.get("foil", False)),
                sell_value=int(raw.get("sell_value", 0)),
                sell_cost=int(raw.get("sell_cost", 0)),
                costs_money_to_sell=bool(raw.get("costs_money_to_sell", False)),
            )
        )
    return result


def _parse_encounter_grid_reroll_raw(raw: dict[str, Any]) -> EncounterGridRerollState:
    cost_per_use = raw.get("cost_per_use", raw.get("cost", 0))
    can_reroll = raw.get("can_reroll", raw.get("available", False))
    return EncounterGridRerollState(
        remaining=int(raw.get("remaining", 0)),
        cost_per_use=int(cost_per_use),
        can_reroll=bool(can_reroll),
        wheel_equipped=bool(raw.get("wheel_equipped", False)),
        fan_equipped=bool(raw.get("fan_equipped", False)),
    )


def parse_encounter_grid_reroll(
    data: dict[str, Any] | None,
) -> EncounterGridRerollState | None:
    if not isinstance(data, dict):
        return None
    raw = data.get("encounter_grid_reroll")
    if not isinstance(raw, dict):
        raw = data.get("encounter_reroll")
    if not isinstance(raw, dict):
        return None
    return _parse_encounter_grid_reroll_raw(raw)


def parse_encounter_reroll(data: dict[str, Any] | None) -> EncounterGridRerollState | None:
    """Deprecated alias for parse_encounter_grid_reroll."""
    return parse_encounter_grid_reroll(data)


def _has_valid_board_export(data: dict[str, Any]) -> bool:
    board_data = data.get("board")
    if not isinstance(board_data, dict):
        return False
    tiles_raw = board_data.get("tiles")
    return isinstance(tiles_raw, list) and len(tiles_raw) in (25, 36)


def _has_shop_offers(data: dict[str, Any]) -> bool:
    shop_raw = data.get("shop")
    if not isinstance(shop_raw, dict):
        return False
    offers = shop_raw.get("offers")
    return isinstance(offers, list) and len(offers) > 0


def encounter_mode_from_run_state(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return "none"
    extras = data.get("extras")
    if isinstance(extras, dict):
        mode = str(extras.get("encounter_mode", "") or "").strip().lower()
        if mode == "cursedle":
            return "cursedle"
    if _has_valid_board_export(data):
        return "encounter"
    if _has_shop_offers(data):
        return "shop"
    extras = data.get("extras")
    if isinstance(extras, dict):
        mode = str(extras.get("encounter_mode", "") or "").strip().lower()
        if mode and mode != "none":
            return mode
    return "none"
