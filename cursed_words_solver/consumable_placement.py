"""Simulate consumable rack placements (Sandy Saguaro boss, target-score rescue)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations, permutations
from typing import Any

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    Tile,
    TileColor,
    WordResult,
    curse_type_from_key,
)
from cursed_words_solver.rules.grid_effects import _clone_board
from cursed_words_solver.rules.rule_lookup import resolve_rule_id
from cursed_words_solver.rules.scoring_conditions import placed_consumable_indices
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


def is_sandy_saguaro_boss(loadout: Loadout, rules: dict[str, Any]) -> bool:
    key = resolve_rule_id(
        rules,
        "bosses",
        loadout.boss_id or "",
        loadout.boss_name or "",
    )
    return key == "sandy_saguaro"


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


def wait_for_sandy_rack_export(
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

    if not sandy_requires_rack_export(loadout, board, rules):
        return loadout
    deadline = time.monotonic() + max(0.0, timeout_sec)
    while time.monotonic() < deadline:
        time.sleep(poll_sec)
        fresh = reload_loadout()
        if fresh is not None and not sandy_requires_rack_export(fresh, board, rules):
            return fresh
    return loadout


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


def _active_indices(board: Board) -> list[int]:
    return [i for i in range(25) if board.is_active_index(i)]


def _placement_cell_score(board: Board, idx: int, rack_tile: Tile) -> float:
    letter = (rack_tile.letter or "").strip().lower()
    score = 0.0
    for nbr in neighbors_from_tile(board, [idx], {idx}):
        ntile = board.get_by_index(nbr)
        nl = (ntile.letter or ntile.char or "").strip().lower()
        if letter and nl and len(nl) == 1 and nl.isalpha():
            score += 1.0
    return score


def _rank_placement_indices(
    board: Board,
    rack_tiles: list[Tile],
    *,
    max_cells: int = 14,
) -> list[int]:
    active = _active_indices(board)
    if len(active) <= max_cells:
        return active
    scored: list[tuple[float, int]] = []
    for idx in active:
        cell_score = max(
            (_placement_cell_score(board, idx, rt) for rt in rack_tiles),
            default=0.0,
        )
        scored.append((cell_score, idx))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [idx for _, idx in scored[:max_cells]]


def _placement_variants(
    board: Board,
    rack_tiles: list[Tile],
    *,
    max_variants: int = 72,
) -> list[list[tuple[int, Tile]]]:
    k = len(rack_tiles)
    if k == 0:
        return []
    cells = _rank_placement_indices(board, rack_tiles)
    if k == 1:
        return [[(idx, rack_tiles[0])] for idx in cells]
    variants: list[tuple[float, list[tuple[int, Tile]]]] = []
    for indices in permutations(cells, k):
        placements = list(zip(indices, rack_tiles, strict=True))
        rank = sum(_placement_cell_score(board, idx, tile) for idx, tile in placements)
        variants.append((rank, placements))
    variants.sort(key=lambda row: (-row[0], [p[0] for p in row[1]]))
    return [placements for _, placements in variants[:max_variants]]


def placement_variants_fewest_first(
    board: Board,
    rack_tiles: list[Tile],
    *,
    max_variants: int = 96,
) -> list[list[tuple[int, Tile]]]:
    """Placement combos ordered by tile count (1 first), then connectivity rank."""
    if not rack_tiles:
        return []
    cells = _rank_placement_indices(board, rack_tiles)
    n = len(rack_tiles)
    grouped: list[tuple[int, float, list[tuple[int, Tile]]]] = []
    for k in range(1, n + 1):
        for tile_combo in combinations(rack_tiles, k):
            for indices in permutations(cells, k):
                placements = list(zip(indices, tile_combo, strict=True))
                rank = sum(
                    _placement_cell_score(board, idx, tile) for idx, tile in placements
                )
                grouped.append((k, -rank, placements))
    grouped.sort(key=lambda row: (row[0], row[1], [p[0] for p in row[2]]))
    return [placements for _, _, placements in grouped[:max_variants]]


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
        return board, [], searcher.find_best_words(board, loadout=loadout, top_n=top_n)

    total_budget = max(2.0, float(time_budget))
    screen_share = min(12.0, total_budget * 0.25)
    refine_share = total_budget - screen_share
    per_screen = max(0.08, screen_share / len(variants))

    screened: list[tuple[float, int, list[tuple[int, Tile]], Board, WordResult]] = []
    prev_budget = searcher.time_budget
    base_required = searcher.validator.required_consumable_indices
    try:
        searcher.time_budget = per_screen
        for placements in variants:
            sim_board = apply_consumable_placements(board, placements)
            searcher.validator.required_consumable_indices = _required_for_placements(
                placements,
                require_placements_in_path=require_placements_in_path,
                base_required=base_required,
            )
            results = searcher.find_best_words(sim_board, loadout=loadout, top_n=1)
            if not results:
                continue
            score = results[0].score
            if min_score is not None and score < min_score:
                continue
            screened.append(
                (score, len(placements), placements, sim_board, results[0])
            )
            if (
                prefer_fewest_tiles
                and min_score is not None
                and score >= min_score
            ):
                break
    finally:
        searcher.time_budget = prev_budget
        searcher.validator.required_consumable_indices = base_required

    if not screened:
        return board, [], []

    if prefer_fewest_tiles and min_score is not None:
        min_tiles = min(row[1] for row in screened)
        screened = [row for row in screened if row[1] == min_tiles]

    screened.sort(key=lambda row: (-row[0], row[1]))
    finalists = screened[: min(12, len(screened))]
    per_refine = max(1.0, refine_share / len(finalists))

    best_score = -1.0
    best_tile_count = 999
    best_board = board
    best_records: list[ConsumablePlacement] = []
    best_results: list[WordResult] = []
    try:
        searcher.time_budget = per_refine
        for score_hint, tile_count, placements, sim_board, _ in finalists:
            searcher.validator.required_consumable_indices = _required_for_placements(
                placements,
                require_placements_in_path=require_placements_in_path,
                base_required=base_required,
            )
            results = searcher.find_best_words(sim_board, loadout=loadout, top_n=top_n)
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


def search_with_consumable_placements(
    searcher: WordSearcher,
    board: Board,
    loadout: Loadout,
    rack_tiles: list[Tile],
    *,
    time_budget: float,
    top_n: int,
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    variants = _placement_variants(board, rack_tiles)
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
) -> tuple[Board, list[ConsumablePlacement], list[WordResult]]:
    variants = placement_variants_fewest_first(board, rack_tiles)
    return _run_placement_search(
        searcher,
        board,
        loadout,
        variants,
        time_budget=time_budget,
        top_n=top_n,
        min_score=float(target),
        prefer_fewest_tiles=True,
    )
