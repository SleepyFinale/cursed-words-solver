"""Full scoring pipeline: boss penalties -> grid -> pin -> stickers -> stamps (wiki order)."""



from __future__ import annotations



import json
import math

from pathlib import Path

from typing import Any



from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor

from cursed_words_solver.rules.base_scoring import _scrabble_value, tile_base_contribution

from cursed_words_solver.rules.pin_effects import apply_pin_word_scoring
from cursed_words_solver.rules.stamp_effects import (
    PIPELINE_SKIP_TYPES as _STAMP_SKIP_TYPES,
    apply_stamp_with_orchestration,
    apply_sticker_with_orchestration,
)
from cursed_words_solver.rules.rule_lookup import (
    collect_unmapped_items,
    count_catalog_items,
    count_scoring_items,
    get_rule,
    resolve_rule_id,
)
from cursed_words_solver.rules.scoring_order import (
    apply_green_tile_word_transfer,
    build_scoring_item_sequence,
    hourglass_reverses_order,
)
from cursed_words_solver.rules.tile_scoring import apply_tile_init
from cursed_words_solver.rules.stamp_behaviors import loadout_has_stamp

from cursed_words_solver.rules.boss_effects import (
    boss_context,
    boss_rule_applies,
    boss_scoring_effect_type,
    get_active_boss_rule,
    resolve_boss_scaling,
)
from cursed_words_solver.rules.boss_scoring import (
    EARLY_BOSS_TYPES,
    apply_early_boss_scoring,
)

# Wiki Scoring step 1: Salamander / Robo-Monkey before pin, stickers, stamps.
_EARLY_BOSS_EFFECT_TYPES = EARLY_BOSS_TYPES
from cursed_words_solver.rules.scoring_conditions import (
    abacus_colored_number_bonus,
    birthday_cake_accumulated,
    bicycle_word_bonus,
    bicycle_word_per_card,
    bicycle_word_score_accumulator,
    bicycle_word_score_accumulator_for_submit,
    brain_multiplier,
    card_suit,
    effective_suited_cards_on_path,
    celestial_body_tile_eligible,
    is_last_card_rank_on_path,
    suited_cards_on_path_count,
    chess_takes_on_path,
    chess_take_strict_mode,
    first_n_movie_camera_piece_value_sum,
    is_take_at_path_position,
    is_chess_tile,
    burrito_word_multiplier,
    coloured_tile_count_on_grid,
    chess_move_tile_count_on_path,
    colourless_adjacent_two_unique_colours,
    consumable_rack_multiplier,
    consumable_count_on_path,
    currency_value_on_path,
    chess_piece_count_on_path,
    grid_number_half,
    longest_red_run_on_path,
    distinct_pair_count_on_path,
    king_take_on_path,
    path_has_wildcard_matching_target_curse,
    shield_blue_base_from_loadout,
    shop_restock_count,
    word_all_colourless_on_path,
    grid_total_base_score,
    michael_book_bonus,
    stamps_shop_price_total,
    target_chess_curse_from_loadout,
    target_score_from_loadout,
    evaluate_sticker_condition,
    explain_sticker_condition,
    first_letter_on_path,
    word_first_letter,
    detect_card_hand,
    unused_cards_on_board,
    is_colored_number_tile,
    is_number_like_tile,
    NON_COLOUR_FOR_NUMBER_BONUS,
    is_consumable_tile,
    mahjong_consumable_factor,
    money_for_scoring,
    money_word_multiplier,
    number_sum_on_path,
    number_tile_count_on_path,
    word_all_numbers_on_path,
    human_hands_stamp_extra_apps,
    pin_left_level,
    pin_right_level,
    rainbow_per_colour_bonus,
    red_tiles_used_encounter,
    letter_counts_on_path,
    max_qualifying_letter_half_multiplier,
    scaled_word_multiplier,
    sticker_rule_int,
    super_8_take_word_bonus,
    tile_matches_target,
    unique_colour_count_on_path,
    unique_curse_type_count_on_path,
    unique_colours_on_path,
    unique_vowels_in_word,
    unused_red_tiles_on_board,
    void_tiles_letter_not_in_word,
    word_same_start_end_letter,
    word_starts_ends_different_suit,
    apply_mutating_dna_bonus,
    mutating_dna_letter_counts_from_loadout,
    normalize_scoring_path,
    adjacent_void_count,
    subtotal_before_mult,
    consecutive_number_run_path_positions,
    highest_number_on_path,
)



STICKERS_PATH = Path(__file__).resolve().parents[2] / "data" / "wiki" / "stickers.json"





def _load_sticker_rules() -> dict[str, Any]:

    if STICKERS_PATH.exists():

        return json.loads(STICKERS_PATH.read_text(encoding="utf-8"))

    return {"stickers": {}, "stamps": {}, "bosses": {}, "pins": {}, "aliases": {}}





def _init_tile_contribution(
    tile: Tile,
    money: int,
    *,
    microscope_base: bool = False,
    blue_base_override: int | None = None,
) -> float:
    """Per-tile score at init; Microscope uses packet base_score instead of color bonuses."""
    if tile.curse == CurseType.ITEM:
        return 0.0
    if microscope_base:
        return float(tile.base_score)
    if tile.color == TileColor.BLUE and blue_base_override is not None:
        return float(blue_base_override)
    return float(tile_base_contribution(tile, money))


def _init_state(
    board: Board,
    path: list[int],
    word: str,
    *,
    blue_base_override: int | None = None,
    microscope_base: bool = False,
) -> dict[str, Any]:

    tile_scores: list[float] = []

    base_total = 0.0

    for idx in path:

        tile = board.get_by_index(idx)

        contrib = _init_tile_contribution(
            tile,
            board.money,
            microscope_base=microscope_base,
            blue_base_override=blue_base_override,
        )

        tile_scores.append(contrib)

        base_total += contrib

    return {

        "word": word,

        "path": path,

        "base_score": base_total,

        "tile_scores": tile_scores,

        "word_score": 0.0,

        "multiplier": 1.0,

        "money_bonus": 0,

        "effects": [],

        "pending_word_multipliers": [],

        "salamander_post_mutating_mults": [],

    }


def _void_number_on_path(tile: Tile) -> bool:
    """Built-in void path bonuses apply to void-cursed NUMBER tiles only (not void letters)."""
    return tile.color == TileColor.VOID and tile.curse == CurseType.NUMBER


def _apply_void_path_bonuses(
    board: Board, path: list[int], loadout: Loadout, state: dict[str, Any]
) -> None:
    """Built-in void path bonus: +2 TILE SCORE on a letter (Scrabble value ≥ 8) immediately before a void NUMBER."""
    bonus = 2
    before_void = 0
    before_void_bonus_total = 0
    for i in range(len(path) - 1):
        next_tile = board.get_by_index(path[i + 1])
        if not _void_number_on_path(next_tile):
            continue
        prev_tile = board.get_by_index(path[i])
        if prev_tile.curse != CurseType.LETTER or _scrabble_value(prev_tile.letter) < 8:
            continue
        state["tile_scores"][i] += bonus
        before_void += 1
        before_void_bonus_total += bonus
    if before_void:
        state["effects"].append(
            f"+{before_void_bonus_total} tile before VOID on path ({before_void})"
        )
        _trace_step(
            state,
            "void_path",
            detail=f"+{before_void_bonus_total} before void number",
        )


def _pending_multiplier_factor(entry: float | tuple[float, str]) -> float:
    if isinstance(entry, tuple):
        return float(entry[0])
    return float(entry)


def _pending_multiplier_rule_id(entry: float | tuple[float, str]) -> str:
    if isinstance(entry, tuple) and len(entry) > 1:
        return str(entry[1])
    return ""


def _apply_immediate_word_multiplier(
    state: dict[str, Any], factor: float, rule_id: str = ""
) -> None:
    """Apply ×WORD to current tile+word subtotal with floor (before +tile stickers)."""
    if factor == 1.0:
        return
    tile_sum = sum(state["tile_scores"])
    subtotal = tile_sum + state["word_score"]
    new_total = math.floor(subtotal * factor)
    state["word_score"] = new_total - tile_sum
    state["multiplier"] *= factor


def _apply_immediate_word_multiplier_word_only(
    state: dict[str, Any], factor: float, rule_id: str = ""
) -> None:
    """×WORD SCORE on the word track only (Wrestlers after other word bonuses)."""
    if factor == 1.0:
        return
    state["word_score"] = math.floor(state["word_score"] * factor)
    state["multiplier"] *= factor


def _queue_word_multiplier(
    state: dict[str, Any],
    factor: float,
    rule_id: str = "",
    *,
    defer_finalize: bool = False,
) -> None:
    """Queue ×WORD SCORE for finalize (stamps / late effects). Pass A uses immediate."""
    if factor == 1.0:
        return
    if state.get("_immediate_word_mult") and not defer_finalize:
        _apply_immediate_word_multiplier(state, factor, rule_id)
        return
    state["pending_word_multipliers"].append((factor, rule_id))
    state["multiplier"] *= factor


def _flush_word_multipliers_to_tiles(state: dict[str, Any]) -> None:
    """Apply queued ×WORD to tile scores only (before later +WORD SCORE adds)."""
    for entry in state.get("pending_word_multipliers", []):
        factor = _pending_multiplier_factor(entry)
        if factor != 1.0:
            for i in range(len(state["tile_scores"])):
                state["tile_scores"][i] *= factor
    state["pending_word_multipliers"].clear()


def _add_word_score(state: dict[str, Any], bonus: float) -> None:
    if not bonus:
        return
    _flush_word_multipliers_to_tiles(state)
    state["word_score"] += bonus


def _subtotal_for_trace(state: dict[str, Any]) -> float:
    return float(sum(state["tile_scores"]) + state["word_score"])


def _trace_step(state: dict[str, Any], phase: str, **fields: Any) -> None:
    trace = state.get("_trace")
    if trace is None:
        return
    entry: dict[str, Any] = {
        "phase": phase,
        "tile_scores": [float(x) for x in state["tile_scores"]],
        "word_score": float(state["word_score"]),
        "subtotal": _subtotal_for_trace(state),
    }
    entry.update(fields)
    trace.append(entry)


def _trace_rule_snapshot(state: dict[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(state["tile_scores"]),
        float(state["word_score"]),
        len(state.get("pending_word_multipliers", [])),
        int(state.get("money_bonus", 0)),
    )


def _trace_rule_step(
    state: dict[str, Any],
    *,
    rule_id: str,
    effect_type: str,
    before: tuple[Any, ...],
    effects_before: int,
    rule: dict,
    trace_context: dict[str, Any] | None = None,
) -> None:
    if state.get("_trace") is None:
        return
    after = _trace_rule_snapshot(state)
    applied = before != after
    effects = state.get("effects") or []
    ctx = trace_context or {}
    if ctx.get("condition_explanation"):
        detail = str(ctx["condition_explanation"])
    elif applied and len(effects) > effects_before:
        detail = str(effects[-1])
    elif applied:
        detail = effect_type
    else:
        condition = rule.get("condition", "")
        detail = f"skipped ({condition})" if condition else f"skipped ({effect_type})"
    fields: dict[str, Any] = {
        "rule_id": rule_id,
        "effect_type": effect_type,
        "applied": applied,
        "detail": detail,
    }
    if ctx:
        for key in (
            "condition",
            "condition_met",
            "word_first_letter",
            "path_first_letter",
            "skip_reason",
        ):
            if key in ctx:
                fields[key] = ctx[key]
    _trace_step(state, "rule", **fields)


def _boss_is_salamander(loadout: Loadout) -> bool:
    bid = (loadout.boss_id or "").strip().lower()
    return bid == "salamander" or "bosslesspoints" in bid


def _finalize(
    state: dict[str, Any],
    board: Board | None = None,
    path: list[int] | None = None,
) -> float:
    """Sum tile + word scores, then apply queued ×WORD multipliers with floor each step."""
    if board is not None and path is not None:
        apply_green_tile_word_transfer(board, path, state)
    total = sum(state["tile_scores"]) + state["word_score"]
    for entry in state.get("pending_word_multipliers", []):
        factor = _pending_multiplier_factor(entry)
        if factor != 1.0:
            total = math.floor(total * factor)
    return float(total)


def _finalize_with_trace(state: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
    """Like _finalize but records each ×WORD floor step in trace."""
    trace = state.get("_trace")
    total = sum(state["tile_scores"]) + state["word_score"]
    mult_trace: list[dict[str, Any]] = []
    if trace is not None:
        _trace_step(state, "pre_multiply", detail="tile sum + word score")
    for entry in state.get("pending_word_multipliers", []):
        factor = _pending_multiplier_factor(entry)
        mult_rule_id = _pending_multiplier_rule_id(entry)
        if factor != 1.0:
            total = math.floor(total * factor)
            if trace is not None:
                fields: dict[str, Any] = {
                    "factor": float(factor),
                    "detail": f"×{factor} word (floor)",
                }
                if mult_rule_id:
                    fields["rule_id"] = mult_rule_id
                _trace_step(state, "multiply", **fields)
    return float(total), mult_trace





class ScoringPipeline:

    """Apply loadout effects in game order (pin -> stickers -> stamps -> boss)."""



    def __init__(self) -> None:

        self.rules = _load_sticker_rules()



    def loadout_mapping_summary(

        self, loadout: Loadout | None

    ) -> tuple[int, int, int, list[str]]:

        """Scoring-active count, total items, grid-only count, unmapped labels."""

        loadout = loadout or Loadout()

        scoring, total, grid_only = count_scoring_items(self.rules, loadout)

        unmapped = collect_unmapped_items(self.rules, loadout)

        return scoring, total, grid_only, unmapped



    def _compute_state(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout,
        *,
        trace: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        path = normalize_scoring_path(path)
        state = _init_state(
            board,
            path,
            word,
            blue_base_override=shield_blue_base_from_loadout(loadout, self.rules),
            microscope_base=loadout_has_stamp(loadout, "microscope"),
        )
        if trace is not None:
            state["_trace"] = trace
        apply_tile_init(
            board,
            path,
            word,
            loadout,
            state,
            microscope_base=loadout_has_stamp(loadout, "microscope"),
            blue_base_override=shield_blue_base_from_loadout(loadout, self.rules),
            trace_step=_trace_step if trace is not None else None,
        )
        hourglass = hourglass_reverses_order(loadout, self.rules)
        if not hourglass:
            state = self._apply_early_boss_rules(state, board, path, loadout)
        _apply_void_path_bonuses(board, path, loadout, state)

        for ref in build_scoring_item_sequence(board, path, loadout, self.rules):
            if ref.kind != "grid_path":
                continue
            _key, rule = get_rule(self.rules, "stickers", ref.rule_id, ref.rule_id)
            if not rule:
                _key, rule = get_rule(self.rules, "stamps", ref.rule_id, ref.rule_id)
            if not rule or rule.get("type") in (
                "unmodeled",
                "custom",
                "scatter_start_grid",
                "scatter_start_encounter",
            ):
                continue
            state = self._apply_rule(
                rule,
                state,
                board,
                path,
                loadout,
                ref.level,
                applying_sticker_id=ref.rule_id,
            )
            _trace_step(state, "grid_item", rule_id=ref.rule_id, detail="scattered grid item")

        pin_effect = str(loadout.extras.get("pin_effect", "") or "").strip()
        if pin_effect and not hourglass:
            state = self._apply_pin(loadout, pin_effect, state, board, path)
            _trace_step(state, "pin", rule_id=pin_effect, detail="pin applied")
        has_mutating_stamp = any(
            "mutating" in (stamp.id or "").lower()
            or "dna" in (stamp.id or "").lower()
            or "mutating" in (stamp.name or "").lower()
            for stamp in loadout.stamps
        )
        mutating_prior_total = sum(
            mutating_dna_letter_counts_from_loadout(loadout).values()
        )
        defer_multiply_stickers = (
            has_mutating_stamp and 0 < mutating_prior_total < 8
        )

        _skip_types = _STAMP_SKIP_TYPES

        def _sticker_slots() -> list[int]:
            slots = list(range(len(loadout.stickers)))
            return list(reversed(slots)) if hourglass else slots

        def _stamp_slots() -> list[int]:
            slots = list(range(len(loadout.stamps)))
            return list(reversed(slots)) if hourglass else slots

        def _apply_sticker_pass(*, multiply_only: bool) -> None:
            nonlocal state
            for slot in _sticker_slots():
                sticker = loadout.stickers[slot]
                _key, rule = get_rule(
                    self.rules, "stickers", sticker.id, sticker.name
                )
                if not rule or rule.get("type") in _skip_types:
                    continue
                is_multiply = rule.get("type") == "multiply_word_scaled"
                if multiply_only != is_multiply:
                    continue
                state = apply_sticker_with_orchestration(
                    rules=self.rules,
                    loadout=loadout,
                    state=state,
                    board=board,
                    path=path,
                    sticker=sticker,
                    slot=slot,
                    apply_rule=self._apply_rule,
                )

        state["_immediate_word_mult"] = True
        if hourglass:
            for slot in _stamp_slots():
                stamp = loadout.stamps[slot]
                _key, rule = get_rule(self.rules, "stamps", stamp.id, stamp.name)
                if rule and rule.get("type") not in _skip_types:
                    state = apply_stamp_with_orchestration(
                        rules=self.rules,
                        loadout=loadout,
                        state=state,
                        board=board,
                        path=path,
                        stamp=stamp,
                        slot=slot,
                        apply_rule=self._apply_rule,
                    )
            if defer_multiply_stickers:
                _apply_sticker_pass(multiply_only=False)
            else:
                for slot in _sticker_slots():
                    sticker = loadout.stickers[slot]
                    _key, rule = get_rule(
                        self.rules, "stickers", sticker.id, sticker.name
                    )
                    if not rule or rule.get("type") in _skip_types:
                        continue
                    state = apply_sticker_with_orchestration(
                        rules=self.rules,
                        loadout=loadout,
                        state=state,
                        board=board,
                        path=path,
                        sticker=sticker,
                        slot=slot,
                        apply_rule=self._apply_rule,
                    )
            if defer_multiply_stickers:
                _apply_sticker_pass(multiply_only=True)
            if pin_effect:
                state = self._apply_pin(loadout, pin_effect, state, board, path)
                _trace_step(state, "pin", rule_id=pin_effect, detail="pin applied")
        elif defer_multiply_stickers:
            _apply_sticker_pass(multiply_only=False)
        else:
            for slot in _sticker_slots():
                sticker = loadout.stickers[slot]
                _key, rule = get_rule(
                    self.rules, "stickers", sticker.id, sticker.name
                )
                if not rule or rule.get("type") in _skip_types:
                    continue
                state = apply_sticker_with_orchestration(
                    rules=self.rules,
                    loadout=loadout,
                    state=state,
                    board=board,
                    path=path,
                    sticker=sticker,
                    slot=slot,
                    apply_rule=self._apply_rule,
                )
        state["_immediate_word_mult"] = False
        if not hourglass:
            for slot in _stamp_slots():
                stamp = loadout.stamps[slot]
                _key, rule = get_rule(self.rules, "stamps", stamp.id, stamp.name)
                if rule and rule.get("type") not in _skip_types:
                    state = apply_stamp_with_orchestration(
                        rules=self.rules,
                        loadout=loadout,
                        state=state,
                        board=board,
                        path=path,
                        stamp=stamp,
                        slot=slot,
                        apply_rule=self._apply_rule,
                    )
        for factor, mult_rule_id in state.get("salamander_post_mutating_mults", []):
            _apply_immediate_word_multiplier(state, factor, mult_rule_id)
        state["salamander_post_mutating_mults"] = []
        if defer_multiply_stickers:
            state["_immediate_word_mult"] = True
            _apply_sticker_pass(multiply_only=True)
            state["_immediate_word_mult"] = False
        if pin_effect and resolve_rule_id(
            self.rules, "pins", pin_effect, pin_effect
        ) == "human_boy":
            state = self._apply_human_hands(loadout, state, board, path)
        if hourglass:
            state = self._apply_early_boss_rules(state, board, path, loadout)
        state = self._apply_late_boss_rules(state, board, path, loadout)
        return state

    def _apply_early_boss_rules(
        self,
        state: dict[str, Any],
        board: Board,
        path: list[int],
        loadout: Loadout,
    ) -> dict[str, Any]:
        """Wiki step 1: ApplyBossModifier before stickers (unless Hourglass)."""
        trace_fn = _trace_step if state.get("_trace") is not None else None
        return apply_early_boss_scoring(
            state,
            board,
            path,
            loadout,
            self.rules,
            self._apply_rule,
            trace_step=trace_fn,
        )

    def _apply_late_boss_rules(
        self,
        state: dict[str, Any],
        board: Board,
        path: list[int],
        loadout: Loadout,
    ) -> dict[str, Any]:
        """Boss effects not handled in wiki step 1 (constraints, vowel zero, custom)."""
        _key, boss = get_active_boss_rule(self.rules, loadout)
        if boss and boss.get("type") not in (
            "unmodeled",
            "custom",
            *_EARLY_BOSS_EFFECT_TYPES,
        ):
            ctx = boss_context(loadout, self.rules)
            if boss_rule_applies(boss, ctx):
                state = self._apply_rule(boss, state, board, path, loadout, 1)
                if state.get("_trace") is not None:
                    _trace_step(
                        state,
                        "boss_late",
                        rule_id=_key or loadout.boss_id or "boss",
                        detail=boss_scoring_effect_type(boss) or boss.get("type", ""),
                    )
        elif loadout.boss_effect:
            state = self._apply_named_effect(
                loadout.boss_effect, state, board, path, loadout
            )
        return state

    def score_total_only(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout | None = None,
    ) -> float:
        """Final score without building the breakdown dict (search hot path)."""
        loadout = loadout or Loadout(money=board.money)
        state = self._compute_state(board, path, word, loadout)
        return _finalize(state, board, path)

    def score(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout | None = None,
    ) -> tuple[float, dict[str, Any]]:
        loadout = loadout or Loadout(money=board.money)
        state = self._compute_state(board, path, word, loadout)
        final = _finalize(state, board, path)
        breakdown: dict[str, Any] = {
            "base_total": state["base_score"],
            "tile_total": sum(state["tile_scores"]),
            "word_score": state["word_score"],
            "multiplier": state["multiplier"],
            "money_bonus": state.get("money_bonus", 0),
            "tiles": [
                {
                    "index": path[i],
                    "tile_score": state["tile_scores"][i],
                }
                for i in range(len(path))
            ],
        }
        breakdown["pipeline"] = state
        return final, breakdown

    def score_with_trace(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout | None = None,
    ) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
        """Full score with ordered trace steps for mismatch debugging."""
        loadout = loadout or Loadout(money=board.money)
        trace: list[dict[str, Any]] = []
        state = self._compute_state(board, path, word, loadout, trace=trace)
        final, _ = _finalize_with_trace(state)
        breakdown: dict[str, Any] = {
            "base_total": state["base_score"],
            "tile_total": sum(state["tile_scores"]),
            "word_score": state["word_score"],
            "multiplier": state["multiplier"],
            "money_bonus": state.get("money_bonus", 0),
            "tiles": [
                {
                    "index": path[i],
                    "tile_score": state["tile_scores"][i],
                }
                for i in range(len(path))
            ],
        }
        pipeline_state = {k: v for k, v in state.items() if k != "_trace"}
        breakdown["pipeline"] = pipeline_state
        return final, breakdown, trace

    def _apply_pin(
        self,
        loadout: Loadout,
        pin_effect: str,
        state: dict,
        board: Board,
        path: list[int],
    ) -> dict:
        return apply_pin_word_scoring(
            rules=self.rules,
            loadout=loadout,
            pin_effect=pin_effect,
            state=state,
            board=board,
            path=path,
            apply_rule=self._apply_rule,
        )



    def _apply_human_hands(

        self,

        loadout: Loadout,

        state: dict,

        board: Board,

        path: list[int],

    ) -> dict:

        left = pin_left_level(loadout)

        right = pin_right_level(loadout)

        fav_sticker = str(

            (loadout.extras or {}).get("favourite_sticker_id", "") or ""

        ).strip()

        fav_stamp = str(

            (loadout.extras or {}).get("favourite_stamp_id", "") or ""

        ).strip()



        if fav_sticker:

            for sticker in loadout.stickers:

                if sticker.id == fav_sticker or sticker.name == fav_sticker:

                    _key, rule = get_rule(

                        self.rules, "stickers", sticker.id, sticker.name

                    )

                    if rule and rule.get("type") not in ("unmodeled", "custom"):

                        eff_level = sticker.level + left

                        state = self._apply_rule(

                            rule, state, board, path, loadout, eff_level

                        )

                        state["effects"].append(

                            f"Human Hands: favourite sticker +{left} level(s)"

                        )

                    break



        stamp_extra = human_hands_stamp_extra_apps(loadout)
        if fav_stamp and stamp_extra > 0:
            for stamp in loadout.stamps:
                if stamp.id == fav_stamp or stamp.name == fav_stamp:
                    _key, rule = get_rule(
                        self.rules, "stamps", stamp.id, stamp.name
                    )
                    if rule and rule.get("type") not in ("unmodeled", "custom"):
                        for _ in range(stamp_extra):
                            state = self._apply_rule(
                                rule, state, board, path, loadout, 1
                            )
                        state["effects"].append(
                            f"Human Hands: favourite stamp ×{stamp_extra} extra"
                        )
                    break



        return state



    def _apply_named_effect(

        self,

        effect_id: str,

        state: dict,

        board: Board,

        path: list[int],

        loadout: Loadout,

    ) -> dict:

        for bucket in ("pins", "stickers", "stamps", "bosses"):

            _key, rule = get_rule(self.rules, bucket, effect_id, effect_id)

            if rule and rule.get("type") not in ("unmodeled", "custom", None):

                return self._apply_rule(rule, state, board, path, loadout, 1)

        canonical = resolve_rule_id(self.rules, "stickers", effect_id, effect_id)

        if canonical:

            rule = self.rules.get("stickers", {}).get(canonical)

            if rule and rule.get("type") not in ("unmodeled", "custom"):

                return self._apply_rule(rule, state, board, path, loadout, 1)

        return state



    def _apply_rule(

        self,

        rule: dict,

        state: dict,

        board: Board,

        path: list[int],

        loadout: Loadout,

        level: int,

        applying_sticker_id: str = "",

    ) -> dict:

        effect_type = rule.get("type", "")

        if effect_type in (
            "unmodeled",
            "custom",
            "pin_memory_replay",
            "human_hands_pin",
            "blue_tile_base_override",
        ):

            return state

        trace_before = (
            _trace_rule_snapshot(state) if state.get("_trace") is not None else None
        )
        effects_before = len(state.get("effects") or [])
        rule_trace_context: dict[str, Any] = {}
        rule_id = applying_sticker_id or str(rule.get("id", "") or rule.get("name", ""))

        value = sticker_rule_int(level, rule) if "base" in rule or effect_type in (
            "add_tile_score",
            "add_word_score",
            "red_tile_bonus",
            "word_length_bonus",
            "shiny_chain",
        ) else rule.get("value", 0) * level

        if effect_type == "colored_number_tile_bonus":

            bonus_each = abacus_colored_number_bonus(loadout, rule)

            count = 0

            for i, idx in enumerate(path):

                if is_colored_number_tile(board.get_by_index(idx)):

                    state["tile_scores"][i] += bonus_each

                    count += 1

            if count:

                state["effects"].append(

                    f"+{bonus_each * count} coloured number tile ({count} tile(s))"

                )

        elif effect_type == "multiply_if_number_sum":

            min_sum = int(rule.get("min_sum", 7))

            num_sum = number_sum_on_path(board, path)

            if num_sum >= min_sum:

                factor = brain_multiplier(level, rule)

                _queue_word_multiplier(state, factor, rule_id)

                state["effects"].append(

                    f"×{factor} word (number sum {num_sum} ≥ {min_sum})"

                )

        elif effect_type == "tile_multiply":
            factor = float(rule.get("factor", 2.0))
            if rule.get("scale_by_pin_right"):
                factor = mahjong_consumable_factor(loadout, rule)
            elif rule.get("per_level_factor"):
                factor = float(rule.get("factor_base", 1.0)) + float(
                    rule.get("factor_per_level", 1.0)
                ) * level
            elif "base" in rule:
                factor = scaled_word_multiplier(level, rule)
            if rule.get("scale_from_extras") == "grid_number_half" and loadout is not None:
                factor = grid_number_half(loadout)
            if rule.get("scale_by_consumable_count_on_path"):
                factor = float(max(consumable_count_on_path(board, path), 1))
            if factor < 0:
                factor = float(sticker_rule_int(level, rule))

            target = rule.get("target", "number")
            applied = 0
            if target == "first_of_each_colour":
                seen_colours: set[str] = set()
                for i, idx in enumerate(path):
                    tile = board.get_by_index(idx)
                    colour_key = tile.color.value
                    if colour_key in seen_colours:
                        continue
                    seen_colours.add(colour_key)
                    state["tile_scores"][i] *= factor
                    applied += 1
            elif target == "first_n_red":
                factor = float(rule.get("factor", 3.0))
                n_apply = sticker_rule_int(level, rule)
                red_seen = 0
                for i, idx in enumerate(path):
                    tile = board.get_by_index(idx)
                    if tile.color.value != "red":
                        continue
                    if red_seen >= n_apply:
                        break
                    state["tile_scores"][i] *= factor
                    red_seen += 1
                    applied += 1
            else:
                strict_takes = chess_take_strict_mode(
                    board,
                    path,
                    strict_requested=rule.get("strict_takes", False),
                )
                for i, idx in enumerate(path):
                    tile = board.get_by_index(idx)
                    if target == "chess_take" and is_take_at_path_position(
                        board, path, i, strict=strict_takes
                    ):
                        # Zebra: multiply the capturing piece (path[i-1]), not landing.
                        mult_idx = i - 1 if i > 0 else 0
                        state["tile_scores"][mult_idx] *= factor
                        applied += 1
                    elif target == "number" and is_number_like_tile(tile):
                        mult = factor
                        if rule.get("scale_by_path_position"):
                            mult = float(i + 1)
                        state["tile_scores"][i] *= mult
                        applied += 1
                    elif target == "consumable" and is_consumable_tile(tile):
                        state["tile_scores"][i] *= factor
                        applied += 1
                    elif target == "colourless_adjacent_two_colours":
                        if colourless_adjacent_two_unique_colours(board, tile):
                            state["tile_scores"][i] *= factor
                            applied += 1
                    elif target.startswith("letter:") and tile_matches_target(
                        tile, target
                    ):
                        state["tile_scores"][i] *= factor
                        applied += 1
                    elif target in (
                        "consonant",
                        "vowel",
                        "red",
                        "blue",
                        "wildcard",
                        "red_note",
                        "shiny",
                        "void",
                        "all",
                    ) and tile_matches_target(tile, target):
                        state["tile_scores"][i] *= factor
                        applied += 1
                    elif target == "all":
                        state["tile_scores"][i] *= factor
                        applied += 1
            if applied:
                state["effects"].append(f"×{factor} {target} tile score ({applied})")

        elif effect_type == "add_tile_score":
            target = rule.get("target", "all")
            bonus_each = sticker_rule_int(level, rule)
            total_bonus = 0
            if target == "void_adjacent":
                for i, idx in enumerate(path):
                    tile = board.get_by_index(idx)
                    n_void = adjacent_void_count(
                        board, tile, path=path, path_index=i
                    )
                    if n_void:
                        add = bonus_each * n_void
                        state["tile_scores"][i] += add
                        total_bonus += add
                if total_bonus:
                    state["effects"].append(
                        f"+{total_bonus} void-adjacent tile score"
                    )
            elif target == "chess_piece":
                curse = target_chess_curse_from_loadout(loadout)
                count = 0
                if curse is not None:
                    for i, idx in enumerate(path):
                        if board.get_by_index(idx).curse == curse:
                            state["tile_scores"][i] += bonus_each
                            count += 1
                            total_bonus += bonus_each
            elif target == "chess_move_tiles":
                count = 0
                for i, idx in enumerate(path):
                    if is_chess_tile(board.get_by_index(idx)):
                        state["tile_scores"][i] += bonus_each
                        count += 1
                        total_bonus += bonus_each
            else:
                count = 0
                for i, idx in enumerate(path):
                    tile = board.get_by_index(idx)
                    if target == "card":
                        if not celestial_body_tile_eligible(
                            board, path, i, level, loadout=loadout
                        ):
                            continue
                    elif not tile_matches_target(tile, target):
                        continue
                    state["tile_scores"][i] += bonus_each
                    count += 1
                    total_bonus += bonus_each
                if count:
                    sign = "+" if bonus_each >= 0 else ""
                    state["effects"].append(
                        f"{sign}{total_bonus} {target} tile score ({count})"
                    )

        elif effect_type == "add_word_score":
            word_mode = rule.get("word_mode", "flat")
            bonus = 0
            if word_mode == "per_path_tile":
                bonus = sticker_rule_int(level, rule) * len(path)
            elif word_mode == "per_money":
                bonus = sticker_rule_int(level, rule) * money_for_scoring(
                    board, path, loadout
                )
            elif word_mode == "per_void_unused":
                n = void_tiles_letter_not_in_word(board, state["word"])
                bonus = sticker_rule_int(level, rule) * n
            elif word_mode == "per_unused_red":
                n = unused_red_tiles_on_board(board, path)
                bonus = sticker_rule_int(level, rule) * n
            elif word_mode == "if_same_start_end":
                if word_same_start_end_letter(state["word"]):
                    bonus = sticker_rule_int(level, rule)
            elif word_mode == "per_unique_vowel":
                n = unique_vowels_in_word(state["word"])
                bonus = sticker_rule_int(level, rule) * n
            elif word_mode == "if_subtotal_zero":
                if subtotal_before_mult(state) == 0:
                    bonus = sticker_rule_int(level, rule)
            elif word_mode == "per_highest_number":
                high = highest_number_on_path(board, path)
                if high:
                    bonus = sticker_rule_int(level, rule) * high
            elif word_mode == "birthday_cake_bonus":
                high = highest_number_on_path(board, path)
                accumulated = birthday_cake_accumulated(loadout)
                level_factor = sticker_rule_int(level, rule)
                raw_improve = level_factor * high if high else 0.0
                improve = int(math.floor(raw_improve + 0.5))
                bonus = accumulated + improve
                if bonus:
                    state["effects"].append(
                        f"+{bonus} word score (Birthday Cake: {accumulated}"
                        f" + {improve})"
                    )
            elif word_mode == "if_contains_target_number":
                if evaluate_sticker_condition(
                    "contains_target_number", board, path, state["word"], loadout
                ):
                    bonus = sticker_rule_int(level, rule)
            elif word_mode == "per_stamp_shop_price":
                total = stamps_shop_price_total(loadout, self.rules)
                bonus = sticker_rule_int(level, rule) * total
            elif word_mode == "scaled_flat":
                bonus = sticker_rule_int(level, rule)
            elif word_mode == "if_base_score_eq_target":
                if state["base_score"] == target_score_from_loadout(loadout):
                    bonus = sticker_rule_int(level, rule)
            elif word_mode == "michael_book_bonus":
                bonus = michael_book_bonus(loadout)
            elif word_mode == "grid_total_base_times_level":
                total = grid_total_base_score(board)
                bonus = sticker_rule_int(level, rule) * total
            elif word_mode == "if_sticker_slot_last":
                if evaluate_sticker_condition(
                    "requires_sticker_slot:last",
                    board,
                    path,
                    state["word"],
                    loadout,
                    applying_sticker_id=applying_sticker_id,
                ):
                    bonus = sticker_rule_int(level, rule)
            elif word_mode == "if_king_take_on_path":
                if king_take_on_path(board, path):
                    bonus = sticker_rule_int(level, rule)
            elif word_mode == "if_target_wildcard_on_path":
                if path_has_wildcard_matching_target_curse(board, path, loadout):
                    bonus = sticker_rule_int(level, rule)
            elif word_mode == "per_shop_restock":
                bonus = sticker_rule_int(level, rule) * shop_restock_count(loadout)
            elif word_mode == "colourless_word_flat":
                if word_all_colourless_on_path(board, path):
                    bonus = sticker_rule_int(level, rule)
            elif word_mode == "colourless_word_per_coloured_on_grid":
                if word_all_colourless_on_path(board, path):
                    bonus = sticker_rule_int(level, rule) * coloured_tile_count_on_grid(
                        board
                    )
            else:
                bonus = sticker_rule_int(level, rule) if "base" in rule else value
            if bonus:
                _add_word_score(state, bonus)
                if word_mode != "birthday_cake_bonus":
                    state["effects"].append(f"+{bonus} word score ({word_mode})")

        elif effect_type == "consecutive_number_tile_bonus":
            bonus_each = sticker_rule_int(level, rule)
            positions = consecutive_number_run_path_positions(path, board)
            if positions and bonus_each:
                for pos in positions:
                    state["tile_scores"][pos] += bonus_each
                state["effects"].append(
                    f"+{bonus_each * len(positions)} consecutive number tile ({len(positions)})"
                )

        elif effect_type == "multiply_word_scaled":
            condition = rule.get("condition", "")
            cond_explanation = ""
            if not condition:
                met = True
                cond_explanation = "applied: no condition"
            elif condition == "word_base_negative":
                met = state["base_score"] < 0
                cond_explanation = (
                    "applied: negative base"
                    if met
                    else "skipped: base score not negative"
                )
            elif condition == "word_base_eq_target":
                met = state["base_score"] == target_score_from_loadout(loadout)
                cond_explanation = (
                    "applied: base equals target"
                    if met
                    else "skipped: base score not equal to target"
                )
            else:
                met, cond_explanation = explain_sticker_condition(
                    condition,
                    board,
                    path,
                    state["word"],
                    loadout,
                    applying_sticker_id=applying_sticker_id,
                )
            rule_trace_context = {
                "condition": condition,
                "condition_met": met,
                "condition_explanation": cond_explanation,
            }
            if condition == "word_starts_vwxyz":
                rule_trace_context["word_first_letter"] = word_first_letter(
                    state["word"]
                )
                rule_trace_context["path_first_letter"] = first_letter_on_path(
                    board, path
                )
            if not met:
                rule_trace_context["skip_reason"] = cond_explanation
            if met:
                factor = scaled_word_multiplier(level, rule, loadout, path=path)
                label = condition or rule.get("scale_from_extras", "scaled")
                rid = (rule_id or applying_sticker_id or "").lower()
                salamander = _boss_is_salamander(loadout)
                if (
                    rid == "yellow_glasses"
                    and state["word_score"] > 0
                    and level >= 3
                    and not salamander
                    and not word_starts_ends_different_suit(board, path)
                    and chess_takes_on_path(board, path) < 2
                ):
                    _queue_word_multiplier(
                        state, factor, rule_id, defer_finalize=True
                    )
                    state["effects"].append(f"×{factor} word ({label})")
                elif (
                    rid == "yellow_glasses"
                    and state["word_score"] > 0
                    and level >= 3
                    and salamander
                ):
                    state["salamander_post_mutating_mults"].append(
                        (factor, rule_id)
                    )
                    state["effects"].append(f"×{factor} word ({label})")
                elif (
                    rid == "wrestlers"
                    and state["word_score"] > 0
                    and salamander
                    and word_starts_ends_different_suit(board, path)
                ):
                    state["salamander_post_mutating_mults"].append(
                        (factor, rule_id)
                    )
                    state["effects"].append(f"×{factor} word ({label})")
                elif (
                    rid == "wrestlers"
                    and state["word_score"] > 0
                    and salamander
                ):
                    bonus = int(100 * factor)
                    _add_word_score(state, bonus)
                    state["multiplier"] *= factor
                    state["effects"].append(f"+{bonus} word ({label})")
                else:
                    _queue_word_multiplier(state, factor, rule_id)
                    state["effects"].append(f"×{factor} word ({label})")

        elif effect_type == "tile_multiply_by_letter_count":
            counts = letter_counts_on_path(board, path)
            applied = 0
            for i, idx in enumerate(path):
                ch = (board.get_by_index(idx).letter or "").strip().lower()
                mult = counts.get(ch, 1)
                if mult > 1:
                    state["tile_scores"][i] *= mult
                    applied += 1
            if applied:
                state["effects"].append(
                    f"×letter-count tile score ({applied} tile(s))"
                )

        elif effect_type == "multiply_word_by_high_letter_count":
            min_count = int(rule.get("min_letter_count", 3))
            factor = max_qualifying_letter_half_multiplier(board, path, min_count)
            if factor > 1.0:
                _queue_word_multiplier(state, factor, rule_id)
                state["effects"].append(f"×{factor} word (letter count ≥{min_count})")

        elif effect_type == "multiply_word_by_longest_red_run":
            run = longest_red_run_on_path(board, path)
            if run >= 1:
                factor = float(run)
                _queue_word_multiplier(state, factor, rule_id)
                state["effects"].append(f"×{factor} word (RED run {run})")

        elif effect_type == "multiply_word_per_path_tile":
            per_tile = float(rule.get("factor", -1.1))
            if path:
                factor = per_tile ** len(path)
                _queue_word_multiplier(state, factor, rule_id)
                state["effects"].append(
                    f"×{factor} word ({len(path)} tile(s) @ {per_tile})"
                )

        elif effect_type == "multiply_word_by_unique_colour_count":
            n = unique_colour_count_on_path(board, path)
            if n >= 1:
                factor = float(n)
                _queue_word_multiplier(state, factor, rule_id)
                state["effects"].append(
                    f"×{factor} word ({n} unique colour(s))"
                )

        elif effect_type == "multiply_word_by_unique_curse_type_count":
            n = unique_curse_type_count_on_path(board, path)
            if n >= 1:
                factor = float(n)
                _queue_word_multiplier(state, factor, rule_id)
                state["effects"].append(
                    f"×{factor} word ({n} unique curse type(s))"
                )

        elif effect_type == "multiply_word_by_number_count":
            if word_all_numbers_on_path(board, path):
                n = number_tile_count_on_path(board, path)
                if n >= 1:
                    factor = float(n)
                    _queue_word_multiplier(state, factor, rule_id)
                    state["effects"].append(
                        f"×{factor} word ({n} number tile(s))"
                    )

        elif effect_type == "use_base_score_tiles":
            # Microscope applies at init (_init_tile_contribution); stamp pass is a no-op
            # so later sticker tile bonuses (e.g. Artist's Palette) are preserved.
            pass

        elif effect_type == "multiply_word_per_distinct_pair":
            pairs = distinct_pair_count_on_path(board, path)
            if pairs:
                rate = scaled_word_multiplier(level, rule)
                for _ in range(pairs):
                    _queue_word_multiplier(state, rate, rule_id)
                state["effects"].append(
                    f"×{rate}^{pairs} word ({pairs} distinct pair(s))"
                )

        elif effect_type == "multiply_money_bonus":
            factor = money_word_multiplier(
                level, rule, money_for_scoring(board, path, loadout)
            )
            if factor != 1.0:
                _queue_word_multiplier(state, factor, rule_id)
                state["effects"].append(f"×{factor} word (money bonus)")

        elif effect_type == "multiply_consumable_rack":
            factor = consumable_rack_multiplier(level, rule, loadout)
            if factor != 1.0:
                _queue_word_multiplier(state, factor, rule_id)
                state["effects"].append(f"×{factor} word (consumable rack)")

        elif effect_type == "multiply_word_other_sticker_levels":
            factor = burrito_word_multiplier(level, rule, loadout)
            if factor != 1.0:
                _queue_word_multiplier(state, factor, rule_id)
                state["effects"].append(f"×{factor} word (other sticker levels)")

        elif effect_type == "red_encounter_tile_bonus":
            reds_used = red_tiles_used_encounter(loadout)
            per_red = level
            if reds_used and per_red:
                count = 0
                for i, idx in enumerate(path):
                    if board.get_by_index(idx).color.value == "red":
                        add = per_red * reds_used
                        state["tile_scores"][i] += add
                        count += 1
                if count:
                    state["effects"].append(
                        f"+{per_red * reds_used} per red tile ({count}, encounter reds={reds_used})"
                    )

        elif effect_type == "multiply":
            condition = rule.get("condition", "")
            if condition:
                met, cond_explanation = explain_sticker_condition(
                    condition,
                    board,
                    path,
                    state["word"],
                    loadout,
                    applying_sticker_id=applying_sticker_id,
                )
                rule_trace_context = {
                    "condition": condition,
                    "condition_met": met,
                    "condition_explanation": cond_explanation,
                }
                if not met:
                    rule_trace_context["skip_reason"] = cond_explanation
            else:
                met = True
            if not condition or met:
                factor = float(rule.get("factor", 1.0))
                mushy = (loadout.extras or {}).get("avocado_mushy")
                if mushy in (True, "true", "True", "1", 1):
                    factor = -2.0
                if level > 1 and factor > 0:
                    factor = factor**level
                _queue_word_multiplier(state, factor, rule_id)
                state["effects"].append(f"×{factor} multiplier")

        elif effect_type == "red_tile_bonus":

            for i, idx in enumerate(path):

                if board.get_by_index(idx).color.value == "red":

                    state["tile_scores"][i] += value

            red_count = sum(

                1 for i in path if board.get_by_index(i).color.value == "red"

            )

            if red_count:

                state["effects"].append(f"+{value} per red tile ({red_count})")

        elif effect_type == "unique_colour_word_bonus":

            per_colour = rainbow_per_colour_bonus(loadout, rule)

            colours = unique_colours_on_path(board, path)

            if colours:

                bonus = per_colour * len(colours)

                _add_word_score(state, bonus)

                state["effects"].append(

                    f"+{bonus} word ({len(colours)} unique colour(s))"

                )

        elif effect_type == "chess_take_word_bonus":
            strict_takes = chess_take_strict_mode(
                board,
                path,
                strict_requested=rule.get("strict_takes", False),
            )
            mode = rule.get("mode", "flat")
            if mode == "piece_value_first_n":
                n = sticker_rule_int(level, rule)
                bonus = first_n_movie_camera_piece_value_sum(
                    board,
                    path,
                    n,
                    strict=strict_takes,
                    loadout=loadout,
                )
                if not bonus and level >= 3 and chess_takes_on_path(
                    board, path, strict=strict_takes
                ) == 0:
                    bonus = n * n
                if bonus:
                    _add_word_score(state, bonus)
                    state["effects"].append(
                        f"+{bonus} word (first {n} take piece value)"
                    )
            else:
                per_take = super_8_take_word_bonus(loadout, rule)
                takes = chess_takes_on_path(board, path, strict=strict_takes)
                if takes:
                    bonus = per_take * takes
                    _add_word_score(state, bonus)
                    state["effects"].append(f"+{bonus} word ({takes} take(s))")

        elif effect_type == "card_hand_word_bonus":
            hand = rule.get("hand", "")
            if not detect_card_hand(hand, board, path, loadout):
                pass
            elif rule.get("word_mode") == "per_unused_card" and hand == "pair":
                n_unused = unused_cards_on_board(board, path)
                per = sticker_rule_int(level, rule)
                if n_unused and per:
                    bonus = per * n_unused
                    _add_word_score(state, bonus)
                    state["effects"].append(
                        f"+{bonus} word (pair, {n_unused} unused card(s))"
                    )
            else:
                bonus = sticker_rule_int(level, rule)
                if bonus:
                    _add_word_score(state, bonus)
                    state["effects"].append(f"+{bonus} word ({hand})")

        elif effect_type == "add_money_on_hand":
            hand = rule.get("hand", "")
            if detect_card_hand(hand, board, path, loadout):
                amount = sticker_rule_int(level, rule)
                if amount:
                    state["money_bonus"] = state.get("money_bonus", 0) + amount
                    state["effects"].append(f"+${amount} ({hand})")

        elif effect_type == "add_money_on_condition":
            condition = rule.get("condition", "")
            if evaluate_sticker_condition(
                condition, board, path, state["word"], loadout
            ):
                amount_mode = rule.get("amount_mode", "")
                if amount_mode == "currency_value_on_path":
                    amount = currency_value_on_path(board, path)
                elif amount_mode == "chess_piece_count_on_path":
                    amount = chess_piece_count_on_path(board, path)
                else:
                    amount = sticker_rule_int(level, rule)
                if amount:
                    state["money_bonus"] = state.get("money_bonus", 0) + amount
                    state["effects"].append(f"+${amount} ({condition})")

        elif effect_type == "cards_submitted_word_bonus":
            bonus = bicycle_word_bonus(board, path, loadout, rule)
            if bonus:
                suited = effective_suited_cards_on_path(board, path, loadout)
                per_card = bicycle_word_per_card(loadout, rule)
                acc = bicycle_word_score_accumulator_for_submit(
                    loadout, board, path, rule
                )
                _add_word_score(state, bonus)
                if suited:
                    state["effects"].append(
                        f"+{bonus} word (Bicycle: {acc} acc + {suited} suited × {per_card})"
                    )
                else:
                    state["effects"].append(f"+{bonus} word (Bicycle: {acc} accumulated)")

        elif effect_type == "void_flip":

            for i, idx in enumerate(path):

                t = board.get_by_index(idx)

                if t.color.value == "void":

                    from cursed_words_solver.rules.base_scoring import (
                        _void_face_value,
                    )

                    flip = abs(t.base_score) * 2
                    if t.base_score == 0:
                        flip = float(_void_face_value(t)) * 2

                    state["tile_scores"][i] += flip

                    state["effects"].append("void flip")

        elif effect_type == "word_length_bonus":

            if len(state["word"]) >= rule.get("min_length", 4):

                _add_word_score(state, value)

                state["effects"].append(f"+{value} long word")

        elif effect_type == "shiny_chain":

            shiny = sum(

                1

                for i in path

                if board.get_by_index(i).color.value == "shiny"

            )

            if shiny >= 2:

                bonus = value * (shiny - 1)

                _add_word_score(state, bonus)

                state["effects"].append(f"+{bonus} shiny chain")

        elif effect_type == "mutating_dna_tile_bonus":
            wrestlers_factor = 1.0
            if word_starts_ends_different_suit(board, path):
                for item in loadout.stickers:
                    if (item.id or "").lower() == "wrestlers":
                        _wkey, wrule = get_rule(
                            self.rules,
                            "stickers",
                            item.id,
                            item.name or "",
                        )
                        if wrule:
                            wrestlers_factor = scaled_word_multiplier(
                                item.level, wrule, loadout, path=path
                            )
                        break
            tile_bonus, word_bonus = apply_mutating_dna_bonus(
                board,
                path,
                state["tile_scores"],
                loadout,
                word_score=float(state["word_score"]),
                wrestlers_factor=wrestlers_factor,
            )
            if word_bonus:
                _add_word_score(state, word_bonus)
            if tile_bonus:
                state["effects"].append(f"+{int(tile_bonus)} mutating DNA tile")
            if word_bonus:
                state["effects"].append(f"+{int(word_bonus)} mutating DNA word")

        elif effect_type == "boss_zero_vowel":

            vowels = set("aeiou")

            if any(c in vowels for c in state["word"].lower()):

                state["multiplier"] = 0

                state["effects"].append("boss: no vowels")

        elif effect_type == "boss_tile_penalty":
            ctx = boss_context(loadout, self.rules)
            penalty = resolve_boss_scaling(rule, ctx.area, ctx.cursed)
            if penalty is not None:
                p = int(penalty)
                for i in range(len(state["tile_scores"])):
                    state["tile_scores"][i] -= p
                state["effects"].append(f"-{p} per tile (boss)")

        elif effect_type == "boss_subtract_word_score_money":
            ctx = boss_context(loadout, self.rules)
            mult = resolve_boss_scaling(
                rule, ctx.area, ctx.cursed, field="multiplier"
            )
            if mult is not None:
                sub = int(mult * loadout.money)
                state["word_score"] -= sub
                state["effects"].append(f"-{sub} word score (boss × money)")

        elif effect_type == "boss_steal_money":
            from cursed_words_solver.rules.boss_scoring import apply_boss_steal_money

            ctx = boss_context(loadout, self.rules)
            apply_boss_steal_money(state, loadout, rule, ctx)

        elif effect_type in ("boss_word_min_length", "boss_word_max_length"):
            pass

        if trace_before is not None:
            _trace_rule_step(
                state,
                rule_id=rule_id,
                effect_type=effect_type,
                before=trace_before,
                effects_before=effects_before,
                rule=rule,
                trace_context=rule_trace_context,
            )
        return state


