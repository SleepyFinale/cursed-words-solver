"""Tests for immutable SolveContext precompute."""

from __future__ import annotations

from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import shield_blue_base_from_loadout
from cursed_words_solver.rules.scoring_order import hourglass_reverses_order
from cursed_words_solver.rules.stamp_behaviors import (
    loadout_has_stamp,
    stamp_search_flags,
)
from cursed_words_solver.solve_context import build_solve_context


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
    assert ctx.search_flags == stamp_search_flags(loadout)
    assert ctx.compound_percents == (150, 200)
    assert ctx.compound_finalize_at_cocktail is True
    assert ctx.microscope_base == loadout_has_stamp(loadout, "microscope")
    assert ctx.hanafuda_level == 3
