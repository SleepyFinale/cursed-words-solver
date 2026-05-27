"""Octacles unlock sticker scoring."""

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import count_scoring_items, get_rule, slugify_name

OCTACLES_STICKER_NAMES = [
    "Amphora",
    "Broom",
    "Ghost",
    "Jack-o'-Lantern",
    "Mischievous Imp",
    "Moai",
    "Mysterious Amulet",
]

GRID_ONLY_SLUGS = {
    "amphora",
    "ghost",
}


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=color,
        curse=curse,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_octacles_stickers_catalogued():
    pipeline = ScoringPipeline()
    for name in OCTACLES_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_octacles():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="sticker")
            for n in OCTACLES_STICKER_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 7
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 7 - len(GRID_ONLY_SLUGS)


def test_amphora_and_ghost_grid_scatter():
    pipeline = ScoringPipeline()
    for slug in ("amphora", "ghost"):
        _key, rule = get_rule(pipeline.rules, "stickers", slug, slug)
        assert rule.get("effect_class") == "scatter"


def test_mysterious_amulet_cursed_tile_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "3", 3, curse=CurseType.NUMBER)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="mysterious_amulet", name="Mysterious Amulet", level=1)]
    )
    score, bd = pipeline.score(board, [0], "3", loadout)
    base, base_bd = pipeline.score(board, [0], "3", Loadout())
    assert bd["pipeline"]["tile_scores"][0] == base_bd["pipeline"]["tile_scores"][0] + 8
    assert score == base + 8


def test_moai_sticker_colourless_cursed_only():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "4", 4, curse=CurseType.NUMBER)
    board.tiles[0][1] = _tile(
        0, 1, "5", 5, curse=CurseType.NUMBER, color=TileColor.RED
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="moai", name="Moai", level=1, kind="sticker")])
    score, bd = pipeline.score(board, [0, 1], "45", loadout)
    base, base_bd = pipeline.score(board, [0, 1], "45", Loadout())
    assert bd["pipeline"]["tile_scores"][0] == base_bd["pipeline"]["tile_scores"][0] + 12
    assert bd["pipeline"]["tile_scores"][1] == base_bd["pipeline"]["tile_scores"][1]
    assert score == base + 12


def test_broom_different_curse_types_at_ends():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "2", 2, curse=CurseType.NUMBER)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    board.tiles[0][2] = _tile(0, 2, "N", 1, curse=CurseType.CHESS_KNIGHT)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="broom", name="Broom", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "2an", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "2an", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)  # floor after ×WORD


def test_broom_same_curse_type_ends_no_mult():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "2", 2, curse=CurseType.NUMBER)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    board.tiles[0][2] = _tile(0, 2, "3", 3, curse=CurseType.NUMBER)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="broom", name="Broom", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "2a3", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "2a3", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_broom_chess_vs_chess_no_mult():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "N", 1, curse=CurseType.CHESS_BISHOP)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    board.tiles[0][2] = _tile(0, 2, "N", 1, curse=CurseType.CHESS_KNIGHT)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="broom", name="Broom", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "nan", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "nan", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_mischievous_imp_all_cursed_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "2", 2, curse=CurseType.NUMBER)
    board.tiles[0][1] = _tile(0, 1, "N", 1, curse=CurseType.CHESS_KNIGHT)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="mischievous_imp", name="Mischievous Imp", level=1)]
    )
    score, bd = pipeline.score(board, [0, 1], "2n", loadout)
    base, _ = pipeline.score(board, [0, 1], "2n", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_mischievous_imp_mixed_letter_no_mult():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "2", 2, curse=CurseType.NUMBER)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="mischievous_imp", name="Mischievous Imp", level=1)]
    )
    score, bd = pipeline.score(board, [0, 1], "2a", loadout)
    base, _ = pipeline.score(board, [0, 1], "2a", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_jack_o_lantern_cursed_word_money():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "2", 2, curse=CurseType.NUMBER)
    board.tiles[0][1] = _tile(0, 1, "?", 1, curse=CurseType.WILDCARD)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="jack_o_lantern", name="Jack-o'-Lantern", level=1)]
    )
    score, bd = pipeline.score(board, [0, 1], "2?", loadout)
    base, _ = pipeline.score(board, [0, 1], "2?", Loadout())
    assert bd["money_bonus"] == 1
    assert score == base


def test_jack_o_lantern_letter_and_currency_path():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "G", 2)
    board.tiles[0][1] = _tile(0, 1, "O", 2)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="jack_o_lantern", name="Jack-o'-Lantern", level=1)]
    )
    score, bd = pipeline.score(board, [0, 1], "go", loadout)
    base, _ = pipeline.score(board, [0, 1], "go", Loadout())
    assert bd["money_bonus"] == 1
    assert score == base
