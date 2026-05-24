"""Transparent on-game overlay highlighting the best word path."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from cursed_words_solver.config import Region
from cursed_words_solver.models import Board

_GRID_SLOTS = 5


def playable_bounds(board: Board) -> tuple[int, int, int, int] | None:
    """Return (min_row, max_row, min_col, max_col) for active playable cells."""
    min_r, max_r, min_c, max_c = _GRID_SLOTS, -1, _GRID_SLOTS, -1
    for r in range(_GRID_SLOTS):
        for c in range(_GRID_SLOTS):
            if board.is_active_cell(r, c):
                min_r = min(min_r, r)
                max_r = max(max_r, r)
                min_c = min(min_c, c)
                max_c = max(max_c, c)
    if max_r < 0:
        return None
    return min_r, max_r, min_c, max_c


def _is_shrunk_grid(board: Board) -> bool:
    return board.rows < _GRID_SLOTS or board.cols < _GRID_SLOTS


@dataclass(frozen=True)
class PathStep:
    """Center of a tile in overlay-local coordinates and draw order (1-based)."""

    x: float
    y: float
    step: int


def path_geometry(
    region: Region,
    path: list[int],
    board: Board | None = None,
) -> list[PathStep]:
    """Map tile indices to centers within a board region (overlay-local coords).

    Indices use the solver's 5×5 storage (row 0 = top). For shrunk Bat-style
    grids the active block may occupy storage rows 2–4 while the game renders
    those tiles centered in the calibrated 5×5 frame (e.g. 4×3 in slots 1–3).
    """
    if not region.is_valid() or not path:
        return []
    w, h = float(region.width), float(region.height)
    slot_w = w / float(_GRID_SLOTS)
    slot_h = h / float(_GRID_SLOTS)

    bounds = playable_bounds(board) if board else None
    shrunk = board is not None and _is_shrunk_grid(board) and bounds is not None
    if shrunk:
        min_r, max_r, min_c, max_c = bounds
        playable_h = max_r - min_r + 1
        playable_w = max_c - min_c + 1
        # Use half-slot margins so 4×N grids center in the 5×5 frame (not left-flush).
        row_margin = (_GRID_SLOTS - playable_h) / 2.0
        col_margin = (_GRID_SLOTS - playable_w) / 2.0

    steps: list[PathStep] = []
    for step, idx in enumerate(path, start=1):
        row, col = idx // _GRID_SLOTS, idx % _GRID_SLOTS
        if shrunk:
            slot_row = row - min_r + row_margin
            slot_col = col - min_c + col_margin
        else:
            slot_row = row
            slot_col = col
        cx = (slot_col + 0.5) * slot_w
        cy = (slot_row + 0.5) * slot_h
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

    def show_path(
        self,
        region: Region,
        path: list[int],
        board: Board | None = None,
    ) -> None:
        if not region.is_valid() or not path:
            self.hide()
            return
        self._steps = path_geometry(region, path, board)
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

        cell = min(self.width(), self.height()) / float(_GRID_SLOTS)
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
