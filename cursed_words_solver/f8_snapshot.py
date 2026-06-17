"""Gather live melmod run_state for a single F8 solve (game-as-source-of-truth)."""

from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from cursed_words_solver.config import CONFIG_DIR, F8_EXPORT_REQUEST_PATH

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
    _grid_number_from_extras,
    _scoring_previous_words_count_from_extras,
    encounter_mode_from_run_state,
    hydrate_tile_ninja_loadout_extras,
    load_run_state_raw,
    melmod_board_available,
    merge_f8_workflow_extras_into,
    merge_loadout_with_board,
    mod_money_from_run_state,
    parse_board_from_run_state,
    parse_run_state,
    sanitize_run_state_snapshot_for_f8,
    validate_run_state_for_scoring,
)
from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.scoring_conditions import (
    consumable_rack_count,
    grid_number,
)
from cursed_words_solver.rules.quest_effects import (
    active_quest_game_class,
    active_quest_slug,
    board_has_crossed_out_tile,
)
from cursed_words_solver.suggestion import (
    loadout_needs_encounter_historic,
    loadout_needs_previous_word_letter,
)

F8_GATHER_POLL_SEC = 0.1
F8_GATHER_BOARD_TIMEOUT_SEC = 5.0
F8_GATHER_EXTRAS_TIMEOUT_SEC = 5.0
F8_EXPORT_ACK_TIMEOUT_SEC = 5.0
F8_RACK_EXPORT_TIMEOUT_SEC = 5.0
F8_CROSSED_OUT_EXPORT_TIMEOUT_SEC = 5.0
F8_EXPORT_WRITE_RETRIES = 12
F8_EXPORT_WRITE_RETRY_DELAY_SEC = 0.04


@dataclass(frozen=True)
class F8SuggestionSession:
    """Active F8 suggestion until word submit or real grid/loadout change."""

    board_fingerprint: str
    loadout_fingerprint: str
    board_tiles_fingerprint: str
    grid_number: int = 0


def write_f8_export_request() -> str:
    """Ask melmod for a live game-memory export before gathering run_state."""
    request_id = str(int(time.time() * 1000))
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "request_id": request_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    content = json.dumps(payload, indent=2)
    tmp_path = F8_EXPORT_REQUEST_PATH.with_suffix(".json.tmp")
    last_error: OSError | None = None
    for attempt in range(max(1, F8_EXPORT_WRITE_RETRIES)):
        try:
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(tmp_path, F8_EXPORT_REQUEST_PATH)
            return request_id
        except OSError as exc:
            last_error = exc
            if attempt + 1 >= F8_EXPORT_WRITE_RETRIES:
                break
            time.sleep(F8_EXPORT_WRITE_RETRY_DELAY_SEC)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
    if last_error is not None:
        raise last_error
    raise OSError("failed to write F8 export request")


def _f8_export_acknowledged(
    run_state: dict[str, Any] | None,
    request_id: str,
) -> bool:
    if not isinstance(run_state, dict) or not request_id:
        return False
    diag = run_state.get("export_diagnostics")
    if not isinstance(diag, dict):
        return False
    ack = str(diag.get("f8_request_id") or "").strip()
    trigger = str(diag.get("export_trigger") or "").strip().lower()
    return ack == request_id and trigger == "f8"


def wait_for_f8_export_ack(
    request_id: str,
    *,
    timeout_sec: float = F8_EXPORT_ACK_TIMEOUT_SEC,
    poll_sec: float = F8_GATHER_POLL_SEC,
    on_wait: Callable[[str], None] | None = None,
) -> bool:
    """Poll run_state until melmod acknowledges the F8 export request."""
    deadline = time.monotonic() + max(0.0, timeout_sec)
    notified = False
    while time.monotonic() < deadline:
        run_state = load_run_state_raw()
        if _f8_export_acknowledged(run_state, request_id):
            return True
        if on_wait and not notified:
            notified = True
            on_wait("waiting for live game export from melmod")
        time.sleep(poll_sec)
    return _f8_export_acknowledged(load_run_state_raw(), request_id)


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


def _has_mutating_dna_stamp(loadout: Loadout) -> bool:
    return any(
        "mutating" in (stamp.id or "").lower() or "dna" in (stamp.id or "").lower()
        for stamp in (loadout.stamps or [])
    )


def _mutating_dna_counts_missing(extras: dict[str, Any]) -> bool:
    raw = str(extras.get("mutating_dna_letter_counts", "") or "").strip()
    return not raw or raw == "{}"


def _supply_and_demand_needs_crossed_out_flags(
    loadout: Loadout,
    board: Board | None,
    extras: dict[str, Any],
) -> bool:
    """True when On Cooldown should have crossed-out tiles but export has none."""
    if active_quest_game_class(loadout) != "SupplyAndDemand":
        return False
    try:
        grid_n = grid_number(loadout)
    except (TypeError, ValueError):
        grid_n = 0
    if grid_n < 2:
        return False
    if board is not None and board_has_crossed_out_tile(board):
        return False
    words_count = extras.get("words_submitted_this_run_count")
    if words_count not in (None, "", "0"):
        return True
    prev_words = extras.get("scoring_previous_words_count")
    try:
        if int(prev_words or 0) >= 1:
            return True
    except (TypeError, ValueError):
        pass
    return False


def _encounter_historic_export_ready(extras: dict[str, Any], hist: str) -> bool:
    """True when melmod exported encounter historic (empty is valid on grid 1)."""
    if hist and hist != "[]":
        return True
    source = str(extras.get("encounter_historic_source", "") or "").strip().lower()
    if source == "grid1_no_scoring_cache":
        return True
    return (
        _grid_number_from_extras(extras) == 1
        and _scoring_previous_words_count_from_extras(extras) == 0
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
    needs_historic = loadout_needs_encounter_historic(loadout, board)
    if (
        not needs_historic
        and _grid_number_from_extras(extras) >= 2
        and _scoring_previous_words_count_from_extras(extras) > 0
    ):
        needs_historic = True
    if needs_historic:
        hist = str(extras.get("historic_words", "") or "").strip()
        if not _encounter_historic_export_ready(extras, hist):
            missing.append("historic_words")
    if _has_neapolitan_stamp(loadout):
        if extras.get("neapolitan_percent") in (None, ""):
            missing.append("neapolitan_percent")
    if _has_steak_stamp(loadout):
        has_pct = extras.get("steak_word_bonus_percent") not in (None, "")
        has_rare = extras.get("rare_item_count") not in (None, "")
        if not has_pct and not has_rare:
            missing.append("steak_word_bonus_percent/rare_item_count")
    if _has_mutating_dna_stamp(loadout) and _mutating_dna_counts_missing(extras):
        missing.append("mutating_dna_letter_counts")
    if consumable_rack_count(loadout) > 0 and not has_exported_consumable_rack(loadout):
        missing.append("consumable_rack")
    if _has_tile_ninja_stamp(loadout):
        if extras.get("tile_ninja_consumables_used") in (None, ""):
            missing.append("tile_ninja_consumables_used")
    game_class = active_quest_game_class(loadout)
    if game_class == "UpAndUp":
        if extras.get("up_and_up_center_index") in (None, ""):
            missing.append("up_and_up_center_index")
        has_center = False
        if board is not None:
            for idx in range(25):
                if not board.is_active_index(idx):
                    continue
                if (board.get_by_index(idx).metadata or {}).get("is_up_and_up_center"):
                    has_center = True
                    break
        if not has_center:
            missing.append("is_up_and_up_center tile flag")
    if _supply_and_demand_needs_crossed_out_flags(loadout, board, extras):
        missing.append("is_crossed_out tile flags")
    if game_class == "PlayingFavourites":
        if not extras.get("favourite_sticker_ids"):
            missing.append("favourite_sticker_ids")
    slug = active_quest_slug(loadout)
    if slug in ("chromaphobia", "chromaphilia", "cursophobia") and not game_class:
        missing.append("challenge_game_class")
    return missing


def _shop_quest_extras_missing(loadout: Loadout, extras: dict[str, Any]) -> list[str]:
    """Shop-mode melmod fields required before shop advice."""
    missing: list[str] = []
    if active_quest_game_class(loadout) == "Embargo":
        if "embargoed_item_types" not in extras:
            missing.append("embargoed_item_types")
    return missing


def shop_extras_ready(run_state: dict[str, Any] | None) -> bool:
    """True when shop quest extras are present for F8 shop advice."""
    if not isinstance(run_state, dict):
        return False
    if encounter_mode_from_run_state(run_state) != "shop":
        return True
    loadout = parse_run_state(run_state)
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    return not _shop_quest_extras_missing(loadout, extras)


def _build_snapshot_from_run_state(
    run_state: dict[str, Any] | None,
    *,
    rules: dict[str, Any] | None = None,
) -> F8Snapshot:
    if not isinstance(run_state, dict):
        return F8Snapshot(run_state=None, board=None, loadout=None)

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
    if isinstance(loadout.extras, dict):
        from cursed_words_solver.loadout import reconcile_encounter_historic_for_scoring

        reconcile_encounter_historic_for_scoring(loadout.extras, board=board)
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
    f8_request_id: str | None = None,
    board_timeout_sec: float = F8_GATHER_BOARD_TIMEOUT_SEC,
    extras_timeout_sec: float = F8_GATHER_EXTRAS_TIMEOUT_SEC,
    poll_sec: float = F8_GATHER_POLL_SEC,
    on_wait: Callable[[str], None] | None = None,
) -> F8Snapshot:
    """Poll melmod run_state until board and required extras are exported."""
    if f8_request_id:
        acked = wait_for_f8_export_ack(
            f8_request_id,
            timeout_sec=min(board_timeout_sec, F8_EXPORT_ACK_TIMEOUT_SEC),
            poll_sec=poll_sec,
            on_wait=on_wait,
        )
        if not acked:
            # Retry request once in case melmod missed the first write.
            retry_id = write_f8_export_request()
            wait_for_f8_export_ack(
                retry_id,
                timeout_sec=F8_EXPORT_ACK_TIMEOUT_SEC,
                poll_sec=poll_sec,
                on_wait=on_wait,
            )

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

    if (
        snapshot.loadout is not None
        and snapshot.board is not None
        and _supply_and_demand_needs_crossed_out_flags(
            snapshot.loadout,
            snapshot.board,
            snapshot.loadout.extras if isinstance(snapshot.loadout.extras, dict) else {},
        )
    ):
        deadline_crossed = time.monotonic() + max(0.0, F8_CROSSED_OUT_EXPORT_TIMEOUT_SEC)
        while time.monotonic() < deadline_crossed:
            run_state = load_run_state_raw()
            snapshot = _build_snapshot_from_run_state(run_state, rules=rules)
            extras = (
                snapshot.loadout.extras
                if snapshot.loadout and isinstance(snapshot.loadout.extras, dict)
                else {}
            )
            if not _supply_and_demand_needs_crossed_out_flags(
                snapshot.loadout, snapshot.board, extras or {}
            ):
                break
            _notify_wait("waiting for melmod: is_crossed_out tile flags")
            time.sleep(poll_sec)
        else:
            snapshot.warnings = list(snapshot.warnings) + [
                "melmod export incomplete after wait: is_crossed_out tile flags"
            ]
            snapshot.extras_ready = False

    if isinstance(snapshot.run_state, dict):
        snapshot.run_state = copy.deepcopy(snapshot.run_state)

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


def embed_f8_snapshot(
    snapshot: F8Snapshot,
    *,
    scoring_loadout: Loadout | None = None,
) -> dict[str, Any] | None:
    """Embed for last_suggestion.json from the frozen F8 gather snapshot."""
    if not isinstance(snapshot.run_state, dict):
        return None

    loadout = scoring_loadout or snapshot.loadout
    if loadout is None:
        return copy.deepcopy(snapshot.run_state)

    run_state = copy.deepcopy(snapshot.run_state)
    sanitized = sanitize_run_state_snapshot_for_f8(run_state, loadout)
    if not isinstance(sanitized, dict):
        return copy.deepcopy(snapshot.run_state)

    extras = sanitized.get("extras")
    if isinstance(extras, dict) and isinstance(loadout.extras, dict):
        merge_f8_workflow_extras_into(extras, loadout.extras)
        sanitized["extras"] = extras
    return sanitized


def embed_run_state_for_suggestion(run_state: dict[str, Any]) -> dict[str, Any]:
    """Legacy wrapper — prefer embed_f8_snapshot with a gathered F8Snapshot."""
    board = parse_board_from_run_state(run_state)
    mod_money = mod_money_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    if board is not None:
        loadout = merge_loadout_with_board(
            loadout,
            board.money,
            mod_money=mod_money if mod_money > 0 else None,
        )
    loadout = hydrate_tile_ninja_loadout_extras(loadout, run_state)
    return (
        embed_f8_snapshot(
            F8Snapshot(
                run_state=run_state,
                board=board,
                loadout=loadout,
                board_available=board is not None,
            ),
            scoring_loadout=loadout,
        )
        or dict(run_state)
    )
