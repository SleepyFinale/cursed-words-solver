"""Transparent on-game overlay highlighting the best word path."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from cursed_words_solver.config import Region


@dataclass(frozen=True)
class PathStep:
    """Center of a tile in overlay-local coordinates and draw order (1-based)."""

    x: float
    y: float
    step: int


def path_geometry(region: Region, path: list[int]) -> list[PathStep]:
    """Map tile indices to centers within a board region (overlay-local coords)."""
    if not region.is_valid() or not path:
        return []
    w, h = float(region.width), float(region.height)
    steps: list[PathStep] = []
    for step, idx in enumerate(path, start=1):
        row, col = idx // 5, idx % 5
        cx = (col + 0.5) * w / 5.0
        cy = (row + 0.5) * h / 5.0
        steps.append(PathStep(x=cx, y=cy, step=step))
    return steps


class BoardHighlightOverlay(QWidget):
    """Click-through highlight drawn over the calibrated game board."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._steps: list[PathStep] = []

    def show_path(self, region: Region, path: list[int]) -> None:
        if not region.is_valid() or not path:
            self.hide()
            return
        self._steps = path_geometry(region, path)
        self.setGeometry(region.x, region.y, region.width, region.height)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.show()
        self.raise_()
        self.repaint()

    def clear(self) -> None:
        self._steps = []
        self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._steps:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        fill = QColor(0, 255, 120, 140)
        border = QColor(0, 255, 140, 255)
        line_pen = QPen(QColor(0, 255, 140, 240), 4)
        painter.setPen(line_pen)

        cell = min(self.width(), self.height()) / 5.0
        radius = max(14.0, cell * 0.36)

        points = [QPointF(s.x, s.y) for s in self._steps]
        if len(points) >= 2:
            for i in range(len(points) - 1):
                painter.drawLine(points[i], points[i + 1])

        font = QFont()
        font.setBold(True)
        font.setPointSize(max(9, int(cell * 0.22)))
        painter.setFont(font)

        for step, pt in zip(self._steps, points, strict=True):
            painter.setBrush(fill)
            painter.setPen(QPen(border, 2))
            painter.drawEllipse(pt, radius, radius)
            painter.setPen(QPen(QColor(10, 30, 20), 1))
            painter.drawText(
                int(pt.x() - radius),
                int(pt.y() - radius),
                int(radius * 2),
                int(radius * 2),
                int(Qt.AlignmentFlag.AlignCenter),
                str(step.step),
            )
