"""Tier-2 fast rank: conservative lower bounds before full scoring pipeline."""

from __future__ import annotations

from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.base_scoring import tile_base_contribution
from cursed_words_solver.setup_value import _has_setup_mechanics

_PIN_SCORING_KEYS = frozenset(
    {
        "pin_effect",
        "PinEffect",
        "pin_id",
        "pin_level",
    }
)


def loadout_allows_fast_rank(loadout: Loadout, *, setup_weight: float = 0.0) -> bool:
    """True when tile-base sum is a safe lower bound on rank_score (no sticker/pin/boss math)."""
    if loadout.stickers or loadout.stamps:
        return False
    if loadout.boss_effect or loadout.boss_id:
        return False
    extras = loadout.extras or {}
    if str(extras.get("pin_effect", "") or extras.get("PinEffect", "") or "").strip():
        return False
    for key in _PIN_SCORING_KEYS:
        if key in extras and extras[key]:
            return False
    if setup_weight > 0 and _has_setup_mechanics(loadout):
        return False
    return True


def fast_rank_lower_bound(board: Board, path: list[int]) -> float:
    """Sum of per-tile base contributions; never exceeds full pipeline score."""
    total = 0.0
    for idx in path:
        total += tile_base_contribution(board.get_by_index(idx), board.money)
    return total
