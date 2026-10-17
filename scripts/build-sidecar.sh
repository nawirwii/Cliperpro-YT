#!/usr/bin/env bash
set -e

TARGET_TRIPLE="x86_64-pc-windows-msvc"
ROOT="$(realpath "$(dirname "$0")/..")"
SPEC="$ROOT/build/spec/sidecar.spec"
BINARY_DIR="$ROOT/src-tauri/binaries"
WORK_DIR="$ROOT/build/sidecar"
SPEC_DIR="$ROOT/build/spec"
NAME="ytclip-sidecar-$TARGET_TRIPLE"

mkdir -p "$BINARY_DIR" "$WORK_DIR" "$SPEC_DIR"

# aria2c is the ONLY real cure for YouTube's per-connection throttle
# (16 parallel HTTP range requests). It is fetched by `npm run deps`
# (scripts/fetch-deps.ps1) into src-tauri/binaries/bin/ and bundled by
# Tauri as the bin/aria2c.exe resource. Fail fast here — without it the
# app silently falls back to yt-dlp's single-connection downloader.
if [[ ! -f "$ROOT/src-tauri/binaries/bin/aria2c.exe" ]]; then
    echo "ERROR: src-tauri/binaries/bin/aria2c.exe not found." >&2
    echo "Run 'npm run deps' first (downloads aria2c), then rebuild." >&2
    exit 1
fi

/opt/hermes/.venv/bin/python -m PyInstaller --clean --noconfirm --distpath "$BINARY_DIR" --workpath "$WORK_DIR" "$SPEC"

EXE="$BINARY_DIR/$NAME"
if [[ ! -f "$EXE" ]]; then
    echo "Sidecar binary was not created: $EXE" >&2
    exit 1
fi

echo "$EXE"