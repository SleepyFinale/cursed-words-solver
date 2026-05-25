"""All 151 wiki stamps catalogued with game_class and audit status."""

import json
from pathlib import Path

import pytest

from cursed_words_solver.rules.rule_lookup import get_rule, is_scoring_rule

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data" / "wiki" / "stickers.json"


@pytest.fixture(scope="module")
def stamps() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))["stamps"]


def test_stamp_count(stamps):
    assert len(stamps) == 151


def test_all_stamps_have_game_class(stamps):
    missing = [slug for slug, r in stamps.items() if not r.get("game_class")]
    assert not missing, f"missing game_class: {missing[:10]}"


@pytest.mark.parametrize(
    "slug,flags",
    [
        ("hungry_snake", {"horizontal_wrap": True}),
        ("full_moon", {"double_letter_teleport": True}),
        ("queenie", {"q_as_qu": True}),
        ("honeypot", {"word_stitch": True}),
    ],
)
def test_movement_stamp_search_flags(stamps, slug, flags):
    rule = stamps[slug]
    sf = rule.get("search_flags") or {}
    for k, v in flags.items():
        assert sf.get(k) is v


def test_hourglass_meta_scoring(stamps):
    rule = stamps["hourglass"]
    assert rule.get("type") == "reverse_scoring_order"
    assert not is_scoring_rule(rule)


def test_shop_only_custom_stamps_not_scoring(stamps):
    shop = [
        slug
        for slug, r in stamps.items()
        if r.get("effect_class") == "shop" and r.get("type") == "custom"
    ]
    assert len(shop) >= 5
    for slug in shop[:5]:
        assert not is_scoring_rule(stamps[slug]), slug
