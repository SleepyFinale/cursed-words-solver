"""Simulate consumable rack placements (Sandy boss, Mahjong pin, target-score rescue)."""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter
from dataclasses import dataclass
from itertools import combinations, count, permutations
from typing import Any, Iterator

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    Tile,
    TileColor,
    WordResult,
    curse_type_from_key,
)
from cursed_words_solver.rules.base_scoring import tile_base_contribution
from cursed_words_solver.rules.grid_effects import _clone_board
from cursed_words_solver.rules.rule_lookup import get_pin_scoring_rule, resolve_rule_id
from cursed_words_solver.rules.scoring_conditions import (
    mahjong_consumable_factor,
    placed_consumable_indices,
)
from cursed_words_solver.search import WordSearcher, neighbors_from_tile

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
    variants_screened: int = 0


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
) -> bool:
    if target <= 0 or not rack_tiles:
        return False
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


def rack_tile_from_entry(entry: dict[str, Any]) -> Tile | None:
    letter_raw = str(entry.get("letter") or entry.get("char_display") or "").strip()
    if not letter_raw:
        return None
    color_key = str(entry.get("color", "colorless") or "colorless").lower()
    curse_key = str(entry.get("curse", "letter") or "letter").lower()
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
    ch = letter_raw.upper()[:1] if len(letter_raw) == 1 else letter_raw
    return Tile(
        row=-1,
        col=-1,
        char=ch,
        letter=ch,
        base_score=base_score,
        color=color,
        curse=curse,
        metadata=meta,
    )


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


def loadout_after_consumable_placements(loadout: Loadout, num_placed: int) -> Loadout:
    """Loadout whose consumable rack count reflects ``num_placed`` consumables placed.

    Hi Vis Jacket multiplies by the consumables the player still owns and drops one
    on submit (decompiled ``HiVisJacket.ApplyWordBonus``). Placing a consumable on
    the board removes it from the rack, so the multiplier must use the
    post-placement count. The solver otherwise scores placed boards with the
    pre-placement count, over-multiplying (e.g. x4.0 with 5 instead of x3.4 with 4).
    """
    from dataclasses import replace

    from cursed_words_solver.rules.scoring_conditions import consumable_rack_count

    if num_placed <= 0:
        return loadout
    remaining = max(0, consumable_rack_count(loadout) - int(num_placed))
    new_extras = dict(loadout.extras or {})
    new_extras["consumable_rack_count"] = remaining
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
    if not has_mahjong_pin(loadout, rules):
        return False
    if not _is_first_grid_of_encounter(loadout):
        return False
    return not has_exported_consumable_rack(loadout)


def wait_for_rack_export(
    loadout: Loadout,
    board: Board,
    rules: dict[str, Any],
    *,
    reload_loadout: Any,
    timeout_sec: float = 1.5,
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
    timeout_sec: float = 1.5,
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


def mahjong_rack_placement_active(
    loadout: Loadout,
    board: Board,
    rules: dict[str, Any],
) -> bool:
    if not has_mahjong_pin(loadout, rules):
        return False
    if sandy_placement_search_active(loadout, board, rules):
        return False
    return len(remaining_rack_tiles(loadout, board)) > 0


def _active_indices(board: Board) -> list[int]:
    return [i for i in range(25) if board.is_active_index(i)]


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


def _placement_cell_score(
    board: Board,
    idx: int,
    rack_tile: Tile,
    *,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
) -> float:
    letter = (rack_tile.letter or "").strip().lower()
    connectivity = 0.0
    for nbr in neighbors_from_tile(board, [idx], {idx}):
        ntile = board.get_by_index(nbr)
        nl = (ntile.letter or ntile.char or "").strip().lower()
        if letter and nl and len(nl) == 1 and nl.isalpha():
            connectivity += 1.0
    tile_value = _mahjong_tile_value(rack_tile, loadout, rules)
    return connectivity * 10.0 + tile_value


def _max_cells_for_rack_count(n: int, *, max_cells: int = 14) -> int:
    if n >= 5:
        return min(max_cells, 10)
    if n >= 4:
        return min(max_cells, 12)
    return max_cells


def _tier_heap_cap(max_variants: int) -> int:
    return max(max_variants * 4, 512)


def _placement_rank(
    board: Board,
    placements: list[tuple[int, Tile]],
    *,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
) -> float:
    return sum(
        _placement_cell_score(board, idx, tile, loadout=loadout, rules=rules)
        for idx, tile in placements
    )


def _rank_placement_indices(
    board: Board,
    rack_tiles: list[Tile],
    *,
    max_cells: int = 14,
    loadout: Loadout | None = None,
    rules: dict[str, Any] | None = None,
) -> list[int]:
    max_cells = _max_cells_for_rack_count(len(rack_tiles), max_cells=max_cells)
    active = _active_indices(board)
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
) -> list[list[tuple[int, Tile]]]:
    if k <= 0:
        return []
    if k == 1:
        ranked = [
            (
                _placement_cell_score(
                    board, idx, rack_tiles[0], loadout=loadout, rules=rules
                ),
                [idx],
                [(idx, rack_tiles[0])],
            )
            for idx in cells
        ]
        ranked.sort(key=lambda row: (-row[0], row[1]))
        return [placements for _, _, placements in ranked[:tier_cap]]

    heap: list[tuple[float, tuple[int, ...], int, list[tuple[int, Tile]]]] = []
    seq = count()
    for tile_combo in combinations(rack_tiles, k):
        for indices in permutations(cells, k):
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
    if k == 1:
        return [[(idx, rack_tiles[0])] for idx in cells]
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
                letter=(tile.letter or tile.char or "?").upper(),
                rack_index=rack_index,
            )
        )
    return records


def format_placement_instructions(records: list[ConsumablePlacement]) -> str:
    parts: list[str] = []
    for rec in records:
        parts.append(f"{rec.letter} at row {rec.row + 1}, col {rec.col + 1}")
    return "; ".join(parts)


def _placement_record_index(rec: ConsumablePlacement | dict[str, Any]) -> int:
    if isinstance(rec, dict):
        return int(rec.get("index", -1))
    return int(rec.index)


def _placement_record_letter(rec: ConsumablePlacement | dict[str, Any]) -> str:
    if isinstance(rec, dict):
        return str(rec.get("letter", "?")).upper()
    return str(rec.letter).upper()


def format_placement_path_hints(
    path: list[int],
    records: list[ConsumablePlacement | dict[str, Any]],
) -> str:
    """Overlay hint using green path step numbers (1-based, same as board highlight)."""
    index_to_step = {idx: step for step, idx in enumerate(path, start=1)}
    hints: list[tuple[int, str]] = []
    for rec in records:
        idx = _placement_record_index(rec)
        step = index_to_step.get(idx)
        if step is not None:
            hints.append((step, _placement_record_letter(rec)))
    hints.sort(key=lambda t: t[0])
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


def _finalize_placement_search(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    screened: list[tuple[float, int, list[tuple[int, Tile]], Board, WordResult]],
    *,
    time_budget: float,
    top_n: int,
    min_score: float | None,
    prefer_fewest_tiles: bool,
    require_placements_in_path: bool,
    base_required: frozenset[int],
    variant_gen_sec: float,
    variants_screened: int,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    global _last_placement_search_stats
    _last_placement_search_stats = PlacementSearchStats(
        variant_gen_sec=variant_gen_sec,
        variants_screened=variants_screened,
    )

    if not screened:
        return board, [], []

    if prefer_fewest_tiles and min_score is not None:
        min_tiles = min(row[1] for row in screened)
        screened = [row for row in screened if row[1] == min_tiles]

    screened.sort(key=lambda row: (-row[0], row[1]))
    finalists = screened[: min(12, len(screened))]

    total_budget = max(2.0, float(time_budget))
    screen_share = min(12.0, total_budget * 0.25)
    refine_share = total_budget - screen_share
    per_refine = max(1.0, refine_share / len(finalists))

    best_score = -1.0
    best_tile_count = 999
    best_board = board
    best_records: list[ConsumablePlacement] = []
    best_results: list[WordResult] = []
    prev_budget = searcher.time_budget
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
                sim_board, loadout=var_loadout, top_n=top_n
            )
            if not results:
                continue
            score = results[0].score
            if min_score is not None and score < min_score:
                continue
            better = score > best_score or (
                prefer_fewest_tiles
                and score == best_score
                and tile_count < best_tile_count
            )
            if better:
                best_score = score
                best_tile_count = tile_count
                best_board = sim_board
                best_records = placements_to_records(placements)
                best_results = results
    finally:
        searcher.time_budget = prev_budget
        searcher.validator.required_consumable_indices = base_required

    if min_score is not None and best_score < min_score:
        return board, [], []

    if best_results:
        _attach_placement_breakdown(best_results, best_records)
    return best_board, best_records, best_results


def _screen_placement_variants(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    variants: list[list[tuple[int, Tile]]],
    *,
    per_screen: float,
    min_score: float | None,
    prefer_fewest_tiles: bool,
    require_placements_in_path: bool,
    base_required: frozenset[int],
    screen_full_tier: bool = False,
) -> tuple[
    list[tuple[float, int, list[tuple[int, Tile]], Board, WordResult]],
    int,
    bool,
]:
    screened: list[tuple[float, int, list[tuple[int, Tile]], Board, WordResult]] = []
    tier_qualifying = False
    prev_budget = searcher.time_budget
    variants_screened = 0
    try:
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
                sim_board, loadout=var_loadout, top_n=1
            )
            if not results:
                continue
            score = results[0].score
            if min_score is not None and score < min_score:
                continue
            screened.append(
                (score, len(placements), placements, sim_board, results[0])
            )
            tier_qualifying = True
            if (
                not screen_full_tier
                and prefer_fewest_tiles
                and min_score is not None
                and score >= min_score
            ):
                break
    finally:
        searcher.time_budget = prev_budget
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
    prefer_fewest_tiles: bool = False,
    require_placements_in_path: bool = False,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    if not variants:
        global _last_placement_search_stats
        _last_placement_search_stats = PlacementSearchStats()
        return board, [], searcher.find_best_words(board, loadout=loadout, top_n=top_n)

    total_budget = max(2.0, float(time_budget))
    screen_share = min(12.0, total_budget * 0.25)
    per_screen = max(0.08, screen_share / len(variants))
    base_required = searcher.validator.required_consumable_indices
    screened, variants_screened, _ = _screen_placement_variants(
        searcher,
        board,
        loadout,
        variants,
        per_screen=per_screen,
        min_score=min_score,
        prefer_fewest_tiles=prefer_fewest_tiles,
        require_placements_in_path=require_placements_in_path,
        base_required=base_required,
    )
    return _finalize_placement_search(
        searcher,
        board,
        loadout,
        screened,
        time_budget=time_budget,
        top_n=top_n,
        min_score=min_score,
        prefer_fewest_tiles=prefer_fewest_tiles,
        require_placements_in_path=require_placements_in_path,
        base_required=base_required,
        variant_gen_sec=0.0,
        variants_screened=variants_screened,
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
    prefer_fewest_tiles: bool = False,
    require_placements_in_path: bool = False,
    max_variants: int = 96,
    rules: dict[str, Any] | None = None,
    variant_gen_budget: float | None = None,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    if not rack_tiles:
        global _last_placement_search_stats
        _last_placement_search_stats = PlacementSearchStats()
        return board, [], []

    rules = rules or {}
    cells = _rank_placement_indices(
        board, rack_tiles, loadout=loadout, rules=rules
    )
    n = len(rack_tiles)
    tier_cap = _tier_heap_cap(max_variants)

    total_budget = max(2.0, float(time_budget))
    screen_share = min(12.0, total_budget * 0.25)
    remaining_screen = screen_share

    screened: list[tuple[float, int, list[tuple[int, Tile]], Board, WordResult]] = []
    variants_screened = 0
    variant_gen_sec = 0.0
    variant_gen_started = time.monotonic()
    base_required = searcher.validator.required_consumable_indices

    for k in range(1, n + 1):
        tier_started = time.monotonic()
        tier_variants = _top_variants_for_tier(
            board,
            rack_tiles,
            cells,
            k,
            tier_cap=tier_cap,
            loadout=loadout,
            rules=rules,
        )
        variant_gen_sec += time.monotonic() - tier_started
        if not tier_variants:
            continue

        per_screen = max(0.08, remaining_screen / len(tier_variants))
        tier_screened, tier_count, tier_qualifying = _screen_placement_variants(
            searcher,
            board,
            loadout,
            tier_variants,
            per_screen=per_screen,
            min_score=min_score,
            prefer_fewest_tiles=prefer_fewest_tiles,
            require_placements_in_path=require_placements_in_path,
            base_required=base_required,
            screen_full_tier=True,
        )
        screened.extend(tier_screened)
        variants_screened += tier_count
        remaining_screen = max(0.0, remaining_screen - per_screen * len(tier_variants))

        if prefer_fewest_tiles and min_score is not None and tier_qualifying:
            break
        if variant_gen_budget is not None:
            if time.monotonic() - variant_gen_started >= variant_gen_budget:
                break

    return _finalize_placement_search(
        searcher,
        board,
        loadout,
        screened,
        time_budget=time_budget,
        top_n=top_n,
        min_score=min_score,
        prefer_fewest_tiles=prefer_fewest_tiles,
        require_placements_in_path=require_placements_in_path,
        base_required=base_required,
        variant_gen_sec=variant_gen_sec,
        variants_screened=variants_screened,
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
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    rules = rules or {}
    variants = _placement_variants(
        board, rack_tiles, loadout=loadout, rules=rules
    )
    return _run_placement_search(
        searcher,
        board,
        loadout,
        variants,
        time_budget=time_budget,
        top_n=top_n,
        require_placements_in_path=True,
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
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    rules = rules or {}
    return _run_tiered_placement_search(
        searcher,
        board,
        loadout,
        rack_tiles,
        time_budget=time_budget,
        top_n=top_n,
        min_score=float(target),
        prefer_fewest_tiles=True,
        rules=rules,
        variant_gen_budget=variant_gen_budget,
    )


def search_consumable_score_boost(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    rack_tiles: list[Tile],
    *,
    baseline_score: float,
    time_budget: float,
    top_n: int,
    rules: dict[str, Any] | None = None,
    variant_gen_budget: float | None = None,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    """Try rack placements; adopt only when score strictly exceeds baseline."""
    if not rack_tiles:
        return board, [], []
    rules = rules or {}
    min_score = float(baseline_score) + 1e-9
    sim_board, records, results = _run_tiered_placement_search(
        searcher,
        board,
        loadout,
        rack_tiles,
        time_budget=time_budget,
        top_n=top_n,
        min_score=min_score,
        prefer_fewest_tiles=True,
        require_placements_in_path=True,
        rules=rules,
        variant_gen_budget=variant_gen_budget,
    )
    if not results or results[0].score <= baseline_score:
        return board, [], []
    return sim_board, records, results
