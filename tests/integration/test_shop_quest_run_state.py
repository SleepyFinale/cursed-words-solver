"""Parse embargo quest extras from run_state.json."""

from cursed_words_solver.f8_snapshot import shop_extras_ready
from cursed_words_solver.loadout import parse_run_state
from cursed_words_solver.rules.shop_quest_effects import embargoed_game_classes


def test_parse_embargoed_item_types() -> None:
    data = {
        "character": "Test",
        "money": 10,
        "challenge_game_class": "Embargo",
        "extras": {
            "encounter_mode": "shop",
            "challenge_game_class": "Embargo",
            "embargoed_item_types": "Blueberries,Newspaper",
            "embargoed_item_slugs": "blueberries,newspaper",
        },
        "stickers": [],
        "stamps": [],
    }
    loadout = parse_run_state(data)
    classes = embargoed_game_classes(loadout)
    assert "Blueberries" in classes
    assert "Newspaper" in classes


def test_shop_extras_ready_embargo() -> None:
    ready = shop_extras_ready(
        {
            "extras": {"encounter_mode": "shop", "challenge_game_class": "Embargo"},
            "challenge_game_class": "Embargo",
            "stickers": [],
            "stamps": [],
        }
    )
    assert not ready
    ready2 = shop_extras_ready(
        {
            "extras": {
                "encounter_mode": "shop",
                "challenge_game_class": "Embargo",
                "embargoed_item_types": "",
            },
            "challenge_game_class": "Embargo",
            "stickers": [],
            "stamps": [],
        }
    )
    assert ready2
