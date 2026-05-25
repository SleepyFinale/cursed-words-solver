"""Octacles unlock stamp catalog and scoring (wiki: Unlocked when unlocking Octacles)."""

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name

from tests.catalog.stamps._coverage import assert_loadout_stamp_coverage

OCTACLES_STAMP_NAMES = [
    "Haunted Mirror",
    "Oden",
]

GRID_ONLY_SLUGS = {
    "haunted_mirror",
}


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
    number_value=None,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=color,
        curse=curse,
        number_value=number_value,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_octacles_stamps_catalogued():
    pipeline = ScoringPipeline()
    for name in OCTACLES_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_octacles_stamps():
    pipeline = ScoringPipeline()
    assert_loadout_stamp_coverage(pipeline.rules, OCTACLES_STAMP_NAMES)



def test_haunted_mirror_grid_scatter():
    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stamps", "haunted_mirror", "Haunted Mirror")
    assert rule.get("effect_class") == "scatter"


def test_oden_two_curse_types_doubles_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, curse=CurseType.LETTER)
    board.tiles[0][1] = _tile(0, 1, "2", 5, curse=CurseType.NUMBER, number_value=2)
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1], "a2", loadout)
    assert bd["multiplier"] == 2.0
    assert score == 20


def test_oden_three_curse_types_triples_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 4, curse=CurseType.LETTER)
    board.tiles[0][1] = _tile(0, 1, "2", 4, curse=CurseType.NUMBER, number_value=2)
    board.tiles[0][2] = _tile(0, 2, "?", 4, curse=CurseType.WILDCARD)
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1, 2], "a2?", loadout)
    assert bd["multiplier"] == 3.0
    assert score == 36
