# Build a Thunderstore zip for Cursed Words Solver (beta).
# Output: dist/Cursed_Words_Solver-0.1.0.zip
# Does not upload. Close the game first if you also want a local DLL deploy.
param(
    [string]$GameDir = "C:\Program Files (x86)\Steam\steamapps\common\Cursed Words"
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path $PSScriptRoot -Parent
$PackageDir = Join-Path $Repo "thunderstore"
$Project = Join-Path $PSScriptRoot "CursedWordsSolverCompanion\CursedWordsSolverCompanion.csproj"
$Spec = Join-Path $PackageDir "CursedWordsSolver.spec"
$Version = "0.1.0"
$Stage = Join-Path $Repo "dist\thunderstore-stage"
$Zip = Join-Path $Repo "dist\Cursed_Words_Solver-$Version.zip"
$PyDist = Join-Path $Repo "dist\pyinstaller"
$PyWork = Join-Path $Repo "build\pyinstaller"

$MelonDll = Join-Path $GameDir "MelonLoader\net35\MelonLoader.dll"
if (-not (Test-Path $MelonDll)) {
    Write-Error "MelonLoader is not installed in $GameDir. Install it, launch the game once, then re-run."
}

$Dotnet = "C:\Program Files\dotnet\dotnet.exe"
if (-not (Test-Path $Dotnet)) { $Dotnet = "dotnet" }

Write-Host "Building companion DLL..."
& $Dotnet build $Project -c Release -p:GameDir="$GameDir"
if ($LASTEXITCODE -ne 0) { Write-Error "dotnet build failed (exit $LASTEXITCODE)." }

$BuiltDll = Join-Path $PSScriptRoot "CursedWordsSolverCompanion\bin\CursedWordsSolverCompanion.dll"
if (-not (Test-Path $BuiltDll)) { Write-Error "DLL not found at $BuiltDll" }

$Python = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "py"
}

Write-Host "Building solver executable..."
if ($Python -eq "py") {
    & py -3.11 -m pip install --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) { Write-Error "pip install pyinstaller failed." }
    & py -3.11 -m PyInstaller --noconfirm --distpath $PyDist --workpath $PyWork $Spec
} else {
    & $Python -m pip install --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) { Write-Error "pip install pyinstaller failed." }
    & $Python -m PyInstaller --noconfirm --distpath $PyDist --workpath $PyWork $Spec
}
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed (exit $LASTEXITCODE)." }

$SolverDir = Join-Path $PyDist "CursedWordsSolver"
$SolverExe = Join-Path $SolverDir "CursedWordsSolver.exe"
if (-not (Test-Path $SolverExe)) { Write-Error "Solver exe not found at $SolverExe" }

if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "UserData\solver") | Out-Null

Copy-Item (Join-Path $PackageDir "manifest.json") (Join-Path $Stage "manifest.json")
Copy-Item (Join-Path $PackageDir "README.md") (Join-Path $Stage "README.md")
Copy-Item (Join-Path $PackageDir "CHANGELOG.md") (Join-Path $Stage "CHANGELOG.md")
Copy-Item (Join-Path $PackageDir "icon.png") (Join-Path $Stage "icon.png")
Copy-Item $BuiltDll (Join-Path $Stage "CursedWordsSolverCompanion.dll")
Copy-Item -Recurse $SolverDir (Join-Path $Stage "UserData\solver")

# Copy-Item of a directory nests the folder name. Flatten so the exe is at UserData/solver/.
$Nested = Join-Path $Stage "UserData\solver\CursedWordsSolver"
if (Test-Path $Nested) {
    Get-ChildItem $Nested | ForEach-Object {
        Move-Item $_.FullName (Join-Path $Stage "UserData\solver") -Force
    }
    Remove-Item $Nested -Force
}

if (Test-Path $Zip) { Remove-Item -Force $Zip }
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zipStream = [System.IO.File]::Open($Zip, [System.IO.FileMode]::Create)
$archive = New-Object System.IO.Compression.ZipArchive(
    $zipStream,
    [System.IO.Compression.ZipArchiveMode]::Create
)
try {
    $stageRoot = (Resolve-Path $Stage).Path.TrimEnd('\')
    Get-ChildItem $Stage -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($stageRoot.Length).TrimStart('\') -replace '\\', '/'
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $_.FullName,
            $relative
        ) | Out-Null
    }
}
finally {
    $archive.Dispose()
    $zipStream.Dispose()
}

Write-Host "Package: $Zip"
Write-Host "Upload that zip at https://thunderstore.io/c/cursed-words/"
