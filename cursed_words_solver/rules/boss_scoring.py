"""Submit-time boss effects (ApplyBossModifier parity)."""

from __future__ import annotations



EARLY_BOSS_TYPES = frozenset(
    {
        "boss_tile_penalty",
        "boss_subtract_word_score_money",
        "boss_steal_money",
    }
)


