param(
    [string]$GameDir = "C:\Program Files (x86)\Steam\steamapps\common\Cursed Words"
)

$ErrorActionPreference = "Stop"
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$managed = Join-Path $GameDir "Cursed Words_Data\Managed"
$ml = Join-Path $GameDir "MelonLoader\net35\MelonLoader.dll"
$src = Join-Path $PSScriptRoot "CursedWordsSolverCompanion"
$out = Join-Path $src "bin"

$nugetDll = Get-ChildItem "$env:USERPROFILE\.nuget\packages\newtonsoft.json" -Recurse -Filter "Newtonsoft.Json.dll" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "net45" } | Select-Object -First 1
if (-not $nugetDll) {
    $pkg = Join-Path $env:TEMP "newtonsoft.zip"
    Invoke-WebRequest "https://www.nuget.org/api/v2/package/Newtonsoft.Json/13.0.3" -OutFile $pkg -UseBasicParsing
    $extract = Join-Path $env:TEMP "newtonsoft_pkg"
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive $pkg $extract -Force
    $nugetDll = Get-ChildItem $extract -Recurse -Filter "Newtonsoft.Json.dll" |
        Where-Object { $_.DirectoryName -match "net45" } | Select-Object -First 1
}

New-Item -ItemType Directory -Force -Path $out | Out-Null
$args = @(
    "/target:library",
    "/out:$(Join-Path $out 'CursedWordsSolverCompanion.dll')",
    "/nologo",
    "/reference:$ml",
    "/reference:$(Join-Path $managed 'Assembly-CSharp.dll')",
    "/reference:$(Join-Path $managed 'UnityEngine.CoreModule.dll')",
    "/reference:$(Join-Path $managed 'UnityEngine.InputLegacyModule.dll')",
    "/reference:$(Join-Path $managed 'netstandard.dll')",
    "/reference:$($nugetDll.FullName)",
    (Join-Path $src "BuildInfo.cs"),
    (Join-Path $src "RunStateSnapshot.cs"),
    (Join-Path $src "BoardSnapshot.cs"),
    (Join-Path $src "BoardExporter.cs"),
    (Join-Path $src "DictionaryExporter.cs"),
    (Join-Path $src "RunStateExporter.cs"),
    (Join-Path $src "CompanionMod.cs")
)
& $csc @args
