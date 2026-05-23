"""Full scoring pipeline: pin -> stickers -> stamps -> boss (wiki order)."""



from __future__ import annotations



import json
import math

from pathlib import Path

from typing import Any



from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor

from cursed_words_solver.rules.base_scoring import _scrabble_value, tile_base_contribution

from cursed_words_solver.rules.rule_lookup import (

    collect_unmapped_items,

    count_catalog_items,

    count_scoring_items,

    get_pin_scoring_rule,

    get_rule,

    resolve_rule_id,

)

from cursed_words_solver.rules.boss_effects import (
    boss_context,
    boss_rule_applies,
    resolve_boss_scaling,
)
from cursed_words_solver.rules.scoring_conditions import (
    abacus_colored_number_bonus,
    birthday_cake_accumulated,
    bicycle_word_per_card,
    brain_multiplier,
    cards_submitted_count,
    chess_takes_on_path,
    first_n_take_piece_value_sum,
    is_take_tile,
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
    detect_card_hand,
    unused_cards_on_board,
    is_colored_number_tile,
    NON_COLOUR_FOR_NUMBER_BONUS,
    is_consumable_tile,
    mahjong_consumable_factor,
    money_word_multiplier,
    number_sum_on_path,
    number_tile_count_on_path,
    word_all_numbers_on_path,
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
    void_tiles_unused_in_word,
    word_same_start_end_letter,
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





def _init_state(
    board: Board,
    path: list[int],
    word: str,
    *,
    blue_base_override: int | None = None,
) -> dict[str, Any]:

    tile_scores: list[float] = []

    base_total = 0.0

    for idx in path:

        tile = board.get_by_index(idx)

        if tile.color == TileColor.BLUE and blue_base_override is not None:
            contrib = float(blue_base_override)
        else:
            contrib = float(tile_base_contribution(tile, board.money))

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


def _queue_word_multiplier(state: dict[str, Any], factor: float) -> None:
    """Queue ×WORD SCORE for step 7 (wiki: applied after tile sum + word score)."""
    if factor == 1.0:
        return
    state["pending_word_multipliers"].append(factor)
    state["multiplier"] *= factor


def _flush_word_multipliers_to_tiles(state: dict[str, Any]) -> None:
    """Apply queued ×WORD to tile scores only (before later +WORD SCORE adds)."""
    for factor in state.get("pending_word_multipliers", []):
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


def _finalize(state: dict[str, Any]) -> float:
    """Sum tile + word scores, then apply queued ×WORD multipliers with floor each step."""
    total = sum(state["tile_scores"]) + state["word_score"]
    for factor in state.get("pending_word_multipliers", []):
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
    for factor in state.get("pending_word_multipliers", []):
        if factor != 1.0:
            total = math.floor(total * factor)
            if trace is not None:
                _trace_step(
                    state,
                    "multiply",
                    factor=float(factor),
                    detail=f"×{factor} word (floor)",
                )
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
        state = _init_state(
            board,
            path,
            word,
            blue_base_override=shield_blue_base_from_loadout(loadout, self.rules),
        )
        if trace is not None:
            state["_trace"] = trace
            _trace_step(
                state,
                "init",
                detail=f"base tile sum {state['base_score']}",
            )
        _apply_void_path_bonuses(board, path, loadout, state)
        pin_effect = str(loadout.extras.get("pin_effect", "") or "").strip()
        if pin_effect:
            state = self._apply_pin(loadout, pin_effect, state, board, path)
            _trace_step(state, "pin", rule_id=pin_effect, detail="pin applied")
        for sticker in loadout.stickers:
            _key, rule = get_rule(
                self.rules, "stickers", sticker.id, sticker.name
            )
            if rule and rule.get("type") not in ("unmodeled", "custom"):
                state = self._apply_rule(
                    rule,
                    state,
                    board,
                    path,
                    loadout,
                    sticker.level,
                    applying_sticker_id=sticker.id or sticker.name,
                )
        for stamp in loadout.stamps:
            _key, rule = get_rule(self.rules, "stamps", stamp.id, stamp.name)
            if rule and rule.get("type") not in ("unmodeled", "custom"):
                state = self._apply_rule(rule, state, board, path, loadout, 1)
        if pin_effect and resolve_rule_id(
            self.rules, "pins", pin_effect, pin_effect
        ) == "human_boy":
            state = self._apply_human_hands(loadout, state, board, path)
        if loadout.boss_id or loadout.boss_name:
            _key, boss = get_rule(
                self.rules, "bosses", loadout.boss_id, loadout.boss_name
            )
            if boss and boss.get("type") not in ("unmodeled", "custom"):
                ctx = boss_context(loadout, self.rules)
                if boss_rule_applies(boss, ctx):
                    state = self._apply_rule(boss, state, board, path, loadout, 1)
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
        return _finalize(self._compute_state(board, path, word, loadout))

    def score(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout | None = None,
    ) -> tuple[float, dict[str, Any]]:
        loadout = loadout or Loadout(money=board.money)
        state = self._compute_state(board, path, word, loadout)
        final = _finalize(state)
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

        canonical = resolve_rule_id(self.rules, "pins", pin_effect, pin_effect)

        if canonical == "random_access_memory":

            return self._apply_pin_memory(loadout, state, board, path)



        pin_rule = get_pin_scoring_rule(self.rules, pin_effect)

        if pin_rule and pin_rule.get("type") != "human_hands_pin":

            state = self._apply_rule(pin_rule, state, board, path, loadout, 1)

        return state



    def _apply_pin_memory(

        self,

        loadout: Loadout,

        state: dict,

        board: Board,

        path: list[int],

    ) -> dict:

        memory = loadout.extras.get("pin_memory") or []

        if not isinstance(memory, list):

            return state

        for entry in memory:

            if not isinstance(entry, dict):

                continue

            kind = str(entry.get("kind", "sticker")).lower()

            bucket = "stamps" if kind == "stamp" else "stickers"

            item_id = str(entry.get("id", "") or "")

            item_name = str(entry.get("name", "") or "")

            try:

                level = int(entry.get("level", 1))

            except (TypeError, ValueError):

                level = 1

            _key, rule = get_rule(self.rules, bucket, item_id, item_name)

            if rule and rule.get("type") not in ("unmodeled", "custom"):

                state = self._apply_rule(

                    rule, state, board, path, loadout, level

                )

                state["effects"].append(f"RAM: {item_name or item_id}")

        return state



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



        if fav_stamp and right > 0:

            for stamp in loadout.stamps:

                if stamp.id == fav_stamp or stamp.name == fav_stamp:

                    _key, rule = get_rule(

                        self.rules, "stamps", stamp.id, stamp.name

                    )

                    if rule and rule.get("type") not in ("unmodeled", "custom"):

                        for _ in range(right):

                            state = self._apply_rule(

                                rule, state, board, path, loadout, 1

                            )

                        state["effects"].append(

                            f"Human Hands: favourite stamp ×{right} extra"

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

                _queue_word_multiplier(state, factor)

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
                strict_takes = rule.get("strict_takes", False)
                for i, idx in enumerate(path):
                    tile = board.get_by_index(idx)
                    if target == "chess_take" and is_take_tile(tile, strict=strict_takes):
                        state["tile_scores"][i] *= factor
                        applied += 1
                    elif target == "number" and tile.curse == CurseType.NUMBER:
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
                    n_void = adjacent_void_count(board, tile)
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
                    if tile_matches_target(tile, target):
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
                bonus = sticker_rule_int(level, rule) * max(board.money, loadout.money, 0)
            elif word_mode == "per_void_unused":
                n = void_tiles_unused_in_word(board, path)
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
                improve = sticker_rule_int(level, rule) * high if high else 0
                bonus = accumulated + improve
                if bonus:
                    state["effects"].append(
                        f"+{bonus} word score (Birthday Cake: {accumulated}"
                        f" + {high}×{sticker_rule_int(level, rule)})"
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
            if not condition:
                met = True
            elif condition == "word_base_negative":
                met = state["base_score"] < 0
            elif condition == "word_base_eq_target":
                met = state["base_score"] == target_score_from_loadout(loadout)
            else:
                met = evaluate_sticker_condition(
                    condition,
                    board,
                    path,
                    state["word"],
                    loadout,
                    applying_sticker_id=applying_sticker_id,
                )
            if met:
                factor = scaled_word_multiplier(level, rule, loadout, path=path)
                _queue_word_multiplier(state, factor)
                label = condition or rule.get("scale_from_extras", "scaled")
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
                _queue_word_multiplier(state, factor)
                state["effects"].append(f"×{factor} word (letter count ≥{min_count})")

        elif effect_type == "multiply_word_by_longest_red_run":
            run = longest_red_run_on_path(board, path)
            if run >= 1:
                factor = float(run)
                _queue_word_multiplier(state, factor)
                state["effects"].append(f"×{factor} word (RED run {run})")

        elif effect_type == "multiply_word_per_path_tile":
            per_tile = float(rule.get("factor", -1.1))
            if path:
                factor = per_tile ** len(path)
                _queue_word_multiplier(state, factor)
                state["effects"].append(
                    f"×{factor} word ({len(path)} tile(s) @ {per_tile})"
                )

        elif effect_type == "multiply_word_by_unique_colour_count":
            n = unique_colour_count_on_path(board, path)
            if n >= 1:
                factor = float(n)
                _queue_word_multiplier(state, factor)
                state["effects"].append(
                    f"×{factor} word ({n} unique colour(s))"
                )

        elif effect_type == "multiply_word_by_unique_curse_type_count":
            n = unique_curse_type_count_on_path(board, path)
            if n >= 1:
                factor = float(n)
                _queue_word_multiplier(state, factor)
                state["effects"].append(
                    f"×{factor} word ({n} unique curse type(s))"
                )

        elif effect_type == "multiply_word_by_number_count":
            if word_all_numbers_on_path(board, path):
                n = number_tile_count_on_path(board, path)
                if n >= 1:
                    factor = float(n)
                    _queue_word_multiplier(state, factor)
                    state["effects"].append(
                        f"×{factor} word ({n} number tile(s))"
                    )

        elif effect_type == "use_base_score_tiles":
            total = 0.0
            for i, idx in enumerate(path):
                tile = board.get_by_index(idx)
                if tile.curse == CurseType.ITEM:
                    state["tile_scores"][i] = 0.0
                else:
                    state["tile_scores"][i] = float(tile.base_score)
                total += state["tile_scores"][i]
            state["base_score"] = total
            state["effects"].append("base score tiles (Microscope)")

        elif effect_type == "multiply_word_per_distinct_pair":
            pairs = distinct_pair_count_on_path(board, path)
            if pairs:
                rate = scaled_word_multiplier(level, rule)
                for _ in range(pairs):
                    _queue_word_multiplier(state, rate)
                state["effects"].append(
                    f"×{rate}^{pairs} word ({pairs} distinct pair(s))"
                )

        elif effect_type == "multiply_money_bonus":
            factor = money_word_multiplier(level, rule, max(board.money, loadout.money, 0))
            if factor != 1.0:
                _queue_word_multiplier(state, factor)
                state["effects"].append(f"×{factor} word (money bonus)")

        elif effect_type == "multiply_consumable_rack":
            factor = consumable_rack_multiplier(level, rule, loadout)
            if factor != 1.0:
                _queue_word_multiplier(state, factor)
                state["effects"].append(f"×{factor} word (consumable rack)")

        elif effect_type == "multiply_word_other_sticker_levels":
            factor = burrito_word_multiplier(level, rule, loadout)
            if factor != 1.0:
                _queue_word_multiplier(state, factor)
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
            if condition and not evaluate_sticker_condition(
                condition,
                board,
                path,
                state["word"],
                loadout,
                applying_sticker_id=applying_sticker_id,
            ):
                pass
            else:
                factor = float(rule.get("factor", 1.0))
                mushy = (loadout.extras or {}).get("avocado_mushy")
                if mushy in (True, "true", "True", "1", 1):
                    factor = -2.0
                if level > 1 and factor > 0:
                    factor = factor**level
                _queue_word_multiplier(state, factor)
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
            strict_takes = rule.get("strict_takes", False)
            mode = rule.get("mode", "flat")
            if mode == "piece_value_first_n":
                n = sticker_rule_int(level, rule)
                bonus = first_n_take_piece_value_sum(
                    board, path, n, strict=strict_takes
                )
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

            per_card = bicycle_word_per_card(loadout, rule)

            submitted = cards_submitted_count(loadout)

            if submitted and per_card:

                bonus = per_card * submitted

                _add_word_score(state, bonus)

                state["effects"].append(

                    f"+{bonus} word ({submitted} card(s) submitted)"

                )

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
                    state["tile_scores"][i] = max(0.0, state["tile_scores"][i] - p)
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

        elif effect_type in ("boss_word_min_length", "boss_word_max_length"):
            pass

        rule_id = applying_sticker_id or str(rule.get("id", "") or rule.get("name", ""))
        effects = state.get("effects") or []
        detail = str(effects[-1]) if effects else effect_type
        _trace_step(
            state,
            "rule",
            rule_id=rule_id,
            effect_type=effect_type,
            detail=detail,
        )
        return state


