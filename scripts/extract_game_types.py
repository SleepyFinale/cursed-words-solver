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

function EnumNames($list) {
    if ($null -eq $list) { return @() }
    $names = @()
    foreach ($v in $list) {
        if ($null -ne $v) { $names += $v.ToString() }
    }
    return $names
}

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
    $tags = @()
    $dependencyTags = @()
    $shopAdviceAdditionalTags = @()
    $functionTags = @()
    $blacklisted = $false
    try {
        $instance = [Activator]::CreateInstance($t)
        $tags = EnumNames $instance.Tags
        $dependencyTags = EnumNames $instance.DependencyTags
        $shopAdviceAdditionalTags = EnumNames $instance.ShopAdviceAdditionalTags
        $functionTags = EnumNames $instance.ItemFunctionTags
        $blacklisted = [bool]$instance.IsBlacklistedFromShopRecommendations
    } catch {
        # keep empty tag lists when instantiation fails
    }
    $shopAdviceTags = @($tags + $shopAdviceAdditionalTags | Select-Object -Unique)
    $result += [ordered]@{
        name = $t.Name
        overrides = $overrides
        tags = $tags
        dependency_tags = $dependencyTags
        shop_advice_additional_tags = $shopAdviceAdditionalTags
        shop_advice_tags = $shopAdviceTags
        function_tags = $functionTags
        blacklisted_from_shop_recommendations = $blacklisted
    }
}
$result | ConvertTo-Json -Depth 6
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

    def _as_str_list(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value if v]
        if isinstance(value, str) and value:
            return [value]
        return []

    tag_fields = (
        "tags",
        "dependency_tags",
        "shop_advice_additional_tags",
        "shop_advice_tags",
        "function_tags",
    )
    for row in rows:
        for key in tag_fields:
            row[key] = _as_str_list(row.get(key))
        row["blacklisted_from_shop_recommendations"] = bool(
            row.get("blacklisted_from_shop_recommendations", False)
        )

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
