"""Per-solve board-level scoring precomputation for static inventory rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

from cursed_words_solver.graph_bitboard import BoardGraphContext
from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.rule_lookup import slugify_name
from cursed_words_solver.rules.rule_phase import (
    PipelinePhase,
    StaticRuleKind,
    StaticRuleSpec,
    blocks_split_pipeline,
    classify_inventory_rule,
)
from cursed_words_solver.rules.scoring_conditions import (
    abacus_colored_number_bonus,
    is_colored_number_tile,
    is_number_like_tile,
    sticker_rule_int,
    tile_matches_target,
)
from cursed_words_solver.solve_context import SolveContext


def build_cell_masks(board: Board, graph_ctx: BoardGraphContext) -> dict[str, int]:
    """Bitmask per target label for all active cells (computed once per solve)."""
    masks: dict[str, int] = {"all": graph_ctx.active_mask}
    vowel = consonant = red = red_plain = blue = void = shiny = red_note = number = (
        colored_number
    ) = colored = 0

    for idx in range(graph_ctx.cell_count):
        if not graph_ctx.is_active(idx):
            continue
        tile = board.get_by_index(idx)
        if tile_matches_target(tile, "vowel"):
            vowel |= 1 << idx
        if tile_matches_target(tile, "consonant"):
            consonant |= 1 << idx
        if tile_matches_target(tile, "red"):
            red |= 1 << idx
        if tile.color.value == "red":
            red_plain |= 1 << idx
        if tile_matches_target(tile, "blue"):
            blue |= 1 << idx
        if tile_matches_target(tile, "void"):
            void |= 1 << idx
        if tile_matches_target(tile, "shiny"):
            shiny |= 1 << idx
        if tile_matches_target(tile, "red_note"):
            red_note |= 1 << idx
        if is_number_like_tile(tile):
            number |= 1 << idx
        if is_colored_number_tile(tile):
            colored_number |= 1 << idx
        if tile_matches_target(tile, "colored"):
            colored |= 1 << idx

    masks["vowel"] = vowel
    masks["consonant"] = consonant
    masks["red"] = red
    masks["red_plain"] = red_plain
    masks["blue"] = blue
    masks["void"] = void
    masks["shiny"] = shiny
    masks["red_note"] = red_note
    masks["number"] = number
    masks["colored_number"] = colored_number
    masks["colored"] = colored
    masks["wildcard"] = graph_ctx.wildcard_mask & graph_ctx.active_mask

    for letter, mask in graph_ctx.letter_masks.items():
        masks[f"letter:{letter}"] = mask & graph_ctx.active_mask

    return masks


@dataclass(frozen=True)
class BoardScoringContext:
    use_split_pipeline: bool
    cell_masks: dict[str, int]
    static_sticker_specs: dict[tuple[int, bool], StaticRuleSpec] = field(
        default_factory=dict
    )
    static_stamp_specs: dict[int, StaticRuleSpec] = field(default_factory=dict)
    static_tile_add_by_phase: dict[str, tuple[float, ...]] = field(default_factory=dict)
    path_static_tile_add_sum: float = 0.0


def _sticker_multiply_pass(rule: dict | None, slug: str) -> bool:
    if slug == "snapshot":
        return False
    return bool(rule and rule.get("type") == "multiply_word_scaled")


def build_board_scoring_context(
    board: Board,
    loadout: Loadout,
    solve_ctx: SolveContext,
    graph_ctx: BoardGraphContext,
    rules: dict[str, Any],
) -> BoardScoringContext:
    from cursed_words_solver.rules.rule_lookup import get_rule

    cell_masks = build_cell_masks(board, graph_ctx)
    if blocks_split_pipeline(loadout, solve_ctx, rules):
        return BoardScoringContext(
            use_split_pipeline=False,
            cell_masks=cell_masks,
        )

    static_sticker_specs: dict[tuple[int, bool], StaticRuleSpec] = {}
    static_stamp_specs: dict[int, StaticRuleSpec] = {}

    for slot in solve_ctx.sticker_slot_order:
        if slot >= len(loadout.stickers):
            continue
        sticker = loadout.stickers[slot]
        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
        slug = slugify_name(sticker.id or sticker.name)
        for multiply_pass in (False, True):
            if _sticker_multiply_pass(rule, slug) != multiply_pass:
                continue
            spec = classify_inventory_rule(
                rule or {},
                level=sticker.level,
                rule_id=sticker.id or sticker.name or "",
                phase=PipelinePhase.STICKER,
                target_masks=cell_masks,
            )
            if spec is not None:
                static_sticker_specs[(slot, multiply_pass)] = spec

    for slot in solve_ctx.stamp_slot_order:
        if slot >= len(loadout.stamps):
            continue
        stamp = loadout.stamps[slot]
        _key, rule = get_rule(rules, "stamps", stamp.id, stamp.name)
        spec = classify_inventory_rule(
            rule or {},
            level=stamp.level,
            rule_id=stamp.id or stamp.name or "",
            phase=PipelinePhase.STAMP,
            target_masks=cell_masks,
        )
        if spec is not None:
            static_stamp_specs[slot] = spec

    use_split = bool(static_sticker_specs or static_stamp_specs)

    sticker_add = [0.0] * graph_ctx.cell_count
    for spec in static_sticker_specs.values():
        if spec.kind == StaticRuleKind.TILE_ADD and spec.value:
            for idx in range(graph_ctx.cell_count):
                if spec.target_mask & (1 << idx):
                    sticker_add[idx] += spec.value

    return BoardScoringContext(
        use_split_pipeline=use_split,
        cell_masks=cell_masks,
        static_sticker_specs=static_sticker_specs,
        static_stamp_specs=static_stamp_specs,
        static_tile_add_by_phase={"sticker": tuple(sticker_add)},
        path_static_tile_add_sum=sum(sticker_add),
    )


def apply_static_tile_add(
    state: dict[str, Any],
    path: list[int],
    bonus: float,
    target_mask: int,
) -> int:
    if not bonus:
        return 0
    count = 0
    for i, idx in enumerate(path):
        if target_mask & (1 << idx):
            state["tile_scores"][i] += bonus
            count += 1
    return count


def apply_static_tile_mult(
    state: dict[str, Any],
    path: list[int],
    factor: float,
    target_mask: int,
) -> int:
    if factor == 1.0:
        return 0
    count = 0
    for i, idx in enumerate(path):
        if target_mask & (1 << idx):
            state["tile_scores"][i] *= factor
            count += 1
    return count


def path_static_tile_add_bonus(
    board_scoring_ctx: BoardScoringContext | None,
    path: list[int],
) -> float:
    """Sum of precomputed static per-cell tile adds for path cells."""
    if board_scoring_ctx is None or not board_scoring_ctx.use_split_pipeline:
        return 0.0
    adds = board_scoring_ctx.static_tile_add_by_phase.get("sticker")
    if not adds:
        return 0.0
    total = 0.0
    for idx in path:
        if 0 <= idx < len(adds):
            total += adds[idx]
    return total


def apply_static_rule(
    spec: StaticRuleSpec,
    state: dict[str, Any],
    path: list[int],
    word: str,
    board: Board,
    loadout: Loadout,
    rules: dict[str, Any],
    *,
    add_word_score: Callable[[dict[str, Any], float], None] | None = None,
) -> None:
    """Apply one board-static rule at the correct pipeline phase (O(path))."""
    effects = state.setdefault("effects", [])

    if spec.kind == StaticRuleKind.TILE_ADD:
        count = apply_static_tile_add(state, path, spec.value, spec.target_mask)
        if count:
            sign = "+" if spec.value >= 0 else ""
            total = spec.value * count
            effects.append(
                f"{sign}{total:g} {spec.target_label} tile score ({count})"
            )

    elif spec.kind == StaticRuleKind.TILE_MULT:
        count = apply_static_tile_mult(state, path, spec.value, spec.target_mask)
        if count:
            effects.append(f"×{spec.value:g} {spec.target_label} tile score ({count})")

    elif spec.kind == StaticRuleKind.COLORED_NUMBER_ADD:
        from cursed_words_solver.rules.rule_lookup import get_rule

        _key, rule = get_rule(rules, "stickers", spec.rule_id, spec.rule_id)
        if not rule:
            _key, rule = get_rule(rules, "stamps", spec.rule_id, spec.rule_id)
        if not rule:
            return
        bonus_each = abacus_colored_number_bonus(loadout, rule)
        count = apply_static_tile_add(state, path, bonus_each, spec.target_mask)
        if count:
            effects.append(
                f"+{bonus_each * count:g} coloured number tile ({count} tile(s))"
            )

    elif spec.kind == StaticRuleKind.WORD_ADD:
        if add_word_score is not None:
            add_word_score(state, spec.value)
        else:
            state["word_score"] = state.get("word_score", 0) + spec.value
        effects.append(f"+{spec.value:g} word")

    elif spec.kind == StaticRuleKind.WORD_LENGTH:
        if len(word) >= spec.min_word_length:
            if add_word_score is not None:
                add_word_score(state, spec.value)
            else:
                state["word_score"] = state.get("word_score", 0) + spec.value
            effects.append(f"+{spec.value:g} long word")

    elif spec.kind == StaticRuleKind.RED_TILE_BONUS:
        count = apply_static_tile_add(state, path, spec.value, spec.target_mask)
        if count:
            effects.append(f"+{spec.value:g} per red tile ({count})")
