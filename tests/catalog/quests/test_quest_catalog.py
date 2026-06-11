"""Catalog coverage for ChallengeRun quest subclasses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_TAXONOMY = _ROOT / "data" / "game" / "quest_taxonomy.json"
_WIKI = _ROOT / "data" / "wiki" / "quests.json"


def _taxonomy_classes() -> set[str]:
    data = json.loads(_TAXONOMY.read_text(encoding="utf-8"))
    return {
        row["game_class"]
        for row in data.get("quests", {}).values()
        if isinstance(row, dict) and row.get("game_class")
    }


def _wiki_classes() -> set[str]:
    data = json.loads(_WIKI.read_text(encoding="utf-8"))
    return {
        row["game_class"]
        for row in data.get("quests", {}).values()
        if isinstance(row, dict) and row.get("game_class")
    }


def test_twenty_six_challenge_run_subclasses() -> None:
    assert len(_taxonomy_classes()) == 26


def test_wiki_catalog_matches_taxonomy() -> None:
    assert _wiki_classes() == _taxonomy_classes()


@pytest.mark.parametrize("game_class", sorted(_taxonomy_classes()))
def test_each_quest_has_wiki_entry(game_class: str) -> None:
    data = json.loads(_WIKI.read_text(encoding="utf-8"))
    matches = [
        row
        for row in data.get("quests", {}).values()
        if isinstance(row, dict) and row.get("game_class") == game_class
    ]
    assert len(matches) == 1, game_class
    row = matches[0]
    assert row.get("wiki_name")
    assert row.get("effect_class")
