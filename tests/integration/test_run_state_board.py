"""Tests for melmod board export ingestion."""

import json

from cursed_words_solver.loadout import (
    merge_loadout_with_board,
    mod_money_from_run_state,
    parse_board_from_run_state,
    parse_run_state,
)
from cursed_words_solver.rules.boss_effects import boss_word_constraints, load_rules_catalog
from cursed_words_solver.models import CurseType, TileColor, normalize_tile_glyph
from cursed_words_solver.board_display import format_board_grid

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


def _currency_font_wrap_run_state() -> dict:
    """Melmod exports currency with Unity <font> tags around the symbol."""
    tiles = [
        {
            "row": r,
            "col": c,
            "char": "A",
            "letter": "A",
            "curse": "letter",
            "color": "colorless",
            "base_score": 1,
        }
        for r in range(5)
        for c in range(5)
    ]
    for t in tiles:
        if t["row"] == 1 and t["col"] == 2:
            t["char"] = "<font=InterBold SDF>₦</font>"
            t["letter"] = "<font=InterBold SDF>₦</font>"
            t["curse"] = "currency"
            t["base_score"] = 0
    return {"board": {"source": "melmod", "row_order": "top_first", "tiles": tiles}}


def test_normalize_tile_glyph_strips_font_tags():
    wrapped = "<font=InterBold SDF>₦</font>"
    assert normalize_tile_glyph(wrapped) == "₦"


def test_currency_font_wrap_resolves_to_letter_n():
    board = parse_board_from_run_state(_currency_font_wrap_run_state())
    assert board is not None
    tile = board.get(1, 2)
    assert tile is not None
    assert tile.curse == CurseType.CURRENCY
    assert tile.char == "₦"
    assert tile.letter == "N"
    grid = format_board_grid(board)
    assert "<" not in grid
    assert "₦" in grid


def _bat_4x3_run_state() -> dict:
    """Bat shrunk grid: game 4×3 (4 wide, 3 tall); rows 2–4 in 5×5 storage."""
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
            "playable_origin": "bottom_left",
            "playable_min_row": 2,
            "playable_max_row": 4,
            "playable_min_col": 0,
            "playable_max_col": 3,
            "tiles": tiles,
        }
    }


# Backward-compatible alias for imports in other tests
_bat_3x4_run_state = _bat_4x3_run_state


def test_parse_board_bat_4x3_from_run_state():
    board = parse_board_from_run_state(_bat_4x3_run_state())
    assert board is not None
    assert board.rows == 3
    assert board.cols == 4
    assert sum(board.active) == 12
    assert board.get(2, 3).letter == "W"
    assert board.get(3, 3).letter == "N"
    assert board.is_active_index(2 * 5 + 3)


def test_format_board_grid_compact_bat_4x3():
    board = parse_board_from_run_state(_bat_4x3_run_state())
    assert board is not None
    grid = format_board_grid(board, compact=True)
    lines = grid.split("\n")
    assert lines[0] == "Playable 4×3:"
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


def test_parse_run_state_bosscactus_alias_is_sandy_saguaro():
    data = {
        "character": "Cretaceous Meg",
        "boss_id": "bosscactus",
        "boss_name": "Sandy Saguaro",
        "extras": {"boss_area_number": 3},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    rules = load_rules_catalog()
    from cursed_words_solver.rules.rule_lookup import (
        boss_display_name,
        collect_unmapped_items,
        resolve_rule_id,
    )

    assert (
        resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name)
        == "sandy_saguaro"
    )
    assert collect_unmapped_items(rules, loadout) == []
    assert boss_display_name(loadout, rules) == "Sandy Saguaro"


def test_parse_run_state_bossqs_alias_is_axolotl():
    """In-game Axolotl prefab/display name is Extra Qs / bossqs."""
    data = {
        "character": "Sam Gambit",
        "boss_id": "bossqs",
        "boss_name": "Extra Qs",
        "extras": {"boss_area_number": 3},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    rules = load_rules_catalog()
    from cursed_words_solver.rules.rule_lookup import (
        boss_display_name,
        collect_unmapped_items,
        resolve_rule_id,
    )

    assert (
        resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name)
        == "axolotl"
    )
    assert collect_unmapped_items(rules, loadout) == []
    assert boss_display_name(loadout, rules) == "Axolotl"


def test_parse_run_state_bossvoids_alias_is_mole():
    """In-game Mole prefab/display name is Extra Voids / bossvoids."""
    data = {
        "character": "Nina Nix",
        "boss_id": "bossvoids",
        "boss_name": "Extra Voids",
        "extras": {"boss_area_number": 1},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    rules = load_rules_catalog()
    from cursed_words_solver.rules.rule_lookup import (
        boss_display_name,
        collect_unmapped_items,
        resolve_rule_id,
    )

    assert (
        resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name)
        == "mole"
    )
    assert collect_unmapped_items(rules, loadout) == []
    assert boss_display_name(loadout, rules) == "Mole"


def test_parse_run_state_toothed_whale_misexport_resolves_via_boss_name():
    """StealsMoney runtime was wrongly mapped to toothed_whale; Fox display name wins."""
    data = {
        "character": "Nina Nix",
        "boss_id": "toothed_whale",
        "boss_name": "Fox",
        "extras": {"boss_area_number": 3},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    rules = load_rules_catalog()
    from cursed_words_solver.rules.rule_lookup import (
        boss_display_name,
        collect_unmapped_items,
        resolve_rule_id,
    )

    assert (
        resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name)
        == "fox"
    )
    assert collect_unmapped_items(rules, loadout) == []
    assert boss_display_name(loadout, rules) == "Fox"


def test_parse_run_state_bossmoney_alias_is_fox():
    """In-game Fox prefab slug is bossmoney (StealsMoney modifier)."""
    data = {
        "character": "Nina Nix",
        "boss_id": "bossmoney",
        "boss_name": "Fox",
        "extras": {"boss_area_number": 3},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    rules = load_rules_catalog()
    from cursed_words_solver.rules.rule_lookup import (
        boss_display_name,
        collect_unmapped_items,
        resolve_rule_id,
    )

    assert (
        resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name)
        == "fox"
    )
    assert collect_unmapped_items(rules, loadout) == []
    assert boss_display_name(loadout, rules) == "Fox"


def test_parse_run_state_bigboss_alias_is_toothed_whale():
    """In-game Toothed Whale prefab/display name is BigBoss / bigboss."""
    data = {
        "character": "Hayley Bayles",
        "boss_id": "bigboss",
        "boss_name": "BigBoss",
        "extras": {"boss_area_number": 4},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    rules = load_rules_catalog()
    from cursed_words_solver.rules.rule_lookup import (
        boss_display_name,
        collect_unmapped_items,
        resolve_rule_id,
    )

    assert (
        resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name)
        == "toothed_whale"
    )
    assert collect_unmapped_items(rules, loadout) == []
    assert boss_display_name(loadout, rules) == "Toothed Whale"


def test_parse_run_state_bossaddnumbers_alias_is_bison():
    """In-game Bison prefab/runtime name is AddNumbers / bossaddnumbers."""
    data = {
        "character": "Nina Nix",
        "boss_id": "bossaddnumbers",
        "boss_name": "AddNumbers",
        "extras": {"boss_area_number": 3},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    rules = load_rules_catalog()
    from cursed_words_solver.rules.rule_lookup import (
        boss_display_name,
        collect_unmapped_items,
        resolve_rule_id,
    )

    assert (
        resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name)
        == "bison"
    )
    assert collect_unmapped_items(rules, loadout) == []
    assert boss_display_name(loadout, rules) == "Bison"


def test_parse_run_state_bosssell_alias_is_hyena():
    """In-game Hyena prefab/runtime name is ForcedSell / bosssell."""
    data = {
        "character": "Nina Nix",
        "boss_id": "bosssell",
        "boss_name": "ForcedSell",
        "extras": {"boss_area_number": 5},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    rules = load_rules_catalog()
    from cursed_words_solver.rules.rule_lookup import (
        boss_display_name,
        collect_unmapped_items,
        resolve_rule_id,
    )

    assert (
        resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name)
        == "hyena"
    )
    assert collect_unmapped_items(rules, loadout) == []
    assert boss_display_name(loadout, rules) == "Hyena"


def test_parse_run_state_bosssmallgrid_alias_is_bat():
    """In-game Bat prefab/display name is 4x4 Grid / bosssmallgrid."""
    data = {
        "character": "Nina Nix",
        "boss_id": "bosssmallgrid",
        "boss_name": "4x4 Grid",
        "extras": {"boss_area_number": 4},
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
        == "bat"
    )
    assert collect_unmapped_items(rules, loadout) == []
    from cursed_words_solver.rules.rule_lookup import boss_display_name

    assert boss_display_name(loadout, rules) == "Bat"


def test_parse_run_state_bossneutralise_alias_is_yeti_crab():
    """In-game Yeti Crab prefab/display name is DiscolourTiles / bossneutralise."""
    data = {
        "character": "Nina Nix",
        "boss_id": "bossneutralise",
        "boss_name": "DiscolourTiles",
        "extras": {"boss_area_number": 3},
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
        == "yeti_crab"
    )
    assert collect_unmapped_items(rules, loadout) == []


def test_parse_run_state_bosseats_alias_is_robo_eel():
    """In-game Robo-Eel prefab/display name is DestroyGrid / bosseats."""
    data = {
        "character": "Nina Nix",
        "boss_id": "bosseats",
        "boss_name": "DestroyGrid",
        "extras": {"boss_area_number": 2},
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
        == "robo_eel"
    )
    assert collect_unmapped_items(rules, loadout) == []


def test_parse_run_state_bossfewergrids_alias_is_badger():
    """In-game Badger prefab/display name is FewerGrids / bossfewergrids."""
    data = {
        "character": "Nina Nix",
        "boss_id": "bossfewergrids",
        "boss_name": "FewerGrids",
        "extras": {"boss_area_number": 1},
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
        == "badger"
    )
    assert collect_unmapped_items(rules, loadout) == []


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


def test_parse_run_state_bosshumanboy_alias_is_human_boy_boss():
    """In-game Human Boy prefab slug is bosshumanboy; meta boss (item steal on grid 1)."""
    data = {
        "character": "Human Boy",
        "boss_id": "bosshumanboy",
        "boss_name": "Human Boy",
        "extras": {"boss_area_number": "4"},
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    rules = load_rules_catalog()
    from cursed_words_solver.rules.rule_lookup import (
        boss_display_name,
        collect_unmapped_items,
        resolve_rule_id,
    )

    assert (
        resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name)
        == "human_boy_boss"
    )
    assert collect_unmapped_items(rules, loadout) == []
    assert boss_display_name(loadout, rules) == "Human Boy"


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


def test_parse_run_state_grid_number_and_kokeshi():
    from cursed_words_solver.rules.scoring_conditions import grid_number

    data = {
        "character": "Cretaceous Meg",
        "extras": {
            "grid_number": "3",
            "kokeshi_dolls": "true",
            "board_from_melmod": "true",
            "character_slug": "cretaceous_meg",
            "fairy_count": "2",
            "rare_item_count": "1",
        },
        "stickers": [],
        "stamps": [{"id": "kokeshi_dolls", "name": "Kokeshi Dolls"}],
    }
    loadout = parse_run_state(data)
    assert grid_number(loadout) == 3
    assert loadout.extras["kokeshi_dolls"] is True
    assert loadout.extras["board_from_melmod"] is True
    assert loadout.extras["character_slug"] == "cretaceous_meg"
    assert loadout.extras["fairy_count"] == 2
    assert loadout.extras["rare_item_count"] == 1


def test_parse_run_state_stitched_and_overhand_json():
    data = {
        "character": "Test",
        "extras": {
            "stitched_sticker_ids": '["brain","tombstone"]',
            "overhand_level": "2",
            "frozen_in_shop": "true",
        },
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    assert loadout.extras["stitched_sticker_ids"] == ["brain", "tombstone"]
    assert loadout.extras["overhand_level"] == 2
    assert loadout.extras["frozen_in_shop"] is True


def test_parse_board_tile_extras_metadata():
    data = {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "tiles": [
                {
                    "row": 0,
                    "col": 0,
                    "char": "A",
                    "letter": "A",
                    "curse": "arrow",
                    "color": "colorless",
                    "base_score": 1,
                    "consumable": True,
                    "was_glitch": True,
                    "cactus_growth": 2,
                },
                *[
                    {
                        "row": r,
                        "col": c,
                        "char": "X",
                        "letter": "X",
                        "curse": "letter",
                        "color": "colorless",
                        "base_score": 1,
                    }
                    for r in range(5)
                    for c in range(5)
                    if not (r == 0 and c == 0)
                ],
            ],
        }
    }
    board = parse_board_from_run_state(data)
    assert board is not None
    tile = board.get(0, 0)
    assert tile.curse == CurseType.ARROW
    assert tile.metadata.get("consumable") is True
    assert tile.metadata.get("was_glitch") is True
    assert tile.metadata.get("cactus_growth") == 2


def test_parse_board_was_consumable_metadata():
    data = {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "tiles": [
                {
                    "row": 1,
                    "col": 2,
                    "char": "e",
                    "letter": "E",
                    "curse": "letter",
                    "color": "blue",
                    "base_score": 2,
                    "was_consumable": True,
                },
                *[
                    {
                        "row": r,
                        "col": c,
                        "char": "X",
                        "letter": "X",
                        "curse": "letter",
                        "color": "colorless",
                        "base_score": 1,
                    }
                    for r in range(5)
                    for c in range(5)
                    if not (r == 1 and c == 2)
                ],
            ],
        }
    }
    board = parse_board_from_run_state(data)
    assert board is not None
    tile = board.get(1, 2)
    assert tile.metadata.get("was_consumable") is True


def test_effective_board_skips_cactus_growth_on_melmod_and_consumables():
    from cursed_words_solver.encounter_board import effective_board_for_loadout
    from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    def _blank(row: int, col: int) -> Tile:
        return Tile(
            row=row,
            col=col,
            char="X",
            letter="X",
            base_score=1,
            color=TileColor.COLORLESS,
            curse=CurseType.LETTER,
            metadata={"source": "melmod"},
        )

    def _cactus(row: int, col: int, *, growth: int, was_consumable: bool = False) -> Tile:
        meta: dict = {"source": "melmod", "cactus_growth": growth}
        if was_consumable:
            meta["was_consumable"] = True
        return Tile(
            row=row,
            col=col,
            char="A",
            letter="A",
            base_score=float(1 + growth),
            color=TileColor.CACTUS,
            curse=CurseType.LETTER,
            metadata=meta,
        )

    tiles = [[_blank(r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _cactus(0, 0, growth=2)
    tiles[1][1] = _cactus(1, 1, growth=0, was_consumable=True)
    board = Board(tiles=tiles)
    loadout = Loadout(extras={"board_from_melmod": "true"})
    rules = ScoringPipeline().rules
    out = effective_board_for_loadout(board, loadout, rules)
    assert out.get(0, 0).metadata.get("cactus_growth") == 2
    assert out.get(1, 1).metadata.get("cactus_growth") == 0


def test_merge_submit_board_tile_state_includes_consumable_fields():
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        prepare_run_state_dict_for_scoring,
    )

    data = {
        "run_state_snapshot": {
            "board": {
                "source": "melmod",
                "row_order": "top_first",
                "tiles": [
                    {
                        "row": 2,
                        "col": 1,
                        "char": "?",
                        "letter": "?",
                        "curse": "wildcard",
                        "color": "void",
                        "base_score": 0,
                    },
                    *[
                        {
                            "row": r,
                            "col": c,
                            "char": "X",
                            "letter": "X",
                            "curse": "letter",
                            "color": "colorless",
                            "base_score": 1,
                        }
                        for r in range(5)
                        for c in range(5)
                        if not (r == 2 and c == 1)
                    ],
                ],
            }
        },
        "submit_board_tiles": [
            {
                "row": 2,
                "col": 1,
                "char": "l",
                "letter": "L",
                "curse": "letter",
                "color": "cactus",
                "base_score": 1.0,
                "was_consumable": True,
                "cactus_growth": 0,
            }
        ],
    }
    merged = prepare_run_state_dict_for_scoring(
        {**data["run_state_snapshot"], **data}
    )
    board = parse_board_from_run_state(merged)
    assert board is not None
    tile = board.get(2, 1)
    assert tile.letter == "L"
    assert tile.color.value == "cactus"
    assert tile.base_score == 1.0
    assert tile.metadata.get("was_consumable") is True
    assert tile.metadata.get("cactus_growth") == 0


def test_parse_run_state_schema_version_passthrough():
    data = {
        "schema_version": 1,
        "exported_at": "2026-05-25T00:00:00Z",
        "character": "Test",
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    assert loadout.character == "Test"
