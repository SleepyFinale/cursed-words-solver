"""Loadout capture: MelonLoader JSON, manual UI, stub tray OCR."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cursed_words_solver.config import RUN_STATE_PATH
from cursed_words_solver.models import (
    CURRENCY_MAP,
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)


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
        sym = char or letter
        if sym in CURRENCY_MAP:
            return CURRENCY_MAP[sym]
        if len(letter) == 1 and letter.isalpha():
            return letter.upper()
        return "?"
    if curse == CurseType.NUMBER:
        return letter if letter else char
    if curse == CurseType.FRACTION:
        return letter if letter else "?"
    ch = (letter or char or "?").strip().upper()
    if len(ch) == 1 and (ch.isalpha() or ch.isdigit() or ch == "?"):
        return ch
    return "?"


def _melmod_row_to_solver(board_data: dict[str, Any], game_row: int) -> int:
    """Map melmod row index to solver/OCR row (0 = top of screen)."""
    if board_data.get("row_order") == "top_first":
        return game_row
    # Legacy exports: Unity grid row 0 is the bottom row on screen.
    return 4 - game_row


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

    for entry in tiles_raw:
        if not isinstance(entry, dict):
            return None
        game_row = int(entry.get("row", -1))
        col = int(entry.get("col", -1))
        if game_row < 0 or game_row > 4 or col < 0 or col > 4:
            return None
        row = _melmod_row_to_solver(board_data, game_row)

        char = str(entry.get("char", entry.get("char_display", "?")) or "?")
        letter_raw = str(entry.get("letter", char) or char)
        color_key = str(entry.get("color", "colorless") or "colorless").lower()
        curse_key = str(entry.get("curse", "letter") or "letter").lower()
        color = _COLOR_MAP.get(color_key, TileColor.UNKNOWN)
        curse = _CURSE_MAP.get(curse_key, CurseType.UNKNOWN)
        letter = _resolve_letter_for_word(char, letter_raw, curse)

        number_value = entry.get("number_value")
        fraction_value = entry.get("fraction_value")

        grid[row][col] = Tile(
            row=row,
            col=col,
            char=char,
            letter=letter,
            base_score=int(entry.get("base_score", 0)),
            color=color,
            curse=curse,
            number_value=int(number_value) if number_value is not None else None,
            fraction_value=float(fraction_value) if fraction_value is not None else None,
            ocr_confidence=1.0,
            metadata={"source": "melmod"},
        )

    if any(grid[r][c] is None for r in range(5) for c in range(5)):
        return None

    tiles = [[grid[r][c] for c in range(5)] for r in range(5)]
    return Board(tiles=tiles, money=money)


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
    return Loadout(
        character=data.get("character", ""),
        pin_branch=data.get("pin_branch", ""),
        stickers=stickers,
        stamps=stamps,
        boss_id=data.get("boss_id", ""),
        boss_name=data.get("boss_name", ""),
        boss_effect=data.get("boss_effect", ""),
        money=int(data.get("money", 0)),
        extras=data.get("extras", {}),
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
        parts.append(f"boss={loadout.boss_id or loadout.boss_name}")
    pin = loadout.extras.get("pin_effect")
    if pin:
        branch = f" ({loadout.pin_branch})" if loadout.pin_branch else ""
        parts.append(f"pin={pin}{branch}")
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
