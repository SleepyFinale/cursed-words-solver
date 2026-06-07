"""Transparent on-game overlay highlighting consumable rack tiles to use."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from cursed_words_solver.config import Region
from cursed_words_solver.ui.board_geometry import (
    RACK_MARKER_PEN_WIDTH,
    RackMarker,
    estimate_rack_slot_size,
    rack_marker_radius,
    rack_placement_geometry,
)


class RackHighlightOverlay(QWidget):
    """Click-through highlight drawn over the calibrated consumable rack row."""

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
        self._markers: list[RackMarker] = []
        self._rack_slot_centers: dict[int, tuple[float, float]] | None = None
        self._rack_slot_centers_local: dict[int, tuple[float, float]] | None = None
        self._rack_slot_sizes: dict[int, tuple[float, float]] | None = None
        self._exported_rack_height: float | None = None

    def show_placements(
        self,
        region: Region,
        path: list[int],
        placements: list | None,
        *,
        rack_slot_centers: dict[int, tuple[float, float]] | None = None,
        rack_slot_sizes: dict[int, tuple[float, float]] | None = None,
        rack_tile_height: int | None = None,
    ) -> None:
        if not region.is_valid() or not path or not placements:
            self.hide()
            return
        self._rack_slot_centers = rack_slot_centers
        self._rack_slot_centers_local = (
            {
                idx: (x - float(region.x), y - float(region.y))
                for idx, (x, y) in rack_slot_centers.items()
            }
            if rack_slot_centers
            else None
        )
        self._rack_slot_sizes = rack_slot_sizes
        self._exported_rack_height = (
            float(rack_tile_height) if rack_tile_height and rack_tile_height > 0 else None
        )
        self._markers = rack_placement_geometry(
            region,
            path,
            placements,
            rack_slot_centers=rack_slot_centers,
        )
        if not self._markers:
            self.hide()
            return
        self.setGeometry(region.x, region.y, region.width, region.height)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.show()
        self.raise_()
        self.repaint()

    def clear(self) -> None:
        self._markers = []
        self._rack_slot_centers = None
        self._rack_slot_centers_local = None
        self._rack_slot_sizes = None
        self._exported_rack_height = None
        self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._markers:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        region = Region(0, 0, self.width(), self.height())
        slot_w, slot_h = estimate_rack_slot_size(
            region,
            self._rack_slot_centers_local,
            exported_rack_height=self._exported_rack_height,
            rack_slot_sizes=self._rack_slot_sizes,
        )
        ref_size = min(slot_w, slot_h)

        font = QFont()
        font.setBold(True)
        font.setPointSize(max(8, int(ref_size * 0.24)))
        painter.setFont(font)

        fill = QColor(255, 180, 40, 140)
        border = QColor(255, 200, 60, 255)
        region_w = float(self.width())
        region_h = float(self.height())
        for marker in self._markers:
            radius = rack_marker_radius(
                marker.x,
                marker.y,
                slot_w,
                slot_h,
                region_w,
                region_h,
                pen_width=RACK_MARKER_PEN_WIDTH,
            )
            if radius <= 0:
                continue
            pt = QPointF(marker.x, marker.y)
            painter.setBrush(fill)
            painter.setPen(QPen(border, RACK_MARKER_PEN_WIDTH))
            painter.drawEllipse(pt, radius, radius)
            painter.setPen(QPen(QColor(60, 30, 0), 1))
            painter.drawText(
                int(pt.x() - radius),
                int(pt.y() - radius),
                int(radius * 2),
                int(radius * 2),
                int(Qt.AlignmentFlag.AlignCenter),
                str(marker.step),
            )
