"""Main application: hotkey solver with overlay."""

from __future__ import annotations

import argparse
import atexit
import json
import signal
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import keyboard
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from cursed_words_solver.capture import capture_region, save_debug_image
from cursed_words_solver.config import (
    CONFIG_DIR,
    DEBUG_DIR,
    AppConfig,
    describe_wordlist,
    resolve_wordlist,
)
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import (
    format_loadout_summary,
    load_run_state,
    load_run_state_raw,
    merge_loadout_with_board,
    mod_money_from_run_state,
    parse_board_from_run_state,
    save_loadout,
    save_run_state_template,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import WordSearcher
from cursed_words_solver.ui.loadout_dialog import LoadoutDialog
from cursed_words_solver.ui.overlay import ResultOverlay
from cursed_words_solver.vision.board_parser import BoardParser, format_board_grid
from cursed_words_solver.vision.calibrate import run_calibration_wizard


class _HotkeyBridge(QObject):
    """Marshal keyboard hook callbacks onto the Qt main thread."""

    recalibrate = Signal()
    edit_loadout = Signal()
    hide_overlay = Signal()
    quit_app = Signal()


class SolverApp:
    def __init__(self, config: AppConfig, calibrate: bool = False) -> None:
        self.config = config
        self.calibrate = calibrate
        self.app = QApplication(sys.argv)
        self.overlay = ResultOverlay()
        self._loadout_cache = load_run_state()
        self._loadout_source = self._detect_loadout_source()
        self._scoring = ScoringPipeline()
        self._parser: BoardParser | None = None
        self._dictionary: WordDictionary | None = None
        self._searcher: WordSearcher | None = None
        self._busy = False
        self._calibrating = False
        self._hotkey_handle = None
        self._shutting_down = False
        self._bridge = _HotkeyBridge()
        self._bridge.recalibrate.connect(self._run_recalibrate)
        self._bridge.edit_loadout.connect(self._run_edit_loadout)
        self._bridge.hide_overlay.connect(self.overlay.hide)
        self._bridge.quit_app.connect(self._shutdown)
        self.overlay.request_quit.connect(self._shutdown)
        atexit.register(keyboard.unhook_all)

    def _ensure_ready(self, *, require_board_region: bool = True) -> bool:
        if require_board_region and not self.config.board_region.is_valid():
            return False
        if self._dictionary is None:
            wl_path = resolve_wordlist(self.config.wordlist)
            self._dictionary = WordDictionary(wl_path)
        if self._parser is None:
            self._parser = BoardParser(
                use_gpu=self.config.ocr_use_gpu,
                cell_inset_ratio=self.config.cell_inset_ratio,
                debug_ocr=self.config.debug_ocr,
            )
        if self._searcher is None:
            self._searcher = WordSearcher(
                dictionary=self._dictionary,
                min_len=self.config.min_word_length,
                max_len=self.config.max_word_length,
                time_budget=self.config.search_time_budget_sec,
            )
        return True

    def run(self) -> int:
        if self.calibrate or not self.config.board_region.is_valid():
            QMessageBox.information(
                None,
                "Calibration",
                "Select the 5×5 board region. Optionally select money display.",
            )
            self.config = run_calibration_wizard(self.config)
            self._finish_calibration("Calibration complete")

        if not self.config.board_region.is_valid():
            QMessageBox.critical(
                None,
                "Calibration required",
                "Board region not set. Run with --calibrate",
            )
            return 1

        if not self.calibrate:
            br = self.config.board_region
            print(
                f"Board region: {br.width}×{br.height} at ({br.x},{br.y}).",
                flush=True,
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

        self.overlay.title.setText(
            f"Cursed Words Solver — {hotkey.upper()} solve · F9 loadout · F10 calibrate"
        )
        self.overlay.show()

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
        mapped, total, unmapped = self._scoring.loadout_mapping_summary(
            self._loadout_cache
        )
        if total:
            print(f"  Rules catalog: {mapped}/{total} items recognized", flush=True)
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
        board_data = load_run_state_raw()
        mod_board = parse_board_from_run_state(board_data)
        if mod_board is not None:
            print(
                "Melmod board ready in run_state.json (F8 will skip OCR).",
                flush=True,
            )
        elif self._loadout_source == "mod":
            print(
                "Melmod loadout found but no board in run_state.json — "
                "press F7 during a round with tiles visible.",
                flush=True,
            )
        print(
            "Preloading OCR in background (first F8 is faster after this finishes)...",
            flush=True,
        )
        threading.Thread(target=self._preload_ocr, daemon=True).start()
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

    def _shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        print("\nShutting down...", flush=True)
        self._cleanup_keyboard()
        self.overlay.hide()
        self.app.quit()

    def _preload_ocr(self) -> None:
        try:
            if not self._ensure_ready():
                return
            _ = self._parser.reader
            print(
                f"Idle — open the game and press {self.config.hotkey.upper()} to solve "
                "(first solve on CPU may take several minutes).",
                flush=True,
            )
        except Exception:
            print("OCR preload failed (will retry on first solve):", flush=True)
            traceback.print_exc()

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
        board_source = "ocr"
        money_source = "none"
        try:
            print("Solve started...", flush=True)

            self._reload_run_state()
            run_state_data = load_run_state_raw()

            mod_money = mod_money_from_run_state(run_state_data)
            board = parse_board_from_run_state(run_state_data)
            board_img = None

            if board is not None:
                if not self._ensure_ready(require_board_region=False):
                    print("Solver not ready (dictionary failed to load).", flush=True)
                    return
                board_source = "melmod"
                money_source = "mod"
                print("Board from melmod (run_state.json).", flush=True)
                if mod_money:
                    print(f"Money: ${mod_money} (mod)", flush=True)
                print("Parsed board:", flush=True)
                print(format_board_grid(board), flush=True)
                if self.config.board_region.is_valid():
                    try:
                        board_img = capture_region(self.config.board_region)
                        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                        save_debug_image(board_img, DEBUG_DIR / "last_board.png")
                    except Exception as e:
                        print(f"Overlay capture skipped: {e}", flush=True)
            else:
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
                if not self._ensure_ready():
                    print(
                        "Solver not ready (calibrate board region or install melmod).",
                        flush=True,
                    )
                    return
                region = self.config.board_region
                print("Capturing board (OCR)...", flush=True)
                board_img = capture_region(region)
                DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                save_debug_image(board_img, DEBUG_DIR / "last_board.png")
                money = 0
                if mod_money > 0:
                    money = mod_money
                    money_source = "mod"
                elif (
                    self.config.money_region
                    and self.config.money_region.is_valid()
                ):
                    money_img = capture_region(self.config.money_region)
                    money = self._parser.parse_money(money_img)
                    if money:
                        money_source = "ocr"
                board = self._parser.parse_board(board_img, money=money)
                if money_source == "mod":
                    print(f"Money: ${money} (mod)", flush=True)
                elif money_source == "ocr":
                    print(f"Money: ${money} (ocr)", flush=True)

            print("Searching for words...", flush=True)
            loadout = merge_loadout_with_board(
                self._loadout_cache,
                board.money,
                mod_money=mod_money if mod_money > 0 else None,
            )
            mapped, total, unmapped = self._scoring.loadout_mapping_summary(loadout)
            print(format_loadout_summary(loadout), flush=True)
            if total:
                print(f"  Rules: {mapped}/{total} recognized", flush=True)
            if unmapped:
                print(f"  Unmapped: {', '.join(unmapped[:6])}", flush=True)
            results = self._searcher.find_best_words(
                board,
                loadout=loadout,
                top_n=self.config.top_n_results,
            )

            self._save_debug(
                board_img,
                board,
                results,
                board_source=board_source,
                money_source=money_source,
            )
            print(f"Board source: {board_source}", flush=True)

            if results:
                top = results[0]
                print(f"Done. Best: {top.word} ({top.score} pts)", flush=True)
            else:
                print("Done. No valid words found.", flush=True)

            summary = self._board_summary(board, loadout, unmapped)
            QTimer.singleShot(
                0,
                lambda: self.overlay.show_results(board_img, results, summary),
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

    def _board_summary(self, board, loadout, unmapped: list[str]) -> str:
        tiles = board.flat
        low_conf = [t for t in tiles if t.ocr_confidence < 0.4]
        unknown = [t for t in tiles if t.letter == "?" or t.char == "?"]
        grid = format_board_grid(board).replace(" ", "&nbsp;")
        lines = [format_loadout_summary(loadout)]
        lines.append(
            f"<pre style='margin:4px 0;font-size:12px;color:#ccc'>{grid}</pre>"
        )
        if unmapped:
            lines.append(
                f"<span style='color:#fa0'>Unmapped rules: {', '.join(unmapped[:4])}"
                f"{'…' if len(unmapped) > 4 else ''}</span>"
            )
        if unknown:
            lines.append(
                f"<span style='color:#fa0'>{len(unknown)} tile(s) unread (?)</span>"
            )
        elif low_conf:
            lines.append(
                f"<span style='color:#fa0'>Low OCR on {len(low_conf)} tiles</span>"
            )
        else:
            lines.append(f"Parsed 25 tiles · money: {board.money}")
        return "<br>".join(lines)

    def _save_debug(
        self,
        img,
        board,
        results,
        *,
        board_source: str = "ocr",
        money_source: str = "none",
    ) -> None:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if img is not None:
            save_debug_image(img, DEBUG_DIR / f"board_{ts}.png")
        if self._parser and self.config.debug_ocr:
            self._parser.save_debug_tiles(img, DEBUG_DIR)
        ocr_debug = []
        if self._parser:
            for d in self._parser.last_cell_debug:
                ocr_debug.append(
                    {
                        "row": d.row,
                        "col": d.col,
                        "letter_texts": d.letter_texts,
                        "score_texts": d.score_texts,
                        "fallback_texts": d.fallback_texts,
                        "score_override": d.score_override,
                        "chosen_variant": d.chosen_variant,
                    }
                )
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
                    "confidence": t.ocr_confidence,
                }
                for t in board.flat
            ],
            "ocr_debug": ocr_debug,
            "results": [
                {"word": r.word, "score": r.score, "path": r.path}
                for r in results
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
            self.overlay.hide()
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
    parser = argparse.ArgumentParser(description="Cursed Words Screenshot Solver")
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Run calibration wizard on startup",
    )
    parser.add_argument("--hotkey", default=None, help="Override hotkey (e.g. f8)")
    parser.add_argument(
        "--debug-ocr",
        action="store_true",
        help="Save per-tile letter/score ROI images under ~/.cursed_words_solver/debug/tiles/",
    )
    args = parser.parse_args()

    config = AppConfig.load()
    if args.hotkey:
        config.hotkey = args.hotkey
    if args.debug_ocr:
        config.debug_ocr = True

    app = SolverApp(config, calibrate=args.calibrate)
    sys.exit(app.run())


if __name__ == "__main__":
    main()
