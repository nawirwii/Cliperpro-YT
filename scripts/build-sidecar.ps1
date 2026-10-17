param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Spec = Join-Path $Root "build\spec\sidecar.spec"
$BinaryDir = Join-Path $Root "src-tauri\binaries"
$WorkDir = Join-Path $Root "build\sidecar"
$SpecDir = Join-Path $Root "build\spec"
$Name = "ytclip-sidecar-$TargetTriple"

New-Item -ItemType Directory -Path $BinaryDir -Force | Out-Null
# aria2c is the ONLY real cure for YouTube's per-connection throttle
# (16 parallel HTTP range requests). It is fetched by `npm run deps`
# (scripts/fetch-deps.ps1) into src-tauri/binaries/bin/ and bundled by
# Tauri as the bin/aria2c.exe resource. Fail fast here — without it the
# app silently falls back to yt-dlp's single-connection downloader.
$Aria2Check = Join-Path $Root "src-tauri\binaries\bin\aria2c.exe"
if (!(Test-Path -LiteralPath $Aria2Check)) {
    throw "aria2c not found: $Aria2Check. Run 'npm run deps' first (downloads aria2c), then rebuild."
}
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
New-Item -ItemType Directory -Path $SpecDir -Force | Out-Null

py -m PyInstaller `
    --clean `
    --noconfirm `
    --distpath $BinaryDir `
    --workpath $WorkDir `
    $Spec

$Exe = Join-Path $BinaryDir "$Name.exe"
if (!(Test-Path -LiteralPath $Exe)) {
    throw "Sidecar binary was not created: $Exe"
}

Write-Output $Exe
