"""Sticker/stamp tray OCR stub — template matching can be added with game assets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from cursed_words_solver.models import Loadout, LoadoutItem

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "data" / "templates"


def match_tray_icons(tray_bgr: np.ndarray, max_slots: int = 5) -> list[LoadoutItem]:
    """
    Placeholder tray OCR: splits tray into slots and returns empty if no templates.
    Drop PNG icons into data/templates/{sticker_id}.png to enable matching.
    """
    if not TEMPLATE_DIR.exists():
        return []

    templates = list(TEMPLATE_DIR.glob("*.png"))
    if not templates:
        return []

    h, w = tray_bgr.shape[:2]
    slot_w = w // max_slots
    found: list[LoadoutItem] = []

    for i in range(max_slots):
        x0, x1 = i * slot_w, (i + 1) * slot_w
        slot = tray_bgr[:, x0:x1]
        if slot.size == 0:
            continue
        best_id = ""
        best_val = 0.0
        for tpl_path in templates:
            tpl = cv2.imread(str(tpl_path))
            if tpl is None or tpl.shape[0] > slot.shape[0]:
                continue
            res = cv2.matchTemplate(slot, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val > best_val and max_val > 0.55:
                best_val = max_val
                best_id = tpl_path.stem
        if best_id:
            found.append(
                LoadoutItem(
                    id=best_id,
                    name=best_id.replace("_", " ").title(),
                    level=1,
                    kind="sticker",
                )
            )
    return found


def detect_loadout_from_screen(
    tray_image: np.ndarray | None,
    run_state: Loadout | None,
) -> Loadout:
    """Prefer run_state; augment with tray OCR if templates exist."""
    base = run_state or Loadout()
    if tray_image is not None:
        detected = match_tray_icons(tray_image)
        if detected and not base.stickers:
            base.stickers = detected
    return base
