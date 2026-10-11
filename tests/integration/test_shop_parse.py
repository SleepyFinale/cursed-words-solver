"""Parse shop blocks from run_state.json."""

from __future__ import annotations

from cursed_words_solver.loadout import encounter_mode_from_run_state


def test_encounter_mode_shop_when_offers_and_no_board():
    data = {
        "shop": {
            "restock_cost": 2,
            "offers": [
                {
                    "slot": "sticker",
                    "index": 0,
                    "id": "celestial_body",
                    "name": "Celestial Body",
                    "level": 1,
                    "price": 10,
                }
            ],
        },
        "extras": {"encounter_mode": "none"},
    }
    assert encounter_mode_from_run_state(data) == "shop"


def test_encounter_mode_encounter_when_board_present():
    tiles = [
        {
            "row": r,
            "col": c,
            "letter": "A",
            "char_display": "a",
            "color": "colorless",
            "curse": "letter",
            "base_score": 1.0,
        }
        for r in range(5)
        for c in range(5)
    ]
    data = {
        "board": {"tiles": tiles},
        "shop": {
            "restock_cost": 2,
            "offers": [
                {
                    "slot": "sticker",
                    "index": 0,
                    "id": "blueberries",
                    "name": "Blueberries",
                    "level": 1,
                    "price": 6,
                }
            ],
        },
        "extras": {"encounter_mode": "shop"},
    }
    assert encounter_mode_from_run_state(data) == "encounter"
