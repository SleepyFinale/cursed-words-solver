#!/usr/bin/env python3
"""Reflect ChallengeRun subclasses from Assembly-CSharp.dll (local Steam install)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "game" / "quest_taxonomy.json"
DEFAULT_DLL = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Cursed Words"
) / "Cursed Words_Data" / "Managed" / "Assembly-CSharp.dll"

# Effect classes used by the solver (see docs/game-research/quests.md).
_EFFECT_BY_CLASS: dict[str, str] = {
    "SupplyAndDemand": "search_filter",
    "UpAndUp": "search_filter",
    "Chromaphobia": "search_filter",
    "Chromaphilia": "search_filter",
    "Cursophobia": "search_filter",
    "SicilianDefense": "movement_override",
    "TheBonesRound": "scoring_override",
    "TwoWrongs": "target_scoring",
    "Bullseye": "target_scoring",
    "Lexographer": "scoring_step",
    "PlayingFavourites": "loadout_filter",
    "CallOfTheVoid": "board_layout",
    "Sudoku": "board_gen",
    "MunchTime": "board_gen",
    "RedLetterDay": "board_gen",
    "RedPepperDay": "board_gen",
    "ColourSwap": "board_gen",
    "EmptyGrid": "board_gen",
    "SpeedrunChallenge": "meta_timer",
    "DecisionParalysis": "shop_only",
    "SecretSanta": "shop_only",
    "Antiphilatelist": "shop_only",
    "Masochist": "shop_only",
    "InTheBeginning": "shop_only",
    "DoNotPassGo": "shop_only",
    "Embargo": "shop_only",
}

PS = r"""
param([string]$DllPath)
$asm = [System.Reflection.Assembly]::LoadFrom($DllPath)
$base = $asm.GetType('ChallengeRun')
$subs = $asm.GetTypes() | Where-Object {
    $_.IsClass -and -not $_.IsAbstract -and $base.IsAssignableFrom($_) -and $_ -ne $base
} | Sort-Object Name
$result = @()
foreach ($t in $subs) {
    $name = $t.Name
    $challengeName = ""
    $elite = $false
    try {
        $instance = [Activator]::CreateInstance($t)
        $challengeName = [string]$instance.ChallengeName
        $elite = [bool]$instance.EliteQuest
    } catch {}
    $result += [ordered]@{
        game_class = $name
        challenge_name = $challengeName
        elite_quest = $elite
    }
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
    quests: dict[str, dict] = {}
    for row in rows:
        game_class = str(row.get("game_class") or "").strip()
        if not game_class:
            continue
        slug = _slugify(game_class)
        quests[slug] = {
            "game_class": game_class,
            "wiki_name": str(row.get("challenge_name") or "").strip(),
            "elite_quest": bool(row.get("elite_quest")),
            "effect_class": _EFFECT_BY_CLASS.get(game_class, "board_gen"),
        }
    payload = {
        "_meta": {"source": str(dll), "count": len(quests)},
        "quests": quests,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(quests)} ChallengeRun subclasses)")
    return 0


def _slugify(name: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "unknown"


if __name__ == "__main__":
    sys.exit(main())
