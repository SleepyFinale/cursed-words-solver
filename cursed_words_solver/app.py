"""Main application: melmod-backed hotkey solver with overlay."""

from __future__ import annotations

import argparse
import atexit
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

from cursed_words_solver.capture import capture_region, save_debug_image
from cursed_words_solver.fingerprints import (
    board_fingerprint,
    fingerprints_from_run_state,
)
from cursed_words_solver.config import (
    CONFIG_DIR,
    DEBUG_DIR,
    AppConfig,
    describe_wordlist,
    resolve_wordlist,
)
from cursed_words_solver.suggestion import (
    clear_last_suggestion,
    clear_stale_last_suggestion_if_context_changed,
    clear_stale_last_suggestion_if_fingerprint_changed,
    clear_stale_last_suggestion_if_loadout_changed,
    dictionary_word_for_path,
    effective_scoring_word,
    format_suggestion_word,
    f8_prior_suggestion_stale_note,
    poll_invalidate_last_suggestion,
    empty_historic_on_later_grid_warning,
    run_state_historic_stale_warnings,
    save_last_suggestion,
)
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, WordResult
from cursed_words_solver.board_display import format_board_grid
from cursed_words_solver.loadout import (
    bicycle_extras_stale_warning,
    format_loadout_summary,
    load_run_state,
    load_run_state_raw,
    melmod_board_available,
    melmod_install_hint,
    describe_f8_historic_catchup,
    f8_historic_stale_after_merge_warning,
    merge_encounter_historic_for_f8_snapshot,
    merge_loadout_with_board,
    neapolitan_extras_stale_warning,
    mod_money_from_run_state,
    export_diagnostics_from_run_state,
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
    solver_session_extras_from_loadout,
    validate_run_state_for_scoring,
    sanitize_run_state_snapshot_for_f8,
    save_loadout,
    save_run_state_template,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.boss_effects import (
    boss_area_number,
    boss_word_constraints,
)
from cursed_words_solver.rules.rule_lookup import boss_display_name, resolve_rule_id
from cursed_words_solver.consumable_placement import (
    consumable_placement_count_on_board,
    consumable_rack_tiles,
    format_placement_instructions,
    last_placement_search_stats,
    loadout_after_consumable_placements,
    mahjong_rack_placement_active,
    mandatory_consumable_indices,
    remaining_rack_tiles,
    sandy_placement_search_active,
    sandy_requires_rack_export,
    wait_for_rack_export,
    search_consumable_score_boost,
    search_target_rescue,
    search_with_consumable_placements,
    target_rescue_worth_trying,
)
from cursed_words_solver.rules.scoring_conditions import (
    consumable_rack_count,
    placed_consumable_indices,
    target_score_from_loadout,
)
from cursed_words_solver.rules.chess_tiles import missing_chess_color_warnings
from cursed_words_solver.search import WordSearcher
from cursed_words_solver.ui.board_highlight import BoardHighlightOverlay
from cursed_words_solver.ui.calibrate import run_calibration_wizard
from cursed_words_solver.ui.loadout_dialog import LoadoutDialog
from cursed_words_solver.ui.overlay import ResultOverlay


@dataclass(frozen=True)
class _SolveUIUpdate:
    """Payload for posting solve results to the Qt main thread."""

    board: Board
    results: list[WordResult]
    board_bgr: np.ndarray | None
    warnings_html: str
    on_game_highlight: bool
    consumable_placements: list | None = None
    # Fingerprints from run_state.json at solve time (melmod); used to detect shop/round end.
    melmod_board_fingerprint: str | None = None
    melmod_loadout_fingerprint: str | None = None


class _HotkeyBridge(QObject):
    """Marshal keyboard hook callbacks onto the Qt main thread."""

    recalibrate = Signal()
    edit_loadout = Signal()
    hide_overlay = Signal()
    quit_app = Signal()
    solve_finished = Signal(object)


class SolverApp:
    def __init__(self, config: AppConfig, calibrate: bool = False) -> None:
        self.config = config
        self.calibrate = calibrate
        self.app = QApplication(sys.argv)
        self.overlay = ResultOverlay()
        self.board_highlight = BoardHighlightOverlay()
        self._highlight_board_fingerprint: str | None = None
        self._highlight_loadout_fingerprint: str | None = None
        self._highlight_watch_run_state = False
        self._last_invalidation_reason: str | None = None
        self._loadout_cache = load_run_state()
        self._loadout_source = self._detect_loadout_source()
        self._scoring = ScoringPipeline()
        self._dictionary: WordDictionary | None = None
        self._searcher: WordSearcher | None = None
        self._busy = False
        self._solve_active = False
        self._calibrating = False
        self._hotkey_handle = None
        self._shutting_down = False
        self._bridge = _HotkeyBridge()
        self._bridge.recalibrate.connect(self._run_recalibrate)
        self._bridge.edit_loadout.connect(self._run_edit_loadout)
        self._bridge.hide_overlay.connect(self._hide_overlays)
        self._bridge.quit_app.connect(self._shutdown)
        self._bridge.solve_finished.connect(self._apply_solve_ui)
        self.overlay.request_quit.connect(self._shutdown)
        atexit.register(keyboard.unhook_all)
        atexit.register(self._shutdown_search_pool)

    def _ensure_solver(self) -> bool:
        if self._dictionary is None:
            wl_path = resolve_wordlist(self.config.wordlist)
            self._dictionary = WordDictionary(wl_path)
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

    def run(self) -> int:
        if self.calibrate or not self.config.board_region.is_valid():
            QMessageBox.information(
                None,
                "Calibration",
                "Select the 5×5 board region on screen for green path highlights.",
            )
            self.config = run_calibration_wizard(self.config)
            self._finish_calibration("Calibration complete")

        if not self.calibrate:
            br = self.config.board_region
            if br.is_valid():
                print(
                    f"Board region: {br.width}×{br.height} at ({br.x},{br.y}).",
                    flush=True,
                )
            else:
                print(
                    "Board region not set — press F10 to calibrate for on-screen highlights.",
                    flush=True,
                )

        board_data = load_run_state_raw()
        if not melmod_board_available(board_data):
            QMessageBox.warning(
                None,
                "MelonLoader mod required",
                melmod_install_hint()
                + "\n\nF8 will not solve until run_state.json contains a board (press F7 in-game).",
            )

        wl_path = resolve_wordlist(self.config.wordlist)
        print(
            f"Word list: {describe_wordlist(wl_path, self.config.wordlist)}",
            flush=True,
        )
        if not (CONFIG_DIR / "run_state.json").exists():
            save_run_state_template()
        self._reload_run_state()

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
        print(
            f"Loadout ({self._loadout_source}): {format_loadout_summary(self._loadout_cache)}",
            flush=True,
        )
        scoring, total, grid_only, unmapped = self._scoring.loadout_mapping_summary(
            self._loadout_cache
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
                "  Tip: F7 works in the game (MelonLoader console), not in this terminal. "
                "Start a run, press F7, then F8 here.",
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
                "press F7 during a round with tiles visible.",
                flush=True,
            )
        if not self.config.board_region.is_valid():
            print(
                "Press F10 to calibrate the board region for green path highlights.",
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
        self.app.quit()

    def _hide_overlays(self) -> None:
        self.overlay.hide()
        self._clear_highlight_state()
        self._highlight_watch_run_state = False

    def _clear_highlight_state(self) -> None:
        self.board_highlight.clear()
        self._highlight_board_fingerprint = None
        self._highlight_loadout_fingerprint = None
        self._highlight_watch_run_state = False

    def _poll_run_state_stale(self) -> None:
        """Invalidate stale F8 suggestions and drop highlights when run_state drifts."""
        if self._solve_active:
            return

        from cursed_words_solver.config import LAST_SUGGESTION_PATH
        from cursed_words_solver.fingerprints import fingerprints_from_run_state

        data = load_run_state_raw()
        extras = data.get("extras") if isinstance(data, dict) else None
        board_fp = ""
        loadout_fp = ""
        if data:
            board_fp, loadout_fp = fingerprints_from_run_state(data)

        if LAST_SUGGESTION_PATH.exists():
            from cursed_words_solver.suggestion import (
                fingerprint_invalidate_suppressed_for_consumable_placement,
            )

            placement_in_progress = fingerprint_invalidate_suppressed_for_consumable_placement(
                board_fp
            )
            if placement_in_progress:
                self._last_invalidation_reason = None
                self.overlay.clear_stale_notice()
            reason = poll_invalidate_last_suggestion(
                extras if isinstance(extras, dict) else None,
                current_board_fp=board_fp,
                current_loadout_fp=loadout_fp,
                search_budget_sec=self.config.search_time_budget_sec,
            )
            if reason and reason != self._last_invalidation_reason:
                self._last_invalidation_reason = reason
                self._clear_highlight_state()
                self.overlay.show_stale_notice(
                    "Suggestion cleared — press F8 again before submitting."
                )
                print(f"  Suggestion cleared — {reason}", flush=True)
            elif reason is None:
                self._last_invalidation_reason = None

        self._maybe_clear_stale_highlights()

    def _maybe_clear_stale_highlights(self) -> None:
        """Drop on-board path when melmod reports a new round, shop, or missing board."""
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
        if current_board_fp != self._highlight_board_fingerprint:
            from cursed_words_solver.suggestion import (
                fingerprint_invalidate_suppressed_for_consumable_placement,
            )

            if not fingerprint_invalidate_suppressed_for_consumable_placement(
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
        self.overlay.show_results(
            update.board,
            update.results,
            board_bgr=update.board_bgr,
            warnings_html=update.warnings_html,
            on_game_highlight=update.on_game_highlight,
            consumable_placements=update.consumable_placements,
        )
        if update.on_game_highlight and self.config.board_region.is_valid():
            if update.melmod_board_fingerprint is not None:
                self._highlight_board_fingerprint = update.melmod_board_fingerprint
                self._highlight_loadout_fingerprint = update.melmod_loadout_fingerprint
                self._highlight_watch_run_state = True
            else:
                self._highlight_board_fingerprint = board_fingerprint(update.board)
                self._highlight_loadout_fingerprint = None
                self._highlight_watch_run_state = False
            self.board_highlight.show_path(
                self.config.board_region,
                update.results[0].path,
                update.board,
                placements=update.consumable_placements,
            )
        else:
            self._clear_highlight_state()

    def _finish_calibration(self, prefix: str) -> None:
        br = self.config.board_region
        if not br.is_valid():
            return
        print(
            f"{prefix}. Board region: {br.width}×{br.height} at ({br.x},{br.y}).",
            flush=True,
        )
        self._save_calibration_preview()

    def _save_calibration_preview(self) -> None:
        if not self.config.board_region.is_valid():
            return
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            img = capture_region(self.config.board_region)
            path = DEBUG_DIR / "calibration_preview.png"
            save_debug_image(img, path)
            print(f"Capture preview saved: {path}", flush=True)
        except Exception as e:
            print(f"Could not save capture preview: {e}", flush=True)

    def _on_hotkey_pressed(self) -> None:
        if self._busy or self._calibrating:
            return
        threading.Thread(target=self._solve_worker, daemon=True).start()

    def _solve_worker(self) -> None:
        self._busy = True
        self._solve_active = True
        unmapped: list[str] = []
        board_source = "melmod"
        money_source = "mod"
        try:
            print("Solve started...", flush=True)

            self._reload_run_state()
            run_state_data = load_run_state_raw()

            mod_money = mod_money_from_run_state(run_state_data)
            prepared_state = (
                prepare_run_state_dict_for_scoring(run_state_data)
                if run_state_data
                else None
            )
            board = parse_board_from_run_state(prepared_state)
            board_img = None

            if board is None:
                print(melmod_install_hint(), flush=True)
                if run_state_data is None:
                    print(
                        "Could not read run_state.json (file locked or invalid JSON). "
                        "Press F7 in-game, wait a moment, then press F8 again.",
                        flush=True,
                    )
                elif not isinstance(run_state_data.get("board"), dict):
                    print(
                        "No board in run_state.json — press F7 in-game during a round.",
                        flush=True,
                    )
                else:
                    n = len(run_state_data.get("board", {}).get("tiles", []))
                    print(
                        f"Board export invalid ({n} tiles, need 25) — press F7 again.",
                        flush=True,
                    )
                return

            if not self._ensure_solver():
                print("Solver not ready (dictionary failed to load).", flush=True)
                return

            print("Board from melmod (run_state.json).", flush=True)
            run_extras = (
                run_state_data.get("extras")
                if isinstance(run_state_data, dict)
                else None
            )
            for warn in run_state_historic_stale_warnings(
                run_extras if isinstance(run_extras, dict) else None
            ):
                print(f"  Warning: {warn}", flush=True)
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
            if self.config.board_region.is_valid():
                try:
                    board_img = capture_region(self.config.board_region)
                    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                    save_debug_image(board_img, DEBUG_DIR / "last_board.png")
                except Exception as e:
                    print(f"Board capture skipped: {e}", flush=True)
            elif self.config.show_board_highlight:
                print(
                    "Press F10 to calibrate board region for on-screen path highlights.",
                    flush=True,
                )

            search_budget = self.config.search_time_budget_sec
            search_started = time.monotonic()
            solve_deadline = search_started + search_budget
            placement_variant_sec = 0.0

            def solve_remaining() -> float:
                return max(0.0, solve_deadline - time.monotonic())

            def phase_budget(share: float) -> float:
                return min(share, solve_remaining())

            def variant_gen_budget() -> float:
                return min(2.0, solve_remaining() * 0.05)
            loadout = merge_loadout_with_board(
                self._loadout_cache,
                board.money,
                mod_money=mod_money if mod_money > 0 else None,
            )
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
                        "cached": "cached fallback",
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
                            "press F7 in-game or submit a word so melmod can capture "
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
            if total:
                msg = f"  Rules: {scoring}/{total} affect score"
                if grid_only:
                    msg += f" ({grid_only} grid-only)"
                print(msg, flush=True)
            if unmapped:
                print(f"  Unmapped: {', '.join(unmapped[:6])}", flush=True)
            if board_source == "melmod" and not (loadout.boss_id or loadout.boss_name):
                print(
                    "  Boss not in run_state.json — press F7 in-game; "
                    "rebuild melmod if you are fighting a boss.",
                    flush=True,
                )
            placed_consumables = placed_consumable_indices(board)
            mandatory = mandatory_consumable_indices(
                loadout, board, self._scoring.rules
            )

            def _reload_solve_loadout() -> Loadout:
                self._reload_run_state()
                fresh_money = mod_money_from_run_state(load_run_state_raw())
                return merge_loadout_with_board(
                    self._loadout_cache,
                    board.money,
                    mod_money=fresh_money if fresh_money > 0 else None,
                )

            loadout = wait_for_rack_export(
                loadout,
                board,
                self._scoring.rules,
                reload_loadout=_reload_solve_loadout,
            )
            if sandy_requires_rack_export(loadout, board, self._scoring.rules):
                print(
                    "  Sandy Saguaro: consumable rack not in run_state yet — "
                    "wait a moment and press F8 again, or press F7 in-game "
                    "to force export.",
                    flush=True,
                )
                clear_last_suggestion()
                return
            sandy_auto_place = sandy_placement_search_active(
                loadout, board, self._scoring.rules
            )
            rack_tiles: list = []
            placement_records: list = []
            has_target = "target_score" in (loadout.extras or {})
            grid_target = target_score_from_loadout(loadout) if has_target else 0
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
            effective_min = max(1, constraints.min_len)
            effective_max = min(board_max_len, constraints.max_len)
            if effective_max < effective_min:
                effective_max = effective_min
            self._searcher.min_len = effective_min
            self._searcher.max_len = effective_max
            self._searcher.time_budget = phase_budget(search_budget)
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
                area = boss_area_number(loadout)
                search_msg += f", Boss: {boss_label} (Area {area})"
                if loadout.extras.get("boss_cursed"):
                    search_msg += " (cursed)"
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
            mahjong_boost_budget = search_budget * 0.3
            rules = self._scoring.rules
            if sandy_auto_place and rack_tiles and solve_remaining() >= 1.0:
                search_board, placement_records, results = (
                    search_with_consumable_placements(
                        self._searcher,
                        board,
                        loadout,
                        rack_tiles,
                        time_budget=phase_budget(search_budget),
                        top_n=self.config.top_n_results,
                        rules=rules,
                    )
                )
                placement_variant_sec += last_placement_search_stats().variant_gen_sec
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
                    print(
                        f"  Target: {grid_target} pts (best {int(results[0].score)})",
                        flush=True,
                    )
            elif solve_remaining() >= 0.5:
                results = self._searcher.find_best_words(
                    board,
                    loadout=loadout,
                    top_n=self.config.top_n_results,
                )
            else:
                results = []

            baseline_score = results[0].score if results else 0.0
            if (
                not sandy_auto_place
                and mahjong_rack_placement_active(loadout, board, rules)
                and results
                and solve_remaining() >= 1.0
            ):
                boost_rack = remaining_rack_tiles(loadout, board)
                if boost_rack:
                    print(
                        f"  Mahjong: {len(boost_rack)} consumable(s) on rack "
                        "— simulating placements…",
                        flush=True,
                    )
                    boost_board, boost_records, boost_results = (
                        search_consumable_score_boost(
                            self._searcher,
                            board,
                            loadout,
                            boost_rack,
                            baseline_score=baseline_score,
                            time_budget=phase_budget(mahjong_boost_budget),
                            top_n=self.config.top_n_results,
                            rules=rules,
                            variant_gen_budget=variant_gen_budget(),
                        )
                    )
                    placement_variant_sec += (
                        last_placement_search_stats().variant_gen_sec
                    )
                    if boost_results and boost_results[0].score > baseline_score:
                        search_board = boost_board
                        placement_records = boost_records
                        results = boost_results
                        baseline_score = boost_results[0].score
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
            if (
                has_target
                and grid_target > 0
                and baseline_score < grid_target
                and not sandy_auto_place
                and solve_remaining() >= 1.0
            ):
                rescue_rack = consumable_rack_tiles(loadout, cactus_only=False)
                if target_rescue_worth_trying(
                    baseline_score, grid_target, rescue_rack
                ):
                    print(
                        f"  Target: {grid_target} pts (best {int(baseline_score)} "
                        "— trying consumables…)",
                        flush=True,
                    )
                    rescue_board, rescue_records, rescue_results = (
                        search_target_rescue(
                            self._searcher,
                            board,
                            loadout,
                            rescue_rack,
                            target=grid_target,
                            time_budget=phase_budget(rescue_budget),
                            top_n=self.config.top_n_results,
                            rules=rules,
                            variant_gen_budget=variant_gen_budget(),
                        )
                    )
                    placement_variant_sec += (
                        last_placement_search_stats().variant_gen_sec
                    )
                    if rescue_results and rescue_results[0].score >= grid_target:
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
                and baseline_score < grid_target
                and solve_remaining() >= 1.0
            ):
                rescue_rack = consumable_rack_tiles(loadout, cactus_only=False)
                if target_rescue_worth_trying(
                    baseline_score, grid_target, rescue_rack
                ):
                    print(
                        f"  Target: {grid_target} pts (best {int(baseline_score)} "
                        "— trying extra consumables…)",
                        flush=True,
                    )
                    rescue_board, rescue_records, rescue_results = (
                        search_target_rescue(
                            self._searcher,
                            board,
                            loadout,
                            rescue_rack,
                            target=grid_target,
                            time_budget=phase_budget(rescue_budget),
                            top_n=self.config.top_n_results,
                            rules=rules,
                            variant_gen_budget=variant_gen_budget(),
                        )
                    )
                    placement_variant_sec += (
                        last_placement_search_stats().variant_gen_sec
                    )
                    if rescue_results and rescue_results[0].score >= grid_target:
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
            for result in results:
                result.dictionary_word = dictionary_word_for_path(
                    search_board,
                    result.path,
                    result.word,
                    loadout,
                    self._dictionary,
                    min_len=effective_min,
                )
            search_elapsed = time.monotonic() - search_started
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
                variant_note = (
                    f"variants {placement_variant_sec:.1f}s, "
                    if placement_variant_sec > 0.001
                    else ""
                )
                print(
                    f"  Timing: {variant_note}"
                    f"dfs {timing.dfs_sec:.1f}s{fallback_note}, "
                    f"extend {timing.extend_sec:.1f}s, "
                    f"chess {timing.chess_sec:.1f}s, score {total_score:.1f}s "
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
            if results:
                top = results[0]
                # Re-read run_state after search; merge encounter historic before score + embed.
                self._reload_run_state()
                fresh_run_state = load_run_state_raw()
                embed_hist_before = ""
                if isinstance(fresh_run_state, dict):
                    raw_extras = fresh_run_state.get("extras")
                    if isinstance(raw_extras, dict):
                        embed_hist_before = str(
                            raw_extras.get("historic_words", "") or ""
                        ).strip()
                merged_run_state: dict | None = (
                    fresh_run_state if isinstance(fresh_run_state, dict) else None
                )
                if merged_run_state is not None:
                    catchup = merge_encounter_historic_for_f8_snapshot(merged_run_state)
                    if catchup is not None:
                        merged_run_state = catchup
                    fresh_again = load_run_state_raw()
                    if isinstance(fresh_again, dict):
                        remerged = merge_encounter_historic_for_f8_snapshot(
                            merged_run_state
                        )
                        if remerged is not None:
                            merged_run_state = remerged
                merged_extras = (
                    merged_run_state.get("extras")
                    if isinstance(merged_run_state, dict)
                    and isinstance(merged_run_state.get("extras"), dict)
                    else None
                )
                merged_hist = ""
                merged_grid = 0
                if isinstance(merged_extras, dict):
                    merged_hist = str(
                        merged_extras.get("historic_words", "") or ""
                    ).strip()
                    try:
                        merged_grid = int(str(merged_extras.get("grid_number") or "0"))
                    except ValueError:
                        merged_grid = 0
                catchup_note = describe_f8_historic_catchup(
                    embed_hist_before,
                    merged_hist,
                    grid_number=merged_grid,
                )
                if catchup_note:
                    print(f"  Warning: {catchup_note}", flush=True)
                hist_stale_note = f8_historic_stale_after_merge_warning(merged_extras)
                if hist_stale_note:
                    print(f"  Warning: {hist_stale_note}", flush=True)
                fresh_mod_money = mod_money_from_run_state(merged_run_state)
                merged_loadout = (
                    parse_run_state(
                        prepare_run_state_dict_for_scoring(merged_run_state)
                    )
                    if merged_run_state is not None
                    else self._loadout_cache
                )
                save_loadout = merge_loadout_with_board(
                    merged_loadout,
                    board.money,
                    mod_money=fresh_mod_money if fresh_mod_money > 0 else None,
                )
                # Consumables placed onto search_board this solve are no longer on
                # the rack, so Hi Vis Jacket must score with the post-placement
                # count (decompiled HiVisJacket: multiplies by consumables still
                # owned and drops one on submit). Scoring with the pre-placement
                # count over-multiplies (x4.0 vs x3.4, etc.).
                num_placed = consumable_placement_count_on_board(
                    search_board
                ) - consumable_placement_count_on_board(board)
                score_loadout = loadout_after_consumable_placements(
                    save_loadout, num_placed
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
                pred_score, pred_bd, pred_trace = self._scoring.score_with_trace(
                    search_board, top.path, score_word, score_loadout
                )
                top.score = pred_score
                top.breakdown = pred_bd
                # The displayed/tracked word must match the assignment that earned
                # pred_score. The per-result loop above picks the max physical-overlap
                # reading, but the score uses the max-scoring wildcard resolution
                # (e.g. "?k?e?" scores as "skies" 102, not "skyey" 27). Surface the
                # scored word so the player plays exactly what was predicted.
                if score_word and score_word.lower() != top.word.lower():
                    top.dictionary_word = score_word
                else:
                    top.dictionary_word = None
                export_diag = export_diagnostics_from_run_state(merged_run_state)
                export_warnings = validate_run_state_for_scoring(
                    save_loadout,
                    board=board,
                    raw=merged_run_state,
                )
                session_extras = solver_session_extras_from_loadout(save_loadout)
                f8_snapshot = sanitize_run_state_snapshot_for_f8(
                    merged_run_state,
                    save_loadout,
                )
                f8_extras = (
                    f8_snapshot.get("extras")
                    if isinstance(f8_snapshot, dict)
                    else None
                )
                run_extras = (
                    merged_run_state.get("extras")
                    if isinstance(merged_run_state, dict)
                    else None
                )
                stale_note = f8_prior_suggestion_stale_note(
                    run_extras if isinstance(run_extras, dict) else None
                )
                if stale_note:
                    print(f"  Warning: {stale_note}", flush=True)
                empty_hist_warn = empty_historic_on_later_grid_warning(
                    f8_extras if isinstance(f8_extras, dict) else run_extras
                )
                if empty_hist_warn:
                    print(f"  Warning: {empty_hist_warn}", flush=True)
                save_last_suggestion(
                    board=search_board,
                    loadout=save_loadout,
                    result=top,
                    predicted_trace=pred_trace,
                    run_state_snapshot=f8_snapshot,
                    dictionary=self._dictionary,
                    min_len=effective_min,
                    scoring_word=score_word,
                    export_diagnostics=export_diag,
                    export_warnings=export_warnings,
                    solver_session_extras=session_extras,
                    consumable_placements=placement_records or None,
                )
                self._last_invalidation_reason = None
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
            )
            print(f"Board source: {board_source}", flush=True)

            if results:
                top = results[0]
                done_msg = (
                    f"Done in {search_elapsed:.1f}s. Best: {format_suggestion_word(top)} "
                    f"({int(top.score)} pts)"
                )
                if placement_records:
                    done_msg += (
                        " — place consumables first, then trace the highlighted path"
                    )
                print(done_msg, flush=True)
                effects = (top.breakdown or {}).get("pipeline", {}).get("effects")
                if effects:
                    print(f"  Score effects: {'; '.join(str(e) for e in effects)}", flush=True)
                print(
                    "  Wrote last_suggestion.json for melmod scoring capture.",
                    flush=True,
                )
            else:
                clear_last_suggestion()
                print(
                    f"Done in {search_elapsed:.1f}s. No valid words found.",
                    flush=True,
                )
                print(
                    "  If the board changed since your last solve, press F7 "
                    "in-game then F8 again.",
                    flush=True,
                )

            warnings = self._overlay_warnings(board, unmapped)
            highlight = (
                self.config.show_board_highlight
                and self.config.board_region.is_valid()
                and bool(results)
            )
            self._bridge.solve_finished.emit(
                _SolveUIUpdate(
                    board=search_board,
                    results=results,
                    board_bgr=board_img,
                    warnings_html=warnings,
                    on_game_highlight=highlight,
                    consumable_placements=placement_records or None,
                    melmod_board_fingerprint=melmod_board_fp,
                    melmod_loadout_fingerprint=melmod_loadout_fp,
                )
            )
        except Exception:
            err = traceback.format_exc()
            print(err)
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            (DEBUG_DIR / "last_error.txt").write_text(err, encoding="utf-8")
        finally:
            self._busy = False
            self._solve_active = False

    def _reload_run_state(self) -> None:
        """Reload run_state.json (e.g. after melmod F7 export)."""
        self._loadout_cache = load_run_state()
        self._loadout_source = self._detect_loadout_source()

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
        if self._loadout_cache is None:
            return "invalid"
        if data.get("character") == "Example":
            return "template"
        if data.get("extras", {}).get("pin_effect") or len(data.get("stickers", [])) > 2:
            return "mod"
        if self._loadout_cache.stickers or self._loadout_cache.stamps:
            return "manual"
        if data.get("character") and data.get("character") != "Example":
            return "mod"
        return "file"

    def _overlay_warnings(self, board, unmapped: list[str]) -> str:
        del board
        lines: list[str] = []
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
        dlg = LoadoutDialog(self._loadout_cache)
        if dlg.exec():
            self._loadout_cache = dlg.get_loadout()
            save_loadout(self._loadout_cache)
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
                "Board region updated.\n"
                f"Check {DEBUG_DIR / 'calibration_preview.png'} to verify the capture.",
            )
        finally:
            self._calibrating = False


def main() -> None:
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
