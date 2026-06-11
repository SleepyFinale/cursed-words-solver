"""Parse melmod quest fields from run_state.json."""

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state


def _blank_tile(row: int, col: int) -> dict:
    return {
        "row": row,
        "col": col,
        "letter": "a",
        "char_display": "a",
        "color": "colorless",
        "curse": "letter",
        "active": True,
    }


def test_parse_challenge_and_tile_flags() -> None:
    tiles = [_blank_tile(r, c) for r in range(5) for c in range(5)]
    tiles[0]["is_crossed_out"] = True
    tiles[12]["letter"] = "5"
    tiles[12]["char_display"] = "5"
    tiles[12]["curse"] = "number"
    tiles[12]["number_value"] = 10
    tiles[12]["is_up_and_up_center"] = True
    data = {
        "character": "Test",
        "money": 10,
        "challenge_game_class": "SicilianDefense",
        "challenge_name": "Knight Time",
        "challenge_elite": False,
        "stickers": [
            {"id": "fav", "name": "Fav", "level": 1, "is_human_boy_favourite": True}
        ],
        "stamps": [],
        "extras": {
            "favourite_sticker_ids": "fav",
            "up_and_up_center_index": "12",
        },
        "board": {
            "rows": 5,
            "cols": 5,
            "row_order": "top_first",
            "tiles": tiles,
        },
    }
    loadout = parse_run_state(data)
    assert loadout.extras["challenge_game_class"] == "SicilianDefense"
    assert loadout.extras["challenge_name"] == "Knight Time"
    assert loadout.extras["favourite_sticker_ids"] == "fav"
    board = parse_board_from_run_state(data)
    assert board is not None
    assert board.get_by_index(0).metadata.get("is_crossed_out")
    assert board.get_by_index(12).metadata.get("is_up_and_up_center")


def test_parse_challenge_from_export_diagnostics_fingerprint() -> None:
    data = {
        "character": "Bones The Dog",
        "money": 2,
        "stickers": [],
        "stamps": [],
        "extras": {},
        "export_diagnostics": {
            "fingerprint": "Bones The Dog|2|||-|SupplyAndDemand|bicycle:left|22",
        },
        "board": {
            "rows": 5,
            "cols": 5,
            "row_order": "top_first",
            "tiles": [
                {
                    "row": r,
                    "col": c,
                    "letter": "A",
                    "char": "a",
                    "color": "colorless",
                    "curse": "letter",
                    "active": True,
                }
                for r in range(5)
                for c in range(5)
            ],
        },
    }
    loadout = parse_run_state(data)
    assert loadout.extras["challenge_game_class"] == "SupplyAndDemand"
