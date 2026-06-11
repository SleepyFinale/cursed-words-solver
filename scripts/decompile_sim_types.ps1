# Decompile encounter/sim types from Assembly-CSharp.dll (Stage 1 traceability).
param(
    [string]$GameDll = "C:\Program Files (x86)\Steam\steamapps\common\Cursed Words\Cursed Words_Data\Managed\Assembly-CSharp.dll",
    [string]$OutDir = "$PSScriptRoot\decompile_type\out"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent

if (-not (Test-Path $GameDll)) {
    Write-Error "Game DLL not found: $GameDll"
}

$types = @(
    "EncounterController",
    "GridUtility",
    "HistoricWord",
    "ScoreCalculation",
    "Player",
    "GridLayoutController"
)

dotnet run --project "$repo\scripts\decompile_type" -- --dll $GameDll --out $OutDir @types

Write-Host "Decompiled sim types -> $OutDir"
