"""Prepare fixture boards and loadouts for shop simulation (enable grid scatter)."""

from __future__ import annotations

import copy

from cursed_words_solver.models import Board, Loadout, Tile


def prepare_boards_for_shop_sim(boards: list[Board]) -> list[Board]:
    """Clone boards and strip melmod source so start-of-grid scatter can run."""
    prepared: list[Board] = []
    for board in boards:
        tiles = [
            [
                Tile(
                    row=t.row,
                    col=t.col,
                    char=t.char,
                    letter=t.letter,
                    base_score=t.base_score,
                    color=t.color,
                    curse=t.curse,
                    number_value=t.number_value,
                    fraction_value=t.fraction_value,
                    ocr_confidence=t.ocr_confidence,
                    metadata={
                        k: v
                        for k, v in (t.metadata or {}).items()
                        if k != "source"
                    },
                )
                for t in row
            ]
            for row in board.tiles
        ]
        prepared.append(
            Board(
                tiles=tiles,
                money=board.money,
                rows=board.rows,
                cols=board.cols,
                active=list(board.active),
                playable_origin=board.playable_origin,
                playable_min_row=board.playable_min_row,
                playable_max_row=board.playable_max_row,
                playable_min_col=board.playable_min_col,
                playable_max_col=board.playable_max_col,
            )
        )
    return prepared


def _scatter_seed(loadout: Loadout) -> int:
    stickers = tuple((s.id, s.level) for s in loadout.stickers)
    stamps = tuple((s.id, s.level) for s in loadout.stamps)
    pin = (
        (loadout.extras or {}).get("pin_effect"),
        (loadout.extras or {}).get("pin_branch"),
    )
    return hash((stickers, stamps, pin)) & 0x7FFFFFFF


def prepare_loadout_for_shop_sim(loadout: Loadout) -> Loadout:
    """Clone loadout for shop sim: allow grid mutations with deterministic scatter."""
    lo = copy.deepcopy(loadout)
    extras = dict(lo.extras or {})
    extras["board_from_melmod"] = "false"
    extras["scatter_seed"] = _scatter_seed(lo)
    lo.extras = extras
    return lo
