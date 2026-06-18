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

$project = Join-Path $repo "scripts\decompile_type"
dotnet build $project -v q | Out-Null
$decompExe = Join-Path $project "bin\Debug\net10.0\DecompileType.exe"
& $decompExe --dll $GameDll --out $OutDir @types

Write-Host "Decompiled sim types -> $OutDir"
