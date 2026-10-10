"""Catalog coverage for 16 main bosses."""

from __future__ import annotations

import pytest

from tests.catalog.bosses._coverage import boss_entries


@pytest.mark.parametrize("slug", sorted(boss_entries().keys()))
def test_boss_has_game_class(slug: str) -> None:
    rule = boss_entries()[slug]
    assert rule.get("game_class"), f"{slug} missing game_class"


# Hidden / meta bosses documented in docs/game-research/bosses.md.
_HIDDEN_META_BOSSES = frozenset(
    {"sandy_saguaro", "prismatic_bean", "human_boy_boss", "michael"}
)


def test_sixteen_main_bosses() -> None:
    entries = boss_entries()
    assert _HIDDEN_META_BOSSES <= entries.keys()
    assert len(entries.keys() - _HIDDEN_META_BOSSES) == 16
