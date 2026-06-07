"""Capybara permutation EV and score range."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.boss_effects import load_rules_catalog
from cursed_words_solver.rules.capybara_scoring import (
    capybara_active_warning,
    capybara_perm_count,
    capybara_shuffle_scope,
    iter_capybara_loadout_permutations,
    score_capybara_distribution,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_order import capybara_shuffles_loadout


def _tile(letter: str = "A") -> Tile:
    return Tile(0, 0, letter, letter, 2, TileColor.COLORLESS, CurseType.LETTER)


def _board() -> Board:
    tiles = [
        [_tile() if r == 0 and c < 3 else Tile(r, c, "", "", 0, curse=CurseType.ITEM) for c in range(5)]
        for r in range(5)
    ]
    active = [r * 5 + c < 3 for r in range(5) for c in range(5)]
    return Board(tiles=tiles, money=10, active=active)


def test_capybara_scope_normal_boss_stickers_only() -> None:
    rules = load_rules_catalog()
    loadout = Loadout(
        boss_id="capybara",
        stickers=[LoadoutItem("brain", "Brain", 1)],
        stamps=[LoadoutItem("hourglass", "Hourglass", 1)],
        extras={"boss_area_number": 1, "boss_cursed": False},
    )
    scope = capybara_shuffle_scope(loadout, rules)
    assert scope.shuffles_stickers is True
    assert scope.shuffles_stamps is False


def test_capybara_scope_cursed_boss_shuffles_stamps() -> None:
    rules = load_rules_catalog()
    loadout = Loadout(
        boss_id="capybara",
        stickers=[LoadoutItem("brain", "Brain", 1)],
        stamps=[
            LoadoutItem("bento_box", "Bento Box", 1),
            LoadoutItem("newspaper", "Newspaper", 1),
        ],
        extras={"boss_area_number": 1, "boss_cursed": True},
    )
    scope = capybara_shuffle_scope(loadout, rules)
    assert scope.shuffles_stickers is True
    assert scope.shuffles_stamps is True
    assert capybara_perm_count(loadout, scope) == 2


def test_capybara_sticker_only_warning() -> None:
    rules = load_rules_catalog()
    loadout = Loadout(
        stickers=[LoadoutItem("capybara", "Capybara", 1)],
        extras={"capybara_shuffle": "true"},
    )
    warn = capybara_active_warning(loadout, rules)
    assert warn is not None
    assert "sticker order randomized" in warn
    assert "stamp" not in warn


def test_capybara_distribution_min_differs_from_max() -> None:
    rules = load_rules_catalog()
    loadout = Loadout(
        boss_id="capybara",
        stamps=[
            LoadoutItem("bento_box", "Bento Box", 1),
            LoadoutItem("newspaper", "Newspaper", 1),
        ],
        extras={
            "boss_area_number": 1,
            "boss_cursed": True,
            "previous_word_first_letter": "a",
        },
    )
    assert capybara_shuffles_loadout(loadout, rules)
    board = _board()
    path = [0, 1, 2]
    pipe = ScoringPipeline()
    stats = score_capybara_distribution(
        pipe, board, path, "aaa", loadout, rules
    )
    assert stats.min_score != stats.max_score
    assert stats.min_score <= stats.ev <= stats.max_score
    assert stats.ev == (stats.min_score + stats.max_score) / 2
    assert stats.perm_count == 2
    assert stats.exhaustive is True


def test_capybara_permutation_iterator_covers_both_orders() -> None:
    rules = load_rules_catalog()
    loadout = Loadout(
        boss_id="capybara",
        stickers=[
            LoadoutItem("brain", "Brain", 1),
            LoadoutItem("chips", "Chips", 1),
        ],
        extras={"boss_area_number": 1},
    )
    scope = capybara_shuffle_scope(loadout, rules)
    orders = {
        tuple(s.id for s in perm.stickers)
        for perm in iter_capybara_loadout_permutations(
            loadout, scope, path=[0, 1, 2], exhaustive=True
        )
    }
    assert orders == {("brain", "chips"), ("chips", "brain")}
