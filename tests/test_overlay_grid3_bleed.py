"""Overlay highlights and grid-3 historic bleed (scoring cache empty)."""



from __future__ import annotations



import json

from pathlib import Path

from unittest.mock import MagicMock



from cursed_words_solver.config import Region

from cursed_words_solver.f8_messages import format_f8_block_reason_html

from cursed_words_solver.f8_snapshot import (

    embed_f8_snapshot,

    rebuild_snapshot_from_run_state,

)

from cursed_words_solver.models import Board, Loadout, WordResult

from cursed_words_solver.suggestion import (

    f8_historic_would_fail_submit_projection,

    f8_should_block_save,

    grid_transition_workflow_bleed_warning,

    scoring_cache_bleed_blocks_f8,

)





def _grid3_board_run_state(*, extras: dict | None = None) -> dict:

    fixture = json.loads(

        (

            Path(__file__).resolve().parent

            / "fixtures"

            / "stale_f8_beans_grid3_bleed.json"

        ).read_text(encoding="utf-8")

    )

    tiles = []

    for r in range(5):

        for c in range(5):

            tiles.append(

                {

                    "row": r,

                    "col": c,

                    "char": "a",

                    "letter": "A",

                    "base_score": 1,

                    "color": "colorless",

                    "curse": "letter",

                    "active": True,

                }

            )

    base_extras = {

        "grid_number": str(fixture["grid_number"]),

        "historic_words": fixture["historic_words"],

        "scoring_previous_words_count": "0",

        "encounter_historic_source": "live",

    }

    if extras:

        base_extras.update(extras)

    return {

        "board": {"tiles": tiles, "money": 0},

        "character": "Beans",

        "stickers": [],

        "stamps": [],

        "extras": base_extras,

    }





def test_raw_melmod_export_may_show_prior_grid_bleed():
    """Unreconciled melmod export can still flag bleed (encounter-wide historic)."""

    run_state = _grid3_board_run_state()

    extras = run_state["extras"]

    assert scoring_cache_bleed_blocks_f8(extras)

    warn = grid_transition_workflow_bleed_warning(extras)

    assert warn is not None

    assert "scoring cache is empty" in warn





def test_reconcile_clears_prior_grid_bleed_single_f8():

    """After gather reconcile, prior-grid historic is cleared — one F8 proceeds."""

    run_state = _grid3_board_run_state()

    snapshot = rebuild_snapshot_from_run_state(run_state, rules={})

    assert snapshot.loadout is not None

    reconciled = snapshot.loadout.extras

    assert isinstance(reconciled, dict)

    assert not scoring_cache_bleed_blocks_f8(reconciled)

    assert grid_transition_workflow_bleed_warning(reconciled) is None

    hist = str(reconciled.get("historic_words", "") or "").strip()

    assert not hist or hist == "[]"





def test_f8_should_not_block_after_reconcile_grid3():

    snapshot = rebuild_snapshot_from_run_state(_grid3_board_run_state(), rules={})

    assert snapshot.loadout is not None

    bleed = grid_transition_workflow_bleed_warning(snapshot.loadout.extras)

    blocked, reason = f8_should_block_save(

        gather_succeeded=True,

        grid_bleed_warn=bleed,

        loadout=snapshot.loadout,

    )

    assert not blocked

    assert reason is None





def test_embed_matches_submit_projection_grid3_beans(tmp_path, monkeypatch):

    from cursed_words_solver.loadout import RUN_STATE_PATH, parse_board_from_run_state



    run_state = _grid3_board_run_state()

    run_state_path = tmp_path / "run_state.json"

    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)

    run_state_path.write_text(json.dumps(run_state), encoding="utf-8")



    snapshot = rebuild_snapshot_from_run_state(run_state, rules={})

    board = parse_board_from_run_state(run_state)

    assert snapshot.loadout is not None

    assert board is not None



    embedded = embed_f8_snapshot(

        snapshot,

        scoring_loadout=snapshot.loadout,

        fresh_run_state=run_state,

    )

    assert embedded is not None

    f8_extras = embedded.get("extras")

    assert isinstance(f8_extras, dict)



    mismatch = f8_historic_would_fail_submit_projection(

        f8_extras,

        board=board,

        projected_extras=run_state["extras"],

    )

    assert mismatch is None





def test_format_f8_block_reason_html_submit_projection():

    html = format_f8_block_reason_html("submit_projection_mismatch")

    assert "UNTRUSTED" not in html

    assert "wait a moment" in html.lower()

    assert "f8 again" in html.lower()





def test_apply_solve_ui_shows_path_when_untrusted():

    from cursed_words_solver.app import SolverApp, _SolveUIUpdate

    from cursed_words_solver.config import AppConfig

    from cursed_words_solver.ui.layout import OverlayRegions



    config = AppConfig()

    config.board_region = Region(0, 0, 500, 500)

    config.show_board_highlight = True

    solver = SolverApp.__new__(SolverApp)

    solver.config = config

    solver._overlay_regions = OverlayRegions(

        board=config.board_region,

        rack=Region(),

        source="manual",

    )

    solver.overlay = MagicMock()

    solver.board_highlight = MagicMock()

    solver.rack_highlight = MagicMock()

    solver._clear_highlight_state = MagicMock()



    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0, active=[True] * 25)

    result = WordResult(word="test", path=[0, 1, 2], score=100)



    SolverApp._apply_solve_ui(

        solver,

        _SolveUIUpdate(

            board=board,

            results=[result],

            board_bgr=None,

            warnings_html=format_f8_block_reason_html("submit_projection_mismatch"),

            on_game_highlight=True,

            trusted_suggestion=False,

            block_reason="submit_projection_mismatch",

            melmod_board_fingerprint="fp",

            melmod_loadout_fingerprint="lfp",

        ),

    )



    solver.board_highlight.show_path.assert_called_once()

    solver._clear_highlight_state.assert_not_called()





def test_should_not_infer_spc_from_historic_grid2_fresh():

    from cursed_words_solver.loadout import (

        _should_infer_spc_from_historic,

        reconcile_scoring_previous_words_count,

    )



    extras = {

        "grid_number": "2",

        "historic_words": '[{"word":"test","path":[0,1,2]}]',

        "scoring_previous_words_count": "0",

        "encounter_historic_source": "live",

    }

    assert not _should_infer_spc_from_historic(extras)

    reconcile_scoring_previous_words_count(extras)

    assert extras["scoring_previous_words_count"] == "0"

