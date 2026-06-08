"""Full scoring pipeline: tile init -> pin -> stickers L→R -> stamps L→R -> boss -> finalize."""



from __future__ import annotations



import json
import math

from pathlib import Path

from typing import TYPE_CHECKING, Any



from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor

from cursed_words_solver.rules.base_scoring import (
    _scrabble_value,
    microscope_init_contribution,
    tile_base_contribution,
)

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
    slugify_name,
)
from cursed_words_solver.rules.scoring_order import (
    apply_green_tile_word_transfer,
    path_grid_item_refs,
    sort_grid_path_refs,
    tile_sum_excluding_green,
)
from cursed_words_solver.rules.tile_scoring import apply_tile_init
from cursed_words_solver.rules.stamp_behaviors import loadout_has_stamp
from cursed_words_solver.solve_context import SolveContext, build_solve_context

if TYPE_CHECKING:
    from cursed_words_solver.board_scoring_context import BoardScoringContext
from cursed_words_solver.graph_bitboard import BoardGraphContext

from cursed_words_solver.rules.boss_effects import (
    boss_context,
    boss_rule_applies,
    boss_scoring_effect_type,
    get_active_boss_rule,
    get_active_boss_rules,
    resolve_boss_scaling,
    resolve_boss_scaling_for_rule,
)
from cursed_words_solver.rules.boss_scoring import (
    EARLY_BOSS_TYPES,
    apply_early_boss_scoring,
    apply_hourglass_boss_scoring,
)

# Wiki Scoring step 1: Salamander / Robo-Monkey before pin, stickers, stamps.
_EARLY_BOSS_EFFECT_TYPES = EARLY_BOSS_TYPES
from cursed_words_solver.rules.scoring_conditions import (
    abacus_colored_number_bonus,
    birthday_cake_accumulated,
    birthday_cake_improve_for_path,
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
    super_8_uses_melmod_take_metadata,
    movie_camera_accumulated,
    movie_camera_encounter_word_bonus,
    movie_camera_improve_for_path,
    telescope_running_red_count,
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
    hanafuda_hand_satisfied,
    hanafuda_x_required,
    unused_cards_on_board,
    is_colored_number_tile,
    is_number_like_tile,
    NON_COLOUR_FOR_NUMBER_BONUS,
    is_consumable_tile,
    is_placed_consumable_tile,
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
    neapolitan_base_percent_from_loadout,
    neapolitan_has_live_percent,
    scaled_word_multiplier,
    word_percent_bonus_from_multiplier,
    sticker_rule_int,
    super_8_take_word_bonus,
    tile_matches_target,
    unique_colour_count_on_path,
    unique_curse_type_count_on_path,
    unique_colours_on_path,
    unique_vowels_on_path,
    unused_red_tiles_on_board,
    void_tiles_letter_not_in_word,
    dusty_coffin_void_units,
    word_same_start_end_letter,
    word_same_start_end_on_path,
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
    loadout: Loadout | None = None,
    microscope_base: bool = False,
    blue_base_override: int | None = None,
) -> float:
    """Per-tile score at init; Microscope uses packet base_score instead of color bonuses."""
    if tile.curse == CurseType.ITEM:
        return 0.0
    if microscope_base:
        return microscope_init_contribution(tile, money, loadout)
    if tile.color == TileColor.BLUE and blue_base_override is not None:
        return float(blue_base_override)
    return float(tile_base_contribution(tile, money, loadout))


def _init_state(
    board: Board,
    path: list[int],
    word: str,
    *,
    loadout: Loadout | None = None,
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
            loadout=loadout,
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
        "pending_word_percent_bonuses": [],
        "pending_word_finalize_steps": [],

        "salamander_post_mutating_mults": [],

    }


def _void_number_on_path(tile: Tile) -> bool:
    """Built-in void path bonuses apply to void-cursed NUMBER tiles only (not void letters)."""
    return tile.color == TileColor.VOID and tile.curse == CurseType.NUMBER


def _apply_void_path_bonuses(
    board: Board, path: list[int], loadout: Loadout, state: dict[str, Any]
) -> None:
    """Built-in void path bonus: +2 TILE SCORE on a letter (Scrabble value ≥ 8) immediately before a void NUMBER.

    In-game, the bonus does not apply when that void number is immediately followed by another
    void number on the path (consecutive void-number run).
    """
    bonus = 2
    before_void = 0
    before_void_bonus_total = 0
    for i in range(len(path) - 1):
        next_tile = board.get_by_index(path[i + 1])
        if not _void_number_on_path(next_tile):
            continue
        if i + 2 < len(path) and _void_number_on_path(board.get_by_index(path[i + 2])):
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


def _apply_immediate_word_percent(
    state: dict[str, Any], percent: int, rule_id: str = ""
) -> None:
    """Apply multiplicative WordBonus percent to current tile+word subtotal (game order)."""
    if percent == 0:
        return
    factor = float(percent) / 100.0
    if factor == 1.0:
        return
    tile_sum = sum(state["tile_scores"])
    subtotal = tile_sum + state["word_score"]
    new_total = math.floor(subtotal * factor)
    state["word_score"] = new_total - tile_sum
    if factor != 1.0:
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
    if (
        state.get("_immediate_word_mult")
        and not defer_finalize
        and not state.get("_defer_word_mults_for_compound")
    ):
        _apply_immediate_word_multiplier(state, factor, rule_id)
        return
    state["pending_word_multipliers"].append((factor, rule_id))
    state["pending_word_finalize_steps"].append(("mult", factor, rule_id))
    state["multiplier"] *= factor


def _queue_word_percent_bonus(
    state: dict[str, Any],
    percent: int,
    rule_id: str = "",
    *,
    wiki_factor: float | None = None,
    defer_finalize: bool = False,
) -> None:
    """Queue multiplicative WordBonus token (game: multiply total by percent/100).

    Example: wiki ×1.5 => percent 150; wiki ×4 => percent 400.
    """
    # Allow negative percents for "negative multiplier" stickers (e.g. Avocado mushy).
    if percent == 0:
        return
    if (
        state.get("_immediate_word_percent")
        and not defer_finalize
        and not state.get("_defer_word_mults_for_compound")
    ):
        _apply_immediate_word_percent(state, int(percent), rule_id)
        return
    state["pending_word_percent_bonuses"].append((int(percent), rule_id))
    state["pending_word_finalize_steps"].append(("percent", int(percent), rule_id))
    if wiki_factor is not None and wiki_factor != 1.0:
        state["multiplier"] *= wiki_factor


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
    if state.get("pending_word_finalize_steps"):
        state["_additive_word_after_pending_percent"] = True
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
        len(state.get("pending_word_finalize_steps", [])),
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


def _has_mutating_dna_stamp(loadout: Loadout) -> bool:
    return any(
        "mutating" in (stamp.id or "").lower()
        or "dna" in (stamp.id or "").lower()
        or "mutating" in (stamp.name or "").lower()
        for stamp in loadout.stamps
    )


def _salamander_defer_multiply_for_mutating(loadout: Loadout) -> bool:
    """Defer ×WORD until after Mutating DNA only when that stamp can still fire."""
    if not _boss_is_salamander(loadout) or not _has_mutating_dna_stamp(loadout):
        return False
    prior = sum(mutating_dna_letter_counts_from_loadout(loadout).values())
    return 0 < prior < 8


def _apply_pending_word_finalize_steps(
    state: dict[str, Any],
    subtotal: float,
    *,
    trace: list[dict[str, Any]] | None = None,
    steps: list[tuple] | None = None,
    multiply_tile_sum_only: bool = False,
    multiply_word_score_only: bool = False,
) -> float:
    """GetScoreFromScoreCalcInfo: apply queued WordBonus steps in sticker order."""
    entries = steps if steps is not None else state.get("pending_word_finalize_steps", [])
    if not entries:
        return subtotal
    if state.get("_wad_deferred_grid_word_mult"):
        total = float(subtotal)
        for kind, value, rule_id in entries:
            if kind == "percent":
                percent = int(value)
                factor = float(percent) / 100.0
                total = math.floor(float(total) * percent / 100.0)
                if trace is not None:
                    fields: dict[str, Any] = {
                        "factor": factor,
                        "percent": percent,
                        "detail": f"×{factor:g} word (word_bonus:{percent})",
                    }
                    if rule_id:
                        fields["rule_id"] = rule_id
                    _trace_step(state, "multiply", **fields)
            else:
                factor = float(value)
                if factor == 1.0:
                    continue
                total = math.floor(total * factor)
                if trace is not None:
                    fields = {
                        "factor": factor,
                        "detail": f"×{factor} word (floor)",
                    }
                    if rule_id:
                        fields["rule_id"] = rule_id
                    _trace_step(state, "multiply", **fields)
        return total
    green_word_track = bool(state.get("_green_transferred"))
    if multiply_tile_sum_only:
        # Queued ×WORD from RAM/grid runs before +WORD SCORE additives in game order;
        # at final finalize, multipliers apply to tile sum only, then word_score is added.
        # After wiki step 6, GREEN lives in word_score and must receive step-7 ×WORD too.
        if green_word_track:
            total = float(subtotal)
            word_part = None
        else:
            tile_sum = float(sum(state["tile_scores"]))
            word_part = float(state["word_score"])
            total = tile_sum
    elif multiply_word_score_only:
        total = float(state["word_score"])
    else:
        total = float(subtotal)
    for kind, value, rule_id in entries:
        if kind == "percent":
            percent = int(value)
            factor = float(percent) / 100.0
            total = math.floor(float(total) * percent / 100.0)
            if trace is not None:
                fields: dict[str, Any] = {
                    "factor": float(factor),
                    "percent": percent,
                    "detail": f"×{factor:g} word (word_bonus:{percent})",
                }
                if rule_id:
                    fields["rule_id"] = rule_id
                _trace_step(state, "multiply", **fields)
        else:
            factor = float(value)
            if factor == 1.0:
                continue
            total = math.floor(total * factor)
            if trace is not None:
                fields: dict[str, Any] = {
                    "factor": factor,
                    "detail": f"×{factor} word (floor)",
                }
                if rule_id:
                    fields["rule_id"] = rule_id
                _trace_step(state, "multiply", **fields)
    if multiply_tile_sum_only:
        if word_part is not None:
            return total + word_part
        return total
    return total


def _parse_percent_list(raw: str) -> list[int] | None:
    percents: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except (TypeError, ValueError):
            return None
        if value > 0:
            percents.append(value)
    return percents or None


def _compound_word_percents_from_loadout(loadout: Loadout | None) -> list[int] | None:
    if loadout is None:
        return None
    raw = str((loadout.extras or {}).get("compound_word_percents_on_tile_sum", "")).strip()
    if not raw:
        return None
    return _parse_percent_list(raw)


def _compound_pre_post_percents(
    loadout: Loadout | None,
) -> tuple[list[int] | None, list[int] | None]:
    """Split stacked WordBonus: pre-cocktail on tile sum, post-cocktail after tile ×N."""
    if loadout is None:
        return None, None
    extras = loadout.extras or {}
    pre_raw = str(extras.get("compound_pre_cocktail_percents", "")).strip()
    post_raw = str(extras.get("compound_post_cocktail_percents", "")).strip()
    if pre_raw or post_raw:
        return _parse_percent_list(pre_raw), _parse_percent_list(post_raw)
    return None, None


def _apply_compound_word_percents_on_tile_sum(
    state: dict[str, Any],
    percents: list[int],
    *,
    trace: list[dict[str, Any]] | None = None,
    board: Board | None = None,
    path: list[int] | None = None,
) -> None:
    """Apply stacked WordBonus percents on tile sum only (down_under snapshot session)."""
    if board is not None and path is not None:
        tile_sum = int(tile_sum_excluding_green(board, path, state))
    else:
        tile_sum = int(sum(state["tile_scores"]))
    total = float(tile_sum)
    for percent in percents:
        total = int(total * int(percent) / 100.0)
        if trace is not None:
            factor = float(percent) / 100.0
            _trace_step(
                state,
                "multiply",
                factor=factor,
                percent=int(percent),
                detail=f"×{factor:g} word (compound on tile sum)",
            )
    state["word_score"] = float(total - tile_sum)
    state["pending_word_finalize_steps"] = []
    state["pending_word_percent_bonuses"] = []
    state["pending_word_multipliers"] = []
    state["_compound_word_percents_applied"] = True


def _apply_compound_post_cocktail_finalize(
    state: dict[str, Any], loadout: Loadout | None
) -> None:
    if loadout is None or state.get("_compound_post_cocktail_applied"):
        return
    _pre, post = _compound_pre_post_percents(loadout)
    if not post:
        return
    trace = state.get("_trace")
    subtotal = float(sum(state["tile_scores"]) + state["word_score"])
    total = subtotal
    for percent in post:
        total = math.floor(total * int(percent) / 100.0)
        if trace is not None:
            factor = float(percent) / 100.0
            _trace_step(
                state,
                "multiply",
                factor=factor,
                percent=int(percent),
                detail=f"×{factor:g} word (post-cocktail compound)",
            )
    tile_sum = float(sum(state["tile_scores"]))
    state["word_score"] = float(total - tile_sum)
    state["pending_word_finalize_steps"] = []
    state["_compound_post_cocktail_applied"] = True
    state["_compound_word_percents_applied"] = True


def _flush_pending_word_mults(state: dict[str, Any]) -> None:
    """Apply queued ×WORD on current subtotal (path scatter + pin), then clear queue."""
    if not state.get("pending_word_finalize_steps"):
        return
    tile_sum = sum(state["tile_scores"])
    subtotal = tile_sum + state["word_score"]
    trace = state.get("_trace")
    new_total = _apply_pending_word_finalize_steps(
        state, subtotal, trace=trace if trace is not None else None
    )
    state["word_score"] = new_total - tile_sum
    state["pending_word_finalize_steps"] = []
    state["pending_word_percent_bonuses"] = []
    state["pending_word_multipliers"] = []


def _flush_pending_through_rule(state: dict[str, Any], through_rule_id: str) -> None:
    """Apply queued ×WORD through ``through_rule_id`` (inclusive), keep the rest pending."""
    steps = state.get("pending_word_finalize_steps")
    if not steps:
        return
    target = str(through_rule_id or "").strip().lower()
    if not target:
        return
    cut = -1
    for i, step in enumerate(steps):
        if not isinstance(step, tuple) or len(step) < 3:
            continue
        rid = str(step[2] or "").strip().lower()
        if rid == target:
            cut = i
            break
    if cut < 0:
        return
    apply_steps = steps[: cut + 1]
    keep_steps = steps[cut + 1 :]
    if not apply_steps:
        return
    tile_sum = sum(state["tile_scores"])
    subtotal = tile_sum + state["word_score"]
    trace = state.get("_trace")
    new_total = _apply_pending_word_finalize_steps(
        state, subtotal, trace=trace if trace is not None else None, steps=apply_steps
    )
    state["word_score"] = new_total - tile_sum
    state["pending_word_finalize_steps"] = keep_steps
    state["pending_word_percent_bonuses"] = [
        entry
        for entry in state.get("pending_word_percent_bonuses", [])
        if isinstance(entry, tuple)
        and len(entry) >= 2
        and str(entry[1] or "").strip().lower() not in {
            str(s[2] or "").strip().lower()
            for s in apply_steps
            if isinstance(s, tuple) and len(s) >= 3
        }
    ]
    state["pending_word_multipliers"] = [
        entry
        for entry in state.get("pending_word_multipliers", [])
        if isinstance(entry, tuple)
        and len(entry) >= 2
        and str(entry[1] or "").strip().lower() not in {
            str(s[2] or "").strip().lower()
            for s in apply_steps
            if isinstance(s, tuple) and len(s) >= 3
        }
    ]


def _strip_sunflower_from_pending(state: dict[str, Any]) -> None:
    """Remove Sunflower from queued ×WORD (applied post-Cocktail instead)."""
    skip = frozenset({"sunflower"})

    def _keep(step: object) -> bool:
        if not isinstance(step, tuple) or len(step) < 3:
            return True
        return str(step[2] or "").strip().lower() not in skip

    state["pending_word_finalize_steps"] = [
        s for s in state.get("pending_word_finalize_steps", []) if _keep(s)
    ]
    state["pending_word_percent_bonuses"] = [
        s for s in state.get("pending_word_percent_bonuses", []) if _keep(s)
    ]
    state["pending_word_multipliers"] = [
        s for s in state.get("pending_word_multipliers", []) if _keep(s)
    ]


def _pending_compound_percents_from_state(
    state: dict[str, Any], loadout: Loadout | None
) -> list[int] | None:
    """Build compound ×WORD list from pending queue (skip Dango if flushed at grid)."""
    steps = state.get("pending_word_finalize_steps")
    if not steps:
        return None
    percents: list[int] = []
    for step in steps:
        if not isinstance(step, tuple) or len(step) < 3:
            continue
        kind, value, rule_id = step[0], step[1], step[2]
        if kind != "percent":
            continue
        rid = str(rule_id or "").strip().lower()
        if rid == "dango" and state.get("_grid_dango_word_flushed"):
            continue
        try:
            percents.append(int(value))
        except (TypeError, ValueError):
            continue
    return percents or None


def _apply_snapshot_phased_word_finalize(
    state: dict[str, Any], loadout: Loadout | None
) -> None:
    """Apply queued ×WORD on final tile sum (Nat-H4 Snapshot sessions)."""
    from cursed_words_solver.rules.scoring_conditions import (
        snapshot_phased_word_scoring,
    )

    if state.get("_snapshot_phased_finalize_applied") or not snapshot_phased_word_scoring(
        loadout
    ):
        return
    steps = state.get("pending_word_finalize_steps")
    if not steps:
        return
    extras = (loadout.extras or {}) if loadout is not None else {}
    if str(extras.get("defer_post_cocktail_sunflower", "")).lower() in (
        "1",
        "true",
        "yes",
    ):
        steps = [
            s
            for s in steps
            if not (
                isinstance(s, tuple)
                and len(s) >= 3
                and str(s[2] or "").strip().lower() == "sunflower"
            )
        ]
    trace = state.get("_trace")
    tile_sum = int(sum(state["tile_scores"]))
    word_add = int(round(state.get("word_score", 0)))
    state["word_score"] = 0.0
    # Grid word additives (e.g. Dusty Coffin) and Snapshot copy are already in
    # word_score; apply queued ×WORD percents on tile + word together.
    total = tile_sum + word_add
    word_add = 0
    add_after_percents = 0
    percent_seen = 0
    for step in steps:
        if not isinstance(step, tuple) or len(step) < 3:
            continue
        kind, value, _rule_id = step[0], step[1], step[2]
        if kind == "percent":
            total = int(math.floor(float(total) * int(value) / 100.0))
            percent_seen += 1
            if percent_seen == add_after_percents and word_add:
                total += word_add
                word_add = 0
            if trace is not None:
                factor = float(value) / 100.0
                _trace_step(
                    state,
                    "multiply",
                    factor=factor,
                    percent=int(value),
                    rule_id=str(_rule_id or ""),
                    detail=f"×{factor:g} word (snapshot-phased tile sum)",
                )
        elif kind == "multiply":
            total = int(math.floor(total * float(value)))
            if trace is not None:
                _trace_step(
                    state,
                    "multiply",
                    factor=float(value),
                    rule_id=str(_rule_id or ""),
                    detail=f"×{value:g} word (snapshot-phased tile sum)",
                )
    if word_add:
        total += word_add
        if trace is not None:
            _trace_step(
                state,
                "add",
                detail=f"+{word_add} word (snapshot-phased additive)",
            )
    state["word_score"] = float(total - tile_sum)
    state["pending_word_finalize_steps"] = []
    state["pending_word_percent_bonuses"] = []
    state["pending_word_multipliers"] = []
    state["_snapshot_phased_finalize_applied"] = True


def _build_tombstone_compound_percents(
    state: dict[str, Any],
    loadout: Loadout,
    board: Board,
    path: list[int],
    rules: dict[str, Any],
) -> list[int] | None:
    """Sunflower + Burrito + Steak + Neo stacked on post-Cocktail tile sum."""
    from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name
    from cursed_words_solver.rules.scoring_conditions import (
        burrito_word_multiplier,
        post_cocktail_sunflower_percent,
        tombstone_heavy_grid_compound_session,
        word_percent_bonus_from_multiplier,
    )

    if not tombstone_heavy_grid_compound_session(loadout, board):
        return None
    percents: list[int] = []
    sun = post_cocktail_sunflower_percent(
        loadout, board, path, state=state, rules=rules
    )
    if sun is not None:
        percents.append(int(sun))
    burrito_level = 1
    for sticker in loadout.stickers:
        if slugify_name(sticker.id or sticker.name) == "burrito":
            burrito_level = max(1, int(sticker.level))
            break
    _key, burrito_rule = get_rule(rules, "stickers", "burrito", "burrito")
    if burrito_rule:
        factor = burrito_word_multiplier(
            burrito_level,
            burrito_rule,
            loadout,
            board=board,
            path=path,
            rules=rules,
        )
        if factor != 1.0:
            percents.append(
                word_percent_bonus_from_multiplier(
                    factor, burrito_rule, level=burrito_level
                )
            )
    extras = loadout.extras or {}
    raw_steak = extras.get("steak_word_bonus_percent")
    if raw_steak not in (None, ""):
        try:
            percents.append(int(raw_steak))
        except (TypeError, ValueError):
            pass
    else:
        for step in state.get("pending_word_finalize_steps", []):
            if (
                isinstance(step, tuple)
                and len(step) >= 3
                and step[0] == "percent"
                and str(step[2] or "").strip().lower() == "steak"
            ):
                percents.append(int(step[1]))
                break
    raw_neo = extras.get("neapolitan_percent")
    if raw_neo not in (None, ""):
        try:
            percents.append(int(raw_neo))
        except (TypeError, ValueError):
            pass
    else:
        for step in state.get("pending_word_finalize_steps", []):
            if (
                isinstance(step, tuple)
                and len(step) >= 3
                and step[0] == "percent"
                and str(step[2] or "").strip().lower() == "neapolitan"
            ):
                percents.append(int(step[1]))
                break
    return percents or None


def _apply_compound_word_finalize_after_stickers(
    state: dict[str, Any],
    loadout: Loadout,
    board: Board,
    path: list[int],
    rules: dict[str, Any],
) -> None:
    """Stack queued ×WORD on tile sum after all equipped sticker passes (down_under sessions)."""
    from cursed_words_solver.rules.scoring_conditions import (
        compound_word_finalize_at_cocktail,
    )

    if state.get("_compound_word_percents_applied"):
        return
    if not compound_word_finalize_at_cocktail(loadout, board):
        return
    compound = _compound_word_percents_from_loadout(loadout)
    if not compound:
        compound = _build_tombstone_compound_percents(
            state, loadout, board, path, rules
        )
    if not compound:
        compound = _pending_compound_percents_from_state(state, loadout)
    if not compound:
        return
    state["word_score"] = 0.0
    _apply_compound_word_percents_on_tile_sum(
        state,
        compound,
        trace=state.get("_trace"),
        board=board,
        path=path,
    )


def _apply_post_cocktail_word_percent_if_needed(
    state: dict[str, Any],
    loadout: Loadout | None,
    *,
    board: Board | None = None,
    path: list[int] | None = None,
    rules: dict[str, Any] | None = None,
) -> None:
    if state.get("_post_cocktail_applied") or loadout is None:
        return
    extras = loadout.extras or {}
    raw = str(extras.get("post_cocktail_word_percent", "")).strip()
    if not raw and str(extras.get("defer_post_cocktail_sunflower", "")).lower() in (
        "1",
        "true",
        "yes",
    ):
        if board is not None and path is not None and rules is not None:
            from cursed_words_solver.rules.scoring_conditions import (
                post_cocktail_sunflower_percent,
            )

            pct = post_cocktail_sunflower_percent(
                loadout,
                board,
                path,
                state=state,
                rules=rules,
            )
            if pct is not None:
                raw = str(pct)
    if not raw:
        return
    try:
        pct = int(raw)
    except (TypeError, ValueError):
        return
    if not pct:
        return
    # Floor combined subtotal so fractional word scores (e.g. after Burrito flush)
    # do not round up before Steak/Neapolitan.
    subtotal = int(math.floor(sum(state["tile_scores"]) + state["word_score"]))
    tile_sum = int(round(sum(state["tile_scores"])))
    # Values >= 1000 are per-mille (e.g. 1379 → ×1.379); 508×138//100 is 701, not 700.
    if pct >= 1000:
        new_total = (subtotal * pct) // 1000
    else:
        new_total = (subtotal * pct) // 100
    state["word_score"] = float(new_total - tile_sum)
    state["multiplier"] *= float(pct) / 100.0
    state["_post_cocktail_applied"] = True


def _finalize(
    state: dict[str, Any],
    board: Board | None = None,
    path: list[int] | None = None,
    loadout: Loadout | None = None,
    *,
    rules: dict[str, Any] | None = None,
) -> float:
    """Sum tile + word scores, apply queued WordBonus steps in sticker order."""
    if state.get("multiplier") == 0:
        return 0.0
    extras = (
        loadout.extras
        if loadout is not None and isinstance(loadout.extras, dict)
        else {}
    )
    has_compound_post = bool(
        str(extras.get("compound_post_cocktail_percents", "")).strip()
    )
    if state.get("_compound_word_percents_applied") and not has_compound_post:
        return float(sum(state["tile_scores"]) + state["word_score"])
    if board is not None and path is not None:
        apply_green_tile_word_transfer(
            board,
            path,
            state,
            trace_step=_trace_step if state.get("_trace") is not None else None,
        )
    _apply_post_cocktail_word_percent_if_needed(
        state, loadout, board=board, path=path, rules=rules
    )
    _apply_compound_post_cocktail_finalize(state, loadout)
    from cursed_words_solver.rules.scoring_conditions import (
        snapshot_dusty_interleaved_word_scoring,
        snapshot_phased_word_scoring,
    )

    dusty_interleaved = (
        snapshot_dusty_interleaved_word_scoring(loadout)
        and not str(extras.get("compound_word_percents_on_tile_sum", "")).strip()
    )
    if not state.get("_compound_word_percents_applied"):
        if snapshot_phased_word_scoring(loadout) and not dusty_interleaved:
            _apply_snapshot_phased_word_finalize(state, loadout)
    if state.get("_snapshot_phased_finalize_applied") or state.get(
        "_compound_post_cocktail_applied"
    ):
        return float(sum(state["tile_scores"]) + state["word_score"])
    subtotal = sum(state["tile_scores"]) + state["word_score"]
    from cursed_words_solver.rules.scoring_conditions import (
        golden_record_multiplies_word_score_only,
    )

    word_only = golden_record_multiplies_word_score_only(
        loadout, board, path, state
    )
    tile_only = bool(
        state.get("_additive_word_after_pending_percent")
        and state.get("pending_word_finalize_steps")
        and not word_only
    )
    return float(
        _apply_pending_word_finalize_steps(
            state,
            subtotal,
            multiply_tile_sum_only=tile_only,
            multiply_word_score_only=word_only,
        )
    )


def _finalize_with_trace(
    state: dict[str, Any],
    loadout: Loadout | None = None,
    *,
    board: Board | None = None,
    path: list[int] | None = None,
    rules: dict[str, Any] | None = None,
) -> tuple[float, list[dict[str, Any]]]:
    """Like _finalize but records each ×WORD floor step in trace."""
    if state.get("multiplier") == 0:
        return 0.0, []
    extras = (
        loadout.extras
        if loadout is not None and isinstance(loadout.extras, dict)
        else {}
    )
    has_compound_post = bool(
        str(extras.get("compound_post_cocktail_percents", "")).strip()
    )
    if state.get("_compound_word_percents_applied") and not has_compound_post:
        return float(sum(state["tile_scores"]) + state["word_score"]), []
    if board is not None and path is not None:
        apply_green_tile_word_transfer(
            board,
            path,
            state,
            trace_step=_trace_step if state.get("_trace") is not None else None,
        )
    trace = state.get("_trace")
    _apply_post_cocktail_word_percent_if_needed(
        state, loadout, board=board, path=path, rules=rules
    )
    _apply_compound_post_cocktail_finalize(state, loadout)
    from cursed_words_solver.rules.scoring_conditions import (
        snapshot_dusty_interleaved_word_scoring,
        snapshot_phased_word_scoring,
    )

    dusty_interleaved = (
        snapshot_dusty_interleaved_word_scoring(loadout)
        and not str(extras.get("compound_word_percents_on_tile_sum", "")).strip()
    )
    if not state.get("_compound_word_percents_applied"):
        if snapshot_phased_word_scoring(loadout) and not dusty_interleaved:
            _apply_snapshot_phased_word_finalize(state, loadout)
    if state.get("_snapshot_phased_finalize_applied") or state.get(
        "_compound_post_cocktail_applied"
    ):
        return float(sum(state["tile_scores"]) + state["word_score"]), []
    subtotal = sum(state["tile_scores"]) + state["word_score"]
    if trace is not None:
        _trace_step(state, "pre_multiply", detail="tile sum + word score")
    from cursed_words_solver.rules.scoring_conditions import (
        golden_record_multiplies_word_score_only,
    )

    word_only = golden_record_multiplies_word_score_only(
        loadout, board, path, state
    )
    tile_only = bool(
        state.get("_additive_word_after_pending_percent")
        and state.get("pending_word_finalize_steps")
        and not word_only
    )
    total = _apply_pending_word_finalize_steps(
        state,
        subtotal,
        trace=trace,
        multiply_tile_sum_only=tile_only,
        multiply_word_score_only=word_only,
    )
    return float(total), []





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
        solve_context: SolveContext | None = None,
        graph_ctx: BoardGraphContext | None = None,
        board_scoring_ctx: "BoardScoringContext | None" = None,
        grid_refs_cache: dict[tuple[int, ...], tuple] | None = None,
        capybara_loadout_cache: dict[tuple[int, ...], Loadout] | None = None,
        grid_refs_timing: object | None = None,
    ) -> dict[str, Any]:
        from cursed_words_solver.board_scoring_context import apply_static_rule

        path = normalize_scoring_path(path)
        from cursed_words_solver.rules.scoring_conditions import (
            apply_snapshot_phased_session_extras,
            ensure_snapshot_copy_slug,
            snapshot_phased_word_scoring,
        )

        if snapshot_phased_word_scoring(loadout):
            apply_snapshot_phased_session_extras(loadout, board)
            extras = loadout.extras if isinstance(loadout.extras, dict) else {}
            if str(extras.get("_skip_snapshot_copy_infer", "")).lower() not in (
                "1",
                "true",
                "yes",
            ):
                expected: int | None = None
                raw_expected = extras.get("snapshot_trial_expected_score")
                if raw_expected not in (None, ""):
                    try:
                        expected = int(raw_expected)
                    except (TypeError, ValueError):
                        expected = None

                def _trial_score() -> int:
                    if loadout.extras is None:
                        loadout.extras = {}
                    loadout.extras["_skip_snapshot_copy_infer"] = "true"
                    try:
                        trial_state = self._compute_state(
                            board,
                            path,
                            word,
                            loadout,
                            trace=None,
                            solve_context=solve_context,
                            graph_ctx=graph_ctx,
                            board_scoring_ctx=board_scoring_ctx,
                            grid_refs_cache=grid_refs_cache,
                            capybara_loadout_cache=capybara_loadout_cache,
                            grid_refs_timing=grid_refs_timing,
                        )
                        return int(
                            _finalize(
                                trial_state,
                                board=board,
                                path=path,
                                loadout=loadout,
                                rules=self.rules,
                            )
                        )
                    finally:
                        loadout.extras.pop("_skip_snapshot_copy_infer", None)

                ensure_snapshot_copy_slug(
                    loadout,
                    board,
                    rules=self.rules,
                    path=path,
                    word=word,
                    trial_score=_trial_score if expected is not None else None,
                    expected_score=expected,
                )

        ctx = (
            solve_context
            if solve_context is not None
            else build_solve_context(loadout, self.rules)
        )
        state = _init_state(
            board,
            path,
            word,
            loadout=loadout,
            blue_base_override=ctx.shield_blue_base,
            microscope_base=ctx.microscope_base,
        )
        if trace is not None:
            state["_trace"] = trace
        state["_search_flags"] = ctx.search_flags
        state["_graph_ctx"] = graph_ctx
        apply_tile_init(
            board,
            path,
            word,
            loadout,
            state,
            microscope_base=ctx.microscope_base,
            blue_base_override=ctx.shield_blue_base,
            trace_step=_trace_step if trace is not None else None,
        )
        hourglass = ctx.hourglass_reversed
        if not hourglass:
            state = self._apply_early_boss_rules(state, board, path, loadout, ctx)
        _apply_void_path_bonuses(board, path, loadout, state)

        from cursed_words_solver.rules.scoring_conditions import (
            grid_path_word_mult_defer_for_pin,
            grid_path_word_mult_is_immediate,
            snapshot_phased_word_scoring,
        )

        compound_percents = ctx.compound_percents
        if compound_percents or ctx.compound_finalize_at_cocktail:
            state["_defer_word_mults_for_compound"] = True

        grid_refs = list(
            path_grid_item_refs(
                board,
                path,
                self.rules,
                loadout,
                cache=grid_refs_cache,
                cache_timing=grid_refs_timing,
            )
        )
        if hourglass:
            grid_refs.reverse()
        if ctx.grid_tile_multiply_first:
            grid_refs = sort_grid_path_refs(grid_refs, self.rules)
        for ref in grid_refs:
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
            prev_immediate_pct = state.get("_immediate_word_percent")
            defer_grid_mult = grid_path_word_mult_defer_for_pin(loadout)
            if defer_grid_mult and grid_path_word_mult_is_immediate(
                loadout, ref.rule_id, rule
            ):
                state["_wad_deferred_grid_word_mult"] = True
            if (
                not state.get("_defer_word_mults_for_compound")
                and grid_path_word_mult_is_immediate(loadout, ref.rule_id, rule)
                and not defer_grid_mult
            ):
                state["_immediate_word_percent"] = True
            state = self._apply_rule(
                rule,
                state,
                board,
                path,
                loadout,
                ref.level,
                applying_sticker_id=ref.rule_id,
            )
            if ref.rule_id == "tombstone" and rule.get("type") == "add_tile_score":
                state["_grid_path_tombstone_applied"] = True
            if (
                snapshot_phased_word_scoring(loadout)
                and rule.get("type") == "multiply_word_by_unique_colour_count"
                and state.get("pending_word_finalize_steps")
            ):
                if slugify_name(ref.rule_id) == "dango":
                    state["_grid_dango_word_flushed"] = True
                _flush_pending_word_mults(state)
            state["_immediate_word_percent"] = prev_immediate_pct
            _trace_step(state, "grid_item", rule_id=ref.rule_id, detail="scattered grid item")
        if str((loadout.extras or {}).get("flush_word_mults_after_grid", "")).lower() in (
            "1",
            "true",
            "yes",
        ):
            _flush_pending_word_mults(state)

        pin_effect = str(loadout.extras.get("pin_effect", "") or "").strip()
        if pin_effect and not hourglass:
            state = self._apply_pin(
                loadout, pin_effect, state, board, path, hourglass_reversed=False
            )
            _trace_step(state, "pin", rule_id=pin_effect, detail="pin applied")
        from cursed_words_solver.rules.scoring_conditions import snapshot_phased_word_scoring

        from cursed_words_solver.rules.scoring_conditions import (
            snapshot_dusty_interleaved_word_scoring,
            snapshot_phased_word_scoring,
        )

        from cursed_words_solver.rules.scoring_conditions import (
            post_cocktail_sunflower_session,
        )

        if post_cocktail_sunflower_session(loadout, board):
            _strip_sunflower_from_pending(state)
        if snapshot_dusty_interleaved_word_scoring(loadout, board) and (
            str((loadout.extras or {}).get("pin_effect", "") or "").strip().lower()
            == "random_access_memory"
        ):
            _flush_pending_through_rule(state, "burrito")
        elif str((loadout.extras or {}).get("flush_word_mults_after_pin", "")).lower() in (
            "1",
            "true",
            "yes",
        ) and (
            not snapshot_phased_word_scoring(loadout)
            or snapshot_dusty_interleaved_word_scoring(loadout, board)
        ):
            from cursed_words_solver.rules.scoring_conditions import (
                compound_word_finalize_at_cocktail,
            )

            if not compound_word_finalize_at_cocktail(loadout, board):
                _flush_pending_word_mults(state)
        defer_multiply_stickers = _salamander_defer_multiply_for_mutating(loadout)

        _skip_types = _STAMP_SKIP_TYPES

        def _apply_static_sticker_slot(
            slot: int,
            sticker: LoadoutItem,
            slug: str,
            rule: dict | None,
            *,
            multiply_only: bool,
        ) -> bool:
            if (
                board_scoring_ctx is None
                or not board_scoring_ctx.use_split_pipeline
                or slug == "snapshot"
                or not rule
                or rule.get("type") in _skip_types
            ):
                return False
            spec = board_scoring_ctx.static_sticker_specs.get((slot, multiply_only))
            if spec is None:
                return False
            apply_static_rule(
                spec,
                state,
                path,
                word,
                board,
                loadout,
                self.rules,
                add_word_score=_add_word_score,
            )
            _trace_step(
                state,
                "sticker",
                rule_id=spec.rule_id,
                effect_type=spec.effect_type,
                detail=f"static {spec.kind.value}",
            )
            return True

        def _apply_static_stamp_slot(
            slot: int,
            stamp: LoadoutItem,
            rule: dict | None,
        ) -> bool:
            if (
                board_scoring_ctx is None
                or not board_scoring_ctx.use_split_pipeline
                or not rule
                or rule.get("type") in _skip_types
            ):
                return False
            spec = board_scoring_ctx.static_stamp_specs.get(slot)
            if spec is None:
                return False
            apply_static_rule(
                spec,
                state,
                path,
                word,
                board,
                loadout,
                self.rules,
                add_word_score=_add_word_score,
            )
            _trace_step(
                state,
                "stamp",
                rule_id=spec.rule_id,
                effect_type=spec.effect_type,
                detail=f"static {spec.kind.value}",
            )
            return True

        def _apply_sticker_pass(*, multiply_only: bool) -> None:
            nonlocal state
            for slot in ctx.sticker_slot_order:
                sticker = loadout.stickers[slot]
                _key, rule = get_rule(
                    self.rules, "stickers", sticker.id, sticker.name
                )
                slug = slugify_name(sticker.id or sticker.name)
                if slug != "snapshot" and (
                    not rule or rule.get("type") in _skip_types
                ):
                    continue
                is_multiply = rule.get("type") == "multiply_word_scaled"
                if slug != "snapshot" and multiply_only != is_multiply:
                    continue
                if state.get("_defer_word_mults_for_compound"):
                    if multiply_only:
                        if not is_multiply:
                            continue
                    elif is_multiply:
                        continue
                if state.get("_compound_word_percents_applied") and multiply_only:
                    continue
                if (
                    not multiply_only
                    and slug == "cocktail"
                    and state.get("pending_word_finalize_steps")
                ):
                    from cursed_words_solver.rules.scoring_conditions import (
                        snapshot_dusty_interleaved_word_scoring,
                        snapshot_phased_word_scoring,
                    )

                    if snapshot_dusty_interleaved_word_scoring(loadout, board):
                        from cursed_words_solver.rules.scoring_conditions import (
                            compound_word_finalize_at_cocktail,
                        )

                        if not compound_word_finalize_at_cocktail(loadout, board):
                            _flush_pending_through_rule(state, "burrito")
                    elif str(
                        (loadout.extras or {}).get("flush_word_mults_before_cocktail", "")
                    ).lower() in ("1", "true", "yes") and not (
                        snapshot_phased_word_scoring(loadout)
                    ):
                        _flush_pending_word_mults(state)
                pre_compound, post_compound = _compound_pre_post_percents(loadout)
                if not multiply_only and slug == "cocktail" and pre_compound:
                    _apply_compound_word_percents_on_tile_sum(
                        state,
                        pre_compound,
                        trace=state.get("_trace"),
                        board=board,
                        path=path,
                    )
                if not _apply_static_sticker_slot(
                    slot,
                    sticker,
                    slug,
                    rule,
                    multiply_only=multiply_only,
                ):
                    state = apply_sticker_with_orchestration(
                        rules=self.rules,
                        loadout=loadout,
                        state=state,
                        board=board,
                        path=path,
                        sticker=sticker,
                        slot=slot,
                        apply_rule=self._apply_rule,
                        multiply_only=multiply_only,
                    )
                if not multiply_only and slug == "cocktail":
                    from cursed_words_solver.rules.scoring_conditions import (
                        compound_word_finalize_at_cocktail,
                    )

                    defer_compound_finalize = compound_word_finalize_at_cocktail(
                        loadout, board
                    )
                    if (
                        not defer_compound_finalize
                        and pre_compound is None
                        and post_compound is None
                    ):
                        compound = (
                            list(ctx.compound_percents) if ctx.compound_percents else None
                        )
                        if compound:
                            state["word_score"] = 0.0
                            _apply_compound_word_percents_on_tile_sum(
                                state,
                                compound,
                                trace=state.get("_trace"),
                                board=board,
                                path=path,
                            )
                    elif post_compound and not pre_compound:
                        state["word_score"] = 0.0
                        _apply_compound_word_percents_on_tile_sum(
                            state,
                            post_compound,
                            trace=state.get("_trace"),
                            board=board,
                            path=path,
                        )

        state["_immediate_word_mult"] = True
        if hourglass:
            for slot in ctx.stamp_slot_order:
                stamp = loadout.stamps[slot]
                _key, rule = get_rule(self.rules, "stamps", stamp.id, stamp.name)
                if rule and rule.get("type") not in _skip_types:
                    if not _apply_static_stamp_slot(slot, stamp, rule):
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
                for slot in ctx.sticker_slot_order:
                    sticker = loadout.stickers[slot]
                    _key, rule = get_rule(
                        self.rules, "stickers", sticker.id, sticker.name
                    )
                    slug = slugify_name(sticker.id or sticker.name)
                    if not rule or rule.get("type") in _skip_types:
                        continue
                    if not _apply_static_sticker_slot(
                        slot,
                        sticker,
                        slug,
                        rule,
                        multiply_only=False,
                    ):
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
                state = self._apply_pin(
                    loadout,
                    pin_effect,
                    state,
                    board,
                    path,
                    hourglass_reversed=True,
                )
                _trace_step(state, "pin", rule_id=pin_effect, detail="pin applied")
        elif defer_multiply_stickers:
            _apply_sticker_pass(multiply_only=False)
        else:
            _apply_sticker_pass(multiply_only=False)
            _apply_sticker_pass(multiply_only=True)
        _apply_compound_word_finalize_after_stickers(
            state, loadout, board, path, self.rules
        )
        state["_immediate_word_mult"] = False
        if not hourglass:
            for slot in ctx.stamp_slot_order:
                stamp = loadout.stamps[slot]
                _key, rule = get_rule(self.rules, "stamps", stamp.id, stamp.name)
                if rule and rule.get("type") not in _skip_types:
                    if not _apply_static_stamp_slot(slot, stamp, rule):
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
            state = self._apply_hourglass_boss_rules(state, board, path, loadout, ctx)
        else:
            state = self._apply_late_boss_rules(state, board, path, loadout, ctx)
        apply_green_tile_word_transfer(
            board,
            path,
            state,
            trace_step=_trace_step if trace is not None else None,
        )
        return state

    def _apply_early_boss_rules(
        self,
        state: dict[str, Any],
        board: Board,
        path: list[int],
        loadout: Loadout,
        solve_ctx: SolveContext,
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
            active_boss_rules=solve_ctx.active_boss_rules,
            boss_ctx=solve_ctx.boss_ctx,
        )

    def _apply_hourglass_boss_rules(
        self,
        state: dict[str, Any],
        board: Board,
        path: list[int],
        loadout: Loadout,
        solve_ctx: SolveContext,
    ) -> dict[str, Any]:
        """Hourglass: reversed ApplyBossModifier pass after items."""
        trace_fn = _trace_step if state.get("_trace") is not None else None
        return apply_hourglass_boss_scoring(
            state,
            board,
            path,
            loadout,
            self.rules,
            self._apply_rule,
            trace_step=trace_fn,
            active_boss_rules=solve_ctx.active_boss_rules,
            boss_ctx=solve_ctx.boss_ctx,
        )

    def _apply_late_boss_rules(
        self,
        state: dict[str, Any],
        board: Board,
        path: list[int],
        loadout: Loadout,
        solve_ctx: SolveContext,
    ) -> dict[str, Any]:
        """Boss effects not handled in wiki step 1 (constraints, vowel zero, custom)."""
        active = list(solve_ctx.active_boss_rules)
        for key, boss in active:
            if not boss or boss.get("type") in (
                "unmodeled",
                "custom",
                *_EARLY_BOSS_EFFECT_TYPES,
            ):
                continue
            ctx = solve_ctx.boss_ctx
            if not boss_rule_applies(boss, ctx):
                continue
            state = self._apply_rule(boss, state, board, path, loadout, 1)
            if state.get("_trace") is not None:
                _trace_step(
                    state,
                    "boss_late",
                    rule_id=key or loadout.boss_id or "boss",
                    detail=boss_scoring_effect_type(boss) or boss.get("type", ""),
                )
        if not active and loadout.boss_effect:
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
        *,
        solve_context: SolveContext | None = None,
        graph_ctx: BoardGraphContext | None = None,
        board_scoring_ctx: "BoardScoringContext | None" = None,
        grid_refs_cache: dict[tuple[int, ...], tuple] | None = None,
        capybara_loadout_cache: dict[tuple[int, ...], Loadout] | None = None,
        grid_refs_timing: object | None = None,
    ) -> float:
        """Final score without building the breakdown dict (search hot path)."""
        loadout = loadout or Loadout(money=board.money)
        state = self._compute_state(
            board,
            path,
            word,
            loadout,
            solve_context=solve_context,
            graph_ctx=graph_ctx,
            board_scoring_ctx=board_scoring_ctx,
            grid_refs_cache=grid_refs_cache,
            capybara_loadout_cache=capybara_loadout_cache,
            grid_refs_timing=grid_refs_timing,
        )
        return _finalize(state, board, path, loadout, rules=self.rules)

    def score(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout | None = None,
        *,
        solve_context: SolveContext | None = None,
        graph_ctx: BoardGraphContext | None = None,
        board_scoring_ctx: "BoardScoringContext | None" = None,
        grid_refs_cache: dict[tuple[int, ...], tuple] | None = None,
        capybara_loadout_cache: dict[tuple[int, ...], Loadout] | None = None,
        grid_refs_timing: object | None = None,
    ) -> tuple[float, dict[str, Any]]:
        loadout = loadout or Loadout(money=board.money)
        state = self._compute_state(
            board,
            path,
            word,
            loadout,
            solve_context=solve_context,
            graph_ctx=graph_ctx,
            board_scoring_ctx=board_scoring_ctx,
            grid_refs_cache=grid_refs_cache,
            capybara_loadout_cache=capybara_loadout_cache,
            grid_refs_timing=grid_refs_timing,
        )
        final = _finalize(state, board, path, loadout, rules=self.rules)
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
        *,
        solve_context: SolveContext | None = None,
    ) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
        """Full score with ordered trace steps for mismatch debugging."""
        loadout = loadout or Loadout(money=board.money)
        trace: list[dict[str, Any]] = []
        state = self._compute_state(
            board, path, word, loadout, trace=trace, solve_context=solve_context
        )
        final, _ = _finalize_with_trace(
            state, loadout, board=board, path=path, rules=self.rules
        )
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
        *,
        hourglass_reversed: bool = False,
    ) -> dict:
        return apply_pin_word_scoring(
            rules=self.rules,
            loadout=loadout,
            pin_effect=pin_effect,
            state=state,
            board=board,
            path=path,
            apply_rule=self._apply_rule,
            hourglass_reversed=hourglass_reversed,
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

                _queue_word_multiplier(
                    state, factor, rule_id, defer_finalize=True
                )

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
                        board,
                        path,
                        i,
                        strict=strict_takes,
                        loadout=loadout,
                        search_flags=state.get("_search_flags", 0),
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
                    elif target == "consumable" and (
                        is_consumable_tile(tile) or is_placed_consumable_tile(tile)
                    ):
                        # Mahjong Red Dragon multiplies WasConsumable tiles (decompiled
                        # MahjongRedDragon.ApplyTileBonus). A placed consumable reads
                        # was_consumable on the board even when its live `consumable`
                        # flag is cleared (submit board: consumable=false), so match
                        # either to fire on placed tiles (swivets).
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
                        board,
                        tile,
                        path=path,
                        path_index=i,
                        search_flags=state.get("_search_flags", 0),
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
                    board, path, loadout, state=state
                )
            elif word_mode == "per_void_unused":
                from cursed_words_solver.rules.scoring_conditions import (
                    snapshot_per_void_unused_override,
                )

                n = dusty_coffin_void_units(
                    board,
                    state["word"],
                    loadout,
                    applying_sticker_id=applying_sticker_id or "",
                    path=path,
                )
                if (applying_sticker_id or "").lower() == "snapshot":
                    override = snapshot_per_void_unused_override(loadout)
                    if override is not None:
                        n = override
                bonus = sticker_rule_int(level, rule) * n
            elif word_mode == "per_unused_red":
                n = unused_red_tiles_on_board(board, path)
                bonus = sticker_rule_int(level, rule) * n
            elif word_mode == "if_same_start_end":
                if word_same_start_end_on_path(board, path, state["word"]):
                    bonus = sticker_rule_int(level, rule)
            elif word_mode == "per_unique_vowel":
                n = unique_vowels_on_path(board, path)
                bonus = sticker_rule_int(level, rule) * n
            elif word_mode == "if_subtotal_zero":
                if subtotal_before_mult(state) == 0:
                    bonus = sticker_rule_int(level, rule)
            elif word_mode == "per_highest_number":
                high = highest_number_on_path(board, path)
                if high:
                    bonus = sticker_rule_int(level, rule) * high
            elif word_mode == "birthday_cake_bonus":
                accumulated = birthday_cake_accumulated(loadout)
                improve = birthday_cake_improve_for_path(
                    board, path, level, rule, state["word"]
                )
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
                _graph_ctx = state.get("_graph_ctx")
                total = grid_total_base_score(
                    board,
                    cached=_graph_ctx.grid_base_score if _graph_ctx else None,
                )
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
                    _graph_ctx = state.get("_graph_ctx")
                    bonus = sticker_rule_int(level, rule) * coloured_tile_count_on_grid(
                        board,
                        cached=_graph_ctx.coloured_tile_count if _graph_ctx else None,
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
            rid = (rule_id or applying_sticker_id or "").lower()
            is_neapolitan = rid == "neapolitan"
            apply_neapolitan = is_neapolitan
            if not met and not apply_neapolitan:
                rule_trace_context["skip_reason"] = cond_explanation
            if met or apply_neapolitan:
                if is_neapolitan:
                    improve_colours = unique_colours_on_path(board, path)
                    improve_eligible = len(improve_colours) >= 3
                    improve_neapolitan = improve_eligible
                    rule_trace_context["condition_met"] = improve_eligible
                    rule_trace_context["neapolitan_improve_colours"] = sorted(
                        improve_colours
                    )
                else:
                    improve_neapolitan = False
                if is_neapolitan:
                    base_percent, source = neapolitan_base_percent_from_loadout(loadout)
                    rule_trace_context["neapolitan_base_percent"] = int(base_percent)
                    rule_trace_context["neapolitan_base_source"] = source
                    rule_trace_context["neapolitan_simulate_submit_improve"] = bool(
                        improve_neapolitan
                    )
                    if improve_neapolitan:
                        rule_trace_context[
                            "condition_explanation"
                        ] = "applied: stored multiplier + submit improve"
                    else:
                        rule_trace_context[
                            "condition_explanation"
                        ] = "applied: stored multiplier (no improve this submit)"
                effective_level = level
                if (
                    rid == "yellow_glasses"
                    and state.get("_wad_deferred_grid_word_mult")
                    and any(
                        str(step[2] or "").strip().lower() == "cherry_pie"
                        for step in state.get("pending_word_finalize_steps", [])
                        if step[0] == "percent"
                    )
                ):
                    effective_level = max(1, level - 1)
                factor = scaled_word_multiplier(
                    effective_level,
                    rule,
                    loadout,
                    path=path,
                    board=board,
                    improve_neapolitan_on_submit=improve_neapolitan,
                )
                if rid == "neapolitan":
                    rule_trace_context["neapolitan_effective_percent"] = int(
                        round(float(factor) * 100.0)
                    )
                label = condition or rule.get("scale_from_extras", "scaled")
                salamander_defer = _salamander_defer_multiply_for_mutating(loadout)
                if (
                    rid == "yellow_glasses"
                    and state["word_score"] > 0
                    and level >= 3
                    and salamander_defer
                ):
                    state["salamander_post_mutating_mults"].append(
                        (factor, rule_id)
                    )
                    state["effects"].append(f"×{factor} word ({label})")
                elif (
                    rid == "wrestlers"
                    and state["word_score"] > 0
                    and salamander_defer
                    and word_starts_ends_different_suit(board, path)
                ):
                    state["salamander_post_mutating_mults"].append(
                        (factor, rule_id)
                    )
                    state["effects"].append(f"×{factor} word ({label})")
                elif (
                    rid == "wrestlers"
                    and state["word_score"] > 0
                    and _boss_is_salamander(loadout)
                ):
                    bonus = int(100 * factor)
                    _add_word_score(state, bonus)
                    state["multiplier"] *= factor
                    state["effects"].append(f"+{bonus} word ({label})")
                else:
                    if rid == "steak" and loadout is not None:
                        raw_pct = (loadout.extras or {}).get("steak_word_bonus_percent")
                        if raw_pct not in (None, ""):
                            try:
                                percent = int(raw_pct)
                                factor = float(percent) / 100.0
                            except (TypeError, ValueError):
                                percent = word_percent_bonus_from_multiplier(
                                    factor, rule, level=level
                                )
                        else:
                            percent = word_percent_bonus_from_multiplier(
                                factor, rule, level=level
                            )
                    elif rid == "neapolitan" and loadout is not None:
                        percent = int(round(float(factor) * 100.0))
                    else:
                        percent = word_percent_bonus_from_multiplier(
                            factor, rule, level=level
                        )
                    _queue_word_percent_bonus(
                        state, percent, rule_id, wiki_factor=factor
                    )
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
                label = rule.get("name") or "Heart On Fire"
                state["effects"].append(
                    f"{label}: ×{factor} word (longest RED run {run})"
                )

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
            factor = float(n)
            if n == 0:
                # Preserve hard-zero behavior for Dango when there are no coloured tiles.
                _queue_word_multiplier(state, factor, rule_id)
                state["effects"].append(
                    f"×{factor} word ({n} unique colour(s))"
                )
            else:
                percent = word_percent_bonus_from_multiplier(factor, rule, level=level)
                _queue_word_percent_bonus(
                    state,
                    percent,
                    rule_id,
                    wiki_factor=factor,
                )
                state["effects"].append(
                    f"×{factor} word ({n} unique colour(s))"
                )

        elif effect_type == "multiply_word_by_unique_curse_type_count":
            from cursed_words_solver.rules.scoring_conditions import (
                golden_record_skips_oden_mult,
            )

            if not golden_record_skips_oden_mult(loadout, board, path, state):
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
            if str(rule_id or "").strip().lower() == "sunflower" and loadout is not None:
                from cursed_words_solver.rules.scoring_conditions import (
                    compound_word_finalize_at_cocktail,
                )

                extras = loadout.extras or {}
                if str(extras.get("defer_post_cocktail_sunflower", "")).lower() in (
                    "1",
                    "true",
                    "yes",
                ) or compound_word_finalize_at_cocktail(loadout, board):
                    return state
            factor = money_word_multiplier(
                level, rule, money_for_scoring(board, path, loadout, state=state)
            )
            if factor != 1.0:
                percent = word_percent_bonus_from_multiplier(factor, rule, level=level)
                _queue_word_percent_bonus(
                    state, percent, rule_id, wiki_factor=factor
                )
                state["effects"].append(f"×{factor} word (money bonus)")

        elif effect_type == "multiply_consumable_rack":
            factor = consumable_rack_multiplier(level, rule, loadout)
            if factor != 1.0:
                percent = word_percent_bonus_from_multiplier(
                    factor, rule, level=level
                )
                _queue_word_percent_bonus(
                    state, percent, rule_id, wiki_factor=factor
                )
                state["effects"].append(f"×{factor} word (consumable rack)")

        elif effect_type == "multiply_word_other_sticker_levels":
            factor = burrito_word_multiplier(
                level,
                rule,
                loadout,
                board=board,
                path=path,
                rules=self.rules,
            )
            if factor != 1.0:
                percent = word_percent_bonus_from_multiplier(
                    factor, rule, level=level
                )
                _queue_word_percent_bonus(
                    state,
                    percent,
                    rule_id,
                    wiki_factor=factor,
                )
                state["effects"].append(f"×{factor} word (other sticker levels)")

        elif effect_type == "red_encounter_tile_bonus":
            per_level = level
            if per_level:
                count = 0
                for i, idx in enumerate(path):
                    if board.get_by_index(idx).color.value == "red":
                        running = telescope_running_red_count(
                            loadout, board, path, i
                        )
                        add = per_level * running
                        state["tile_scores"][i] += add
                        count += 1
                if count:
                    tele_label = rule.get("name") or "Telescope"
                    state["effects"].append(
                        f"{tele_label}: +{per_level}×encounter red count per red tile"
                        f" ({count} tile(s))"
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
                percent = word_percent_bonus_from_multiplier(factor, rule, level=level)
                _queue_word_percent_bonus(
                    state, percent, rule_id, wiki_factor=factor
                )
                state["effects"].append(f"×{factor} word")

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
            rid_take = slugify_name(rule_id or applying_sticker_id or "")
            if rid_take in ("super_8", "super_eight") and super_8_uses_melmod_take_metadata(
                board, path
            ):
                strict_takes = True
            mode = rule.get("mode", "flat")
            if mode == "piece_value_first_n":
                n = sticker_rule_int(level, rule)
                improve = movie_camera_improve_for_path(
                    board, path, n, strict=strict_takes, loadout=loadout
                )
                bonus = movie_camera_encounter_word_bonus(
                    board, path, n, loadout, strict=strict_takes
                )
                accumulated = bonus - improve
                if not bonus and level >= 3 and chess_takes_on_path(
                    board,
                    path,
                    strict=strict_takes,
                    search_flags=state.get("_search_flags", 0),
                ) == 0:
                    bonus = n * n
                    accumulated = 0
                    improve = bonus
                if bonus:
                    _add_word_score(state, bonus)
                    state["effects"].append(
                        f"+{bonus} word (Movie Camera: {accumulated} + {improve})"
                    )
            else:
                per_take = super_8_take_word_bonus(loadout, rule)
                takes = chess_takes_on_path(
                    board,
                    path,
                    strict=strict_takes,
                    search_flags=state.get("_search_flags", 0),
                )
                if takes:
                    bonus = per_take * takes
                    _add_word_score(state, bonus)
                    state["effects"].append(f"+{bonus} word ({takes} take(s))")

        elif effect_type == "card_hand_word_bonus":
            hand = rule.get("hand", "")
            if rule.get("word_mode") == "per_unused_card":
                if not hanafuda_hand_satisfied(board, path, level):
                    pass
                else:
                    _graph_ctx = state.get("_graph_ctx")
                    n_unused = unused_cards_on_board(
                        board,
                        path,
                        hanafuda_suit_mask=(
                            _graph_ctx.hanafuda_suit_mask if _graph_ctx else 0
                        ),
                    )
                    per = sticker_rule_int(level, rule)
                    x = hanafuda_x_required(level)
                    hand_label = {
                        2: "pair",
                        3: "three_of_a_kind",
                        4: "four_of_a_kind",
                    }.get(x, hand or "pair")
                    if n_unused and per:
                        bonus = per * n_unused
                        _add_word_score(state, bonus)
                        state["effects"].append(
                            f"+{bonus} word ({hand_label}, {n_unused} unused card(s))"
                        )
            elif not detect_card_hand(hand, board, path, loadout):
                pass
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
            rule_key = str(loadout.extras.get("_scoring_boss_rule_key") or "")
            penalty = resolve_boss_scaling_for_rule(
                loadout, self.rules, rule_key or None, rule
            )
            if penalty is None:
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


