"""Transparent on-game overlay highlighting consumable rack tiles to use."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from cursed_words_solver.config import Region
from cursed_words_solver.ui.board_geometry import (
    RackMarker,
    estimate_rack_slot_size,
    placement_rack_index,
    rack_badge_layout,
    rack_placement_geometry,
    rack_tile_side,
)

# Same amber family as the dashed placement rings on the board overlay, so the
# rack tile and its board destination read as a pair.
_BOX_FILL = QColor(255, 180, 40, 55)
_BOX_BORDER = QColor(255, 200, 60, 255)
_BOX_SHADOW = QColor(20, 10, 0, 170)
_BADGE_FILL = QColor(255, 190, 50, 255)
_BADGE_BORDER = QColor(40, 20, 0, 255)
_BADGE_TEXT = QColor(30, 15, 0)


class RackHighlightOverlay(QWidget):
    """Click-through highlight drawn over the consumable rack (both Stadium rows)."""

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
        self._rack_slot_centers_local: dict[int, tuple[float, float]] | None = None
        self._rack_slot_sizes: dict[int, tuple[float, float]] | None = None
        self._exported_rack_height: float | None = None

    @property
    def markers(self) -> list[RackMarker]:
        return list(self._markers)

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
            self.clear()
            return
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
        rack_placements = sum(
            1 for p in placements if placement_rack_index(p) >= 0
        )
        if len(self._markers) < rack_placements:
            known = sorted(rack_slot_centers) if rack_slot_centers else "none"
            print(
                f"  Overlay: {rack_placements - len(self._markers)} rack marker(s) "
                f"could not be placed (exported rack slots: {known}).",
                flush=True,
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
        self._rack_slot_centers_local = None
        self._rack_slot_sizes = None
        self._exported_rack_height = None
        self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._markers:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        region_w = float(self.width())
        region_h = float(self.height())
        slot_w, slot_h = estimate_rack_slot_size(
            Region(0, 0, self.width(), self.height()),
            self._rack_slot_centers_local,
            exported_rack_height=self._exported_rack_height,
            rack_slot_sizes=self._rack_slot_sizes,
        )
        tile = rack_tile_side(slot_w, slot_h, self._rack_slot_sizes)
        box = tile + 6.0
        corner = max(4.0, box * 0.14)

        # Pass 1: tile boxes (dark under-stroke keeps the amber edge visible on
        # shiny / bright tiles).
        painter.setBrush(_BOX_FILL)
        for marker in self._markers:
            rect = QRectF(marker.x - box / 2, marker.y - box / 2, box, box)
            painter.setPen(QPen(_BOX_SHADOW, 5.0))
            painter.drawRoundedRect(rect, corner, corner)
            painter.setPen(QPen(_BOX_BORDER, 3.0))
            painter.drawRoundedRect(rect, corner, corner)

        # Pass 2: numbered badges on top so overlapping neighbours stay legible.
        font = QFont()
        font.setBold(True)
        for marker in self._markers:
            cx, cy, radius = rack_badge_layout(marker.x, marker.y, box, region_w, region_h)
            font.setPixelSize(max(10, int(radius * 1.2)))
            painter.setFont(font)
            painter.setBrush(_BADGE_FILL)
            painter.setPen(QPen(_BADGE_BORDER, 2.0))
            painter.drawEllipse(QPointF(cx, cy), radius, radius)
            painter.setPen(QPen(_BADGE_TEXT, 1))
            painter.drawText(
                QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                int(Qt.AlignmentFlag.AlignCenter),
                str(marker.step),
            )
