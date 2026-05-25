#!/usr/bin/env python3
"""Map wiki stamp slugs to game Item subclasses and scoring override methods."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "game" / "stamp_subclasses.json"
CATALOG = ROOT / "data" / "wiki" / "stickers.json"
DEFAULT_DLL = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Cursed Words"
) / "Cursed Words_Data" / "Managed" / "Assembly-CSharp.dll"

HOOK_METHODS = (
    "ApplyStartOfGridEffect",
    "ApplyItemToScore",
    "ApplyTileBonus",
    "ApplyWordBonus",
    "StartOfEncounterSetUp",
)

PS_TEMPLATE = r"""
param([string]$DllPath, [string]$ClassNamesJson)
$asm = [System.Reflection.Assembly]::LoadFrom($DllPath)
$names = $ClassNamesJson | ConvertFrom-Json
$result = @()
foreach ($n in $names) {
  $t = $asm.GetType($n)
  if (-not $t) { continue }
  $overrides = @()
  $methods = $t.GetMethods([System.Reflection.BindingFlags]::Instance -bor `
    [System.Reflection.BindingFlags]::DeclaredOnly -bor `
    [System.Reflection.BindingFlags]::Public -bor `
    [System.Reflection.BindingFlags]::NonPublic)
  foreach ($m in $methods) {
    if ($m.Name -match 'ApplyStartOfGrid|ApplyTileBonus|ApplyWordBonus|ApplyItemToScore|StartOfEncounter') {
      if ($m.DeclaringType.Name -eq $n) { $overrides += $m.Name }
    }
  }
  $result += [ordered]@{ name = $n; overrides = $overrides }
}
$result | ConvertTo-Json -Depth 4
"""


def slug_to_pascal(slug: str) -> str:
    parts = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_").split("_")
    return "".join(p.capitalize() for p in parts if p)


def main() -> int:
    dll = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DLL
    if not CATALOG.is_file():
        print(f"Missing catalog: {CATALOG}", file=sys.stderr)
        return 1

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    stamp_slugs = sorted(catalog.get("stamps", {}).keys())
    subclasses_path = ROOT / "data" / "game" / "item_subclasses.json"
    known: set[str] = set()
    if subclasses_path.is_file():
        data = json.loads(subclasses_path.read_text(encoding="utf-8"))
        known = {r["name"] for r in data.get("subclasses", [])}

    rows: list[dict] = []
    class_names: list[str] = []
    for slug in stamp_slugs:
        gc = slug_to_pascal(slug)
        in_game = gc in known
        rows.append({"slug": slug, "game_class": gc, "in_subclasses": in_game})
        if in_game:
            class_names.append(gc)

    overrides_by_name: dict[str, list[str]] = {}
    if dll.is_file() and class_names:
        names_json = json.dumps(class_names)
        ps_cmd = (
            f"$DllPath = '{dll}'; $ClassNamesJson = '{names_json}'; "
            + PS_TEMPLATE.replace("param([string]$DllPath, [string]$ClassNamesJson)", "").strip()
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            for entry in json.loads(proc.stdout):
                overrides_by_name[entry["name"]] = entry.get("overrides", [])

    for row in rows:
        gc = row["game_class"]
        row["overrides"] = overrides_by_name.get(gc, [])

    matched = sum(1 for r in rows if r["in_subclasses"])
    payload = {
        "_meta": {"source": str(dll), "catalog_stamps": len(rows), "matched": matched},
        "stamps": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({matched}/{len(rows)} matched game classes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
