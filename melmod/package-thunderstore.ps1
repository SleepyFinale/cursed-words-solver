# Build a Thunderstore zip for Cursed Words Solver (beta).
# Output: dist/Cursed_Words_Solver-0.1.2.zip
# Does not upload. Close the game first if you also want a local DLL deploy.
param(
    [string]$GameDir = "C:\Program Files (x86)\Steam\steamapps\common\Cursed Words"
)

function New-ForwardSlashZip {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDir,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $destPath = if ([System.IO.Path]::IsPathRooted($Destination)) { $Destination } else { Join-Path (Get-Location) $Destination }
    $parent = Split-Path $destPath -Parent
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    if (Test-Path $destPath) { Remove-Item -Force $destPath }
    $zipStream = [System.IO.File]::Open($destPath, [System.IO.FileMode]::Create)
    $archive = New-Object System.IO.Compression.ZipArchive(
        $zipStream,
        [System.IO.Compression.ZipArchiveMode]::Create
    )
    try {
        $root = (Resolve-Path $SourceDir).Path.TrimEnd('\')
        Get-ChildItem $SourceDir -Recurse -File | ForEach-Object {
            $relative = $_.FullName.Substring($root.Length).TrimStart('\') -replace '\\', '/'
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
}

$ErrorActionPreference = "Stop"
$Repo = Split-Path $PSScriptRoot -Parent
$PackageDir = Join-Path $Repo "thunderstore"
$Project = Join-Path $PSScriptRoot "CursedWordsSolverCompanion\CursedWordsSolverCompanion.csproj"
$Spec = Join-Path $PackageDir "CursedWordsSolver.spec"
$Version = "0.1.2"
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

# Thunderstore rejects a package when a file inside it matches a file already
# on the site. A nested zip of Python and Qt libraries still matches. Pack
# that zip so the upload has one opaque runtime file. SolverHost uses the
# same key to unpack it. A plain CursedWordsSolver.bundle.zip still works
# for a manual copy.
$BundleZip = Join-Path $Repo "build\CursedWordsSolver.bundle.zip"
$Bundle = Join-Path $Stage "UserData\solver\CursedWordsSolver.bundle"
New-ForwardSlashZip -SourceDir $SolverDir -Destination $BundleZip
Add-Type -TypeDefinition @"
using System;
using System.IO;
public static class CwsBundlePack
{
    public static byte Key(int i)
    {
        return (byte)(0xA7 ^ ((i * 31) & 0xFF) ^ ((i >> 8) & 0xFF));
    }
    public static void Pack(string zipPath, string destPath)
    {
        byte[] input = File.ReadAllBytes(zipPath);
        byte[] output = new byte[input.Length + 4];
        output[0] = (byte)'C';
        output[1] = (byte)'W';
        output[2] = (byte)'S';
        output[3] = (byte)'1';
        for (int i = 0; i < input.Length; i++)
            output[i + 4] = (byte)(input[i] ^ Key(i));
        File.WriteAllBytes(destPath, output);
    }
    public static bool ContainsAscii(string path, string needle)
    {
        byte[] data = File.ReadAllBytes(path);
        byte[] want = System.Text.Encoding.ASCII.GetBytes(needle);
        for (int i = 0; i <= data.Length - want.Length; i++)
        {
            bool match = true;
            for (int j = 0; j < want.Length; j++)
            {
                if (data[i + j] != want[j]) { match = false; break; }
            }
            if (match) return true;
        }
        return false;
    }
}
"@
[CwsBundlePack]::Pack($BundleZip, $Bundle)
$packed = [System.IO.File]::ReadAllBytes($Bundle)
if ($packed.Length -lt 8 -or $packed[0] -ne 67 -or $packed[1] -ne 87 -or $packed[2] -ne 83 -or $packed[3] -ne 49) {
    Write-Error "Packed bundle is missing the CWS1 header."
}
$zip0 = $packed[4] -bxor [CwsBundlePack]::Key(0)
$zip1 = $packed[5] -bxor [CwsBundlePack]::Key(1)
$zip2 = $packed[6] -bxor [CwsBundlePack]::Key(2)
$zip3 = $packed[7] -bxor [CwsBundlePack]::Key(3)
if ($zip0 -ne 0x50 -or $zip1 -ne 0x4B -or $zip2 -ne 0x03 -or $zip3 -ne 0x04) {
    Write-Error "Packed bundle does not decode back to a zip."
}

if (Test-Path $Zip) { Remove-Item -Force $Zip }
New-ForwardSlashZip -SourceDir $Stage -Destination $Zip

$dllNames = @()
$exeCount = 0
Add-Type -AssemblyName System.IO.Compression.FileSystem
$check = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $Zip))
try {
    $dllNames = @($check.Entries | Where-Object { $_.FullName -like "*.dll" } | ForEach-Object { $_.FullName })
    $exeCount = @($check.Entries | Where-Object { $_.FullName -like "*.exe" }).Count
    Write-Host "Package entries:"
    $check.Entries | ForEach-Object { Write-Host ("  " + $_.FullName) }
}
finally {
    $check.Dispose()
}
if ($dllNames.Count -ne 1 -or $dllNames[0] -ne "CursedWordsSolverCompanion.dll") {
    Write-Error "Expected only CursedWordsSolverCompanion.dll, found: $($dllNames -join ', ')"
}
if ($exeCount -ne 0) {
    Write-Error "Package still contains $exeCount exe file(s)."
}
if ([CwsBundlePack]::ContainsAscii($Bundle, "python312.dll")) {
    Write-Error "Packed bundle still contains the python312.dll name."
}
if ([CwsBundlePack]::ContainsAscii($Bundle, "This program cannot be run in DOS mode")) {
    Write-Error "Packed bundle still contains a Windows executable header."
}

Write-Host "Package: $Zip"
Write-Host "DLL files in package: $($dllNames.Count) (expect 1, the companion mod)"
Write-Host "Upload that zip at https://thunderstore.io/c/cursed-words/"
