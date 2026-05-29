"""Dusty Coffin + Snapshot copy void units (Nat-H4 axons class)."""

from cursed_words_solver.models import CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.scoring_conditions import dusty_coffin_void_units
from tests.catalog.stickers.test_default_stickers import _empty_board, _tile


def test_dusty_void_units_axons_shape_nine():
    """VOID letters not in word + path void letter in word + dusty item face."""
    board = _empty_board()
    loadout = Loadout(extras={"snapshot_copy_slug": "dusty_coffin"})
    # VOID letters not in 'axons'
    for r, c, letter in [(0, 0, "R"), (0, 2, "F"), (1, 0, "G"), (2, 0, "R"), (2, 2, "V"), (4, 0, "U"), (4, 4, "Y")]:
        board.tiles[r][c] = _tile(r, c, letter, 0, color=TileColor.VOID)
    # Path void letter N (in 'axons') when Dusty is on path
    board.tiles[3][4] = _tile(3, 4, "N", 0, color=TileColor.VOID)
    board.tiles[0][4] = Tile(
        row=0,
        col=4,
        char="E",
        letter="E",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "dusty_coffin"},
    )
    path = [
        board.tiles[0][3].index,
        board.tiles[0][4].index,
        board.tiles[3][4].index,
    ]
    board.tiles[0][3] = _tile(0, 3, "A", 0, color=TileColor.VOID, curse=CurseType.ITEM)
    board.tiles[0][3].metadata["scattered_item_id"] = "ornate_key"
    n = dusty_coffin_void_units(
        board, "axons", loadout, applying_sticker_id="dusty_coffin", path=path
    )
    assert n == 9
    snap_n = dusty_coffin_void_units(
        board, "axons", loadout, applying_sticker_id="snapshot", path=path
    )
    assert snap_n == 9


def test_burrito_grid_two_does_not_add_level():
    """Encounter grid index does not add a Burrito level (sates 20260528_211913)."""
    from cursed_words_solver.rules.scoring_conditions import other_sticker_levels_sum
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    loadout = Loadout(
        stickers=[
            LoadoutItem(id="retro_raider", name="Retro Raider", level=2),
            LoadoutItem(id="doughnut", name="Doughnut", level=2),
            LoadoutItem(id="snapshot", name="Snapshot", level=1),
            LoadoutItem(id="burrito", name="Burrito", level=1),
            LoadoutItem(id="cocktail", name="Cocktail", level=2),
        ],
        extras={"grid_number": "1", "snapshot_copy_slug": "down_under"},
    )
    rules = ScoringPipeline().rules
    assert other_sticker_levels_sum(loadout, rules=rules) == 7
    loadout.extras["grid_number"] = "2"
    assert other_sticker_levels_sum(loadout, rules=rules) == 7


def test_dusty_void_units_blunge_shape_eleven():
    """VOID letters not in word + ornate void item on path (C not in blunge)."""
    import json
    from pathlib import Path

    from cursed_words_solver.loadout import parse_board_from_run_state

    data = json.loads(
        Path("tests/fixtures/mismatches/20260528_183732.json").read_text(encoding="utf-8")
    )
    board = parse_board_from_run_state(data["run_state_snapshot"])
    path = data["path"]
    loadout = Loadout(extras={"snapshot_copy_slug": "dusty_coffin"})
    n = dusty_coffin_void_units(
        board, "blunge", loadout, applying_sticker_id="dusty_coffin", path=path
    )
    assert n == 11
    snap_n = dusty_coffin_void_units(
        board, "blunge", loadout, applying_sticker_id="snapshot", path=path
    )
    assert snap_n == 11


def test_burrito_off_path_ferris_adds_level():
    from cursed_words_solver.rules.scoring_conditions import (
        burrito_word_multiplier,
        other_sticker_levels_sum,
    )
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    board = _empty_board()
    board.tiles[2][3] = Tile(
        row=2, col=3, char="Y", letter="Y", base_score=0.0,
        color=TileColor.RED, curse=CurseType.ITEM,
        metadata={"scattered_item_id": "ferris_wheel", "scattered_item_level": 1},
    )
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="retro_raider", name="Retro Raider", level=2),
            LoadoutItem(id="doughnut", name="Doughnut", level=2),
            LoadoutItem(id="snapshot", name="Snapshot", level=1),
            LoadoutItem(id="burrito", name="Burrito", level=1),
            LoadoutItem(id="cocktail", name="Cocktail", level=2),
        ],
        extras={
            "grid_number": "1",
            "snapshot_copy_slug": "dusty_coffin",
        },
    )
    board.tiles[2][0] = Tile(
        row=2, col=0, char="O", letter="O", base_score=0.0,
        color=TileColor.BLUE, curse=CurseType.ITEM,
        metadata={"scattered_item_id": "dusty_coffin", "scattered_item_level": 1},
    )
    rules = ScoringPipeline().rules
    rule = rules["stickers"]["burrito"]
    path = [board.tiles[0][0].index]
    board.tiles[0][0] = _tile(0, 0, "A", 10, color=TileColor.BLUE)
    without = other_sticker_levels_sum(
        loadout, board=board, path=path, rules=rules, include_equipped_path_scatter=True
    )
    assert without == 7
    assert burrito_word_multiplier(
        1, rule, loadout, board=board, path=path, rules=rules
    ) == 1.35


def test_plan_burrito_sum_and_score():
    import json
    from pathlib import Path

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from cursed_words_solver.rules.scoring_conditions import (
        burrito_word_multiplier,
        other_sticker_levels_sum,
    )
    from tests.regression.test_scoring_mismatches import (
        _adjust_nat_h4_session_extras,
        _adjust_neapolitan_percent_extras,
        _run_state_for_replay,
    )

    data = json.loads(
        Path("tests/fixtures/mismatches/20260528_211744.json").read_text(encoding="utf-8")
    )
    run_state = _run_state_for_replay(data)
    _adjust_neapolitan_percent_extras(run_state, data)
    _adjust_nat_h4_session_extras(run_state, data, "20260528_211744")
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    rules = ScoringPipeline().rules
    path = data["path"]
    assert (
        other_sticker_levels_sum(loadout, board=board, path=path, rules=rules) == 9
    )
    rule = rules["stickers"]["burrito"]
    assert (
        burrito_word_multiplier(1, rule, loadout, board=board, path=path, rules=rules)
        == 1.45
    )
    score, _ = ScoringPipeline().score(board, path, data["word"], loadout)
    assert int(score) == 1868


def test_sates_burrito_sum_and_score():
    import json
    from pathlib import Path

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from cursed_words_solver.rules.scoring_conditions import (
        burrito_word_multiplier,
        other_sticker_levels_sum,
    )
    from tests.regression.test_scoring_mismatches import (
        _adjust_nat_h4_session_extras,
        _adjust_neapolitan_percent_extras,
        _run_state_for_replay,
    )

    data = json.loads(
        Path("tests/fixtures/mismatches/20260528_211913.json").read_text(encoding="utf-8")
    )
    run_state = _run_state_for_replay(data)
    _adjust_neapolitan_percent_extras(run_state, data)
    _adjust_nat_h4_session_extras(run_state, data, "20260528_211913")
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    rules = ScoringPipeline().rules
    path = data["path"]
    assert (
        other_sticker_levels_sum(loadout, board=board, path=path, rules=rules) == 10
    )
    rule = rules["stickers"]["burrito"]
    assert (
        burrito_word_multiplier(1, rule, loadout, board=board, path=path, rules=rules)
        == 1.5
    )
    score, _ = ScoringPipeline().score(board, path, data["word"], loadout)
    assert int(score) == 4779


def test_accoutre_tombstone_deep_void_level_two_with_boss_floor():
    """Grid tombstone L2 when boss_floor_mod export caps scattered level at 1 (accoutre)."""
    import json
    from pathlib import Path

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from cursed_words_solver.rules.scoring_conditions import (
        _tombstone_uses_grid_encounter_level,
        apply_snapshot_phased_session_extras,
        grid_path_sticker_level,
    )
    from tests.regression.test_scoring_mismatches import (
        _adjust_nat_h4_session_extras,
        _adjust_neapolitan_percent_extras,
        _run_state_for_replay,
    )

    data = json.loads(
        Path("tests/fixtures/mismatches/20260528_222519.json").read_text(encoding="utf-8")
    )
    run_state = _run_state_for_replay(data)
    _adjust_neapolitan_percent_extras(run_state, data)
    _adjust_nat_h4_session_extras(run_state, data, "20260528_222519")
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    assert _tombstone_uses_grid_encounter_level(board, path, loadout)
    assert (
        grid_path_sticker_level(
            loadout, "tombstone", board=board, path=path, path_tile_index=0
        )
        == 2
    )
    apply_snapshot_phased_session_extras(loadout, board)
    score, _ = ScoringPipeline().score(board, path, data["word"], loadout)
    assert int(score) == 10849


def test_blunge_pipeline_matches_trace_replay_score():
    """Full replay score matches manual actual_trace replay (3772); see _KNOWN_FAILING for actual 5141."""
    import json
    from pathlib import Path

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from tests.regression.test_scoring_mismatches import (
        _adjust_bento_previous_word_extras,
        _adjust_nat_h4_session_extras,
        _adjust_neapolitan_percent_extras,
        _adjust_previous_word_letter_extras,
        _adjust_rare_item_count_extras,
        _adjust_scattered_item_level_from_trace,
        _adjust_snapshot_copy_from_trace,
        _adjust_steak_percent_extras,
        _adjust_void_penalty_from_trace,
        _run_state_for_replay,
    )

    data = json.loads(
        Path("tests/fixtures/mismatches/20260528_183732.json").read_text(encoding="utf-8")
    )
    run_state = _run_state_for_replay(data)
    path = data["path"]
    word = data["word"]
    for fn in (
        _adjust_previous_word_letter_extras,
        _adjust_bento_previous_word_extras,
        _adjust_neapolitan_percent_extras,
        _adjust_rare_item_count_extras,
        _adjust_steak_percent_extras,
    ):
        fn(run_state, data)
    board = parse_board_from_run_state(run_state)
    _adjust_void_penalty_from_trace(run_state, data, board, path)
    _adjust_scattered_item_level_from_trace(run_state, data, board, path)
    _adjust_nat_h4_session_extras(run_state, data, "20260528_183732")
    _adjust_snapshot_copy_from_trace(
        run_state, data, board, path, word, case_stem="20260528_183732"
    )
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    score, _ = ScoringPipeline().score(board, path, word, loadout)
    assert int(score) == 3811
    assert int(data["actual_score"]) == 5141
