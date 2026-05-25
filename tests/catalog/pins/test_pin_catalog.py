"""All 11 pins catalogued with left/right tracks."""

import json
from pathlib import Path

import pytest

from cursed_words_solver.rules.rule_lookup import (
    get_pin_branch_rule,
    get_pin_scoring_rule,
    pin_has_word_scoring,
)

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data" / "wiki" / "stickers.json"

EXPECTED_PINS = frozenset(
    {
        "abacus",
        "milky_way",
        "rainbow",
        "sam_gambit",
        "bones_the_dog",
        "bucket",
        "random_access_memory",
        "rodman",
        "mahjong_red_dragon",
        "cretaceous_meg",
        "human_boy",
    }
)


@pytest.fixture(scope="module")
def pins() -> dict:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return data["pins"]


def test_all_eleven_pins_present(pins):
    assert set(pins.keys()) == EXPECTED_PINS


@pytest.mark.parametrize(
    "slug,game_class,has_right,has_left",
    [
        ("abacus", "Abacus", True, True),
        ("milky_way", "MilkyWay", False, True),
        ("rainbow", "Rainbow", True, True),
        ("sam_gambit", "SuperEight", True, True),
        ("bones_the_dog", "Bicycle", True, True),
        ("bucket", "Bucket", False, True),
        ("random_access_memory", "RandomAccessMemory", False, False),
        ("rodman", "CarpStreamers", False, True),
        ("mahjong_red_dragon", "MahjongRedDragon", True, True),
        ("cretaceous_meg", "WadOfCash", True, True),
        ("human_boy", "HumanHands", False, False),
    ],
)
def test_pin_game_class_and_tracks(pins, slug, game_class, has_right, has_left):
    entry = pins[slug]
    assert entry.get("game_class") == game_class
    if has_left:
        left = get_pin_branch_rule({"pins": pins}, slug, "left")
        assert left is not None
        assert left.get("type", "").startswith("scatter_")
    if has_right:
        right = get_pin_scoring_rule({"pins": pins}, slug)
        assert right is not None
    if slug in ("random_access_memory", "human_boy"):
        assert pin_has_word_scoring(entry)


def test_super_8_uses_pin_right_variable():
    from cursed_words_solver.models import Board, Loadout
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from cursed_words_solver.rules.scoring_conditions import super_8_take_word_bonus

    rule = get_pin_scoring_rule(
        json.loads(CATALOG.read_text(encoding="utf-8")), "sam_gambit"
    )
    lo = Loadout(extras={"pin_right_variable": 24, "pin_right_level": "1"})
    assert super_8_take_word_bonus(lo, rule) == 24
