"""Nina Nix unlock stamp scoring (wiki: Unlocked when unlocking Nina Nix)."""

from cursed_words_solver.models import (
    Board,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name

from tests.catalog.stamps._coverage import assert_loadout_stamp_coverage

NINA_STAMP_NAMES = [
    "Chocolate Candy",
    "Dangerous Summit",
    "Dango",
]

GRID_ONLY_SLUGS = {
    "chocolate_candy",
    "dangerous_summit",
}


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=color,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_nina_stamps_catalogued():
    pipeline = ScoringPipeline()
    for name in NINA_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_nina_stamps():
    pipeline = ScoringPipeline()
    assert_loadout_stamp_coverage(pipeline.rules, NINA_STAMP_NAMES)



def test_dango_zero_colours_zeros_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.COLORLESS)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.COLORLESS)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="dango", name="Dango", level=1, kind="stamp")]
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    assert bd["multiplier"] == 0.0
    assert score == 0


def test_dango_two_colours_doubles_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="dango", name="Dango", level=1, kind="stamp")]
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    assert bd["multiplier"] == 2.0
    assert score == 20


def test_dango_three_colours_triples_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 4, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 4, color=TileColor.BLUE)
    board.tiles[0][2] = _tile(0, 2, "C", 4, color=TileColor.SHINY)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="dango", name="Dango", level=1, kind="stamp")]
    )
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    assert bd["multiplier"] == 3.0
    assert score == 36


def test_dango_uses_word_bonus_channel_for_nonzero():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="dango", name="Dango", level=1, kind="stamp")]
    )
    score, _bd, trace = pipeline.score_with_trace(board, [0, 1], "ab", loadout)
    assert score == 20
    assert any(
        step.get("phase") == "multiply" and step.get("rule_id") == "dango"
        for step in trace
    )
