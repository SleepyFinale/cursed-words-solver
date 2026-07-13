# Full decompile refresh from Assembly-CSharp.dll + optional metadata extraction.
param(
    [string]$GameDll = "C:\Program Files (x86)\Steam\steamapps\common\Cursed Words\Cursed Words_Data\Managed\Assembly-CSharp.dll",
    [switch]$SkipExtract
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$project = Join-Path $repo "scripts\decompile_type"
$decompExe = Join-Path $project "bin\Debug\net10.0\DecompileType.exe"

if (-not (Test-Path $GameDll)) {
    Write-Error "Game DLL not found: $GameDll"
}

function Invoke-Decompile {
    param(
        [string]$OutDir,
        [string[]]$TypeArgs
    )
    & $decompExe --dll $GameDll --out $OutDir @TypeArgs
}

Write-Host "Building decompile_type..."
dotnet build $project -v q | Out-Null

Write-Host "Core solver / sim types -> scripts/decompile_type/out/"
Invoke-Decompile (Join-Path $project "out") @(
    "EncounterController", "GridUtility", "HistoricWord", "ScoreCalculation", "Player", "GridLayoutController",
    "Item", "Tile", "Hanafuda", "PokerHands", "Wrestlers", "Bicycle", "Joker",
    "WordBonusToken", "ScoreCalcVizInfo", "TileNinja", "MutatingDNA", "MichaelBoss", "TileSelectionManager"
)

Write-Host "Quests -> scripts/decompile_type/out_quests/"
Invoke-Decompile (Join-Path $project "out_quests") @(
    "--subclasses-of", "ChallengeRun",
    "ChallengeRun", "ChallengeRuns", "GridUtility", "GridUtilitySingleton",
    "ScoreCalculation", "Player", "Tile", "HistoricWord"
)

Write-Host "Shop -> scripts/decompile_type/out_shop/"
Invoke-Decompile (Join-Path $project "out_shop") @(
    "ShopController", "ShopRecommendation", "AdviceData", "BuildData", "Item", "GoldenScales", "NorthernCardinal"
)

Write-Host "Stamps / curses -> scripts/decompile_type/out_stamps/"
Invoke-Decompile (Join-Path $project "out_stamps") @(
    "Oden", "CurseType", "TileSelection", "Footprints", "Cartwheeler"
)

Write-Host "UI helpers -> scripts/decompile_type/out2/"
Invoke-Decompile (Join-Path $project "out2") @(
    "CameraFinder", "CharacterInfoPanel", "GridLayoutController", "InventoryVisualController",
    "TileObject", "TileConsumableObject"
)

Write-Host "Cursedle -> scripts/decompile_type/out_cursedle/"
Invoke-Decompile (Join-Path $project "out_cursedle") @(
    "FairyGrid", "FairyGridGeneration", "PuzzleController",
    "TileSolutionState", "WordHistoryController"
)

Write-Host "Scratch copies -> docs/game-research/_decompiled/ (gitignored)"
Invoke-Decompile (Join-Path $repo "docs\game-research\_decompiled") @(
    "ScoreCalculation", "EncounterController", "Item", "Player", "Tile", "Hanafuda", "PokerHands"
)

if (-not $SkipExtract) {
    Write-Host "Extracting game metadata..."
    $py = if (Test-Path (Join-Path $repo ".venv\Scripts\python.exe")) {
        Join-Path $repo ".venv\Scripts\python.exe"
    } else {
        "python"
    }
    $extractScripts = @(
        "extract_game_types.py",
        "extract_quest_types.py",
        "extract_stamp_types.py",
        "extract_tile_enums.py",
        "extract_boss_types.py",
        "enrich_boss_catalog.py",
        "generate_sticker_audit.py",
        "generate_stamp_audit.py",
        "generate_tile_audit.py",
        "generate_boss_audit.py"
    )
    foreach ($script in $extractScripts) {
        & $py (Join-Path $repo "scripts\$script")
    }
}

Write-Host "Done. See docs/game-research/README.md for output layout."
