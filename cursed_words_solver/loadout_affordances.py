"""Per-solve search affordances compiled from loadout + board.

Search reacts to this small tag vocabulary instead of per-sticker special cases.
ScoringPipeline remains the only exact score source.
"""

from __future__ import annotations

from dataclasses import dataclass

from cursed_words_solver.graph_bitboard import BoardGraphContext
from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.mult_search import MultNeighborHints, MultRule
from cursed_words_solver.rules.rule_lookup import get_rule
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_DOUBLE_LETTER_TELEPORT,
    flag_test,
)
from cursed_words_solver.solve_context import SolveContext, hanafuda_sticker_level

# Geometry tags that change which paths win under a time budget.
_AFFORDANCE_TAG_DOC = (
    "needs_digit_start, needs_item_cover, needs_suit_diverse_ends, "
    "rewards_chess_takes, rewards_hanafuda_hand, rewards_long_word, "
    "rewards_high_letter_count, rewards_number_tiles, rewards_all_number_tiles, "
    "has_path_order_mult, has_setup_npv, bounds_unsafe"
)


@dataclass(frozen=True)
class LoadoutAffordances:
    """Immutable search steering tags for one F8 solve."""

    needs_digit_start: bool
    needs_item_cover: bool
    needs_suit_diverse_ends: bool
    rewards_chess_takes: bool
    rewards_hanafuda_hand: bool
    rewards_long_word: bool
    rewards_high_letter_count: bool
    rewards_number_tiles: bool
    # Lab Coat / Full Battery pay on any number; Abacus alone → coloured only.
    rewards_all_number_tiles: bool
    has_path_order_mult: bool
    has_setup_npv: bool
    bounds_unsafe: bool
    # Convenience counters / policy for side-slice scheduling
    item_count: int
    number_count: int
    chess_count: int
    hanafuda_level: int
    dense_items: bool
    full_moon: bool
    prefer_joker: bool
    prefer_card_tiles: bool
    prefer_length: bool
    end_colors: frozenset[str]

    def has(self, tag: str) -> bool:
        return bool(getattr(self, tag, False))

    @property
    def tags(self) -> frozenset[str]:
        names = (
            "needs_digit_start",
            "needs_item_cover",
            "needs_suit_diverse_ends",
            "rewards_chess_takes",
            "rewards_hanafuda_hand",
            "rewards_long_word",
            "rewards_high_letter_count",
            "rewards_number_tiles",
            "rewards_all_number_tiles",
            "has_path_order_mult",
            "has_setup_npv",
            "bounds_unsafe",
        )
        return frozenset(n for n in names if getattr(self, n))

    def side_slice_budgets(self, main_span: float) -> tuple[float, float, float, float]:
        """Return (digit_slice, number_cover_slice, item_slice, chess_slice) seconds.

        Computed fresh from this solve's tags + main_span — no cross-F8 cache.
        When Lab Coat / Abacus reward numbers, digit_slice shrinks so a mixed
        letter+number cover pass can compete with short digits_only locals.
        """
        if main_span < 10.0:
            return 0.0, 0.0, 0.0, 0.0
        digit_slice = 0.0
        number_cover_slice = 0.0
        item_slice = 0.0
        chess_slice = 0.0
        if self.needs_digit_start and self.number_count > 0:
            digit_slice = min(14.0, main_span * 0.30)
            if self.rewards_number_tiles and self.number_count >= 3:
                # Split: short digit locals vs letter-bridged number cover.
                number_cover_slice = min(10.0, main_span * 0.18)
                digit_slice = min(digit_slice, main_span * 0.16)
        if self.needs_item_cover and self.item_count >= 2:
            if self.full_moon and not self.dense_items:
                item_slice = min(4.0, main_span * 0.08)
            else:
                item_slice = min(10.0, main_span * 0.20)
        if self.rewards_chess_takes and self.chess_count >= 2:
            chess_slice = min(4.0, main_span * 0.08)
        max_side = main_span * 0.45
        side = digit_slice + number_cover_slice + item_slice + chess_slice
        if side > max_side and side > 0:
            scale = max_side / side
            digit_slice *= scale
            number_cover_slice *= scale
            item_slice *= scale
            chess_slice *= scale
        letter_floor = min(22.0, main_span * 0.55)
        side = digit_slice + number_cover_slice + item_slice + chess_slice
        if main_span - side < letter_floor and side > 0:
            scale = max(0.0, main_span - letter_floor) / side
            digit_slice *= scale
            number_cover_slice *= scale
            item_slice *= scale
            chess_slice *= scale
        return digit_slice, number_cover_slice, item_slice, chess_slice


def _scan_inventory_rules(
    loadout: Loadout,
    rules: dict,
) -> tuple[bool, bool, bool, bool, bool, bool, bool, bool, bool]:
    """Flags derived from catalog rule types/conditions."""
    needs_suit = False
    rewards_chess = False
    rewards_hanafuda = False
    rewards_long = False
    rewards_letter_count = False
    rewards_number = False
    rewards_all_numbers = False
    path_order_mult = False
    setup_npv = False

    for bucket, items in (("stickers", loadout.stickers), ("stamps", loadout.stamps)):
        for item in items:
            _key, rule = get_rule(rules, bucket, item.id or "", item.name or "")
            if not rule:
                continue
            effect = str(rule.get("type") or "")
            cond = str(rule.get("condition") or "")
            target = str(rule.get("target") or "").strip().lower()
            rid = (item.id or "").strip().lower()
            if cond == "word_starts_ends_different_suit" or rid == "wrestlers":
                needs_suit = True
            if effect in ("chess_take_word_bonus", "movie_camera_word_bonus") or (
                "chess" in cond and "take" in cond
            ):
                rewards_chess = True
            if effect == "card_hand_word_bonus" or rid == "hanafuda":
                rewards_hanafuda = True
            if effect == "word_length_bonus" or cond.startswith(
                ("path_length_gte:", "word_length_gte:")
            ):
                rewards_long = True
            if effect in (
                "multiply_word_by_high_letter_count",
                "tile_multiply_by_letter_count",
            ) or rid in ("banana", "bubble_tea"):
                rewards_letter_count = True
            # Lab Coat: tile_multiply target number; Full Battery: by number count.
            if effect == "tile_multiply" and target == "number":
                rewards_number = True
                rewards_all_numbers = True
            if effect == "multiply_word_by_number_count":
                rewards_number = True
                rewards_all_numbers = True
            if effect == "colored_number_tile_bonus":
                rewards_number = True
            if effect in (
                "multiply_word_scaled",
                "tile_multiply",
                "multiply_word_by_high_letter_count",
            ) and cond not in ("always", ""):
                path_order_mult = True
            if rid in (
                "birthday_cake",
                "hi_vis_jacket",
                "michaels_book",
                "michael_book",
                "red_rider",
                "tile_ninja",
            ):
                setup_npv = True

    # Abacus (and similar) live on the pin, not sticker/stamp inventory.
    pin_effect = str(
        (loadout.extras or {}).get("pin_effect", "") or ""
    ).strip()
    if pin_effect:
        _pkey, pin_rule = get_rule(rules, "pins", pin_effect, pin_effect)
        if pin_rule:
            pin_type = str(pin_rule.get("type") or "")
            if pin_type == "colored_number_tile_bonus":
                rewards_number = True
            right = pin_rule.get("right")
            if isinstance(right, dict) and str(right.get("type") or "") == (
                "colored_number_tile_bonus"
            ):
                rewards_number = True

    return (
        needs_suit,
        rewards_chess,
        rewards_hanafuda,
        rewards_long,
        rewards_letter_count,
        rewards_number,
        rewards_all_numbers,
        path_order_mult,
        setup_npv,
    )


def build_loadout_affordances(
    board: Board,
    loadout: Loadout,
    solve_ctx: SolveContext,
    graph_ctx: BoardGraphContext,
    *,
    rules: dict,
    mult_rules: list[MultRule] | None = None,
    mult_hints: MultNeighborHints | None = None,
) -> LoadoutAffordances:
    """Compile geometry/mult tags once per F8 from live board + inventory."""
    del board  # board features come from graph_ctx masks
    item_count = graph_ctx.item_mask.bit_count()
    from cursed_words_solver.graph_bitboard import CURSE_CODE_NUMBER

    number_count = 0
    for idx in range(graph_ctx.cell_count):
        if graph_ctx.active_mask & (1 << idx) and graph_ctx.curse_code[idx] == CURSE_CODE_NUMBER:
            number_count += 1
    chess_count = graph_ctx.chess_piece_mask.bit_count()
    hanafuda_level = solve_ctx.hanafuda_level or hanafuda_sticker_level(loadout)
    full_moon = flag_test(solve_ctx.search_flags, FLAG_DOUBLE_LETTER_TELEPORT)
    dense_items = item_count >= 5

    (
        needs_suit,
        rewards_chess,
        rewards_hanafuda,
        rewards_long,
        rewards_letter_count,
        rewards_number,
        rewards_all_numbers,
        path_order_mult,
        setup_npv,
    ) = _scan_inventory_rules(loadout, rules)

    if mult_rules:
        for mr in mult_rules:
            if mr.condition == "word_starts_ends_different_suit":
                needs_suit = True
            if mr.condition.startswith(("path_length_gte:", "word_length_gte:")):
                rewards_long = True
            if mr.condition not in ("always", ""):
                path_order_mult = True

    prefer_joker = bool(mult_hints and mult_hints.prefer_joker) or rewards_hanafuda
    prefer_card = bool(mult_hints and mult_hints.prefer_card_tiles) or needs_suit
    prefer_length = bool(mult_hints and mult_hints.prefer_length) or rewards_long
    end_colors = mult_hints.end_colors if mult_hints else frozenset()

    needs_digit = number_count > 0
    needs_item = item_count >= 2
    if rewards_letter_count and item_count >= 1:
        # Banana/Bubble Tea may reward repeated ITEM faces — keep item cover on.
        needs_item = True

    bounds_unsafe = (
        not solve_ctx.tier2_screen_enabled
        or setup_npv
        or solve_ctx.compound_percents is not None
        or solve_ctx.hourglass_reversed
    )

    return LoadoutAffordances(
        needs_digit_start=needs_digit,
        needs_item_cover=needs_item,
        needs_suit_diverse_ends=needs_suit,
        rewards_chess_takes=rewards_chess or chess_count >= 3,
        rewards_hanafuda_hand=rewards_hanafuda or hanafuda_level > 0,
        rewards_long_word=rewards_long or prefer_length,
        rewards_high_letter_count=rewards_letter_count,
        rewards_number_tiles=rewards_number,
        rewards_all_number_tiles=rewards_all_numbers,
        has_path_order_mult=path_order_mult,
        has_setup_npv=setup_npv,
        bounds_unsafe=bounds_unsafe,
        item_count=item_count,
        number_count=number_count,
        chess_count=chess_count,
        hanafuda_level=hanafuda_level,
        dense_items=dense_items,
        full_moon=full_moon,
        prefer_joker=prefer_joker,
        prefer_card_tiles=prefer_card,
        prefer_length=prefer_length,
        end_colors=end_colors,
    )


__all__ = [
    "LoadoutAffordances",
    "build_loadout_affordances",
    "_AFFORDANCE_TAG_DOC",
]
