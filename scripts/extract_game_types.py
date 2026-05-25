#!/usr/bin/env python3
"""Reflect game Item subclasses from Assembly-CSharp.dll (local Steam install)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "game" / "item_subclasses.json"
DEFAULT_DLL = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Cursed Words"
) / "Cursed Words_Data" / "Managed" / "Assembly-CSharp.dll"

PS = r"""
param([string]$DllPath)
$asm = [System.Reflection.Assembly]::LoadFrom($DllPath)
$item = $asm.GetType('Item')
$subs = $asm.GetTypes() | Where-Object {
    $_.IsClass -and -not $_.IsAbstract -and $item.IsAssignableFrom($_) -and $_ -ne $item
} | Sort-Object Name
$result = @()
foreach ($t in $subs) {
    $methods = $t.GetMethods([System.Reflection.BindingFlags]::Instance -bor `
        [System.Reflection.BindingFlags]::DeclaredOnly -bor `
        [System.Reflection.BindingFlags]::Public -bor `
        [System.Reflection.BindingFlags]::NonPublic)
    $overrides = @()
    foreach ($m in $methods) {
        if ($m.Name -in @('ApplyStartOfGridEffect','ApplyItemToScore','ApplyTileBonus','ApplyWordBonus','StartOfEncounterSetUp')) {
            $decl = $m.DeclaringType.Name
            if ($decl -eq $t.Name) { $overrides += $m.Name }
        }
    }
    $result += [ordered]@{ name = $t.Name; overrides = $overrides }
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
    payload = {
        "_meta": {"source": str(dll), "count": len(rows)},
        "subclasses": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(rows)} Item subclasses)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
