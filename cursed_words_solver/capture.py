"""Screen capture utilities."""

from __future__ import annotations

from pathlib import Path

import cv2
import mss
import numpy as np
from PIL import Image

from cursed_words_solver.config import Region


def screen_relative_origin(region: Region, screen_x: int, screen_y: int) -> tuple[int, int]:
    """Convert virtual-desktop coords to position relative to a screen origin."""
    return region.x - screen_x, region.y - screen_y


def _virtual_desktop_bounds() -> tuple[int, int, int, int]:
    """Return (x, y, width, height) covering all connected monitors."""
    try:
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.instance() is not None:
            bounds = QRect()
            for screen in QGuiApplication.screens():
                bounds = bounds.united(screen.geometry())
            if bounds.width() > 0 and bounds.height() > 0:
                return bounds.x(), bounds.y(), bounds.width(), bounds.height()
    except Exception:
        pass

    with mss.mss() as sct:
        monitor = sct.monitors[0]
        return (
            int(monitor["left"]),
            int(monitor["top"]),
            int(monitor["width"]),
            int(monitor["height"]),
        )


def _pixmap_to_bgr(pixmap) -> np.ndarray:
    from PySide6.QtGui import QImage

    qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
    w, h = qimg.width(), qimg.height()
    if w <= 0 or h <= 0:
        raise ValueError("Qt capture returned empty image")
    bytes_per_line = qimg.bytesPerLine()
    ptr = qimg.bits()
    ptr.setsize(h * bytes_per_line)
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bytes_per_line))
    rgb = arr[:, : w * 3].reshape((h, w, 3)).copy()
    return rgb[:, :, ::-1]


def _capture_region_mss(region: Region) -> np.ndarray:
    with mss.mss() as sct:
        monitor = {
            "left": region.x,
            "top": region.y,
            "width": region.width,
            "height": region.height,
        }
        shot = sct.grab(monitor)
        return np.array(shot)[:, :, :3]


def _capture_region_qt(region: Region) -> np.ndarray:
    """Capture using Qt (matches calibration coordinate system on HiDPI displays)."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        raise RuntimeError("Qt application required for screen capture")

    pt = QPoint(region.x, region.y)
    screen = QGuiApplication.screenAt(pt) or QGuiApplication.primaryScreen()
    if screen is None:
        raise RuntimeError("No screen available for capture")

    geo = screen.geometry()
    rel_x, rel_y = screen_relative_origin(region, geo.x(), geo.y())
    pixmap = screen.grabWindow(0, rel_x, rel_y, region.width, region.height)
    dpr = float(pixmap.devicePixelRatio() or 1.0)
    if (
        dpr > 1.0
        and (pixmap.width() != region.width or pixmap.height() != region.height)
    ):
        from PySide6.QtCore import Qt

        pixmap = pixmap.scaled(
            region.width,
            region.height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return _pixmap_to_bgr(pixmap)


def capture_region(region: Region) -> np.ndarray:
    """Capture screen region as BGR numpy array."""
    if not region.is_valid():
        raise ValueError("Invalid capture region; run calibration first.")

    try:
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.instance() is not None:
            return _capture_region_qt(region)
    except Exception:
        pass

    return _capture_region_mss(region)


def capture_virtual_desktop() -> tuple[np.ndarray, int, int]:
    """Capture the full virtual desktop; return (bgr, origin_x, origin_y)."""
    origin_x, origin_y, width, height = _virtual_desktop_bounds()
    region = Region(x=origin_x, y=origin_y, width=width, height=height)
    return capture_region(region), origin_x, origin_y


def save_calibration_debug_image(
    board: Region,
    rack: Region | None,
    path: Path,
) -> None:
    """Save a full-desktop screenshot with overlay region rectangles drawn."""
    img, origin_x, origin_y = capture_virtual_desktop()
    if board.is_valid():
        x1 = board.x - origin_x
        y1 = board.y - origin_y
        x2 = x1 + board.width
        y2 = y1 + board.height
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 200, 255), 3)
        cv2.putText(
            img,
            "board",
            (x1 + 4, max(20, y1 + 24)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 200, 255),
            2,
            cv2.LINE_AA,
        )
    if rack is not None and rack.is_valid():
        x1 = rack.x - origin_x
        y1 = rack.y - origin_y
        x2 = x1 + rack.width
        y2 = y1 + rack.height
        cv2.rectangle(img, (x1, y1), (x2, y2), (255, 180, 40), 3)
        cv2.putText(
            img,
            "rack",
            (x1 + 4, max(20, y1 + 24)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 180, 40),
            2,
            cv2.LINE_AA,
        )
    save_debug_image(img, path)


def capture_full_screen() -> np.ndarray:
    img, _, _ = capture_virtual_desktop()
    return img


def save_debug_image(img: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if img is None or img.size == 0:
        raise ValueError(f"Cannot save empty image to {path}")
    Image.fromarray(img[:, :, ::-1]).save(path)
