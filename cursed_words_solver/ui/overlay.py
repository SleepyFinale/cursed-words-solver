"""Result overlay with path preview on captured board."""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from cursed_words_solver.models import WordResult


class ResultOverlay(QWidget):
    request_quit = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(
            "background: rgba(20, 20, 30, 230); color: #eee; "
            "border: 2px solid #0cf; border-radius: 8px; padding: 8px;"
        )

        layout = QVBoxLayout(self)
        self.title = QLabel("Cursed Words Solver")
        self.title.setStyleSheet("font-size: 16px; font-weight: bold; color: #0cf;")
        layout.addWidget(self.title)

        self.preview = QLabel()
        self.preview.setFixedSize(280, 280)
        self.preview.setScaledContents(True)
        layout.addWidget(self.preview)

        self.results_label = QLabel()
        self.results_label.setWordWrap(True)
        self.results_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(self.results_label)

        self.hint = QLabel(
            "F8 solve · F9 loadout · F7 in-game · ESC hide · Ctrl+Shift+Q quit"
        )
        self.hint.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self.hint)

        self.resize(320, 420)
        self.move(50, 50)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.request_quit.emit()
        event.accept()

    def show_results(
        self,
        board_bgr: np.ndarray | None,
        results: list,
        parse_summary: str = "",
    ) -> None:
        if board_bgr is not None:
            annotated = self._draw_paths(board_bgr, results)
            self._set_preview(annotated)
        else:
            self.preview.clear()
            self.preview.setText("Board from mod (no screenshot)")

        lines = []
        if parse_summary:
            lines.append(parse_summary)
        for i, r in enumerate(results[:3]):
            path_str = " → ".join(str(p + 1) for p in r.path)
            lines.append(
                f"<b>#{i + 1}</b> {r.word.upper()} — <span style='color:#0f8'>{r.score:.0f}</span> pts<br>"
                f"<span style='color:#aaa'>Path: {path_str}</span>"
            )
        if not results:
            lines.append("<span style='color:#f88'>No valid words found.</span>")
        self.results_label.setText("<br>".join(lines))
        self.show()
        self.raise_()

    def _draw_paths(
        self, board_bgr: np.ndarray, results: list
    ) -> np.ndarray:
        img = board_bgr.copy()
        h, w = img.shape[:2]
        colors = [(0, 255, 100), (255, 200, 0), (255, 80, 180)]
        for ri, result in enumerate(results[:3]):
            color = colors[ri % len(colors)]
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

    def _set_preview(self, bgr: np.ndarray) -> None:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self.preview.setPixmap(QPixmap.fromImage(qimg.copy()))
