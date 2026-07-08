"""Simulate consumable rack placements (Sandy boss, Mahjong pin, target-score rescue)."""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter
from dataclasses import dataclass
from itertools import combinations, count, permutations
from typing import Any, Iterator

from cursed_words_solver.loadout import _resolve_letter_for_word
from cursed_words_solver.models import (
    CURRENCY_MAP,
    Board,
    CurseType,
    Loadout,
    Tile,
    TileColor,
    WordResult,
    curse_type_from_key,
    normalize_tile_glyph,
)
from cursed_words_solver.rules.base_scoring import tile_base_contribution
from cursed_words_solver.rules.grid_effects import _clone_board
from cursed_words_solver.rules.rule_lookup import get_pin_scoring_rule, resolve_rule_id
from cursed_words_solver.rules.scoring_conditions import (
    mahjong_consumable_factor,
    placed_consumable_indices,
    word_starts_ends_consumable,
)
from cursed_words_solver.rules.fraction_tiles import (
    attach_fraction_metadata,
    format_fraction_text,
    format_fraction_tile,
)
from cursed_words_solver.search import (
    WordSearcher,
    _paths_between_indices,
    neighbors_from_tile,
)

_ENDPOINT_PATH_MAX_LEN = 10
_ENDPOINT_PAIR_MIN = 8
_UC_SCREEN_RANK_BUMP = 1_000_000.0

_COLOR_MAP: dict[str, TileColor] = {
    "colorless": TileColor.COLORLESS,
    "red": TileColor.RED,
    "blue": TileColor.BLUE,
    "shiny": TileColor.SHINY,
    "void": TileColor.VOID,
    "purple": TileColor.PURPLE,
    "white": TileColor.WHITE,
    "gold": TileColor.GOLD,
    "pink": TileColor.PINK,
    "green": TileColor.GREEN,
    "cactus": TileColor.CACTUS,
    "glitch": TileColor.GLITCH,
}


@dataclass(frozen=True)
class ConsumablePlacement:
    """Suggested rack tile placement on the board grid."""

    row: int
    col: int
    index: int
    letter: str
    rack_index: int = -1


@dataclass
class PlacementSearchStats:
    """Timing and counts from the last placement search."""

    variant_gen_sec: float = 0.0
    variant_screen_sec: float = 0.0
    variant_refine_sec: float = 0.0
    variants_screened: int = 0
    rack_slots_screened: int = 0
    best_screened_rank: float = -1.0
    threshold_rank: float | None = None
    adopted: bool = False


_last_placement_search_stats = PlacementSearchStats()


def last_placement_search_stats() -> PlacementSearchStats:
    return _last_placement_search_stats


def is_sandy_saguaro_boss(loadout: Loadout, rules: dict[str, Any]) -> bool:
    key = resolve_rule_id(
        rules,
        "bosses",
        loadout.boss_id or "",
        loadout.boss_name or "",
    )
    return key == "sandy_saguaro"


def has_mahjong_pin(loadout: Loadout, rules: dict[str, Any]) -> bool:
    pin = str((loadout.extras or {}).get("pin_effect", "") or "").strip()
    if not pin:
        return False
    key = resolve_rule_id(rules, "pins", pin, pin)
    return key == "mahjong_red_dragon"


def mandatory_consumable_indices(
    loadout: Loadout,
    board: Board,
    rules: dict[str, Any],
) -> frozenset[int]:
    """Sandy Saguaro: placed consumables must appear in the submitted word."""
    if not is_sandy_saguaro_boss(loadout, rules):
        return frozenset()
    return placed_consumable_indices(board)


def target_rescue_worth_trying(
    baseline_score: float,
    target: int,
    rack_tiles: list[Tile],
    loadout: Loadout | None = None,
) -> bool:
    if target <= 0 or not rack_tiles:
        return False
    if loadout is not None:
        from cursed_words_solver.rules.quest_scoring import (
            target_rescue_worth_trying_quest,
        )

        return target_rescue_worth_trying_quest(baseline_score, target, loadout)
    return baseline_score < target


def _parse_consumable_rack_raw(loadout: Loadout) -> list[dict[str, Any]]:
    raw = (loadout.extras or {}).get("consumable_rack")
    if raw is None:
        return []
    rows: list[Any]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            rows = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            rows = []
    elif isinstance(raw, list):
        rows = raw
    else:
        rows = []
    return [entry for entry in rows if isinstance(entry, dict)]


def _placement_letter_for_tile(tile: Tile) -> str:
    if tile.curse == CurseType.FRACTION:
        return format_fraction_tile(tile)
    letter = (tile.letter or "").strip()
    if letter and letter != "?":
        glyph = normalize_tile_glyph(letter)
        if glyph in CURRENCY_MAP:
            return CURRENCY_MAP[glyph]
        if len(letter) == 1 and letter.isalpha():
            return letter.upper()
        return letter
    char = normalize_tile_glyph(tile.char or "")
    if char in CURRENCY_MAP:
        return CURRENCY_MAP[char]
    if len(char) == 1 and char.isalpha():
        return char.upper()
    if tile.curse == CurseType.WILDCARD:
        return "?"
    return char or "?"


def placement_record_display_letter(
    rec: ConsumablePlacement | dict[str, Any],
) -> str:
    """Overlay/terminal label; keeps fraction glyphs, uppercases single letters."""
    if isinstance(rec, dict):
        raw = str(rec.get("letter", "?")).strip()
    else:
        raw = str(rec.letter).strip()
    formatted = format_fraction_text(raw)
    if formatted:
        return formatted
    if len(raw) == 1 and raw.isalpha():
        return raw.upper()
    return raw


def rack_tile_from_entry(entry: dict[str, Any]) -> Tile | None:
    curse_key = str(entry.get("curse", "letter") or "letter").lower()
    if curse_key == "fraction":
        display_raw = str(
            entry.get("char_display")
            or entry.get("char")
            or entry.get("letter")
            or ""
        ).strip()
    else:
        display_raw = str(
            entry.get("letter") or entry.get("char_display") or ""
        ).strip()
    if not display_raw:
        return None
    color_key = str(entry.get("color", "colorless") or "colorless").lower()
    color = _COLOR_MAP.get(color_key, TileColor.UNKNOWN)
    curse = curse_type_from_key(curse_key)
    try:
        base_score = float(entry.get("base_score", 1) or 1)
    except (TypeError, ValueError):
        base_score = 1.0
    meta: dict[str, Any] = {"source": "consumable_rack"}
    rack_index = entry.get("rack_index")
    if rack_index is not None:
        try:
            meta["rack_index"] = int(rack_index)
        except (TypeError, ValueError):
            pass
    cactus_growth = entry.get("cactus_growth")
    if cactus_growth is not None:
        try:
            meta["cactus_growth"] = int(cactus_growth)
        except (TypeError, ValueError):
            pass
    card_suit_raw = entry.get("card_suit")
    if card_suit_raw:
        meta["card_suit"] = str(card_suit_raw).strip().lower()
    card_rank_raw = entry.get("card_rank")
    if card_rank_raw is not None:
        meta["card_rank"] = str(card_rank_raw).strip().upper()[:1]
    if entry.get("is_joker") in (True, "true", "True", "1", 1):
        meta["is_joker"] = True
    fraction_value = entry.get("fraction_value")
    try:
        frac_val = float(fraction_value) if fraction_value is not None else None
    except (TypeError, ValueError):
        frac_val = None
    display_norm = normalize_tile_glyph(display_raw)
    if curse == CurseType.FRACTION:
        ch = display_raw
        letter = ch
    elif curse == CurseType.CURRENCY:
        ch = display_norm or display_raw
        letter = _resolve_letter_for_word(ch, display_raw, curse)
    elif len(display_raw) == 1:
        ch = display_raw.upper()
        letter = ch
    else:
        ch = display_raw
        letter = _resolve_letter_for_word(ch, display_raw, curse)
    tile = Tile(
        row=-1,
        col=-1,
        char=ch,
        letter=letter,
        base_score=base_score,
        color=color,
        curse=curse,
        fraction_value=frac_val,
        metadata=meta,
    )
    if curse == CurseType.FRACTION:
        attach_fraction_metadata(tile)
    return tile


def consumable_rack_tiles(
    loadout: Loadout,
    *,
    cactus_only: bool = False,
) -> list[Tile]:
    out: list[Tile] = []
    for entry in _parse_consumable_rack_raw(loadout):
        tile = rack_tile_from_entry(entry)
        if tile is None:
            continue
        if cactus_only and tile.color != TileColor.CACTUS:
            continue
        out.append(tile)
    return out


def effective_consumable_rack_tiles(loadout: Loadout) -> list[Tile]:
    """Rack tiles from melmod consumable_rack JSON (all colors)."""
    return consumable_rack_tiles(loadout, cactus_only=False)


def _tile_ninja_used_count_from_extras(extras: dict[str, Any]) -> int:
    from cursed_words_solver.loadout import tile_ninja_placement_baseline_used

    return tile_ninja_placement_baseline_used(extras)


def _sync_tile_ninja_bonus_from_used(extras: dict[str, Any], used: int) -> None:
    if used < 0:
        return
    bonus = used * 0.02
    serialized = str(bonus)
    extras["tile_ninja_consumables_used"] = str(used)
    extras["tile_ninja_bonus"] = serialized
    extras["tile_ninja_bonus_last_known"] = serialized
    extras["tile_ninja_word_bonus_percent"] = str(120 + used * 2)


def loadout_after_consumable_placements(loadout: Loadout, num_placed: int) -> Loadout:
    """Loadout whose consumable rack count reflects ``num_placed`` consumables placed.

    Hi Vis Jacket multiplies by the consumables the player still owns and drops one
    on submit (decompiled ``HiVisJacket.ApplyWordBonus``). Placing a consumable on
    the board removes it from the rack, so the multiplier must use the
    post-placement count. The solver otherwise scores placed boards with the
    pre-placement count, over-multiplying (e.g. x4.0 with 5 instead of x3.4 with 4).

    Tile Ninja: mirror stamp ``ConsumableTilesUsed`` (+0.02 per placement) so
    simulated boards do not collapse to a lone +0.02 path bump when rack drops
    below five.
    """
    from dataclasses import replace

    from cursed_words_solver.rules.scoring_conditions import consumable_rack_count
    from cursed_words_solver.rules.stamp_behaviors import loadout_has_stamp

    if num_placed <= 0:
        return loadout
    remaining = max(0, consumable_rack_count(loadout) - int(num_placed))
    new_extras = dict(loadout.extras or {})
    new_extras["consumable_rack_count"] = remaining
    if loadout_has_stamp(loadout, "tile_ninja"):
        used = _tile_ninja_used_count_from_extras(new_extras) + int(num_placed)
        _sync_tile_ninja_bonus_from_used(new_extras, used)
    return replace(loadout, extras=new_extras)


def consumable_placement_count_on_board(board: Board) -> int:
    """Number of placed-consumable tiles on ``board`` (``was_consumable`` metadata)."""
    count = 0
    for idx in range(25):
        if not board.is_active_index(idx):
            continue
        tile = board.get_by_index(idx)
        if bool((tile.metadata or {}).get("was_consumable")):
            count += 1
    return count


def count_new_path_consumables(
    base_board: Board,
    scoring_board: Board,
    path: list[int],
) -> int:
    """Path tiles newly marked ``was_consumable`` on ``scoring_board`` vs ``base_board``."""
    count = 0
    for idx in path:
        if not scoring_board.is_active_index(idx):
            continue
        scoring_tile = scoring_board.get_by_index(idx)
        if not bool((scoring_tile.metadata or {}).get("was_consumable")):
            continue
        if not base_board.is_active_index(idx):
            count += 1
            continue
        base_tile = base_board.get_by_index(idx)
        if not bool((base_tile.metadata or {}).get("was_consumable")):
            count += 1
    return count


def consumables_placed_for_scoring(
    base_board: Board,
    scoring_board: Board,
    path: list[int],
    placement_records: list[ConsumablePlacement] | None,
) -> int:
    """Rack consumables placed for F8 rescore (max of board diff, records, path)."""
    from_board = consumable_placement_count_on_board(
        scoring_board
    ) - consumable_placement_count_on_board(base_board)
    from_records = len(placement_records or [])
    from_path = count_new_path_consumables(base_board, scoring_board, path)
    return max(from_board, from_records, from_path)


def has_exported_consumable_rack(loadout: Loadout) -> bool:
    return len(effective_consumable_rack_tiles(loadout)) > 0


def sandy_requires_rack_export(
    loadout: Loadout,
    board: Board,
    rules: dict[str, Any],
) -> bool:
    """Sandy fight with unplaced consumables but no F7 rack export."""
    if not is_sandy_saguaro_boss(loadout, rules):
        return False
    if placed_consumable_indices(board):
        return False
    return not has_exported_consumable_rack(loadout)


def _is_first_grid_of_encounter(loadout: Loadout) -> bool:
    first = (loadout.extras or {}).get("is_first_grid_of_encounter")
    if first is False or str(first).lower() == "false":
        return False
    return True


def rack_requires_export(
    loadout: Loadout,
    board: Board,
    rules: dict[str, Any],
) -> bool:
    """Poll melmod when rack export is expected but missing."""
    if placed_consumable_indices(board):
        return False
    if sandy_requires_rack_export(loadout, board, rules):
        return True
    if has_exported_consumable_rack(loadout):
        return False
    from cursed_words_solver.rules.scoring_conditions import consumable_rack_count

    return consumable_rack_count(loadout) > 0


def wait_for_rack_export(
    loadout: Loadout,
    board: Board,
    rules: dict[str, Any],
    *,
    reload_loadout: Any,
    timeout_sec: float = 5.0,
    poll_sec: float = 0.1,
) -> Loadout:
    """Poll run_state until melmod auto-export writes consumable_rack (or timeout)."""
    import time

    if not rack_requires_export(loadout, board, rules):
        return loadout
    deadline = time.monotonic() + max(0.0, timeout_sec)
    while time.monotonic() < deadline:
        time.sleep(poll_sec)
        fresh = reload_loadout()
        if fresh is not None and not rack_requires_export(fresh, board, rules):
            return fresh
    return loadout


def wait_for_sandy_rack_export(
    loadout: Loadout,
    board: Board,
    rules: dict[str, Any],
    *,
    reload_loadout: Any,
    timeout_sec: float = 5.0,
    poll_sec: float = 0.1,
) -> Loadout:
    """Backward-compatible alias for wait_for_rack_export."""
    return wait_for_rack_export(
        loadout,
        board,
        rules,
        reload_loadout=reload_loadout,
        timeout_sec=timeout_sec,
        poll_sec=poll_sec,
    )


def sandy_placement_search_active(
    loadout: Loadout,
    board: Board,
    rules: dict[str, Any],
) -> bool:
    if not is_sandy_saguaro_boss(loadout, rules):
        return False
    if placed_consumable_indices(board):
        return False
    return len(consumable_rack_tiles(loadout, cactus_only=True)) > 0


def remaining_rack_tiles(loadout: Loadout, board: Board) -> list[Tile]:
    """Rack tiles not yet represented as placed consumables on the board."""
    rack = effective_consumable_rack_tiles(loadout)
    if not rack:
        return []
    placed = placed_consumable_indices(board)
    if not placed:
        return rack

    used_rack_indices: set[int] = set()
    for idx in placed:
        tile = board.get_by_index(idx)
        raw = tile.metadata.get("rack_index")
        if raw is not None:
            try:
                used_rack_indices.add(int(raw))
            except (TypeError, ValueError):
                pass

    if used_rack_indices:
        out: list[Tile] = []
        for rt in rack:
            raw = rt.metadata.get("rack_index")
            try:
                ri = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                ri = None
            if ri is not None and ri in used_rack_indices:
                continue
            out.append(rt)
        return out

    placed_letters = Counter(
        (board.get_by_index(i).letter or "").upper() for i in placed
    )
    remaining: list[Tile] = []
    for rt in rack:
        letter = (rt.letter or "").upper()
        if placed_letters.get(letter, 0) > 0:
            placed_letters[letter] -= 1
            continue
        remaining.append(rt)
    return remaining


def rack_placement_search_active(
    loadout: Loadout,
    board: Board,
    rules: dict[str, Any],
) -> bool:
    """Score-boost placement search when unplaced rack tiles remain (any character)."""
    if sandy_placement_search_active(loadout, board, rules):
        return False
    return len(remaining_rack_tiles(loadout, board)) > 0


def consumable_investment_active(loadout: Loadout) -> bool:
    """True when loadout rewards placing consumables for future grids (Tile Ninja, Hi Vis)."""
    for item in loadout.stamps:
        if (item.id or "").lower() == "tile_ninja":
            return True
    for item in loadout.stickers:
        if (item.id or "").lower() == "hi_vis_jacket":
            return True
    return False


def under_construction_active(loadout: Loadout) -> bool:
    """True when Under Construction rewards words starting and ending on consumables."""
    for item in loadout.stickers:
        if (item.id or "").lower() == "under_construction":
            return True
    return False


def multi_consumable_placement_beneficial(loadout: Loadout) -> bool:
    """True when placing multiple consumables is worth exploring (investment or endpoints)."""
    return consumable_investment_active(loadout) or under_construction_active(
        loadout
    )


def _result_rank_score(result: WordResult) -> float:
    """Search ranking score for a placement candidate (includes setup bonus)."""
    if result.rank_score > 0:
        return result.rank_score
    return result.score + result.setup_bonus


def _quest_rank_score(result: WordResult, loadout: Loadout | None) -> float:
    from cursed_words_solver.rules.quest_scoring import search_rank_for_quest

    return search_rank_for_quest(_result_rank_score(result), loadout)


def _variant_meets_threshold(
    result: WordResult,
    *,
    min_score: float | None,
    min_rank_score: float | None,
    loadout: Loadout | None = None,
) -> bool:
    if min_rank_score is not None:
        rank = _result_rank_score(result)
        if loadout is not None:
            from cursed_words_solver.rules.quest_scoring import search_rank_for_quest

            return search_rank_for_quest(rank, loadout) >= min_rank_score
        return rank >= min_rank_score
    if min_score is not None:
        return result.score >= min_score
    return True


def mahjong_rack_placement_active(
    loadout: Loadout,
    board: Board,
    rules: dict[str, Any],
) -> bool:
    """Backward-compatible alias for rack_placement_search_active."""
    return rack_placement_search_active(loadout, board, rules)


def _active_indices(board: Board) -> list[int]:
    return [i for i in range(25) if board.is_active_index(i)]


def _placement_hard_from_loadout(loadout: Loadout | None) -> bool:
    if loadout is None:
        return False
    from cursed_words_solver.rules.quest_effects import quest_constraints

    if quest_constraints(loadout).require_center_index is not None:
        return True
    from cursed_words_solver.rules.boss_effects import boss_modifier_active

    if boss_modifier_active(loadout, "cobra"):
        return True
    for key in ("cobra_min_length", "encounter_min_word_length"):
        try:
            if int((loadout.extras or {}).get(key, 0) or 0) >= 7:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _placement_search_hard(
    searcher: WordSearcher,
    loadout: Loadout | None,
) -> bool:
    """True when placement screening needs longer per-variant search budgets."""
    if loadout is not None:
        from cursed_words_solver.rules.quest_effects import quest_constraints

        if quest_constraints(loadout).require_center_index is not None:
            return True
    if _placement_hard_from_loadout(loadout):
        return True
    min_len = int(getattr(searcher.validator, "min_len", 1) or 1)
    return min_len >= 7


def _placement_screen_floor(*, investment: bool, hard: bool) -> float:
    if hard:
        return 2.0
    return 0.5 if investment else 0.25


def _screen_variant_limit(
    screen_share: float,
    screen_floor: float,
    screen_cap: int,
) -> int:
    by_budget = max(1, int(screen_share / screen_floor))
    return min(screen_cap, by_budget)


def _rack_index_sort_key(tile: Tile) -> int:
    raw = tile.metadata.get("rack_index")
    try:
        return int(raw) if raw is not None else 999
    except (TypeError, ValueError):
        return 999


def _distinct_rack_slots_screened(
    screened: list[tuple[float, int, list[tuple[int, Tile]], Board, WordResult]],
) -> int:
    slots: set[int] = set()
    for _, _, placements, _, _ in screened:
        for _, tile in placements:
            raw = tile.metadata.get("rack_index")
            if raw is None:
                continue
            try:
                slots.add(int(raw))
            except (TypeError, ValueError):
                pass
    return len(slots)


def format_placement_search_stats_line() -> str:
    """One-line summary of the last placement search for terminal logging."""
    stats = last_placement_search_stats()
    if stats.variants_screened <= 0:
        return "Consumable placement: no variants screened"
    best = (
        f", best rank {int(stats.best_screened_rank)}"
        if stats.best_screened_rank >= 0
        else ""
    )
    adopted = " — adopted" if stats.adopted else ""
    rack_slots = (
        f" across {stats.rack_slots_screened} rack tile(s)"
        if stats.rack_slots_screened > 0
        else ""
    )
    return (
        f"Consumable placement: screened {stats.variants_screened} variants"
        f"{rack_slots}{best}{adopted}"
    )


def _mahjong_tile_value(
    rack_tile: Tile,
    loadout: Loadout | None,
    rules: dict[str, Any] | None,
) -> float:
    value = float(tile_base_contribution(rack_tile))
    if loadout is None or rules is None:
        return value
    if not has_mahjong_pin(loadout, rules):
        return value
    pin_rule = get_pin_scoring_rule(rules, "mahjong_red_dragon") or {}
    return value * mahjong_consumable_factor(loadout, pin_rule)


def _consumable_investment_cell_bonus(
    rack_tile: Tile,
    loadout: Loadout | None,
) -> float:
    if loadout is None:
        return 0.0
    bonus = 0.0
    if any((item.id or "").lower() == "tile_ninja" for item in loadout.stamps):
        bonus += 8.0
    if any((item.id or "").lower() == "hi_vis_jacket" for item in loadout.stickers):
        bonus += float(tile_base_contribution(rack_tile)) * 0.25
    return bonus


def _cell_letter_connectivity(board: Board, idx: int, rack_tile: Tile) -> float:
    letter = (rack_tile.letter or "").strip().lower()
    connectivity = 0.0
    for nbr in neighbors_from_tile(board, [idx], {idx}):
        ntile = board.get_by_index(nbr)
        nl = (ntile.letter or ntile.char or "").strip().lower()
        if letter and nl and len(nl) == 1 and nl.isalpha():
            connectivity += 1.0
    return connectivity


def _cells_have_path_between(board: Board, start: int, end: int) -> bool:
    if start == end:
        return False
    cap = _ENDPOINT_PATH_MAX_LEN
    if _paths_between_indices(board, start, end, cap, path_cap=1):
        return True
    return bool(_paths_between_indices(board, end, start, cap, path_cap=1))


def _screened_entry_rank(
    rank: float,
    sim_board: Board,
    result: WordResult,
    loadout: Loadout,
) -> float:
    """Boost screened ordering when Under Construction endpoints are satisfied."""
    if (
        under_construction_active(loadout)
        and result.path
        and word_starts_ends_consumable(sim_board, result.path)
    ):
        return rank + _UC_SCREEN_RANK_BUMP
    return rank


def _endpoint_placement_variants_for_tier(
    board: Board,
    rack_tiles: list[Tile],
    cells: list[int],
    *,
    tier_cap: int,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
    gen_deadline: float | None = None,
) -> list[list[tuple[int, Tile]]]:
    """k=2 variants where both cells can serve as path endpoints (Under Construction)."""
    directed_pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for i, start in enumerate(cells):
        for end in cells[i + 1 :]:
            if _cells_have_path_between(board, start, end):
                for pair in ((start, end), (end, start)):
                    if pair not in seen:
                        seen.add(pair)
                        directed_pairs.append(pair)
    if len(directed_pairs) < _ENDPOINT_PAIR_MIN:
        return []

    heap: list[tuple[float, tuple[int, ...], int, list[tuple[int, Tile]]]] = []
    seq = count()
    loop_steps = 0
    for tile_combo in combinations(rack_tiles, 2):
        if _variant_gen_past_deadline(gen_deadline):
            break
        for start, end in directed_pairs:
            if _variant_gen_past_deadline(gen_deadline):
                break
            for placements in (
                [(start, tile_combo[0]), (end, tile_combo[1])],
                [(start, tile_combo[1]), (end, tile_combo[0])],
            ):
                loop_steps += 1
                if loop_steps % _VARIANT_GEN_DEADLINE_CHECK_EVERY == 0:
                    if _variant_gen_past_deadline(gen_deadline):
                        break
                rank = _placement_rank(
                    board, placements, loadout=loadout, rules=rules
                )
                tie = (start, end)
                entry = (-rank, tie, next(seq), placements)
                if len(heap) < tier_cap:
                    heapq.heappush(heap, entry)
                elif rank > -heap[0][0]:
                    heapq.heapreplace(heap, entry)
    heap.sort(key=lambda row: (row[0], row[1]))
    return [placements for _, _, _, placements in heap]


def _endpoint_pair_bonus(
    board: Board,
    placements: list[tuple[int, Tile]],
    *,
    loadout: Loadout | None = None,
) -> float:
    """Bias k=2 variants toward viable Under Construction endpoint pairs."""
    if loadout is None or not under_construction_active(loadout):
        return 0.0
    if len(placements) != 2:
        return 0.0
    (idx_a, tile_a), (idx_b, tile_b) = placements
    if idx_a == idx_b:
        return 0.0
    conn_a = _cell_letter_connectivity(board, idx_a, tile_a)
    conn_b = _cell_letter_connectivity(board, idx_b, tile_b)
    if conn_a < 1.0 or conn_b < 1.0:
        return 0.0
    return 15.0 + conn_a + conn_b


def _placement_cell_score(
    board: Board,
    idx: int,
    rack_tile: Tile,
    *,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
) -> float:
    connectivity = _cell_letter_connectivity(board, idx, rack_tile)
    tile_value = _mahjong_tile_value(rack_tile, loadout, rules)
    investment = _consumable_investment_cell_bonus(rack_tile, loadout)
    return connectivity * 10.0 + tile_value + investment


def _max_cells_for_rack_count(
    n: int,
    *,
    max_cells: int = 14,
) -> int:
    if n >= 5:
        return min(max_cells, 10)
    if n >= 4:
        return min(max_cells, 12)
    return max_cells


_VARIANT_GEN_DEADLINE_CHECK_EVERY = 256


def _variant_gen_past_deadline(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _effective_variant_gen_deadline(
    solve_deadline: float | None,
    variant_gen_started: float,
    variant_gen_budget: float | None,
) -> float | None:
    deadlines: list[float] = []
    if solve_deadline is not None:
        deadlines.append(solve_deadline)
    if variant_gen_budget is not None:
        deadlines.append(variant_gen_started + variant_gen_budget)
    if not deadlines:
        return None
    return min(deadlines)


def _tier_heap_cap(max_variants: int) -> int:
    return max(max_variants * 4, 512)


def _placement_rank(
    board: Board,
    placements: list[tuple[int, Tile]],
    *,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
) -> float:
    base = sum(
        _placement_cell_score(board, idx, tile, loadout=loadout, rules=rules)
        for idx, tile in placements
    )
    return base + _endpoint_pair_bonus(board, placements, loadout=loadout)


def _active_placement_indices(
    board: Board,
    loadout: Loadout | None = None,
) -> list[int]:
    active = _active_indices(board)
    if loadout is not None:
        from cursed_words_solver.rules.quest_effects import quest_constraints

        center = quest_constraints(loadout).require_center_index
        if center is not None:
            active = [i for i in active if i != center]
    return active


def _rank_placement_indices(
    board: Board,
    rack_tiles: list[Tile],
    *,
    max_cells: int = 14,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
) -> list[int]:
    max_cells = _max_cells_for_rack_count(len(rack_tiles), max_cells=max_cells)
    active = _active_placement_indices(board, loadout)
    if len(active) <= max_cells:
        return active
    scored: list[tuple[float, int]] = []
    for idx in active:
        cell_score = max(
            (
                _placement_cell_score(
                    board, idx, rt, loadout=loadout, rules=rules
                )
                for rt in rack_tiles
            ),
            default=0.0,
        )
        scored.append((cell_score, idx))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [idx for _, idx in scored[:max_cells]]


def _top_variants_for_tier(
    board: Board,
    rack_tiles: list[Tile],
    cells: list[int],
    k: int,
    *,
    tier_cap: int,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
    gen_deadline: float | None = None,
) -> list[list[tuple[int, Tile]]]:
    if k <= 0:
        return []
    if k == 1:
        ranked = [
            (
                _placement_cell_score(
                    board, idx, rack_tile, loadout=loadout, rules=rules
                ),
                _rack_index_sort_key(rack_tile),
                idx,
                [(idx, rack_tile)],
            )
            for rack_tile in rack_tiles
            for idx in cells
        ]
        ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
        return [placements for _, _, _, placements in ranked[:tier_cap]]

    if (
        k == 2
        and loadout is not None
        and under_construction_active(loadout)
    ):
        endpoint_variants = _endpoint_placement_variants_for_tier(
            board,
            rack_tiles,
            cells,
            tier_cap=tier_cap,
            loadout=loadout,
            rules=rules,
            gen_deadline=gen_deadline,
        )
        if endpoint_variants:
            return endpoint_variants

    heap: list[tuple[float, tuple[int, ...], int, list[tuple[int, Tile]]]] = []
    seq = count()
    loop_steps = 0
    for tile_combo in combinations(rack_tiles, k):
        if _variant_gen_past_deadline(gen_deadline):
            break
        for indices in permutations(cells, k):
            loop_steps += 1
            if loop_steps % _VARIANT_GEN_DEADLINE_CHECK_EVERY == 0:
                if _variant_gen_past_deadline(gen_deadline):
                    break
            placements = list(zip(indices, tile_combo, strict=True))
            rank = _placement_rank(
                board, placements, loadout=loadout, rules=rules
            )
            tie = tuple(placement[0] for placement in placements)
            entry = (-rank, tie, next(seq), placements)
            if len(heap) < tier_cap:
                heapq.heappush(heap, entry)
            elif rank > -heap[0][0]:
                heapq.heapreplace(heap, entry)
    heap.sort(key=lambda row: (row[0], row[1]))
    return [placements for _, _, _, placements in heap]


def _placement_variants(
    board: Board,
    rack_tiles: list[Tile],
    *,
    max_variants: int = 72,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
) -> list[list[tuple[int, Tile]]]:
    k = len(rack_tiles)
    if k == 0:
        return []
    cells = _rank_placement_indices(
        board, rack_tiles, loadout=loadout, rules=rules
    )
    tier_cap = _tier_heap_cap(max_variants) if k >= 4 else max_variants
    return _top_variants_for_tier(
        board,
        rack_tiles,
        cells,
        k,
        tier_cap=tier_cap,
        loadout=loadout,
        rules=rules,
    )[:max_variants]


def iter_placement_variants_fewest_first(
    board: Board,
    rack_tiles: list[Tile],
    *,
    max_variants: int = 96,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
) -> Iterator[list[tuple[int, Tile]]]:
    """Yield placement combos tier-by-tier (k=1 first), ranked within each tier."""
    if not rack_tiles:
        return
    cells = _rank_placement_indices(
        board, rack_tiles, loadout=loadout, rules=rules
    )
    n = len(rack_tiles)
    tier_cap = _tier_heap_cap(max_variants)
    yielded = 0
    for k in range(1, n + 1):
        for placements in _top_variants_for_tier(
            board,
            rack_tiles,
            cells,
            k,
            tier_cap=tier_cap,
            loadout=loadout,
            rules=rules,
        ):
            yield placements
            yielded += 1
            if yielded >= max_variants:
                return


def placement_variants_fewest_first(
    board: Board,
    rack_tiles: list[Tile],
    *,
    max_variants: int = 96,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
) -> list[list[tuple[int, Tile]]]:
    """Placement combos ordered by tile count (1 first), then connectivity rank."""
    return list(
        iter_placement_variants_fewest_first(
            board,
            rack_tiles,
            max_variants=max_variants,
            loadout=loadout,
            rules=rules,
        )
    )


def apply_consumable_placements(
    board: Board,
    placements: list[tuple[int, Tile]],
) -> Board:
    out = _clone_board(board)
    for idx, rack_tile in placements:
        row, col = divmod(idx, 5)
        meta = dict(rack_tile.metadata)
        meta["was_consumable"] = True
        meta["consumable"] = True
        out.tiles[row][col] = Tile(
            row=row,
            col=col,
            char=rack_tile.char,
            letter=rack_tile.letter,
            base_score=rack_tile.base_score,
            color=rack_tile.color,
            curse=rack_tile.curse,
            number_value=rack_tile.number_value,
            fraction_value=rack_tile.fraction_value,
            metadata=meta,
        )
    out._rebuild_flat_cache()
    return out


def placements_to_records(
    placements: list[tuple[int, Tile]],
) -> list[ConsumablePlacement]:
    records: list[ConsumablePlacement] = []
    for idx, tile in placements:
        row, col = divmod(idx, 5)
        rack_index = int(tile.metadata.get("rack_index", -1))
        records.append(
            ConsumablePlacement(
                row=row,
                col=col,
                index=idx,
                letter=_placement_letter_for_tile(tile),
                rack_index=rack_index,
            )
        )
    return records


def format_placement_instructions(records: list[ConsumablePlacement]) -> str:
    parts: list[str] = []
    for rec in records:
        letter = placement_record_display_letter(rec)
        parts.append(f"{letter} at row {rec.row + 1}, col {rec.col + 1}")
    return "; ".join(parts)


def _placement_record_index(rec: ConsumablePlacement | dict[str, Any]) -> int:
    if isinstance(rec, dict):
        return int(rec.get("index", -1))
    return int(rec.index)


def _placement_record_letter(rec: ConsumablePlacement | dict[str, Any]) -> str:
    return placement_record_display_letter(rec)


def format_placement_path_hints(
    path: list[int],
    records: list[ConsumablePlacement | dict[str, Any]],
) -> str:
    """Overlay hint using green path step numbers (1-based, same as board highlight)."""
    from cursed_words_solver.ui.board_geometry import placement_display_steps

    hints: list[tuple[int, str]] = []
    for step, rec in placement_display_steps(path, records):
        hints.append((step, _placement_record_letter(rec)))
    if not hints:
        return ""
    parts = [f"Place {letter} on {step}" for step, letter in hints]
    return "First: " + "; ".join(parts)


def _attach_placement_breakdown(
    results: list[WordResult],
    records: list[ConsumablePlacement],
) -> None:
    payload = [
        {
            "row": rec.row,
            "col": rec.col,
            "index": rec.index,
            "letter": rec.letter,
            "rack_index": rec.rack_index,
        }
        for rec in records
    ]
    for result in results:
        result.breakdown = dict(result.breakdown or {})
        result.breakdown["consumable_placements"] = payload


def _required_for_placements(
    placements: list[tuple[int, Tile]],
    *,
    require_placements_in_path: bool,
    base_required: frozenset[int],
) -> frozenset[int]:
    if require_placements_in_path:
        return frozenset(idx for idx, _ in placements)
    return base_required


_SCREEN_VARIANT_CAP_INVESTMENT = 32
_SCREEN_VARIANT_CAP_DEFAULT = 24


def _placement_screen_share(total_budget: float, *, investment: bool) -> float:
    share_frac = 0.38 if investment else 0.25
    cap = 16.0 if investment else 12.0
    return min(cap, max(2.0, float(total_budget)) * share_frac)


def _placement_per_screen(
    screen_share: float,
    variant_count: int,
    *,
    investment: bool,
    hard: bool = False,
) -> float:
    floor = _placement_screen_floor(investment=investment, hard=hard)
    if variant_count <= 0:
        return floor
    return max(floor, screen_share / variant_count)


def _cap_variants_for_screening(
    board: Board,
    variants: list[list[tuple[int, Tile]]],
    *,
    max_screen: int,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
) -> list[list[tuple[int, Tile]]]:
    if len(variants) <= max_screen:
        return variants
    ranked = sorted(
        variants,
        key=lambda placements: -_placement_rank(
            board, placements, loadout=loadout, rules=rules
        ),
    )
    return ranked[:max_screen]


def _placement_search_use_serial(
    searcher: WordSearcher,
    *,
    per_screen: float,
    require_placements_in_path: bool,
) -> bool:
    return per_screen < 2.0 or require_placements_in_path


def _best_screened_rank(
    screened: list[tuple[float, int, list[tuple[int, Tile]], Board, WordResult]],
) -> float:
    if not screened:
        return -1.0
    return max(row[0] for row in screened)


def _finalize_placement_search(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    screened: list[tuple[float, int, list[tuple[int, Tile]], Board, WordResult]],
    *,
    time_budget: float,
    top_n: int,
    min_score: float | None,
    min_rank_score: float | None = None,
    prefer_fewest_tiles: bool = False,
    require_placements_in_path: bool = False,
    base_required: frozenset[int],
    variant_gen_sec: float,
    variant_screen_sec: float,
    variants_screened: int,
    solve_deadline: float | None = None,
    hard: bool = False,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    global _last_placement_search_stats
    threshold = min_rank_score if min_rank_score is not None else min_score

    if not screened:
        _last_placement_search_stats = PlacementSearchStats(
            variant_gen_sec=variant_gen_sec,
            variant_screen_sec=variant_screen_sec,
            variants_screened=variants_screened,
            rack_slots_screened=_distinct_rack_slots_screened(screened),
            best_screened_rank=_best_screened_rank(screened),
            threshold_rank=float(threshold) if threshold is not None else None,
            adopted=False,
        )
        return board, [], []

    multi_consumable = multi_consumable_placement_beneficial(loadout)
    uc_active = under_construction_active(loadout)
    if prefer_fewest_tiles and min_score is not None and not multi_consumable:
        min_tiles = min(row[1] for row in screened)
        screened = [row for row in screened if row[1] == min_tiles]

    if uc_active:
        screened.sort(key=lambda row: (-row[0], -row[1]))
    else:
        screened.sort(key=lambda row: (-row[0], row[1]))
    finalists = screened[: min(12, len(screened))]

    total_budget = max(2.0, float(time_budget))
    screen_share = min(12.0, total_budget * 0.25)
    refine_share = total_budget - screen_share
    refine_floor = 2.0 if hard else 1.0
    per_refine = max(refine_floor, refine_share / len(finalists))

    best_rank = -1.0
    best_tile_count = 0 if uc_active else 999
    best_board = board
    best_records: list[ConsumablePlacement] = []
    best_results: list[WordResult] = []
    prev_budget = searcher.time_budget
    refine_started = time.monotonic()
    try:
        searcher.time_budget = per_refine
        for _score_hint, tile_count, placements, sim_board, _ in finalists:
            searcher.validator.required_consumable_indices = _required_for_placements(
                placements,
                require_placements_in_path=require_placements_in_path,
                base_required=base_required,
            )
            var_loadout = loadout_after_consumable_placements(
                loadout, len(placements)
            )
            results = searcher.find_best_words(
                sim_board,
                loadout=var_loadout,
                top_n=top_n,
                deadline=solve_deadline,
            )
            if not results:
                continue
            rank = _quest_rank_score(results[0], loadout)
            if not _variant_meets_threshold(
                results[0],
                min_score=min_score,
                min_rank_score=min_rank_score,
                loadout=loadout,
            ):
                continue
            better = rank > best_rank
            if not better and rank == best_rank:
                if uc_active and tile_count > best_tile_count:
                    better = True
                elif (
                    prefer_fewest_tiles
                    and not uc_active
                    and tile_count < best_tile_count
                ):
                    better = True
            if better:
                best_rank = rank
                best_tile_count = tile_count
                best_board = sim_board
                best_records = placements_to_records(placements)
                best_results = results
    finally:
        searcher.time_budget = prev_budget
        searcher.validator.required_consumable_indices = base_required

    variant_refine_sec = time.monotonic() - refine_started
    adopted = False
    if threshold is not None and best_rank < threshold:
        _last_placement_search_stats = PlacementSearchStats(
            variant_gen_sec=variant_gen_sec,
            variant_screen_sec=variant_screen_sec,
            variant_refine_sec=variant_refine_sec,
            variants_screened=variants_screened,
            rack_slots_screened=_distinct_rack_slots_screened(screened),
            best_screened_rank=_best_screened_rank(screened),
            threshold_rank=float(threshold) if threshold is not None else None,
            adopted=False,
        )
        return board, [], []

    if best_results:
        _attach_placement_breakdown(best_results, best_records)
        adopted = True
    _last_placement_search_stats = PlacementSearchStats(
        variant_gen_sec=variant_gen_sec,
        variant_screen_sec=variant_screen_sec,
        variant_refine_sec=variant_refine_sec,
        variants_screened=variants_screened,
        rack_slots_screened=_distinct_rack_slots_screened(screened),
        best_screened_rank=_best_screened_rank(screened),
        threshold_rank=float(threshold) if threshold is not None else None,
        adopted=adopted,
    )
    return best_board, best_records, best_results


def _screen_placement_variants(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    variants: list[list[tuple[int, Tile]]],
    *,
    per_screen: float,
    min_score: float | None,
    min_rank_score: float | None = None,
    prefer_fewest_tiles: bool = False,
    require_placements_in_path: bool = False,
    base_required: frozenset[int],
    screen_full_tier: bool = False,
    solve_deadline: float | None = None,
) -> tuple[
    list[tuple[float, int, list[tuple[int, Tile]], Board, WordResult]],
    int,
    bool,
]:
    screened: list[tuple[float, int, list[tuple[int, Tile]], Board, WordResult]] = []
    tier_qualifying = False
    prev_budget = searcher.time_budget
    variants_screened = 0
    multi_consumable = multi_consumable_placement_beneficial(loadout)
    prev_workers = searcher.search_workers
    use_serial = _placement_search_use_serial(
        searcher,
        per_screen=per_screen,
        require_placements_in_path=require_placements_in_path,
    )
    try:
        if use_serial:
            searcher.search_workers = 1
        searcher._placement_screen_pass = use_serial
        searcher.time_budget = per_screen
        for placements in variants:
            variants_screened += 1
            sim_board = apply_consumable_placements(board, placements)
            searcher.validator.required_consumable_indices = _required_for_placements(
                placements,
                require_placements_in_path=require_placements_in_path,
                base_required=base_required,
            )
            var_loadout = loadout_after_consumable_placements(
                loadout, len(placements)
            )
            results = searcher.find_best_words(
                sim_board,
                loadout=var_loadout,
                top_n=1,
                deadline=solve_deadline,
            )
            if not results:
                continue
            result = results[0]
            if not _variant_meets_threshold(
                result,
                min_score=min_score,
                min_rank_score=min_rank_score,
                loadout=loadout,
            ):
                continue
            rank = _quest_rank_score(result, loadout)
            screened.append(
                (
                    _screened_entry_rank(rank, sim_board, result, loadout),
                    len(placements),
                    placements,
                    sim_board,
                    result,
                )
            )
            tier_qualifying = True
            if (
                not screen_full_tier
                and prefer_fewest_tiles
                and not multi_consumable
                and min_score is not None
                and result.score >= min_score
            ):
                break
    finally:
        searcher.time_budget = prev_budget
        searcher.search_workers = prev_workers
        searcher._placement_screen_pass = False
        searcher.validator.required_consumable_indices = base_required
    return screened, variants_screened, tier_qualifying


def _run_placement_search(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    variants: list[list[tuple[int, Tile]]],
    *,
    time_budget: float,
    top_n: int,
    min_score: float | None = None,
    min_rank_score: float | None = None,
    prefer_fewest_tiles: bool = False,
    require_placements_in_path: bool = False,
    solve_deadline: float | None = None,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    if not variants:
        global _last_placement_search_stats
        _last_placement_search_stats = PlacementSearchStats()
        return board, [], searcher.find_best_words(
            board,
            loadout=loadout,
            top_n=top_n,
            deadline=solve_deadline,
        )

    multi_consumable = multi_consumable_placement_beneficial(loadout)
    hard = _placement_search_hard(searcher, loadout)
    screen_floor = _placement_screen_floor(investment=multi_consumable, hard=hard)
    total_budget = max(2.0, float(time_budget))
    screen_share = _placement_screen_share(total_budget, investment=multi_consumable)
    screen_cap = (
        _SCREEN_VARIANT_CAP_INVESTMENT if multi_consumable else _SCREEN_VARIANT_CAP_DEFAULT
    )
    screen_limit = _screen_variant_limit(screen_share, screen_floor, screen_cap)
    screen_variants = _cap_variants_for_screening(
        board,
        variants,
        max_screen=screen_limit,
        loadout=loadout,
        rules=searcher.scoring.rules,
    )
    per_screen = _placement_per_screen(
        screen_share,
        len(screen_variants),
        investment=multi_consumable,
        hard=hard,
    )
    base_required = searcher.validator.required_consumable_indices
    screen_started = time.monotonic()
    screened, variants_screened, _ = _screen_placement_variants(
        searcher,
        board,
        loadout,
        screen_variants,
        per_screen=per_screen,
        min_score=min_score,
        min_rank_score=min_rank_score,
        prefer_fewest_tiles=prefer_fewest_tiles,
        require_placements_in_path=require_placements_in_path,
        base_required=base_required,
        solve_deadline=solve_deadline,
    )
    variant_screen_sec = time.monotonic() - screen_started
    return _finalize_placement_search(
        searcher,
        board,
        loadout,
        screened,
        time_budget=time_budget,
        top_n=top_n,
        min_score=min_score,
        min_rank_score=min_rank_score,
        prefer_fewest_tiles=prefer_fewest_tiles,
        require_placements_in_path=require_placements_in_path,
        base_required=base_required,
        variant_gen_sec=0.0,
        variant_screen_sec=variant_screen_sec,
        variants_screened=variants_screened,
        solve_deadline=solve_deadline,
        hard=hard,
    )


def _run_tiered_placement_search(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    rack_tiles: list[Tile],
    *,
    time_budget: float,
    top_n: int,
    min_score: float | None = None,
    min_rank_score: float | None = None,
    prefer_fewest_tiles: bool = False,
    require_placements_in_path: bool = False,
    max_variants: int = 96,
    rules: dict[str, Any] | None = None,
    variant_gen_budget: float | None = None,
    solve_deadline: float | None = None,
    max_tier_override: int | None = None,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    if not rack_tiles:
        global _last_placement_search_stats
        _last_placement_search_stats = PlacementSearchStats()
        return board, [], []

    rules = rules or {}
    multi_consumable = multi_consumable_placement_beneficial(loadout)
    uc_active = under_construction_active(loadout)
    uc_only = uc_active and not consumable_investment_active(loadout)
    min_tier = 2 if uc_active else 1
    n = len(rack_tiles)
    max_tier = min(n, 2) if uc_only else n
    if max_tier_override is not None:
        max_tier = min(max_tier, max_tier_override)
    hard = _placement_search_hard(searcher, loadout)
    screen_floor = _placement_screen_floor(investment=multi_consumable, hard=hard)
    cells = _rank_placement_indices(
        board, rack_tiles, loadout=loadout, rules=rules
    )
    active_full = _active_placement_indices(board, loadout)
    cells_full = active_full if hard and len(active_full) > len(cells) else cells
    tier_cap = _tier_heap_cap(max_variants)
    if multi_consumable and n >= 4:
        tier_cap = max(tier_cap, _tier_heap_cap(max_variants + 32))

    total_budget = max(2.0, float(time_budget))
    screen_share = _placement_screen_share(total_budget, investment=multi_consumable)
    remaining_screen = screen_share
    screen_cap = (
        _SCREEN_VARIANT_CAP_INVESTMENT if multi_consumable else _SCREEN_VARIANT_CAP_DEFAULT
    )
    screen_limit = _screen_variant_limit(screen_share, screen_floor, screen_cap)

    screened: list[tuple[float, int, list[tuple[int, Tile]], Board, WordResult]] = []
    variants_screened = 0
    variant_gen_sec = 0.0
    variant_screen_sec = 0.0
    variant_gen_started = time.monotonic()
    base_required = searcher.validator.required_consumable_indices

    for k in range(1, max_tier + 1):
        if solve_deadline is not None and time.monotonic() >= solve_deadline:
            break
        tier_cells = cells_full if hard and k <= 2 else cells
        tier_started = time.monotonic()
        tier_variants = _top_variants_for_tier(
            board,
            rack_tiles,
            tier_cells,
            k,
            tier_cap=tier_cap,
            loadout=loadout,
            rules=rules,
            gen_deadline=solve_deadline,
        )
        variant_gen_sec += time.monotonic() - tier_started
        if not tier_variants:
            continue

        tier_screen_batch = _cap_variants_for_screening(
            board,
            tier_variants,
            max_screen=screen_limit,
            loadout=loadout,
            rules=rules,
        )
        per_screen = _placement_per_screen(
            remaining_screen,
            len(tier_screen_batch),
            investment=multi_consumable,
            hard=hard,
        )
        screen_started = time.monotonic()
        tier_screened, tier_count, tier_qualifying = _screen_placement_variants(
            searcher,
            board,
            loadout,
            tier_screen_batch,
            per_screen=per_screen,
            min_score=min_score,
            min_rank_score=min_rank_score,
            prefer_fewest_tiles=prefer_fewest_tiles,
            require_placements_in_path=require_placements_in_path,
            base_required=base_required,
            screen_full_tier=True,
            solve_deadline=solve_deadline,
        )
        variant_screen_sec += time.monotonic() - screen_started
        screened.extend(tier_screened)
        variants_screened += tier_count
        remaining_screen = max(
            0.0, remaining_screen - per_screen * len(tier_screen_batch)
        )

        if (
            prefer_fewest_tiles
            and not multi_consumable
            and min_score is not None
            and tier_qualifying
        ):
            break
        if variant_gen_budget is not None:
            if (
                k >= min_tier
                and time.monotonic() - variant_gen_started >= variant_gen_budget
            ):
                break

    return _finalize_placement_search(
        searcher,
        board,
        loadout,
        screened,
        time_budget=time_budget,
        top_n=top_n,
        min_score=min_score,
        min_rank_score=min_rank_score,
        prefer_fewest_tiles=prefer_fewest_tiles,
        require_placements_in_path=require_placements_in_path,
        base_required=base_required,
        variant_gen_sec=variant_gen_sec,
        variant_screen_sec=variant_screen_sec,
        variants_screened=variants_screened,
        solve_deadline=solve_deadline,
        hard=hard,
    )


def search_with_consumable_placements(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    rack_tiles: list[Tile],
    *,
    time_budget: float,
    top_n: int,
    rules: dict[str, Any] | None = None,
    solve_deadline: float | None = None,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    rules = rules or {}
    return _run_tiered_placement_search(
        searcher,
        board,
        loadout,
        rack_tiles,
        time_budget=time_budget,
        top_n=top_n,
        require_placements_in_path=True,
        max_variants=72,
        rules=rules,
        solve_deadline=solve_deadline,
    )


def search_consumable_placement_fallback(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    rack_tiles: list[Tile],
    *,
    time_budget: float,
    top_n: int,
    rules: dict[str, Any] | None = None,
    solve_deadline: float | None = None,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    """Tiered placement search when board-only DFS found no valid word."""
    rules = rules or {}
    return _run_tiered_placement_search(
        searcher,
        board,
        loadout,
        rack_tiles,
        time_budget=time_budget,
        top_n=top_n,
        require_placements_in_path=True,
        max_variants=128,
        rules=rules,
        solve_deadline=solve_deadline,
    )


def search_target_rescue(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    rack_tiles: list[Tile],
    *,
    target: int,
    time_budget: float,
    top_n: int,
    rules: dict[str, Any] | None = None,
    variant_gen_budget: float | None = None,
    solve_deadline: float | None = None,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    from cursed_words_solver.rules.quest_scoring import bullseye_active, two_wrongs_active

    rules = rules or {}
    min_score = float(target)
    if bullseye_active(loadout):
        min_score = float(target) - 0.5
    elif two_wrongs_active(loadout):
        min_score = None
    board_out, records, results = _run_tiered_placement_search(
        searcher,
        board,
        loadout,
        rack_tiles,
        time_budget=time_budget,
        top_n=top_n,
        min_score=min_score,
        prefer_fewest_tiles=True,
        rules=rules,
        variant_gen_budget=variant_gen_budget,
        solve_deadline=solve_deadline,
    )
    if bullseye_active(loadout) and results:
        from cursed_words_solver.rules.quest_scoring import target_met

        results = [
            r for r in results if target_met(float(r.score), float(target), loadout)
        ]
        if not results:
            return board, [], []
    if two_wrongs_active(loadout) and results:
        from cursed_words_solver.rules.quest_scoring import target_met

        results = [
            r for r in results if target_met(float(r.score), float(target), loadout)
        ]
        if not results:
            return board, [], []
    return board_out, records, results


def search_consumable_score_boost(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    rack_tiles: list[Tile],
    *,
    baseline_score: float,
    baseline_rank_score: float | None = None,
    time_budget: float,
    top_n: int,
    rules: dict[str, Any] | None = None,
    variant_gen_budget: float | None = None,
    solve_deadline: float | None = None,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    """Try rack placements; adopt when rank score strictly exceeds baseline."""
    if not rack_tiles:
        return board, [], []
    rules = rules or {}
    from cursed_words_solver.rules.quest_scoring import (
        quest_inverts_search_rank,
        quest_rank_beats_baseline,
        search_rank_for_quest,
    )

    baseline_rank = (
        baseline_rank_score
        if baseline_rank_score is not None
        else baseline_score
    )
    if quest_inverts_search_rank(loadout):
        min_rank = search_rank_for_quest(float(baseline_rank), loadout) - 1e-9
    else:
        min_rank = float(baseline_rank) + 1e-9
    rack_n = len(rack_tiles)
    max_variants = 96
    if multi_consumable_placement_beneficial(loadout) and rack_n >= 4:
        max_variants = 128
    elif under_construction_active(loadout) and rack_n >= 2:
        max_variants = 128
    prefer_fewest = not under_construction_active(loadout)
    if under_construction_active(loadout):
        variant_gen_budget = None
    boost_max_tier: int | None = None
    if prefer_fewest:
        boost_max_tier = (
            3 if multi_consumable_placement_beneficial(loadout) else 2
        )
    sim_board, records, results = _run_tiered_placement_search(
        searcher,
        board,
        loadout,
        rack_tiles,
        time_budget=time_budget,
        top_n=top_n,
        min_rank_score=min_rank,
        prefer_fewest_tiles=prefer_fewest,
        require_placements_in_path=True,
        rules=rules,
        variant_gen_budget=variant_gen_budget,
        max_variants=max_variants,
        solve_deadline=solve_deadline,
        max_tier_override=boost_max_tier,
    )
    if not results or not quest_rank_beats_baseline(
        _result_rank_score(results[0]), float(baseline_rank), loadout
    ):
        return board, [], []
    return sim_board, records, results
