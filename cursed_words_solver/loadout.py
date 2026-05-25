"""Loadout capture: MelonLoader JSON and manual UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cursed_words_solver.config import RUN_STATE_PATH
from cursed_words_solver.rules.rule_lookup import slugify_name
from cursed_words_solver.rules.fraction_tiles import attach_fraction_metadata
from cursed_words_solver.models import (
    CURRENCY_MAP,
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
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


def _read_run_state_json(path: Path) -> dict[str, Any] | None:
    """Parse run_state.json (melmod writes UTF-8 with BOM on Windows)."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def load_run_state_raw(path: Path | None = None) -> dict[str, Any] | None:
    """Load raw run_state.json dict from companion mod or manual edit."""
    path = path or RUN_STATE_PATH
    if not path.exists():
        return None
    return _read_run_state_json(path)


def load_run_state(path: Path | None = None) -> Loadout | None:
    """Load run state exported by companion mod or manual JSON."""
    data = load_run_state_raw(path)
    if data is None:
        return None
    return parse_run_state(data)


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
    """User-facing steps when the companion mod or F7 export is missing."""
    return (
        "Install the MelonLoader companion mod (see melmod/README.md in the repo), "
        "start a run in-game, then press F7 to export the board to run_state.json."
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
    if not isinstance(tiles_raw, list) or len(tiles_raw) != 25:
        return None

    money = mod_money_from_run_state(data)
    grid: list[list[Tile | None]] = [[None] * 5 for _ in range(5)]
    active = [False] * 25

    try:
        board_rows = int(board_data.get("rows", 5))
        board_cols = int(board_data.get("cols", 5))
    except (TypeError, ValueError):
        board_rows, board_cols = 5, 5
    board_rows = max(1, min(5, board_rows))
    board_cols = max(1, min(5, board_cols))

    for entry in tiles_raw:
        if not isinstance(entry, dict):
            return None
        game_row = int(entry.get("row", -1))
        col = int(entry.get("col", -1))
        if game_row < 0 or game_row > 4 or col < 0 or col > 4:
            return None
        row = _melmod_row_to_solver(board_data, game_row)
        idx = row * 5 + col

        curse_key = str(entry.get("curse", "letter") or "letter").lower()
        is_active = entry.get("active", True)
        if curse_key == "inactive":
            is_active = False
        if is_active in (False, "false", "False", "0", 0):
            is_active = False
        else:
            is_active = True
        active[idx] = bool(is_active)

        char = normalize_tile_glyph(
            str(entry.get("char", entry.get("char_display", "?")) or "?")
        )
        letter_raw = normalize_tile_glyph(str(entry.get("letter", char) or char))
        color_key = str(entry.get("color", "colorless") or "colorless").lower()
        if not is_active:
            curse_key = "inactive"
            char = ""
            letter_raw = ""
            color_key = "colorless"

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
        if entry.get("is_joker") in (True, "true", "True", "1", 1):
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

    if any(grid[r][c] is None for r in range(5) for c in range(5)):
        return None

    tiles = [[grid[r][c] for c in range(5)] for r in range(5)]

    playable_origin = str(board_data.get("playable_origin") or "").strip().lower()
    has_bounds = "playable_min_row" in board_data
    try:
        pmin_r = int(board_data.get("playable_min_row", 0))
        pmax_r = int(board_data.get("playable_max_row", 4))
        pmin_c = int(board_data.get("playable_min_col", 0))
        pmax_c = int(board_data.get("playable_max_col", 4))
    except (TypeError, ValueError):
        pmin_r, pmax_r, pmin_c, pmax_c = 0, 4, 0, 4

    if not has_bounds and (board_rows < 5 or board_cols < 5):
        min_r, max_r, min_c, max_c = 5, -1, 5, -1
        for r in range(5):
            for c in range(5):
                if active[r * 5 + c]:
                    min_r = min(min_r, r)
                    max_r = max(max_r, r)
                    min_c = min(min_c, c)
                    max_c = max(max_c, c)
        if max_r >= 0:
            pmin_r, pmax_r, pmin_c, pmax_c = min_r, max_r, min_c, max_c
            if not playable_origin:
                if min_r == 0:
                    playable_origin = "top_left"
                elif max_r == 4:
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


def _normalize_pin_extras(extras: dict[str, Any]) -> dict[str, Any]:
    """Parse melmod string extras into structures the scoring pipeline uses."""
    out = dict(extras)
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
        "bicycle_suited_on_path",
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
        "fairy_count",
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
    ):
        if key in out:
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError):
                out[key] = 0
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
    if "previous_word_first_letter" in out and out["previous_word_first_letter"]:
        out["previous_word_first_letter"] = (
            str(out["previous_word_first_letter"]).strip().lower()[:1]
        )
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
    return out


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
    return Loadout(
        character=data.get("character", ""),
        pin_branch=data.get("pin_branch", ""),
        stickers=stickers,
        stamps=stamps,
        boss_id=boss_id,
        boss_name=boss_name,
        boss_effect=data.get("boss_effect", ""),
        money=int(data.get("money", 0)),
        extras=_normalize_pin_extras(data.get("extras", {}) or {}),
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
            "press F7 in-game or rebuild melmod before trusting Bicycle scores."
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
            "press F7 in-game or wait for melmod refresh."
        )
    if bonus == 0 and cards > 0:
        return (
            f"Bicycle pin: bicycle_word_score_bonus is 0 but cards_submitted={cards} — "
            "press F7 in-game or wait for melmod refresh."
        )
    return None


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
    if loadout.boss_id or loadout.boss_name:
        bid = (loadout.boss_id or "").strip()
        bname = (loadout.boss_name or "").strip()
        if bid:
            if bname and slugify_name(bname) == bid.lower():
                parts.append(f"boss={bname}")
            else:
                parts.append(f"boss={bid}")
        elif bname:
            parts.append(f"boss={bname}")
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
    if has_birthday:
        bday = loadout.extras.get("birthday_cake_bonus")
        if bday is not None and int(bday) > 0:
            parts.append(f"Birthday={int(bday)}")
        else:
            parts.append("Birthday=? (F7 in-game; rebuild melmod if stuck at 0)")
    if loadout.money:
        parts.append(f"${loadout.money}")
    return "loadout: " + (", ".join(parts) if parts else "empty")


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
