"""Tier-2 fast rank: bounds before full scoring pipeline."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Loadout, TileColor
from cursed_words_solver.mult_search import (
    MultRule,
    guaranteed_mult_factor,
    loadout_mult_rules,
    optimistic_mult_upper_bound,
    search_rank_score,
)
from cursed_words_solver.rules.base_scoring import (
    microscope_init_contribution,
    tile_base_contribution,
)
from cursed_words_solver.rules.scoring_conditions import (
    hanafuda_hand_satisfied,
    unused_cards_on_board,
)
from cursed_words_solver.setup_value import _has_setup_mechanics
from cursed_words_solver.solve_context import SolveContext, tier2_setup_blocks_screen

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


def loadout_allows_mult_prune(
    loadout: Loadout,
    rules: dict,
    *,
    setup_weight: float = 0.0,
) -> bool:
    """True when mult_aware_lower_bound is safe for heap pruning."""
    if loadout_allows_fast_rank(loadout, setup_weight=setup_weight):
        return True
    mult_rules = loadout_mult_rules(loadout, rules)
    if not mult_rules:
        return False
    return all(mr.condition in ("always", "") for mr in mult_rules)


def mult_aware_lower_bound(
    board: Board,
    path: list[int],
    loadout: Loadout,
    rules: dict,
) -> float:
    """Tile bases × guaranteed always-on mults; never exceeds full pipeline score."""
    base = fast_rank_lower_bound(board, path)
    mult_rules = loadout_mult_rules(loadout, rules, board=board, path=path)
    return base * guaranteed_mult_factor(mult_rules, loadout, path)


def tier2_tile_base_sum(board: Board, path: list[int], ctx: SolveContext) -> float:
    """Per-tile init sum respecting SolveContext microscope/shield overrides."""
    total = 0.0
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.ITEM:
            continue
        if ctx.microscope_base:
            total += microscope_init_contribution(tile, board.money)
        elif tile.color == TileColor.BLUE and ctx.shield_blue_base is not None:
            total += float(ctx.shield_blue_base)
        else:
            total += tile_base_contribution(tile, board.money)
    return total


def tier2_immediate_upper_bound(
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    ctx: SolveContext,
    mult_rules: list[MultRule],
) -> float:
    """Optimistic upper bound on score_total_only before search-rank heuristics."""
    base = tier2_tile_base_sum(board, path, ctx)
    word_bonus = (
        ctx.max_word_length_bonus if len(word) >= ctx.word_length_min else 0
    )
    path_bonus = (
        ctx.bicycle_word_accumulator
        + ctx.pin_word_bonus_per_tile * len(path)
        + ctx.always_add_word_bonus
    )
    red_bonus = 0
    if ctx.red_tile_bonus_per_red > 0:
        reds = sum(
            1 for idx in path if board.get_by_index(idx).color == TileColor.RED
        )
        red_bonus = ctx.red_tile_bonus_per_red * reds
    hanafuda_bonus = 0
    if ctx.hanafuda_level > 0 and ctx.hanafuda_per_unused > 0:
        if hanafuda_hand_satisfied(board, path, ctx.hanafuda_level):
            hanafuda_bonus = ctx.hanafuda_per_unused * unused_cards_on_board(
                board, path
            )
    subtotal = base + word_bonus + path_bonus + red_bonus + hanafuda_bonus
    mult = optimistic_mult_upper_bound(mult_rules, loadout, path)
    return subtotal * mult


def tier2_rank_upper_bound(
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    ctx: SolveContext,
    mult_rules: list[MultRule],
    *,
    mult_weight: float,
    hanafuda_level: int = 0,
) -> float:
    """Optimistic upper bound on heap rank_score for tier-2 screening."""
    immediate_ub = tier2_immediate_upper_bound(
        board, path, word, loadout, ctx, mult_rules
    )
    mult_ub = optimistic_mult_upper_bound(mult_rules, loadout, path)
    rank_ub = search_rank_score(
        immediate_ub,
        mult_ub,
        mult_weight=mult_weight,
        setup_bonus=0.0,
    )
    if hanafuda_level > 0 and hanafuda_hand_satisfied(board, path, hanafuda_level):
        rank_ub += 800.0
    return rank_ub


def loadout_allows_tier2_screen(
    ctx: SolveContext,
    loadout: Loadout,
    *,
    setup_weight: float = 0.0,
    score_fn=None,
) -> bool:
    """True when tier-2 optimistic screen is safe and likely useful."""
    if score_fn is not None:
        return False
    if not ctx.tier2_screen_enabled:
        return False
    if setup_weight > 0 and tier2_setup_blocks_screen(loadout):
        return False
    return True
