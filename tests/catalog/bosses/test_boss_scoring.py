"""Boss submit-time scoring."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.boss_scoring import apply_boss_steal_money
from cursed_words_solver.rules.boss_effects import boss_context, load_rules_catalog
from cursed_words_solver.rules.pipeline import ScoringPipeline, _finalize, _init_state
from cursed_words_solver.rules.scoring_order import (
    _maybe_shuffled_loadout,
    build_scoring_item_sequence,
    capybara_shuffles_loadout,
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


def test_capybara_shuffles_sticker_order() -> None:
    from cursed_words_solver.models import LoadoutItem

    rules = load_rules_catalog()
    orders: set[tuple[str, ...]] = set()
    for seed in range(30):
        loadout = Loadout(
            boss_id="capybara",
            stickers=[
                LoadoutItem("brain", "Brain", 1),
                LoadoutItem("chips", "Chips", 1),
            ],
            extras={"boss_area_number": 1, "run_seed": str(seed)},
        )
        assert capybara_shuffles_loadout(loadout, rules)
        shuffled = _maybe_shuffled_loadout(loadout, rules, [0, 1, 2])
        orders.add(tuple(s.id for s in shuffled.stickers))
    assert len(orders) > 1
