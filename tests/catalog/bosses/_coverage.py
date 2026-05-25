"""Boss catalog coverage helpers."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data" / "wiki" / "stickers.json"


def boss_entries() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8")).get("bosses", {})
