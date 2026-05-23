# Install MelonLoader into a Cursed Words (Steam) game folder.
# Run from repo root: .\melmod\install-melonloader.ps1
param(
    [string]$GameDir = "C:\Program Files (x86)\Steam\steamapps\common\Cursed Words",
    [string]$MelonZipUrl = "https://github.com/LavaGang/MelonLoader/releases/latest/download/MelonLoader.x64.zip"
)

$ErrorActionPreference = "Stop"

$Exe = Join-Path $GameDir "Cursed Words.exe"
if (-not (Test-Path $Exe)) {
    Write-Error "Game not found at $GameDir (missing Cursed Words.exe). Pass -GameDir if Steam is elsewhere."
}

$Marker = Join-Path $GameDir "MelonLoader\net35\MelonLoader.dll"
if (Test-Path $Marker) {
    Write-Host "MelonLoader already installed at $GameDir"
    New-Item -ItemType Directory -Force -Path (Join-Path $GameDir "Mods") | Out-Null
    exit 0
}

$TempZip = Join-Path $env:TEMP "MelonLoader.x64.zip"
$TempExtract = Join-Path $env:TEMP "MelonLoader.x64.extract"

Write-Host "Downloading MelonLoader (x64)..."
Invoke-WebRequest -Uri $MelonZipUrl -OutFile $TempZip -UseBasicParsing

if (Test-Path $TempExtract) { Remove-Item -Recurse -Force $TempExtract }
New-Item -ItemType Directory -Force -Path $TempExtract | Out-Null
Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force

# Zip layout: MelonLoader/ folder, version.dll, dobby.dll at archive root.
$SrcMelon = Join-Path $TempExtract "MelonLoader"
if (-not (Test-Path $SrcMelon)) {
    Write-Error "Unexpected zip layout: MelonLoader folder not found in $TempExtract"
}

$DestMelon = Join-Path $GameDir "MelonLoader"
Write-Host "Installing to $GameDir ..."
Copy-Item -Recurse -Force $SrcMelon $DestMelon

foreach ($file in @("version.dll", "dobby.dll")) {
    $src = Join-Path $TempExtract $file
    if (Test-Path $src) {
        Copy-Item -Force $src (Join-Path $GameDir $file)
    }
}

New-Item -ItemType Directory -Force -Path (Join-Path $GameDir "Mods") | Out-Null

if (-not (Test-Path $Marker)) {
    Write-Error "Install finished but $Marker is missing. Check the zip version or game path."
}

Write-Host "MelonLoader installed. Launch the game once from Steam (creates UserData/logs), then run:"
Write-Host "  .\melmod\build.ps1 -GameDir `"$GameDir`""
