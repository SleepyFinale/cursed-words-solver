"""Tests for melmod board export ingestion."""

import json

from cursed_words_solver.loadout import (
    merge_loadout_with_board,
    mod_money_from_run_state,
    parse_board_from_run_state,
    parse_run_state,
)
from cursed_words_solver.rules.boss_effects import boss_word_constraints, load_rules_catalog
from cursed_words_solver.models import CurseType, TileColor
from cursed_words_solver.vision.board_parser import format_board_grid

SAMPLE_BOARD_JSON = {
    "character": "Test",
    "money": 42,
    "stickers": [],
    "stamps": [],
    "board": {
        "source": "melmod",
        "row_order": "top_first",
        "money": 42,
        "rows": 5,
        "cols": 5,
        "tiles": [
            {"row": 0, "col": 0, "char": "N", "letter": "N", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 0, "col": 1, "char": "A", "letter": "A", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 0, "col": 2, "char": "E", "letter": "E", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 0, "col": 3, "char": "W", "letter": "W", "base_score": 4, "color": "shiny", "curse": "letter"},
            {"row": 0, "col": 4, "char": "O", "letter": "O", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 1, "col": 0, "char": "U", "letter": "U", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 1, "col": 1, "char": "G", "letter": "G", "base_score": 2, "color": "shiny", "curse": "letter"},
            {"row": 1, "col": 2, "char": "K", "letter": "K", "base_score": 5, "color": "shiny", "curse": "letter"},
            {"row": 1, "col": 3, "char": "1", "letter": "1", "base_score": 1, "color": "shiny", "curse": "number", "number_value": 1},
            {"row": 1, "col": 4, "char": "E", "letter": "E", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 2, "col": 0, "char": "X", "letter": "X", "base_score": 8, "color": "shiny", "curse": "letter"},
            {"row": 2, "col": 1, "char": "E", "letter": "E", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 2, "col": 2, "char": "I", "letter": "I", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 2, "col": 3, "char": "R", "letter": "R", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 2, "col": 4, "char": "O", "letter": "O", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 3, "col": 0, "char": "E", "letter": "E", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 3, "col": 1, "char": "S", "letter": "S", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 3, "col": 2, "char": "E", "letter": "E", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 3, "col": 3, "char": "I", "letter": "I", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 3, "col": 4, "char": "K", "letter": "K", "base_score": 5, "color": "shiny", "curse": "letter"},
            {"row": 4, "col": 0, "char": "E", "letter": "E", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 4, "col": 1, "char": "B", "letter": "B", "base_score": 3, "color": "shiny", "curse": "letter"},
            {"row": 4, "col": 2, "char": "K", "letter": "K", "base_score": 5, "color": "shiny", "curse": "letter"},
            {"row": 4, "col": 3, "char": "O", "letter": "O", "base_score": 1, "color": "shiny", "curse": "letter"},
            {"row": 4, "col": 4, "char": "P", "letter": "P", "base_score": 3, "color": "shiny", "curse": "letter"},
        ],
    },
}


def test_parse_board_from_run_state_full_grid():
    board = parse_board_from_run_state(SAMPLE_BOARD_JSON)
    assert board is not None
    assert board.money == 42
    assert format_board_grid(board) == (
        "N A E W O\n"
        "U G K 1 E\n"
        "X E I R O\n"
        "E S E I K\n"
        "E B K O P"
    )


def test_number_tile_curse():
    board = parse_board_from_run_state(SAMPLE_BOARD_JSON)
    assert board is not None
    tile = board.get(1, 3)
    assert tile is not None
    assert tile.curse == CurseType.NUMBER
    assert tile.letter == "1"
    assert tile.number_value == 1


def test_mod_money_from_run_state():
    assert mod_money_from_run_state(SAMPLE_BOARD_JSON) == 42
    assert mod_money_from_run_state({"money": 99}) == 99


def test_legacy_melmod_bottom_row_zero_is_flipped():
    """Game grid row 0 = bottom; solver row 0 = top."""
    bottom_row = {
        "board": {
            "source": "melmod",
            "tiles": [
                {"row": 0, "col": c, "char": "B", "letter": "B", "curse": "letter"}
                for c in range(5)
            ]
            + [
                {"row": r, "col": c, "char": "X", "letter": "X", "curse": "letter"}
                for r in range(1, 5)
                for c in range(5)
            ],
        }
    }
    board = parse_board_from_run_state(bottom_row)
    assert board is not None
    assert format_board_grid(board).split("\n")[0] == "X X X X X"
    assert format_board_grid(board).split("\n")[4] == "B B B B B"


def test_row_order_top_first_skips_flip():
    top_row = {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "tiles": [
                {"row": 0, "col": c, "char": "T", "letter": "T", "curse": "letter"}
                for c in range(5)
            ]
            + [
                {"row": r, "col": c, "char": "B", "letter": "B", "curse": "letter"}
                for r in range(1, 5)
                for c in range(5)
            ],
        }
    }
    board = parse_board_from_run_state(top_row)
    assert board is not None
    assert format_board_grid(board).split("\n")[0] == "T T T T T"
    assert format_board_grid(board).split("\n")[4] == "B B B B B"


def test_parse_board_invalid_returns_none():
    assert parse_board_from_run_state(None) is None
    assert parse_board_from_run_state({}) is None
    assert parse_board_from_run_state({"board": {"tiles": []}}) is None


def test_merge_loadout_prefers_mod_money():
    loadout = parse_run_state({"character": "X", "money": 42, "stickers": [], "stamps": []})
    merged = merge_loadout_with_board(loadout, board_money=5, mod_money=42)
    assert merged.money == 42


def test_tile_color_mapping():
    board = parse_board_from_run_state(SAMPLE_BOARD_JSON)
    assert board is not None
    assert board.get(0, 0).color == TileColor.SHINY


def _bat_3x4_run_state() -> dict:
    """Bat shrunk grid: 3 rows × 4 cols (top_first, anchored at rows 2–4 in 5×5)."""
    letters = {
        (2, 0): "A",
        (2, 1): "E",
        (2, 2): "T",
        (2, 3): "W",
        (3, 0): "R",
        (3, 1): "H",
        (3, 2): "E",
        (3, 3): "N",
        (4, 0): "O",
        (4, 1): "O",
        (4, 2): "T",
        (4, 3): "T",
    }
    tiles = []
    for row in range(5):
        for col in range(5):
            ch = letters.get((row, col))
            in_play = ch is not None
            tiles.append(
                {
                    "row": row,
                    "col": col,
                    "char": ch or "",
                    "letter": ch or "",
                    "base_score": 1 if in_play else 0,
                    "color": "colorless",
                    "curse": "letter" if in_play else "inactive",
                    "active": in_play,
                }
            )
    return {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "rows": 3,
            "cols": 4,
            "tiles": tiles,
        }
    }


def test_parse_board_bat_3x4_from_run_state():
    board = parse_board_from_run_state(_bat_3x4_run_state())
    assert board is not None
    assert board.rows == 3
    assert board.cols == 4
    assert sum(board.active) == 12
    assert board.get(2, 3).letter == "W"
    assert board.get(3, 3).letter == "N"
    assert board.is_active_index(2 * 5 + 3)


def test_format_board_grid_compact_bat_3x4():
    board = parse_board_from_run_state(_bat_3x4_run_state())
    assert board is not None
    grid = format_board_grid(board, compact=True)
    lines = grid.split("\n")
    assert lines[0] == "Playable 3×4:"
    assert len(lines) == 4
    assert lines[1] == "A E T W"
    assert lines[2] == "R H E N"
    assert lines[3] == "O O T T"
    full = format_board_grid(board, compact=False)
    assert full.count("\n") == 4


def test_load_run_state_raw_with_utf8_bom(tmp_path):
    path = tmp_path / "run_state.json"
    body = json.dumps(
        {
            "character": "Test",
            "money": 0,
            "stickers": [],
            "stamps": [],
            "board": SAMPLE_BOARD_JSON["board"],
        }
    )
    path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    from cursed_words_solver.loadout import load_run_state_raw

    data = load_run_state_raw(path)
    assert data is not None
    assert parse_board_from_run_state(data) is not None


def test_parse_run_state_wolf_boss_max_length():
    data = {
        "character": "Nina Nix",
        "boss_id": "wolf",
        "boss_name": "Wolf",
        "extras": {"boss_area_number": 5},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    assert loadout.boss_id == "wolf"
    assert loadout.boss_name == "Wolf"
    rules = load_rules_catalog()
    constraints = boss_word_constraints(loadout, rules, default_max_len=15)
    assert constraints.max_len == 4


def test_parse_run_state_bosssmallwords_alias_is_wolf():
    """In-game Wolf uses MaxWordLength / BossSmallWords / 'Five Letter Maximum'."""
    data = {
        "character": "Nina Nix",
        "boss_id": "bosssmallwords",
        "boss_name": "Five Letter Maximum",
        "extras": {"boss_area_number": 3},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    rules = load_rules_catalog()
    from cursed_words_solver.rules.rule_lookup import resolve_rule_id

    assert resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name) == "wolf"
    assert boss_word_constraints(loadout, rules, default_max_len=15).max_len == 4


def test_parse_run_state_bossdino_alias_is_cretaceous_meg():
    """In-game Cretaceous Meg prefab slug is bossdino; no per-word scoring rules."""
    data = {
        "character": "Nina Nix",
        "boss_id": "bossdino",
        "boss_name": "Cretaceous Meg",
        "extras": {"boss_area_number": "5"},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    rules = load_rules_catalog()
    from cursed_words_solver.rules.rule_lookup import (
        collect_unmapped_items,
        resolve_rule_id,
    )

    assert (
        resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name)
        == "cretaceous_meg"
    )
    assert collect_unmapped_items(rules, loadout) == []
    constraints = boss_word_constraints(loadout, rules, default_max_len=15)
    assert constraints.max_len == 15
    assert constraints.min_len == 3


def test_parse_run_state_nested_boss_object():
    data = {
        "character": "Test",
        "boss": {"id": "wolf", "name": "Wolf"},
        "extras": {"boss_area_number": "5"},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    assert loadout.boss_id == "wolf"
    assert loadout.boss_name == "Wolf"
    rules = load_rules_catalog()
    assert boss_word_constraints(loadout, rules, default_max_len=15).max_len == 4
