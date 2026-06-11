"""Gather live melmod run_state for a single F8 solve (game-as-source-of-truth)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from cursed_words_solver.consumable_placement import (
    has_exported_consumable_rack,
    rack_requires_export,
    wait_for_rack_export,
)
from cursed_words_solver.fingerprints import (
    board_tiles_fingerprint_suffix,
    fingerprints_from_run_state,
)
from cursed_words_solver.loadout import (
    hydrate_tile_ninja_loadout_extras,
    load_run_state_raw,
    melmod_board_available,
    merge_encounter_historic_for_f8_with_retry,
    merge_loadout_with_board,
    mod_money_from_run_state,
    parse_board_from_run_state,
    parse_run_state,
    project_previous_word_first_letter_from_round_log,
    validate_run_state_for_scoring,
)
from cursed_words_solver.round_log import last_submit_effective_first_letter
from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.scoring_conditions import (
    consumable_rack_count,
    grid_number,
)
from cursed_words_solver.suggestion import (
    loadout_needs_encounter_historic,
    loadout_needs_previous_word_letter,
)

F8_GATHER_POLL_SEC = 0.1
F8_GATHER_BOARD_TIMEOUT_SEC = 5.0
F8_GATHER_EXTRAS_TIMEOUT_SEC = 5.0
F8_RACK_EXPORT_TIMEOUT_SEC = 5.0


@dataclass(frozen=True)
class F8SuggestionSession:
    """Active F8 suggestion until word submit or real grid/loadout change."""

    board_fingerprint: str
    loadout_fingerprint: str
    board_tiles_fingerprint: str
    grid_number: int = 0


@dataclass
class F8Snapshot:
    """Game export gathered for one F8 press."""

    run_state: dict[str, Any] | None
    board: Board | None
    loadout: Loadout | None
    warnings: list[str] = field(default_factory=list)
    board_available: bool = False
    extras_ready: bool = False


def _has_neapolitan_stamp(loadout: Loadout) -> bool:
    return any(
        str(getattr(stamp, "id", "") or "").strip().lower() == "neapolitan"
        for stamp in (loadout.stamps or [])
    )


def _has_steak_stamp(loadout: Loadout) -> bool:
    return any(
        str(getattr(stamp, "id", "") or "").strip().lower() == "steak"
        for stamp in (loadout.stamps or [])
    )


def _has_tile_ninja_stamp(loadout: Loadout) -> bool:
    return any(
        str(getattr(stamp, "id", "") or "").strip().lower() == "tile_ninja"
        for stamp in (loadout.stamps or [])
    )


def _extras_missing_for_loadout(
    loadout: Loadout,
    board: Board,
    extras: dict[str, Any],
) -> list[str]:
    """Fields melmod should export before solve; empty when satisfied."""
    missing: list[str] = []
    if loadout_needs_previous_word_letter(loadout):
        prev = str(extras.get("previous_word_first_letter", "") or "").strip()
        if not prev:
            missing.append("previous_word_first_letter")
    if loadout_needs_encounter_historic(loadout, board):
        hist = str(extras.get("historic_words", "") or "").strip()
        if not hist or hist == "[]":
            missing.append("historic_words")
    if _has_neapolitan_stamp(loadout):
        if extras.get("neapolitan_percent") in (None, ""):
            missing.append("neapolitan_percent")
    if _has_steak_stamp(loadout):
        has_pct = extras.get("steak_word_bonus_percent") not in (None, "")
        has_rare = extras.get("rare_item_count") not in (None, "")
        if not has_pct and not has_rare:
            missing.append("steak_word_bonus_percent/rare_item_count")
    if consumable_rack_count(loadout) > 0 and not has_exported_consumable_rack(loadout):
        missing.append("consumable_rack")
    if _has_tile_ninja_stamp(loadout):
        if extras.get("tile_ninja_consumables_used") in (None, ""):
            missing.append("tile_ninja_consumables_used")
    return missing


def _workflow_prev_letter_catchup_note(
    loadout: Loadout | None,
    extras: dict[str, Any],
) -> str | None:
    """Human-readable lag when run_state prev letter trails last round-log submit."""
    if loadout is None or not loadout_needs_previous_word_letter(loadout):
        return None
    expected = last_submit_effective_first_letter()
    if not expected:
        return None
    cur = str(extras.get("previous_word_first_letter", "") or "").strip().lower()[:1]
    if not cur:
        return f"previous_word_first_letter (expect {expected}, got empty)"
    if cur != expected.lower()[:1]:
        return f"previous_word_first_letter (expect {expected}, got {cur})"
    return None


def _apply_historic_merge_to_run_state(
    run_state: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Merge encounter historic from disk; return merged state and optional stale note."""
    if not isinstance(run_state, dict):
        return run_state, None
    merged, stale_note = merge_encounter_historic_for_f8_with_retry(run_state)
    return merged if merged is not None else run_state, stale_note


def _build_snapshot_from_run_state(
    run_state: dict[str, Any] | None,
    *,
    rules: dict[str, Any] | None = None,
) -> F8Snapshot:
    if not isinstance(run_state, dict):
        return F8Snapshot(run_state=None, board=None, loadout=None)

    run_state = project_previous_word_first_letter_from_round_log(run_state)

    board = parse_board_from_run_state(run_state)
    if board is None:
        return F8Snapshot(run_state=run_state, board=None, loadout=None)

    mod_money = mod_money_from_run_state(run_state)
    loadout = merge_loadout_with_board(
        parse_run_state(run_state),
        board.money,
        mod_money=mod_money if mod_money > 0 else None,
    )
    loadout = hydrate_tile_ninja_loadout_extras(loadout, run_state)
    warnings = validate_run_state_for_scoring(
        loadout,
        board=board,
        raw=run_state,
    )
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    missing = _extras_missing_for_loadout(loadout, board, extras)
    if missing and rules is not None and rack_requires_export(loadout, board, rules):
        if "consumable_rack" not in missing:
            missing.append("consumable_rack")

    extras_ready = not missing
    if missing:
        warnings = list(warnings) + [
            f"waiting for melmod export: {', '.join(missing)}"
        ]

    return F8Snapshot(
        run_state=run_state,
        board=board,
        loadout=loadout,
        warnings=warnings,
        board_available=True,
        extras_ready=extras_ready,
    )


def gather_f8_snapshot(
    *,
    rules: dict[str, Any] | None = None,
    board_timeout_sec: float = F8_GATHER_BOARD_TIMEOUT_SEC,
    extras_timeout_sec: float = F8_GATHER_EXTRAS_TIMEOUT_SEC,
    poll_sec: float = F8_GATHER_POLL_SEC,
    on_wait: Callable[[str], None] | None = None,
) -> F8Snapshot:
    """Poll melmod run_state until board and required extras are exported."""
    deadline_board = time.monotonic() + max(0.0, board_timeout_sec)
    run_state: dict[str, Any] | None = None

    while time.monotonic() < deadline_board:
        run_state = load_run_state_raw()
        if melmod_board_available(run_state):
            break
        time.sleep(poll_sec)
    else:
        run_state = load_run_state_raw()

    snapshot = _build_snapshot_from_run_state(run_state, rules=rules)
    if not snapshot.board_available:
        return snapshot

    logged_wait: set[str] = set()

    def _notify_wait(msg: str) -> None:
        if on_wait and msg not in logged_wait:
            logged_wait.add(msg)
            on_wait(msg)

    deadline_extras = time.monotonic() + max(0.0, extras_timeout_sec)
    last_missing: list[str] = []
    while time.monotonic() < deadline_extras:
        run_state = load_run_state_raw()
        snapshot = _build_snapshot_from_run_state(run_state, rules=rules)
        if snapshot.extras_ready:
            break
        extras = snapshot.loadout.extras if snapshot.loadout else {}
        last_missing = _extras_missing_for_loadout(
            snapshot.loadout, snapshot.board, extras or {}
        )
        if last_missing:
            _notify_wait(f"waiting for melmod: {', '.join(last_missing)}")
        time.sleep(poll_sec)

    if isinstance(run_state, dict):
        run_state, historic_stale = _apply_historic_merge_to_run_state(run_state)
        run_state = project_previous_word_first_letter_from_round_log(run_state)
        snapshot = _build_snapshot_from_run_state(run_state, rules=rules)
        if historic_stale:
            snapshot.warnings = list(snapshot.warnings) + [historic_stale]

    deadline_workflow = time.monotonic() + max(0.0, extras_timeout_sec)
    last_workflow_note: str | None = None
    while time.monotonic() < deadline_workflow:
        if snapshot.loadout is None:
            break
        extras = snapshot.loadout.extras if isinstance(snapshot.loadout.extras, dict) else {}
        workflow_note = _workflow_prev_letter_catchup_note(snapshot.loadout, extras or {})
        if workflow_note is None:
            break
        last_workflow_note = workflow_note
        _notify_wait(f"waiting for melmod: {workflow_note}")
        time.sleep(poll_sec)
        run_state = load_run_state_raw()
        if isinstance(run_state, dict):
            run_state, _ = _apply_historic_merge_to_run_state(run_state)
            run_state = project_previous_word_first_letter_from_round_log(run_state)
        snapshot = _build_snapshot_from_run_state(run_state, rules=rules)

    if snapshot.loadout is not None:
        extras = snapshot.loadout.extras if isinstance(snapshot.loadout.extras, dict) else {}
        if _workflow_prev_letter_catchup_note(snapshot.loadout, extras or {}):
            if isinstance(run_state, dict):
                run_state = project_previous_word_first_letter_from_round_log(run_state)
                snapshot = _build_snapshot_from_run_state(run_state, rules=rules)
                extras = (
                    snapshot.loadout.extras
                    if snapshot.loadout and isinstance(snapshot.loadout.extras, dict)
                    else {}
                )
            if _workflow_prev_letter_catchup_note(snapshot.loadout, extras or {}):
                snapshot.warnings = list(snapshot.warnings) + [
                    "melmod workflow export incomplete after wait: "
                    + (last_workflow_note or "previous_word_first_letter")
                ]
                snapshot.extras_ready = False
            else:
                snapshot.warnings = list(snapshot.warnings) + [
                    "projected previous_word_first_letter from round log (melmod lag)"
                ]

    if snapshot.loadout is not None and snapshot.board is not None and rules is not None:
        def _reload() -> Loadout | None:
            fresh = load_run_state_raw()
            if not isinstance(fresh, dict):
                return snapshot.loadout
            b = parse_board_from_run_state(fresh)
            if b is None:
                return snapshot.loadout
            money = mod_money_from_run_state(fresh)
            return merge_loadout_with_board(
                parse_run_state(fresh),
                b.money,
                mod_money=money if money > 0 else None,
            )

        updated_loadout = wait_for_rack_export(
            snapshot.loadout,
            snapshot.board,
            rules,
            reload_loadout=_reload,
            timeout_sec=F8_RACK_EXPORT_TIMEOUT_SEC,
            poll_sec=poll_sec,
        )
        run_state = load_run_state_raw()
        snapshot = _build_snapshot_from_run_state(run_state, rules=rules)
        if snapshot.loadout is not None:
            snapshot.loadout = hydrate_tile_ninja_loadout_extras(
                updated_loadout, run_state
            )

    if last_missing and not snapshot.extras_ready:
        snapshot.warnings = list(snapshot.warnings) + [
            f"melmod export incomplete after wait: {', '.join(last_missing)}"
        ]

    return snapshot


def session_from_snapshot(snapshot: F8Snapshot) -> F8SuggestionSession | None:
    """Build active-session metadata from a gathered snapshot."""
    if snapshot.run_state is None or snapshot.board is None:
        return None
    board_fp, loadout_fp = fingerprints_from_run_state(snapshot.run_state)
    tiles_fp = board_tiles_fingerprint_suffix(board_fp)
    gn = 0
    if snapshot.loadout is not None:
        try:
            gn = grid_number(snapshot.loadout)
        except (TypeError, ValueError):
            gn = 0
    return F8SuggestionSession(
        board_fingerprint=board_fp,
        loadout_fingerprint=loadout_fp,
        board_tiles_fingerprint=tiles_fp,
        grid_number=gn,
    )


def embed_run_state_for_suggestion(run_state: dict[str, Any]) -> dict[str, Any]:
    """Copy of game export for last_suggestion.json (trim unequipped item extras only)."""
    from cursed_words_solver.loadout import (
        merge_tile_ninja_extras_into,
        sanitize_run_state_snapshot_for_f8,
    )

    loadout = parse_run_state(run_state)
    board = parse_board_from_run_state(run_state)
    mod_money = mod_money_from_run_state(run_state)
    if board is not None:
        loadout = merge_loadout_with_board(
            loadout,
            board.money,
            mod_money=mod_money if mod_money > 0 else None,
        )
    sanitized = sanitize_run_state_snapshot_for_f8(run_state, loadout)
    if not isinstance(sanitized, dict):
        return dict(run_state)
    fresh = load_run_state_raw()
    extras = sanitized.get("extras")
    if isinstance(fresh, dict) and isinstance(extras, dict):
        merge_tile_ninja_extras_into(extras, fresh)
    return sanitized
