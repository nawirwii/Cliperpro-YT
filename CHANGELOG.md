# Changelog

## [Unreleased]

### Changed
- Bauhaus visual restyle (UI only, no behavior change): off-white ground with flat red/blue/yellow planes, Host Grotesk type, square corners, 4px black seams and hard offset shadows. Sidebar is now a red plane with a white circular brand mark; buttons, cards, inputs, progress, sliders and switches follow the same language. Dark mode uses the same planes on a black ground with white seams. All routes, copy, controls and processing behavior are unchanged.

### Added
- Persistent source-video library (DOWNLOAD ONCE, CLIP MANY TIMES): full YouTube downloads are now stored once under `output/source_videos/` and indexed in `output/database/video_history.json`, so later clips — including clips processed in a new app session — cut from the saved source instead of re-downloading. A source is re-downloaded only when its file is missing or fails validation, or when `forceRedownload` is set.

### Fixed
- Fixed the per-clip temp cleanup deleting the cached full source video (`*_NNN.*` also matched `section_NNN.mp4.download.mp4`), which defeated the in-memory download cache and caused every clip to re-download the full video.
- "Generate with AI" no longer fails when the provider replies with no usable text ("AI returned empty response (no choices)"): it now retries once without `response_format` (some gateways silently drop the JSON-object format instead of rejecting it) and, if the reply is still empty, keeps the clip's original title/description instead of erroring. Genuine request failures (auth, rate limit, network) still surface as errors.

## [2.0.112] - 2026-10-25
### Fixed
- Credit watermark font size now stays synchronized between Settings preview and processed videos by scaling against the final video width.
- Processing dialog now shows the active credit font size from Credit Watermark Settings.

## [2.0.108] - 2026-10-20
### Fixed
- Subtitle downloads now retry transient YouTube TLS/SSL connection resets.
- Removed the subtitle path's dependency on remote EJS components from GitHub.
- Added stable YouTube player clients and explicit network timeouts.

## [2.0.107] - 2026-10-20
### Fixed
- Prevented the download watchdog from aborting a healthy silent audio
  download after the video stream completes.
- Improved timeout diagnostics to distinguish extraction and download phases.

## [2.0.106] - 2026-10-20
### Removed
- Popup Announcement/Notification dihapus sepenuhnya (kontennya basi dari
  server luar). Dialog update versi resmi tetap dipertahankan.

## [2.0.105] - 2026-10-19
### Fixed
- GPU encoding now applies to hook text overlay and caption burning steps:
  `_resolve_gpu_config` normalizes the GPU config to include the legacy
  `available`/`name` keys expected by `build_video_enc_args`, fixing the
  silent fallback to CPU (libx264) even with GPU Acceleration enabled.

## [2.0.104] - 2026-10-18
### Fixed
- Credit watermark position moved to (0.5, 0.3) — horizontally centered,
  upper third of the frame — as the default; stale pre-v2.0.99 configs
  (0.03, 0.72) are migrated there automatically on load.

## [2.0.103] - 2026-10-18
### Fixed
- Credit watermark clipped at the left edge for configs saved before v2.0.99:
  the legacy `position_x` default (0.03, top-left anchor) is now migrated to
  0.5 (true center) when the config loads, matching the center-anchored
  positioning introduced in v2.0.99.

## [2.0.102] - 2026-10-17
### Fixed
- `NameError: cache_key is not defined` in `_download_section_module`
  (download-once cache) — the cache key is now built inline from
  `(url, max_height)`, and fallback downloads also populate the cache so the
  next section never re-downloads.

## [2.0.101] - 2026-10-17
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
