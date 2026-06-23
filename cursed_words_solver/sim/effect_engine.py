"""EffectEngine — post-submit and grid-start state mutations."""

from __future__ import annotations

import copy
import json
from typing import Any

from cursed_words_solver.encounter_board import effective_board_for_loadout
from cursed_words_solver.rules.scoring_conditions import _effective_word_start_letter
from cursed_words_solver.setup_value import project_setup_delta
from cursed_words_solver.sim.reward_engine import RewardResult
from cursed_words_solver.sim.rng import SimRNG
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


def _first_letter(word: str) -> str:
    for ch in (word or "").strip().lower():
        if ch.isalpha():
            return ch
    return ""


def _load_historic_list(extras: dict[str, Any]) -> list[dict[str, Any]]:
    raw = extras.get("historic_words")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return list(parsed) if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    if isinstance(raw, list):
        return list(raw)
    return []


def _apply_setup_extras(
    state: RunState,
    submission: Submission,
    reward: RewardResult,
    rules: dict,
) -> None:
    """Post-submit accumulator extras (Birthday Cake, Bicycle, rack bonuses, …)."""
    delta = project_setup_delta(
        state.board,
        submission.path,
        submission.effective_scoring_word,
        state.loadout,
        rules=rules,
    )
    extras = state.extras
    if delta.birthday_cake_bonus:
        try:
            cur = int(extras.get("birthday_cake_bonus", 0) or 0)
        except (TypeError, ValueError):
            cur = 0
        extras["birthday_cake_bonus"] = str(cur + int(delta.birthday_cake_bonus))

    if delta.bicycle_word_score_bonus:
        try:
            cur = int(extras.get("bicycle_word_score_bonus", 0) or 0)
        except (TypeError, ValueError):
            cur = 0
        extras["bicycle_word_score_bonus"] = str(cur + int(delta.bicycle_word_score_bonus))

    if delta.consumable_rack_count:
        try:
            cur = int(extras.get("consumable_rack_count", 0) or 0)
        except (TypeError, ValueError):
            cur = 0
        extras["consumable_rack_count"] = str(cur + int(delta.consumable_rack_count))

    if delta.red_tiles_used_encounter:
        try:
            cur = int(extras.get("red_tiles_used_encounter", 0) or 0)
        except (TypeError, ValueError):
            cur = 0
        extras["red_tiles_used_encounter"] = str(cur + int(delta.red_tiles_used_encounter))

    if delta.tile_ninja_bonus:
        try:
            cur = float(extras.get("tile_ninja_bonus", 0) or 0)
        except (TypeError, ValueError):
            cur = 0.0
        extras["tile_ninja_bonus"] = str(cur + float(delta.tile_ninja_bonus))


def _count_red_tiles_on_path(state: RunState, path: list[int]) -> int:
    count = 0
    for idx in path:
        try:
            tile = state.board.get_by_index(int(idx))
        except (IndexError, ValueError):
            continue
        if tile.color.value == "red":
            count += 1
    return count


class EffectEngine:
    """
    Post-submit + grid-start mutations.

    Submit path traces EncounterController.SubmitWord / _remainingTarget -= score.
    Grid advance traces GenerateGrid / _remainingGrids--.
    """

    def __init__(self, rules: dict | None = None) -> None:
        self._rules = rules

    @property
    def rules(self) -> dict:
        if self._rules is None:
            from cursed_words_solver.rules.pipeline import ScoringPipeline

            self._rules = ScoringPipeline().rules
        return self._rules

    def apply_post_submit(
        self,
        state: RunState,
        submission: Submission,
        reward: RewardResult,
    ) -> RunState:
        """Apply post-submit extras without advancing grid."""
        next_state = state.clone()
        extras = next_state.extras
        raw_score = reward.score
        from cursed_words_solver.rules.quest_scoring import effective_submit_score

        submit_score = effective_submit_score(raw_score, next_state.loadout)

        remaining = next_state.encounter_remaining_target
        if remaining > 0 or "encounter_remaining_target" in extras:
            from cursed_words_solver.rules.quest_scoring import (
                remaining_target_after_submit,
            )

            next_state.set_encounter_remaining_target(
                int(
                    remaining_target_after_submit(
                        float(remaining), raw_score, next_state.loadout
                    )
                )
            )
        next_state.encounter_score_earned += int(submit_score)

        word = submission.word
        first = _effective_word_start_letter(
            next_state.board, submission.path, submission.effective_scoring_word
        )
        if not first:
            first = _first_letter(word)
        if first:
            extras["previous_word_first_letter"] = first.lower()[:1]

        red_count = _count_red_tiles_on_path(next_state, submission.path)
        historic = _load_historic_list(extras)
        entry: dict[str, Any] = {
            "word": word.upper(),
            "score": int(submit_score),
            "path": list(submission.path),
        }
        if red_count:
            entry["red_tile_count"] = red_count
        historic.append(entry)
        extras["historic_words"] = json.dumps(historic, separators=(",", ":"))

        _apply_setup_extras(next_state, submission, reward, self.rules)

        try:
            prev_count = int(extras.get("scoring_previous_words_count", 0) or 0)
        except (TypeError, ValueError):
            prev_count = 0
        extras["scoring_previous_words_count"] = str(prev_count + 1)

        next_state.step_index += 1
        return next_state

    def apply_grid_start(
        self,
        state: RunState,
        rng: SimRNG,
    ) -> RunState:
        """
        Advance to next grid: decrement grids_remaining, bump grid_number.

        Board mutations via effective_board_for_loadout when not board_from_melmod.
        """
        next_state = state.clone()
        extras = next_state.extras

        grids = next_state.grids_remaining
        next_state.set_grids_remaining(max(0, grids - 1))
        next_state.set_grid_number(next_state.grid_number + 1)
        extras["is_first_grid_of_encounter"] = "false"
        extras.pop("board_from_melmod", None)

        scatter_seed = extras.get("scatter_seed")
        if scatter_seed is None:
            extras["scatter_seed"] = str(rng.substream("scatter").randint(0, 2**31 - 1))

        next_state.board = effective_board_for_loadout(
            next_state.board,
            next_state.loadout,
            self.rules,
        )
        return next_state

    def apply(
        self,
        state: RunState,
        submission: Submission,
        reward: RewardResult,
        rng: SimRNG,
        *,
        advance_grid: bool = True,
    ) -> RunState:
        after_submit = self.apply_post_submit(state, submission, reward)
        if not advance_grid:
            return after_submit

        remaining_target = after_submit.encounter_remaining_target
        if remaining_target <= 0:
            after_submit.encounter_won = True
            return after_submit

        grids_left = after_submit.grids_remaining
        if grids_left <= 0 and remaining_target > 0:
            after_submit.encounter_lost = True
            return after_submit

        return self.apply_grid_start(after_submit, rng)
