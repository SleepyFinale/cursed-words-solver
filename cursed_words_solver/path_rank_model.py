"""Lightweight CPU path ranker for beam/heap guidance.

Predicts an approximate score_total_only from path + affordance features.
Always re-score top-K with ScoringPipeline — this never replaces exact scoring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from cursed_words_solver.graph_bitboard import BoardGraphContext
from cursed_words_solver.loadout_affordances import LoadoutAffordances
from cursed_words_solver.models import Board, CurseType


@dataclass(frozen=True)
class PathRankFeatures:
    length: float
    base_sum: float
    item_frac: float
    number_frac: float
    chess_frac: float
    suit_ends: float
    hub_frac: float
    cover_frac: float
    digit_start: float
    long_word: float


# Ridge-style weights fit to prefer longer, cover-heavy, mult-geometry paths.
# Calibrated conservatively so ordering is useful without overclaiming magnitude.
_DEFAULT_WEIGHTS: tuple[float, ...] = (
    4.0,   # length
    1.0,   # base_sum
    25.0,  # item_frac
    8.0,   # number_frac
    12.0,  # chess_frac
    30.0,  # suit_ends
    10.0,  # hub_frac
    40.0,  # cover_frac
    15.0,  # digit_start
    6.0,   # long_word
)
_DEFAULT_BIAS = 5.0


@dataclass(frozen=True)
class PathRankModel:
    weights: tuple[float, ...] = _DEFAULT_WEIGHTS
    bias: float = _DEFAULT_BIAS

    def predict(self, feats: PathRankFeatures) -> float:
        vec = (
            feats.length,
            feats.base_sum,
            feats.item_frac,
            feats.number_frac,
            feats.chess_frac,
            feats.suit_ends,
            feats.hub_frac,
            feats.cover_frac,
            feats.digit_start,
            feats.long_word,
        )
        total = self.bias
        for w, x in zip(self.weights, vec):
            total += w * x
        return max(0.0, total)


_DEFAULT_MODEL = PathRankModel()


def extract_path_features(
    board: Board,
    path: list[int],
    graph_ctx: BoardGraphContext,
    affordances: LoadoutAffordances | None,
    *,
    value_hub_mask: int = 0,
    must_soft_mask: int = 0,
) -> PathRankFeatures:
    n = max(1, len(path))
    base_sum = 0.0
    items = numbers = chess = hubs = 0
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.ITEM:
            items += 1
            if 0 <= idx < len(graph_ctx.item_tile_base):
                base_sum += float(graph_ctx.item_tile_base[idx])
        else:
            if 0 <= idx < len(graph_ctx.tile_base):
                base_sum += float(graph_ctx.tile_base[idx])
        if tile.curse == CurseType.NUMBER:
            numbers += 1
        if graph_ctx.chess_piece_mask & (1 << idx):
            chess += 1
        if value_hub_mask & (1 << idx):
            hubs += 1
    suit_ends = 0.0
    if len(path) >= 2:
        s0 = str((board.get_by_index(path[0]).metadata or {}).get("card_suit") or "")
        s1 = str((board.get_by_index(path[-1]).metadata or {}).get("card_suit") or "")
        if s0 and s1 and s0 != s1:
            suit_ends = 1.0
        elif affordances and affordances.needs_suit_diverse_ends and (s0 or s1):
            suit_ends = 0.5
    visited = 0
    for idx in path:
        visited |= 1 << idx
    cover = 0.0
    if must_soft_mask:
        cover = (visited & must_soft_mask).bit_count() / max(1, must_soft_mask.bit_count())
    digit_start = (
        1.0
        if path and board.get_by_index(path[0]).curse == CurseType.NUMBER
        else 0.0
    )
    long_word = 1.0 if n >= 8 else (0.5 if n >= 5 else 0.0)
    return PathRankFeatures(
        length=float(n),
        base_sum=base_sum,
        item_frac=items / n,
        number_frac=numbers / n,
        chess_frac=chess / n,
        suit_ends=suit_ends,
        hub_frac=hubs / n,
        cover_frac=cover,
        digit_start=digit_start,
        long_word=long_word,
    )


def approximate_path_rank(
    board: Board,
    path: list[int],
    graph_ctx: BoardGraphContext,
    affordances: LoadoutAffordances | None,
    *,
    value_hub_mask: int = 0,
    must_soft_mask: int = 0,
    model: PathRankModel | None = None,
) -> float:
    """Heuristic rank for beam ordering; pipeline must re-score survivors."""
    feats = extract_path_features(
        board,
        path,
        graph_ctx,
        affordances,
        value_hub_mask=value_hub_mask,
        must_soft_mask=must_soft_mask,
    )
    return (model or _DEFAULT_MODEL).predict(feats)


def blend_rank_with_heuristic(
    pipeline_rank: float,
    approx_rank: float,
    *,
    weight: float = 0.15,
) -> float:
    """Blend exact rank with approximate guidance (small weight)."""
    w = max(0.0, min(0.5, weight))
    if not math.isfinite(approx_rank):
        return pipeline_rank
    return (1.0 - w) * pipeline_rank + w * approx_rank
