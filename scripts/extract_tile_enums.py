#!/usr/bin/env python3
"""Reflect TileType, GlyphType, ChessPiece, Suit from Assembly-CSharp.dll."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "game" / "tile_enums.json"
DEFAULT_DLL = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Cursed Words"
) / "Cursed Words_Data" / "Managed" / "Assembly-CSharp.dll"

PS = r"""
param([string]$DllPath)
$asm = [System.Reflection.Assembly]::LoadFrom($DllPath)
$names = @('TileType','GlyphType','ChessPiece','Suit')
$result = [ordered]@{}
foreach ($n in $names) {
  $t = $asm.GetType($n)
  if (-not $t) { continue }
  $vals = [Enum]::GetNames($t) | ForEach-Object {
    [ordered]@{ name = $_; value = [int][Enum]::Parse($t, $_) }
  }
  $result[$n] = $vals
}
$result | ConvertTo-Json -Depth 4
"""


def main() -> int:
    dll = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DLL
    if not dll.is_file():
        print(f"Assembly not found: {dll}", file=sys.stderr)
        return 1
    ps_cmd = f"$DllPath = '{dll}'; " + PS.replace("param([string]$DllPath)", "").strip()
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout, file=sys.stderr)
        return proc.returncode
    enums = json.loads(proc.stdout)
    payload = {"_meta": {"source": str(dll)}, "enums": enums}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")
    for key, vals in enums.items():
        print(f"  {key}: {len(vals)} values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
