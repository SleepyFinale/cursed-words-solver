#!/usr/bin/env python3
"""Reflect run-level game data (items, characters, bosses) from Assembly-CSharp.dll.

Writes ``data/game/run_catalog.json`` for the full-run simulator (``sim/``):

- items: rarity, base cost, sell cost, slot (stamp/sticker/pin by
  ``UpgradeableComponents.Count`` — same rule as ``ItemPools.AddItemsToPools``),
  upgradeable component values, tags, food/animal flags
- characters: pin (character item) type and starter-item pool (``_goodIntroItemTypes``)
- bosses: banned floor indexes, difficulty curves, secret / Michael-summonable flags
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "game" / "run_catalog.json"
DEFAULT_DLL = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Cursed Words"
) / "Cursed Words_Data" / "Managed" / "Assembly-CSharp.dll"

PS = r"""
$asm = [System.Reflection.Assembly]::LoadFrom($DllPath)
$bf = [System.Reflection.BindingFlags]'Instance,Public,NonPublic'

function EnumNames($list) {
    $names = @()
    if ($null -eq $list) { return ,$names }
    foreach ($v in $list) { if ($null -ne $v) { $names += $v.ToString() } }
    return ,$names
}
function IntList($list) {
    $out = @()
    if ($null -eq $list) { return ,$out }
    foreach ($v in $list) { $out += [int]$v }
    return ,$out
}

$itemBase = $asm.GetType('Item')
$items = @()
foreach ($t in ($asm.GetTypes() | Where-Object { $_.IsClass -and -not $_.IsAbstract -and $itemBase.IsAssignableFrom($_) -and $_ -ne $itemBase } | Sort-Object Name)) {
    $row = [ordered]@{ type = $t.Name; ok = $false }
    try {
        $i = [Activator]::CreateInstance($t)
        $comps = @()
        foreach ($c in $i.UpgradeableComponents) {
            $comps += [ordered]@{ level = [int]$c.Level; increment = [int]$c.GetLevelIncrement(); value = [int]$c.VariableValue }
        }
        $n = $comps.Count
        $slot = if ($n -eq 0) { 'stamp' } elseif ($n -eq 1) { 'sticker' } elseif ($n -eq 2) { 'pin' } else { 'other' }
        $row.name = [string]$i.Name
        $row.rarity = $i.Rarity.ToString()
        $row.cost = [int]$i.Cost
        $row.sell_cost = [int]$i.SellCost
        $row.slot = $slot
        $row.components = $comps
        $row.tags = EnumNames $i.Tags
        $row.dependency_tags = EnumNames $i.DependencyTags
        $row.function_tags = EnumNames $i.ItemFunctionTags
        $row.relevant_colours = EnumNames $i.RelevantColours
        $row.is_food = [bool]$i.IsFood
        $row.is_animal = [bool]$i.IsAnimal
        $row.selling_prevented = [bool]$i.IsSellingPrevented
        $row.ok = $true
    } catch {
        $row.error = $_.Exception.InnerException.Message
    }
    $items += $row
}

$charBase = $asm.GetType('Character')
$chars = @()
foreach ($t in ($asm.GetTypes() | Where-Object { $_.IsClass -and -not $_.IsAbstract -and $_.IsSubclassOf($charBase) } | Sort-Object Name)) {
    $row = [ordered]@{ type = $t.Name; ok = $false }
    try {
        $c = [Activator]::CreateInstance($t)
        $row.name = [string]$c.GetName()
        $row.pin = if ($null -ne $c.CharacterItem) { $c.CharacterItem.GetType().Name } else { $null }
        $intro = @()
        foreach ($x in $charBase.GetField('_goodIntroItemTypes', $bf).GetValue($c)) { $intro += $x.Name }
        $row.intro_items = $intro
        $row.is_secret = [bool]$charBase.GetField('_isSecret', $bf).GetValue($c)
        $row.ok = $true
    } catch {
        $row.error = $_.Exception.InnerException.Message
    }
    $chars += $row
}

$bossBase = $asm.GetType('BossModifier')
$bosses = @()
foreach ($t in ($asm.GetTypes() | Where-Object { $_.IsClass -and -not $_.IsAbstract -and $_.IsSubclassOf($bossBase) } | Sort-Object Name)) {
    $row = [ordered]@{ type = $t.Name; ok = $false }
    try {
        $b = [Activator]::CreateInstance($t)
        $row.name = [string]$b.Name
        $row.banned_floor_indexes = IntList $b.BannedFloorIndexes
        $row.difficulty_modifier = IntList $b.DifficultyModifier
        $row.difficulty_increase = IntList $b.DifficultyIncrease
        $row.is_secret_character = [bool]$b.IsSecretCharacter
        $row.can_be_summoned_by_michael = [bool]$b.CanBeSummonedByMichael
        $row.ok = $true
    } catch {
        $row.error = $_.Exception.InnerException.Message
    }
    $bosses += $row
}

[ordered]@{ items = $items; characters = $chars; bosses = $bosses } | ConvertTo-Json -Depth 8
"""


# Types whose constructors cannot run outside Unity (ECall / scene refs); values
# copied from the decompiled constructors.
_MANUAL: dict[str, dict] = {
    "LuckyDice": {
        "name": "Lucky Dice", "rarity": "Common", "cost": 10, "sell_cost": 0, "slot": "sticker",
        "components": [{"level": 1, "increment": 50, "value": 50}],
        "tags": ["NumbersBuild"], "dependency_tags": ["NumbersGenerator"],
        "function_tags": ["SpecificAdditive"], "relevant_colours": [],
        "is_food": False, "is_animal": False, "selling_prevented": False,
    },
    # Never drafted: RunProgress appends Michael as the sole stage-6 boss.
    "MichaelBoss": {
        "name": "MichaelBoss", "banned_floor_indexes": [1, 2, 3, 4, 5],
        "difficulty_modifier": [0, 0, 0, 0, 0, 3, 4], "difficulty_increase": [0, 0, 0, 0, 0, 0, 1],
        "is_secret_character": False, "can_be_summoned_by_michael": False,
    },
}


def main() -> int:
    dll = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DLL
    if not dll.is_file():
        print(f"Assembly not found: {dll}", file=sys.stderr)
        return 1
    # Load from the Managed dir so UnityEngine dependencies resolve.
    ps_cmd = (
        f"$DllPath = '{dll}'; [System.IO.Directory]::SetCurrentDirectory('{dll.parent}'); "
        + PS.strip()
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        print(proc.stderr or proc.stdout, file=sys.stderr)
        return proc.returncode or 1
    data = json.loads(proc.stdout)

    def _list(value: object) -> list:
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    for section in ("items", "characters", "bosses"):
        rows = _list(data.get(section))
        for row in rows:
            for key, val in list(row.items()):
                if key in {"components", "tags", "dependency_tags", "function_tags", "relevant_colours",
                           "intro_items", "banned_floor_indexes", "difficulty_modifier", "difficulty_increase"}:
                    row[key] = _list(val)
        data[section] = rows

    for section in ("items", "bosses"):
        data[section] = [
            {**row, **_MANUAL[row["type"]], "ok": True, "manual": True}
            if not row.get("ok") and row["type"] in _MANUAL else row
            for row in data[section]
        ]

    failed = {s: [r["type"] for r in data[s] if not r.get("ok")] for s in ("items", "characters", "bosses")}
    payload = {
        "_meta": {
            "source": str(dll),
            "counts": {s: len(data[s]) for s in ("items", "characters", "bosses")},
            "failed": failed,
        },
        **{s: data[s] for s in ("items", "characters", "bosses")},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}: {payload['_meta']['counts']}; failed: "
          f"{ {k: len(v) for k, v in failed.items()} }")
    return 0


if __name__ == "__main__":
    sys.exit(main())
