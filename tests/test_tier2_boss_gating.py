"""Tier-2 screening with boss loadouts."""

from __future__ import annotations

from cursed_words_solver.fast_rank import loadout_allows_tier2_screen
from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.solve_context import build_solve_context


def test_hyena_boss_allows_tier2_screen() -> None:
    rules = ScoringPipeline().rules
    loadout = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=1, kind="sticker")],
        boss_id="hyena",
        boss_name="ForcedSell",
    )
    ctx = build_solve_context(loadout, rules)
    assert ctx.tier2_screen_enabled
    assert loadout_allows_tier2_screen(ctx, loadout)


def test_cobra_boss_allows_tier2_screen() -> None:
    rules = ScoringPipeline().rules
    loadout = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=1, kind="sticker")],
        boss_id="cobra",
        boss_name="Cobra",
    )
    ctx = build_solve_context(loadout, rules)
    assert ctx.tier2_screen_enabled
    assert loadout_allows_tier2_screen(ctx, loadout)
