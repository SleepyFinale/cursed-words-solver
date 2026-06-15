"""Transparent on-game overlay highlighting the best word path."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from cursed_words_solver.config import Region
from cursed_words_solver.models import Board
from cursed_words_solver.ui.board_geometry import (
    PathStep,
    PlacementMarker,
    path_geometry,
    placement_geometry,
    swap_geometry,
)

_GRID_SLOTS = 5


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
        self._placements: list[PlacementMarker] = []
        self._swap_markers: list[PlacementMarker] = []

    def show_path(
        self,
        region: Region,
        path: list[int],
        board: Board | None = None,
        *,
        placements: list[Any] | None = None,
        twinkle_toes_swap: Any | None = None,
        cell_centers: dict[int, tuple[float, float]] | None = None,
    ) -> None:
        if not region.is_valid() or (not path and not placements and not twinkle_toes_swap):
            self.hide()
            return
        self._steps = (
            path_geometry(region, path, board, cell_centers=cell_centers) if path else []
        )
        self._placements = (
            placement_geometry(region, placements, board, cell_centers=cell_centers)
            if placements
            else []
        )
        self._swap_markers = (
            swap_geometry(region, twinkle_toes_swap, board, cell_centers=cell_centers)
            if twinkle_toes_swap
            else []
        )
        self.setGeometry(region.x, region.y, region.width, region.height)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.show()
        self.raise_()
        self.repaint()

    def clear(self) -> None:
        self._steps = []
        self._placements = []
        self._swap_markers = []
        self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._steps and not self._placements and not self._swap_markers:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cell = min(self.width(), self.height()) / float(_GRID_SLOTS)
        radius = max(14.0, cell * 0.36)

        font = QFont()
        font.setBold(True)
        font.setPointSize(max(9, int(cell * 0.22)))
        painter.setFont(font)

        for marker in self._swap_markers:
            pt = QPointF(marker.x, marker.y)
            painter.setBrush(QColor(255, 105, 180, 95))
            painter.setPen(QPen(QColor(255, 50, 160, 255), 3, Qt.PenStyle.DashLine))
            painter.drawEllipse(pt, radius * 1.08, radius * 1.08)

        for marker in self._placements:
            pt = QPointF(marker.x, marker.y)
            painter.setBrush(QColor(255, 180, 40, 90))
            painter.setPen(QPen(QColor(255, 200, 60, 255), 3, Qt.PenStyle.DashLine))
            painter.drawEllipse(pt, radius * 1.08, radius * 1.08)

        fill = QColor(0, 255, 120, 140)
        border = QColor(0, 255, 140, 255)
        line_pen = QPen(QColor(0, 255, 140, 240), 4)
        painter.setPen(line_pen)

        points = [QPointF(s.x, s.y) for s in self._steps]
        if len(points) >= 2:
            for i in range(len(points) - 1):
                painter.drawLine(points[i], points[i + 1])

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
