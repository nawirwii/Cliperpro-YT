# Downloads bundled runtime dependencies (ffmpeg, deno) into src-tauri/binaries
# so they can be shipped with the app. Idempotent: skips files that already exist.

param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
# Suppress the progress bar — it floods output and drastically slows Invoke-WebRequest
$ProgressPreference = "SilentlyContinue"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$BinariesDir = Join-Path $Root "src-tauri\binaries"
$FfmpegDir = Join-Path $BinariesDir "ffmpeg"
$BinDir = Join-Path $BinariesDir "bin"
$TempDir = Join-Path $Root "build\deps-temp"

New-Item -ItemType Directory -Path $FfmpegDir -Force | Out-Null
New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

# ---------------------------------------------------------------------------
# FFmpeg (gyan.dev GPL full build — includes libass/libx264/nvenc/qsv/amf)
#
# IMPORTANT: we use gyan.dev (GnuTLS) NOT BtbN. BtbN's Windows builds link TLS
# via Schannel (--enable-schannel), which hangs indefinitely when yt-dlp's
# ffmpeg downloader (FFmpegFD) fetches keepalive HTTPS ranges from googlevideo
# for a DASH section download — the process freezes right after "Reinit
# context", writes zero bytes, and never recovers (the "stuck for hours" bug).
# gyan.dev builds use --enable-gnutls, which does not have this hang. Pinned to
# a version because gyan only publishes .zip (Expand-Archive-friendly) per
# tagged release on the GyanD/codexffmpeg mirror; bump when updating ffmpeg.
# ---------------------------------------------------------------------------
$FfmpegVersion = "8.1.2"
$FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
if ((Test-Path -LiteralPath $FfmpegExe) -and (-not $Force)) {
    Write-Host "[fetch-deps] ffmpeg already present, skipping."
} else {
    Write-Host "[fetch-deps] Downloading ffmpeg (gyan.dev GnuTLS full build $FfmpegVersion)..."
    $FfmpegUrl = "https://github.com/GyanD/codexffmpeg/releases/download/$FfmpegVersion/ffmpeg-$FfmpegVersion-full_build.zip"
    $FfmpegZip = Join-Path $TempDir "ffmpeg.zip"
    Invoke-WebRequest -Uri $FfmpegUrl -OutFile $FfmpegZip

    Write-Host "[fetch-deps] Extracting ffmpeg..."
    $FfmpegExtract = Join-Path $TempDir "ffmpeg-extract"
    if (Test-Path -LiteralPath $FfmpegExtract) { Remove-Item -Recurse -Force $FfmpegExtract }
    Expand-Archive -Path $FfmpegZip -DestinationPath $FfmpegExtract -Force

    # The zip contains a versioned folder like ffmpeg-7.x-essentials_build/bin/ffmpeg.exe
    $FoundFfmpeg = Get-ChildItem -Path $FfmpegExtract -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    if (-not $FoundFfmpeg) {
        throw "ffmpeg.exe not found in extracted archive"
    }
    Copy-Item -LiteralPath $FoundFfmpeg.FullName -Destination $FfmpegExe -Force

    Write-Host "[fetch-deps] ffmpeg ready: $FfmpegExe"
}

# ---------------------------------------------------------------------------
# Deno (for yt-dlp remote-components / JS challenges)
# ---------------------------------------------------------------------------
$DenoExe = Join-Path $BinDir "deno.exe"
if ((Test-Path -LiteralPath $DenoExe) -and (-not $Force)) {
    Write-Host "[fetch-deps] deno already present, skipping."
} else {
    Write-Host "[fetch-deps] Downloading deno..."
    $DenoUrl = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
    $DenoZip = Join-Path $TempDir "deno.zip"
    Invoke-WebRequest -Uri $DenoUrl -OutFile $DenoZip

    Write-Host "[fetch-deps] Extracting deno..."
    $DenoExtract = Join-Path $TempDir "deno-extract"
    if (Test-Path -LiteralPath $DenoExtract) { Remove-Item -Recurse -Force $DenoExtract }
    Expand-Archive -Path $DenoZip -DestinationPath $DenoExtract -Force

    $FoundDeno = Get-ChildItem -Path $DenoExtract -Recurse -Filter "deno.exe" | Select-Object -First 1
    if (-not $FoundDeno) {
        throw "deno.exe not found in extracted archive"
    }
    Copy-Item -LiteralPath $FoundDeno.FullName -Destination $DenoExe -Force
    Write-Host "[fetch-deps] deno ready: $DenoExe"
}

# ---------------------------------------------------------------------------
# aria2c (multi-connection downloader — the ONLY real cure for YouTube's
# per-connection cap on non-fragmented/progressive formats)
#
# WHY THIS EXISTS (v2.0.82):
#   yt-dlp's `concurrent_fragment_downloads` only applies to *fragmented*
#   transports (dash/hls). Our format selector asks for
#   `bestvideo+bestaudio`, which is a plain progressive MP4 — ONE connection.
#   So that option was a no-op and YouTube's per-connection cap hit at full
#   force. aria2c splits a single file into N parallel HTTP *range* requests
#   (`-x`), which does defeat a per-connection cap.
#
#   The official win-64bit build1 zip is self-contained: its PE import table
#   references only Windows system DLLs (kernel32, ws2_32, crypt32,
#   secur32, iphlpapi, shell32, bcrypt, msvcrt, advapi32) — no
#   VCRUNTIME140/MSVCP140 required, so it runs on a clean Windows box.
#   Pinned because the "latest" tag is not immutable.
$aria2Version = "1.37.0"
$Aria2Exe = Join-Path $BinDir "aria2c.exe"
if ((Test-Path -LiteralPath $Aria2Exe) -and (-not $Force)) {
    Write-Host "[fetch-deps] aria2c already present, skipping."
} else {
    Write-Host "[fetch-deps] Downloading aria2c $aria2Version..."
    $Aria2Url = "https://github.com/aria2/aria2/releases/download/release-$aria2Version/aria2-$aria2Version-win-64bit-build1.zip"
    $Aria2Zip = Join-Path $TempDir "aria2.zip"
    Invoke-WebRequest -Uri $Aria2Url -OutFile $Aria2Zip

    Write-Host "[fetch-deps] Extracting aria2c..."
    $Aria2Extract = Join-Path $TempDir "aria2-extract"
    if (Test-Path -LiteralPath $Aria2Extract) { Remove-Item -Recurse -Force $Aria2Extract }
    Expand-Archive -Path $Aria2Zip -DestinationPath $Aria2Extract -Force

    $FoundAria2 = Get-ChildItem -Path $Aria2Extract -Recurse -Filter "aria2c.exe" | Select-Object -First 1
    if (-not $FoundAria2) {
        throw "aria2c.exe not found in extracted archive"
    }
    Copy-Item -LiteralPath $FoundAria2.FullName -Destination $Aria2Exe -Force
    Write-Host "[fetch-deps] aria2c ready: $Aria2Exe"
}

# ---------------------------------------------------------------------------
# Cleanup temp
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $TempDir) {
    Remove-Item -Recurse -Force $TempDir
}

Write-Host "[fetch-deps] All dependencies ready in $BinariesDir"
