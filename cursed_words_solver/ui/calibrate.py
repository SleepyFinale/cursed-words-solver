"""Calibration wizard to select board capture region for path highlights."""

from __future__ import annotations

import sys

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPainter, QPen, QColor
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from cursed_words_solver.config import AppConfig, Region


def _all_screens_geometry() -> QRect:
    screens = QGuiApplication.screens()
    if not screens:
        return QGuiApplication.primaryScreen().geometry()
    bounds = QRect()
    for screen in screens:
        bounds = bounds.united(screen.geometry())
    return bounds


def region_from_widget_rect(widget: QWidget, rect: QRect) -> Region | None:
    """Build a Region in Qt virtual-desktop coordinates from a widget-local rect."""
    if rect.width() <= 20 or rect.height() <= 20:
        return None
    top_left = widget.mapToGlobal(rect.topLeft())
    return Region(
        x=top_left.x(),
        y=top_left.y(),
        width=rect.width(),
        height=rect.height(),
    )


class RegionSelector(QWidget):
    finished = Signal(object)

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt
        self.origin: QPoint | None = None
        self.current: QPoint | None = None
        self.result: Region | None = None

        self.setGeometry(_all_screens_geometry())
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.label = QLabel(self)
        self.label.setText(prompt)
        self.label.setStyleSheet(
            "background: rgba(0,0,0,180); color: white; padding: 12px; "
            "font-size: 14px; border-radius: 6px;"
        )
        self.label.move(20, 20)
        self.label.adjustSize()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))
        if self.origin and self.current:
            rect = QRect(self.origin, self.current).normalized()
            painter.setPen(QPen(QColor(0, 200, 255), 2, Qt.PenStyle.SolidLine))
            painter.drawRect(rect)
            painter.fillRect(rect, QColor(0, 200, 255, 40))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.current = self.origin
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self.origin is not None:
            self.current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.origin:
            self.current = event.position().toPoint()
            rect = QRect(self.origin, self.current).normalized()
            self.result = region_from_widget_rect(self, rect)
            self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.result = None
            self.close()

    def closeEvent(self, event) -> None:
        self.finished.emit(self.result)
        super().closeEvent(event)


def run_calibration_wizard(config: AppConfig) -> AppConfig:
    """Interactive region selection for the 5×5 board overlay alignment."""
    app = QApplication.instance() or QApplication(sys.argv)

    def select_region(prompt: str, terminal_hint: str) -> Region | None:
        print(f">>> {terminal_hint}", flush=True)
        selector = RegionSelector(prompt)
        done: list[Region | None] = [None]
        loop = QEventLoop()

        def on_done(region: Region | None) -> None:
            done[0] = region
            loop.quit()

        selector.finished.connect(on_done)
        selector.show()
        selector.raise_()
        selector.activateWindow()
        selector.setFocus()
        loop.exec()
        return done[0]

    board = select_region(
        "Drag a rectangle over the 5×5 BOARD.\n"
        "Release to confirm. ESC to cancel.",
        "Drag a rectangle over the 5×5 board (all monitors). ESC to cancel.",
    )
    if board:
        config.board_region = board
        print(
            f"  Board set: {board.width}×{board.height} at ({board.x},{board.y})",
            flush=True,
        )
    else:
        print("  Board selection cancelled (previous region kept).", flush=True)

    config.save()
    return config
