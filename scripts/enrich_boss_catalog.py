#!/usr/bin/env python3
"""Merge boss_taxonomy.json fields into data/wiki/stickers.json bosses bucket."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAX = ROOT / "data" / "game" / "boss_taxonomy.json"
CATALOG = ROOT / "data" / "wiki" / "stickers.json"


def main() -> int:
    tax = json.loads(TAX.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    bosses = catalog.setdefault("bosses", {})
    for slug, fields in tax.get("bosses", {}).items():
        if slug not in bosses:
            continue
        entry = bosses[slug]
        if fields.get("game_class"):
            entry["game_class"] = fields["game_class"]
        if fields.get("effect_class"):
            entry["effect_class"] = fields["effect_class"]
        if fields.get("grid_handler"):
            entry["grid_handler"] = fields["grid_handler"]
        if fields.get("effect_type") and entry.get("type") == "custom":
            entry["boss_effect_type"] = fields["effect_type"]
    CATALOG.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Enriched {len(tax.get('bosses', {}))} bosses in {CATALOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
