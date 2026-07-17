"""Search heuristics for multiplicative scoring boosts (not game score)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.rule_lookup import SCORING_INACTIVE_TYPES, get_rule
from cursed_words_solver.rules.scoring_conditions import (
    VOWELS,
    VWXYZ,
    card_suit,
    evaluate_sticker_condition,
    first_letter_on_path,
    is_card_tile,
    is_consumable_tile,
    is_joker_tile,
    is_placed_consumable_tile,
    is_vowel_letter,
    scaled_word_multiplier,
    tile_counts_as_color,
    word_first_letter,
    word_starts_ends_different_suit,
)
from cursed_words_solver.rules.scoring_order import build_scoring_item_sequence
from cursed_words_solver.solve_context import SolveContext

MULT_EFFECT_TYPES = frozenset({"multiply_word_scaled", "tile_multiply"})
PARTIAL_MULT_WEIGHT = 0.35


@dataclass(frozen=True)
class MultRule:
    rule_id: str
    effect_type: str
    condition: str
    level: int
    rule: dict


@dataclass(frozen=True)
class MultNeighborHints:
    end_colors: frozenset[str]
    prefer_vowel_start: bool
    prefer_consonant_start: bool
    prefer_card_tiles: bool
    prefer_joker: bool
    prefer_currency: bool
    prefer_length: bool


def _rule_from_ref(rules: dict, ref) -> MultRule | None:
    if ref.kind == "grid_path":
        _key, rule = get_rule(rules, "stickers", ref.rule_id, ref.rule_id)
    elif ref.kind == "stamp":
        _key, rule = get_rule(rules, "stamps", ref.rule_id, ref.rule_id)
    elif ref.kind == "pin":
        _key, rule = get_rule(rules, "pins", ref.rule_id, ref.rule_id)
    else:
        _key, rule = get_rule(rules, "stickers", ref.rule_id, ref.rule_id)
    if not rule:
        return None
    effect = str(rule.get("type") or "")
    if effect not in MULT_EFFECT_TYPES:
        return None
    if effect in SCORING_INACTIVE_TYPES:
        return None
    return MultRule(
        rule_id=ref.rule_id,
        effect_type=effect,
        condition=str(rule.get("condition") or ""),
        level=max(1, int(ref.level)),
        rule=rule,
    )


def loadout_mult_rules(
    loadout: Loadout,
    rules: dict,
    *,
    board: Board | None = None,
    path: list[int] | None = None,
    solve_context: SolveContext | None = None,
) -> list[MultRule]:
    """Active multiply_word_scaled / tile_multiply rules in scoring order."""
    if board is None or path is None:
        from cursed_words_solver.search import _active_indices

        board = Board(tiles=[[Tile(0, 0, "a", "a", 1)] * 5 for _ in range(5)])
        active = _active_indices(board)
        path = [active[0]] if active else [0]
    if solve_context is not None:
        refs = build_scoring_item_sequence(
            board,
            path,
            loadout,
            rules,
            hourglass_reversed=solve_context.hourglass_reversed,
            inventory_refs=solve_context.inventory_refs,
        )
    else:
        refs = build_scoring_item_sequence(board, path, loadout, rules)
    out: list[MultRule] = []
    seen: set[str] = set()
    for ref in refs:
        mr = _rule_from_ref(rules, ref)
        if mr and mr.rule_id not in seen:
            seen.add(mr.rule_id)
            out.append(mr)
    return out


def _partial_mult_credit(
    condition: str,
    board: Board,
    path: list[int],
    word: str,
) -> bool:
    """True when an incomplete path already satisfies an end-local mult hint."""
    if not path:
        return False
    w = (word or "").lower()
    if condition == "ends_with_color:blue":
        return tile_counts_as_color(board.get_by_index(path[-1]), TileColor.BLUE)
    if condition == "word_starts_vowel":
        # Mirror scoring_conditions / Egg: only path[0] LETTER faces count.
        if path:
            tile0 = board.get_by_index(path[0])
            if tile0.curse != CurseType.LETTER:
                return False
            ch = (tile0.letter or tile0.char or "").strip().lower()
            return len(ch) == 1 and ch.isalpha() and is_vowel_letter(ch)
        first = word_first_letter(word)
        return bool(first) and is_vowel_letter(first)
    if condition == "word_starts_vwxyz":
        # Mirror scoring_conditions / WheezyVixen: only path[0] LETTER faces count.
        if path:
            tile0 = board.get_by_index(path[0])
            if tile0.curse != CurseType.LETTER:
                return False
            ch = (tile0.letter or tile0.char or "").strip().lower()
            return len(ch) == 1 and ch.isalpha() and ch in VWXYZ
        first = word_first_letter(word)
        return bool(first) and first in VWXYZ
    if condition == "word_starts_consonant":
        return bool(w) and w[0] not in VOWELS and w[0].isalpha()
    if condition == "word_starts_ends_different_suit" and len(path) >= 2:
        start = card_suit(board.get_by_index(path[0]))
        end = card_suit(board.get_by_index(path[-1]))
        if start and end and start != end:
            return True
        if start and is_joker_tile(board.get_by_index(path[-1])):
            return True
    if condition == "word_starts_ends_number":
        start = board.get_by_index(path[0])
        end = board.get_by_index(path[-1])
        return start.curse == CurseType.NUMBER and end.curse == CurseType.NUMBER
    if condition == "word_starts_ends_consumable" and len(path) >= 1:
        start = board.get_by_index(path[0])
        if is_consumable_tile(start) or is_placed_consumable_tile(start):
            return True
    return False


def optimistic_mult_factor(
    loadout: Loadout,
    board: Board,
    path: list[int],
    word: str,
    rules: dict,
    mult_rules: list[MultRule] | None = None,
) -> float:
    """Product of expected ×WORD / tile mult factors for search ranking."""
    if mult_rules is None:
        mult_rules = loadout_mult_rules(loadout, rules, board=board, path=path)
    product = 1.0
    for mr in mult_rules:
        cond = mr.condition
        met = False
        if word and len(path) >= 1:
            met = evaluate_sticker_condition(
                cond,
                board,
                path,
                word,
                loadout,
                applying_sticker_id=mr.rule_id,
            )
        partial = not met and _partial_mult_credit(cond, board, path, word)
        if not met and not partial:
            if cond == "always":
                met = True
            else:
                continue
        if mr.effect_type == "multiply_word_scaled":
            factor = scaled_word_multiplier(mr.level, mr.rule, loadout, path)
            if factor <= 1.0:
                continue
            if partial and not met:
                factor = 1.0 + (factor - 1.0) * PARTIAL_MULT_WEIGHT
            product *= factor
        elif mr.effect_type == "tile_multiply" and met:
            factor = scaled_word_multiplier(mr.level, mr.rule, loadout, path)
            if factor > 1.0:
                product *= factor
    return product


def search_rank_score(
    immediate: float,
    mult_factor: float,
    *,
    mult_weight: float,
    setup_bonus: float = 0.0,
) -> float:
    """Heap ranking score; does not change displayed game score."""
    if mult_weight <= 0 or mult_factor <= 1.0:
        return immediate + setup_bonus
    return immediate + mult_weight * immediate * (mult_factor - 1.0) + setup_bonus


def build_mult_neighbor_hints(mult_rules: list[MultRule]) -> MultNeighborHints:
    end_colors: set[str] = set()
    prefer_vowel = False
    prefer_consonant = False
    prefer_card = False
    prefer_joker = False
    prefer_currency = False
    prefer_length = False
    for mr in mult_rules:
        cond = mr.condition
        if cond.startswith("ends_with_color:"):
            end_colors.add(cond.split(":", 1)[1].lower())
        elif cond == "word_starts_vowel":
            prefer_vowel = True
        elif cond in ("word_starts_consonant", "word_starts_non_vowel"):
            prefer_consonant = True
        elif cond in (
            "word_starts_ends_different_suit",
            "card_hand:pair",
            "card_hand:flush",
        ):
            prefer_card = True
        elif "joker" in cond or mr.rule_id in ("hanafuda", "wrestlers", "poker_face"):
            prefer_joker = True
        if mr.rule.get("scale_from_extras") in ("money_lost_encounter",):
            prefer_currency = True
        if cond.startswith("path_length_gte:") or cond.startswith("word_length_gte:"):
            prefer_length = True
    return MultNeighborHints(
        end_colors=frozenset(end_colors),
        prefer_vowel_start=prefer_vowel,
        prefer_consonant_start=prefer_consonant,
        prefer_card_tiles=prefer_card,
        prefer_joker=prefer_joker,
        prefer_currency=prefer_currency,
        prefer_length=prefer_length,
    )


def neighbor_mult_priority(
    board: Board,
    path: list[int],
    idx: int,
    hints: MultNeighborHints,
    *,
    letter_pos: int,
) -> int:
    """Lower is better (sorted before base_score tie-break)."""
    tile = board.get_by_index(idx)
    priority = 5
    if hints.end_colors:
        color_name = tile.color.value.lower() if tile.color != TileColor.UNKNOWN else ""
        if color_name in hints.end_colors:
            priority = 0
    if hints.prefer_vowel_start and letter_pos == 0:
        ch = (tile.letter or tile.char or "").lower()[:1]
        if ch in VOWELS:
            priority = min(priority, 1)
    if hints.prefer_consonant_start and letter_pos == 0:
        ch = (tile.letter or tile.char or "").lower()[:1]
        if ch.isalpha() and ch not in VOWELS:
            priority = min(priority, 1)
    if hints.prefer_card_tiles and is_card_tile(tile):
        priority = min(priority, 2)
    if hints.prefer_joker and is_joker_tile(tile):
        priority = min(priority, 1)
    if hints.prefer_currency and tile.char in ("$", "€", "£", "¥"):
        priority = min(priority, 2)
    if hints.prefer_length:
        priority = min(priority, 3)
    return priority


@lru_cache(maxsize=1)
def _default_rules() -> dict:
    from cursed_words_solver.rules.boss_effects import load_rules_catalog

    return load_rules_catalog()


def guaranteed_mult_factor(mult_rules: list[MultRule], loadout: Loadout, path: list[int]) -> float:
    """Conservative mult product for pruning (only conditions that always fire)."""
    product = 1.0
    for mr in mult_rules:
        if mr.effect_type != "multiply_word_scaled":
            continue
        if mr.condition not in ("always", ""):
            continue
        factor = scaled_word_multiplier(mr.level, mr.rule, loadout, path)
        if factor > 1.0:
            product *= factor
    return product


def optimistic_mult_upper_bound(
    mult_rules: list[MultRule],
    loadout: Loadout,
    path: list[int],
) -> float:
    """Product of all mult factors assuming every rule fires (tier-2 screen upper bound)."""
    product = 1.0
    for mr in mult_rules:
        factor = scaled_word_multiplier(mr.level, mr.rule, loadout, path)
        if factor <= 1.0:
            continue
        if mr.effect_type in MULT_EFFECT_TYPES:
            product *= factor
    return product
