# Build and deploy CursedWordsSolverCompanion to the game's Mods folder.
param(
    [string]$GameDir = "C:\Program Files (x86)\Steam\steamapps\common\Cursed Words"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Project = Join-Path $Root "CursedWordsSolverCompanion\CursedWordsSolverCompanion.csproj"
$MelonDll = Join-Path $GameDir "MelonLoader\net35\MelonLoader.dll"
$ModsDir = Join-Path $GameDir "Mods"

if (-not (Test-Path $MelonDll)) {
    Write-Error @"
MelonLoader is not installed in:
  $GameDir

Install MelonLoader first (https://melonwiki.xyz), launch the game once, then re-run:
  .\melmod\build.ps1
"@
}

$Dotnet = "C:\Program Files\dotnet\dotnet.exe"
if (-not (Test-Path $Dotnet)) { $Dotnet = "dotnet" }

Write-Host "Building companion mod (GameDir=$GameDir)..."
& $Dotnet build $Project -c Release -p:GameDir="$GameDir"
if ($LASTEXITCODE -ne 0) {
    Write-Error @"
dotnet build failed (exit $LASTEXITCODE).

Install the .NET SDK: https://dotnet.microsoft.com/download
Then re-run: .\melmod\build.ps1
"@
}

$BuiltDll = Join-Path $Root "CursedWordsSolverCompanion\bin\CursedWordsSolverCompanion.dll"
if (-not (Test-Path $BuiltDll)) {
    Write-Error "Build succeeded but DLL not found at $BuiltDll"
}

New-Item -ItemType Directory -Force -Path $ModsDir | Out-Null
Copy-Item -Force $BuiltDll (Join-Path $ModsDir "CursedWordsSolverCompanion.dll")
Write-Host "Deployed to $ModsDir\CursedWordsSolverCompanion.dll"
