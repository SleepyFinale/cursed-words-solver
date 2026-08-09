"""Nina Nix unlock sticker scoring."""

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

NINA_STICKER_NAMES = [
    "Deep Sea Horror",
    "Doughnut",
    "Ferris Wheel",
    "Fish Cake",
    "Game Pad",
    "Jigsaw Piece",
    "Maracas",
    "Rainbow Sprinkles",
    "Tombstone",
]

GRID_ONLY_SLUGS = {
    "doughnut",
    "game_pad",
    "maracas",
    "rainbow_sprinkles",
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


def test_all_nina_stickers_catalogued():
    pipeline = ScoringPipeline()
    for name in NINA_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_nina():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="sticker")
            for n in NINA_STICKER_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 9
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 9 - len(GRID_ONLY_SLUGS)


def test_deep_sea_horror_void_penalty():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", -3, color=TileColor.VOID)
    board.tiles[0][1] = _tile(0, 1, "B", 2)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="deep_sea_horror", name="Deep Sea Horror", level=1)]
    )
    score, _ = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert score == base - 10


def test_ferris_wheel_different_coloured_ends():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 4, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 4)
    board.tiles[0][2] = _tile(0, 2, "C", 4, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="ferris_wheel", name="Ferris Wheel", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    assert bd["multiplier"] == 1.5
    assert score == 12 * 1.5


def test_ferris_wheel_white_and_green_endpoints():
    """Mismatch 20260623_131346: WHITE is a distinct colour for Ferris Wheel."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "D", 2, color=TileColor.WHITE)
    board.tiles[0][1] = _tile(0, 1, "O", 1)
    board.tiles[0][2] = _tile(0, 2, "B", 3, color=TileColor.GREEN)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="ferris_wheel", name="Ferris Wheel", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "dob", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "dob", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == base * 1.5


def test_ferris_wheel_same_colour_ends_no_mult():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.RED)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="ferris_wheel", name="Ferris Wheel", level=1)])
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_ferris_wheel_item_endpoints_different_colours():
    """speos shape: scattered item tiles at both ends with different colours."""
    board = _empty_board()
    board.tiles[0][2] = Tile(
        row=0,
        col=2,
        char="p",
        letter="P",
        base_score=0,
        color=TileColor.BLUE,
        curse=CurseType.ITEM,
        metadata={"source": "melmod", "scattered_item_id": "game_pad"},
    )
    board.tiles[0][3] = _tile(0, 3, "M", 4)
    board.tiles[1][4] = Tile(
        row=1,
        col=4,
        char="r",
        letter="R",
        base_score=0,
        color=TileColor.RED,
        curse=CurseType.ITEM,
        metadata={"source": "melmod", "scattered_item_id": "maracas"},
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="ferris_wheel", name="Ferris Wheel", level=3)])
    score, bd = pipeline.score(board, [2, 3, 9], "pmr", loadout)
    base, _ = pipeline.score(board, [2, 3, 9], "pmr", Loadout())
    assert bd["multiplier"] == 2.5
    assert score == base * 2.5


def test_ferris_wheel_letter_and_item_endpoints():
    """ecrus shape: blue letter start, shiny scattered item end."""
    board = _empty_board()
    board.tiles[0][1] = _tile(0, 1, "E", 4, color=TileColor.BLUE)
    board.tiles[0][2] = _tile(0, 2, "C", 4)
    board.tiles[0][4] = Tile(
        row=0,
        col=4,
        char="k",
        letter="K",
        base_score=0,
        color=TileColor.SHINY,
        curse=CurseType.ITEM,
        metadata={"source": "melmod", "scattered_item_id": "ornate_key"},
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="ferris_wheel", name="Ferris Wheel", level=3)])
    score, bd = pipeline.score(board, [1, 2, 4], "eck", loadout)
    assert bd["multiplier"] == 2.5
    assert score == 8 * 2.5


def test_fish_cake_shiny_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "S", 10, color=TileColor.SHINY)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="fish_cake", name="Fish Cake", level=1)])
    score, _ = pipeline.score(board, [0], "s", loadout)
    assert score == 20


def test_jigsaw_piece_zero_subtotal_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 0)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="jigsaw_piece", name="Jigsaw Piece", level=1)])
    score, bd = pipeline.score(board, [0], "a", loadout)
    assert bd["word_score"] == 100
    assert score == 100


def test_jigsaw_piece_nonzero_subtotal_no_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="jigsaw_piece", name="Jigsaw Piece", level=1)])
    score, bd = pipeline.score(board, [0], "a", loadout)
    assert bd["word_score"] == 0
    assert score == 5


def test_tombstone_void_adjacent_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "V", 0, color=TileColor.VOID)
    board.tiles[0][1] = _tile(0, 1, "A", 3)
    board.tiles[1][1] = _tile(1, 1, "V2", 0, color=TileColor.VOID)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=1)])
    score, _ = pipeline.score(board, [1], "a", loadout)
    # A at (0,1) has void at (0,0) and (1,1) → +10
    assert score == 13


def test_tombstone_diagonal_void_adjacent_bonus():
    board = _empty_board()
    board.tiles[4][3] = _tile(4, 3, "G", 2)
    board.tiles[3][4] = _tile(3, 4, "E", 0, color=TileColor.VOID)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=1)])
    score, _ = pipeline.score(board, [23], "g", loadout)
    base, _ = pipeline.score(board, [23], "g", Loadout())
    assert score == base + 5


def test_tombstone_void_path_corner_cluster_direct_only():
    """Tombstone counts only direct VOID neighbours on path tiles."""
    board = _empty_board()
    board.tiles[2][0] = _tile(2, 0, "Y", 0, color=TileColor.VOID)
    board.tiles[2][1] = _tile(2, 1, "S", 0, color=TileColor.VOID)
    board.tiles[2][2] = _tile(2, 2, "M", 0, color=TileColor.VOID)
    board.tiles[3][0] = _tile(3, 0, "I", 0, color=TileColor.VOID)
    board.tiles[3][1] = _tile(3, 1, "F", 0, color=TileColor.VOID)
    board.tiles[3][4] = _tile(3, 4, "X", 0, color=TileColor.VOID)
    board.tiles[1][1] = _tile(1, 1, "R", 1)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=2)])
    score, _ = pipeline.score(board, [10, 6, 11], "yrs", loadout)
    base, _ = pipeline.score(board, [10, 6, 11], "yrs", Loadout())
    assert score - base == 100


def test_tombstone_stoolies_shape_uses_direct_void_adjacency():
    board = _empty_board()
    # Match the stoolies mismatch neighborhood with VOID and SHINY tiles.
    board.tiles[1][1] = _tile(1, 1, "S", 0, color=TileColor.VOID)
    board.tiles[1][0] = _tile(1, 0, "T", 50, color=TileColor.SHINY)
    board.tiles[2][0] = _tile(2, 0, "O", 1, color=TileColor.COLORLESS)
    board.tiles[4][3] = _tile(4, 3, "O", 1, color=TileColor.COLORLESS)
    board.tiles[4][2] = _tile(4, 2, "L", 1, color=TileColor.COLORLESS)
    board.tiles[3][2] = _tile(3, 2, "I", 0, color=TileColor.VOID)
    board.tiles[2][2] = _tile(2, 2, "E", 1, color=TileColor.COLORLESS)
    board.tiles[2][3] = _tile(2, 3, "S", 50, color=TileColor.SHINY)
    board.tiles[4][1] = _tile(4, 1, "E", 0, color=TileColor.VOID)
    board.tiles[4][4] = _tile(4, 4, "W", 0, color=TileColor.VOID)
    board.tiles[2][1] = _tile(2, 1, "G", 0, color=TileColor.VOID)
    board.tiles[1][3] = _tile(1, 3, "E", 0, color=TileColor.VOID)
    path = [6, 5, 10, 23, 22, 17, 12, 13]
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=2)])
    score, _ = pipeline.score(board, path, "stoolies", loadout)
    base, _ = pipeline.score(board, path, "stoolies", Loadout())
    assert score - base == 170


def test_tombstone_number_void_counts_adjacent():
    board = _empty_board()
    board.tiles[3][2] = _tile(3, 2, "E", 1)
    board.tiles[3][0] = _tile(3, 0, "O", 0, color=TileColor.VOID)
    board.tiles[2][2] = _tile(2, 2, "A", 0, color=TileColor.VOID)
    board.tiles[2][3] = _tile(2, 3, "F", 0, color=TileColor.VOID)
    board.tiles[3][1] = Tile(
        row=3,
        col=1,
        char="8",
        letter="8",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.NUMBER,
        number_value=8,
        metadata={"source": "melmod"},
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=1)])
    score, _ = pipeline.score(board, [17], "e", loadout)
    base, _ = pipeline.score(board, [17], "e", Loadout())
    assert score == base + 15


def test_tombstone_counts_void_path_tile_itself():
    board = _empty_board()
    board.tiles[3][4] = _tile(3, 4, "₩", 0, color=TileColor.VOID, curse=CurseType.CURRENCY)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=1)])
    score, _ = pipeline.score(board, [19], "navvy", loadout)
    base, _ = pipeline.score(board, [19], "navvy", Loadout())
    assert score == base + 5


def test_tombstone_counts_scattered_tombstone_tile_itself():
    board = _empty_board()
    board.tiles[3][4] = Tile(
        row=3,
        col=4,
        char="🪦",
        letter="Y",
        base_score=0.0,
        color=TileColor.COLORLESS,
        curse=CurseType.ITEM,
        metadata={"source": "melmod", "scattered_item_id": "tombstone"},
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=1)])
    score, _ = pipeline.score(board, [19], "navvy", loadout)
    base, _ = pipeline.score(board, [19], "navvy", Loadout())
    assert score == base + 5


def test_shiny_grid_tombstone_keeps_export_level_not_equipped():
    """SHINY grid Tombstone uses live export Level; equipped fires separately.

    Regression (deceit): predicted 727 vs actual 622 — solver merged equipped L3
    onto SHINY grid L2. Melmod ApplyVoidTombstoneCombinedScatterLevels is void-only.
    """
    from cursed_words_solver.rules.scoring_conditions import grid_path_sticker_level

    board = _empty_board()
    board.tiles[2][2] = _tile(2, 2, "A", 1)
    board.tiles[2][1] = _tile(2, 1, "V", 0, color=TileColor.VOID)
    board.tiles[2][3] = Tile(
        row=2,
        col=3,
        char="🪦",
        letter="T",
        base_score=0.0,
        color=TileColor.SHINY,
        curse=CurseType.ITEM,
        metadata={
            "source": "melmod",
            "scattered_item_id": "tombstone",
            "scattered_item_level": 2,
        },
    )
    path = [12, 13]
    loadout = Loadout(
        stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=3)],
        extras={
            "boss_floor_modification": "6",
            "grid_number": "1",
            "boss_modifiers": '["yeti_crab"]',
            "boss_modifier_floor_mods": '{"yeti_crab":6}',
        },
    )
    level = grid_path_sticker_level(
        loadout, "tombstone", board=board, path=path, path_tile_index=1
    )
    assert level == 2
    pipeline = ScoringPipeline()
    score, _ = pipeline.score(board, path, "at", loadout)
    # L2 grid (+10/void) then L3 inventory (+15/void); A has 1 void neighbor.
    # Base 1 + 10 + 15 = 26 (tombstone tile itself also counts as adjacent void? no —
    # shiny item is not void). Only V at (2,1) adjacent to A; tombstone tile on path
    # counts for its own neighbors.
    assert int(score) == 26


def test_void_grid_tombstone_still_merges_equipped_level():
    """VOID path Tombstone may use equipped tier (jun10-style under-export)."""
    from cursed_words_solver.rules.scoring_conditions import grid_path_sticker_level

    board = _empty_board()
    board.tiles[2][2] = _tile(2, 2, "A", 1)
    board.tiles[2][1] = _tile(2, 1, "V", 0, color=TileColor.VOID)
    board.tiles[2][3] = Tile(
        row=2,
        col=3,
        char="🪦",
        letter="T",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.ITEM,
        metadata={
            "source": "melmod",
            "scattered_item_id": "tombstone",
            "scattered_item_level": 1,
        },
    )
    path = [12, 13]
    loadout = Loadout(
        stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=3)],
        extras={
            "boss_floor_modification": "3",
            "grid_number": "3",
            "boss_modifiers": '["wolf"]',
            "boss_modifier_floor_mods": '{"wolf":3}',
        },
    )
    level = grid_path_sticker_level(
        loadout, "tombstone", board=board, path=path, path_tile_index=1
    )
    assert level >= 3


def test_void_tombstone_combined_export_undoes_to_live_level():
    """Melmod void combine export (live+equipped) undoes to live tier (qin/hesp)."""
    from cursed_words_solver.rules.scoring_conditions import grid_path_sticker_level

    board = _empty_board()
    board.tiles[2][2] = _tile(2, 2, "A", 1)
    board.tiles[2][1] = _tile(2, 1, "V", 0, color=TileColor.VOID)
    board.tiles[2][3] = Tile(
        row=2,
        col=3,
        char="🪦",
        letter="T",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.ITEM,
        metadata={
            "source": "melmod",
            "scattered_item_id": "tombstone",
            "scattered_item_level": 6,  # live 3 + equipped 3
        },
    )
    path = [12, 13]
    loadout = Loadout(
        stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=3)],
        extras={
            "boss_floor_modification": "8",
            "grid_number": "2",
            "boss_modifiers": '["axolotl"]',
            "boss_modifier_floor_mods": '{"axolotl":8}',
        },
    )
    level = grid_path_sticker_level(
        loadout, "tombstone", board=board, path=path, path_tile_index=1
    )
    assert level == 3


def test_void_dusty_grid_uses_exported_level():
    """VOID dusty grid scatter trusts live export Level (abye L3, not forced L1)."""
    from cursed_words_solver.rules.scoring_conditions import dusty_coffin_word_score_level

    board = _empty_board()
    board.tiles[2][2] = Tile(
        row=2,
        col=2,
        char="⚰",
        letter="E",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.ITEM,
        metadata={
            "source": "melmod",
            "scattered_item_id": "dusty_coffin",
            "scattered_item_level": 3,
        },
    )
    # Unused void letter not on path
    board.tiles[0][0] = _tile(0, 0, "Z", 0, color=TileColor.VOID)
    path = [12]
    loadout = Loadout(
        extras={
            "boss_floor_modification": "8",
            "grid_number": "1",
            "boss_modifiers": '["axolotl"]',
        }
    )
    level = dusty_coffin_word_score_level(
        loadout,
        from_grid_scatter=True,
        sticker_level=3,
        board=board,
        path=path,
    )
    assert level == 3
    pipeline = ScoringPipeline()
    score, _ = pipeline.score(board, path, "e", loadout)
    # L3 dusty: 24 per unused void; Z unused → +24 on base 0
    assert int(score) == 24


def test_shiny_dusty_grid_uses_exported_level():
    """SHINY unequipped dusty grid trusts live export (erosely L3 → 12×24 word)."""
    from cursed_words_solver.rules.scoring_conditions import dusty_coffin_word_score_level

    board = _empty_board()
    board.tiles[2][2] = Tile(
        row=2,
        col=2,
        char="⚰",
        letter="E",
        base_score=0.0,
        color=TileColor.SHINY,
        curse=CurseType.ITEM,
        metadata={
            "source": "melmod",
            "scattered_item_id": "dusty_coffin",
            "scattered_item_level": 3,
        },
    )
    board.tiles[0][0] = _tile(0, 0, "Z", 0, color=TileColor.VOID)
    path = [12]
    loadout = Loadout(extras={"grid_number": "2"})
    level = dusty_coffin_word_score_level(
        loadout,
        from_grid_scatter=True,
        sticker_level=3,
        board=board,
        path=path,
    )
    assert level == 3


def test_off_path_tombstone_uses_full_inventory_level_only():
    """Off-path grid Tombstone must not double-apply with a nerfed inventory (cinch)."""
    from cursed_words_solver.rules.scoring_order import encounter_grid_scatter_refs
    from cursed_words_solver.rules.scoring_conditions import tombstone_inventory_scoring_level

    board = _empty_board()
    # Path of void letters; tombstone off-path
    board.tiles[2][0] = _tile(2, 0, "C", 0, color=TileColor.VOID)
    board.tiles[2][1] = _tile(2, 1, "I", -1, color=TileColor.VOID)
    board.tiles[3][1] = Tile(
        row=3,
        col=1,
        char="🪦",
        letter="O",
        base_score=0.0,
        color=TileColor.COLORLESS,
        curse=CurseType.ITEM,
        metadata={
            "source": "melmod",
            "scattered_item_id": "tombstone",
            "scattered_item_level": 3,
        },
    )
    path = [10, 11]
    loadout = Loadout(
        stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=3)],
        extras={"grid_number": "1"},
    )
    rules = ScoringPipeline().rules
    assert not any(
        r.rule_id == "tombstone"
        for r in encounter_grid_scatter_refs(board, path, rules, loadout)
    )
    inv = tombstone_inventory_scoring_level(
        loadout.stickers[0], loadout, board, path=path
    )
    assert inv == 3
