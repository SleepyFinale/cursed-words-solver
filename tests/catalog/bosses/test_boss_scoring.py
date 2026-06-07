"""Boss submit-time scoring."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.boss_scoring import apply_boss_steal_money
from cursed_words_solver.rules.boss_effects import boss_context, load_rules_catalog
from cursed_words_solver.rules.pipeline import ScoringPipeline, _finalize, _init_state
from cursed_words_solver.rules.scoring_order import (
    build_scoring_item_sequence,
    capybara_shuffles_loadout,
)
from cursed_words_solver.rules.capybara_scoring import (
    CapybaraScope,
    iter_capybara_loadout_permutations,
)


def _tile(letter: str = "A") -> Tile:
    return Tile(0, 0, letter, letter, 2, TileColor.COLORLESS, CurseType.LETTER)


def _board() -> Board:
    tiles = [[_tile() if r == 0 and c < 3 else Tile(r, c, "", "", 0, curse=CurseType.ITEM) for c in range(5)] for r in range(5)]
    active = [r * 5 + c < 3 for r in range(5) for c in range(5)]
    return Board(tiles=tiles, money=10, active=active)


def test_fox_steal_money() -> None:
    rules = load_rules_catalog()
    boss = rules["bosses"]["fox"]
    loadout = Loadout(money=10, boss_id="fox", extras={"boss_area_number": 1})
    state = {"money_bonus": 0, "effects": [], "tile_scores": [0.0, 2.0]}
    apply_boss_steal_money(state, loadout, boss, boss_context(loadout, rules))
    assert loadout.money == 8
    assert "stolen" in state["effects"][-1].lower()
    assert state["tile_scores"][0] == 0.0


def test_boss_zero_vowel_finalize_zeros_score() -> None:
    state = {
        "tile_scores": [10.0, 10.0, 10.0],
        "word_score": 5.0,
        "multiplier": 0.0,
        "pending_word_multipliers": [(2.0, "brain")],
        "pending_word_percent_bonuses": [],
    }
    assert _finalize(state) == 0.0


def test_boss_zero_vowel_via_pipeline() -> None:
    board = _board()
    loadout = Loadout()
    pipe = ScoringPipeline()
    state = _init_state(board, [0, 1, 2], "aaa")
    state = pipe._apply_rule(
        {"type": "boss_zero_vowel"},
        state,
        board,
        [0, 1, 2],
        loadout,
        1,
    )
    assert state["multiplier"] == 0
    assert _finalize(state, board, [0, 1, 2]) == 0.0


def test_salamander_still_applies() -> None:
    board = _board()
    loadout = Loadout(boss_id="salamander", extras={"boss_area_number": 1})
    pipe = ScoringPipeline()
    _, bd = pipe.score(board, [0, 1, 2], "aaa", loadout)
    assert any("per tile (boss)" in e for e in bd["pipeline"]["effects"])


def test_boss_modifiers_source_of_truth_can_disable_stale_primary_boss() -> None:
    board = _board()
    # Primary boss id can be stale in capture; explicit empty boss_modifiers means
    # this phase has no copied boss effects.
    loadout = Loadout(
        boss_id="salamander",
        extras={"boss_area_number": 1, "boss_modifiers": []},
    )
    pipe = ScoringPipeline()
    _, bd = pipe.score(board, [0, 1, 2], "aaa", loadout)
    assert not any("per tile (boss)" in e for e in bd["pipeline"]["effects"])


def test_multiple_boss_modifiers_apply_in_single_score() -> None:
    board = _board()
    loadout = Loadout(
        boss_id="badger",
        money=10,
        extras={
            "boss_area_number": 1,
            "boss_modifiers": ["salamander", "robo_monkey"],
        },
    )
    pipe = ScoringPipeline()
    _, bd = pipe.score(board, [0, 1, 2], "aaa", loadout)
    effects = bd["pipeline"]["effects"]
    assert any("per tile (boss)" in e for e in effects)
    assert any("word score (boss × money)" in e for e in effects)


def test_capybara_shuffles_sticker_order() -> None:
    from cursed_words_solver.models import LoadoutItem

    rules = load_rules_catalog()
    loadout = Loadout(
        boss_id="capybara",
        stickers=[
            LoadoutItem("brain", "Brain", 1),
            LoadoutItem("chips", "Chips", 1),
        ],
        extras={"boss_area_number": 1},
    )
    assert capybara_shuffles_loadout(loadout, rules)
    scope = CapybaraScope(True, False)
    orders = {
        tuple(s.id for s in perm.stickers)
        for perm in iter_capybara_loadout_permutations(
            loadout, scope, path=[0, 1, 2], exhaustive=True
        )
    }
    assert len(orders) == 2
