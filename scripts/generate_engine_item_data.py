#!/usr/bin/env python3
"""Generate cursed_words_solver/engine/item_data.py from decompiled game sources.

usage: python scripts/generate_engine_item_data.py <decompiled-dir>

<decompiled-dir> is an ``ilspycmd -p`` project dump of Assembly-CSharp.dll (one
.cs file per type). Every ``: Item`` subclass with a ``Name`` contributes a row
keyed by the melmod slug (RunStateExporter.Slugify of the display name).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "cursed_words_solver" / "engine" / "item_data.py"

_COMPONENT_RE = re.compile(r"new UpgradeableComponent\((-?\d+),\s*(-?\d+),\s*(-?\d+)\)")
_TILE_TYPE_RE = re.compile(r"TileType\.(\w+)")


def slugify(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", name.lower()).strip("_")


def _constructor_body(src: str, cls: str) -> str:
    m = re.search(rf"public {cls}\(\)\s*\{{", src)
    if not m:
        return ""
    depth, i = 1, m.end()
    while i < len(src) and depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[m.end() : i]


def parse(path: Path) -> dict | None:
    src = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"public class (\w+) : Item\b", src)
    if not m:
        return None
    cls = m.group(1)
    body = _constructor_body(src, cls)
    name = re.search(r'\bName = "([^"]+)"', body)
    if not name:
        return None
    rarity = re.search(r"Rarity = ItemRarity\.(\w+)", body)
    cost = re.search(r"\bCost = (-?\d+)", body)
    colours: list[str] = []
    rc = re.search(r"RelevantColours = new List<TileType>\s*\{([^}]*)\}", body)
    if rc:
        colours = [c.lower() for c in _TILE_TYPE_RE.findall(rc.group(1))]
    return {
        "cls": cls,
        "name": name.group(1),
        "slug": slugify(name.group(1)),
        "rarity": rarity.group(1).lower() if rarity else "common",
        "cost": int(cost.group(1)) if cost else 0,
        "food": "IsFood = true" in body,
        "animal": "IsAnimal = true" in body,
        "components": [tuple(int(x) for x in c) for c in _COMPONENT_RE.findall(body)],
        "colours": colours,
    }


def main() -> int:
    src_dir = Path(sys.argv[1])
    rows = [r for p in sorted(src_dir.glob("*.cs")) if (r := parse(p))]
    by_slug: dict[str, dict] = {}
    for row in rows:
        # Sticker/StampPadlock share a display name; keep the first (both inert).
        by_slug.setdefault(row["slug"], row)
    lines = [
        '"""Item metadata generated from the game DLL — do not edit by hand.',
        "",
        "Regenerate: python scripts/generate_engine_item_data.py <ilspycmd -p dump>",
        "",
        "Each row: class name, rarity, shop cost, IsFood, IsAnimal, upgrade components",
        "(level, levelIncrement, initial VariableValue) and default RelevantColours.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import NamedTuple",
        "",
        "",
        "class ItemInfo(NamedTuple):",
        "    cls: str",
        "    rarity: str",
        "    cost: int",
        "    food: bool",
        "    animal: bool",
        "    components: tuple[tuple[int, int, int], ...]",
        "    colours: tuple[str, ...]",
        "",
        "",
        "ITEMS: dict[str, ItemInfo] = {",
    ]
    for slug in sorted(by_slug):
        r = by_slug[slug]
        lines.append(
            f"    {slug!r}: ItemInfo({r['cls']!r}, {r['rarity']!r}, {r['cost']}, "
            f"{r['food']}, {r['animal']}, {tuple(r['components'])!r}, {tuple(r['colours'])!r}),"
        )
    lines += ["}", "", "CLASS_TO_SLUG: dict[str, str] = {info.cls: slug for slug, info in ITEMS.items()}", ""]
    cls_to_slug = {r["cls"]: slug for slug, r in by_slug.items()}
    pools_src = (src_dir / "ScatteredItemPools.cs").read_text(encoding="utf-8", errors="replace")
    lines += ["# ScatteredItemPools lists (slugs), used to resolve legacy scatter levels.", "POOLS: dict[str, tuple[str, ...]] = {"]
    for name, body in re.findall(r"public static List<Item> (\w+) = new List<Item>\s*\{([^}]*)\}", pools_src):
        slugs = [cls_to_slug.get(c, c) for c in re.findall(r"new (\w+)\(\)", body)]
        lines.append(f"    {name!r}: {tuple(slugs)!r},")
    lines += ["}", ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {len(by_slug)} items -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
