"""Main application: melmod-backed hotkey solver with overlay."""

from __future__ import annotations

import argparse
import atexit
import copy
import json
import signal
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

import keyboard
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from cursed_words_solver.capture import (
    capture_region,
    save_calibration_debug_image,
    save_debug_image,
)
from cursed_words_solver.fingerprints import (
    board_fingerprint,
    fingerprints_from_run_state,
)
from cursed_words_solver.config import (
    CONFIG_DIR,
    DEBUG_DIR,
    AppConfig,
    Region,
    describe_wordlist,
    resolve_wordlist,
)
from cursed_words_solver.f8_snapshot import (
    F8_HISTORIC_CATCHUP_REEXPORT_POLL_SEC,
    F8SuggestionSession,
    catchup_historic_gather_after_search,
    embed_f8_snapshot,
    f8_embed_replay_score,
    gather_f8_snapshot,
    historic_words_gather_pending,
    historic_workflow_catchup_needed,
    session_from_snapshot,
    sole_gather_miss_is_historic,
    write_f8_export_request,
)
from cursed_words_solver.suggestion import (
    clear_last_suggestion,
    clear_stale_last_suggestion_if_context_changed,
    clear_stale_last_suggestion_if_fingerprint_changed,
    clear_stale_last_suggestion_if_loadout_changed,
    dictionary_word_for_path,
    effective_scoring_word,
    empty_historic_on_later_grid_warning,
    f8_should_block_save,
    filter_submittable_results,
    format_suggestion_word,
    format_result_score_display,
    grid_transition_workflow_bleed_warning,
    poll_invalidate_last_suggestion,
    run_state_historic_stale_warnings,
    save_last_suggestion,
    save_blocked_suggestion,
)
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.f8_messages import format_f8_block_reason_html
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor, WordResult
from cursed_words_solver.board_display import format_board_grid
from cursed_words_solver.loadout import (
    bicycle_extras_stale_warning,
    encounter_mode_from_run_state,
    format_loadout_summary,
    load_run_state,
    load_run_state_raw,
    melmod_board_available,
    melmod_install_hint,
    merge_loadout_with_board,
    neapolitan_extras_stale_warning,
    mod_money_from_run_state,
    export_diagnostics_from_run_state,
    f8_historic_stale_after_merge_warning,
    parse_board_from_run_state,
    parse_encounter_grid_reroll,
    parse_run_state,
    parse_shop_from_run_state,
    solver_session_extras_from_loadout,
    validate_run_state_for_scoring,
    loadout_fingerprint_stale_warning,
    save_loadout,
    save_run_state_template,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.boss_effects import (
    boss_stage_display_suffix,
    boss_word_constraints,
)
from cursed_words_solver.rules.quest_effects import (
    active_quest_name,
    quest_constraints,
)
from cursed_words_solver.rules.quest_scoring import (
    bullseye_active,
    display_score_for_quest,
    quest_rank_beats_baseline,
    target_met,
    two_wrongs_active,
)
from cursed_words_solver.rules.rule_lookup import boss_display_name, resolve_rule_id
from cursed_words_solver.consumable_placement import (
    consumable_investment_active,
    consumables_placed_for_scoring,
    consumable_rack_tiles,
    format_placement_instructions,
    last_placement_search_stats,
    loadout_after_consumable_placements,
    multi_consumable_placement_beneficial,
    under_construction_active,
    rack_placement_search_active,
    mandatory_consumable_indices,
    remaining_rack_tiles,
    sandy_placement_search_active,
    search_consumable_score_boost,
    search_consumable_placement_fallback,
    search_target_rescue,
    search_with_consumable_placements,
    format_placement_search_stats_line,
    target_rescue_worth_trying,
    _result_rank_score,
)
from cursed_words_solver.rules.twinkle_toes import (
    TwinkleToesSwap,
    format_swap_instructions,
    search_with_twinkle_toes_swap,
    twinkle_toes_swap_pending,
)
from cursed_words_solver.rules.scoring_conditions import (
    consumable_rack_count,
    placed_consumable_indices,
    target_score_from_loadout,
)
from cursed_words_solver.rules.chess_tiles import missing_chess_color_warnings
from cursed_words_solver.search import (
    WordSearcher,
    format_microscope_position_hint,
    microscope_position_uses,
)
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
from cursed_words_solver.ui.board_highlight import BoardHighlightOverlay
from cursed_words_solver.ui.rack_highlight import RackHighlightOverlay
from cursed_words_solver.ui.layout import (
    OverlayRegions,
    describe_overlay_source,
    overlay_regions_ready,
    resolve_overlay_regions,
    ui_layout_export_status,
)
from cursed_words_solver.ui.calibrate import run_calibration_wizard
from cursed_words_solver.ui.loadout_dialog import LoadoutDialog
from cursed_words_solver.ui.overlay import ResultOverlay

RACK_RESERVE_FRAC = 0.35


def twinkle_swap_time_budget(
    *,
    search_budget: float,
    rack_placement_pending: bool,
    rack_reserve_frac: float = RACK_RESERVE_FRAC,
    solve_remaining_sec: float,
) -> float:
    """Cap Twinkle Toes search when rack placement still needs F8 budget."""
    if rack_placement_pending:
        return search_budget * (1.0 - rack_reserve_frac)
    return solve_remaining_sec


def twinkle_swap_deadline(
    *,
    search_started: float,
    solve_deadline: float,
    twinkle_budget: float,
) -> float:
    return min(solve_deadline, search_started + twinkle_budget)


@dataclass(frozen=True)
class _SolveUIUpdate:
    """Payload for posting solve results to the Qt main thread."""

    board: Board
    results: list[WordResult]
    board_bgr: np.ndarray | None
    warnings_html: str
    on_game_highlight: bool
    consumable_placements: list | None = None
    twinkle_toes_swap: TwinkleToesSwap | None = None
    loadout: Loadout | None = None
    # Fingerprints from run_state.json at solve time (melmod); used to detect shop/round end.
    melmod_board_fingerprint: str | None = None
    melmod_loadout_fingerprint: str | None = None
    shop_advice_html: str | None = None
    trusted_suggestion: bool = True
    block_reason: str | None = None


class _HotkeyBridge(QObject):
    """Marshal keyboard hook callbacks onto the Qt main thread."""

    recalibrate = Signal()
    edit_loadout = Signal()
    hide_overlay = Signal()
    quit_app = Signal()
    solve_finished = Signal(object)
    show_stale = Signal(str)


class SolverApp:
    def __init__(self, config: AppConfig, calibrate: bool = False) -> None:
        self.config = config
        self.calibrate = calibrate
        self.app = QApplication(sys.argv)
        self.overlay = ResultOverlay()
        self.board_highlight = BoardHighlightOverlay()
        self.rack_highlight = RackHighlightOverlay()
        self._highlight_board_fingerprint: str | None = None
        self._highlight_loadout_fingerprint: str | None = None
        self._highlight_watch_run_state = False
        self._last_invalidation_reason: str | None = None
        self._workflow_stale_overlay_reason: str | None = None
        self._active_suggestion_session: F8SuggestionSession | None = None
        self._loadout_source = self._detect_loadout_source()
        self._scoring = ScoringPipeline()
        self._dictionary: WordDictionary | None = None
        self._searcher: WordSearcher | None = None
        self._busy = False
        self._solve_active = False
        self._solve_generation = 0
        self._solve_gather_board_fp = ""
        self._solve_gather_grid = 0
        self._mid_solve_grid_advanced = False
        self._calibrating = False
        self._hotkey_handle = None
        self._shutting_down = False
        self._solver_started_at = datetime.now()
        self._bridge = _HotkeyBridge()
        self._bridge.recalibrate.connect(self._run_recalibrate)
        self._bridge.edit_loadout.connect(self._run_edit_loadout)
        self._bridge.hide_overlay.connect(self._hide_overlays)
        self._bridge.quit_app.connect(self._shutdown)
        self._bridge.solve_finished.connect(self._apply_solve_ui)
        self._bridge.show_stale.connect(self._on_show_stale_notice)
        self.overlay.request_quit.connect(self._shutdown)
        self._overlay_regions = resolve_overlay_regions(None, config)
        self._rack_collapse_warned = False
        from cursed_words_solver.round_log import round_log_index_size

        self._round_log_index_offset = round_log_index_size()
        atexit.register(keyboard.unhook_all)
        atexit.register(self._shutdown_search_pool)

    def _ensure_dictionary(self) -> bool:
        if self._dictionary is None:
            wl_path = resolve_wordlist(self.config.wordlist)
            self._dictionary = WordDictionary(wl_path)
        return True

    def _ensure_solver(self) -> bool:
        if not self._ensure_dictionary():
            return False
        if self._searcher is None:
            from cursed_words_solver.search_parallel import (
                resolve_search_workers,
                warmup_search_pool,
            )

            wl_path = resolve_wordlist(self.config.wordlist)
            workers = resolve_search_workers(self.config.search_workers)
            self._searcher = WordSearcher(
                dictionary=self._dictionary,
                min_len=1,
                max_len=25,
                time_budget=self.config.search_time_budget_sec,
                setup_weight=self.config.setup_weight,
                setup_discount=self.config.setup_discount,
                mult_search_weight=self.config.mult_search_weight,
                mult_search_passes=self.config.mult_search_passes,
                search_workers=workers,
                wordlist_path=wl_path,
            )
            if workers > 1:
                print(
                    f"Warming parallel search pool ({workers} workers)...",
                    flush=True,
                )
                warm_sec = warmup_search_pool(wl_path, workers)
                from cursed_words_solver.config import wordlist_count

                words = wordlist_count(wl_path)
                words_note = f", {words} words" if words else ""
                print(
                    f"  Pool ready in {warm_sec:.1f}s "
                    f"({workers} workers{words_note}).",
                    flush=True,
                )
        return True

    def _refresh_overlay_regions(self, run_state: dict | None = None) -> OverlayRegions:
        if run_state is None:
            run_state = load_run_state_raw()
        from cursed_words_solver.ui.layout import cursedle_overlay_mode

        cursedle = cursedle_overlay_mode(run_state)
        self._overlay_regions = resolve_overlay_regions(run_state, self.config)
        if self._overlay_regions.board_region_repaired:
            br = self._overlay_regions.board
            print(
                "  Warning: board overlay region looked corrupt; "
                f"repaired from cell centers to {br.width}×{br.height} "
                f"at ({br.x},{br.y}) — press F7 if highlights still misaligned",
                flush=True,
            )
        if not cursedle:
            if self._overlay_regions.rack_layout_collapsed:
                if not self._rack_collapse_warned:
                    self._rack_collapse_warned = True
                    print(
                        "  Warning: consumable rack layout export collapsed — "
                        "using last good F7 alignment (press F7 if markers still wrong)",
                        flush=True,
                    )
            elif self._overlay_regions.rack_slot_corrected:
                print(
                    "  Warning: consumable rack slot alignment corrected — "
                    "press F7 if rack markers still misaligned",
                    flush=True,
                )
        return self._overlay_regions

    def _overlay_board_region(self) -> Region | None:
        regions = getattr(self, "_overlay_regions", None)
        if regions is None:
            return None
        br = regions.board
        return br if br.is_valid() else None

    def _maybe_refresh_overlay_regions(self, run_state: dict | None) -> None:
        if run_state and hasattr(self, "config"):
            self._refresh_overlay_regions(run_state)

    def _on_show_stale_notice(self, message: str) -> None:
        data = load_run_state_raw()
        self._maybe_refresh_overlay_regions(data)
        self.overlay.show_stale_notice(
            message,
            board_region=self._overlay_board_region(),
        )

    def _needs_manual_calibration(self) -> bool:
        if self.calibrate:
            return True
        self._refresh_overlay_regions()
        if overlay_regions_ready(self._overlay_regions):
            return False
        return (
            not self.config.board_region.is_valid()
            or not self.config.rack_region.is_valid()
        )

    def run(self) -> int:
        if self._needs_manual_calibration():
            QMessageBox.information(
                None,
                "Calibration",
                "Melmod ui_layout not available yet.\n\n"
                "Press F7 in-game first for automatic overlay alignment.\n\n"
                "Otherwise drag the board and consumable rack regions manually.",
            )
            self.config = run_calibration_wizard(self.config)
            self._finish_calibration("Calibration complete")

        self._refresh_overlay_regions()
        if not self.calibrate:
            print(
                f"Overlay layout: {describe_overlay_source(self._overlay_regions)}",
                flush=True,
            )
            if self._overlay_regions.source == "manual":
                layout_status = ui_layout_export_status(load_run_state_raw())
                if layout_status:
                    print(
                        f"  ui_layout export failed ({layout_status}) — using manual F10",
                        flush=True,
                    )
                elif not overlay_regions_ready(self._overlay_regions):
                    print(
                        "  Tip: rebuild melmod and press F7 in-game for automatic alignment.",
                        flush=True,
                    )

        board_data = load_run_state_raw()
        if not melmod_board_available(board_data):
            QMessageBox.warning(
                None,
                "MelonLoader mod required",
                melmod_install_hint()
                + "\n\nF8 will not solve until run_state.json contains a board (start a round).",
            )

        wl_path = resolve_wordlist(self.config.wordlist)
        print(
            f"Word list: {describe_wordlist(wl_path, self.config.wordlist)}",
            flush=True,
        )
        if not (CONFIG_DIR / "run_state.json").exists():
            save_run_state_template()
        hotkey = self.config.hotkey
        try:
            keyboard.add_hotkey(hotkey, self._on_hotkey_pressed, suppress=False)
            self._hotkey_handle = hotkey
        except Exception as e:
            QMessageBox.critical(
                None,
                "Hotkey error",
                f"Could not register hotkey '{hotkey}': {e}\n"
                "Try running as administrator.",
            )
            return 1

        keyboard.add_hotkey("f9", self._bridge.edit_loadout.emit, suppress=False)
        keyboard.add_hotkey("f10", self._bridge.recalibrate.emit, suppress=False)
        keyboard.add_hotkey("esc", self._bridge.hide_overlay.emit, suppress=False)
        keyboard.add_hotkey(
            "ctrl+shift+q", self._bridge.quit_app.emit, suppress=False
        )
        self._install_shutdown_handlers()

        self.overlay.show_idle()

        self._run_state_poll_timer = QTimer()
        self._run_state_poll_timer.timeout.connect(self._poll_run_state_stale)
        self._run_state_poll_timer.start(500)

        print(
            f"Ready. Press {hotkey.upper()} to solve, F9 loadout, F10 recalibrate.",
            flush=True,
        )
        print(
            "Quit: Ctrl+Shift+Q or close the overlay window "
            "(Ctrl+C often fails while hotkeys are active).",
            flush=True,
        )
        startup_loadout = load_run_state()
        print(
            f"Loadout ({self._loadout_source}): "
            f"{format_loadout_summary(startup_loadout)}",
            flush=True,
        )
        scoring, total, grid_only, unmapped = self._scoring.loadout_mapping_summary(
            startup_loadout
        )
        if total:
            msg = f"  Rules: {scoring}/{total} affect score"
            if grid_only:
                msg += f" ({grid_only} grid-only)"
            print(msg, flush=True)
        if unmapped:
            print(
                f"  Unmapped (no wiki rule): {', '.join(unmapped[:8])}"
                + (" ..." if len(unmapped) > 8 else ""),
                flush=True,
            )
        if self._loadout_source == "template":
            print(
                "  Tip: install melmod (see melmod/README.md), start a run, press F7 in-game.",
                flush=True,
            )
        elif self._loadout_source in ("missing", "invalid"):
            print(
                "  Tip: start a run in-game, then press F8 here.",
                flush=True,
            )
        if melmod_board_available(board_data):
            print("Melmod board ready in run_state.json.", flush=True)
            board_fp, loadout_fp = fingerprints_from_run_state(board_data)
            if not clear_stale_last_suggestion_if_loadout_changed(loadout_fp):
                extras = board_data.get("extras") if isinstance(board_data, dict) else {}
                if not clear_stale_last_suggestion_if_context_changed(
                    board_fp,
                    current_loadout_fp=loadout_fp,
                    run_state_extras=extras if isinstance(extras, dict) else None,
                ):
                    cleared = clear_stale_last_suggestion_if_fingerprint_changed(
                        board_fp,
                        current_loadout_fp=loadout_fp,
                    )
                    if cleared:
                        self._last_invalidation_reason = cleared
                        print(
                            "  Cleared stale F8 suggestion from a prior board — "
                            "press F8 on this board.",
                            flush=True,
                        )
        elif self._loadout_source == "mod":
            print(
                "Melmod loadout found but no board in run_state.json — "
                "start a round, then press F8.",
                flush=True,
            )
        if not overlay_regions_ready(self._overlay_regions):
            print(
                "Press F7 in-game for automatic overlay alignment, "
                "or F10 to calibrate manually.",
                flush=True,
            )
        try:
            return self.app.exec()
        finally:
            self._cleanup_keyboard()

    def _install_shutdown_handlers(self) -> None:
        """Allow SIGINT and periodic wakeups so Ctrl+C can exit during Qt exec (Windows)."""

        def request_shutdown(*_args: object) -> None:
            QTimer.singleShot(0, self._shutdown)

        signal.signal(signal.SIGINT, request_shutdown)
        signal.signal(signal.SIGTERM, request_shutdown)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, request_shutdown)

        # Wake the Qt loop so Python can deliver SIGINT while keyboard hooks are active.
        self._sigint_timer = QTimer()
        self._sigint_timer.timeout.connect(lambda: None)
        self._sigint_timer.start(200)

        self.app.aboutToQuit.connect(self._cleanup_keyboard)

    def _cleanup_keyboard(self) -> None:
        try:
            keyboard.unhook_all()
        except Exception:
            pass

    @staticmethod
    def _shutdown_search_pool() -> None:
        from cursed_words_solver.search_parallel import shutdown_search_pool

        shutdown_search_pool(wait=False)

    def _shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        print("\nShutting down...", flush=True)
        self._cleanup_keyboard()
        self._hide_overlays()
        if self._solve_active:
            deadline = time.monotonic() + 5.0
            while self._solve_active and time.monotonic() < deadline:
                time.sleep(0.05)
        self._shutdown_search_pool()
        self.app.quit()

    def _hide_overlays(self) -> None:
        self.overlay.hide()
        self._clear_highlight_state()
        self._highlight_watch_run_state = False

    def _clear_highlight_state(self) -> None:
        self.board_highlight.clear()
        self.rack_highlight.clear()
        self._highlight_board_fingerprint = None
        self._highlight_loadout_fingerprint = None
        self._highlight_watch_run_state = False

    def _poll_run_state_stale(self) -> None:
        """Clear suggestion on word submit; guard active session from export lag."""
        from cursed_words_solver.round_log import (
            poll_round_log_submits,
            round_log_entries_after,
        )

        data = load_run_state_raw()

        entries, self._round_log_index_offset = poll_round_log_submits(
            self._round_log_index_offset
        )
        entries = round_log_entries_after(entries, self._solver_started_at)
        if entries:
            clear_last_suggestion()
            self._active_suggestion_session = None
            self._last_invalidation_reason = "word_submitted"
            self._workflow_stale_overlay_reason = None
            self._clear_highlight_state()
            if data:
                self._maybe_refresh_overlay_regions(data)
            self.overlay.show_idle(board_region=self._overlay_board_region())
            print("  Word submitted — press F8 for the next grid.", flush=True)

        if self._solve_active:
            from cursed_words_solver.fingerprints import fingerprints_from_run_state
            from cursed_words_solver.suggestion import _board_tiles_match

            if isinstance(data, dict):
                cur_board_fp, _ = fingerprints_from_run_state(data)
                if (
                    self._solve_gather_board_fp
                    and cur_board_fp
                    and not _board_tiles_match(
                        self._solve_gather_board_fp, cur_board_fp
                    )
                ):
                    self._solve_generation += 1
                extras_poll = data.get("extras")
                if isinstance(extras_poll, dict):
                    try:
                        cur_grid = int(str(extras_poll.get("grid_number") or "0"))
                    except ValueError:
                        cur_grid = 0
                    if (
                        self._solve_gather_grid > 0
                        and cur_grid > self._solve_gather_grid
                    ):
                        self._mid_solve_grid_advanced = True
                        self._solve_generation += 1
            return

        from cursed_words_solver.config import LAST_SUGGESTION_PATH
        from cursed_words_solver.fingerprints import (
            board_tiles_fingerprint_suffix,
            fingerprints_from_run_state,
        )

        extras = data.get("extras") if isinstance(data, dict) else None
        board_fp = ""
        loadout_fp = ""
        if data:
            board_fp, loadout_fp = fingerprints_from_run_state(data)

        if LAST_SUGGESTION_PATH.exists():
            from cursed_words_solver.suggestion import (
                fingerprint_invalidate_suppressed_for_suggested_board_change,
            )

            suggested_board_change = (
                fingerprint_invalidate_suppressed_for_suggested_board_change(
                    board_fp
                )
            )
            if suggested_board_change:
                self._last_invalidation_reason = None
            reason = poll_invalidate_last_suggestion(
                extras if isinstance(extras, dict) else None,
                current_board_fp=board_fp,
                current_loadout_fp=loadout_fp,
                active_session=self._active_suggestion_session,
            )
            if reason and reason != self._last_invalidation_reason:
                if not suggested_board_change:
                    self._last_invalidation_reason = reason
                    self._active_suggestion_session = None
                    self._clear_highlight_state()
                    from cursed_words_solver.suggestion import (
                        poll_invalidation_is_bicycle_stale,
                        poll_invalidation_is_workflow_stale,
                    )

                    if poll_invalidation_is_workflow_stale(reason):
                        detail = reason.removeprefix("workflow drift (").removesuffix(")")
                        if data:
                            self._maybe_refresh_overlay_regions(data)
                        self.overlay.show_stale_notice(
                            f"F8 prediction may be wrong ({detail}) — press F8 again.",
                            board_region=self._overlay_board_region(),
                        )
                    elif poll_invalidation_is_bicycle_stale(reason):
                        if data:
                            self._maybe_refresh_overlay_regions(data)
                        self.overlay.show_stale_notice(
                            "Bicycle acc changed — press F8 again.",
                            board_region=self._overlay_board_region(),
                        )
                    else:
                        if data:
                            self._maybe_refresh_overlay_regions(data)
                        self.overlay.show_idle(
                            board_region=self._overlay_board_region()
                        )
                    print(f"  Suggestion cleared — {reason}", flush=True)
            elif reason is None and self._active_suggestion_session is not None:
                self._last_invalidation_reason = None
        elif (
            self._highlight_board_fingerprint is not None
            and not LAST_SUGGESTION_PATH.exists()
            and self._active_suggestion_session is None
        ):
            self._active_suggestion_session = None
            self._last_invalidation_reason = "suggestion_expired"
            self._clear_highlight_state()
            if data:
                self._maybe_refresh_overlay_regions(data)
            self.overlay.show_idle(board_region=self._overlay_board_region())

        self._maybe_clear_stale_highlights(board_tiles_fingerprint_suffix)

    def _maybe_clear_stale_highlights(self, tiles_fp_fn=None) -> None:
        """Drop on-board path when melmod reports a new round, shop, or missing board."""
        from cursed_words_solver.fingerprints import (
            board_tiles_fingerprint_suffix,
            fingerprints_from_run_state,
        )

        if tiles_fp_fn is None:
            tiles_fp_fn = board_tiles_fingerprint_suffix
        if self._highlight_board_fingerprint is None:
            return
        if not self._highlight_watch_run_state:
            return
        data = load_run_state_raw()
        if parse_board_from_run_state(data) is None:
            self._clear_highlight_state()
            return
        current_board_fp = ""
        current_loadout_fp = ""
        if data:
            current_board_fp, current_loadout_fp = fingerprints_from_run_state(data)
        saved_tiles = tiles_fp_fn(self._highlight_board_fingerprint or "")
        current_tiles = tiles_fp_fn(current_board_fp)
        if saved_tiles and current_tiles and saved_tiles != current_tiles:
            from cursed_words_solver.suggestion import (
                fingerprint_invalidate_suppressed_for_suggested_board_change,
            )

            if not fingerprint_invalidate_suppressed_for_suggested_board_change(
                current_board_fp
            ):
                self._clear_highlight_state()
            return
        if (
            self._highlight_loadout_fingerprint is not None
            and current_loadout_fp != self._highlight_loadout_fingerprint
        ):
            self._clear_highlight_state()

    def _apply_solve_ui(self, update: _SolveUIUpdate) -> None:
        """Show overlay and board highlights on the Qt GUI thread."""
        if update.shop_advice_html:
            self._clear_highlight_state()
            self.overlay.show_shop_advice(
                update.shop_advice_html,
                warnings_html=update.warnings_html,
                board_region=self._overlay_board_region(),
            )
            return
        show_path = (
            update.on_game_highlight
            and self._overlay_regions.board.is_valid()
            and bool(update.results)
        )
        self.overlay.show_results(
            update.board,
            update.results,
            board_bgr=update.board_bgr,
            warnings_html=update.warnings_html,
            on_game_highlight=show_path,
            consumable_placements=update.consumable_placements,
            twinkle_toes_swap=update.twinkle_toes_swap,
            trusted=update.trusted_suggestion,
            loadout=update.loadout,
            board_region=self._overlay_board_region(),
        )
        if show_path:
            if update.melmod_board_fingerprint is not None:
                self._highlight_board_fingerprint = update.melmod_board_fingerprint
                self._highlight_loadout_fingerprint = update.melmod_loadout_fingerprint
                self._highlight_watch_run_state = True
            else:
                self._highlight_board_fingerprint = board_fingerprint(update.board)
                self._highlight_loadout_fingerprint = None
                self._highlight_watch_run_state = False
            self.board_highlight.show_path(
                self._overlay_regions.board,
                update.results[0].path,
                update.board,
                placements=update.consumable_placements,
                twinkle_toes_swap=update.twinkle_toes_swap,
                cell_centers=self._overlay_regions.board_cell_centers,
            )
            if (
                update.consumable_placements
                and self._overlay_regions.rack.is_valid()
            ):
                self.rack_highlight.show_placements(
                    self._overlay_regions.rack,
                    update.results[0].path,
                    update.consumable_placements,
                    rack_slot_centers=self._overlay_regions.rack_slot_centers,
                    rack_slot_sizes=self._overlay_regions.rack_slot_sizes,
                    rack_tile_height=self._overlay_regions.rack_tile_height,
                )
            else:
                self.rack_highlight.clear()
            self.rack_highlight.raise_()
        else:
            self._clear_highlight_state()

    def _finish_calibration(self, prefix: str) -> None:
        self._overlay_regions = OverlayRegions(
            board=self.config.board_region,
            rack=self.config.rack_region,
            source="manual",
        )
        br = self._overlay_regions.board
        rr = self._overlay_regions.rack
        if br.is_valid():
            print(
                f"{prefix}. Board region: {br.width}×{br.height} at ({br.x},{br.y}).",
                flush=True,
            )
        if rr.is_valid():
            print(
                f"{prefix}. Rack region: {rr.width}×{rr.height} at ({rr.x},{rr.y}).",
                flush=True,
            )
        if br.is_valid() or rr.is_valid():
            self._save_calibration_preview()

    def _save_calibration_preview(self) -> None:
        br = self._overlay_regions.board
        rr = self._overlay_regions.rack
        if not br.is_valid() and not rr.is_valid():
            return
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            path = DEBUG_DIR / "calibration_preview.png"
            save_calibration_debug_image(
                br if br.is_valid() else self.config.board_region,
                rr if rr.is_valid() else self.config.rack_region,
                path,
            )
            print(f"Capture preview saved: {path}", flush=True)
            if br.is_valid():
                board_only = DEBUG_DIR / "calibration_board_crop.png"
                img = capture_region(br)
                save_debug_image(img, board_only)
        except Exception as e:
            print(f"Could not save capture preview: {e}", flush=True)

    def _on_hotkey_pressed(self) -> None:
        if self._calibrating:
            return
        if self._busy:
            self._solve_generation += 1
            print(
                "F8 re-pressed — cancelling stale solve and re-exporting.",
                flush=True,
            )
            return
        self._solve_generation += 1
        threading.Thread(target=self._solve_worker, daemon=True).start()

    def _solve_cancelled(self, my_gen: int) -> bool:
        return self._solve_generation != my_gen

    def _shop_advisor_worker(self, run_state_data: dict | None) -> None:
        """Shop advice path when encounter_mode is shop."""
        from cursed_words_solver.shop_advisor import (
            format_shop_advice_html,
            format_shop_advice_text,
            run_shop_advisor,
        )

        from cursed_words_solver.f8_snapshot import shop_extras_ready

        extras_deadline = time.monotonic() + 5.0
        while not shop_extras_ready(run_state_data) and time.monotonic() < extras_deadline:
            time.sleep(0.1)
            run_state_data = load_run_state_raw()

        shop = parse_shop_from_run_state(run_state_data)
        if shop is None or not shop.offers:
            print(
                "Shop mode detected but no shop offers in run_state.json — "
                "rebuild melmod, press F8 in the Ej?A56 shop.",
                flush=True,
            )
            return

        loadout = parse_run_state(run_state_data or {})
        mod_money = mod_money_from_run_state(run_state_data)
        loadout = merge_loadout_with_board(
            loadout,
            loadout.money,
            mod_money=mod_money if mod_money > 0 else None,
        )
        from cursed_words_solver.rules.quest_effects import active_quest_name

        quest_label = active_quest_name(loadout)
        search_msg = f"Shop advice (${loadout.money} available)"
        if quest_label:
            search_msg += f", Quest: {quest_label}"
        print(search_msg + "...", flush=True)

        advice = run_shop_advisor(
            loadout,
            shop,
            on_progress=lambda msg: print(f"  {msg}", flush=True),
        )
        print(format_shop_advice_text(advice), flush=True)

        placeholder = Tile(
            row=0,
            col=0,
            char=".",
            letter=".",
            base_score=0,
            color=TileColor.COLORLESS,
            curse=CurseType.LETTER,
        )
        empty_board = Board(tiles=[[placeholder for _ in range(5)] for _ in range(5)])
        self._bridge.solve_finished.emit(
            _SolveUIUpdate(
                board=empty_board,
                results=[],
                board_bgr=None,
                warnings_html="<br>".join(advice.warnings) if advice.warnings else "",
                on_game_highlight=False,
                shop_advice_html=format_shop_advice_html(advice),
            )
        )

    def _cursedle_worker(self, run_state_data: dict | None) -> None:
        """Cursedle constraint solver when encounter_mode is cursedle."""
        from cursed_words_solver.f8_snapshot import gather_f8_snapshot, write_f8_export_request

        if not self._ensure_dictionary():
            print("Solver not ready (dictionary failed to load).", flush=True)
            return

        f8_request_id = write_f8_export_request()
        snapshot = gather_f8_snapshot(
            rules=self._scoring.rules,
            f8_request_id=f8_request_id,
            on_wait=lambda msg: print(f"  {msg}", flush=True),
        )
        self._finish_cursedle_from_snapshot(snapshot)

    def _finish_cursedle_from_snapshot(self, snapshot) -> None:
        """Run Cursedle solver from a gathered F8 snapshot."""
        from cursed_words_solver.cursedle_solver import (
            format_cursedle_advice_text,
            run_cursedle_solver,
            save_cursedle_suggestion,
        )
        from cursed_words_solver.f8_messages import gather_incomplete_message

        run_state_data = snapshot.run_state
        board = snapshot.board
        loadout = snapshot.loadout

        gather_succeeded = (
            snapshot.board_available
            and snapshot.loadout is not None
            and snapshot.extras_ready
        )
        for warn in snapshot.warnings:
            if not warn.startswith("waiting for melmod"):
                print(f"  Warning: {warn}", flush=True)
        if not gather_succeeded:
            print(
                f"  {gather_incomplete_message(snapshot.gather_missing)}",
                flush=True,
            )
            return
        if board is None or loadout is None:
            print("Cursedle: no board in export — press F8 in the trial.", flush=True)
            return

        if not self._ensure_dictionary():
            print("Solver not ready (dictionary failed to load).", flush=True)
            return
        print("Cursedle solve started...", flush=True)
        print(format_board_grid(board, compact=True), flush=True)
        self._refresh_overlay_regions(run_state_data)

        advice = run_cursedle_solver(
            board,
            loadout,
            self._dictionary,
            on_progress=lambda msg: print(f"  {msg}", flush=True),
        )
        print(format_cursedle_advice_text(advice), flush=True)

        if advice.path and advice.word:
            save_cursedle_suggestion(
                board=board,
                loadout=loadout,
                advice=advice,
                run_state_snapshot=run_state_data,
                export_diagnostics=(
                    run_state_data.get("export_diagnostics")
                    if isinstance(run_state_data, dict)
                    else None
                ),
                export_warnings=snapshot.warnings,
                gather_status={
                    "extras_ready": snapshot.extras_ready,
                    "gather_missing": snapshot.gather_missing,
                },
            )
            self._last_invalidation_reason = None
            melmod_board_fp = ""
            melmod_loadout_fp = ""
            if isinstance(run_state_data, dict):
                from cursed_words_solver.fingerprints import fingerprints_from_run_state

                melmod_board_fp, melmod_loadout_fp = fingerprints_from_run_state(
                    run_state_data
                )
            result = WordResult(
                word=advice.word,
                path=advice.path,
                score=0,
            )
            self._bridge.solve_finished.emit(
                _SolveUIUpdate(
                    board=board,
                    results=[result],
                    board_bgr=None,
                    warnings_html="<br>".join(advice.warnings) if advice.warnings else "",
                    on_game_highlight=True,
                    melmod_board_fingerprint=melmod_board_fp or None,
                    melmod_loadout_fingerprint=melmod_loadout_fp or None,
                )
            )
        else:
            self._bridge.solve_finished.emit(
                _SolveUIUpdate(
                    board=board,
                    results=[],
                    board_bgr=None,
                    warnings_html="<br>".join(advice.warnings) if advice.warnings else "",
                    on_game_highlight=False,
                )
            )

    def _solve_worker(self) -> None:
        my_gen = self._solve_generation
        self._mid_solve_grid_advanced = False
        self._solve_gather_board_fp = ""
        self._solve_gather_grid = 0
        self._busy = True
        self._solve_active = True
        cancel_check = lambda: self._solve_cancelled(my_gen)
        unmapped: list[str] = []
        board_source = "melmod"
        money_source = "mod"
        try:
            print("Solve started...", flush=True)

            run_state_data = load_run_state_raw()
            mode = encounter_mode_from_run_state(run_state_data)
            if mode == "shop":
                self._shop_advisor_worker(run_state_data)
                return
            if mode == "cursedle":
                self._cursedle_worker(run_state_data)
                return

            f8_request_id = write_f8_export_request()
            snapshot = gather_f8_snapshot(
                rules=self._scoring.rules,
                f8_request_id=f8_request_id,
                on_wait=lambda msg: print(f"  {msg}", flush=True),
            )
            run_state_data = snapshot.run_state
            board = snapshot.board
            loadout = snapshot.loadout
            board_img = None
            gather_succeeded = (
                snapshot.board_available
                and snapshot.loadout is not None
                and snapshot.extras_ready
            )
            solve_grid_at_start = 0
            if loadout is not None:
                from cursed_words_solver.rules.scoring_conditions import grid_number

                try:
                    solve_grid_at_start = grid_number(loadout)
                except (TypeError, ValueError):
                    solve_grid_at_start = 0

            for warn in snapshot.warnings:
                if not warn.startswith("waiting for melmod"):
                    print(f"  Warning: {warn}", flush=True)

            if not gather_succeeded:
                from cursed_words_solver.f8_messages import gather_incomplete_message

                print(
                    f"  {gather_incomplete_message(snapshot.gather_missing)}",
                    flush=True,
                )

            if (
                gather_succeeded
                and run_state_data is not None
                and encounter_mode_from_run_state(run_state_data) == "cursedle"
            ):
                self._finish_cursedle_from_snapshot(snapshot)
                return

            if not self._ensure_solver():
                print("Solver not ready (dictionary failed to load).", flush=True)
                return
            if self._searcher is not None:
                self._searcher._cancel_check = cancel_check

            workflow_warnings: list[str] = []
            if loadout is not None and isinstance(loadout.extras, dict):
                workflow_warnings = run_state_historic_stale_warnings(loadout.extras)
            if board is not None and loadout is not None:
                from cursed_words_solver.suggestion import (
                    scatter_level_below_equipped_warning,
                )

                scatter_note = scatter_level_below_equipped_warning(loadout, board)
                if scatter_note:
                    workflow_warnings.append(scatter_note)
            for warn in workflow_warnings:
                print(f"  Workflow: {warn}", flush=True)

            if board is None:
                shop = parse_shop_from_run_state(run_state_data)
                if shop is not None and shop.offers:
                    self._shop_advisor_worker(run_state_data)
                    return

                print(melmod_install_hint(), flush=True)
                if run_state_data is None:
                    print(
                        "Could not read run_state.json (file locked or invalid JSON). "
                        "Press F8 again — waiting for live game export.",
                        flush=True,
                    )
                elif isinstance(run_state_data.get("shop"), dict):
                    print(
                        "Shop export has no offers — press F8 in the Ej?A56 shop. "
                        "Rebuild melmod if offers stay empty.",
                        flush=True,
                    )
                elif not isinstance(run_state_data.get("board"), dict):
                    print(
                        "No board in run_state.json — start a round, then press F8.",
                        flush=True,
                    )
                else:
                    n = len(run_state_data.get("board", {}).get("tiles", []))
                    print(
                        f"Board export invalid ({n} tiles, need 25 or 36) — press F8 again.",
                        flush=True,
                    )
                return

            assert loadout is not None
            mod_money = mod_money_from_run_state(run_state_data)
            print("Board from melmod (run_state.json).", flush=True)
            self._refresh_overlay_regions(run_state_data)
            if self._overlay_regions.source == "melmod":
                print(
                    f"  Overlay layout: {describe_overlay_source(self._overlay_regions)}",
                    flush=True,
                )
            else:
                layout_status = ui_layout_export_status(run_state_data)
                if layout_status:
                    print(
                        f"  ui_layout export failed ({layout_status}) — using manual F10",
                        flush=True,
                    )
            run_extras = (
                run_state_data.get("extras")
                if isinstance(run_state_data, dict)
                else None
            )
            fp_warn = loadout_fingerprint_stale_warning(
                loadout,
                run_extras if isinstance(run_extras, dict) else None,
            )
            if fp_warn:
                print(f"  Warning: {fp_warn}", flush=True)
            if mod_money:
                print(f"Money: ${mod_money} (mod)", flush=True)
            print("Parsed board:", flush=True)
            print(format_board_grid(board, compact=True), flush=True)
            melmod_board_fp: str | None = None
            melmod_loadout_fp: str | None = None
            if run_state_data:
                melmod_board_fp, melmod_loadout_fp = fingerprints_from_run_state(
                    run_state_data
                )
            for warn in missing_chess_color_warnings(board):
                print(f"  Warning: {warn}", flush=True)
            if self._overlay_regions.board.is_valid():
                try:
                    board_img = capture_region(self._overlay_regions.board)
                    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                    save_debug_image(board_img, DEBUG_DIR / "last_board.png")
                except Exception as e:
                    print(f"Board capture skipped: {e}", flush=True)
            elif self.config.show_board_highlight:
                print(
                    "Press F10 to calibrate board region for on-screen path highlights.",
                    flush=True,
                )

            if melmod_board_fp:
                self._solve_gather_board_fp = melmod_board_fp
            self._solve_gather_grid = solve_grid_at_start

            if self._solve_cancelled(my_gen):
                return

            search_budget = self.config.search_time_budget_sec
            search_started = time.monotonic()
            solve_deadline = search_started + search_budget
            search_call_mono = search_started
            search_end_mono = search_started
            dict_resolve_truncated = False
            placement_gen_sec = 0.0
            placement_screen_sec = 0.0
            placement_refine_sec = 0.0

            def _accumulate_placement_timing() -> None:
                nonlocal placement_gen_sec, placement_screen_sec, placement_refine_sec
                stats = last_placement_search_stats()
                placement_gen_sec += stats.variant_gen_sec
                placement_screen_sec += stats.variant_screen_sec
                placement_refine_sec += stats.variant_refine_sec

            def solve_remaining() -> float:
                return max(0.0, solve_deadline - time.monotonic())

            def phase_budget(share: float) -> float:
                return min(share, solve_remaining())

            def variant_gen_budget() -> float:
                base = min(2.0, solve_remaining() * 0.05)
                if under_construction_active(loadout):
                    return min(10.0, max(base, solve_remaining() * 0.15))
                if multi_consumable_placement_beneficial(loadout):
                    return min(6.0, max(base, solve_remaining() * 0.10))
                return base
            from cursed_words_solver.rules.scoring_conditions import rewind_setup_extras

            rewind_notes = rewind_setup_extras(loadout, board)
            # Neapolitan +5% submit simulation when 3+ colours (F8 export is pre-submit).
            if isinstance(loadout.extras, dict):
                has_neapolitan = any(
                    str(getattr(stamp, "id", "") or "").strip().lower() == "neapolitan"
                    for stamp in (loadout.stamps or [])
                )
                from cursed_words_solver.rules.scoring_conditions import (
                    neapolitan_has_live_percent,
                )

                if (
                    not has_neapolitan
                    or not neapolitan_has_live_percent(loadout)
                    or has_neapolitan
                ):
                    loadout.extras["simulate_submit_improvements"] = True
                if has_neapolitan:
                    from cursed_words_solver.rules.scoring_conditions import (
                        neapolitan_base_percent_from_loadout,
                    )

                    base_percent, source = neapolitan_base_percent_from_loadout(loadout)
                    source_label = {
                        "live": "live export",
                        "default": "default fallback",
                    }.get(source, source)
                    print(
                        "  Setup: Neapolitan submit simulation "
                        f"({base_percent}% -> {base_percent + 5}% when 3+ colours; "
                        f"{source_label}).",
                        flush=True,
                    )
                    if source == "default" and not neapolitan_has_live_percent(loadout):
                        print(
                            "  Warning: Neapolitan baseline missing from run_state — "
                            "press F8 again so melmod can capture "
                            "neapolitan_percent.",
                            flush=True,
                        )
            self._searcher.setup_weight = self.config.setup_weight
            self._searcher.setup_discount = self.config.setup_discount
            self._searcher.mult_search_weight = self.config.mult_search_weight
            self._searcher.mult_search_passes = self.config.mult_search_passes
            scoring, total, grid_only, unmapped = self._scoring.loadout_mapping_summary(
                loadout
            )
            print(format_loadout_summary(loadout), flush=True)
            for note in rewind_notes:
                print(f"  Setup: {note}", flush=True)
            bicycle_warn = bicycle_extras_stale_warning(loadout)
            if bicycle_warn:
                print(f"  Warning: {bicycle_warn}", flush=True)
            neap_warn = neapolitan_extras_stale_warning(loadout)
            if neap_warn:
                print(f"  Warning: {neap_warn}", flush=True)
            from cursed_words_solver.loadout import steak_extras_stale_warning

            steak_warn = steak_extras_stale_warning(loadout)
            if steak_warn:
                print(f"  Warning: {steak_warn}", flush=True)
            from cursed_words_solver.rules.capybara_scoring import (
                MAX_EXHAUSTIVE_PERMS,
                capybara_active_warning,
                capybara_perm_count,
                capybara_sampling_warning,
                capybara_shuffle_scope,
            )

            capybara_warn = capybara_active_warning(loadout, self._scoring.rules)
            if capybara_warn:
                print(f"  Warning: {capybara_warn}", flush=True)
                scope = capybara_shuffle_scope(loadout, self._scoring.rules)
                if capybara_perm_count(loadout, scope) > MAX_EXHAUSTIVE_PERMS:
                    sample_warn = capybara_sampling_warning(False, 256)
                    if sample_warn:
                        print(f"  Warning: {sample_warn}", flush=True)
            if total:
                msg = f"  Rules: {scoring}/{total} affect score"
                if grid_only:
                    msg += f" ({grid_only} grid-only)"
                print(msg, flush=True)
            if unmapped:
                print(f"  Unmapped: {', '.join(unmapped[:6])}", flush=True)
            if board_source == "melmod":
                from cursed_words_solver.loadout import encounter_missing_boss_should_warn

                if encounter_missing_boss_should_warn(loadout):
                    print(
                        "  Boss not in run_state.json — press F8 again; "
                        "rebuild melmod if you are fighting a boss.",
                        flush=True,
                    )
            placed_consumables = placed_consumable_indices(board)
            mandatory = mandatory_consumable_indices(
                loadout, board, self._scoring.rules
            )

            sandy_auto_place = sandy_placement_search_active(
                loadout, board, self._scoring.rules
            )
            rack_tiles: list = []
            placement_records: list = []
            twinkle_swap_record: TwinkleToesSwap | None = None
            has_target = "target_score" in (loadout.extras or {})
            grid_target = target_score_from_loadout(loadout) if has_target else 0
            if two_wrongs_active(loadout) or bullseye_active(loadout):
                try:
                    encounter_remaining = int(
                        (loadout.extras or {}).get("encounter_remaining_target") or 0
                    )
                except (TypeError, ValueError):
                    encounter_remaining = 0
                if encounter_remaining > 0:
                    has_target = True
                    grid_target = encounter_remaining
            if mandatory:
                print(
                    f"  Sandy Saguaro: {len(mandatory)} placed consumable(s) "
                    "must be in word path",
                    flush=True,
                )
            elif sandy_auto_place:
                rack_tiles = consumable_rack_tiles(loadout, cactus_only=True)
                print(
                    f"  Sandy Saguaro: {len(rack_tiles)} CACTUS consumable(s) on rack "
                    "— simulating placements…",
                    flush=True,
                )
            board_max_len = max(1, sum(board.active))
            constraints = boss_word_constraints(
                loadout,
                self._scoring.rules,
                default_max_len=board_max_len,
            )
            effective_min = max(constraints.min_len, 3)
            effective_max = min(board_max_len, constraints.max_len)
            if effective_max < effective_min:
                effective_max = effective_min
            from cursed_words_solver.loadout import encounter_missing_boss_should_warn
            from cursed_words_solver.rules.boss_effects import (
                michael_finale_active,
                michael_finale_export_expected,
            )

            if encounter_missing_boss_should_warn(loadout):
                print(
                    "  Boss fight detected but boss export missing — press F8 again.",
                    flush=True,
                )
                return
            _run_extras = loadout.extras if isinstance(loadout.extras, dict) else {}
            _run_stage = 0
            try:
                _run_stage = int(_run_extras.get("run_stage") or 0)
            except (TypeError, ValueError):
                _run_stage = 0
            _node = str(_run_extras.get("run_node_type") or "").strip().lower()
            if (
                board_max_len >= 25
                and _run_stage >= 6
                and "boss" in _node
                and effective_min < 25
                and not michael_finale_active(loadout, default_max_len=board_max_len)
                and michael_finale_export_expected(
                    loadout, default_max_len=board_max_len
                )
            ):
                _cobra_raw = _run_extras.get("cobra_min_length")
                _has_stacked_min = False
                if _cobra_raw not in (None, ""):
                    try:
                        _has_stacked_min = int(_cobra_raw) > 1
                    except (TypeError, ValueError):
                        _has_stacked_min = False
                if not _has_stacked_min:
                    print(
                        "  Michael finale expected but 25-tile word rules not loaded "
                        "— press F8 again.",
                        flush=True,
                    )
                    return
            michael_finale_guaranteed = (
                michael_finale_active(loadout, default_max_len=board_max_len)
                and effective_min == effective_max == board_max_len
            )
            rules = self._scoring.rules
            rack_placement_pending = (
                not sandy_auto_place
                and rack_placement_search_active(loadout, board, rules)
            )
            rack_reserve_frac = RACK_RESERVE_FRAC
            twinkle_pending = twinkle_toes_swap_pending(loadout)
            primary_search_budget = (
                search_budget * (1.0 - rack_reserve_frac)
                if rack_placement_pending
                else search_budget
            )
            rack_fallback_budget = search_budget * rack_reserve_frac
            self._searcher.min_len = effective_min
            self._searcher.max_len = effective_max
            self._searcher.time_budget = phase_budget(primary_search_budget)
            self._searcher.validator.min_len = self._searcher.min_len
            self._searcher.validator.required_consumable_indices = mandatory
            self._searcher.blocked = constraints.blocked
            self._searcher.block_reason = constraints.block_reason
            search_msg = (
                f"Searching for words (total F8 budget {search_budget:.0f}s, "
                f"length {effective_min}–{effective_max})"
            )
            if loadout.boss_id or loadout.boss_name:
                boss_label = boss_display_name(loadout, self._scoring.rules)
                search_msg += f", Boss: {boss_label} ({boss_stage_display_suffix(loadout)})"
                if loadout.extras.get("boss_cursed"):
                    search_msg += " (cursed)"
            quest_label = active_quest_name(loadout)
            if quest_label:
                search_msg += f", Quest: {quest_label}"
                q = quest_constraints(loadout)
                if q.bullseye:
                    search_msg += " (exact target)"
                elif q.two_wrongs:
                    search_msg += " (inverted target)"
            print(search_msg + "...", flush=True)
            if constraints.blocked and constraints.block_reason:
                print(f"  Boss: {constraints.block_reason}", flush=True)
            if self._searcher.search_workers > 1:
                print(
                    f"  Parallel search: {self._searcher.search_workers} workers "
                    "(pool reused for this solve)",
                    flush=True,
                )
            search_board = board
            results: list = []
            rescue_budget = search_budget * 0.4
            rack_boost_share = (
                0.45 if multi_consumable_placement_beneficial(loadout) else 0.3
            )
            rack_boost_budget = search_budget * rack_boost_share
            if sandy_auto_place and rack_tiles and solve_remaining() >= 1.0:
                search_call_mono = time.monotonic()
                search_board, placement_records, results = (
                    search_with_consumable_placements(
                        self._searcher,
                        board,
                        loadout,
                        rack_tiles,
                        time_budget=phase_budget(search_budget),
                        top_n=self.config.top_n_results,
                        rules=rules,
                        solve_deadline=solve_deadline,
                    )
                )
                _accumulate_placement_timing()
                self._searcher.validator.required_consumable_indices = (
                    mandatory_consumable_indices(
                        loadout, search_board, self._scoring.rules
                    )
                )
                if placement_records:
                    print(
                        f"  Place consumables: {format_placement_instructions(placement_records)}",
                        flush=True,
                    )
                elif not results:
                    print(
                        "  No valid word found with simulated consumable placements.",
                        flush=True,
                    )
                if has_target and results:
                    best_display = int(
                        display_score_for_quest(float(results[0].score), loadout)
                    )
                    if two_wrongs_active(loadout):
                        print(
                            f"  Target: {-grid_target} display "
                            f"({grid_target} remaining, best {best_display})",
                            flush=True,
                        )
                    elif bullseye_active(loadout):
                        best_score = int(results[0].score)
                        exact = target_met(
                            float(best_score), float(grid_target), loadout
                        )
                        suffix = "" if exact else " (exact hit needed)"
                        print(
                            f"  Target: {grid_target} pts{suffix} (best {best_score})",
                            flush=True,
                        )
                    else:
                        print(
                            f"  Target: {grid_target} pts (best {int(results[0].score)})",
                            flush=True,
                        )
            elif twinkle_pending and solve_remaining() >= 1.0:
                print(
                    "  Twinkle Toes: swap pending — simulating tile pairs…",
                    flush=True,
                )
                search_call_mono = time.monotonic()
                twinkle_budget = twinkle_swap_time_budget(
                    search_budget=search_budget,
                    rack_placement_pending=rack_placement_pending,
                    rack_reserve_frac=rack_reserve_frac,
                    solve_remaining_sec=solve_remaining(),
                )
                twinkle_deadline = twinkle_swap_deadline(
                    search_started=search_started,
                    solve_deadline=solve_deadline,
                    twinkle_budget=twinkle_budget,
                )
                search_board, twinkle_swap_record, results = (
                    search_with_twinkle_toes_swap(
                        self._searcher,
                        board,
                        loadout,
                        time_budget=phase_budget(twinkle_budget),
                        top_n=self.config.top_n_results,
                        solve_deadline=twinkle_deadline,
                    )
                )
                if twinkle_swap_record:
                    print(
                        f"  {format_swap_instructions(twinkle_swap_record, board)}",
                        flush=True,
                    )
                elif not results:
                    print(
                        "  No valid word found after Twinkle Toes swap search.",
                        flush=True,
                    )
                if has_target and results:
                    best_display = int(
                        display_score_for_quest(float(results[0].score), loadout)
                    )
                    if two_wrongs_active(loadout):
                        print(
                            f"  Target: {-grid_target} display "
                            f"({grid_target} remaining, best {best_display})",
                            flush=True,
                        )
                    elif bullseye_active(loadout):
                        best_score = int(results[0].score)
                        exact = target_met(
                            float(best_score), float(grid_target), loadout
                        )
                        suffix = "" if exact else " (exact hit needed)"
                        print(
                            f"  Target: {grid_target} pts{suffix} (best {best_score})",
                            flush=True,
                        )
                    else:
                        print(
                            f"  Target: {grid_target} pts (best {int(results[0].score)})",
                            flush=True,
                        )
            elif solve_remaining() >= 0.5:
                search_call_mono = time.monotonic()
                results = self._searcher.find_best_words(
                    board,
                    loadout=loadout,
                    top_n=self.config.top_n_results,
                    deadline=solve_deadline,
                    cancel_check=cancel_check,
                )
            else:
                results = []

            if not results:
                q_center = quest_constraints(loadout).require_center_index
                if q_center is not None:
                    print(
                        "  Warning: No words found that use the center tile "
                        "(Up and Up).",
                        flush=True,
                    )

            if (
                not results
                and not sandy_auto_place
                and rack_placement_search_active(loadout, board, rules)
                and solve_remaining() >= 1.0
            ):
                fallback_rack = remaining_rack_tiles(loadout, board)
                if fallback_rack:
                    print(
                        "  No board-only word — simulating consumable placements…",
                        flush=True,
                    )
                    search_board, placement_records, results = (
                        search_consumable_placement_fallback(
                            self._searcher,
                            board,
                            loadout,
                            fallback_rack,
                            time_budget=phase_budget(rack_fallback_budget),
                            top_n=self.config.top_n_results,
                            rules=rules,
                            solve_deadline=solve_deadline,
                        )
                    )
                    _accumulate_placement_timing()
                    print(
                        f"  {format_placement_search_stats_line()}",
                        flush=True,
                    )
                    self._searcher.validator.required_consumable_indices = (
                        mandatory_consumable_indices(
                            loadout, search_board, rules
                        )
                    )
                    if placement_records:
                        print(
                            f"  Place consumables: "
                            f"{format_placement_instructions(placement_records)}",
                            flush=True,
                        )
                    elif not results:
                        print(
                            "  No valid word found with simulated consumable "
                            "placements.",
                            flush=True,
                        )

            if not results and michael_finale_guaranteed:
                print(
                    f"  Michael finale: no word in {search_budget:.0f}s "
                    "— continuing until solution found…",
                    flush=True,
                )
                search_call_mono = time.monotonic()
                completion_start = time.monotonic()
                completion_results = self._searcher.find_best_words(
                    search_board,
                    loadout=loadout,
                    top_n=self.config.top_n_results,
                    run_until_found=True,
                    cancel_check=cancel_check,
                )
                if completion_results:
                    results = completion_results
                    print(
                        f"  Found in {time.monotonic() - completion_start:.1f}s "
                        "additional search",
                        flush=True,
                    )

            baseline_score = results[0].score if results else 0.0
            baseline_rank = (
                _result_rank_score(results[0]) if results else baseline_score
            )
            if (
                not sandy_auto_place
                and rack_placement_search_active(loadout, board, rules)
                and results
                and solve_remaining() >= 1.0
            ):
                boost_rack = remaining_rack_tiles(loadout, board)
                if boost_rack:
                    print(
                        f"  Consumables: {len(boost_rack)} on rack "
                        "— simulating placements…",
                        flush=True,
                    )
                    boost_gen_budget = (
                        None
                        if under_construction_active(loadout)
                        else variant_gen_budget()
                    )
                    boost_board, boost_records, boost_results = (
                        search_consumable_score_boost(
                            self._searcher,
                            search_board,
                            loadout,
                            boost_rack,
                            baseline_score=baseline_score,
                            baseline_rank_score=baseline_rank,
                            time_budget=phase_budget(rack_boost_budget),
                            top_n=self.config.top_n_results,
                            rules=rules,
                            variant_gen_budget=boost_gen_budget,
                            solve_deadline=solve_deadline,
                        )
                    )
                    _accumulate_placement_timing()
                    if (
                        boost_results
                        and quest_rank_beats_baseline(
                            _result_rank_score(boost_results[0]),
                            baseline_rank,
                            loadout,
                        )
                    ):
                        search_board = boost_board
                        placement_records = boost_records
                        results = boost_results
                        baseline_score = boost_results[0].score
                        baseline_rank = _result_rank_score(boost_results[0])
                        self._searcher.validator.required_consumable_indices = (
                            mandatory_consumable_indices(
                                loadout, search_board, rules
                            )
                        )
                        print(
                            f"  Place consumables: "
                            f"{format_placement_instructions(boost_records)}",
                            flush=True,
                        )
                        print(
                            f"  Score improved with {len(boost_records)} consumable(s) "
                            f"({int(boost_results[0].score)} pts)",
                            flush=True,
                        )
                    elif boost_rack:
                        boost_stats = last_placement_search_stats()
                        best = boost_stats.best_screened_rank
                        threshold = boost_stats.threshold_rank
                        thresh_label = (
                            f"{int(threshold)}"
                            if threshold is not None
                            else f"{int(baseline_rank)}"
                        )
                        if boost_stats.variants_screened > 0 and best >= 0:
                            rack_slots = (
                                f" across {boost_stats.rack_slots_screened} rack tile(s)"
                                if boost_stats.rack_slots_screened > 0
                                else ""
                            )
                            print(
                                f"  Consumable boost: screened "
                                f"{boost_stats.variants_screened} variants"
                                f"{rack_slots}, "
                                f"best rank {int(best)} ≤ baseline {thresh_label} "
                                "— no placement adopted",
                                flush=True,
                            )
                        else:
                            print(
                                f"  Consumable boost: no variant beat baseline "
                                f"({boost_stats.variants_screened} screened, "
                                f"baseline rank {thresh_label})",
                                flush=True,
                            )
            elif (
                not sandy_auto_place
                and rack_placement_search_active(loadout, board, rules)
                and results
                and twinkle_swap_record is not None
                and solve_remaining() < 1.0
                and remaining_rack_tiles(loadout, board)
            ):
                print(
                    "  Consumable placement skipped — F8 budget exhausted "
                    "after Twinkle Toes",
                    flush=True,
                )
            if (
                has_target
                and grid_target > 0
                and not sandy_auto_place
                and solve_remaining() >= 1.0
                and target_rescue_worth_trying(
                    baseline_score, grid_target, consumable_rack_tiles(loadout, cactus_only=False), loadout=loadout
                )
            ):
                rescue_rack = consumable_rack_tiles(loadout, cactus_only=False)
                if rescue_rack:
                    if two_wrongs_active(loadout):
                        print(
                            f"  Target: {-grid_target} display "
                            f"({grid_target} remaining, best "
                            f"{int(display_score_for_quest(baseline_score, loadout))} "
                            "— trying consumables…)",
                            flush=True,
                        )
                    elif bullseye_active(loadout):
                        print(
                            f"  Target: {grid_target} pts exact "
                            f"(best {int(baseline_score)} — trying consumables…)",
                            flush=True,
                        )
                    else:
                        print(
                            f"  Target: {grid_target} pts (best {int(baseline_score)} "
                            "— trying consumables…)",
                            flush=True,
                        )
                    rescue_board, rescue_records, rescue_results = (
                        search_target_rescue(
                            self._searcher,
                            search_board,
                            loadout,
                            rescue_rack,
                            target=grid_target,
                            time_budget=phase_budget(rescue_budget),
                            top_n=self.config.top_n_results,
                            rules=rules,
                            variant_gen_budget=variant_gen_budget(),
                            solve_deadline=solve_deadline,
                        )
                    )
                    _accumulate_placement_timing()
                    if rescue_results and target_met(
                        float(rescue_results[0].score), float(grid_target), loadout
                    ):
                        search_board = rescue_board
                        placement_records = rescue_records
                        results = rescue_results
                        print(
                            f"  Place consumables: "
                            f"{format_placement_instructions(rescue_records)}",
                            flush=True,
                        )
                        print(
                            f"  Target met with {len(rescue_records)} consumable(s) "
                            f"({int(rescue_results[0].score)} pts)",
                            flush=True,
                        )
                    else:
                        print(
                            "  Target not reachable even with consumables",
                            flush=True,
                        )
                elif consumable_rack_count(loadout) > 0 and not rescue_rack:
                    print(
                        "  Warning: consumable rack not exported — rebuild melmod "
                        "and press F7 to enable target rescue.",
                        flush=True,
                    )
            elif (
                has_target
                and grid_target > 0
                and sandy_auto_place
                and solve_remaining() >= 1.0
                and target_rescue_worth_trying(
                    baseline_score,
                    grid_target,
                    consumable_rack_tiles(loadout, cactus_only=False),
                    loadout=loadout,
                )
            ):
                rescue_rack = consumable_rack_tiles(loadout, cactus_only=False)
                if rescue_rack:
                    if two_wrongs_active(loadout):
                        print(
                            f"  Target: {-grid_target} display "
                            f"({grid_target} remaining, best "
                            f"{int(display_score_for_quest(baseline_score, loadout))} "
                            "— trying extra consumables…)",
                            flush=True,
                        )
                    elif bullseye_active(loadout):
                        print(
                            f"  Target: {grid_target} pts exact "
                            f"(best {int(baseline_score)} — trying extra consumables…)",
                            flush=True,
                        )
                    else:
                        print(
                            f"  Target: {grid_target} pts (best {int(baseline_score)} "
                            "— trying extra consumables…)",
                            flush=True,
                        )
                    rescue_board, rescue_records, rescue_results = (
                        search_target_rescue(
                            self._searcher,
                            search_board,
                            loadout,
                            rescue_rack,
                            target=grid_target,
                            time_budget=phase_budget(rescue_budget),
                            top_n=self.config.top_n_results,
                            rules=rules,
                            variant_gen_budget=variant_gen_budget(),
                            solve_deadline=solve_deadline,
                        )
                    )
                    _accumulate_placement_timing()
                    if rescue_results and target_met(
                        float(rescue_results[0].score), float(grid_target), loadout
                    ):
                        search_board = rescue_board
                        placement_records = rescue_records
                        results = rescue_results
                        self._searcher.validator.required_consumable_indices = (
                            mandatory_consumable_indices(
                                loadout, search_board, self._scoring.rules
                            )
                        )
                        print(
                            f"  Place consumables: "
                            f"{format_placement_instructions(rescue_records)}",
                            flush=True,
                        )
                        print(
                            f"  Target met with {len(rescue_records)} consumable(s) "
                            f"({int(rescue_results[0].score)} pts)",
                            flush=True,
                        )
            if (
                has_target
                and grid_target > 0
                and bullseye_active(loadout)
                and results
                and not target_met(float(results[0].score), float(grid_target), loadout)
            ):
                best_score = int(results[0].score)
                print(
                    f"  Warning: no exact hit found; closest is {best_score} "
                    f"(target {grid_target}) — overshoot will bounce",
                    flush=True,
                )
            search_end_mono = time.monotonic()

            def _post_deadline_reached() -> bool:
                return time.monotonic() >= solve_deadline

            for result in results:
                if _post_deadline_reached():
                    dict_resolve_truncated = True
                    break
                result.dictionary_word = dictionary_word_for_path(
                    search_board,
                    result.path,
                    result.word,
                    loadout,
                    self._dictionary,
                    min_len=effective_min,
                    deadline_check=_post_deadline_reached,
                )
            post_search_sec = time.monotonic() - search_end_mono
            pre_search_sec = search_call_mono - search_started
            search_elapsed = time.monotonic() - search_started
            if dict_resolve_truncated:
                print(
                    "  Note: dictionary resolve truncated (F8 budget).",
                    flush=True,
                )
            timing = self._searcher.last_search_timing
            if timing is not None:
                pool_note = (
                    f", pool init {timing.pool_init_sec:.1f}s"
                    if timing.pool_init_sec > 0.05
                    else ""
                )
                total_score = timing.score_sec + timing.final_score_sec
                score_pct = (
                    f"{100.0 * total_score / timing.wall_sec:.0f}%"
                    if timing.wall_sec > 0
                    else "n/a"
                )
                worker_note = ""
                if timing.parallel_workers > 1:
                    worker_note = (
                        f", {timing.score_calls} parent pipeline calls "
                        "(worker scoring not counted)"
                    )
                else:
                    worker_note = f", {timing.score_calls} pipeline calls"
                fallback_note = (
                    " (serial fallback after parallel)"
                    if timing.parallel_serial_fallback
                    else ""
                )
                placement_parts: list[str] = []
                if placement_gen_sec > 0.001:
                    placement_parts.append(f"gen {placement_gen_sec:.1f}s")
                if placement_screen_sec > 0.001:
                    placement_parts.append(f"screen {placement_screen_sec:.1f}s")
                if placement_refine_sec > 0.001:
                    placement_parts.append(f"refine {placement_refine_sec:.1f}s")
                variant_note = (
                    f"placement {', '.join(placement_parts)}, "
                    if placement_parts
                    else ""
                )
                if timing.reserve_scaling_applied and timing.main_dfs_slice_sec > 0:
                    pool_note += f", main DFS {timing.main_dfs_slice_sec:.1f}s"
                overrun_note = ""
                if timing.refine_overrun_sec > 0.05:
                    overrun_note = (
                        f", refine overrun +{timing.refine_overrun_sec:.1f}s"
                        f" ({timing.refine_overrun_deferred} deferred)"
                    )
                over_budget = search_elapsed > search_budget + 0.5
                extra_timing = ""
                if over_budget and (
                    timing.refine_sec > 0.05
                    or timing.seed_sec > 0.05
                    or timing.tier2_phase2_deferred > 0
                    or timing.refine_overrun_sec > 0.05
                ):
                    extra_timing = (
                        f", refine {timing.refine_sec:.1f}s"
                        f", seed {timing.seed_sec:.1f}s"
                    )
                    if (
                        timing.tier2_phase2_deferred > 0
                        and timing.refine_sec > search_budget * 0.25
                    ):
                        extra_timing += (
                            f" (tier-2 deferred "
                            f"{timing.tier2_phase2_deferred}, "
                            f"refined {timing.tier2_phase2_calls})"
                        )
                print(
                    f"  Timing: {variant_note}"
                    f"dfs {timing.dfs_sec:.1f}s{fallback_note}, "
                    f"extend {timing.extend_sec:.1f}s, "
                    f"chess {timing.chess_sec:.1f}s, score {total_score:.1f}s"
                    f"{extra_timing}{overrun_note} "
                    f"({score_pct} of {timing.wall_sec:.1f}s{worker_note}{pool_note})",
                    flush=True,
                )
                from cursed_words_solver.search_parallel import (
                    drain_parallel_worker_errors,
                )

                for err in drain_parallel_worker_errors():
                    print(f"  Parallel worker error: {err}", flush=True)

            pred_trace: list | None = None
            export_warnings: list[str] = []
            capybara_stats = None
            saved_suggestion = False
            block_f8_save = False
            block_f8_reason: str | None = None
            if results and self._dictionary is not None:
                raw_count = len(results)
                results = filter_submittable_results(
                    search_board,
                    results,
                    loadout,
                    self._dictionary,
                    min_len=effective_min,
                    pipeline=self._scoring,
                    deadline_check=_post_deadline_reached,
                )
                if raw_count and not results:
                    print(
                        "  Warning: no playable dictionary word among search results.",
                        flush=True,
                    )
                elif len(results) < raw_count:
                    print(
                        "  Note: skipped unplayable candidate(s) "
                        "(no dictionary word on path).",
                        flush=True,
                    )
            if results:
                top = results[0]
                score_run_state = (
                    run_state_data if isinstance(run_state_data, dict) else None
                )
                f8_loadout = loadout
                historic_catchup_stale_note: str | None = None
                behind_disk_warn: str | None = None
                historic_sole_miss = sole_gather_miss_is_historic(snapshot) or (
                    snapshot.gather_missing == ["historic_words"]
                )
                if not gather_succeeded or historic_workflow_catchup_needed(snapshot):
                    if historic_sole_miss or "historic_words" in (
                        snapshot.gather_missing or []
                    ):
                        catchup_budget = min(
                            6.0, max(3.0, solve_remaining() * 0.15)
                        )
                        reexport_poll = F8_HISTORIC_CATCHUP_REEXPORT_POLL_SEC
                    else:
                        catchup_budget = min(2.0, max(1.0, solve_remaining() * 0.05))
                        reexport_poll = min(
                            F8_HISTORIC_CATCHUP_REEXPORT_POLL_SEC,
                            max(1.0, solve_remaining() * 0.1),
                        )
                    snapshot, catchup_note, historic_catchup_stale_note, behind_disk_warn = (
                        catchup_historic_gather_after_search(
                            snapshot,
                            rules=self._scoring.rules,
                            catchup_timeout_sec=catchup_budget,
                            reexport_poll_sec=reexport_poll,
                        )
                    )
                    if catchup_note:
                        print(f"  {catchup_note}", flush=True)
                    run_state_data = snapshot.run_state
                    score_run_state = (
                        run_state_data if isinstance(run_state_data, dict) else None
                    )
                    if snapshot.loadout is not None:
                        f8_loadout = snapshot.loadout
                        loadout = snapshot.loadout
                    gather_succeeded = (
                        snapshot.board_available
                        and snapshot.loadout is not None
                        and snapshot.extras_ready
                    )
                    if (
                        not gather_succeeded
                        and historic_sole_miss
                        and historic_words_gather_pending(snapshot)
                    ):
                        print(
                            "  Movie Camera needs prior-word export — "
                            "wait ~1s after your last submit, then F8 again.",
                            flush=True,
                        )
                num_placed = consumables_placed_for_scoring(
                    board,
                    search_board,
                    top.path,
                    placement_records or None,
                )
                score_loadout = loadout_after_consumable_placements(
                    f8_loadout, num_placed
                )
                score_word = effective_scoring_word(
                    search_board,
                    top.path,
                    top.word,
                    score_loadout,
                    self._dictionary,
                    min_len=effective_min,
                    pipeline=self._scoring,
                )
                pred_score, pred_bd, pred_trace, capybara_stats = (
                    self._score_top_with_capybara(
                        search_board,
                        top,
                        score_word,
                        score_loadout,
                    )
                )
                if (
                    capybara_stats is not None
                    and int(capybara_stats.min_score) != int(capybara_stats.max_score)
                ):
                    print(
                        f"  Capybara score range: "
                        f"{int(capybara_stats.min_score)}–"
                        f"{int(capybara_stats.max_score)} "
                        f"(EV {int(round(capybara_stats.ev))})",
                        flush=True,
                    )
                top.score = pred_score
                top.breakdown = pred_bd
                ms_uses = microscope_position_uses(
                    search_board,
                    top.path,
                    score_word,
                    flags=stamp_search_flags_mask(score_loadout),
                )
                if ms_uses:
                    ms_hint = format_microscope_position_hint(ms_uses)
                    top.breakdown = dict(top.breakdown or {})
                    top.breakdown["microscope_positions"] = ms_uses
                    top.breakdown["microscope_hint"] = ms_hint
                    pred_trace = list(pred_trace or [])
                    pred_trace.append(
                        {
                            "phase": "hint",
                            "rule_id": "microscope",
                            "detail": ms_hint,
                            "microscope_positions": ms_uses,
                        }
                    )
                # The displayed/tracked word must match the assignment that earned
                # pred_score. The per-result loop above picks the max physical-overlap
                # reading, but the score uses the max-scoring wildcard resolution
                # (e.g. "?k?e?" scores as "skies" 102, not "skyey" 27). Surface the
                # scored word so the player plays exactly what was predicted.
                if score_word and score_word.lower() != top.word.lower():
                    top.dictionary_word = score_word
                else:
                    top.dictionary_word = None
                export_diag = export_diagnostics_from_run_state(score_run_state)
                export_warnings = list(snapshot.warnings) + validate_run_state_for_scoring(
                    f8_loadout,
                    board=board,
                    raw=score_run_state,
                )
                capybara_warn = capybara_active_warning(
                    f8_loadout, self._scoring.rules
                )
                if capybara_warn:
                    export_warnings = list(export_warnings) + [capybara_warn]
                    scope = capybara_shuffle_scope(f8_loadout, self._scoring.rules)
                    if capybara_perm_count(f8_loadout, scope) > MAX_EXHAUSTIVE_PERMS:
                        sample_warn = capybara_sampling_warning(False, 256)
                        if sample_warn:
                            export_warnings.append(sample_warn)
                session_extras = solver_session_extras_from_loadout(f8_loadout)
                fresh_embed_run_state = load_run_state_raw()
                embed_state = embed_f8_snapshot(
                    snapshot,
                    scoring_loadout=score_loadout,
                    scoring_board=search_board,
                    fresh_run_state=(
                        fresh_embed_run_state
                        if isinstance(fresh_embed_run_state, dict)
                        else score_run_state
                    ),
                )
                embed_replay_mismatch = False
                if (
                    isinstance(embed_state, dict)
                    and capybara_stats is None
                    and score_word
                ):
                    replay_score = f8_embed_replay_score(
                        embed_state,
                        path=list(top.path),
                        word=score_word,
                        loadout=score_loadout,
                        pipeline=self._scoring,
                    )
                    if replay_score is not None and int(replay_score) != int(pred_score):
                        embed_replay_mismatch = True
                        export_warnings = list(export_warnings) + [
                            f"F8 embed replay mismatch: predicted {int(pred_score)} "
                            f"vs embed replay {replay_score}"
                        ]
                f8_extras = (
                    embed_state.get("extras")
                    if isinstance(embed_state, dict)
                    and isinstance(embed_state.get("extras"), dict)
                    else (f8_loadout.extras if f8_loadout is not None else None)
                )
                post_catchup_workflow_warns = run_state_historic_stale_warnings(
                    f8_loadout.extras
                    if f8_loadout is not None
                    and isinstance(f8_loadout.extras, dict)
                    else None
                )
                grid_bleed_warn = grid_transition_workflow_bleed_warning(
                    f8_loadout.extras
                    if f8_loadout is not None
                    and isinstance(f8_loadout.extras, dict)
                    else None
                )
                submit_projected_extras = None
                if (
                    f8_loadout is not None
                    and isinstance(f8_loadout.extras, dict)
                ):
                    from cursed_words_solver.loadout import (
                        project_workflow_extras_for_f8_embed,
                        reconcile_encounter_historic_for_scoring,
                    )

                    submit_projected_extras = copy.deepcopy(f8_loadout.extras)
                    reconcile_encounter_historic_for_scoring(
                        submit_projected_extras, board=search_board
                    )
                    project_workflow_extras_for_f8_embed(
                        submit_projected_extras, board=search_board
                    )
                scoring_extras_for_block = (
                    f8_loadout.extras
                    if f8_loadout is not None
                    and isinstance(f8_loadout.extras, dict)
                    else None
                )
                block_f8_save, block_f8_reason = f8_should_block_save(
                    gather_succeeded=gather_succeeded,
                    gather_missing=snapshot.gather_missing or None,
                    historic_catchup_stale_note=historic_catchup_stale_note,
                    behind_disk_warn=behind_disk_warn,
                    hist_stale_note=f8_historic_stale_after_merge_warning(
                        f8_loadout.extras
                        if f8_loadout is not None
                        and isinstance(f8_loadout.extras, dict)
                        else None
                    ),
                    empty_hist_warn=empty_historic_on_later_grid_warning(
                        f8_loadout.extras
                        if f8_loadout is not None
                        and isinstance(f8_loadout.extras, dict)
                        else None,
                        loadout=score_loadout,
                        board=search_board,
                    ),
                    workflow_stale_warn=(
                        post_catchup_workflow_warns[0]
                        if post_catchup_workflow_warns
                        else None
                    ),
                    grid_bleed_warn=grid_bleed_warn,
                    mid_solve_grid_advanced=self._mid_solve_grid_advanced,
                    loadout=score_loadout,
                    board=search_board,
                    path=top.path,
                    f8_extras=f8_extras if isinstance(f8_extras, dict) else None,
                    submit_projected_extras=submit_projected_extras,
                    scoring_extras=scoring_extras_for_block,
                    dictionary=self._dictionary,
                    scoring_word=score_word,
                    min_len=effective_min,
                    pipeline=self._scoring,
                )
                gather_status = {
                    "f8_export_acked": snapshot.f8_export_acked,
                    "extras_ready": snapshot.extras_ready,
                    "gather_missing": list(snapshot.gather_missing),
                }
                if not block_f8_save and embed_replay_mismatch:
                    block_f8_save = True
                    block_f8_reason = "embed_replay_mismatch"
                if not block_f8_save:
                    save_last_suggestion(
                        board=search_board,
                        loadout=score_loadout,
                        result=top,
                        predicted_trace=pred_trace,
                        run_state_snapshot=embed_state,
                        dictionary=self._dictionary,
                        min_len=effective_min,
                        scoring_word=score_word,
                        export_diagnostics=export_diag,
                        export_warnings=export_warnings,
                        workflow_warnings=workflow_warnings,
                        gather_status=gather_status,
                        solver_session_extras=session_extras,
                        consumable_placements=placement_records or None,
                        twinkle_toes_swap=twinkle_swap_record,
                        score_nondeterministic=capybara_stats is not None,
                        predicted_score_min=(
                            int(capybara_stats.min_score) if capybara_stats else None
                        ),
                        predicted_score_max=(
                            int(capybara_stats.max_score) if capybara_stats else None
                        ),
                        capybara_perm_count=(
                            capybara_stats.perm_count if capybara_stats else None
                        ),
                        capybara_exhaustive=(
                            capybara_stats.exhaustive if capybara_stats else None
                        ),
                    )
                    saved_suggestion = True
                    self._last_invalidation_reason = None
                    self._active_suggestion_session = session_from_snapshot(snapshot)
                    if self._active_suggestion_session is None and isinstance(
                        score_run_state, dict
                    ):
                        from cursed_words_solver.f8_snapshot import F8Snapshot

                        self._active_suggestion_session = session_from_snapshot(
                            F8Snapshot(
                                run_state=score_run_state,
                                board=search_board,
                                loadout=f8_loadout,
                                board_available=True,
                            )
                        )
                else:
                    save_blocked_suggestion(
                        board=search_board,
                        loadout=score_loadout,
                        result=top,
                        predicted_trace=pred_trace,
                        run_state_snapshot=embed_state,
                        scoring_word=score_word,
                        block_reason=block_f8_reason or "unknown",
                        export_diagnostics=export_diag,
                        consumable_placements=placement_records or None,
                        twinkle_toes_swap=twinkle_swap_record,
                    )
                    self._active_suggestion_session = session_from_snapshot(snapshot)
                    if self._active_suggestion_session is None and isinstance(
                        score_run_state, dict
                    ):
                        from cursed_words_solver.f8_snapshot import F8Snapshot

                        self._active_suggestion_session = session_from_snapshot(
                            F8Snapshot(
                                run_state=score_run_state,
                                board=search_board,
                                loadout=f8_loadout,
                                board_available=True,
                            )
                        )
                for warn in export_warnings:
                    print(f"  Export warning: {warn}", flush=True)

            self._save_debug(
                board_img,
                board,
                results,
                board_source=board_source,
                money_source=money_source,
                top_predicted_trace=pred_trace,
                loadout=loadout,
                run_state_data=run_state_data,
                export_warnings=export_warnings if results else None,
                workflow_warnings=workflow_warnings if results else None,
                gather_status={
                    "f8_export_acked": snapshot.f8_export_acked,
                    "extras_ready": snapshot.extras_ready,
                    "gather_missing": list(snapshot.gather_missing),
                }
                if results
                else None,
            )
            print(f"Board source: {board_source}", flush=True)

            if results:
                top = results[0]
                timing_note = ""
                if timing is not None and search_elapsed > search_budget + 0.5:
                    core_sec = timing.wall_sec
                    timing_note = (
                        f" (budget {search_budget:.0f}s; "
                        f"pre {pre_search_sec:.1f}s + core {core_sec:.1f}s "
                        f"+ post {post_search_sec:.1f}s)"
                    )
                done_msg = (
                    f"Done in {search_elapsed:.1f}s{timing_note}. "
                    f"Best: {format_suggestion_word(top)} "
                    f"({format_result_score_display(top, loadout)})"
                )
                if (
                    block_f8_save
                    and block_f8_reason
                    and str(block_f8_reason).startswith("gather_incomplete")
                ):
                    done_msg = (
                        f"Preview only (overlay disabled): {done_msg}"
                    )
                if twinkle_swap_record and placement_records:
                    done_msg += (
                        " — swap tiles first, place consumables, "
                        "then trace the highlighted path"
                    )
                elif twinkle_swap_record:
                    done_msg += (
                        " — swap tiles first, then trace the highlighted path"
                    )
                elif placement_records:
                    done_msg += (
                        " — place consumables first, then trace the highlighted path"
                    )
                print(done_msg, flush=True)
                effects = (top.breakdown or {}).get("pipeline", {}).get("effects")
                if effects:
                    print(f"  Score effects: {'; '.join(str(e) for e in effects)}", flush=True)
                ms_hint = (top.breakdown or {}).get("microscope_hint")
                if ms_hint:
                    print(f"  {ms_hint}", flush=True)
                if saved_suggestion:
                    print(
                        "  Wrote last_suggestion.json for melmod scoring capture.",
                        flush=True,
                    )
                elif block_f8_save:
                    print(
                        f"  Did not write last_suggestion.json ({block_f8_reason}).",
                        flush=True,
                    )
            else:
                clear_last_suggestion()
                self._active_suggestion_session = None
                print(
                    f"Done in {search_elapsed:.1f}s. No valid words found.",
                    flush=True,
                )

            warnings = self._overlay_warnings(board, unmapped, loadout=loadout)
            if results and encounter_mode_from_run_state(run_state_data) == "encounter":
                from cursed_words_solver.grid_reroll_advisor import (
                    format_grid_reroll_reason,
                    should_reroll_grid,
                )

                grid_reroll = parse_encounter_grid_reroll(run_state_data)
                best_score = results[0].score
                if should_reroll_grid(
                    best_score,
                    loadout,
                    grid_reroll,
                    gap_ratio=self.config.grid_reroll_gap_ratio,
                ):
                    reason = format_grid_reroll_reason(
                        best_score,
                        loadout,
                        gap_ratio=self.config.grid_reroll_gap_ratio,
                    )
                    print(f"  Grid reroll recommended ({reason})", flush=True)
                    reroll_warn = (
                        "<span style='color:#fa0;font-weight:bold'>Reroll Grid</span>"
                    )
                    warnings = (
                        f"{warnings}<br>{reroll_warn}" if warnings else reroll_warn
                    )
            block_warn_html = format_f8_block_reason_html(block_f8_reason)
            if block_warn_html:
                warnings = (
                    f"{warnings}<br>{block_warn_html}" if warnings else block_warn_html
                )
            highlight = (
                self.config.show_board_highlight
                and self._overlay_regions.board.is_valid()
                and bool(results)
                and not (
                    block_f8_save
                    and block_f8_reason
                    and str(block_f8_reason).startswith("gather_incomplete")
                )
            )
            trusted = not block_f8_save if results else True
            if self._solve_cancelled(my_gen):
                return
            self._bridge.solve_finished.emit(
                _SolveUIUpdate(
                    board=search_board,
                    results=results,
                    board_bgr=board_img,
                    warnings_html=warnings,
                    on_game_highlight=highlight,
                    consumable_placements=placement_records or None,
                    twinkle_toes_swap=twinkle_swap_record,
                    melmod_board_fingerprint=melmod_board_fp,
                    melmod_loadout_fingerprint=melmod_loadout_fp,
                    trusted_suggestion=trusted,
                    block_reason=block_f8_reason,
                    loadout=loadout,
                )
            )
        except Exception as exc:
            if self._shutting_down and isinstance(exc, RuntimeError) and (
                "cannot schedule new futures after shutdown" in str(exc)
            ):
                pass
            else:
                err = traceback.format_exc()
                print(err)
                DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                (DEBUG_DIR / "last_error.txt").write_text(err, encoding="utf-8")
        finally:
            restart = self._solve_generation != my_gen
            self._busy = False
            self._solve_active = False
            self._solve_gather_board_fp = ""
            self._solve_gather_grid = 0
            if restart and not self._shutting_down:
                threading.Thread(target=self._solve_worker, daemon=True).start()

    def _detect_loadout_source(self) -> str:
        path = CONFIG_DIR / "run_state.json"
        if not path.exists():
            return "missing"
        from cursed_words_solver.loadout import _read_run_state_json

        data = _read_run_state_json(path)
        if data is None:
            return "invalid"
        board = data.get("board")
        if isinstance(board, dict) and len(board.get("tiles", [])) == 25:
            return "mod"
        loadout = load_run_state()
        if loadout is None:
            return "invalid"
        if data.get("character") == "Example":
            return "template"
        if data.get("extras", {}).get("pin_effect") or len(data.get("stickers", [])) > 2:
            return "mod"
        if loadout.stickers or loadout.stamps:
            return "manual"
        if data.get("character") and data.get("character") != "Example":
            return "mod"
        return "file"

    def _score_top_with_capybara(
        self,
        board: Board,
        top: WordResult,
        score_word: str,
        loadout: Loadout,
    ) -> tuple[float, dict, list, object | None]:
        from cursed_words_solver.rules.capybara_scoring import (
            score_capybara_with_trace,
        )
        from cursed_words_solver.rules.scoring_order import capybara_shuffles_loadout

        if capybara_shuffles_loadout(loadout, self._scoring.rules):
            pred_score, pred_bd, pred_trace, stats = score_capybara_with_trace(
                self._scoring,
                board,
                top.path,
                score_word,
                loadout,
                self._scoring.rules,
            )
            return pred_score, pred_bd, pred_trace, stats
        pred_score, pred_bd, pred_trace = self._scoring.score_with_trace(
            board, top.path, score_word, loadout
        )
        return pred_score, pred_bd, pred_trace, None

    def _overlay_warnings(
        self,
        board,
        unmapped: list[str],
        *,
        loadout: Loadout | None = None,
    ) -> str:
        del board
        lines: list[str] = []
        if loadout is not None:
            from cursed_words_solver.rules.capybara_scoring import (
                capybara_active_warning,
            )

            capybara_warn = capybara_active_warning(loadout, self._scoring.rules)
            if capybara_warn:
                lines.append(capybara_warn)
        if unmapped:
            lines.append(
                f"Unmapped rules: {', '.join(unmapped[:4])}"
                f"{'…' if len(unmapped) > 4 else ''}"
            )
        return "<br>".join(lines)

    def _save_debug(
        self,
        img,
        board,
        results,
        *,
        board_source: str = "melmod",
        money_source: str = "mod",
        top_predicted_trace: list | None = None,
        loadout: Loadout | None = None,
        run_state_data: dict | None = None,
        export_warnings: list[str] | None = None,
        workflow_warnings: list[str] | None = None,
        gather_status: dict | None = None,
    ) -> None:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if img is not None:
            save_debug_image(img, DEBUG_DIR / f"board_{ts}.png")
        board_fp = ""
        loadout_fp = ""
        if run_state_data is not None:
            from cursed_words_solver.fingerprints import fingerprints_from_run_state

            board_fp, loadout_fp = fingerprints_from_run_state(run_state_data)
        payload = {
            "board_source": board_source,
            "money_source": money_source,
            "board_fingerprint": board_fp,
            "loadout_fingerprint": loadout_fp,
            "export_diagnostics": export_diagnostics_from_run_state(run_state_data),
            "export_warnings": list(export_warnings or []),
            "workflow_warnings": list(workflow_warnings or []),
            "gather_status": dict(gather_status or {}),
            "extras": dict(loadout.extras) if loadout is not None else {},
            "solver_session_extras": solver_session_extras_from_loadout(loadout),
            "grid": format_board_grid(board).split("\n"),
            "tiles": [
                {
                    "row": t.row,
                    "col": t.col,
                    "char": t.char,
                    "letter": t.letter,
                    "base_score": t.base_score,
                    "color": t.color.value,
                    "curse": t.curse.value,
                }
                for t in board.flat
            ],
            "results": [
                {
                    "word": r.word,
                    "score": r.score,
                    "path": r.path,
                    "predicted_trace": top_predicted_trace if i == 0 else None,
                }
                for i, r in enumerate(results)
            ],
        }
        (DEBUG_DIR / f"parse_{ts}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def _run_edit_loadout(self) -> None:
        dlg = LoadoutDialog(load_run_state())
        if dlg.exec():
            save_loadout(dlg.get_loadout())
            self._loadout_source = "manual"

    def _run_recalibrate(self) -> None:
        if self._busy:
            print("Cannot recalibrate while a solve is running.", flush=True)
            return
        self._calibrating = True
        try:
            print("Recalibration started (F10)...", flush=True)
            self._hide_overlays()
            self.config = run_calibration_wizard(self.config)
            self._finish_calibration("Recalibration complete")
            QMessageBox.information(
                None,
                "Recalibrated",
                "Board and rack regions updated.\n"
                f"Check {DEBUG_DIR / 'calibration_preview.png'} to verify the capture.",
            )
        finally:
            self._calibrating = False


def main() -> None:
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "validate-path":
            from cursed_words_solver.debug_path import cli_validate_path

            sys.exit(cli_validate_path(sys.argv[2:]))
        if cmd == "explain":
            from cursed_words_solver.debug_path import cli_explain

            sys.exit(cli_explain(sys.argv[2:]))
        if cmd == "diagnose":
            from cursed_words_solver.diagnose import cli_diagnose

            sys.exit(cli_diagnose(sys.argv[2:]))
    parser = argparse.ArgumentParser(
        description="Cursed Words solver (requires MelonLoader companion mod)"
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run board-region calibration wizard on startup",
    )
    parser.add_argument("--hotkey", default=None, help="Override hotkey (e.g. f8)")
    args = parser.parse_args()

    config = AppConfig.load()
    if args.hotkey:
        config.hotkey = args.hotkey

    app = SolverApp(config, calibrate=args.calibrate)
    sys.exit(app.run())


if __name__ == "__main__":
    main()
