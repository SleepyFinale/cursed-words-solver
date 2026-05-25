"""Catalog coverage for 16 main bosses."""

from __future__ import annotations

import pytest

from tests.catalog.bosses._coverage import boss_entries


@pytest.mark.parametrize("slug", sorted(boss_entries().keys()))
def test_boss_has_game_class(slug: str) -> None:
    rule = boss_entries()[slug]
    assert rule.get("game_class"), f"{slug} missing game_class"


def test_sixteen_main_bosses() -> None:
    assert len(boss_entries()) == 16
