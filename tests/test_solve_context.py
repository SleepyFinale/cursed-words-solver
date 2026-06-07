"""Tests for immutable SolveContext precompute."""

from __future__ import annotations

from unittest.mock import patch

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.rules.boss_effects import (
    boss_context,
    get_active_boss_rule,
    get_active_boss_rules,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import shield_blue_base_from_loadout
from cursed_words_solver.rules.scoring_order import _inventory_item_refs, capybara_shuffles_loadout
from cursed_words_solver.rules.scoring_order import hourglass_reverses_order
from cursed_words_solver.rules.stamp_behaviors import (
    loadout_has_stamp,
    mask_from_flags,
    stamp_search_flags,
    stamp_search_flags_mask,
)
from cursed_words_solver.search import WordSearcher
from cursed_words_solver.solve_context import build_solve_context
from tests.helpers.boards import _board_cat_horizontal, _make_wordlist


def test_build_solve_context_matches_individual_lookups():
    loadout = Loadout(
        stamps=[LoadoutItem(id="hourglass", name="Hourglass", level=1, kind="stamp")],
        stickers=[
            LoadoutItem(id="shield", name="Shield", level=2, kind="sticker"),
            LoadoutItem(id="hanafuda", name="Hanafuda", level=3, kind="sticker"),
        ],
        extras={
            "compound_word_percents_on_tile_sum": "150,200",
            "compound_word_finalize_at_cocktail": "true",
        },
    )
    rules = ScoringPipeline().rules
    ctx = build_solve_context(loadout, rules)
    assert ctx.hourglass_reversed == hourglass_reverses_order(loadout, rules)
    assert ctx.shield_blue_base == shield_blue_base_from_loadout(loadout, rules)
    assert ctx.search_flags == stamp_search_flags_mask(loadout)
    assert ctx.search_flags == mask_from_flags(stamp_search_flags(loadout))
    assert ctx.compound_percents == (150, 200)
    assert ctx.compound_finalize_at_cocktail is True
    assert ctx.microscope_base == loadout_has_stamp(loadout, "microscope")
    assert ctx.hanafuda_level == 3
    boss_key, boss_rule = get_active_boss_rule(rules, loadout)
    assert ctx.active_boss_id == (boss_key or loadout.boss_id or "")
    expected_rules = tuple(get_active_boss_rules(rules, loadout))
    if not expected_rules:
        expected_rules = (
            ((boss_key or "", boss_rule),) if boss_rule is not None else ()
        )
    assert ctx.active_boss_rules == expected_rules
    assert ctx.boss_ctx == boss_context(loadout, rules)
    assert ctx.inventory_refs == tuple(_inventory_item_refs(loadout, rules))
    assert ctx.capybara_shuffles == capybara_shuffles_loadout(loadout, rules)


def test_solve_context_precompute_called_once_per_find_best_words(tmp_path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[LoadoutItem(id="bone", name="Bone", level=1, kind="sticker")]
    )
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=6,
        time_budget=1.0,
        search_workers=1,
    )
    with (
        patch(
            "cursed_words_solver.solve_context.stamp_search_flags_mask",
            wraps=stamp_search_flags_mask,
        ) as mock_flags,
        patch(
            "cursed_words_solver.solve_context.hourglass_reverses_order",
            wraps=hourglass_reverses_order,
        ) as mock_hourglass,
        patch(
            "cursed_words_solver.solve_context.shield_blue_base_from_loadout",
            wraps=shield_blue_base_from_loadout,
        ) as mock_shield,
    ):
        results = searcher.find_best_words(board, loadout, top_n=1)
    assert results
    assert mock_flags.call_count == 1
    assert mock_hourglass.call_count == 1
    assert mock_shield.call_count == 1
