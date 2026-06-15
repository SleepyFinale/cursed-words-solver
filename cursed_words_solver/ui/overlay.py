"""Result overlay with path preview on captured board."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from cursed_words_solver.config import Region
from cursed_words_solver.consumable_placement import (
    format_placement_path_hints,
    placement_record_display_letter,
)
from cursed_words_solver.suggestion import format_suggestion_word, format_result_score_display
from cursed_words_solver.ui.board_geometry import path_geometry

if TYPE_CHECKING:
    from cursed_words_solver.models import Board, WordResult


class ResultOverlay(QWidget):
    request_quit = Signal()

    _PANEL_COLUMNS = 5
    _PANEL_COLUMN_INDEX = 1  # second column from the left (0-based)
    _MARGIN_Y = 32
    _MAX_CONTENT_WIDTH = 320
    _MIN_PANEL_WIDTH = 135
    _MIN_PANEL_HEIGHT = 56
    # Stylesheet border (2px) + padding (6px) per side — not included in layout.sizeHint().
    _STYLE_CHROME = 16

    def __init__(self) -> None:
        super().__init__()
        self._has_solved = False
        self._stale_notice_active = False
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(
            "background: rgba(20, 20, 30, 230); color: #eee; "
            "border: 2px solid #0cf; border-radius: 6px; padding: 6px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.idle_label = QLabel("Press F8 to solve")
        self.idle_label.setStyleSheet("font-size: 13px; color: #aaa;")
        self.idle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.idle_label)

        self.hero_result = QLabel()
        self.hero_result.setTextFormat(Qt.TextFormat.RichText)
        self.hero_result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_result.setWordWrap(True)
        self.hero_result.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Minimum,
        )
        self.hero_result.setMinimumHeight(0)
        self.hero_result.hide()
        layout.addWidget(self.hero_result)

        self.warnings_label = QLabel()
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setStyleSheet("font-size: 10px; color: #fa0;")
        self.warnings_label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Minimum,
        )
        self.warnings_label.setMinimumHeight(0)
        self.warnings_label.hide()
        layout.addWidget(self.warnings_label)

        self.preview = QLabel()
        self.preview.setFixedSize(140, 140)
        self.preview.setScaledContents(True)
        self.preview.hide()
        layout.addWidget(self.preview)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.request_quit.emit()
        event.accept()

    def show_idle(self) -> None:
        self._has_solved = False
        self._stale_notice_active = False
        self.idle_label.show()
        self.hero_result.hide()
        self.warnings_label.hide()
        self.preview.hide()
        self._resize_for_content()
        self._position_panel()
        self.show()
        self.raise_()

    def show_solving_notice(self) -> None:
        """Brief state while auto-solve runs after an in-game word submit."""
        self._has_solved = False
        self._stale_notice_active = False
        self.idle_label.hide()
        self.hero_result.setText(
            "<span style='font-size:13px;font-weight:bold;color:#fa0'>"
            "Solving…</span>"
        )
        self.hero_result.show()
        self.warnings_label.hide()
        self.preview.hide()
        self._resize_for_content()
        self._position_panel()
        self.show()
        self.raise_()

    def show_stale_notice(self, message: str) -> None:
        """Warn that the F8 suggestion is stale — user should press F8 again."""
        self._has_solved = False
        self._stale_notice_active = True
        self.idle_label.hide()
        self.hero_result.setText(
            "<span style='font-size:13px;font-weight:bold;color:#fa0'>"
            "STALE — press F8</span>"
        )
        self.hero_result.show()
        detail = (message or "").strip()
        if detail:
            self.warnings_label.setText(detail)
            self.warnings_label.show()
        else:
            self.warnings_label.hide()
        self.preview.hide()
        self._resize_for_content()
        self._position_panel()
        self.show()
        self.raise_()

    def clear_stale_notice(self) -> None:
        """Remove stale warning (fresh F8 solve will replace content)."""
        if not self._stale_notice_active:
            return
        self._stale_notice_active = False
        self.warnings_label.hide()

    def show_shop_advice(self, advice_html: str, *, warnings_html: str = "") -> None:
        """Show shop purchase/sell/restock recommendations."""
        self._has_solved = True
        self.idle_label.hide()
        self.clear_stale_notice()
        if warnings_html:
            self.warnings_label.setText(warnings_html)
            self.warnings_label.show()
        else:
            self.warnings_label.hide()
        self.hero_result.setText(advice_html)
        self.hero_result.show()
        self.preview.hide()
        self._resize_for_content()
        self._position_panel()
        self.show()
        self.raise_()

    def show_results(
        self,
        board: Board,
        results: list[WordResult],
        *,
        board_bgr: np.ndarray | None = None,
        warnings_html: str = "",
        on_game_highlight: bool = False,
        consumable_placements: list | None = None,
        twinkle_toes_swap: Any | None = None,
        trusted: bool = True,
    ) -> None:
        self._has_solved = True
        self.idle_label.hide()
        self.clear_stale_notice()

        if warnings_html:
            self.warnings_label.setText(warnings_html)
            self.warnings_label.show()
        else:
            self.warnings_label.hide()

        if results:
            top = results[0]
            word_html = format_suggestion_word(top).upper().replace(
                " → ", "<span style='color:#8cf'> → </span>"
            )
            setup_line = ""
            if top.setup_bonus > 0:
                setup_line = (
                    f"<br><span style='font-size:12px;color:#8cf'>"
                    f"+{top.setup_bonus:,.0f} setup (rank {top.rank_score:,.0f})</span>"
                )
            placement_line = ""
            swap_line = ""
            microscope_line = ""
            ms_hint = (top.breakdown or {}).get("microscope_hint")
            if ms_hint:
                microscope_line = (
                    "<br><span style='font-size:11px;color:#8cf'>"
                    f"{ms_hint}</span>"
                )
            if consumable_placements:
                hint = ""
                if top.path:
                    hint = format_placement_path_hints(top.path, consumable_placements)
                if not hint:
                    parts: list[str] = []
                    for rec in consumable_placements:
                        letter = placement_record_display_letter(rec)
                        row = int(
                            getattr(rec, "row", 0)
                            if not isinstance(rec, dict)
                            else rec.get("row", 0)
                        )
                        col = int(
                            getattr(rec, "col", 0)
                            if not isinstance(rec, dict)
                            else rec.get("col", 0)
                        )
                        parts.append(f"{letter} (row {row + 1}, col {col + 1})")
                    if parts:
                        hint = f"Place {'; '.join(parts)} first"
                if hint:
                    placement_line = (
                        "<br><span style='font-size:11px;color:#fa0'>"
                        f"{hint}</span>"
                    )
            if twinkle_toes_swap:
                row_a = int(
                    getattr(twinkle_toes_swap, "row_a", 0)
                    if not isinstance(twinkle_toes_swap, dict)
                    else twinkle_toes_swap.get("row_a", 0)
                )
                col_a = int(
                    getattr(twinkle_toes_swap, "col_a", 0)
                    if not isinstance(twinkle_toes_swap, dict)
                    else twinkle_toes_swap.get("col_a", 0)
                )
                row_b = int(
                    getattr(twinkle_toes_swap, "row_b", 0)
                    if not isinstance(twinkle_toes_swap, dict)
                    else twinkle_toes_swap.get("row_b", 0)
                )
                col_b = int(
                    getattr(twinkle_toes_swap, "col_b", 0)
                    if not isinstance(twinkle_toes_swap, dict)
                    else twinkle_toes_swap.get("col_b", 0)
                )
                swap_line = (
                    "<br><span style='font-size:11px;color:#f6a'>"
                    f"Swap ({row_a + 1},{col_a + 1}) \u2194 ({row_b + 1},{col_b + 1}) first"
                    "</span>"
                )
            score_html = format_result_score_display(top)
            if not trusted:
                score_html = (
                    "<span style='color:#fa0;font-weight:bold'>UNTRUSTED</span> "
                    f"{score_html}"
                )
            self.hero_result.setText(
                f"<span style='font-size:22px;font-weight:bold;color:#fff'>"
                f"{word_html}</span>"
                f"&nbsp;&nbsp;"
                f"<span style='font-size:18px;font-weight:bold;color:#0f8'>"
                f"{score_html}</span>"
                f"{setup_line}"
                f"{placement_line}"
                f"{swap_line}"
                f"{microscope_line}"
            )
            self.hero_result.show()
        else:
            self.hero_result.setText(
                "<span style='font-size:14px;color:#f88'>No valid words</span>"
            )
            self.hero_result.show()

        best_path = results[0].path if results else []
        if board_bgr is not None and not on_game_highlight:
            annotated = self._draw_paths(board_bgr, results[:1], board)
            self._set_capture_preview(annotated)
        else:
            self.preview.hide()

        self._resize_for_content()
        self._position_panel()
        self.show()
        self.raise_()

    def _position_panel(self) -> None:
        """Place in the 2nd column of a 5-column layout (away from the score)."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.move(200, self._MARGIN_Y)
            return
        avail = screen.availableGeometry()
        col_width = avail.width() / self._PANEL_COLUMNS
        x = avail.x() + int(col_width * self._PANEL_COLUMN_INDEX)
        y = avail.y() + self._MARGIN_Y
        self.move(x, y)

    def _set_capture_preview(self, bgr: np.ndarray) -> None:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self.preview.setPixmap(QPixmap.fromImage(qimg.copy()))
        self.preview.show()

    def _resize_for_content(self) -> None:
        """Size panel from layout hints; never below minimumSizeHint (Qt geometry warnings)."""
        max_w = self._MAX_CONTENT_WIDTH
        layout = self.layout()
        if layout is not None:
            lm = layout.contentsMargins()
            horiz_inset = lm.left() + lm.right()
            vert_inset = lm.top() + lm.bottom()
        else:
            horiz_inset = vert_inset = 12

        max_label_w = max(1, max_w - self._STYLE_CHROME - horiz_inset)
        for label in (self.hero_result, self.warnings_label, self.idle_label):
            if not label.isVisible():
                continue
            label.setMaximumWidth(max_label_w)
            if label.wordWrap():
                label.setFixedWidth(max_label_w)

        if layout is not None:
            layout.activate()
            hint = layout.sizeHint()
        else:
            hint = self.minimumSizeHint()

        w = min(
            max(hint.width() + self._STYLE_CHROME + horiz_inset, self._MIN_PANEL_WIDTH),
            max_w,
        )
        h = max(hint.height() + self._STYLE_CHROME + vert_inset, self._MIN_PANEL_HEIGHT)
        self.resize(w, h)

        # Rich-text / word-wrap labels may raise minimum height after the first pass.
        for _ in range(8):
            min_sz = self.minimumSizeHint()
            new_w = min(max(w, min_sz.width()), max_w)
            new_h = max(h, min_sz.height())
            if new_w == self.width() and new_h == self.height():
                break
            w, h = new_w, new_h
            self.resize(w, h)
        min_sz = self.minimumSizeHint()
        final_w = min(max(w, min_sz.width()), max_w)
        final_h = max(h, min_sz.height())
        self.setFixedSize(final_w, final_h)

    def _draw_paths(
        self,
        board_bgr: np.ndarray,
        results: list,
        board: Board | None = None,
    ) -> np.ndarray:
        img = board_bgr.copy()
        h, w = img.shape[:2]
        color = (0, 255, 100)
        region = Region(0, 0, w, h)
        for result in results[:1]:
            steps = path_geometry(region, result.path, board)
            pts = [(int(s.x), int(s.y)) for s in steps]
            for cx, cy in pts:
                cv2.circle(img, (cx, cy), max(4, min(h, w) // 25), color, -1)
            if len(pts) >= 2:
                for j in range(len(pts) - 1):
                    cv2.line(img, pts[j], pts[j + 1], color, 2)
        return img
