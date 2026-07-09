"""Telescope running-red count: historic prior plus path-prefix reds (game parity)."""

import json
from pathlib import Path

from cursed_words_solver.loadout import (
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    apply_snapshot_phased_session_extras,
    encounter_red_tiles_before_current_word,
    grid_path_sticker_level,
    scaled_word_multiplier,
    telescope_running_red_count,
)
from cursed_words_solver.rules.rule_lookup import get_rule
from cursed_words_solver.models import TileColor
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mismatches"
CELLULATED = FIXTURES / "20260530_175032.json"
BASNETS = FIXTURES / "20260607_011541.json"
IMBLAZING = FIXTURES / "20260607_011738.json"
FETOSCOPIC = FIXTURES / "20260607_011836.json"
VENIREMEN = FIXTURES / "20260608_142113.json"
AXMAKER = FIXTURES / "20260608_142438.json"
EYESTRIPE = FIXTURES / "20260608_155545.json"
RECTIFIES = FIXTURES / "20260609_122845.json"
IGAPOS = FIXTURES / "20260708_213827.json"


def _replay_score(fixture_path: Path) -> tuple[int, dict, list[int], object, object]:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    run_state = dict(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    apply_snapshot_phased_session_extras(loadout, board)
    score, _, _ = ScoringPipeline().score_with_trace(
        board, path, data["word"], loadout
    )
    return int(score), data, path, board, loadout


def _red_path_indices(board, path: list[int]) -> list[int]:
    return [
        i
        for i, idx in enumerate(path)
        if board.get_by_index(idx).color == TileColor.RED
    ]


def test_cellulated_telescope_gap_path_score():
    """Nat-H4: Snapshot L2 copying telescope; reds at path steps 0 and 4."""
    data = json.loads(CELLULATED.read_text(encoding="utf-8"))
    run_state = dict(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    apply_snapshot_phased_session_extras(loadout, board)
    score, _, trace = ScoringPipeline().score_with_trace(
        board, path, data["word"], loadout
    )
    assert int(score) == int(data["actual_score"]) == 80
    tele_steps = [
        s
        for s in (trace or [])
        if isinstance(s, dict)
        and s.get("rule_id") == "telescope"
        and s.get("effect_type") == "red_encounter_tile_bonus"
    ]
    assert tele_steps
    assert int(tele_steps[0]["subtotal"]) == 12


def test_eyestripe_telescope_gap_path_score():
    """Grid 1 word 1: seven reds on path with historic prefix counts only."""
    data = json.loads(EYESTRIPE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    apply_snapshot_phased_session_extras(loadout, board)
    score, _, trace = ScoringPipeline().score_with_trace(
        board, path, data["word"], loadout
    )
    assert int(score) == int(data["actual_score"]) == 4080
    tele_steps = [
        s
        for s in (trace or [])
        if isinstance(s, dict)
        and s.get("rule_id") == "telescope"
        and s.get("effect_type") == "red_encounter_tile_bonus"
    ]
    assert tele_steps
    assert int(tele_steps[0]["subtotal"]) == 129


def test_eyestripe_telescope_running_counts():
    data = json.loads(EYESTRIPE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    red_indices = _red_path_indices(board, path)
    assert len(red_indices) == 7
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 1
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 2
    assert telescope_running_red_count(loadout, board, path, red_indices[-1]) == 7


def test_telescope_running_count_on_second_red():
    data = json.loads(CELLULATED.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    red_indices = _red_path_indices(board, path)
    assert red_indices == [0, 4]
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 1
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 3


def test_basnets_telescope_prior_zero_without_red_tile_count():
    """Word 2: historic without red_tile_count must not use red_tiles_used_encounter."""
    data = json.loads(BASNETS.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    assert encounter_red_tiles_before_current_word(loadout) == 0
    red_indices = _red_path_indices(board, path)
    assert red_indices == [4, 6]
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 1
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 2


def test_basnets_replay_score():
    score, data, *_ = _replay_score(BASNETS)
    assert score == int(data["actual_score"]) == -4


def test_imblazing_telescope_running_counts():
    data = json.loads(IMBLAZING.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    assert encounter_red_tiles_before_current_word(loadout) == 2
    red_indices = _red_path_indices(board, path)
    assert red_indices == [0, 3]
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 3
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 4


def test_imblazing_replay_score():
    score, data, *_ = _replay_score(IMBLAZING)
    assert score == int(data["actual_score"]) == 12


def test_fetoscopic_telescope_running_counts():
    data = json.loads(FETOSCOPIC.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    assert encounter_red_tiles_before_current_word(loadout) == 4
    red_indices = _red_path_indices(board, path)
    assert red_indices == [3, 6]
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 5
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 6


def test_fetoscopic_replay_score():
    score, data, *_ = _replay_score(FETOSCOPIC)
    assert score == int(data["actual_score"]) == 8


def _run_state_for_replay(data: dict) -> dict:
    payload = dict(data.get("run_state_snapshot") or {})
    if data.get("extras_snapshot") is not None:
        payload["extras_snapshot"] = data.get("extras_snapshot")
    if data.get("extras_diff") is not None:
        payload["extras_diff"] = data.get("extras_diff")
    if data.get("submit_board_tiles") is not None:
        payload["submit_board_tiles"] = data.get("submit_board_tiles")
    return prepare_run_state_dict_for_scoring(payload)


def test_grid_one_stale_historic_telescope_prior_zero():
    """Grid 1 word 1: stale encounter historic must not inflate Telescope prior."""
    data = json.loads(VENIREMEN.read_text(encoding="utf-8"))
    loadout = parse_run_state(_run_state_for_replay(data))
    assert encounter_red_tiles_before_current_word(loadout) == 0


def test_veniremen_replay_score():
    data = json.loads(VENIREMEN.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    apply_snapshot_phased_session_extras(loadout, board)
    score, _, trace = ScoringPipeline().score_with_trace(
        board, path, data["word"], loadout
    )
    assert int(score) == int(data["actual_score"]) == 2856
    tele_steps = [
        s
        for s in (trace or [])
        if isinstance(s, dict)
        and s.get("rule_id") == "telescope"
        and s.get("effect_type") == "red_encounter_tile_bonus"
    ]
    assert tele_steps
    assert int(tele_steps[0]["subtotal"]) == 40


def test_axmaker_replay_score():
    data = json.loads(AXMAKER.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    apply_snapshot_phased_session_extras(loadout, board)
    score, _, trace = ScoringPipeline().score_with_trace(
        board, path, data["word"], loadout
    )
    assert int(score) == int(data["actual_score"]) == 1920
    tele_steps = [
        s
        for s in (trace or [])
        if isinstance(s, dict)
        and s.get("rule_id") == "telescope"
        and s.get("effect_type") == "red_encounter_tile_bonus"
    ]
    assert tele_steps
    assert int(tele_steps[0]["subtotal"]) == 60


def test_equipped_scatter_matches_inventory_level():
    from cursed_words_solver.models import (
        Board,
        CurseType,
        Loadout,
        LoadoutItem,
        Tile,
        TileColor,
    )

    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    board.tiles[2][2] = Tile(
        row=2,
        col=2,
        char="s",
        letter="S",
        base_score=0,
        color=TileColor.RED,
        curse=CurseType.ITEM,
        metadata={
            "scattered_item_id": "lucky_scarf",
            "scattered_item_level": 1,
        },
    )
    loadout = Loadout(
        stickers=[LoadoutItem(id="lucky_scarf", name="Lucky Scarf", level=3)],
        extras={"grid_number": "1", "scoring_previous_words_count": "2"},
    )
    level = grid_path_sticker_level(
        loadout,
        "lucky_scarf",
        board=board,
        path=[12],
        path_tile_index=0,
    )
    assert level == 3


def test_rectifies_telescope_running_counts():
    """Two non-red separators between reds: prefix count only (no gap bonus)."""
    data = json.loads(RECTIFIES.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    red_indices = _red_path_indices(board, path)
    assert red_indices[:2] == [0, 3]
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 1
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 2


def test_rectifies_replay_score():
    score, data, *_ = _replay_score(RECTIFIES)
    assert score == int(data["actual_score"]) == 60


def _igapos_f8_run_state(data: dict) -> dict:
    """F8-time extras for igapos: grid word 1, no encounter historic."""
    payload = dict(data.get("run_state_snapshot") or {})
    if data.get("submit_board_tiles") is not None:
        payload["submit_board_tiles"] = data.get("submit_board_tiles")
    extras = dict(payload.get("extras") or {})
    extras["scoring_previous_words_count"] = "0"
    extras.pop("historic_words", None)
    extras["encounter_historic_source"] = "grid1_no_scoring_cache"
    payload["extras"] = extras
    return prepare_run_state_dict_for_scoring(payload)


def test_igapos_telescope_running_count_on_scattered_tile():
    """Scattered Telescope on path: prefix reds only (no invented gap bonus)."""
    data = json.loads(IGAPOS.read_text(encoding="utf-8"))
    run_state = _igapos_f8_run_state(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = path_from_melmod_indices(board, data["path"])
    red_indices = _red_path_indices(board, path)
    assert red_indices == [0, 4]
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 1
    scattered = (board.get_by_index(path[red_indices[1]]).metadata or {}).get(
        "scattered_item_id"
    )
    assert scattered == "telescope"
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 2


def test_igapos_telescope_f8_score():
    """igapos 20260708: F8 predicted 444; game actual 440 after gap fix."""
    data = json.loads(IGAPOS.read_text(encoding="utf-8"))
    run_state = _igapos_f8_run_state(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = path_from_melmod_indices(board, data["path"])
    apply_snapshot_phased_session_extras(loadout, board)
    score, _, _ = ScoringPipeline().score_with_trace(
        board, path, data["word"], loadout
    )
    assert int(score) == int(data["actual_score"]) == 440


def test_toolbox_boosts_cherry_pie_grid_multiplier():
    from cursed_words_solver.models import (
        Board,
        CurseType,
        Loadout,
        LoadoutItem,
        Tile,
        TileColor,
    )

    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stickers", "cherry_pie", "Cherry Pie")
    assert rule is not None

    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    board.tiles[0][0] = Tile(
        row=0,
        col=0,
        char="p",
        letter="A",
        base_score=0,
        color=TileColor.RED,
        curse=CurseType.ITEM,
        metadata={
            "scattered_item_id": "cherry_pie",
            "scattered_item_level": 1,
        },
    )
    loadout = Loadout(
        stickers=[LoadoutItem(id="toolbox", name="Toolbox", level=2)],
        extras={"grid_number": "1", "scoring_previous_words_count": "0"},
    )
    level = grid_path_sticker_level(
        loadout,
        "cherry_pie",
        board=board,
        path=[0],
        path_tile_index=0,
    )
    assert level == 2
    factor = scaled_word_multiplier(level, rule, loadout)
    assert factor == 3.0


def test_maple_leaf_floor_mod_caps_grid_scatter_level():
    """reink 20260609_155559: floor mod caps grid Maple at L1 despite export/equipped L2."""
    from cursed_words_solver.models import (
        Board,
        CurseType,
        Loadout,
        LoadoutItem,
        Tile,
        TileColor,
    )

    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    board.tiles[4][1] = Tile(
        row=4,
        col=1,
        char="m",
        letter="M",
        base_score=0,
        color=TileColor.RED,
        curse=CurseType.ITEM,
        metadata={
            "scattered_item_id": "maple_leaf",
            "scattered_item_level": 2,
        },
    )
    loadout = Loadout(
        stickers=[LoadoutItem(id="maple_leaf", name="Maple Leaf", level=2)],
        boss_id="capybara",
        extras={
            "grid_number": "1",
            "boss_floor_modification": "2",
            "scoring_previous_words_count": "0",
        },
    )
    level = grid_path_sticker_level(
        loadout,
        "maple_leaf",
        board=board,
        path=[21],
        path_tile_index=0,
    )
    assert level == 1
