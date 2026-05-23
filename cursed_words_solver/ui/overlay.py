"""Result overlay with path preview on captured board."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from cursed_words_solver.models import Board, WordResult


class ResultOverlay(QWidget):
    request_quit = Signal()

    _PANEL_COLUMNS = 5
    _PANEL_COLUMN_INDEX = 1  # second column from the left (0-based)
    _MARGIN_Y = 32

    def __init__(self) -> None:
        super().__init__()
        self._has_solved = False
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
        self.hero_result.hide()
        layout.addWidget(self.hero_result)

        self.alternates_label = QLabel()
        self.alternates_label.setWordWrap(True)
        self.alternates_label.setStyleSheet("font-size: 11px; color: #888;")
        self.alternates_label.hide()
        layout.addWidget(self.alternates_label)

        self.warnings_label = QLabel()
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setStyleSheet("font-size: 10px; color: #fa0;")
        self.warnings_label.hide()
        layout.addWidget(self.warnings_label)

        self.preview = QLabel()
        self.preview.setFixedSize(140, 140)
        self.preview.setScaledContents(True)
        self.preview.hide()
        layout.addWidget(self.preview)

        self.resize(200, 72)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.request_quit.emit()
        event.accept()

    def show_idle(self) -> None:
        self._has_solved = False
        self.idle_label.show()
        self.hero_result.hide()
        self.alternates_label.hide()
        self.warnings_label.hide()
        self.preview.hide()
        self.resize(200, 56)
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
    ) -> None:
        del board  # letter path no longer shown in panel
        self._has_solved = True
        self.idle_label.hide()

        if warnings_html:
            self.warnings_label.setText(warnings_html)
            self.warnings_label.show()
        else:
            self.warnings_label.hide()

        if results:
            top = results[0]
            self.hero_result.setText(
                f"<span style='font-size:22px;font-weight:bold;color:#fff'>"
                f"{top.word.upper()}</span>"
                f"&nbsp;&nbsp;"
                f"<span style='font-size:18px;font-weight:bold;color:#0f8'>"
                f"{top.score:,.0f} pts</span>"
            )
            self.hero_result.show()

            alt_lines = []
            for i, r in enumerate(results[1:3], start=2):
                alt_lines.append(
                    f"#{i} {r.word.upper()} — {r.score:,.0f} pts"
                )
            if alt_lines:
                self.alternates_label.setText("<br>".join(alt_lines))
                self.alternates_label.show()
            else:
                self.alternates_label.hide()
        else:
            self.hero_result.setText(
                "<span style='font-size:14px;color:#f88'>No valid words</span>"
            )
            self.hero_result.show()
            self.alternates_label.hide()

        best_path = results[0].path if results else []
        if board_bgr is not None and not on_game_highlight:
            annotated = self._draw_paths(board_bgr, results[:1])
            self._set_capture_preview(annotated)
        else:
            self.preview.hide()

        self._resize_for_content(on_game_highlight and bool(best_path))
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

    def _resize_for_content(self, compact: bool) -> None:
        w = 200
        h = 56 if not self._has_solved else 72
        if compact:
            h = 72
        elif self.preview.isVisible():
            h = 200
        if self.warnings_label.isVisible():
            h += 22
        if self.alternates_label.isVisible():
            h += 18 * min(2, self.alternates_label.text().count("<br>") + 1)
        self.resize(w, h)

    def _draw_paths(
        self, board_bgr: np.ndarray, results: list
    ) -> np.ndarray:
        img = board_bgr.copy()
        h, w = img.shape[:2]
        color = (0, 255, 100)
        for result in results[:1]:
            pts = []
            for idx in result.path:
                row, col = idx // 5, idx % 5
                cy = int((row + 0.5) * h / 5)
                cx = int((col + 0.5) * w / 5)
                pts.append((cx, cy))
                cv2.circle(img, (cx, cy), max(4, min(h, w) // 25), color, -1)
            if len(pts) >= 2:
                for j in range(len(pts) - 1):
                    cv2.line(img, pts[j], pts[j + 1], color, 2)
        return img
