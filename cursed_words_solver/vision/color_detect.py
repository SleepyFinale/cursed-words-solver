"""Tile color classification from cell images."""

from __future__ import annotations

import cv2
import numpy as np

from cursed_words_solver.models import TileColor

# HSV ranges tuned for typical saturated UI tiles (adjust via calibration samples)
COLOR_RANGES: dict[TileColor, list[tuple[tuple[int, int, int], tuple[int, int, int]]]] = {
    TileColor.RED: [((0, 80, 80), (12, 255, 255)), ((165, 80, 80), (180, 255, 255))],
    TileColor.BLUE: [((95, 60, 60), (135, 255, 255))],
    TileColor.SHINY: [((15, 30, 180), (45, 120, 255)), ((0, 0, 200), (180, 50, 255))],
    TileColor.VOID: [((120, 20, 20), (150, 255, 120))],
    TileColor.PURPLE: [((135, 50, 50), (165, 255, 255))],
    TileColor.GOLD: [((18, 100, 120), (35, 255, 255))],
    TileColor.PINK: [((145, 50, 120), (175, 255, 255))],
    TileColor.GREEN: [((40, 60, 60), (85, 255, 255))],
    TileColor.WHITE: [((0, 0, 200), (180, 40, 255))],
}


def _mask_ratio(hsv: np.ndarray, low: tuple[int, int, int], high: tuple[int, int, int]) -> float:
    mask = cv2.inRange(hsv, np.array(low), np.array(high))
    return float(np.count_nonzero(mask)) / max(mask.size, 1)


def classify_tile_color(cell_bgr: np.ndarray) -> TileColor:
    """Classify tile color from border/background hues."""
    h, w = cell_bgr.shape[:2]
    # Sample border ring (outer 18%)
    margin = max(2, int(min(h, w) * 0.18))
    border = np.zeros((h, w), dtype=bool)
    border[:margin, :] = True
    border[-margin:, :] = True
    border[:, :margin] = True
    border[:, -margin:] = True
    border_pixels = cell_bgr[border]
    if border_pixels.size == 0:
        border_pixels = cell_bgr.reshape(-1, 3)
    hsv = cv2.cvtColor(border_pixels.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV)

    scores: dict[TileColor, float] = {c: 0.0 for c in COLOR_RANGES}
    for color, ranges in COLOR_RANGES.items():
        for low, high in ranges:
            mask = cv2.inRange(hsv, np.array(low), np.array(high))
            scores[color] = max(scores[color], float(np.count_nonzero(mask)) / len(hsv))

    # Shiny: high value center
    center = cell_bgr[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
    if center.size:
        v = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)[:, :, 2].mean()
        if v > 200:
            scores[TileColor.SHINY] += 0.15

    best = max(scores, key=scores.get)
    if scores[best] < 0.08:
        # Neutral gray board
        gray = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2GRAY)
        if gray.std() < 25:
            return TileColor.COLORLESS
        return TileColor.UNKNOWN
    return best
