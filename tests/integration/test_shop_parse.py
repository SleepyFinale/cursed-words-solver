"""Parse shop blocks from run_state.json."""

from __future__ import annotations

from cursed_words_solver.loadout import (
    encounter_mode_from_run_state,
    parse_encounter_grid_reroll,
    parse_encounter_reroll,
    parse_inventory_sell,
    parse_shop_from_run_state,
)


def test_parse_shop_offers():
    data = {
        "shop": {
            "restock_cost": 3,
            "free_item_available": True,
            "offers": [
                {
                    "slot": "sticker",
                    "index": 0,
                    "id": "blueberries",
                    "name": "Blueberries",
                    "level": 2,
                    "price": 6,
                    "frozen": False,
                },
                {
                    "slot": "tile",
                    "index": 0,
                    "color": "blue",
                    "letter": "T",
                    "price": 3,
                },
            ],
        },
        "inventory_sell": [
            {
                "kind": "sticker",
                "slot": 1,
                "id": "mystery_gift",
                "name": "Mystery Gift",
                "sell_value": 2,
            }
        ],
        "encounter_grid_reroll": {
            "remaining": 2,
            "cost_per_use": 1,
            "can_reroll": True,
            "wheel_equipped": True,
            "fan_equipped": False,
        },
        "extras": {
            "encounter_mode": "encounter",
            "encounter_remaining_target": "48",
            "encounter_total_target": "96",
        },
    }
    shop = parse_shop_from_run_state(data)
    assert shop is not None
    assert shop.restock_cost == 3
    assert len(shop.offers) == 2
    assert shop.offers[0].id == "blueberries"
    assert shop.offers[1].slot == "tile"

    sells = parse_inventory_sell(data)
    assert len(sells) == 1
    assert sells[0].sell_value == 2

    reroll = parse_encounter_grid_reroll(data)
    assert reroll is not None
    assert reroll.remaining == 2
    assert reroll.cost_per_use == 1
    assert reroll.can_reroll is True
    assert encounter_mode_from_run_state(data) == "shop"


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


def test_parse_legacy_encounter_reroll_key():
    data = {
        "encounter_reroll": {
            "remaining": 1,
            "cost": 0,
            "available": True,
            "wheel_equipped": False,
        }
    }
    reroll = parse_encounter_reroll(data)
    assert reroll is not None
    assert reroll.remaining == 1
    assert reroll.cost_per_use == 0
    assert reroll.can_reroll is True
