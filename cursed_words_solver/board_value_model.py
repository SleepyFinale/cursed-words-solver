"""Per-solve board value model for score-aware search guidance.

Built once per F8 from live board + loadout contexts. Never cached across solves.
Does not replace ScoringPipeline — only guides expansion order / beam priority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cursed_words_solver.board_scoring_context import BoardScoringContext
from cursed_words_solver.graph_bitboard import (
    CURSE_CODE_NUMBER,
    BoardGraphContext,
)
from cursed_words_solver.models import Board, CurseType, Loadout
from cursed_words_solver.mult_search import MultNeighborHints, MultRule
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_DOUBLE_LETTER_TELEPORT,
    SearchFlagsMask,
    flag_test,
)
from cursed_words_solver.solve_context import SolveContext

if TYPE_CHECKING:
    from cursed_words_solver.loadout_affordances import LoadoutAffordances

# Color code from graph_bitboard._COLOR_TO_CODE (WHITE)
_WHITE_COLOR_CODE = 6


@dataclass(frozen=True)
class BoardValueModel:
    """Immutable per-solve expansion guidance (rebuild every find_best_words)."""

    cell_potential: tuple[float, ...]
    coverage_mask: int
    hub_mask: int
    branch_cost: tuple[float, ...]
    must_include_mask: int
    soft_cover_mask: int
    number_mask: int
    wildcard_density: float
    item_count: int
    chess_count: int
    soft_must_include: bool = False
    needs_suit_diverse_ends: bool = False
    rewards_long_word: bool = False
    rewards_chess_takes: bool = False
    suit_endpoint_mask: int = 0

    def cell_score(self, idx: int) -> float:
        if 0 <= idx < len(self.cell_potential):
            return self.cell_potential[idx]
        return 0.0

    def branch_penalty(self, idx: int) -> float:
        if 0 <= idx < len(self.branch_cost):
            return self.branch_cost[idx]
        return 0.0

    def is_hub(self, idx: int) -> bool:
        return bool(self.hub_mask & (1 << idx))

    def is_must_include(self, idx: int) -> bool:
        return bool(self.must_include_mask & (1 << idx))

    def is_soft_cover(self, idx: int) -> bool:
        return bool(self.soft_cover_mask & (1 << idx))

    def is_number(self, idx: int) -> bool:
        return bool(self.number_mask & (1 << idx))

    def coverage_progress(self, visited_mask: int) -> float:
        """Fraction of must/soft cover cells already on the path."""
        target = self.must_include_mask | self.soft_cover_mask
        if not target:
            return 1.0
        hit = (visited_mask & target).bit_count()
        need = target.bit_count()
        return hit / need if need else 1.0

    def missing_must_include(self, visited_mask: int) -> int:
        return (self.must_include_mask & ~visited_mask).bit_count()

    def soft_must_pressure(self, visited_mask: int) -> float:
        """Soft must-include pressure for beam (does not hard-skip scoring)."""
        if not self.soft_must_include or not self.must_include_mask:
            return 0.0
        missing = self.must_include_mask & ~visited_mask
        return 12.0 * float(missing.bit_count())

    def start_priority(self, idx: int) -> float:
        """Higher is better for seeding the frontier."""
        pot = self.cell_score(idx)
        hub = 25.0 if self.is_hub(idx) else 0.0
        cover = 40.0 if self.is_must_include(idx) else (
            18.0 if self.is_soft_cover(idx) else 0.0
        )
        penalty = self.branch_penalty(idx)
        if self.wildcard_density >= 0.16:
            penalty *= 1.35
        if self.is_number(idx):
            penalty *= 0.35
            pot += 8.0
        if self.needs_suit_diverse_ends and (self.suit_endpoint_mask & (1 << idx)):
            pot += 14.0
        if self.rewards_chess_takes and self.is_hub(idx):
            pot += 6.0
        return pot + hub + cover - penalty

    def expand_priority(
        self,
        *,
        path: list[int],
        visited_mask: int,
        next_idx: int,
        prefix_len: int,
        min_len: int,
    ) -> float:
        """Optimistic priority for expanding onto next_idx (higher = sooner)."""
        pot = self.cell_score(next_idx)
        hub = 12.0 if self.is_hub(next_idx) else 0.0
        cover_before = self.coverage_progress(visited_mask)
        next_visited = visited_mask | (1 << next_idx)
        cover_after = self.coverage_progress(next_visited)
        cover_delta = (cover_after - cover_before) * 80.0
        must_left = self.missing_must_include(visited_mask)
        must_bonus = 0.0
        if must_left and self.is_must_include(next_idx):
            must_bonus = 100.0 + 15.0 * must_left
        length_pull = 0.0
        if prefix_len + 1 >= min_len:
            length_pull = 2.0 * (prefix_len + 1)
        if self.item_count >= 2 and cover_after < 1.0:
            length_pull += 4.0
        if self.rewards_long_word and prefix_len + 1 >= min_len:
            length_pull += 3.0
        if self.needs_suit_diverse_ends and path:
            start_suited = bool(self.suit_endpoint_mask & (1 << path[0]))
            next_suited = bool(self.suit_endpoint_mask & (1 << next_idx))
            if start_suited and next_suited:
                pot += 18.0
            elif next_suited:
                pot += 8.0
        if self.rewards_chess_takes and self.is_hub(next_idx):
            pot += 10.0
        pot -= self.soft_must_pressure(visited_mask) * 0.15
        if self.soft_must_include and self.is_must_include(next_idx):
            pot += self.soft_must_pressure(visited_mask)
        penalty = self.branch_penalty(next_idx)
        if self.wildcard_density >= 0.16 and prefix_len < min_len:
            penalty *= 1.25
        return pot + hub + cover_delta + must_bonus + length_pull - penalty

    def ordered_starts(self, indices: list[int]) -> list[int]:
        return sorted(indices, key=lambda i: (-self.start_priority(i), i))


def build_board_value_model(
    board: Board,
    loadout: Loadout,
    solve_ctx: SolveContext,
    graph_ctx: BoardGraphContext,
    board_scoring_ctx: BoardScoringContext | None,
    *,
    mult_rules: list[MultRule] | None = None,
    mult_hints: MultNeighborHints | None = None,
    required_consumable_indices: frozenset[int] | None = None,
    search_flags: SearchFlagsMask | None = None,
    affordances: LoadoutAffordances | None = None,
) -> BoardValueModel:
    """Pure function of live board/loadout/contexts — call once per solve."""
    del loadout  # affordances / hints cover inventory geometry today
    n = graph_ctx.cell_count
    flags = (
        search_flags
        if search_flags is not None
        else solve_ctx.search_flags
    )
    static_adds = (0.0,) * n
    if board_scoring_ctx is not None and board_scoring_ctx.use_split_pipeline:
        sticker_adds = board_scoring_ctx.static_tile_add_by_phase.get("sticker")
        if sticker_adds:
            static_adds = sticker_adds

    cell_potential = [0.0] * n
    branch_cost = [0.0] * n
    hub_mask = 0
    soft_cover = 0
    must_include = 0
    number_mask = 0
    suit_endpoint_mask = 0

    wildcard_count = graph_ctx.wildcard_mask.bit_count()
    chess_count = graph_ctx.chess_piece_mask.bit_count()
    item_count = graph_ctx.item_mask.bit_count()
    active_count = max(1, graph_ctx.active_mask.bit_count())
    wildcard_density = wildcard_count / active_count

    full_moon = flag_test(flags, FLAG_DOUBLE_LETTER_TELEPORT)
    needs_suit = bool(affordances and affordances.needs_suit_diverse_ends)
    rewards_long = bool(affordances and affordances.rewards_long_word) or (
        mult_hints is not None and mult_hints.prefer_length
    )
    rewards_chess = bool(affordances and affordances.rewards_chess_takes)
    soft_must = bool(
        affordances
        and (affordances.needs_item_cover or affordances.rewards_long_word)
    )

    for idx in range(n):
        if not graph_ctx.is_active(idx):
            continue
        base = float(graph_ctx.tile_base[idx])
        add = float(static_adds[idx]) if idx < len(static_adds) else 0.0
        pot = base + add

        tile = board.get_by_index(idx)
        suit = str((tile.metadata or {}).get("card_suit") or "").strip().lower()
        if suit and suit not in ("none", ""):
            suit_endpoint_mask |= 1 << idx
            if needs_suit:
                pot += 12.0

        if mult_hints is not None:
            if mult_hints.prefer_joker and (
                tile.curse == CurseType.WILDCARD
                or (tile.metadata or {}).get("is_joker")
            ):
                pot += 20.0
            if mult_hints.prefer_card_tiles and tile.curse == CurseType.CARD:
                pot += 15.0
            if mult_hints.end_colors:
                color = tile.color.value if tile.color else ""
                if color in mult_hints.end_colors:
                    pot += 10.0

        if mult_rules:
            if graph_ctx.number_like[idx]:
                pot += 6.0
            if graph_ctx.is_fraction[idx]:
                pot += 8.0

        is_white = graph_ctx.tile_color_code[idx] == _WHITE_COLOR_CODE
        is_chess = bool(graph_ctx.chess_piece_mask & (1 << idx))
        is_wild = bool(graph_ctx.wildcard_mask & (1 << idx))
        if is_white or is_chess or (full_moon and not is_wild):
            hub_mask |= 1 << idx
            pot += 8.0 if is_chess or is_white else 3.0

        cost = 0.0
        if is_wild:
            cost += 6.0 + 4.0 * wildcard_density
            if mult_hints is not None and mult_hints.prefer_joker:
                pot += 35.0
                cost *= 0.5
            if affordances is not None and affordances.prefer_joker:
                pot += 10.0
                cost *= 0.85
        if graph_ctx.curse_code[idx] == CURSE_CODE_NUMBER:
            number_mask |= 1 << idx
            cost += 6.0
        if graph_ctx.is_fraction[idx]:
            cost += 5.0
        if is_white:
            cost += 4.0

        cell_potential[idx] = pot
        branch_cost[idx] = cost

    center = solve_ctx.quest_ctx.require_center_index
    if center is not None and 0 <= center < n and graph_ctx.is_active(center):
        must_include |= 1 << center
        cell_potential[center] += 50.0

    if required_consumable_indices:
        for idx in required_consumable_indices:
            if 0 <= idx < n and graph_ctx.is_active(idx):
                must_include |= 1 << idx
                cell_potential[idx] += 45.0

    soft_cover = graph_ctx.item_mask & graph_ctx.active_mask
    if soft_cover:
        for idx in range(n):
            if soft_cover & (1 << idx):
                cell_potential[idx] += 30.0 + float(graph_ctx.item_tile_base[idx])
                if affordances and affordances.rewards_high_letter_count:
                    cell_potential[idx] += 10.0

    return BoardValueModel(
        cell_potential=tuple(cell_potential),
        coverage_mask=must_include | soft_cover,
        hub_mask=hub_mask,
        branch_cost=tuple(branch_cost),
        must_include_mask=must_include,
        soft_cover_mask=soft_cover,
        number_mask=number_mask,
        wildcard_density=wildcard_density,
        item_count=item_count,
        chess_count=chess_count,
        soft_must_include=soft_must or bool(must_include),
        needs_suit_diverse_ends=needs_suit,
        rewards_long_word=rewards_long,
        rewards_chess_takes=rewards_chess,
        suit_endpoint_mask=suit_endpoint_mask,
    )
