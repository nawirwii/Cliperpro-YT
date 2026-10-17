# Changelog

## [Unreleased]
### Added
- One-click Style Presets in the Process Clips dialog (Podcast / Gaming /
  Ceramah): a single tap applies caption style, reframe mode, watermark
  toggles and download quality. The last used preset is remembered and
  auto-applied when the dialog opens.
- Split-screen composition on Intel UHD 620 (and HD 620) now tries the Windows Media Foundation
  hardware encoder (`h264_mf`) before falling back to CPU. The QSV driver on these adapters is
  unstable with complex vstack graphs, but Media Foundation is a separate OS-level hardware path,
  so encoding can still be GPU-accelerated where QSV cannot be used.

## [2.0.100] - 2026-10-17
### Added
- Download full source video ONCE per (url, quality) and cut all highlight
  sections from the cached file (`_FULL_SOURCE_CACHE` in `video_processor.py`).
  Previously every highlight re-downloaded the entire video, so N highlights
  meant N full downloads.
### Fixed
- Credit overlay now anchors to the CENTER of the text
  (`x=(main_w*pos_x-text_w/2)` in `watermark.py`); default position (0.5, 0.5),
  and the settings-page preview centers on the position point.
- `build-sidecar.sh` / `build-sidecar.ps1` now fail fast when
  `src-tauri/binaries/bin/aria2c.exe` is missing (run `npm run deps` first),
  instead of silently falling back to yt-dlp's single-connection downloader.
