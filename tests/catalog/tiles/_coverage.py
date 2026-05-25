"""Taxonomy coverage helpers for tile catalog tests."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TAXONOMY = ROOT / "data" / "game" / "tile_taxonomy.json"


def load_taxonomy() -> dict:
    return json.loads(TAXONOMY.read_text(encoding="utf-8"))


def color_entries() -> list[dict]:
    return load_taxonomy().get("colors", [])


def curse_entries() -> list[dict]:
    return load_taxonomy().get("curses", [])
