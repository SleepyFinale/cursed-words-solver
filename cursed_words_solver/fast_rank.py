"""Tier-2 fast rank: bounds before full scoring pipeline."""



from __future__ import annotations



from cursed_words_solver.graph_bitboard import (
    RED_COLOR_CODE,
    BoardGraphContext,
)
from cursed_words_solver.models import Board, CurseType, Loadout, TileColor

from cursed_words_solver.mult_search import (
    MultRule,
    guaranteed_mult_factor,
    loadout_mult_rules,
    optimistic_mult_factor,
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

from cursed_words_solver.solve_context import SolveContext



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


def number_aware_lower_bound(
    board: Board,
    path: list[int],
    loadout: Loadout,
    rules: dict,
    graph_ctx: BoardGraphContext | None = None,
) -> float:
    """Tile-base lower bound using precomputed graph bases (number/fraction safe)."""
    if graph_ctx is None:
        base = fast_rank_lower_bound(board, path)
    else:
        base = 0.0
        for idx in path:
            tile = board.get_by_index(idx)
            if tile.curse == CurseType.ITEM:
                base += graph_ctx.item_tile_base[idx]
            else:
                base += graph_ctx.tile_base[idx]
    mult_rules = loadout_mult_rules(loadout, rules, board=board, path=path)
    return base * guaranteed_mult_factor(mult_rules, loadout, path)





def path_has_scattered_grid_items(board: Board, path: list[int]) -> bool:
    """True when the path crosses scattered sticker/stamp tiles (CurseType.ITEM)."""
    return any(board.get_by_index(idx).curse == CurseType.ITEM for idx in path)


# Tier-1 bounds skip item tiles in tile-base sums; without a finite item UB they
# prune high-scoring scatter routes. Use a finite optimistic add+scale instead of
# a 1e15 sentinel so tier-2 can still skip hopeless candidates.


def _scattered_item_optimistic_add(
    board: Board,
    path: list[int],
    graph_ctx: BoardGraphContext | None,
) -> tuple[float, int]:
    """Optimistic additive value from ITEM faces on the path (+ count)."""
    total = 0.0
    n_items = 0
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse != CurseType.ITEM:
            continue
        n_items += 1
        if graph_ctx is not None and 0 <= idx < len(graph_ctx.item_tile_base):
            total += abs(float(graph_ctx.item_tile_base[idx]))
        else:
            total += abs(float(tile.base_score or 0.0))
            total += abs(tile_base_contribution(tile, board.money))
        # Scatter inventory effects can add more than tile base; keep loose headroom.
        total += 80.0
    return total, n_items


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


def _tier2_additive_bonuses(
    board: Board,
    path: list[int],
    word: str,
    ctx: SolveContext,
    graph_ctx: BoardGraphContext | None = None,
    board_scoring_ctx=None,
) -> tuple[float, float, float, float, float, float]:
    """Tile-base sum and loadout-invariant bonuses from SolveContext."""
    from cursed_words_solver.board_scoring_context import path_static_tile_add_bonus

    base = tier2_tile_base_sum(board, path, ctx)
    static_tile_add = path_static_tile_add_bonus(board_scoring_ctx, path)
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
                board,
                path,
                hanafuda_suit_mask=(
                    graph_ctx.hanafuda_suit_mask if graph_ctx else 0
                ),
            )
    return base, word_bonus, path_bonus, red_bonus, hanafuda_bonus, static_tile_add


def tier2_immediate_lower_bound(
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    ctx: SolveContext,
    mult_rules: list[MultRule],
    graph_ctx: BoardGraphContext | None = None,
    board_scoring_ctx=None,
) -> float:
    """Conservative immediate score; never exceeds full pipeline score_total_only."""
    (
        base,
        word_bonus,
        path_bonus,
        red_bonus,
        hanafuda_bonus,
        static_tile_add,
    ) = _tier2_additive_bonuses(
        board,
        path,
        word,
        ctx,
        graph_ctx=graph_ctx,
        board_scoring_ctx=board_scoring_ctx,
    )
    subtotal = (
        base + word_bonus + path_bonus + red_bonus + hanafuda_bonus + static_tile_add
    )
    return subtotal * guaranteed_mult_factor(mult_rules, loadout, path)


def tier2_immediate_upper_bound(
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    ctx: SolveContext,
    mult_rules: list[MultRule],
    graph_ctx: BoardGraphContext | None = None,
    board_scoring_ctx=None,
) -> float:
    """Optimistic upper bound on score_total_only before search-rank heuristics."""
    (
        base,
        word_bonus,
        path_bonus,
        red_bonus,
        hanafuda_bonus,
        static_tile_add,
    ) = _tier2_additive_bonuses(
        board,
        path,
        word,
        ctx,
        graph_ctx=graph_ctx,
        board_scoring_ctx=board_scoring_ctx,
    )
    item_add, n_items = _scattered_item_optimistic_add(board, path, graph_ctx)
    subtotal = (
        base
        + word_bonus
        + path_bonus
        + red_bonus
        + hanafuda_bonus
        + static_tile_add
        + item_add
    )
    mult = optimistic_mult_upper_bound(mult_rules, loadout, path)
    result = subtotal * mult
    if n_items > 0:
        # Path-order item stickers can further scale; finite but loose ceiling.
        result *= max(2.0, 1.0 + 2.5 * n_items)
    return result





def tier2_rank_lower_bound(
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    ctx: SolveContext,
    mult_rules: list[MultRule],
    *,
    mult_weight: float,
    hanafuda_level: int = 0,
    graph_ctx: BoardGraphContext | None = None,
    board_scoring_ctx=None,
) -> float:
    """Conservative lower bound on heap rank_score for tier-2 two-phase scoring."""
    immediate_lb = tier2_immediate_lower_bound(
        board,
        path,
        word,
        loadout,
        ctx,
        mult_rules,
        graph_ctx=graph_ctx,
        board_scoring_ctx=board_scoring_ctx,
    )
    mult_lb = guaranteed_mult_factor(mult_rules, loadout, path)
    rank_lb = search_rank_score(
        immediate_lb,
        mult_lb,
        mult_weight=mult_weight,
        setup_bonus=0.0,
    )
    if hanafuda_level > 0 and hanafuda_hand_satisfied(board, path, hanafuda_level):
        rank_lb += 800.0
    return rank_lb


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
    graph_ctx: BoardGraphContext | None = None,
    board_scoring_ctx=None,
    setup_weight: float = 0.0,
    setup_discount: float = 0.85,
    rules: dict | None = None,
) -> float:
    """Optimistic upper bound on heap rank_score for tier-2 screening."""
    from cursed_words_solver.setup_value import rank_score_for_word

    immediate_ub = tier2_immediate_upper_bound(
        board,
        path,
        word,
        loadout,
        ctx,
        mult_rules,
        graph_ctx=graph_ctx,
        board_scoring_ctx=board_scoring_ctx,
    )
    mult_ub = optimistic_mult_upper_bound(mult_rules, loadout, path)
    setup_bonus = 0.0
    if setup_weight > 0:
        _, setup_bonus = rank_score_for_word(
            board,
            path,
            word,
            loadout,
            immediate_ub,
            setup_weight=setup_weight,
            setup_discount=setup_discount,
            rules=rules,
        )
    rank_ub = search_rank_score(
        immediate_ub,
        mult_ub,
        mult_weight=mult_weight,
        setup_bonus=setup_bonus,
    )
    if hanafuda_level > 0 and hanafuda_hand_satisfied(board, path, hanafuda_level):
        rank_ub += 800.0
    return rank_ub


def loadout_allows_tier2_two_phase(
    ctx: SolveContext,
    loadout: Loadout,
    *,
    setup_weight: float = 0.0,
    score_fn=None,
) -> bool:
    """True when tier-1 screen + deferred phase-2 full scoring is safe."""
    return loadout_allows_tier2_screen(
        ctx,
        loadout,
        setup_weight=setup_weight,
        score_fn=score_fn,
    )





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

    return True


def build_search_tile_base(
    board: Board,
    ctx: SolveContext,
    graph_ctx: BoardGraphContext,
) -> tuple[float, ...]:
    """Per-cell base scores for DFS prefix tracking (SolveContext overrides)."""
    cell_count = graph_ctx.cell_count
    out = [0.0] * cell_count
    for idx in range(cell_count):
        if not (graph_ctx.active_mask & (1 << idx)):
            continue
        if graph_ctx.item_mask & (1 << idx):
            continue
        tile = board.get_by_index(idx)
        if ctx.microscope_base:
            out[idx] = float(microscope_init_contribution(tile, board.money))
        elif tile.color == TileColor.BLUE and ctx.shield_blue_base is not None:
            out[idx] = float(ctx.shield_blue_base)
        else:
            out[idx] = graph_ctx.tile_base[idx]
    return tuple(out)


def _max_unvisited_base_sum(
    graph_ctx: BoardGraphContext,
    search_tile_base: tuple[float, ...],
    visited_mask: int,
    steps_left: int,
) -> float:
    if steps_left <= 0:
        return 0.0
    avail = graph_ctx.active_mask & ~visited_mask
    if not avail:
        return 0.0
    candidates: list[float] = []
    while avail:
        bit = (avail & -avail).bit_length() - 1
        candidates.append(search_tile_base[bit])
        avail &= avail - 1
    candidates.sort(reverse=True)
    return sum(candidates[:steps_left])


def _prefix_additive_bonuses(
    board: Board,
    path: list[int],
    chars: list[str],
    visited_mask: int,
    steps_left: int,
    ctx: SolveContext,
    graph_ctx: BoardGraphContext,
    *,
    max_len: int,
    prefix_red_count: int,
) -> tuple[float, float, float, float]:
    """Optimistic loadout bonuses assuming the path extends to max_len."""
    prefix_word = "".join(chars)
    hypothetical_len = len(prefix_word) + steps_left
    word_bonus = (
        ctx.max_word_length_bonus if hypothetical_len >= ctx.word_length_min else 0
    )
    path_bonus = (
        ctx.bicycle_word_accumulator
        + ctx.pin_word_bonus_per_tile * max_len
        + ctx.always_add_word_bonus
    )
    red_bonus = 0
    if ctx.red_tile_bonus_per_red > 0:
        reds = prefix_red_count
        unvisited = graph_ctx.active_mask & ~visited_mask
        while unvisited:
            bit = (unvisited & -unvisited).bit_length() - 1
            if graph_ctx.tile_color_code[bit] == RED_COLOR_CODE:
                reds += 1
            unvisited &= unvisited - 1
        red_bonus = ctx.red_tile_bonus_per_red * reds
    hanafuda_bonus = 0
    if ctx.hanafuda_level > 0 and ctx.hanafuda_per_unused > 0:
        if hanafuda_hand_satisfied(board, path, ctx.hanafuda_level) or steps_left > 0:
            hanafuda_bonus = ctx.hanafuda_per_unused * unused_cards_on_board(
                board,
                path,
                hanafuda_suit_mask=graph_ctx.hanafuda_suit_mask,
            )
    return word_bonus, path_bonus, red_bonus, hanafuda_bonus


def _prefix_subtotal_upper_bound(
    prefix_base: float,
    board: Board,
    path: list[int],
    chars: list[str],
    visited_mask: int,
    steps_left: int,
    ctx: SolveContext,
    graph_ctx: BoardGraphContext,
    search_tile_base: tuple[float, ...],
    *,
    max_len: int,
    prefix_red_count: int,
) -> float:
    max_fill = _max_unvisited_base_sum(
        graph_ctx, search_tile_base, visited_mask, steps_left
    )
    base = prefix_base + max_fill
    word_bonus, path_bonus, red_bonus, hanafuda_bonus = _prefix_additive_bonuses(
        board,
        path,
        chars,
        visited_mask,
        steps_left,
        ctx,
        graph_ctx,
        max_len=max_len,
        prefix_red_count=prefix_red_count,
    )
    return base + word_bonus + path_bonus + red_bonus + hanafuda_bonus


def prefix_immediate_upper_bound(
    prefix_base: float,
    board: Board,
    path: list[int],
    chars: list[str],
    visited_mask: int,
    steps_left: int,
    loadout: Loadout,
    ctx: SolveContext,
    mult_rules: list[MultRule],
    graph_ctx: BoardGraphContext,
    search_tile_base: tuple[float, ...],
    *,
    max_len: int,
    prefix_red_count: int,
) -> float:
    """Optimistic upper bound on score_total_only for any word extending a DFS prefix."""
    subtotal = _prefix_subtotal_upper_bound(
        prefix_base,
        board,
        path,
        chars,
        visited_mask,
        steps_left,
        ctx,
        graph_ctx,
        search_tile_base,
        max_len=max_len,
        prefix_red_count=prefix_red_count,
    )
    mult = optimistic_mult_upper_bound(mult_rules, loadout, path)
    return subtotal * mult


def prefix_dfs_rank_bound(
    prefix_base: float,
    board: Board,
    path: list[int],
    chars: list[str],
    visited_mask: int,
    steps_left: int,
    loadout: Loadout,
    ctx: SolveContext,
    mult_rules: list[MultRule],
    graph_ctx: BoardGraphContext,
    search_tile_base: tuple[float, ...],
    rules: dict,
    *,
    mult_weight: float,
    max_len: int,
    prefix_red_count: int,
    hanafuda_level: int = 0,
    mult_factor: float | None = None,
) -> float:
    """Heap rank_score upper estimate for DFS pruning (uses optimistic_mult_factor)."""
    immediate_ub = prefix_immediate_upper_bound(
        prefix_base,
        board,
        path,
        chars,
        visited_mask,
        steps_left,
        loadout,
        ctx,
        mult_rules,
        graph_ctx,
        search_tile_base,
        max_len=max_len,
        prefix_red_count=prefix_red_count,
    )
    if mult_factor is None:
        mult_factor = optimistic_mult_factor(
            loadout,
            board,
            path,
            "".join(chars),
            rules,
            mult_rules,
        )
    rank_ub = search_rank_score(
        immediate_ub,
        mult_factor,
        mult_weight=mult_weight,
        setup_bonus=0.0,
    )
    if hanafuda_level > 0 and hanafuda_hand_satisfied(board, path, hanafuda_level):
        rank_ub += 800.0
    return rank_ub


def prefix_rank_upper_bound(
    prefix_base: float,
    board: Board,
    path: list[int],
    chars: list[str],
    visited_mask: int,
    steps_left: int,
    loadout: Loadout,
    ctx: SolveContext,
    mult_rules: list[MultRule],
    graph_ctx: BoardGraphContext,
    search_tile_base: tuple[float, ...],
    *,
    mult_weight: float,
    max_len: int,
    prefix_red_count: int,
    hanafuda_level: int = 0,
    setup_weight: float = 0.0,
    setup_discount: float = 0.85,
    rules: dict | None = None,
) -> float:
    """Optimistic upper bound on heap rank_score for a DFS prefix."""
    from cursed_words_solver.setup_value import rank_score_for_word

    immediate_ub = prefix_immediate_upper_bound(
        prefix_base,
        board,
        path,
        chars,
        visited_mask,
        steps_left,
        loadout,
        ctx,
        mult_rules,
        graph_ctx,
        search_tile_base,
        max_len=max_len,
        prefix_red_count=prefix_red_count,
    )
    mult = optimistic_mult_upper_bound(mult_rules, loadout, path)
    setup_bonus = 0.0
    if setup_weight > 0:
        word = "".join(chars).lower()
        _, setup_bonus = rank_score_for_word(
            board,
            path,
            word,
            loadout,
            immediate_ub,
            setup_weight=setup_weight,
            setup_discount=setup_discount,
            rules=rules,
        )
    rank_ub = search_rank_score(
        immediate_ub,
        mult,
        mult_weight=mult_weight,
        setup_bonus=setup_bonus,
    )
    if hanafuda_level > 0 and hanafuda_hand_satisfied(board, path, hanafuda_level):
        rank_ub += 800.0
    return rank_ub


def loadout_allows_dfs_bb(
    ctx: SolveContext,
    loadout: Loadout,
    *,
    has_number_tiles: bool,
    has_chess_pieces: bool,
    setup_weight: float = 0.0,
    score_fn=None,
) -> bool:
    """True when in-tree DFS branch-and-bound is safe."""
    del has_chess_pieces
    # Number tiles previously blocked BB entirely. Prefix UBs are slightly loose
    # on digit branches but still useful — keep BB on when tier-2 is enabled.
    del has_number_tiles
    return loadout_allows_tier2_screen(
        ctx,
        loadout,
        setup_weight=setup_weight,
        score_fn=score_fn,
    )


