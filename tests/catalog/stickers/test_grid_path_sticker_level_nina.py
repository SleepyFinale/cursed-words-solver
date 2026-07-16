"""Grid-path sticker levels for Nina Nix Dusty Coffin / Tombstone session (2026-06-29)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    apply_snapshot_phased_session_extras,
    dusty_coffin_void_units,
    dusty_coffin_word_score_level,
    grid_path_sticker_level,
)

_CAPTURES = Path(r"C:\Users\TheMi\.cursed_words_solver\scoring_mismatches")
_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mismatches"


def _load(stem: str) -> dict:
    path = _FIXTURES / f"{stem}.json"
    if not path.is_file():
        path = _CAPTURES / f"{stem}.json"
    if not path.is_file():
        pytest.skip(f"fixture {stem} not installed")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "stem,slug,path_index,expected_level",
    [
        ("20260629_125703", "dusty_coffin", 0, 1),
        ("20260629_125833", "tombstone", 3, 2),
        ("20260629_130154", "tombstone", 0, 2),
        ("20260629_130252", "tombstone", 3, 2),
        ("20260629_130347", "dusty_coffin", 0, 3),
        ("20260629_135501", "tombstone", 3, 2),
        ("20260629_141855", "tombstone", 4, 2),
        ("20260629_142001", "tombstone", 6, 2),
        ("20260629_142306", "tombstone", 0, 2),
        ("20260629_143611", "down_under", 4, 2),
        ("20260701_113327", "down_under", 6, 2),
    ],
)
def test_grid_path_sticker_level_on_session_captures(
    stem: str, slug: str, path_index: int, expected_level: int
) -> None:
    data = _load(stem)
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    apply_snapshot_phased_session_extras(loadout, board)
    path = data["path"]
    level = grid_path_sticker_level(
        loadout,
        slug,
        board=board,
        path=path,
        path_tile_index=path_index,
    )
    assert level == expected_level


@pytest.mark.parametrize(
    "stem,expected",
    [
        ("20260629_125703", 401),
        ("20260629_125833", 449),
        ("20260629_130154", 528),
        ("20260629_130252", 552),
        ("20260629_130347", 504),
        ("20260629_135322", 684),
        ("20260629_135501", 523),
        ("20260629_141855", 771),
        ("20260629_142001", 987),
        ("20260629_142306", 1056),
        ("20260629_143611", 613),
        ("20260629_143704", 748),
        ("20260629_150249", 646),
    ],
)
def test_nina_nix_session_capture_scores(stem: str, expected: int) -> None:
    data = _load(stem)
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    apply_snapshot_phased_session_extras(loadout, board)
    score, _ = ScoringPipeline().score(board, data["path"], data["word"], loadout)
    assert int(score) == expected


def test_dusty_grid_scatter_word_score_level_is_one() -> None:
    data = _load("20260629_130347")
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert (
        dusty_coffin_word_score_level(
            loadout,
            from_grid_scatter=True,
            sticker_level=3,
            board=board,
            path=data["path"],
        )
        == 1
    )


def test_dusty_colorless_grid_scatter_uses_scatter_plus_one() -> None:
    data = _load("20260629_135322")
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert (
        dusty_coffin_word_score_level(
            loadout,
            from_grid_scatter=True,
            sticker_level=3,
            board=board,
            path=data["path"],
        )
        == 2
    )


def test_dusty_equipped_one_above_scatter_uses_encounter_tier() -> None:
    data = _load("20260629_125833")
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert (
        dusty_coffin_word_score_level(
            loadout,
            from_grid_scatter=False,
            sticker_level=2,
            board=board,
            path=data["path"],
        )
        == 1
    )


def test_down_under_grid_path_uses_max_equipped_excluding_dusty() -> None:
    """israeli: grid Down Under L1 export bleeds to L2 (max equipped excl. dusty)."""
    data = _load("20260629_143611")
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    apply_snapshot_phased_session_extras(loadout, board)
    path = data["path"]
    level = grid_path_sticker_level(
        loadout,
        "down_under",
        board=board,
        path=path,
        path_tile_index=4,
    )
    assert level == 2


def test_dusty_void_units_israeli_excludes_down_under_scatter() -> None:
    """israeli: void Down Under on path must not expand dusty equipped pool."""
    data = _load("20260629_143611")
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    apply_snapshot_phased_session_extras(loadout, board)
    n = dusty_coffin_void_units(
        board,
        data["word"],
        loadout,
        applying_sticker_id="dusty_coffin",
        path=data["path"],
        after_tombstone=True,
    )
    assert n == 6


def test_mysterious_amulet_capped_below_equipped_scores_at_board_tier() -> None:
    """Boss floor cap: L1 grid amulet scores at L1 despite L3 equipped."""
    from cursed_words_solver.models import (
        Board,
        CurseType,
        Loadout,
        LoadoutItem,
        Tile,
        TileColor,
    )

    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    board.tiles[0][2] = Tile(
        row=0,
        col=2,
        char="?",
        letter="?",
        base_score=0,
        color=TileColor.COLORLESS,
        curse=CurseType.ITEM,
        metadata={
            "scattered_item_id": "mysterious_amulet",
            "scattered_item_level": 1,
        },
    )
    loadout = Loadout(
        stickers=[LoadoutItem(id="mysterious_amulet", name="Mysterious Amulet", level=3)],
        boss_id="michael",
        extras={
            "grid_number": "6",
            "boss_floor_modification": "5",
            "scoring_previous_words_count": "0",
        },
    )
    level = grid_path_sticker_level(
        loadout,
        "mysterious_amulet",
        board=board,
        path=[2],
        path_tile_index=0,
    )
    assert level == 1


def test_dusty_red_grid_scatter_level_anigh() -> None:
    """anigh: RED dusty grid scatter uses L2; path void units capped at off-path count."""
    data = _load("20260629_143704")
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    apply_snapshot_phased_session_extras(loadout, board)
    assert (
        dusty_coffin_word_score_level(
            loadout,
            from_grid_scatter=True,
            sticker_level=1,
            board=board,
            path=data["path"],
        )
        == 2
    )
    n = dusty_coffin_void_units(
        board,
        data["word"],
        loadout,
        applying_sticker_id="dusty_coffin",
        path=data["path"],
        from_grid_scatter=True,
    )
    assert n == 7


def test_incave_session_capture_score() -> None:
    data = _load("20260629_150249")
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    apply_snapshot_phased_session_extras(loadout, board)
    score, _ = ScoringPipeline().score(board, data["path"], data["word"], loadout)
    assert int(score) == 646


def test_tombstone_bleed_export_scores_at_encounter_level() -> None:
    """deepies: void Tombstone L4 export is inventory bleed; grid scatter scores at L1."""
    data = _load("20260630_154233")
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    apply_snapshot_phased_session_extras(loadout, board)
    path = data["path"]
    path_pos = path.index(11)
    level = grid_path_sticker_level(
        loadout,
        "tombstone",
        board=board,
        path=path,
        path_tile_index=path_pos,
    )
    assert level == 1


def test_dusty_wolf_off_path_grid_scatter_level_hoi() -> None:
    data = _load("20260630_153156")
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert (
        dusty_coffin_word_score_level(
            loadout,
            from_grid_scatter=True,
            sticker_level=1,
            board=board,
            path=data["path"],
        )
        == 2
    )
    assert (
        dusty_coffin_void_units(
            board,
            data["word"],
            loadout,
            applying_sticker_id="dusty_coffin",
            path=data["path"],
            from_grid_scatter=True,
        )
        == 6
    )


def test_off_path_tombstone_grid_ref_ynals() -> None:
    from cursed_words_solver.rules.scoring_order import encounter_grid_scatter_refs

    data = _load("20260630_152914")
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    rules = ScoringPipeline().rules
    refs = encounter_grid_scatter_refs(board, data["path"], rules, loadout)
    assert any(r.rule_id == "tombstone" for r in refs)


def test_dusty_colorless_path_void_in_word_caps_units_incave() -> None:
    """incave: COLORLESS dusty on path + void letter in word caps grid/equipped units."""
    data = _load("20260629_150249")
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    apply_snapshot_phased_session_extras(loadout, board)
    path = data["path"]
    word = data["word"]
    grid_units = dusty_coffin_void_units(
        board,
        word,
        loadout,
        applying_sticker_id="dusty_coffin",
        path=path,
        from_grid_scatter=True,
    )
    equipped_units = dusty_coffin_void_units(
        board,
        word,
        loadout,
        applying_sticker_id="dusty_coffin",
        path=path,
        after_tombstone=True,
    )
    assert grid_units == 5
    assert equipped_units == 5
    assert (
        dusty_coffin_word_score_level(
            loadout,
            from_grid_scatter=True,
            sticker_level=3,
            board=board,
            path=path,
            word=word,
        )
        == 2
    )
    assert (
        dusty_coffin_word_score_level(
            loadout,
            from_grid_scatter=False,
            sticker_level=3,
            board=board,
            path=path,
            word=word,
        )
        == 3
    )


@pytest.mark.parametrize(
    "stem,expected",
    [
        ("20260701_113044", 434),
        ("20260701_113117", 4076),
        ("20260701_113238", 4708),
        ("20260701_113327", 1900),
    ],
)
def test_20260701_milky_way_session_replay_scores(stem: str, expected: int) -> None:
    """Submit-time replay (submit board + trace extras) for 2026-07-01 Nina session."""
    from tests.regression import test_scoring_mismatches as tsm

    data = _load(stem)
    run_state = tsm._run_state_for_replay(data)
    word = data["word"]
    path = data["path"]
    tsm._adjust_previous_word_letter_extras(run_state, data)
    tsm._adjust_bento_previous_word_extras(run_state, data)
    tsm._adjust_neapolitan_percent_extras(run_state, data)
    tsm._adjust_ruler_distance_extras(run_state, data)
    tsm._adjust_rare_item_count_extras(run_state, data)
    tsm._adjust_steak_percent_extras(run_state, data)
    tsm._adjust_cursed_bosses_defeated_from_trace(run_state, data)
    tsm._adjust_tile_ninja_bonus_from_trace(run_state, data)
    tsm._adjust_green_tile_count_from_trace(run_state, data)
    board_for_lucky = parse_board_from_run_state(run_state)
    if board_for_lucky is not None:
        path = tsm._replay_path(board_for_lucky, path)
        tsm._adjust_lucky_dice_target_extras(run_state, data, board_for_lucky, path)
    board = parse_board_from_run_state(run_state)
    tsm._adjust_movie_camera_telescope_extras(run_state, data, board, path)
    board = parse_board_from_run_state(run_state)
    tsm._adjust_void_penalty_from_trace(run_state, data, board, path)
    tsm._adjust_scattered_item_level_from_trace(run_state, data, board, path)
    tsm._adjust_nat_h4_session_extras(run_state, data, stem)
    tsm._adjust_snapshot_copy_from_trace(
        run_state, data, board, path, word, case_stem=stem
    )
    board = parse_board_from_run_state(run_state)
    tsm._adjust_nat_h4_post_cocktail_extras(run_state, data, board, path, word, stem)
    loadout = parse_run_state(run_state)
    apply_snapshot_phased_session_extras(loadout, board)
    tsm._adjust_bicycle_pre_word_extras(run_state, data, board, path, loadout)
    loadout = parse_run_state(run_state)
    replay_money = tsm._bank_money_for_replay(data, board, path, loadout)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    if replay_money is not None:
        board.money = max(board.money, replay_money)
        loadout.money = max(loadout.money, replay_money)
    score, _ = ScoringPipeline().score(board, path, word, loadout)
    assert int(score) == expected


def test_dusty_off_path_skipped_after_first_encounter_word() -> None:
    """linnets: off-path grid Dusty does not fire once encounter has scored words."""
    from cursed_words_solver.rules.scoring_order import encounter_grid_scatter_refs

    data = _load("20260701_113238")
    run_state = __import__(
        "tests.regression.test_scoring_mismatches", fromlist=["_run_state_for_replay"]
    )._run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    loadout.extras["scoring_previous_words_count"] = "3"
    rules = ScoringPipeline().rules
    refs = encounter_grid_scatter_refs(board, data["path"], rules, loadout)
    assert not any(r.rule_id == "dusty_coffin" for r in refs)
