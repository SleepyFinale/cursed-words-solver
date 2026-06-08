"""Catalog heuristics when word-search lift is zero for grid-only shop items."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from cursed_words_solver.models import Board, Loadout, SellCandidate, ShopOffer, TileColor
from cursed_words_solver.rules.scoring_conditions import encounter_red_tiles_before_current_word
from cursed_words_solver.rules.rule_lookup import get_rule
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.setup_value import grids_remaining_from_loadout

_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "wiki" / "stickers.json"
_LIFT_EPSILON = 1.0


@lru_cache(maxsize=1)
def _sticker_rules() -> dict:
    if not _CATALOG_PATH.is_file():
        return {}
    try:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        return data.get("stickers") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _rule_for_id(item_id: str, name: str = "") -> dict | None:
    rules = ScoringPipeline().rules
    _key, rule = get_rule(rules, "stickers", item_id, name)
    if rule:
        return rule
    wiki = _sticker_rules()
    raw = wiki.get((item_id or "").lower())
    return raw if isinstance(raw, dict) else None


def _horizon_factor(loadout: Loadout, *, grids_discount: float = 0.85) -> float:
    grids = grids_remaining_from_loadout(loadout)
    return sum(grids_discount ** i for i in range(max(1, grids)))


def _red_tiles_on_board(board: Board) -> int:
    return sum(
        1
        for t in board.flat
        if board.is_active_index(t.index) and t.color == TileColor.RED
    )


def _void_adjacent_letters(board: Board) -> int:
    count = 0
    for tile in board.flat:
        if not board.is_active_index(tile.index):
            continue
        if tile.curse.value != "letter":
            continue
        row, col = tile.row, tile.col
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = row + dr, col + dc
            if 0 <= nr < 5 and 0 <= nc < 5:
                neighbor = board.tiles[nr][nc]
                if neighbor.color == TileColor.VOID:
                    count += 1
                    break
    return count


def catalog_lift_for_offer(
    offer: ShopOffer,
    loadout: Loadout,
    boards: list[Board],
    *,
    grids_discount: float = 0.85,
) -> tuple[float, str]:
    """Estimated WORD lift when search delta is ~0."""
    if offer.slot not in {"sticker", "stamp"}:
        return 0.0, ""

    rule = _rule_for_id(offer.id or "", offer.name or "")
    if not rule:
        return 0.0, ""

    effect_type = str(rule.get("type") or "")
    level = max(1, offer.level or 1)
    horizon = _horizon_factor(loadout, grids_discount=grids_discount)

    if effect_type in ("scatter_start_grid", "scatter_start_encounter"):
        tiles = max(1, int(rule.get("scatter_count") or level))
        per_tile = 14.0
        lift = tiles * per_tile * horizon / max(1, len(boards) or 1)
        return lift, "grid setup"

    if effect_type == "red_encounter_tile_bonus":
        prior = encounter_red_tiles_before_current_word(loadout)
        if boards:
            avg_reds = sum(_red_tiles_on_board(b) for b in boards) / len(boards)
        else:
            avg_reds = 2.0
        lift = level * max(1, prior) * avg_reds * 6.0 * horizon / max(1, len(boards) or 1)
        return lift, "encounter red bonus"

    if effect_type == "add_tile_score":
        base = int(rule.get("base") or 5)
        upgrade = int(rule.get("upgrade") or 0)
        per_tile = base + upgrade * max(0, level - 1)
        if boards:
            avg_adj = sum(_void_adjacent_letters(b) for b in boards) / len(boards)
        else:
            avg_adj = 2.0
        lift = per_tile * avg_adj * horizon / max(1, len(boards) or 1)
        return lift, "void-adjacent tiles"

    return 0.0, ""


def catalog_lift_for_owned_item(
    candidate: SellCandidate,
    loadout: Loadout,
    boards: list[Board],
    *,
    grids_discount: float = 0.85,
) -> tuple[float, str]:
    """Opportunity cost (WORD) of selling a grid-scoring item."""
    if candidate.kind != "sticker":
        return 0.0, ""
    offer = ShopOffer(
        slot="sticker",
        index=candidate.slot,
        id=candidate.id or "",
        name=candidate.name or "",
        level=max(1, candidate.level or 1),
        price=0,
    )
    lift, kind = catalog_lift_for_offer(
        offer, loadout, boards, grids_discount=grids_discount
    )
    return lift, kind


def merge_search_and_catalog_lift(
    search_lift: float,
    catalog_lift: float,
    *,
    search_reason: str = "",
    catalog_kind: str = "",
    max_boards: int = 2,
) -> tuple[float, str]:
    """Combine search delta with catalog estimate; pick reason label."""
    if abs(search_lift) >= _LIFT_EPSILON:
        if search_lift > 0 and catalog_kind:
            return search_lift, f"+{search_lift:,.0f} WORD over {max_boards} boards"
        return search_lift, search_reason or f"+{search_lift:,.0f} WORD over {max_boards} boards"
    if catalog_lift > 0:
        return catalog_lift, f"+{catalog_lift:,.0f} WORD ({catalog_kind or 'catalog est.'})"
    return search_lift, f"+{search_lift:,.0f} WORD over {max_boards} boards"
