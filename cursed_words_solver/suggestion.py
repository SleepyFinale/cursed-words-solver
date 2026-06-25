"""Persist F8 solver suggestion for melmod scoring comparison."""



from __future__ import annotations



import json

import copy

from datetime import datetime, timezone

from typing import Any



from cursed_words_solver.config import LAST_SUGGESTION_BLOCKED_PATH, LAST_SUGGESTION_PATH
from cursed_words_solver.f8_messages import F8_RETRY_HINT

from cursed_words_solver.dictionary import WordDictionary

from cursed_words_solver.fingerprints import (
    board_fingerprint,
    board_tiles_fingerprint_suffix,
    fingerprints_from_run_state,
)

from cursed_words_solver.models import (
    CHESS_CURSES,
    CURRENCY_MAP,
    Board,
    CurseType,
    Loadout,
    WordResult,
    normalize_tile_glyph,
)

from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import SearchFlagsMask, stamp_search_flags

from cursed_words_solver.rules.twinkle_toes import TwinkleToesSwap

from cursed_words_solver.search import (
    PathValidator,
    physical_word_for_path,
    resolve_letter,
    search_word_from_path,
    word_assignable_on_path,
)
from cursed_words_solver.ui.board_geometry import path_to_melmod_indices



SOLVER_VERSION = "0.1.0"

_F8_SEQUENCE_PATH = LAST_SUGGESTION_PATH.parent / ".f8_sequence"

# Melmod auto-export can update workflow extras shortly after F8 save.
F8_EXPORT_CATCHUP_GRACE_SEC = 2.5


def f8_export_catchup_grace_sec(search_budget_sec: float | None = None) -> float:
    """Grace period for post-F8 export catch-up (covers long searches)."""
    base = F8_EXPORT_CATCHUP_GRACE_SEC
    if search_budget_sec is None:
        return base
    return max(base, float(search_budget_sec) + 5.0)


def _board_tiles_match(saved_board_fp: str, cur_board_fp: str) -> bool:
    saved_tiles = board_tiles_fingerprint_suffix(saved_board_fp)
    cur_tiles = board_tiles_fingerprint_suffix(cur_board_fp)
    return bool(saved_tiles and cur_tiles and saved_tiles == cur_tiles)


def _parse_board_fp_tiles(fp: str) -> dict[tuple[int, int], str]:
    """Parse melmod-style board fingerprint tile segments."""
    tiles: dict[tuple[int, int], str] = {}
    suffix = board_tiles_fingerprint_suffix(fp)
    for segment in suffix.split(";"):
        segment = segment.strip()
        if not segment or ":" not in segment:
            continue
        coord, _, rest = segment.partition(":")
        if "," not in coord:
            continue
        row_s, _, col_s = coord.partition(",")
        try:
            key = (int(row_s), int(col_s))
        except ValueError:
            continue
        tiles[key] = rest
    return tiles


def _fp_tile_letter_prefix(fp_tile_segment: str) -> str:
    """Letter or currency glyph before the first '/' in a fingerprint tile segment."""
    return (fp_tile_segment.split("/")[0] or "").strip()


def _normalize_placement_letter(letter: str) -> str:
    """Map currency symbols to A–Z; preserve '?' wildcard."""
    raw = (letter or "").strip()
    if raw == "?":
        return "?"
    glyph = normalize_tile_glyph(raw)
    if glyph in CURRENCY_MAP:
        return CURRENCY_MAP[glyph].upper()
    if len(glyph) == 1 and glyph.isalpha():
        return glyph.upper()
    if len(raw) == 1 and raw.isalpha():
        return raw.upper()
    return raw.upper()


def _fp_tile_matches_placement(placement_letter: str, fp_tile_segment: str) -> bool:
    """True when melmod tile segment matches a suggested consumable placement letter."""
    if not (fp_tile_segment or "").strip():
        return False
    placed = _normalize_placement_letter(placement_letter)
    if placed == "?":
        return True
    cur = _normalize_placement_letter(_fp_tile_letter_prefix(fp_tile_segment))
    if not cur:
        return False
    return cur == placed or cur.startswith(placed) or placed.startswith(cur)


def _placement_cells_from_records(
    placements: list[Any],
) -> dict[tuple[int, int], str]:
    placement_cells: dict[tuple[int, int], str] = {}
    for rec in placements:
        if isinstance(rec, dict):
            row = rec.get("row")
            col = rec.get("col")
            letter = str(rec.get("letter") or "").strip().upper()
        else:
            row = getattr(rec, "row", None)
            col = getattr(rec, "col", None)
            letter = str(getattr(rec, "letter", "") or "").strip().upper()
        if row is None or col is None or not letter:
            continue
        placement_cells[(int(row), int(col))] = letter
    return placement_cells


def _twinkle_swap_coords_from_record(
    swap: Any,
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    if swap is None:
        return None
    if isinstance(swap, dict):
        row_a = swap.get("row_a")
        col_a = swap.get("col_a")
        row_b = swap.get("row_b")
        col_b = swap.get("col_b")
    else:
        row_a = getattr(swap, "row_a", None)
        col_a = getattr(swap, "col_a", None)
        row_b = getattr(swap, "row_b", None)
        col_b = getattr(swap, "col_b", None)
    try:
        return (int(row_a), int(col_a)), (int(row_b), int(col_b))
    except (TypeError, ValueError):
        return None


def fingerprint_change_is_suggested_board_progress(
    saved_board_fp: str,
    current_board_fp: str,
    *,
    placements: list[Any] | None = None,
    swap: Any | None = None,
) -> bool:
    """True when board drift matches suggested consumable placements and/or Twinkle Toes swap."""
    placement_cells = _placement_cells_from_records(placements or [])
    swap_coords = _twinkle_swap_coords_from_record(swap)
    swap_keys: set[tuple[int, int]] = set()
    if swap_coords is not None:
        swap_keys = {swap_coords[0], swap_coords[1]}

    if not placement_cells and not swap_keys:
        return False

    saved = _parse_board_fp_tiles(saved_board_fp)
    current = _parse_board_fp_tiles(current_board_fp)
    if not saved or not current:
        return False

    if swap_coords is not None:
        key_a, key_b = swap_coords
        if key_a not in saved or key_b not in saved:
            return False

    all_keys = set(saved) | set(current)
    changed_keys = {key for key in all_keys if saved.get(key) != current.get(key)}
    if not changed_keys:
        return False

    allowed_keys = set(placement_cells.keys()) | swap_keys
    if not changed_keys.issubset(allowed_keys):
        return False

    for key in changed_keys:
        if key in placement_cells:
            if not _fp_tile_matches_placement(placement_cells[key], current.get(key, "")):
                return False

    if swap_coords is not None:
        key_a, key_b = swap_coords
        if key_a not in placement_cells and key_a in changed_keys:
            if saved.get(key_b) != current.get(key_a):
                return False
        if key_b not in placement_cells and key_b in changed_keys:
            if saved.get(key_a) != current.get(key_b):
                return False

    return True


def fingerprint_change_is_consumable_placement_progress(
    saved_board_fp: str,
    current_board_fp: str,
    placements: list[Any],
) -> bool:
    """True when board drift is only rack consumables placed at suggested cells (partial OK)."""
    return fingerprint_change_is_suggested_board_progress(
        saved_board_fp,
        current_board_fp,
        placements=placements,
        swap=None,
    )


def fingerprint_change_is_suggested_consumable_placement_only(
    saved_board_fp: str,
    current_board_fp: str,
    placements: list[Any],
) -> bool:
    """Alias for placement-progress check (supports one-at-a-time rack placement)."""
    return fingerprint_change_is_consumable_placement_progress(
        saved_board_fp,
        current_board_fp,
        placements,
    )


def fingerprint_invalidate_suppressed_for_consumable_placement(
    current_board_fp: str,
) -> bool:
    """Keep F8 suggestion/highlight when user placed suggested consumables only."""
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return False
    placements = data.get("consumable_placements")
    if not isinstance(placements, list) or not placements:
        return False
    saved_board = str(data.get("board_fingerprint") or "").strip()
    cur_board = (current_board_fp or "").strip()
    if not saved_board or not cur_board or saved_board == cur_board:
        return False
    return fingerprint_change_is_suggested_board_progress(
        saved_board,
        cur_board,
        placements=placements,
        swap=None,
    )


def fingerprint_change_is_twinkle_toes_swap_progress(
    saved_board_fp: str,
    current_board_fp: str,
    swap: Any,
) -> bool:
    """True when board drift is only the suggested Twinkle Toes tile swap."""
    return fingerprint_change_is_suggested_board_progress(
        saved_board_fp,
        current_board_fp,
        placements=None,
        swap=swap,
    )


def fingerprint_invalidate_suppressed_for_twinkle_toes_swap(
    current_board_fp: str,
) -> bool:
    """Keep F8 suggestion/highlight when user performed the suggested Twinkle Toes swap."""
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return False
    swap = data.get("twinkle_toes_swap")
    if not isinstance(swap, dict) or not swap:
        return False
    saved_board = str(data.get("board_fingerprint") or "").strip()
    cur_board = (current_board_fp or "").strip()
    if not saved_board or not cur_board or saved_board == cur_board:
        return False
    return fingerprint_change_is_suggested_board_progress(
        saved_board,
        cur_board,
        placements=None,
        swap=swap,
    )


def fingerprint_invalidate_suppressed_for_suggested_board_change(
    current_board_fp: str,
) -> bool:
    """Keep F8 suggestion when board drift matches suggested consumables and/or swap."""
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return False
    saved_board = str(data.get("board_fingerprint") or "").strip()
    cur_board = (current_board_fp or "").strip()
    if not saved_board or not cur_board or saved_board == cur_board:
        return False
    placements = data.get("consumable_placements")
    if not isinstance(placements, list):
        placements = None
    swap = data.get("twinkle_toes_swap")
    if not isinstance(swap, dict) or not swap:
        swap = None
    if not placements and swap is None:
        return False
    return fingerprint_change_is_suggested_board_progress(
        saved_board,
        cur_board,
        placements=placements,
        swap=swap,
    )


def stale_suggestion_warning(
    current_board_fp: str,
    *,
    current_loadout_fp: str | None = None,
) -> str | None:
    """Return a startup note when last F8 was for a different board or run context."""
    current = (current_board_fp or "").strip()
    if not current or not LAST_SUGGESTION_PATH.exists():
        return None
    try:
        data = json.loads(LAST_SUGGESTION_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    previous_board = str(data.get("board_fingerprint") or "").strip()
    loadout = (current_loadout_fp or "").strip()
    previous_loadout = str(data.get("loadout_fingerprint") or "").strip()
    same_board = previous_board == current or _board_tiles_match(previous_board, current)
    if previous_board and same_board:
        if loadout and previous_loadout and previous_loadout != loadout:
            return (
                "Note: loadout changed since last F8 (e.g. Bicycle acc) — "
                "press F8 again before submitting."
            )
        return None
    if not previous_board:
        return None
    if loadout and previous_loadout and previous_loadout != loadout:
        return (
            "Note: last F8 was for a different run — "
            "press F8 to refresh before submitting."
        )
    if fingerprint_invalidate_suppressed_for_suggested_board_change(current):
        return None
    return (
        "Note: board changed since last F8 — "
        "press F8 again before submitting."
    )


def _last_suggestion_fingerprint_data() -> dict[str, Any] | None:
    if not LAST_SUGGESTION_PATH.exists():
        return None
    try:
        data = json.loads(LAST_SUGGESTION_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _mutating_dna_letter_counts_equal(previous: str, current: str) -> bool:
    """True when JSON letter-count maps match (key order ignored)."""
    prev = (previous or "").strip() or "{}"
    cur = (current or "").strip() or "{}"
    if prev == cur:
        return True
    try:
        prev_obj = json.loads(prev)
        cur_obj = json.loads(cur)
    except (json.JSONDecodeError, TypeError):
        return prev == cur
    if not isinstance(prev_obj, dict) or not isinstance(cur_obj, dict):
        return prev == cur
    prev_norm = {
        str(k).lower(): int(v)
        for k, v in prev_obj.items()
        if str(k).strip()
    }
    cur_norm = {
        str(k).lower(): int(v)
        for k, v in cur_obj.items()
        if str(k).strip()
    }
    return prev_norm == cur_norm


def _historic_words_count(raw: str) -> int:
    """Parse historic_words JSON array length safely."""
    raw = (raw or "").strip()
    if not raw or raw == "[]":
        return 0
    try:
        arr = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return 0
    return len(arr) if isinstance(arr, list) else 0


def _last_historic_word_first_letter(raw: str) -> str:
    """First letter of the last word in melmod historic_words JSON."""
    from cursed_words_solver.loadout import _previous_letter_from_historic_words

    return _previous_letter_from_historic_words(raw)


def historic_previous_letter_mismatch_warning(
    run_state_extras: dict[str, Any] | None,
) -> str | None:
    """Warn when previous_word_first_letter disagrees with the last historic word."""
    extras = run_state_extras if isinstance(run_state_extras, dict) else {}
    prev = str(extras.get("previous_word_first_letter", "") or "").strip().lower()
    hist = str(extras.get("historic_words", "") or "").strip()
    last_letter = _last_historic_word_first_letter(hist)
    if not prev or not last_letter or prev == last_letter:
        return None
    return (
        f"run_state previous_word_first_letter ({prev}) does not match "
        f"last historic word ({last_letter}) — press F8 again."
    )


def empty_historic_on_later_grid_warning(
    run_state_extras: dict[str, Any] | None,
) -> str | None:
    """Warn when grid 2+ has no encounter historic in run_state (F8 score may be wrong)."""
    extras = run_state_extras if isinstance(run_state_extras, dict) else {}
    try:
        grid = int(str(extras.get("grid_number") or "0"))
    except ValueError:
        return None
    if grid < 2:
        return None
    hist = str(extras.get("historic_words", "") or "").strip()
    if hist and hist != "[]":
        return None
    try:
        spc = int(str(extras.get("scoring_previous_words_count") or "0"))
    except (TypeError, ValueError):
        spc = 0
    if spc == 0:
        return None
    msg = (
        f"run_state has no encounter historic on grid {grid} — {F8_RETRY_HINT}."
    )
    try:
        red_enc = int(str(extras.get("red_tiles_used_encounter") or "0"))
    except (TypeError, ValueError):
        red_enc = 0
    if red_enc > 0:
        msg += (
            f" (red_tiles_used_encounter={red_enc} — Telescope may use count fallback only)"
        )
    return msg


def grid_advanced_since_last_f8_warning(
    run_state_extras: dict[str, Any] | None,
) -> str | None:
    """Warn when grid_number advanced since the prior F8 embed."""
    if not LAST_SUGGESTION_PATH.exists():
        return None
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return None
    f8_extras = _f8_snapshot_extras(data)
    cur = run_state_extras if isinstance(run_state_extras, dict) else {}
    try:
        grid_f8 = int(str(f8_extras.get("grid_number") or "0"))
        grid_cur = int(str(cur.get("grid_number") or "0"))
    except ValueError:
        return None
    if grid_cur > grid_f8 >= 1:
        return (
            f"Grid advanced ({grid_f8}→{grid_cur}) since last F8 — "
            "press F8 again before trusting scores."
        )
    return None


def _last_suggestion_age_sec(data: dict[str, Any] | None = None) -> float | None:
    """Seconds since last_suggestion.json was written, or None if unknown."""
    if data is None:
        data = _last_suggestion_fingerprint_data()
    if not data:
        return None
    raw = str(data.get("created_at") or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        created = datetime.fromisoformat(raw)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0.0, (now - created).total_seconds())
    except (ValueError, TypeError):
        return None


def is_embed_stale_drift(
    f8_extras: dict[str, Any] | None,
    cur_extras: dict[str, Any] | None,
) -> bool:
    """True when F8 embed workflow is ahead of or inconsistent with live export."""
    f8 = f8_extras if isinstance(f8_extras, dict) else {}
    cur = cur_extras if isinstance(cur_extras, dict) else {}
    hist_f8 = str(f8.get("historic_words", "") or "").strip()
    hist_cur = str(cur.get("historic_words", "") or "").strip()
    count_f8 = _historic_words_count(hist_f8)
    count_cur = _historic_words_count(hist_cur)
    if count_f8 > count_cur and (hist_f8 or hist_cur):
        return True
    if (
        hist_f8
        and hist_cur
        and hist_f8 != hist_cur
        and count_cur < count_f8
    ):
        return True
    scattered_f8 = str(f8.get("grid_scattered_items", "") or "").strip()
    scattered_cur = str(cur.get("grid_scattered_items", "") or "").strip()
    if scattered_f8 and scattered_f8 != "[]" and not scattered_cur:
        return True
    return False


def is_disk_catchup_drift(
    f8_extras: dict[str, Any] | None,
    cur_extras: dict[str, Any] | None,
) -> bool:
    """True when live run_state likely caught up from melmod export lag after F8."""
    if is_embed_stale_drift(f8_extras, cur_extras):
        return False
    f8 = f8_extras if isinstance(f8_extras, dict) else {}
    cur = cur_extras if isinstance(cur_extras, dict) else {}
    hist_f8 = str(f8.get("historic_words", "") or "").strip()
    hist_cur = str(cur.get("historic_words", "") or "").strip()
    if hist_f8 == hist_cur:
        try:
            spc_f8 = int(
                str(f8.get("scoring_previous_words_count", "") or "0").strip()
            )
            spc_cur = int(
                str(cur.get("scoring_previous_words_count", "") or "0").strip()
            )
            if spc_cur > spc_f8:
                return True
        except ValueError:
            pass
        prev_f8 = str(f8.get("previous_word_first_letter", "") or "").strip().lower()
        prev_cur = str(cur.get("previous_word_first_letter", "") or "").strip().lower()
        return bool(prev_f8 and prev_cur and prev_f8 != prev_cur)
    count_f8 = _historic_words_count(hist_f8)
    count_cur = _historic_words_count(hist_cur)
    if count_cur > count_f8:
        return True
    if count_cur == count_f8:
        prev_f8 = str(f8.get("previous_word_first_letter", "") or "").strip().lower()
        prev_cur = str(cur.get("previous_word_first_letter", "") or "").strip().lower()
        if prev_f8 and prev_cur and prev_f8 != prev_cur:
            return True
    try:
        bday_f8 = int(str(f8.get("birthday_cake_bonus") or "0"))
        bday_cur = int(str(cur.get("birthday_cake_bonus") or "0"))
        if bday_cur > bday_f8:
            return True
    except (TypeError, ValueError):
        pass
    return False


def is_export_catchup_drift(
    f8_extras: dict[str, Any] | None,
    cur_extras: dict[str, Any] | None,
) -> bool:
    """Alias for disk catchup drift (melmod export lag after F8, not embed ahead)."""
    return is_disk_catchup_drift(f8_extras, cur_extras)


def fingerprint_invalidate_suppressed_for_post_f8_export(
    current_board_fp: str,
    *,
    search_budget_sec: float | None = None,
) -> bool:
    """Skip board-fp poll clear when melmod refreshed money but tiles are unchanged."""
    if not LAST_SUGGESTION_PATH.exists():
        return False
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return False
    age = _last_suggestion_age_sec(data)
    grace = f8_export_catchup_grace_sec(search_budget_sec)
    if age is None or age > grace:
        return False
    saved_board = str(data.get("board_fingerprint") or "").strip()
    cur_board = (current_board_fp or "").strip()
    if not saved_board or not cur_board:
        return False
    return _board_tiles_match(saved_board, cur_board)


def workflow_invalidate_suppressed_for_export_catchup(
    run_state_extras: dict[str, Any] | None,
    *,
    current_board_fp: str = "",
    search_budget_sec: float | None = None,
) -> bool:
    """Skip workflow invalidation when melmod export likely lagged after F8."""
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return False
    f8_extras = _f8_snapshot_extras(data)
    cur_extras = run_state_extras if isinstance(run_state_extras, dict) else {}
    if is_embed_stale_drift(f8_extras, cur_extras):
        return False
    f8_board = str(data.get("board_fingerprint") or "").strip()
    cur_board = (current_board_fp or "").strip()
    if not f8_board or not cur_board or not _board_tiles_match(f8_board, cur_board):
        return False
    return is_disk_catchup_drift(f8_extras, cur_extras)


def grid_one_historic_cache_mismatch_warning(
    run_state_extras: dict[str, Any] | None,
) -> str | None:
    """Warn when grid 1 has encounter historic but the scoring cache is empty."""
    extras = run_state_extras if isinstance(run_state_extras, dict) else {}
    try:
        grid = int(str(extras.get("grid_number") or "0"))
    except ValueError:
        return None
    if grid != 1:
        return None
    hist = str(extras.get("historic_words", "") or "").strip()
    hist_count = _historic_words_count(hist)
    if hist_count == 0:
        return None
    try:
        scoring_count = int(str(extras.get("scoring_previous_words_count") or "0"))
    except ValueError:
        scoring_count = 0
    source = str(extras.get("encounter_historic_source", "") or "").strip().lower()
    if scoring_count == 0 or source == "grid1_no_scoring_cache":
        return (
            f"Grid 1 has {hist_count} encounter historic word(s) but scoring cache is "
            f"empty (spc={scoring_count}) — Telescope scores may be wrong; "
            f"{F8_RETRY_HINT}."
        )
    return None


def grid_transition_workflow_bleed_warning(
    run_state_extras: dict[str, Any] | None,
) -> str | None:
    """Warn when encounter workflow extras likely bled from a prior grid."""
    extras = run_state_extras if isinstance(run_state_extras, dict) else {}
    source = str(extras.get("encounter_historic_source", "") or "").strip().lower()
    hist = str(extras.get("historic_words", "") or "").strip()
    hist_count = _historic_words_count(hist)
    try:
        grid = int(str(extras.get("grid_number") or "0"))
    except ValueError:
        grid = 0
    try:
        scoring_count = int(str(extras.get("scoring_previous_words_count") or "0"))
    except ValueError:
        scoring_count = 0

    if grid == 1 and hist_count > 0 and scoring_count == 0:
        return (
            f"Grid 1 encounter historic ({hist_count} words) with empty scoring cache — "
            f"press F8 again before trusting Telescope scores."
        )

    if grid >= 2 and hist_count > 0 and scoring_count == 0:
        return (
            f"Grid {grid} has prior-grid encounter historic ({hist_count} words) but "
            f"scoring cache is empty — {F8_RETRY_HINT}."
        )

    if source in ("grid_advanced", "grid_advanced_disk") and hist_count > 0:
        if scoring_count < hist_count:
            return (
                f"Encounter historic may be from prior grid ({hist_count} exported words, "
                f"scoring cache {scoring_count}) — {F8_RETRY_HINT}."
            )
    scattered = str(extras.get("grid_scattered_items", "") or "").strip()
    if (
        scattered
        and scattered != "[]"
        and source in ("grid_advanced", "grid_advanced_disk")
    ):
        return (
            "grid_scattered_items may be stale after grid advance — "
            f"{F8_RETRY_HINT}."
        )
    return None


def scoring_cache_bleed_blocks_f8(
    run_state_extras: dict[str, Any] | None,
) -> bool:
    """True when grid 2+ has prior-grid historic but melmod scoring cache is still empty."""
    extras = run_state_extras if isinstance(run_state_extras, dict) else {}
    hist = str(extras.get("historic_words", "") or "").strip()
    hist_count = _historic_words_count(hist)
    try:
        grid = int(str(extras.get("grid_number") or "0"))
    except ValueError:
        grid = 0
    try:
        scoring_count = int(str(extras.get("scoring_previous_words_count") or "0"))
    except ValueError:
        scoring_count = 0
    return grid >= 2 and hist_count > 0 and scoring_count == 0


def run_state_historic_stale_warnings(
    run_state_extras: dict[str, Any] | None,
) -> list[str]:
    """Collect workflow warnings for stale encounter historic before solving."""
    warnings: list[str] = []
    for fn in (
        grid_one_historic_cache_mismatch_warning,
        grid_transition_workflow_bleed_warning,
        grid_advanced_since_last_f8_warning,
        historic_previous_letter_mismatch_warning,
        empty_historic_on_later_grid_warning,
    ):
        note = fn(run_state_extras)
        if note:
            warnings.append(note)
    return warnings


def _f8_snapshot_extras(data: dict[str, Any]) -> dict[str, Any]:
    snapshot = data.get("run_state_snapshot")
    if isinstance(snapshot, dict):
        raw = snapshot.get("extras")
        if isinstance(raw, dict):
            return raw
    return {}


def has_played_word_since_f8_embed(
    live_extras: dict[str, Any] | None,
    embed_extras: dict[str, Any] | None,
) -> bool:
    """True when melmod workflow advanced since F8 (mirrors HasPlayedWordSinceF8)."""
    live = live_extras if isinstance(live_extras, dict) else {}
    embed = embed_extras if isinstance(embed_extras, dict) else {}

    hist_embed = str(embed.get("historic_words", "") or "").strip()
    hist_live = str(live.get("historic_words", "") or "").strip()
    if hist_embed != hist_live and (hist_embed or hist_live):
        count_embed = _historic_words_count(hist_embed)
        count_live = _historic_words_count(hist_live)
        if count_live > count_embed:
            return True

    # spc-only drift after historic sync in the F8 embed is not "played since F8".
    return False


def describe_f8_prediction_historic_stale_note(
    f8_extras: dict[str, Any] | None,
    authoritative_extras: dict[str, Any] | None,
) -> str | None:
    """Mirror melmod ExtrasDiffHelper.DescribeF8PredictionHistoricStaleNote."""
    f8 = f8_extras if isinstance(f8_extras, dict) else {}
    auth = authoritative_extras if isinstance(authoritative_extras, dict) else {}
    f8_raw = str(f8.get("historic_words", "") or "").strip()
    auth_raw = str(auth.get("historic_words", "") or "").strip()
    f8_count = _historic_words_count(f8_raw)
    auth_count = _historic_words_count(auth_raw)

    def _prev_letter_drift() -> bool:
        f8_l = str(f8.get("previous_word_first_letter", "") or "").strip()
        auth_l = str(auth.get("previous_word_first_letter", "") or "").strip()
        if not f8_l or not auth_l:
            return False
        return f8_l.lower() != auth_l.lower()

    if auth_count <= f8_count:
        if f8_count > auth_count and _prev_letter_drift():
            return (
                f"F8 prediction used {f8_count}-word historic, score used "
                f"{auth_count}-word historic (previous word letter drift)"
            )
        if _prev_letter_drift():
            return (
                f"F8 prediction used {f8_count}-word historic, score used "
                f"{auth_count}-word historic (previous word letter drift)"
            )
        if f8_count > 0 and auth_count == f8_count and f8_raw != auth_raw:
            return (
                f"F8 prediction used {f8_count}-word historic, score used "
                f"{auth_count}-word historic (historic_words changed)"
            )
        if has_played_word_since_f8_embed(auth, f8):
            return "F8 prediction historic lag (workflow advanced since F8)"
        return None

    if not f8_raw and auth_count > 0:
        return (
            f"F8 prediction used empty historic, score used "
            f"{auth_count}-word historic"
        )
    return (
        f"F8 prediction used {f8_count}-word historic, score used "
        f"{auth_count}-word historic"
    )


def f8_historic_would_fail_submit_projection(
    embed_extras: dict[str, Any] | None,
    *,
    board: Board | None = None,
    projected_extras: dict[str, Any] | None = None,
) -> str | None:
    """True when melmod would block capture for historic lag at submit."""
    from cursed_words_solver.loadout import (
        load_run_state_raw,
        project_workflow_extras_for_f8_embed,
        reconcile_encounter_historic_for_scoring,
    )

    if projected_extras is not None:
        source_extras = copy.deepcopy(projected_extras)
        reconcile_encounter_historic_for_scoring(source_extras, board=board)
    else:
        fresh = load_run_state_raw()
        if not isinstance(fresh, dict):
            return None
        fresh_extras = fresh.get("extras")
        if not isinstance(fresh_extras, dict):
            return None
        source_extras = copy.deepcopy(fresh_extras)
        project_workflow_extras_for_f8_embed(source_extras, board=board)
    embed = embed_extras if isinstance(embed_extras, dict) else {}
    embed_hist = str(embed.get("historic_words", "") or "").strip()
    proj_hist = str(source_extras.get("historic_words", "") or "").strip()
    embed_count = _historic_words_count(embed_hist)
    proj_count = _historic_words_count(proj_hist)

    if embed_count == 0:
        try:
            proj_spc = int(str(source_extras.get("scoring_previous_words_count") or "0"))
        except (TypeError, ValueError):
            proj_spc = 0
        if proj_count > 0 or proj_spc > 0:
            return describe_f8_prediction_historic_stale_note(embed, source_extras)
        return None
    if proj_count > embed_count:
        return None

    if embed_count > proj_count:
        return (
            f"F8 embed historic ({embed_count} words) ahead of submit projection "
            f"({proj_count} words)"
        )

    return describe_f8_prediction_historic_stale_note(embed, source_extras)


def workflow_stale_vs_f8_snapshot(
    run_state_extras: dict[str, Any] | None,
    f8_snapshot_extras: dict[str, Any] | None,
) -> str | None:
    """Human-readable reason when workflow extras drifted since F8 (mirrors melmod)."""
    extras = run_state_extras if isinstance(run_state_extras, dict) else {}
    f8_extras = f8_snapshot_extras if isinstance(f8_snapshot_extras, dict) else {}
    notes: list[str] = []

    prev_letter_f8 = str(f8_extras.get("previous_word_first_letter", "") or "").strip()
    prev_letter_cur = str(extras.get("previous_word_first_letter", "") or "").strip()
    if (
        prev_letter_f8
        and prev_letter_cur
        and prev_letter_f8.lower() != prev_letter_cur.lower()
    ):
        notes.append(f"previous word letter {prev_letter_f8}→{prev_letter_cur}")

    hist_f8 = str(f8_extras.get("historic_words", "") or "").strip()
    hist_cur = str(extras.get("historic_words", "") or "").strip()
    if hist_f8 != hist_cur and (hist_f8 or hist_cur):
        count_f8 = _historic_words_count(hist_f8)
        count_cur = _historic_words_count(hist_cur)
        if count_cur > count_f8:
            notes.append(f"historic words changed ({count_f8}→{count_cur})")
        elif hist_f8 and hist_cur:
            notes.append("historic words changed")

    prev_dna = str(f8_extras.get("mutating_dna_letter_counts", "") or "").strip()
    cur_dna = str(extras.get("mutating_dna_letter_counts", "") or "").strip()
    has_dna = (prev_dna and prev_dna != "{}") or (cur_dna and cur_dna != "{}")
    if (
        has_dna
        and prev_dna
        and cur_dna
        and not _mutating_dna_letter_counts_equal(prev_dna, cur_dna)
    ):
        notes.append("mutating DNA counts changed")

    try:
        spc_f8 = int(str(f8_extras.get("scoring_previous_words_count", "") or "").strip())
    except ValueError:
        spc_f8 = None
    try:
        spc_cur = int(str(extras.get("scoring_previous_words_count", "") or "").strip())
    except ValueError:
        spc_cur = None
    if spc_f8 is not None and spc_cur is not None and spc_cur > spc_f8:
        notes.append(f"scoring previous words count {spc_f8}→{spc_cur}")
    if spc_f8 is not None and spc_cur is not None and spc_f8 > spc_cur:
        notes.append(f"scoring previous words count {spc_f8}→{spc_cur}")

    if not notes:
        return None
    return "; ".join(notes)


def f8_prediction_workflow_stale_warning(
    run_state_extras: dict[str, Any] | None,
    f8_snapshot_extras: dict[str, Any] | None,
) -> str | None:
    """Blocking-style warning when live run_state workflow drifted from the F8 embed."""
    reason = workflow_stale_vs_f8_snapshot(run_state_extras, f8_snapshot_extras)
    if reason is None:
        return None
    return (
        f"F8 prediction may be wrong ({reason}) — press F8 again."
    )


def f8_prior_suggestion_stale_note(
    run_state_extras: dict[str, Any] | None,
) -> str | None:
    """Note when run_state workflow drifted since the prior F8 embed (before overwriting)."""
    if not LAST_SUGGESTION_PATH.exists():
        return None
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return None
    reason = workflow_stale_vs_f8_snapshot(
        run_state_extras if isinstance(run_state_extras, dict) else {},
        _f8_snapshot_extras(data),
    )
    if reason is None:
        return None
    return (
        "Played a word since last F8 "
        f"({reason}) — prior overlay suggestion was stale; this F8 refreshes it."
    )


def clear_stale_last_suggestion_if_workflow_changed(
    run_state_extras: dict[str, Any] | None,
) -> str | None:
    """Remove last_suggestion.json when a word was played since F8 (no board-fp gate)."""
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return None
    reason = workflow_stale_vs_f8_snapshot(
        run_state_extras,
        _f8_snapshot_extras(data),
    )
    if reason is None:
        return None
    if clear_last_suggestion():
        return reason
    return None


def clear_stale_last_suggestion_if_fingerprint_changed(
    current_board_fp: str,
    *,
    current_loadout_fp: str | None = None,
) -> str | None:
    """Remove last_suggestion.json when board or loadout fingerprint drifted since F8."""
    if not LAST_SUGGESTION_PATH.exists():
        return None
    note = stale_suggestion_warning(
        current_board_fp,
        current_loadout_fp=current_loadout_fp,
    )
    if note is None:
        return None
    if clear_last_suggestion():
        return note
    return None


def _active_session_same_board_tiles(
    active_session: Any,
    current_board_fp: str,
) -> bool:
    if active_session is None:
        return False
    session_tiles = str(
        getattr(active_session, "board_tiles_fingerprint", "") or ""
    ).strip()
    cur_tiles = board_tiles_fingerprint_suffix(current_board_fp)
    return bool(session_tiles and cur_tiles and session_tiles == cur_tiles)


def poll_invalidate_last_suggestion(
    run_state_extras: dict[str, Any] | None,
    *,
    current_board_fp: str = "",
    current_loadout_fp: str | None = None,
    search_budget_sec: float | None = None,
    active_session: Any = None,
) -> str | None:
    """Clear last_suggestion.json when board tiles, loadout, or workflow extras change."""
    if not LAST_SUGGESTION_PATH.exists():
        return None

    if fingerprint_invalidate_suppressed_for_suggested_board_change(
        current_board_fp
    ):
        return None

    data = _last_suggestion_fingerprint_data()
    saved_board = str((data or {}).get("board_fingerprint") or "").strip()
    if not _board_tiles_match(saved_board, current_board_fp):
        fp_reason = clear_stale_last_suggestion_if_fingerprint_changed(
            current_board_fp,
            current_loadout_fp=current_loadout_fp,
        )
        if fp_reason:
            return fp_reason

    previous_loadout = str((data or {}).get("loadout_fingerprint") or "").strip()
    current_loadout = (current_loadout_fp or "").strip()
    if current_loadout and previous_loadout and previous_loadout != current_loadout:
        if clear_stale_last_suggestion_if_fingerprint_changed(
            current_board_fp,
            current_loadout_fp=current_loadout_fp,
        ):
            return "loadout changed"

    if data is not None and saved_board and _board_tiles_match(saved_board, current_board_fp):
        extras = run_state_extras if isinstance(run_state_extras, dict) else {}
        embed_extras = _f8_snapshot_extras(data)
        if _active_session_same_board_tiles(active_session, current_board_fp):
            return None
        if workflow_invalidate_suppressed_for_export_catchup(
            extras,
            current_board_fp=current_board_fp,
            search_budget_sec=search_budget_sec,
        ):
            return None
        if not has_played_word_since_f8_embed(extras, embed_extras):
            return None
        workflow_reason = workflow_stale_vs_f8_snapshot(
            extras,
            embed_extras,
        )
        if workflow_reason and clear_last_suggestion():
            return f"workflow drift ({workflow_reason})"

    return None


def poll_invalidation_is_workflow_stale(reason: str | None) -> bool:
    """True when poll cleared the suggestion due to workflow extras drift."""
    return bool(reason and reason.startswith("workflow drift ("))


def clear_stale_last_suggestion_if_context_changed(
    current_board_fp: str,
    *,
    current_loadout_fp: str | None = None,
    run_state_extras: dict[str, Any] | None = None,
) -> bool:
    """Remove last_suggestion.json when board/loadout/extras drift on the same board."""
    data = _last_suggestion_fingerprint_data()
    if data is None:
        return False
    previous_board = str(data.get("board_fingerprint") or "").strip()
    current_board = (current_board_fp or "").strip()
    if not previous_board or not current_board or previous_board != current_board:
        return False

    previous_loadout = str(data.get("loadout_fingerprint") or "").strip()
    current_loadout = (current_loadout_fp or "").strip()
    if current_loadout and previous_loadout and previous_loadout != current_loadout:
        return clear_last_suggestion()

    snapshot_extras = _f8_snapshot_extras(data)
    extras = run_state_extras if isinstance(run_state_extras, dict) else {}
    if workflow_stale_vs_f8_snapshot(extras, snapshot_extras):
        return clear_last_suggestion()

    for key in ("bicycle_word_score_bonus", "cards_submitted"):
        prev = str(snapshot_extras.get(key, "") or "").strip()
        cur = str(extras.get(key, "") or "").strip()
        if prev and cur and prev != cur:
            return clear_last_suggestion()
    return False


def clear_last_suggestion() -> bool:
    """Remove last_suggestion.json (failed solve or explicit invalidation)."""
    cleared = False
    for path in (LAST_SUGGESTION_PATH, LAST_SUGGESTION_BLOCKED_PATH):
        if not path.exists():
            continue
        try:
            path.unlink()
            cleared = True
        except OSError:
            pass
    return cleared


def clear_stale_last_suggestion_if_loadout_changed(current_loadout_fp: str) -> bool:
    """Remove last_suggestion.json when character/loadout changed (new run)."""
    current = (current_loadout_fp or "").strip()
    if not current or not LAST_SUGGESTION_PATH.exists():
        return False
    try:
        data = json.loads(LAST_SUGGESTION_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    previous = str(data.get("loadout_fingerprint") or "").strip()
    if not previous or previous == current:
        return False
    try:
        LAST_SUGGESTION_PATH.unlink()
    except OSError:
        return False
    return True


def stale_suggestion_warning_for_board(board: Board) -> str | None:
    return stale_suggestion_warning(board_fingerprint(board))


def format_suggestion_word(result: WordResult) -> str:
    """Human-readable suggestion: scoring pattern → dictionary word when they differ."""
    if result.dictionary_word and result.dictionary_word.lower() != result.word.lower():
        return f"{result.word} → {result.dictionary_word}"
    return result.word


def format_result_score_display(
    result: WordResult,
    loadout: Loadout | None = None,
) -> str:
    """Score line for terminal/overlay; includes Capybara min–max when present."""
    from cursed_words_solver.rules.quest_scoring import display_score_for_quest

    cap = (result.breakdown or {}).get("capybara")
    score = int(display_score_for_quest(float(result.score), loadout))
    if cap and float(cap.get("max", result.score)) > float(cap.get("min", result.score)):
        cap_min = int(display_score_for_quest(float(cap["min"]), loadout))
        cap_max = int(display_score_for_quest(float(cap["max"]), loadout))
        return f"{score:,} pts ({cap_min:,}–{cap_max:,})"
    return f"{score:,} pts"


def _fixed_letters_align(scoring_word: str, candidate: str) -> bool:
    """True when every alphabetic char in scoring_word matches the candidate."""
    if len(scoring_word) != len(candidate):
        return False
    for a, b in zip(scoring_word, candidate, strict=True):
        if a.isalpha() and a.lower() != b.lower():
            return False
    return True


def _alignment_pattern_for_path(
    board: Board,
    path: list[int],
    flags: SearchFlagsMask,
) -> str:
    """Wildcard pattern for dictionary resolve (face letters fixed; true wildcards '?')."""
    parts: list[str] = []
    char_pos = 0
    for idx in path:
        tile = board.get_by_index(idx)
        token = resolve_letter(tile, char_pos, flags=flags)
        if token == "?":
            parts.append("?")
        elif token == "qu":
            parts.append("?")
        elif len(token) == 1 and token.isalpha():
            parts.append(token.lower())
        else:
            parts.append("?")
        char_pos += 2 if token == "qu" else max(1, len(token))
    return "".join(parts)


def dictionary_word_length_for_path(
    board: Board, path: list[int], scoring_word: str
) -> int:
    """Dictionary word length for this path (one letter per tile on number boards)."""
    from cursed_words_solver.rules.scoring_conditions import is_number_like_tile

    word = scoring_word.lower()
    if len(path) > 1 and any(
        is_number_like_tile(board.get_by_index(i)) for i in path
    ):
        if not word.isalpha() or len(word) != len(path):
            return len(path)
    return len(word)


def _candidate_aligns_scoring_word(
    scoring_word: str, candidate: str, *, word_len: int
) -> bool:
    """True when candidate length matches resolve length and fixed letters align."""
    if len(candidate) != word_len:
        return False
    if len(scoring_word) == word_len:
        return _fixed_letters_align(scoring_word, candidate)
    if scoring_word.isdigit():
        return True
    return False


def path_needs_dictionary_resolve(
    board: Board, path: list[int], search_word: str
) -> bool:
    """True when search_word must be resolved to a dictionary spelling for scoring."""
    from cursed_words_solver.rules.scoring_conditions import is_number_like_tile

    if "?" in search_word:
        return True
    has_number = False
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.ITEM or tile.curse in CHESS_CURSES:
            return True
        if is_number_like_tile(tile):
            has_number = True
    if not has_number:
        return False
    word = search_word.lower()
    if len(word) != len(path):
        return True
    if len(path) > 1 and not word.isalpha():
        return True
    return False


def path_tiles_need_dictionary_resolve(
    board: Board,
    path: list[int],
    *,
    flags: SearchFlagsMask = 0,
) -> bool:
    """True when path tiles require dictionary-resolve search (chess, fraction, etc.)."""
    search_word = search_word_from_path(board, path, flags=flags)
    return path_needs_dictionary_resolve(board, path, search_word)


def path_requires_tile_dictionary_resolve(
    board: Board,
    path: list[int],
    *,
    flags: SearchFlagsMask = 0,
) -> bool:
    """True when tile types on the path need dictionary spelling resolve (not plain wildcards)."""
    from cursed_words_solver.search import resolve_letter, resolve_letter_options

    char_pos = 0
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.ITEM or tile.curse in CHESS_CURSES:
            return True
        if tile.curse == CurseType.FRACTION:
            return True
        options = resolve_letter_options(tile, char_pos, flags=flags)
        alpha_opts = [o for o in options if len(o) == 1 and o.isalpha()]
        if len(alpha_opts) > 1:
            return True
        token = resolve_letter(tile, char_pos, flags=flags)
        char_pos += 2 if token == "qu" else max(1, len(token))
    return False


def _validator_for_loadout(
    dictionary: WordDictionary,
    loadout: Loadout,
    *,
    min_len: int = 3,
) -> PathValidator:
    validator = PathValidator(dictionary, min_len=min_len)
    validator.quest_loadout = loadout
    return validator


def _physical_letter_overlap(board: Board, path: list[int], candidate: str) -> int:
    """Count positions where candidate matches the tile's physical letter."""
    score = 0
    for i, idx in enumerate(path):
        if i >= len(candidate):
            break
        tile = board.get_by_index(idx)
        ph = (tile.letter or tile.char or "").strip().lower()
        if len(ph) == 1 and ph.isalpha() and ph == candidate[i]:
            score += 1
    return score


def _pick_best_dictionary_word(
    board: Board,
    path: list[int],
    valid: list[str],
    loadout: Loadout,
    *,
    pipeline: ScoringPipeline | None = None,
) -> str:
    """Choose best dictionary spelling from assignable candidates on this path."""
    pool = valid
    if pipeline is not None and loadout is not None:
        if len(pool) > 64:
            pool = sorted(
                pool,
                key=lambda c: -_physical_letter_overlap(board, path, c),
            )[:64]

        scored = [
            (c, pipeline.score_total_only(board, path, c, loadout)) for c in pool
        ]
        best_score = max(sc for _, sc in scored)
        top = [c for c, sc in scored if sc >= best_score - 1e-6]
        myrrh_family = [c for c in top if "myrrh" in c]
        pick_from = myrrh_family or top
        return max(
            pick_from,
            key=lambda c: (_physical_letter_overlap(board, path, c), c),
        )

    return max(pool, key=lambda c: (_physical_letter_overlap(board, path, c), c))


def dictionary_word_for_path(

    board: Board,

    path: list[int],

    scoring_word: str,

    loadout: Loadout,

    dictionary: WordDictionary,

    *,

    min_len: int = 3,

    pipeline: ScoringPipeline | None = None,

) -> str | None:

    """Best-effort dictionary spelling the game accepts on this path (vs scoring form)."""

    word = scoring_word.lower()

    flags = stamp_search_flags(loadout)

    validator = _validator_for_loadout(dictionary, loadout, min_len=min_len)

    if word.isalpha() and validator.word_ok(board, path, word, flags):

        return word

    if validator.word_ok(board, path, word, flags) and not path_requires_tile_dictionary_resolve(
        board, path, flags=flags
    ):
        return word



    pattern = _alignment_pattern_for_path(board, path, flags)
    word_len = len(pattern)

    valid: list[str] = []

    for candidate in dictionary.words_of_length(word_len):
        if not _fixed_letters_align(pattern, candidate):
            continue
        if not word_assignable_on_path(board, path, candidate, flags=flags):
            continue
        if not validator.word_ok(board, path, candidate, flags):
            continue
        valid.append(candidate)

    if not valid:

        return None

    return _pick_best_dictionary_word(
        board, path, valid, loadout, pipeline=pipeline
    )


def loadout_needs_encounter_historic(loadout: Loadout | None, board: Board | None) -> bool:
    """True when scoring rules need encounter historic_words (not just red_tiles fallback)."""
    if loadout is not None:
        for sticker in loadout.stickers:
            if (sticker.id or "").lower() == "movie_camera":
                return True
    if board is not None:
        for tile in board.flat:
            if tile is None:
                continue
            scattered = (tile.metadata or {}).get("scattered_item_id")
            if scattered == "telescope":
                return True
    return False


_PREVIOUS_WORD_LETTER_STAMPS = frozenset({"bento_box", "bento", "chips", "limnophila"})


def loadout_needs_previous_word_letter(loadout: Loadout | None) -> bool:
    """True when Bento/Chips/Limnophila can apply previous_word_first_letter this grid."""
    if loadout is None:
        return False
    from cursed_words_solver.rules.scoring_conditions import (
        _limnophila_previous_word_available,
        grid_number,
    )

    if grid_number(loadout) < 2:
        return False

    has_stamp = False
    for item in (*(loadout.stamps or []), *(loadout.stickers or [])):
        if (item.id or "").lower() in _PREVIOUS_WORD_LETTER_STAMPS:
            has_stamp = True
            break
    if not has_stamp:
        return False

    if _limnophila_previous_word_available(loadout):
        return True

    prev = str((loadout.extras or {}).get("previous_word_first_letter", "") or "").strip()
    return bool(prev)


def _loadout_has_bento_box(loadout: Loadout | None) -> bool:
    if loadout is None:
        return False
    for item in (*(loadout.stamps or []), *(loadout.stickers or [])):
        if (item.id or "").lower() in ("bento_box", "bento"):
            return True
    return False


def f8_should_block_save(
    *,
    historic_catchup_stale_note: str | None = None,
    empty_hist_warn: str | None = None,
    hist_stale_note: str | None = None,
    behind_disk_warn: str | None = None,
    workflow_stale_warn: str | None = None,
    grid_adv_warn: str | None = None,
    grid_bleed_warn: str | None = None,
    grid_one_hist_warn: str | None = None,
    loadout: Loadout | None = None,
    board: Board | None = None,
    f8_extras: dict[str, Any] | None = None,
    submit_projected_extras: dict[str, Any] | None = None,
    gather_succeeded: bool = True,
    gather_missing: list[str] | None = None,
    mid_solve_grid_advanced: bool = False,
    path: list[int] | None = None,
    dictionary: WordDictionary | None = None,
    scoring_word: str | None = None,
) -> tuple[bool, str | None]:
    """Whether F8 must skip trusted last_suggestion.json (melmod capture)."""
    del grid_adv_warn, grid_one_hist_warn
    if grid_bleed_warn:
        return True, "workflow_bleed"
    if not gather_succeeded:
        from cursed_words_solver.f8_messages import gather_block_reason

        return True, gather_block_reason(gather_missing)
    if mid_solve_grid_advanced:
        return True, "grid_advanced_during_solve"
    if f8_path_uses_crossed_out_tiles(board, path):
        return True, "crossed_out_tile_in_path"
    if f8_path_missing_up_and_up_center(board, path, loadout):
        return True, "up_and_up_center_not_in_path"
    if _loadout_has_bento_box(loadout) and loadout_needs_previous_word_letter(loadout):
        extras = (loadout.extras or {}) if loadout is not None else {}
        from cursed_words_solver.loadout import f8_historic_stale_after_merge_warning

        if hist_stale_note or f8_historic_stale_after_merge_warning(extras):
            return True, "bento_previous_word_stale"
        if workflow_stale_warn and "previous word letter" in workflow_stale_warn.lower():
            return True, "bento_previous_word_stale"
        if isinstance(f8_extras, dict):
            drift = workflow_stale_vs_f8_snapshot(extras, f8_extras)
            if drift and "previous word letter" in drift:
                return True, "bento_previous_word_stale"
    if empty_hist_warn and loadout is not None and loadout_needs_encounter_historic(
        loadout, board
    ):
        return True, "empty_historic_on_later_grid"
    if historic_catchup_stale_note:
        return True, "historic_catchup_stale"
    if behind_disk_warn:
        return True, "behind_disk"
    if isinstance(f8_extras, dict) and isinstance(submit_projected_extras, dict):
        if f8_historic_would_fail_submit_projection(
            f8_extras,
            board=board,
            projected_extras=submit_projected_extras,
        ):
            return True, "submit_projection_mismatch"
    if (
        dictionary is not None
        and board is not None
        and loadout is not None
        and path
        and scoring_word
        and not path_is_submittable(
            board,
            list(path),
            scoring_word,
            loadout,
            dictionary,
        )
    ):
        return True, "no_playable_dictionary_word"
    return False, None


def f8_path_missing_up_and_up_center(
    board: Board | None,
    path: list[int] | None,
    loadout: Loadout | None,
) -> bool:
    """True when Up and Up is active but the path omits the required center tile."""
    if board is None or not path or loadout is None:
        return False
    from cursed_words_solver.rules.quest_effects import quest_constraints, quest_path_allowed

    center_idx = quest_constraints(loadout).require_center_index
    if center_idx is None:
        return False
    try:
        return not quest_path_allowed(board, list(path), loadout=loadout)
    except (IndexError, ValueError):
        return True


def f8_path_uses_crossed_out_tiles(
    board: Board | None,
    path: list[int] | None,
) -> bool:
    """True when the suggested path includes an on-cooldown (crossed-out) tile."""
    if board is None or not path:
        return False
    from cursed_words_solver.rules.quest_effects import path_uses_crossed_out_tile

    try:
        return path_uses_crossed_out_tile(board, list(path))
    except (IndexError, ValueError):
        return False


def _trace_word_for_path(
    board: Board,
    path: list[int],
    *,
    flags: int = 0,
) -> str:
    """Word from tile face chars as resolved when tracing the path in-game."""
    parts: list[str] = []
    char_pos = 0
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.ITEM:
            ch = (tile.letter or tile.char or "?").strip().lower()[:1]
            parts.append(ch if ch.isalpha() else "?")
            char_pos += 1
        elif tile.curse in CHESS_CURSES:
            ch = (tile.char or "").strip().lower()
            parts.append(ch if len(ch) == 1 and ch.isalpha() else "?")
        else:
            token = resolve_letter(tile, char_pos, flags=flags).lower()
            parts.append(token)
            char_pos += len(token)
    return "".join(parts)


def _valid_dictionary_words_for_path(
    board: Board,
    path: list[int],
    scoring_word: str,
    loadout: Loadout,
    dictionary: WordDictionary,
    *,
    min_len: int = 3,
    limit: int | None = None,
) -> list[str]:
    flags = stamp_search_flags(loadout)
    validator = _validator_for_loadout(dictionary, loadout, min_len=min_len)
    pattern = _alignment_pattern_for_path(board, path, flags)
    word_len = len(pattern)
    if word_len < min_len:
        return []
    valid: list[str] = []
    for candidate in dictionary.words_of_length(word_len):
        if not _fixed_letters_align(pattern, candidate):
            continue
        if not word_assignable_on_path(board, path, candidate, flags=flags):
            continue
        if not validator.word_ok(board, path, candidate, flags):
            continue
        valid.append(candidate)
        if limit is not None and len(valid) >= limit:
            break
    return valid


def path_is_submittable(
    board: Board,
    path: list[int],
    scoring_word: str,
    loadout: Loadout,
    dictionary: WordDictionary,
    *,
    min_len: int = 3,
    pipeline: ScoringPipeline | None = None,
) -> bool:
    """True when the game accepts a dictionary word on this path."""
    lowered = scoring_word.lower()
    if "?" in lowered:
        return bool(
            _valid_dictionary_words_for_path(
                board,
                path,
                lowered,
                loadout,
                dictionary,
                min_len=min_len,
                limit=1,
            )
        )
    flags = stamp_search_flags(loadout)
    validator = _validator_for_loadout(dictionary, loadout, min_len=min_len)
    if validator.word_ok(board, path, lowered, flags):
        return True
    resolved = dictionary_word_for_path(
        board,
        path,
        lowered,
        loadout,
        dictionary,
        min_len=min_len,
        pipeline=pipeline,
    )
    return resolved is not None and resolved.isalpha()


def filter_submittable_results(
    board: Board,
    results: list[WordResult],
    loadout: Loadout,
    dictionary: WordDictionary | None,
    *,
    min_len: int = 3,
    pipeline: ScoringPipeline | None = None,
) -> list[WordResult]:
    """Drop search hits the game cannot submit as a dictionary word."""
    if not results or dictionary is None:
        return results
    return [
        r
        for r in results
        if path_is_submittable(
            board,
            r.path,
            r.word,
            loadout,
            dictionary,
            min_len=min_len,
            pipeline=pipeline,
        )
    ]


def game_word_for_path(
    board: Board,
    path: list[int],
    scoring_word: str,
    loadout: Loadout,
    dictionary: WordDictionary | None,
    *,
    min_len: int = 3,
    pipeline: ScoringPipeline | None = None,
) -> str:
    """Dictionary word the game submits when tracing this path (not max-score search pick)."""
    lowered = scoring_word.lower()
    if dictionary is None:
        return lowered
    flags = stamp_search_flags(loadout)
    validator = _validator_for_loadout(dictionary, loadout, min_len=min_len)
    if lowered.isalpha() and validator.word_ok(board, path, lowered, flags):
        return lowered

    trace = _trace_word_for_path(board, path, flags=flags)
    if trace.isalpha() and validator.word_ok(board, path, trace, flags):
        return trace

    resolved = dictionary_word_for_path(
        board,
        path,
        lowered,
        loadout,
        dictionary,
        min_len=min_len,
        pipeline=pipeline,
    )
    return resolved if resolved else lowered


def effective_scoring_word(
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    dictionary: WordDictionary | None,
    *,
    min_len: int = 3,
    pipeline: ScoringPipeline | None = None,
) -> str:
    """Spelling used for scoring: game-submit word on this path."""
    lowered = word.lower()
    if dictionary is None:
        return lowered
    return game_word_for_path(
        board,
        path,
        lowered,
        loadout,
        dictionary,
        min_len=min_len,
        pipeline=pipeline,
    )




def save_last_suggestion(

    *,

    board: Board,

    loadout: Loadout,

    result: WordResult,

    predicted_trace: list[dict[str, Any]],

    run_state_snapshot: dict[str, Any] | None = None,

    dictionary: WordDictionary | None = None,
    min_len: int = 3,
    scoring_word: str | None = None,
    export_diagnostics: dict[str, Any] | None = None,
    export_warnings: list[str] | None = None,
    workflow_warnings: list[str] | None = None,
    gather_status: dict[str, Any] | None = None,
    solver_session_extras: dict[str, Any] | None = None,
    consumable_placements: list[Any] | None = None,
    twinkle_toes_swap: TwinkleToesSwap | None = None,
    score_nondeterministic: bool = False,
    predicted_score_min: int | None = None,
    predicted_score_max: int | None = None,
    capybara_perm_count: int | None = None,
    capybara_exhaustive: bool | None = None,

) -> None:

    """Write last_suggestion.json for the companion mod after F8 solve."""

    LAST_SUGGESTION_PATH.parent.mkdir(parents=True, exist_ok=True)

    board_fp = ""

    loadout_fp = ""

    if run_state_snapshot is not None:

        board_fp, loadout_fp = fingerprints_from_run_state(run_state_snapshot)



    if scoring_word is None:
        scoring_word = result.word
        phys_word = physical_word_for_path(
            board, result.path, flags=stamp_search_flags(loadout)
        )
        if phys_word != scoring_word.lower():
            scoring_word = phys_word

    dict_word: str | None = None

    if dictionary is not None:

        dict_word = dictionary_word_for_path(

            board,
            result.path,
            scoring_word,
            loadout,
            dictionary,
            min_len=max(1, int(min_len)),

        )



    f8_sequence = _next_f8_sequence()

    from cursed_words_solver.rules.quest_scoring import display_score_for_quest

    raw_score = int(result.score)
    display_score = int(display_score_for_quest(float(result.score), loadout))

    payload: dict[str, Any] = {

        "created_at": datetime.now(timezone.utc).isoformat(),

        "f8_sequence": f8_sequence,

        "solver_version": SOLVER_VERSION,

        "word": scoring_word,

        "scoring_word": scoring_word,

        "path": list(path_to_melmod_indices(board, result.path)),

        "predicted_score": display_score,

        "predicted_score_raw": raw_score,

        "board_fingerprint": board_fp,

        "loadout_fingerprint": loadout_fp,

        "predicted_trace": predicted_trace,

    }

    if dict_word and dict_word != scoring_word.lower():

        payload["dictionary_word"] = dict_word

    if run_state_snapshot is not None:

        payload["run_state_snapshot"] = run_state_snapshot

    if export_diagnostics:
        payload["export_diagnostics"] = export_diagnostics

    if export_warnings:
        payload["export_warnings"] = list(export_warnings)

    if workflow_warnings:
        payload["workflow_warnings"] = list(workflow_warnings)

    if gather_status:
        payload["gather_status"] = dict(gather_status)

    if solver_session_extras:
        payload["solver_session_extras"] = dict(solver_session_extras)

    if consumable_placements:
        payload["consumable_placements"] = [
            {
                "row": p.row,
                "col": p.col,
                "index": p.index,
                "letter": p.letter,
                "rack_index": p.rack_index,
            }
            for p in consumable_placements
        ]

    if twinkle_toes_swap is not None:
        payload["twinkle_toes_swap"] = {
            "row_a": twinkle_toes_swap.row_a,
            "col_a": twinkle_toes_swap.col_a,
            "row_b": twinkle_toes_swap.row_b,
            "col_b": twinkle_toes_swap.col_b,
        }

    ms_hint = (result.breakdown or {}).get("microscope_hint")
    if ms_hint:
        payload["microscope_hint"] = ms_hint
    ms_positions = (result.breakdown or {}).get("microscope_positions")
    if ms_positions:
        payload["microscope_positions"] = ms_positions

    if score_nondeterministic:
        payload["score_nondeterministic"] = True
        if predicted_score_min is not None:
            payload["predicted_score_min"] = int(
                display_score_for_quest(float(predicted_score_min), loadout)
            )
            payload["predicted_score_min_raw"] = int(predicted_score_min)
        if predicted_score_max is not None:
            payload["predicted_score_max"] = int(
                display_score_for_quest(float(predicted_score_max), loadout)
            )
            payload["predicted_score_max_raw"] = int(predicted_score_max)
        if capybara_perm_count is not None:
            payload["capybara_perm_count"] = int(capybara_perm_count)
        if capybara_exhaustive is not None:
            payload["capybara_exhaustive"] = bool(capybara_exhaustive)

    if LAST_SUGGESTION_BLOCKED_PATH.exists():
        try:
            LAST_SUGGESTION_BLOCKED_PATH.unlink()
        except OSError:
            pass

    LAST_SUGGESTION_PATH.write_text(

        json.dumps(payload, indent=2),

        encoding="utf-8",

    )


def save_blocked_suggestion(
    *,
    board: Board,
    loadout: Loadout,
    result: WordResult,
    predicted_trace: list[dict[str, Any]] | None,
    run_state_snapshot: dict[str, Any] | None,
    scoring_word: str,
    block_reason: str,
    export_diagnostics: dict[str, Any] | None = None,
    consumable_placements: list[Any] | None = None,
    twinkle_toes_swap: TwinkleToesSwap | None = None,
) -> None:
    """Write diagnostic sidecar when F8 ran but trusted capture was blocked."""
    LAST_SUGGESTION_BLOCKED_PATH.parent.mkdir(parents=True, exist_ok=True)
    board_fp = ""
    loadout_fp = ""
    if run_state_snapshot is not None:
        board_fp, loadout_fp = fingerprints_from_run_state(run_state_snapshot)
    f8_sequence = _next_f8_sequence()
    from cursed_words_solver.rules.quest_scoring import display_score_for_quest

    payload: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "f8_sequence": f8_sequence,
        "solver_version": SOLVER_VERSION,
        "capture_blocked": True,
        "block_reason": block_reason,
        "word": scoring_word,
        "scoring_word": scoring_word,
        "path": list(result.path),
        "predicted_score": int(
            display_score_for_quest(float(result.score), loadout)
        ),
        "predicted_score_raw": int(result.score),
        "board_fingerprint": board_fp,
        "loadout_fingerprint": loadout_fp,
        "predicted_trace": predicted_trace,
    }
    if run_state_snapshot is not None:
        payload["run_state_snapshot"] = run_state_snapshot
    if export_diagnostics:
        payload["export_diagnostics"] = export_diagnostics
    if consumable_placements:
        payload["consumable_placements"] = [
            {
                "row": p.row,
                "col": p.col,
                "index": p.index,
                "letter": p.letter,
                "rack_index": p.rack_index,
            }
            for p in consumable_placements
        ]
    if twinkle_toes_swap is not None:
        payload["twinkle_toes_swap"] = {
            "row_a": twinkle_toes_swap.row_a,
            "col_a": twinkle_toes_swap.col_a,
            "row_b": twinkle_toes_swap.row_b,
            "col_b": twinkle_toes_swap.col_b,
        }
    if LAST_SUGGESTION_PATH.exists():
        try:
            LAST_SUGGESTION_PATH.unlink()
        except OSError:
            pass
    LAST_SUGGESTION_BLOCKED_PATH.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _next_f8_sequence() -> int:
    """Monotonic F8 counter for correlating with round_logs."""
    LAST_SUGGESTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    seq = 0
    if _F8_SEQUENCE_PATH.exists():
        try:
            seq = int(_F8_SEQUENCE_PATH.read_text(encoding="utf-8").strip())
        except (TypeError, ValueError):
            seq = 0
    seq += 1
    _F8_SEQUENCE_PATH.write_text(str(seq), encoding="utf-8")
    return seq


