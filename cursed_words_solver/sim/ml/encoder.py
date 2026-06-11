"""StateEncoder — RunState → feature vector for V and π."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cursed_words_solver.models import TileColor
from cursed_words_solver.sim.state import RunState


_COLOR_INDEX = {c.value: i for i, c in enumerate(TileColor)}


@dataclass
class StateEncoder:
    """Structured summary: stickers, resources, encounter, grid."""

    sticker_slots: int = 16
    include_candidate_stats: bool = False

    def feature_dim(self) -> int:
        base = (
            8  # encounter counters
            + self.sticker_slots
            + 8  # grid summary
            + 4  # boss flags
        )
        if self.include_candidate_stats:
            base += 4
        return base

    def encode(self, state: RunState, *, candidate_stats: dict | None = None) -> np.ndarray:
        extras = state.extras
        vec = np.zeros(self.feature_dim(), dtype=np.float64)

        vec[0] = float(state.encounter_remaining_target)
        vec[1] = float(state.grids_remaining)
        vec[2] = float(state.grid_number)
        vec[3] = float(state.loadout.money)
        vec[4] = float(state.encounter_score_earned)
        vec[5] = 1.0 if state.encounter_won else 0.0
        vec[6] = 1.0 if state.encounter_lost else 0.0
        vec[7] = float(len(state.loadout.stickers))

        offset = 8
        for i, sticker in enumerate(state.loadout.stickers[: self.sticker_slots]):
            vec[offset + i] = float(max(1, sticker.level))
        offset += self.sticker_slots

        color_counts = [0.0] * 6
        base_sum = 0.0
        active = 0
        for tile in state.board.flat:
            if not state.board.is_active_index(tile.index):
                continue
            active += 1
            base_sum += float(tile.base_score)
            ci = _COLOR_INDEX.get(tile.color.value, 0) % 6
            color_counts[ci] += 1.0
        vec[offset] = float(active)
        vec[offset + 1] = base_sum / max(1, active)
        for j, c in enumerate(color_counts[:6]):
            if offset + 2 + j < offset + 8:
                vec[offset + 2 + j] = c

        offset += 8
        vec[offset] = 1.0 if state.loadout.boss_id else 0.0
        try:
            vec[offset + 1] = float(extras.get("birthday_cake_bonus", 0) or 0)
        except (TypeError, ValueError):
            pass
        try:
            vec[offset + 2] = float(extras.get("bicycle_word_score_bonus", 0) or 0)
        except (TypeError, ValueError):
            pass
        try:
            vec[offset + 3] = float(extras.get("neapolitan_percent", 0) or 0)
        except (TypeError, ValueError):
            pass

        if self.include_candidate_stats and candidate_stats:
            base = offset + 4
            if base + 3 < len(vec):
                vec[base] = float(candidate_stats.get("top_score", 0))
                vec[base + 1] = float(candidate_stats.get("score_spread", 0))
                vec[base + 2] = float(candidate_stats.get("pool_size", 0))
                vec[base + 3] = float(candidate_stats.get("setup_delta", 0))

        return vec
