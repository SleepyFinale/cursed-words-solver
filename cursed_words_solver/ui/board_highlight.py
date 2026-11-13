"""Transparent on-game overlay highlighting the best word path."""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from cursed_words_solver.config import Region
from cursed_words_solver.models import Board
from cursed_words_solver.ui.board_geometry import (
    PathStep,
    PlacementMarker,
    board_cell_pitch,
    path_geometry,
    path_step_hue,
    placement_geometry,
    swap_geometry,
    trim_segment,
)

_GRID_SLOTS = 5
_OUTLINE = QColor(10, 20, 15, 200)
_BADGE_TEXT = QColor(10, 20, 15)
# Badge corners for repeat visits to the same tile: TL, TR, BR, BL.
_BADGE_CORNERS = ((-1, -1), (1, -1), (1, 1), (-1, 1))


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
        self._pitch: float | None = None

    def show_path(
        self,
        region: Region,
        path: list[int],
        board: Board | None = None,
        *,
        placements: list[Any] | None = None,
        twinkle_toes_swap: Any | None = None,
        cell_centers: dict[int, tuple[float, float]] | None = None,
        wrapping: bool = False,
    ) -> None:
        if not region.is_valid() or (not path and not placements and not twinkle_toes_swap):
            self.hide()
            return
        self._steps = (
            path_geometry(region, path, board, cell_centers=cell_centers, wrapping=wrapping)
            if path
            else []
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
        self._pitch = board_cell_pitch(region, board, cell_centers)
        self.setGeometry(region.x, region.y, region.width, region.height)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.show()
        self.raise_()
        self.repaint()

    def clear(self) -> None:
        self._steps = []
        self._placements = []
        self._swap_markers = []
        self._pitch = None
        self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._steps and not self._placements and not self._swap_markers:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pitch = self._pitch or min(self.width(), self.height()) / float(_GRID_SLOTS)
        ring_r = max(14.0, pitch * 0.32)

        for marker in self._swap_markers:
            pt = QPointF(marker.x, marker.y)
            painter.setBrush(QColor(255, 105, 180, 60))
            painter.setPen(QPen(QColor(255, 50, 160, 255), 3, Qt.PenStyle.DashLine))
            painter.drawEllipse(pt, ring_r * 1.12, ring_r * 1.12)

        for marker in self._placements:
            pt = QPointF(marker.x, marker.y)
            painter.setBrush(QColor(255, 180, 40, 60))
            painter.setPen(QPen(QColor(255, 200, 60, 255), 3, Qt.PenStyle.DashLine))
            painter.drawEllipse(pt, ring_r * 1.12, ring_r * 1.12)

        if self._steps:
            self._paint_path(painter, pitch, ring_r)

    def _paint_path(self, painter: QPainter, pitch: float, ring_r: float) -> None:
        steps = self._steps
        n = len(steps)
        colors = [_step_color(i, n) for i in range(n)]
        line_w = max(3.0, pitch * 0.045)
        gap = ring_r + 2.0

        # 1) Connectors trimmed to the rings so they never cross tile letters.
        segments: list[tuple[int, QPointF, QPointF, bool]] = []
        for i in range(1, n):
            a = (steps[i - 1].x, steps[i - 1].y)
            b = (steps[i].x, steps[i].y)
            wrap = steps[i].wrap
            if not wrap:
                seg = trim_segment(a, b, gap, gap)
                if seg is not None:
                    segments.append((i, QPointF(*seg[0]), QPointF(*seg[1]), False))
                continue
            # Hungry Snake wrap: run off one side and back in from the other
            # instead of a straight line across the whole row.
            mid_y = (a[1] + b[1]) / 2.0
            exit_x, enter_x = (
                (float(self.width()), 0.0) if wrap > 0 else (0.0, float(self.width()))
            )
            out = trim_segment(a, (exit_x, mid_y), gap, 0.0)
            back = trim_segment((enter_x, mid_y), b, 0.0, gap)
            if out is not None:
                segments.append((i, QPointF(*out[0]), QPointF(*out[1]), True))
            if back is not None:
                segments.append((i, QPointF(*back[0]), QPointF(*back[1]), True))

        cap = Qt.PenCapStyle.RoundCap
        # Dark under-strokes first, so crossings stay distinguishable.
        for _i, p0, p1, dashed in segments:
            style = Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine
            painter.setPen(QPen(_OUTLINE, line_w + 4.0, style, cap))
            painter.drawLine(p0, p1)
        for i, p0, p1, dashed in segments:
            style = Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine
            painter.setPen(QPen(colors[i - 1], line_w, style, cap))
            painter.drawLine(p0, p1)
            if not dashed:
                _draw_arrowhead(painter, p0, p1, max(7.0, pitch * 0.09), colors[i - 1])

        # 2) Hollow rings around each tile (letter stays readable).
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i, step in enumerate(steps):
            pt = QPointF(step.x, step.y)
            width = 5.0 if i == 0 else 3.0
            painter.setPen(QPen(_OUTLINE, width + 3.0))
            painter.drawEllipse(pt, ring_r, ring_r)
            painter.setPen(QPen(colors[i], width))
            painter.drawEllipse(pt, ring_r, ring_r)
            if i == n - 1 and n > 1:
                # Finish: extra white ring so the last tile is unmistakable.
                painter.setPen(QPen(QColor(255, 255, 255, 230), 2.0))
                painter.drawEllipse(pt, ring_r + 4.0, ring_r + 4.0)

        # 3) Numbered badges on the ring's corner, drawn last so connectors
        #    never cover them.
        badge_r = max(10.0, min(16.0, pitch * 0.15))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(10, int(badge_r * 1.15)))
        painter.setFont(font)
        visits: dict[tuple[int, int], int] = {}
        diag = ring_r * 0.72
        for i, step in enumerate(steps):
            key = (round(step.x), round(step.y))
            k = visits.get(key, 0)
            visits[key] = k + 1
            sx, sy = _BADGE_CORNERS[k % len(_BADGE_CORNERS)]
            cx = min(max(step.x + sx * diag, badge_r + 1), self.width() - badge_r - 1)
            cy = min(max(step.y + sy * diag, badge_r + 1), self.height() - badge_r - 1)
            painter.setBrush(colors[i])
            painter.setPen(QPen(_OUTLINE, 2.0))
            painter.drawEllipse(QPointF(cx, cy), badge_r, badge_r)
            painter.setPen(QPen(_BADGE_TEXT, 1))
            painter.drawText(
                QRectF(cx - badge_r, cy - badge_r, badge_r * 2, badge_r * 2),
                int(Qt.AlignmentFlag.AlignCenter),
                str(step.step),
            )


def _step_color(index: int, total: int) -> QColor:
    return QColor.fromHsvF(path_step_hue(index, total) / 360.0, 0.85, 1.0, 1.0)


def _draw_arrowhead(
    painter: QPainter, p0: QPointF, p1: QPointF, size: float, color: QColor
) -> None:
    """Small direction chevron at the segment midpoint."""
    dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
    length = math.hypot(dx, dy)
    if length < size * 1.5:
        return
    ux, uy = dx / length, dy / length
    mx = (p0.x() + p1.x()) / 2.0 + ux * size * 0.5
    my = (p0.y() + p1.y()) / 2.0 + uy * size * 0.5
    px, py = -uy, ux
    tri = QPolygonF(
        [
            QPointF(mx, my),
            QPointF(mx - ux * size + px * size * 0.6, my - uy * size + py * size * 0.6),
            QPointF(mx - ux * size - px * size * 0.6, my - uy * size - py * size * 0.6),
        ]
    )
    painter.setBrush(color)
    painter.setPen(QPen(_OUTLINE, 1.5))
    painter.drawPolygon(tri)
