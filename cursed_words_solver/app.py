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
    clear_stale_last_suggestion_if_loadout_changed,
    dictionary_word_for_path,
    format_suggestion_word,
    save_last_suggestion,
    stale_suggestion_warning,
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
    merge_loadout_with_board,
    neapolitan_extras_stale_warning,
    mod_money_from_run_state,
    parse_board_from_run_state,
    save_loadout,
    save_run_state_template,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.boss_effects import (
    boss_area_number,
    boss_word_constraints,
)
from cursed_words_solver.rules.rule_lookup import boss_display_name
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
        self._loadout_cache = load_run_state()
        self._loadout_source = self._detect_loadout_source()
        self._scoring = ScoringPipeline()
        self._dictionary: WordDictionary | None = None
        self._searcher: WordSearcher | None = None
        self._busy = False
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
        self._run_state_poll_timer.timeout.connect(self._maybe_clear_stale_highlights)
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
                stale_note = stale_suggestion_warning(
                    board_fp, current_loadout_fp=loadout_fp
                )
                if stale_note:
                    print(f"  {stale_note}", flush=True)
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
        unmapped: list[str] = []
        board_source = "melmod"
        money_source = "mod"
        try:
            print("Solve started...", flush=True)

            self._reload_run_state()
            run_state_data = load_run_state_raw()

            mod_money = mod_money_from_run_state(run_state_data)
            board = parse_board_from_run_state(run_state_data)
            board_img = None

            if board is None:
                print(melmod_install_hint(), flush=True)
                if run_state_data is None:
                    print(
                        "Could not read run_state.json (file locked or invalid JSON).",
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
            loadout = merge_loadout_with_board(
                self._loadout_cache,
                board.money,
                mod_money=mod_money if mod_money > 0 else None,
            )
            from cursed_words_solver.rules.scoring_conditions import rewind_setup_extras

            rewind_notes = rewind_setup_extras(loadout, board)
            # Neapolitan +5% submit simulation only when live percent is not exported.
            if isinstance(loadout.extras, dict):
                has_neapolitan = any(
                    str(getattr(stamp, "id", "") or "").strip().lower() == "neapolitan"
                    for stamp in (loadout.stamps or [])
                )
                from cursed_words_solver.rules.scoring_conditions import (
                    neapolitan_has_live_percent,
                )

                if not has_neapolitan or not neapolitan_has_live_percent(loadout):
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
                    if neapolitan_has_live_percent(loadout):
                        print(
                            "  Setup: Neapolitan using "
                            f"{base_percent}% ({source_label}).",
                            flush=True,
                        )
                    else:
                        print(
                            "  Setup: Neapolitan submit simulation "
                            f"({base_percent}% -> {base_percent + 5}% when 3+ colours; "
                            f"{source_label}).",
                            flush=True,
                        )
                        if source == "default":
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
            self._searcher.time_budget = search_budget
            self._searcher.validator.min_len = self._searcher.min_len
            self._searcher.blocked = constraints.blocked
            self._searcher.block_reason = constraints.block_reason
            search_msg = (
                f"Searching for words (up to {search_budget:.0f}s, "
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
            results = self._searcher.find_best_words(
                board,
                loadout=loadout,
                top_n=self.config.top_n_results,
            )
            for result in results:
                result.dictionary_word = dictionary_word_for_path(
                    board,
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
                print(
                    f"  Timing: dfs {timing.dfs_sec:.1f}s{fallback_note}, "
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
            if results:
                top = results[0]
                pred_score, pred_bd, pred_trace = self._scoring.score_with_trace(
                    board, top.path, top.word, loadout
                )
                top.score = pred_score
                top.breakdown = pred_bd
                save_last_suggestion(
                    board=board,
                    loadout=loadout,
                    result=top,
                    predicted_trace=pred_trace,
                    run_state_snapshot=run_state_data,
                    dictionary=self._dictionary,
                    min_len=effective_min,
                )

            self._save_debug(
                board_img,
                board,
                results,
                board_source=board_source,
                money_source=money_source,
                top_predicted_trace=pred_trace,
            )
            print(f"Board source: {board_source}", flush=True)

            if results:
                top = results[0]
                print(
                    f"Done in {search_elapsed:.1f}s. Best: {format_suggestion_word(top)} "
                    f"({int(top.score)} pts)",
                    flush=True,
                )
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
                    board=board,
                    results=results,
                    board_bgr=board_img,
                    warnings_html=warnings,
                    on_game_highlight=highlight,
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
    ) -> None:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if img is not None:
            save_debug_image(img, DEBUG_DIR / f"board_{ts}.png")
        payload = {
            "board_source": board_source,
            "money_source": money_source,
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
