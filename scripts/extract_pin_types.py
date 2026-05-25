#!/usr/bin/env python3
"""Reflect pin Item subclasses and overridden methods from Assembly-CSharp.dll."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "game" / "pin_subclasses.json"
DEFAULT_DLL = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Cursed Words"
) / "Cursed Words_Data" / "Managed" / "Assembly-CSharp.dll"

PIN_CLASSES = [
    "Abacus",
    "Bicycle",
    "SuperEight",
    "MilkyWay",
    "RandomAccessMemory",
    "Rainbow",
    "MahjongRedDragon",
    "WadOfCash",
    "Bucket",
    "CarpStreamers",
    "HumanHands",
]

PS = r"""
param([string]$DllPath)
$asm = [System.Reflection.Assembly]::LoadFrom($DllPath)
$item = $asm.GetType('Item')
$names = @(
'Abacus','Bicycle','SuperEight','MilkyWay','RandomAccessMemory','Rainbow',
'MahjongRedDragon','WadOfCash','Bucket','CarpStreamers','HumanHands'
)
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
    if ($m.Name -match 'ApplyStartOfGrid|ApplyTileBonus|ApplyWordBonus|StartOfEncounter') {
      $overrides += $m.Name
    }
  }
  $result += [ordered]@{ name = $n; overrides = $overrides }
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
    rows = json.loads(proc.stdout)
    payload = {"_meta": {"source": str(dll)}, "pins": rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(rows)} pin classes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
