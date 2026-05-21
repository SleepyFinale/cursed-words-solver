"""Screen capture utilities."""

from __future__ import annotations

from pathlib import Path

import mss
import numpy as np
from PIL import Image

from cursed_words_solver.config import Region


def screen_relative_origin(region: Region, screen_x: int, screen_y: int) -> tuple[int, int]:
    """Convert virtual-desktop coords to position relative to a screen origin."""
    return region.x - screen_x, region.y - screen_y


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
    from PySide6.QtGui import QGuiApplication, QImage

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
    qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
    w, h = qimg.width(), qimg.height()
    if w <= 0 or h <= 0:
        raise ValueError("Qt capture returned empty image; recalibrate board region")
    bytes_per_line = qimg.bytesPerLine()
    ptr = qimg.bits()
    ptr.setsize(h * bytes_per_line)
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bytes_per_line))
    rgb = arr[:, : w * 3].reshape((h, w, 3)).copy()
    return rgb[:, :, ::-1]


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


def capture_full_screen() -> np.ndarray:
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        return np.array(shot)[:, :, :3]


def save_debug_image(img: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if img is None or img.size == 0:
        raise ValueError(f"Cannot save empty image to {path}")
    Image.fromarray(img[:, :, ::-1]).save(path)
