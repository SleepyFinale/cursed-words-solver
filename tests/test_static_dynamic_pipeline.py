"""Board-static vs path-dynamic scoring pipeline split."""

from __future__ import annotations

from cursed_words_solver.board_scoring_context import (
    build_board_scoring_context,
    build_cell_masks,
)
from cursed_words_solver.graph_bitboard import build_board_graph_context
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_phase import (
    PipelinePhase,
    StaticRuleKind,
    classify_inventory_rule,
)
from cursed_words_solver.solve_context import build_solve_context


def _letter_board(*cells: tuple[int, str]) -> Board:
    tiles = [
        [
            Tile(
                row=r,
                col=c,
                char="Q",
                letter="Q",
                base_score=2,
                color=TileColor.COLORLESS,
                curse=CurseType.LETTER,
            )
            for c in range(5)
        ]
        for r in range(5)
    ]
    for idx, ch in cells:
        r, c = divmod(idx, 5)
        tiles[r][c] = Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=2,
            color=TileColor.COLORLESS,
            curse=CurseType.LETTER,
        )
    return Board(tiles=tiles)


def _scores_equal(
    pipeline: ScoringPipeline,
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
) -> None:
    ctx = build_solve_context(loadout, pipeline.rules)
    graph_ctx = build_board_graph_context(board)
    board_scoring_ctx = build_board_scoring_context(
        board, loadout, ctx, graph_ctx, pipeline.rules
    )
    kwargs = dict(
        solve_context=ctx,
        graph_ctx=graph_ctx,
        board_scoring_ctx=board_scoring_ctx,
    )
    without = pipeline.score_total_only(board, path, word, loadout, solve_context=ctx)
    with_split = pipeline.score_total_only(board, path, word, loadout, **kwargs)
    assert without == with_split


def test_classify_sequoia_sapling_is_static_tile_add():
    pipeline = ScoringPipeline()
    board = _letter_board((0, "a"), (1, "e"), (6, "b"))
    graph_ctx = build_board_graph_context(board)
    masks = build_cell_masks(board, graph_ctx)
    rule = pipeline.rules["stickers"]["sequoia_sapling"]
    spec = classify_inventory_rule(
        rule,
        level=1,
        rule_id="sequoia_sapling",
        phase=PipelinePhase.STICKER,
        target_masks=masks,
    )
    assert spec is not None
    assert spec.kind == StaticRuleKind.TILE_ADD
    assert spec.value == 6
    assert spec.target_mask & (1 << 0)
    assert spec.target_mask & (1 << 1)
    assert not (spec.target_mask & (1 << 6))


def test_classify_egg_is_dynamic():
    pipeline = ScoringPipeline()
    board = _letter_board((0, "a"))
    graph_ctx = build_board_graph_context(board)
    masks = build_cell_masks(board, graph_ctx)
    rule = pipeline.rules["stickers"]["egg"]
    assert classify_inventory_rule(
        rule,
        level=1,
        rule_id="egg",
        phase=PipelinePhase.STICKER,
        target_masks=masks,
    ) is None


def test_sequoia_sapling_split_matches_full_pipeline():
    pipeline = ScoringPipeline()
    board = _letter_board((0, "a"), (1, "e"), (2, "i"))
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="sequoia_sapling", name="Sequoia Sapling", level=1, kind="sticker")
        ]
    )
    _scores_equal(pipeline, board, [0, 1, 2], "aei", loadout)


def test_static_plus_conditional_sticker_scores_match():
    pipeline = ScoringPipeline()
    board = _letter_board((0, "a"), (1, "r"), (2, "t"))
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="sequoia_sapling", name="Sequoia Sapling", level=1, kind="sticker"),
            LoadoutItem(id="egg", name="Egg", level=1, kind="sticker"),
        ]
    )
    _scores_equal(pipeline, board, [0, 1, 2], "art", loadout)
    _scores_equal(pipeline, board, [0, 1, 2], "are", loadout)


def test_build_board_scoring_context_enables_split_for_static_loadout():
    pipeline = ScoringPipeline()
    board = _letter_board((0, "a"))
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="sequoia_sapling", name="Sequoia Sapling", level=1, kind="sticker")
        ]
    )
    ctx = build_solve_context(loadout, pipeline.rules)
    graph_ctx = build_board_graph_context(board)
    bsc = build_board_scoring_context(board, loadout, ctx, graph_ctx, pipeline.rules)
    assert bsc.use_split_pipeline
    assert (0, False) in bsc.static_sticker_specs


def test_compound_loadout_disables_split_pipeline():
    pipeline = ScoringPipeline()
    board = _letter_board((0, "a"))
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="sequoia_sapling", name="Sequoia Sapling", level=1, kind="sticker")
        ],
        extras={"compound_word_percents_on_tile_sum": "150"},
    )
    ctx = build_solve_context(loadout, pipeline.rules)
    graph_ctx = build_board_graph_context(board)
    bsc = build_board_scoring_context(board, loadout, ctx, graph_ctx, pipeline.rules)
    assert not bsc.use_split_pipeline
