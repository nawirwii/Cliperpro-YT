"""Download video sections from YouTube via yt-dlp."""

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .cookies import validate_cookies
from .helpers import debug_log, get_aria2c_path, get_deno_path, get_ffmpeg_path, is_ytdlp_module_available
from .helpers import _get_app_dir
from .gpu import build_video_enc_args

LogFn = Callable[[str], None]

# Shared by http and https so there is a single source of truth for the
# aria2c tuning (see _build_downloader_opts for what each flag buys).
_ARIA2_ARGS = [
    "-x16",                    # max 16 connections per server
    "-s16",                    # split into 16 pieces
    "-j16",                    # 16 parallel downloads
    "-k1M",                    # only split files larger than 1 MiB
    "--file-allocation=none",  # no sparse pre-allocation
    "--summary-interval=0",    # silence aria2's own status line
    "--no-conf",               # ignore a stray user aria2.conf
]

# Sustained-throttle abort thresholds. 40 KiB/s is ~2x below the 100 KiB/s
# warning line and was the worst speed seen live (log: 63 KiB/s), so this
# only fires when a download is genuinely crawling. At 40 KiB/s a 47 MiB
# file needs ~20 min — aborting and re-rolling the client is far better.
_SUSTAINED_THROTTLE_BPS = 40 * 1024
_SUSTAINED_THROTTLE_SECS = 60

# Player clients to try, in order. Each is JS-less (no po_token challenge),
# and YouTube treats them as separate identities — so when one gets capped,
# the next often does not. Ordered by how reliably they return stream
# info without a JS runtime; the first entry is the default.
_CLIENT_LADDER: list[list[str]] = [
    ["visionos", "ios", "android", "tv_downgraded"],
    ["ios", "android", "mweb", "web_safari"],
    ["android", "tv_downgraded", "web_embedded"],
]


class _SustainedThrottle(RuntimeError):
    """Download was crawling for so long that waiting it out is pointless.

    Raised only from the watchdog, and only after the progress hook has
    confirmed sustained sub-threshold speed. It is deliberately NOT a
    generic failure: it tells ``_do_download`` to retry the whole
    extraction with a different player client, because YouTube's cap is
    decided per client/URL and a different client often flies.
    """


def _sustained_throttle_check(d: dict, state: dict, log: LogFn) -> None:
    """Track how long the download has been crawling.

    At 40 KiB/s a 47 MiB video needs ~20 minutes, so after
    ``_SUSTAINED_THROTTLE_SECS`` of being that slow the honest move is to
    stop and re-roll the client instead of waiting. The threshold is
    deliberately far below the 100 KiB/s the warning uses, so this only
    fires on links that are genuinely not moving.
    """
    if d.get("status") != "downloading":
        return
    speed = d.get("speed")
    if not speed:
        return
    now = time.monotonic()
    if speed < _SUSTAINED_THROTTLE_BPS:
        first = state.get("throttle_since")
        if first is None:
            state["throttle_since"] = now
            state["throttle_since_speed"] = speed
        elif now - first >= _SUSTAINED_THROTTLE_SECS:
            state["sustained_throttle"] = True
            log(
                f"🐌 Download meringkek {int(speed / 1024)} KiB/s selama "
                f"{int(now - first)}s — membatalkan untuk mencoba client "
                "YouTube lain (cap throttle decided per client)."
            )
    else:
        # Recovered (or a false alarm) — clear the timer so the window restarts.
        state["throttle_since"] = None
        state["sustained_throttle"] = False


def _parse_timestamp(ts: str) -> float:
    """Convert timestamp HH:MM:SS,mmm or HH:MM:SS.mmm to seconds."""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def _build_downloader_opts(aria2_path: str | None, log: LogFn) -> dict[str, Any]:
    """Build ``external_downloader`` opts for yt-dlp.

    Returns ``{}`` when aria2c is unavailable — yt-dlp then uses its native
    downloader, which still works, just single-connection. That silent
    fallback matters: aria2c is a bundled convenience, never a hard
    dependency, so a missing/corrupt binary must not break downloading.

    Why aria2c and not more ``concurrent_fragment_downloads``: that option
    only splits *fragmented* streams (dash/hls). Our format is a
    progressive MP4, so there is nothing for it to parallelise.
    aria2c instead issues N concurrent HTTP **range** requests for a single
    file, which is exactly what defeats a per-connection speed cap.

    Args tuned for a throttled consumer line rather than raw maximum
    bandwidth:
      ``-x 16``  up to 16 connections per server
      ``-s 16``  16 splits (the piece actually downloaded in parallel)
      ``-j 16``  16 parallel downloads (video+audio run together)
      ``-k 1M``  only split files above 1 MiB; smaller chunks waste
                 round-trips and look more like abuse
      ``--file-allocation=none``  don't pre-create a sparse file the size
                 of the whole download (wastes disk on slow connections)
      ``--summary-interval=0``  aria2's own status line would interleave
                 with our yt-dlp log; progress comes from our hook
      ``--no-conf``  ignore any user aria2.conf that could break things
    """
    if not aria2_path:
        log(
            "ℹ️ aria2c tidak ditemukan — memakai downloader bawaan "
            "(1 koneksi). Download tetap jalan, tapi lebih lambat saat "
            "YouTube membatasi koneksi."
        )
        return {}

    # yt-dlp resolves an external downloader by protocol key, or 'default'.
    # Mapping both http and https to the absolute path avoids depending on
    # aria2c being on PATH inside the packaged app.
    return {
        "external_downloader": {
            "http": aria2_path,
            "https": aria2_path,
        },
        "external_downloader_args": {
            "http": _ARIA2_ARGS,
            "https": _ARIA2_ARGS,
        },
    }


def _build_format_selector(max_height: int) -> str:
    """Build a yt-dlp format selector capped at ``max_height`` pixels.

    Strongly prefers H.264 (avc1) video + m4a audio at any height. Smaller
    caps (720p/480p) download much less data — vital on throttled lines where
    a full 1080p source can be >1.5 GiB and take 40+ minutes.
    """
    return (
        f"bestvideo[height<={max_height}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
        f"bestvideo[height<={max_height}][vcodec^=avc1]+bestaudio/"
        f"bestvideo[height<={max_height}]+bestaudio/"
        # 2026-09-16: prefer formats that actually carry audio. On SABR
        # sessions `best[height<=N]` can resolve to a video-only HLS stream
        # (no audio at all) — the downstream portrait encoder then failed
        # with "Output file does not contain any stream". acodec!=none keeps
        # combined formats with a real audio track ahead of silent ones.
        f"best[height<={max_height}][acodec!=none]/"
        f"best[height<={max_height}]/best"
    )


def _find_downloaded_file(output_path: str) -> str:
    """yt-dlp may change the extension; find the actual file."""
    if Path(output_path).exists():
        return output_path
    output_dir = Path(output_path).parent
    output_stem = Path(output_path).stem
    mp4 = output_dir / f"{output_stem}.mp4"
    if mp4.exists():
        return str(mp4)
    candidates = [
        c for c in output_dir.glob(f"{output_stem}.*")
        if c.suffix in (".mp4", ".mkv", ".webm")
    ]
    if candidates:
        return str(candidates[0])
    raise RuntimeError(f"Downloaded section file not found: {output_path}")


def _setup_ytdlp_env() -> None:
    """Ensure Deno is in PATH for yt-dlp remote components."""
    deno_path = get_deno_path()
    if deno_path and Path(deno_path).exists():
        deno_dir = str(Path(deno_path).parent)
        os.environ["PATH"] = f"{deno_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def _extract_progress(d: dict) -> tuple[str | None, str]:
    """Normalize a yt-dlp progress dict into ``(percent, detail)``.

    yt-dlp only fills ``_percent_str`` for some transports. For DASH/range
    downloads (e.g. ``271+140``) it's usually empty, so we compute the
    percentage ourselves from the raw byte counters, then fall back to
    fragment counts (HLS/DASH manifests). ``percent`` is a bare number string
    without the ``%`` sign, or ``None`` if nothing usable is available.
    """
    pct: str | None = None

    # 1) yt-dlp's own formatted percent, when present
    raw_pct = (d.get("_percent_str") or "").strip()
    match = re.search(r"(\d+\.?\d*)%", raw_pct)
    if match:
        pct = match.group(1)
    else:
        # 2) compute from raw byte counters (total may only be an estimate)
        downloaded = d.get("downloaded_bytes")
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if isinstance(downloaded, (int, float)) and isinstance(total, (int, float)) and total > 0:
            pct = f"{min(100.0, downloaded / total * 100):.1f}"
        else:
            # 3) fall back to fragment progress for segmented downloads
            frag_i = d.get("fragment_index")
            frag_n = d.get("fragment_count")
            if isinstance(frag_i, (int, float)) and isinstance(frag_n, (int, float)) and frag_n > 0:
                pct = f"{frag_i / frag_n * 100:.0f}"

    downloaded_str = d.get("_downloaded_bytes_str") or d.get("downloaded_bytes")
    speed = d.get("_speed_str") or d.get("speed")
    eta = d.get("_eta_str") or d.get("eta")
    parts = []
    if downloaded_str:
        parts.append(f"{downloaded_str}")
    if speed:
        parts.append(f"@ {speed}")
    if eta is not None:
        parts.append(f"eta {eta}")
    detail = " ".join(str(p) for p in parts)
    return pct, detail


def _yt_dlp_progress_hook(d: dict, log: LogFn) -> None:
    """Report yt-dlp download progress.

    yt-dlp's progress dict uses different keys depending on the transport
    (direct HTTP, HLS fragments, DASH). ``_percent_str`` can be empty during
    the first fragment or when the total size is unknown — in that case we
    compute the percentage from raw counters (see ``_extract_progress``).

    v2.0.34: per user request, the per-second "Download progress: X%"
    lines are NO LONGER written to the log — they dilute the console. The
    heartbeat thread (every 15s, "⏳ Still downloading...") already reports
    the same percentage, so the user still gets download state without the
    noise. We still update ``_progress_hook_state`` (rate-limit + throttle
    warning) and ``finished`` still logs the merge line.

    Rate-limited: HLS fires this hook per fragment (thousands of times),
    which would flood the sidecar stdout. We cap at ~1 progress line per
    second and always pass "finished" through.
    """
    status = d.get("status")
    if status == "finished":
        total = d.get("_total_bytes_str") or d.get("total_bytes") or ""
        elapsed = d.get("_elapsed_str") or d.get("elapsed") or ""
        tail = f" ({total}, {elapsed})" if (total or elapsed) else ""
        log(f"Download complete, merging...{tail}")
        return

    if status != "downloading":
        return

    now = time.monotonic()
    last = _progress_hook_state.get("last_ts", 0.0)
    if now - last < 1.0 and _progress_hook_state.get("last_pct") is not None:
        # suppress duplicate rapid-fire progress lines; heartbeat covers the gap
        return
    _progress_hook_state["last_ts"] = now

    pct, detail = _extract_progress(d)
    if pct is not None:
        _progress_hook_state["last_pct"] = pct
        _maybe_warn_throttled(d, log)
    # NOTE: no "Download progress:" log line here (v2.0.34) — the 15s
    # heartbeat reports it instead. Keep state so the heartbeat has data.


def _maybe_warn_throttled(d: dict, log: LogFn) -> None:
    """Warn once per download when YouTube is throttling the connection.

    Speed < ~100 KiB/s sustained is NOT a normal slow network — it is
    YouTube's deliberate per-connection cap for non-browser clients (or a
    missing cookies.txt). We surface it once so the user knows what's going
    on instead of watching a crawling percentage.

    v2.0.82: the old message claimed "Mitigations active: parallel
    fragments (×8)". That was **factually wrong** for our format — yt-dlp's
    concurrent_fragment_downloads only applies to fragmented dash/hls
    streams, and we download a plain progressive MP4 with a single
    connection. The user was told a mitigation was running when nothing was
    parallelising their download. The message now reports what is actually
    true, and tells the user where to put cookies.txt instead of vaguely
    suggesting one.
    """
    speed = d.get("speed")
    if not speed:
        return
    kiB_s = speed / 1024.0
    if kiB_s >= 100:
        return  # healthy speed
    now = time.monotonic()
    if _progress_hook_state.get("throttle_warned_ts", 0.0) and now - _progress_hook_state["throttle_warned_ts"] < 60:
        return  # already warned recently
    _progress_hook_state["throttle_warned_ts"] = now

    # NOTE: _get_cookies_path() RAISES when cookies are absent, which is
    # exactly the case this warning fires in. Never call it unguarded here.
    try:
        cookies_path: str | None = _get_cookies_path()
    except Exception:
        cookies_path = None
    if cookies_path:
        cookies_state = f"✅ cookies.txt terbaca ({cookies_path})"
    else:
        where = " atau ".join(str(p) for p in _cookies_search_dirs()[:2])
        cookies_state = f"⚠️ cookies.txt TIDAK ada — taruh di: {where}"
    multi = "aktif" if get_aria2c_path() else "TIDAK aktif (aria2c tidak ditemukan)"
    log(
        f"⚠️ YouTube membatasi koneksi: hanya {kiB_s:.0f} KiB/s. Ini cap "
        "per-koneksi YouTube untuk klien non-browser, bukan jaringan Bos. "
        f"Multi-koneksi: {multi}. {cookies_state}. "
        "Export cookies dari browser yang sudah login ke YouTube (ekstensi "
        "'Get cookies.txt LOCALLY') lalu taruh di folder aplikasi — ini "
        "mitigasi paling handal karena request terautentikasi tidak kena cap."
    )


_progress_hook_state: dict = {"last_ts": 0.0, "last_pct": None, "throttle_warned_ts": 0.0}


class _YTDlpLogger:
    """Forward yt-dlp's own log lines to our sidecar log fn.

    yt-dlp emits a lot of useful messages (extractor selection, format
    probing, fragment retries, 403s, merge steps) that are silenced by
    ``quiet: True``. Passing an instance of this class via ``ydl_opts[
    "logger"]`` surfaces info/warning/error lines so the user can see what
    yt-dlp is actually doing while a section download is in flight — instead
    of a silent hang at "FFmpeg path resolved: ...".
    """

    def __init__(self, log: LogFn, state: dict | None = None) -> None:
        self._log = log
        self._state = state

    def debug(self, msg: str) -> None:
        # When yt-dlp starts fetching m3u8 manifests or fragments, extraction
        # is DONE and the download phase has begun.  Signal the watchdog so
        # it doesn't fire during slow CDN connections (>90s on throttled
        # Indonesian links).
        if self._state is not None and (
            "Downloading m3u8" in msg or "Downloading item" in msg
        ):
            self._state["download_phase_active"] = True
        # yt-dlp's debug channel is extremely noisy (per-fragment bytes),
        # so we only surface the lines that hint at *what* yt-dlp is doing
        # right now, not the byte counters. "Downloading fragment" is
        # excluded on purpose — on HLS it fires per fragment (thousands
        # of times) and would flood the sidecar stdout pipe.
        # CRITICAL (v2.0.28): "[download] X% of ~ YMiB at ZKiB/s (frag N/M)"
        # progress lines must NEVER be forwarded. With
        # concurrent_fragment_downloads=8, yt-dlp emits one per fragment per
        # thread (~10-30 lines/sec), flooding the log AND hammering CPU on
        # low-end machines (Celeron 2-core). Progress belongs to
        # _yt_dlp_progress_hook only (rate-limited to 1 line/sec). Keep only
        # the lifecycle lines: Destination, already-downloaded skips.
        if "[download]" in msg:
            if "[download] Destination" in msg or "[download] has already" in msg:
                self._log(msg)
            return
        if any(k in msg for k in ("Downloading ", "Downloading item ", "Extracting", "Resuming", "Merging", "Deleting")):
            self._log(msg)

    def info(self, msg: str) -> None:
        self._log(msg)

    def warning(self, msg: str) -> None:
        self._log(f"⚠️ {msg}")

    def error(self, msg: str) -> None:
        self._log(f"❌ {msg}")


def _get_cookies_path() -> str:
    """Find cookies.txt in cwd, app dir, or Tauri app data dir."""
    app_dir = _get_app_dir()
    for loc in [Path("cookies.txt"), app_dir / "cookies.txt"]:
        if loc.exists():
            return str(loc)
    # Tauri app data dir
    try:
        import platform
        if platform.system() == "Windows":
            data_dir = Path(os.environ.get("APPDATA", ""))
        elif platform.system() == "Darwin":
            data_dir = Path.home() / "Library" / "Application Support"
        else:
            data_dir = Path.home() / ".config"
        app_data = data_dir / "com.jipraks.ytshortclipper-v2"
        ck = app_data / "cookies.txt"
        if ck.exists():
            return str(ck)
    except Exception:
        pass
    raise RuntimeError("cookies.txt not found. Please upload cookies first.")


def _cookies_search_dirs() -> list[Path]:
    """Every directory cookies.txt is looked for in, most specific last.

    Mirrors the search order in ``_get_cookies_path`` but returns the
    directories instead of throwing, so it is safe to call from the
    throttle warning (which fires exactly when cookies are often missing).
    """
    dirs: list[Path] = []
    for d in (Path.cwd(), _get_app_dir()):
        # cwd and the app dir are the same folder for a portable install,
        # which would otherwise print the same path twice in the hint.
        if d and d not in dirs:
            dirs.append(d)
    try:
        import platform
        if platform.system() == "Windows":
            data_dir = Path(os.environ.get("APPDATA", ""))
        elif platform.system() == "Darwin":
            data_dir = Path.home() / "Library" / "Application Support"
        else:
            data_dir = Path.home() / ".config"
        if str(data_dir):
            dirs.append(data_dir / "com.jipraks.ytshortclipper-v2")
    except Exception:
        pass
    return dirs


def cut_video_section(
    full_path: str,
    output_path: str,
    start_time: str,
    end_time: str,
    log: LogFn | None = None,
    gpu_config: dict[str, Any] | None = None,
) -> str:
    """Cut a full downloaded video to [start_time, end_time] — ACCURATE RE-ENCODE.

    v2.0.74 (caption/audio desync fix): this is intentionally NOT a
    ``-ss + -c copy`` trim. Stream-copy can only start at a keyframe
    at-or-BEFORE the requested start (up to a whole GOP earlier — ~2s typical
    on YouTube, 10s+ on some HLS). ``-avoid_negative_ts make_zero`` then hid
    the shift by re-basing the file's t=0 to that early keyframe, while
    captions were rebased by the REQUESTED clip start — so every subtitle
    appeared (clip_start − keyframe) seconds away from the actual speech
    (the "caption/ucapan tidak sinkron, ada delay" report).

    Decoding with ``-ss`` is frame-accurate, and re-encoding naturally writes
    0-based timestamps, so the section starts EXACTLY at clip_start with
    audio, video and later-rendered captions sharing the same t=0. The audio
    is re-encoded (not copied) so its timestamps are normalized together with
    the video. A video-only source (SABR/240p) is handled with ``-an``.

    If a hardware encoder was requested and fails at runtime, retries once
    with CPU libx264 so the clip still completes.
    """
    log = log or debug_log
    import shutil
    import subprocess
    import sys

    ffmpeg_path = get_ffmpeg_path()
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    log("Cutting downloaded video to requested section (exact start, re-encode)...")

    # Probe the source for an audio stream (video-only downloads must not
    # fail on `-c:a aac` when there is no audio input).
    probe = subprocess.run(
        [str(ffmpeg_path), "-hide_banner", "-i", str(full_path)],
        capture_output=True, creationflags=flags,
    )
    has_audio = b"Audio:" in (probe.stderr or b"")

    if gpu_config and gpu_config.get("available"):
        log(f"Cut encode: GPU {gpu_config.get('name')} (preset={gpu_config.get('preset')})")
        video_enc_args = build_video_enc_args(gpu_config)
    else:
        log("Cut encode: CPU libx264 (ultrafast)")
        video_enc_args = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "18"]
    audio_args = ["-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"]

    def run_cut(enc_args: list[str], audio: list[str], tag: str) -> str:
        cut_output = output_path + ".cut.mp4"
        cmd = [
            str(ffmpeg_path), "-y",
            "-ss", start_time,
            "-to", end_time,
            "-i", str(full_path),
            *enc_args,
            "-pix_fmt", "yuv420p",
            *audio,
            str(cut_output),
        ]
        log(f"Cut ({tag}): {start_time} -> {end_time}")
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to cut video section with ffmpeg: {result.stderr[:600]}"
            )
        shutil.move(cut_output, output_path)
        return output_path

    try:
        return run_cut(video_enc_args, audio_args, "primary")
    except Exception:
        if gpu_config and gpu_config.get("available"):
            log("⚠️ Hardware cut encode failed — retrying once with CPU libx264")
            return run_cut(
                ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "18"],
                audio_args, "CPU fallback",
            )
        raise


def download_video_section(
    url: str,
    start_time: str,
    end_time: str,
    output_path: str,
    log: LogFn | None = None,
    max_height: int = 1080,
    gpu_config: dict[str, Any] | None = None,
) -> str:
    """Download a specific section of a YouTube video.

    ``max_height`` caps the source resolution (1080/720/480...) — smaller
    caps = smaller download = faster on throttled links. Shorts output is
    1080x1920 max, so 720p is plenty for most cases.

    Returns path to the downloaded file.
    """
    log = log or debug_log
    start_clean = start_time.replace(",", ".")
    end_clean = end_time.replace(",", ".")

    if is_ytdlp_module_available():
        return _download_section_module(
            url, start_clean, end_clean, output_path, log, max_height, gpu_config
        )
    else:
        raise RuntimeError(
            "yt-dlp Python module is required for downloading video sections. "
            "Install it with: pip install yt-dlp"
        )


def _download_section_module(
    url: str,
    start_time: str,
    end_time: str,
    output_path: str,
    log: LogFn,
    max_height: int = 1080,
    gpu_config: dict[str, Any] | None = None,
) -> str:
    import yt_dlp

    log(f"Downloading section {start_time} -> {end_time}...")
    log(f"Source quality: max {max_height}p (H.264) — smaller quality = smaller file & faster download")

    _setup_ytdlp_env()
    ffmpeg_path = get_ffmpeg_path()
    cookies_path = _get_cookies_path()

    format_selector = _build_format_selector(max_height)

    # v2.0.32: Ranged section download (download_ranges) was trialled here
    # (2026.8.19) to fetch only the highlight's time window instead of the
    # whole 64-min source. It failed in E2E: yt-dlp forces FFmpegFD for
    # ranged formats → single connection, no progress-hook activity → app
    # watchdog aborted after 150s. Reverted to full-download + local cut
    # (tested in v2.0.31); ranges stay a candidate for a future release.

    download_state = {
        "last_log_ts": time.monotonic(),
        "last_pct": None,
        "last_detail": "",
        "first_activity_ts": None,
        "download_phase_active": False,  # set by _YTDlpLogger when m3u8/frag seen
    }

    ydl_opts: dict[str, Any] = {
        "format": format_selector,
        "format_sort": ["res", "br"],
        "merge_output_format": "mp4",
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": False,
        # v2.0.28: suppress yt-dlp's OWN progress rendering entirely
        # ("[download] X% of ~ YMiB ... (frag N/M)" lines). With 8 parallel
        # fragments those fire ~10-30x/sec and hammer CPU on low-end machines.
        # progress_hooks still fire (watchdog + UI progress keep working), only
        # the raw console/logger rendering is disabled.
        "noprogress": True,
        "hls_prefer_native": True,
        # NOTE: ranged section download (download_ranges callback) was trialled
        # on 2026.8.19 but yt-dlp forces FFmpegFD for ranged formats, which
        # stalls on throttled links with NO progress-hook activity → the app's
        # own watchdog aborts. Kept full-download + local cut as primary;
        # ranges may return as an option in a future release after testing.
        # Parallel fragment connections — ONLY meaningful for fragmented
        # transports. YouTube's `bestvideo+bestaudio` is a plain progressive
        # MP4 (one file, one connection), so this option is a NO-OP for our
        # format. It stays because it does help if an HLS/DASH format is ever
        # selected, but the REAL per-connection defence is aria2c below
        # (v2.0.82) — see _build_downloader_opts.
        "concurrent_fragment_downloads": 8,
        # Anti-throttle flags (v2.0.82):
        #  - throttled_rate: if the measured speed falls below this, yt-dlp
        #    assumes server-side throttling and RE-EXTRACTS the video, which
        #    gets fresh CDN URLs. The single most effective no-dependency
        #    mitigation: throttling is a per-URL/per-session decision, so new
        #    URLs often escape it.
        #  - sleep_interval: pace the extractor requests so a burst of
        #    downloads doesn't get our IP flagged in the first place.
        # 100 KiB/s is well below a healthy Indonesian line but well above
        # the 1-99 KiB/s we measured under the cap, so it only fires when
        # something is actually wrong.
        "throttled_rate": 100 * 1024,
        "sleep_interval": 1.0,
        "max_sleep_interval": 5.0,
        # Fail fast on dead connections (ISP NAT drops, throttled YouTube):
        "socket_timeout": 10,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
        # CRITICAL (2026-09): force player clients that do NOT require the
        # BotGuard JS challenge. The defaults for authenticated sessions are
        # ('tv_downgraded', 'web') — the 'web' client needs a po_token and
        # a JS runtime, and yt-dlp lazily downloads the 'ejs' challenge
        # component from GitHub to solve it. On networks where GitHub is
        # slow/blocked (common in Indonesia), extraction HANGS forever after
        # "Downloading webpage" with no error. visionos/ios/android return
        # stream info directly without any JavaScript challenge.
        "extractor_args": {
            "youtube": {
                "player_client": ["visionos", "ios", "android", "tv_downgraded"],
                "player_skip": ["js"],
            },
        },
        # Overall extraction timeout (seconds). yt-dlp hangs here if YouTube
        # blocks or the connection silently dies mid-handshake.
        "extractor_timeout": 30,
        # NO download_ranges / force_keyframes_at_cuts here on purpose: ranged
        # downloads hand the network I/O to FFmpegFD (ffmpeg, single
        # connection), and YouTube throttles non-browser clients per-connection
        # (~10-20 KiB/s on Indonesian lines — an 85s section would take hours).
        # Full download + local cut stays the primary path. The per-connection
        # cap is handled by aria2c above (real multi-connection); the section
        # is then cut locally with ffmpeg -c copy (no network involved).
        "cookiefile": cookies_path,
        "logger": _YTDlpLogger(log, download_state),
        "progress_hooks": [
            lambda d: _yt_dlp_progress_hook(d, log)
        ],
    }

    # Multi-connection downloader (v2.0.82). Added last so it overrides
    # nothing above; returns {} when aria2c is absent (native fallback).
    aria2_path = get_aria2c_path()
    ydl_opts.update(_build_downloader_opts(aria2_path, log))
    if aria2_path:
        log("⚡ Multi-connection aktif (aria2c, 16 koneksi) — ini yang "
            "menaklok throttle YouTube per-koneksi.")

    deno_path = get_deno_path()
    if deno_path and Path(deno_path).exists():
        ydl_opts["js_runtimes"] = {"deno": {"path": deno_path}}
        # NOTE: deliberately NOT setting remote_components=["ejs:github"] —
        # yt-dlp lazily fetches the ejs challenge solver from GitHub at
        # runtime, which can HANG extraction on slow/blocked networks. We
        # force JS-less player clients instead (see extractor_args above),
        # so the ejs solver is never needed.

    if ffmpeg_path and Path(ffmpeg_path).exists():
        ffmpeg_dir = str(Path(ffmpeg_path).parent)
        ydl_opts["ffmpeg_location"] = ffmpeg_dir
        os.environ["PATH"] = f"{ffmpeg_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        log(f"FFmpeg path resolved: {ffmpeg_path}")
    else:
        raise RuntimeError(
            f"FFmpeg is required for downloading video sections but was not found. "
            f"Last path checked: {ffmpeg_path!r}. "
            "Please ensure ffmpeg is bundled with the app (ffmpeg/ffmpeg.exe next to "
            "the sidecar) or installed on the system PATH."
        )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    def _hook_with_heartbeat(d: dict) -> None:
        # Update heartbeat timestamp whenever yt-dlp reports activity
        download_state["last_log_ts"] = time.monotonic()
        if download_state["first_activity_ts"] is None:
            download_state["first_activity_ts"] = time.monotonic()
        # Track sustained crawl so the watchdog can abort and re-roll the
        # player client (v2.0.82). Cheap: two dict lookups per progress event.
        _sustained_throttle_check(d, download_state, log)
        if d.get("status") == "downloading":
            pct, detail = _extract_progress(d)
            if pct is not None:
                download_state["last_pct"] = pct
            if detail:
                download_state["last_detail"] = detail
        _yt_dlp_progress_hook(d, log)

    ydl_opts["progress_hooks"] = [_hook_with_heartbeat]

    stop_evt = threading.Event()

    def heartbeat() -> None:
        started = time.monotonic()
        every = 15
        while not stop_evt.wait(every):
            elapsed = int(time.monotonic() - started)
            since_last_log = int(time.monotonic() - download_state["last_log_ts"])
            pct = download_state["last_pct"]
            detail = download_state["last_detail"]
            first = download_state["first_activity_ts"]
            if first is None:
                log(
                    f"⏳ Preparing download... {elapsed}s elapsed "
                    "(fetching stream info / connecting). Can take a while on slow networks."
                )
            elif pct is not None:
                log(f"⏳ Still downloading: {pct}% ({detail}), {elapsed}s elapsed")
            elif detail:
                log(f"⏳ Still downloading: {detail}, {elapsed}s elapsed (no progress % yet)")
            elif since_last_log > 120:
                log(
                    f"⚠️ Download appears stalled — no data for {since_last_log}s. "
                    "If the connection is dead, the app will retry automatically with a simpler method."
                )
            else:
                log(
                    f"⏳ Waiting for download data... {elapsed}s elapsed, "
                    f"{since_last_log}s since last activity"
                )

    hb_thread = threading.Thread(target=heartbeat, daemon=True, name="yt-dlp-heartbeat")
    hb_thread.start()

    # --- Extraction watchdog ---
    # If yt-dlp never calls the progress hook (extraction stuck), abort after
    # _EXTRACT_ABORT seconds so the app doesn't hang forever.
    _EXTRACT_ABORT = 90  # 90s: extraction normally takes <15s with JS-less clients
    # Once extraction is done (m3u8 manifest / download phase seen), the
    # watchdog above must NOT kill a legitimately slow CDN fetch — but it also
    # must not exit permanently: if the m3u8/manifest fetch then STALLS forever
    # (dead NAT on throttled links — no progress hook fires, no debug lines),
    # nothing else would ever abort. Keep watching; abort only after this much
    # time with ZERO log/hook activity. Legit m3u8 fetches take 90-100s on
    # Indonesian throttled links, so 150s gives margin without hanging forever.
    _DOWNLOAD_STALL_ABORT = 150
    _abort = threading.Event()

    def _extraction_watchdog() -> None:
        """Guard extraction AND download phases from silent stalls.

        Phase 1 (extraction): abort after _EXTRACT_ABORT with no progress-hook
        activity. Phase 2 (download): extraction is done (progress hook fired
        or \"Downloading m3u8\"/\"Downloading item\" debug seen) — keep
        watching, but only abort once _DOWNLOAD_STALL_ABORT passes with no
        data/log activity at all. Both phases share one loop.
        """
        while not _abort.wait(15):
            first = download_state.get("first_activity_ts")
            dl_active = download_state.get("download_phase_active", False)
            if first is not None or dl_active:
                # Download phase: extraction finished. Last-resort guard for a
                # manifest (m3u8) fetch that hangs forever — no progress hook
                # fires, the connection may be dead. Fall through only when
                # data truly stalled; real downloads refresh last_log_ts via
                # the progress hook on every fragment.
                last_activity = download_state.get("last_log_ts") or _download_start
                idle_for = int(time.monotonic() - last_activity)
                if idle_for < _DOWNLOAD_STALL_ABORT:
                    continue  # still alive — keep watching
                log(
                    f"⚠️ Download phase stalled — no data for {idle_for}s. "
                    "Aborting and retrying with fallback options..."
                )
                _abort.set()
                return
            elapsed = int(time.monotonic() - _download_start)
            if elapsed >= _EXTRACT_ABORT:
                log(
                    f"⚠️ Extraction stuck for {elapsed}s with no response — "
                    "aborting and retrying with fallback options..."
                )
                _abort.set()
                return

    _download_start = time.monotonic()
    _watchdog = threading.Thread(target=_extraction_watchdog, daemon=True, name="yt-dlp-watchdog")
    _watchdog.start()

    def _run_download(ydl_opts_local: dict, label: str) -> None:
        """Run yt-dlp download in a thread, aborting if watchdog fires."""
        dl_thread = threading.Thread(
            target=lambda: yt_dlp.YoutubeDL(ydl_opts_local).download([url]),
            daemon=True, name=f"yt-dlp-dl-{label}",
        )
        dl_thread.start()
        while dl_thread.is_alive():
            if _abort.is_set():
                if download_state.get("sustained_throttle"):
                    # Distinct from a stall: the bytes ARE arriving, just far
                    # too slowly. Callers retry this with another player
                    # client rather than falling back to a simpler format.
                    raise _SustainedThrottle(
                        f"Download ({label}) crawling for "
                        f"{_SUSTAINED_THROTTLE_SECS}s+ under "
                        f"{_SUSTAINED_THROTTLE_BPS // 1024} KiB/s — "
                        "retrying with a different YouTube client."
                    )
                raise RuntimeError(
                    f"Download ({label}) aborted: extraction timed out after "
                    f"{_EXTRACT_ABORT}s with no activity. Check your network or try again."
                )
            dl_thread.join(timeout=5)

    def _cut_section(full_path: str) -> str:
        """Cut a full downloaded video to [start_time, end_time].

        v2.0.74: delegates to the module-level ACCURATE RE-ENCODE cut (the
        old ``-ss + -c copy`` trim started at a keyframe before the requested
        start, shifting caption timing vs the speech — see
        ``cut_video_section`` docstring). The section is 720p-capped so the
        extra encode is cheap; the portrait stage re-encodes it anyway.
        """
        stop_evt.set()  # download phase done — stop the heartbeat thread
        log("Cutting downloaded video to requested section...")
        return cut_video_section(
            full_path, output_path, start_time, end_time,
            log=log, gpu_config=gpu_config,
        )

    def _do_download() -> str:
        """Primary: multi-connection full download + local cut → fallback.

        Kept as the tested, reliable path (v2.0.31+): download the whole
        video, then cut the section locally with ffmpeg. Ranged section
        download was trialled on yt-dlp 2026.8.19 but stalls (FFmpegFD,
        no progress) — see ydl_opts note.

        v2.0.82 adds a **client ladder**: on sustained throttle we retry the
        whole download with a different YouTube player client before giving
        up, because the per-connection cap is decided per client identity.
        """
        e_download: Exception | None = None
        for client_idx, clients in enumerate(_CLIENT_LADDER):
            # Reset per-attempt throttle bookkeeping, otherwise a previous
            # attempt's flag would immediately abort the retry.
            download_state["throttle_since"] = None
            download_state["sustained_throttle"] = False
            # Fresh watchdog for each client attempt.
            if client_idx > 0:
                _abort.clear()
                download_state["first_activity_ts"] = None
                download_state["download_phase_active"] = False
                threading.Thread(
                    target=_extraction_watchdog, daemon=True,
                    name=f"yt-dlp-watchdog-client{client_idx}",
                ).start()
                log(
                    f"🔄 YouTube membatasi client sebelumnya — mencoba "
                    f"client {client_idx + 1}/{len(_CLIENT_LADDER)}: "
                    f"{', '.join(clients)}"
                )

            client_opts = dict(ydl_opts)
            client_opts["extractor_args"] = {
                "youtube": {
                    "player_client": list(clients),
                    "player_skip": ["js"],
                },
            }

            # Retry-on-WinError-32 loop: the final .part → .mp4 rename can
            # fail on Windows when antivirus briefly locks the file.
            for attempt in range(1, 4):
                try:
                    _run_download(client_opts, f"c{client_idx}-a{attempt}")
                    return _cut_section(_find_downloaded_file(output_path))
                except _SustainedThrottle:
                    # Not a hard failure — break to the next client, but
                    # keep the exception as e_download so a final failure
                    # still reports something meaningful.
                    e_download = RuntimeError("throttled by YouTube")
                    break
                except Exception as e:
                    e_download = e
                    msg = str(e)
                    rename_locked = (
                        "Unable to rename file" in msg
                        or "WinError 32" in msg
                        or "being used by another process" in msg
                    )
                    if rename_locked and attempt < 3:
                        log(
                            f"⚠️ Rename lock (WinError 32) on attempt "
                            f"{attempt}/3 — file busy (antivirus?), retrying in 5s..."
                        )
                        time.sleep(5)
                        continue
                    break  # real failure → next client / fallback below

        msg = str(e_download)
        log(f"Section download failed: {msg[:200]}")
        if "403" in msg or "Forbidden" in msg:
            raise RuntimeError(
                "YouTube rejected access (HTTP 403). Your cookies may have expired. "
                "Please export fresh cookies while logged into YouTube."
            )

        log("Retrying with fallback options (simple format + no ranges)...")
        fallback_opts = dict(ydl_opts)
        fallback_opts.pop("download_ranges", None)
        fallback_opts.pop("downloader", None)
        fallback_opts.pop("force_keyframes_at_cuts", None)
        fallback_opts["format"] = _build_format_selector(max_height)
        download_state["last_log_ts"] = time.monotonic()
        download_state["last_pct"] = None
        download_state["last_detail"] = "(fallback retry)"
        download_state["download_phase_active"] = False
        # Reset watchdog for the fallback attempt
        _abort.clear()
        download_state["first_activity_ts"] = None
        _watchdog_fallback = threading.Thread(
            target=_extraction_watchdog, daemon=True, name="yt-dlp-watchdog-fallback"
        )
        _watchdog_fallback.start()
        try:
            _run_download(fallback_opts, "fallback")
        except Exception as e2:
            msg2 = str(e2)
            log(f"Fallback download also failed: {msg2[:200]}")
            raise RuntimeError(f"Failed to download video section: {msg2}")

        # Fallback downloaded the full video — cut locally (same helper as primary)
        return _cut_section(_find_downloaded_file(output_path))

    try:
        result_path = _do_download()
    finally:
        stop_evt.set()
        hb_thread.join(timeout=2)

    return result_path
