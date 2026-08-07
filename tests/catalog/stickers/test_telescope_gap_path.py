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


def test_telescope_purple_counts_as_red_running_and_bonus():
    """Purple IsTileType(red): Telescope prefix/bonus must include purple tiles."""
    from cursed_words_solver.models import (
        Board,
        CurseType,
        Loadout,
        LoadoutItem,
        Tile,
        TileColor,
    )

    def _cell(r: int, c: int, letter: str, color: TileColor, base: int = 1) -> Tile:
        return Tile(r, c, letter, letter, base, color, CurseType.LETTER)

    tiles = [[_cell(r, c, "x", TileColor.COLORLESS) for c in range(5)] for r in range(5)]
    tiles[0][0] = _cell(0, 0, "a", TileColor.PURPLE, base=2)
    tiles[0][1] = _cell(0, 1, "b", TileColor.COLORLESS, base=1)
    tiles[0][2] = _cell(0, 2, "c", TileColor.PURPLE, base=2)
    board = Board(tiles=tiles)
    path = [0, 1, 2]
    loadout = Loadout(
        stickers=[LoadoutItem(id="telescope", name="Telescope", level=1)],
        extras={"grid_number": "1", "scoring_previous_words_count": "0"},
    )
    assert telescope_running_red_count(loadout, board, path, 0) == 1
    assert telescope_running_red_count(loadout, board, path, 2) == 2

    score, _, trace = ScoringPipeline().score_with_trace(
        board, path, "abc", loadout
    )
    tele = [
        s
        for s in (trace or [])
        if isinstance(s, dict)
        and s.get("effect_type") == "red_encounter_tile_bonus"
    ]
    assert tele
    # L1: purple@0 +1*1 → 3, purple@2 +1*2 → 6; colorless middle unchanged
    assert tele[0]["tile_scores"] == [3.0, 1.0, 6.0]
    assert int(score) == 10


def test_telescope_purple_l2_matches_unsexed_tile_math():
    """unsexed-style: prior 22, L2, five purple path tiles → Telescope tile vector."""
    from cursed_words_solver.models import (
        Board,
        CurseType,
        Loadout,
        LoadoutItem,
        Tile,
        TileColor,
    )

    def _cell(
        r: int,
        c: int,
        letter: str,
        color: TileColor,
        base: float,
        *,
        curse: CurseType = CurseType.LETTER,
        meta: dict | None = None,
    ) -> Tile:
        return Tile(
            r, c, letter, letter, base, color, curse, metadata=meta or {}
        )

    tiles = [
        [_cell(r, c, "x", TileColor.COLORLESS, 0) for c in range(5)]
        for r in range(5)
    ]
    # Path faces mirroring unsexed actual_trace (indices 0..6 on a linear path).
    tiles[0][0] = _cell(
        0,
        0,
        "S",
        TileColor.PURPLE,
        0,
        curse=CurseType.ITEM,
        meta={"scattered_item_id": "telescope", "scattered_item_level": 2},
    )
    tiles[0][1] = _cell(0, 1, "N", TileColor.COLORLESS, 1)
    tiles[0][2] = _cell(0, 2, "N", TileColor.PURPLE, 3)
    tiles[0][3] = _cell(0, 3, "E", TileColor.PURPLE, 2)
    tiles[0][4] = _cell(0, 4, "X", TileColor.COLORLESS, 6)
    tiles[1][0] = _cell(1, 0, "E", TileColor.PURPLE, 2)
    tiles[1][1] = _cell(
        1,
        1,
        "O",
        TileColor.PURPLE,
        0,
        curse=CurseType.ITEM,
        meta={"scattered_item_id": "family_ticket", "scattered_item_level": 1},
    )
    board = Board(tiles=tiles)
    path = [0, 1, 2, 3, 4, 5, 6]
    loadout = Loadout(
        extras={
            "grid_number": "4",
            "scoring_previous_words_count": "1",
            "historic_words": json.dumps(
                [
                    {"red_tile_count": 7},
                    {"red_tile_count": 6},
                    {"red_tile_count": 9},
                ]
            ),
        }
    )
    assert telescope_running_red_count(loadout, board, path, 0) == 23
    assert telescope_running_red_count(loadout, board, path, 6) == 27
    score, _, trace = ScoringPipeline().score_with_trace(
        board, path, "snnexeo", loadout
    )
    tele = [
        s
        for s in (trace or [])
        if isinstance(s, dict)
        and s.get("effect_type") == "red_encounter_tile_bonus"
    ]
    assert tele
    assert tele[0]["tile_scores"] == [46.0, 1.0, 51.0, 52.0, 6.0, 54.0, 54.0]
    assert int(tele[0]["subtotal"]) == 264
    assert score >= 264


UNSEXED = FIXTURES / "20260801_224800.json"


def _overlay_path_tiles_on_board(board, path: list[int], path_tiles: list[dict]) -> None:
    from cursed_words_solver.models import CurseType, Tile, TileColor

    for idx, pt in zip(path, path_tiles):
        if not isinstance(pt, dict):
            continue
        row, col = divmod(int(idx), 5)
        color_raw = str(pt.get("color") or "colorless").lower()
        try:
            color = TileColor(color_raw)
        except ValueError:
            color = TileColor.COLORLESS
        curse_raw = str(pt.get("curse") or "letter").lower()
        try:
            curse = CurseType(curse_raw)
        except ValueError:
            curse = CurseType.LETTER
        letter = str(pt.get("letter") or "A")
        char = str(pt.get("char") or letter)
        base = float(pt.get("base_score") or 0)
        meta: dict = {}
        if "🔭" in char:
            meta["scattered_item_id"] = "telescope"
            meta["scattered_item_level"] = 2
            curse = CurseType.ITEM
        elif "🎟️" in char or "family_ticket" in str(
            pt.get("scattered_item_id") or ""
        ):
            meta["scattered_item_id"] = "family_ticket"
            meta["scattered_item_level"] = 1
            curse = CurseType.ITEM
        sid = pt.get("scattered_item_id")
        if sid:
            meta["scattered_item_id"] = sid
            try:
                meta["scattered_item_level"] = int(pt.get("scattered_item_level") or 1)
            except (TypeError, ValueError):
                meta["scattered_item_level"] = 1
            curse = CurseType.ITEM
        board.tiles[row][col] = Tile(
            row, col, char, letter, base, color, curse, metadata=meta
        )


def test_unsexed_telescope_purple_via_path_tiles():
    """20260801 unsexed: path_tiles board + purple-as-red Telescope → 2832."""
    if not UNSEXED.is_file():
        return
    data = json.loads(UNSEXED.read_text(encoding="utf-8"))
    run_state = dict(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = list(data["path"])
    _overlay_path_tiles_on_board(board, path, data.get("path_tiles") or [])
    apply_snapshot_phased_session_extras(loadout, board)
    score, _, trace = ScoringPipeline().score_with_trace(
        board, path, data["word"], loadout
    )
    assert int(score) == int(data["actual_score"]) == 2832
    tele = [
        s
        for s in (trace or [])
        if isinstance(s, dict)
        and s.get("effect_type") == "red_encounter_tile_bonus"
    ]
    assert tele
    assert tele[0]["tile_scores"] == [46.0, 1.0, 51.0, 52.0, 6.0, 54.0, 54.0]


ELSHIN = FIXTURES / "20260801_224419.json"


def test_elshin_electric_guitar_purple_note():
    """20260801 elshin: purple E is a red note → Guitar L2 +30 → 1200."""
    if not ELSHIN.is_file():
        return
    data = json.loads(ELSHIN.read_text(encoding="utf-8"))
    run_state = dict(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = list(data["path"])
    _overlay_path_tiles_on_board(board, path, data.get("path_tiles") or [])
    # path_tiles use emoji; ensure guitar/big_bang scatter metadata
    for idx, pt in zip(path, data.get("path_tiles") or []):
        if not isinstance(pt, dict):
            continue
        char = str(pt.get("char") or "")
        row, col = divmod(int(idx), 5)
        tile = board.tiles[row][col]
        if "🎸" in char:
            tile.metadata["scattered_item_id"] = "electric_guitar"
            tile.metadata["scattered_item_level"] = 2
        elif "💥" in char:
            tile.metadata["scattered_item_id"] = "big_bang"
            tile.metadata["scattered_item_level"] = 1
    apply_snapshot_phased_session_extras(loadout, board)
    score, _, trace = ScoringPipeline().score_with_trace(
        board, path, data["word"], loadout
    )
    assert int(score) == int(data["actual_score"]) == 1200
    guitar = [
        s
        for s in (trace or [])
        if isinstance(s, dict) and s.get("rule_id") == "electric_guitar" and s.get("applied")
    ]
    assert guitar
    assert guitar[0]["tile_scores"][0] == 32.0


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


def test_cherry_pie_scatter_keeps_export_when_extras_confirm_equipped_tier():
    """Equipped + on-path cherry_pie at same tier is not inventory bleed-through."""
    from cursed_words_solver.models import (
        Board,
        CurseType,
        Loadout,
        LoadoutItem,
        Tile,
        TileColor,
    )

    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    board.tiles[0][4] = Tile(
        row=0,
        col=4,
        char="🥧",
        letter="Y",
        base_score=0,
        color=TileColor.PURPLE,
        curse=CurseType.ITEM,
        metadata={
            "scattered_item_id": "cherry_pie",
            "scattered_item_level": 3,
        },
    )
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="toolbox", name="Toolbox", level=3),
            LoadoutItem(id="cherry_pie", name="Cherry Pie", level=3),
        ],
        extras={
            "grid_number": "1",
            "scoring_previous_words_count": "0",
            "grid_scattered_items": (
                '[{"row":0,"col":4,"id":"cherry_pie","level":3}]'
            ),
        },
    )
    level = grid_path_sticker_level(
        loadout,
        "cherry_pie",
        board=board,
        path=[4],
        path_tile_index=0,
    )
    assert level == 3


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
