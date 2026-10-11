"""Capture-prep helpers shared by older capture tests (moved from the retired
pipeline replay test). New tests should use ``sim.replay.prepare_replay``."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from cursed_words_solver.loadout import prepare_run_state_dict_for_scoring
from cursed_words_solver.rules.scoring_conditions import normalize_scoring_path


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mismatches"


def _merge_submit_card_metadata(run_state: dict, data: dict) -> None:
    """Apply submit-time card_suit from capture; empty suit clears stale F8 suits."""
    submit_tiles = data.get("submit_board_tiles")
    if not isinstance(submit_tiles, list):
        return
    board = run_state.get("board")
    if not isinstance(board, dict):
        return
    tiles = board.get("tiles")
    if not isinstance(tiles, list):
        return
    card_at: dict[tuple[int, int], tuple[str, str, bool]] = {}
    for t in submit_tiles:
        if not isinstance(t, dict):
            continue
        key = (int(t["row"]), int(t["col"]))
        suit = str(t.get("card_suit") or "").strip()
        rank = str(t.get("card_rank") or "").strip()
        is_joker = t.get("is_joker") in (True, "true", "True", 1, "1")
        card_at[key] = (suit, rank, is_joker)

    if not card_at:
        return

    for tile in tiles:
        if not isinstance(tile, dict):
            continue
        key = (int(tile.get("row", -1)), int(tile.get("col", -1)))
        if key not in card_at:
            continue
        suit, rank, is_joker = card_at[key]
        # Set-or-clear: empty submit suit must wipe stale F8 card_suit.
        tile["card_suit"] = suit
        tile["card_rank"] = rank
        tile["is_joker"] = is_joker


def _strip_post_submit_historic_self(run_state: dict, data: dict) -> None:
    """Drop historic_words row that is the word under replay (post-submit snapshot lag).

    Captures often embed the just-scored word in historic_words; replaying poison
    from that row double-counts (howdied +74 = 1×740×0.1).
    """
    path = data.get("path")
    actual = data.get("actual_score")
    extras = dict(run_state.get("extras") or {})
    raw = extras.get("historic_words")
    if not raw:
        return
    try:
        rows = json.loads(raw) if isinstance(raw, str) else list(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return
    if not isinstance(rows, list) or not rows:
        return
    path_ints: list[int] | None = None
    if isinstance(path, list) and path:
        try:
            path_ints = [int(x) for x in path]
        except (TypeError, ValueError):
            path_ints = None
    actual_int: int | None = None
    if actual is not None:
        try:
            actual_int = int(actual)
        except (TypeError, ValueError):
            actual_int = None

    kept: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            kept.append(row)
            continue
        row_path = row.get("path")
        if path_ints is not None and isinstance(row_path, list):
            try:
                if [int(x) for x in row_path] == path_ints:
                    continue
            except (TypeError, ValueError):
                pass
        elif (
            actual_int is not None
            and row_path in (None, [])
            and int(row.get("score") or -1) == actual_int
            and int(row.get("green_tile_count") or 0) > 0
        ):
            # prepare_run_state may strip paths; match by score on poison rows.
            continue
        kept.append(row)
    if len(kept) == len(rows):
        return
    extras["historic_words"] = json.dumps(kept, ensure_ascii=False)
    try:
        spc = int(str(extras.get("scoring_previous_words_count") or "0").strip())
    except (TypeError, ValueError):
        spc = len(rows)
    extras["scoring_previous_words_count"] = str(max(0, min(spc, len(kept))))
    run_state["extras"] = extras


def _run_state_for_replay(data: dict) -> dict:
    """Merge submit-time extras into the F8 snapshot so replay matches in-game scoring."""
    payload = dict(data.get("run_state_snapshot") or {})
    if data.get("extras_snapshot") is not None:
        payload["extras_snapshot"] = data.get("extras_snapshot")
    if data.get("extras_diff") is not None:
        payload["extras_diff"] = data.get("extras_diff")
    if data.get("submit_board_tiles") is not None:
        payload["submit_board_tiles"] = data.get("submit_board_tiles")
    run_state = prepare_run_state_dict_for_scoring(payload)
    _merge_submit_card_metadata(run_state, data)
    _strip_post_submit_historic_self(run_state, data)
    return run_state


_BOTTOM_ORIGIN_PATH_STEMS = frozenset({"20260526_103842", "20260621_222004_upwells"})


def _replay_path(board, path: list[int], case_path: Path | None = None) -> list[int]:
    """Melmod mismatch captures use compact indices on Bat-shrunk boards.

    Full-grid captures predating the melmod bottom-origin flip keep storage indices.
    """
    if board is None:
        return list(path)
    from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

    captured_at = case_path.stem if case_path is not None else None
    if captured_at in _BOTTOM_ORIGIN_PATH_STEMS:
        captured_at = ""  # current layout
    return path_from_melmod_indices(board, path, captured_at=captured_at)


def _money_from_actual_trace(data: dict) -> int | None:
    """Peak bank $ during scoring; F8 snapshot can be behind in-run earnings."""
    trace = data.get("actual_trace")
    if not isinstance(trace, list):
        return None
    peak = 0
    for step in trace:
        if isinstance(step, dict) and step.get("money") is not None:
            peak = max(peak, int(step["money"]))
    return peak if peak > 0 else None


def _jack_o_lantern_money(loadout) -> int:
    for item in loadout.stickers:
        if item.id == "jack_o_lantern":
            return max(1, item.level)
    return 0


def engine_replay_score(data: dict) -> int:
    """Engine score of a capture's submitted path (``prepare_replay``: path layout,
    pre-submit extras, rack count). Mismatch bundles and round logs both work."""
    from cursed_words_solver.engine import EnginePlan
    from cursed_words_solver.sim.replay import prepare_replay

    capture = dict(data)
    if "run_state" not in capture and "run_state_snapshot" in capture:
        capture["run_state"] = capture["run_state_snapshot"]
        capture["actual"] = {"word": data.get("word", ""), "path": data.get("path", []), "score": data.get("actual_score")}
    prep, err = prepare_replay(capture)
    assert prep is not None, err
    score = EnginePlan.build(prep.board, prep.loadout).score(prep.submission.path, prep.submission.effective_scoring_word).int_score
    return -score if prep.two_wrongs else score
