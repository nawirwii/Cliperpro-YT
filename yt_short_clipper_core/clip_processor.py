"""Process selected highlights: download → portrait → hook → caption → watermark."""

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

LogFn = Callable[[str], None]

# Hide ffmpeg's console window on Windows (CREATE_NO_WINDOW), like every
# other ffmpeg call in this codebase. Without it the intro/outro probe and
# render pop a visible black console window.
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

from .video_processor import download_video_section, cut_video_section
from .source_library import library_paths
from .portrait import convert_to_portrait, convert_to_portrait_centered, convert_to_portrait_pane
from .split_screen import combine_split_screen, OUTPUT_HEIGHT
from .hook_generator import generate_hook
from .caption_generator import generate_captions_from_words
from .srt_parser import parse_srt_segments, parse_timestamp
from .watermark import apply_watermark
from .helpers import get_ffmpeg_path


def sanitize_clip_filename(title: str) -> str:
    """Turn a clip title into a Windows-safe file stem.

    Rules (mirrored by sanitizeClipFilename in HighlightSelectionPage.tsx):
    - Replace Windows-illegal characters <>:"/\\|?* and control characters
      (U+0000-U+001F) with "-".
    - Collapse runs of whitespace to a single space.
    - Strip leading/trailing spaces and dots.
    - Cap at 120 characters, then strip trailing spaces/dots again.
    - Fall back to "Untitled" when nothing remains.
    Other Unicode (e.g. Indonesian letters) is kept as-is.
    """
    name = "".join(
        "-" if (c in '<>:"/\\|?*' or ord(c) < 0x20) else c for c in (title or "")
    )
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > 120:
        name = name[:120].rstrip(" .")
    return name or "Untitled"


def _load_caption_words(session_path: Path, log: LogFn) -> list[dict[str, Any]]:
    """Load the full-video word-timing list saved during the find-highlights phase.

    Returns an empty list when the video had no original subtitle track (in
    which case captions are skipped but clips are still produced).
    """
    words_file = session_path / "words.json"
    if not words_file.exists():
        log("No words.json in session — captions will be skipped for all clips")
        return []
    try:
        with open(words_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"Failed to read words.json: {str(e)[:200]} — captions will be skipped")
        return []


def _words_for_clip(
    all_words: list[dict[str, Any]],
    clip_start: float,
    clip_end: float,
) -> list[dict[str, Any]]:
    """Slice words overlapping [clip_start, clip_end] and shift to clip-relative time."""
    sliced: list[dict[str, Any]] = []
    for w in all_words:
        if w["end"] < clip_start or w["start"] > clip_end:
            continue
        rel_start = max(0.0, w["start"] - clip_start)
        rel_end = w["end"] - clip_start
        if rel_end <= 0:
            continue
        sliced.append({"word": w["word"], "start": rel_start, "end": rel_end})
    return sliced


def _load_session_channel(session_path: Path) -> str:
    """Load the YouTube channel name saved during the find-highlights phase.

    The placeholder `{channel}` in the credit text is replaced with this
    value at render time. Falls back to an empty string when the session file
    is missing or the channel could not be detected.
    """
    try:
        data_file = session_path / "session_data.json"
        if not data_file.exists():
            return ""
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        channel = (data.get("video_info") or {}).get("channel") or ""
        return str(channel).strip()
    except Exception:
        return ""


def _mark_processed_highlights(session_path: Path, indices: list[int], log: LogFn) -> None:
    """Record freshly rendered clips in ``session_data.json``.

    The highlights page only shows the "Clip ready" footer (View + open
    folder button) for indices listed in ``processed_highlights`` — but
    nothing ever wrote that field, so the footer could never appear. This
    merges the new indices into the saved session file (dedupe + sorted)
    so the mark survives app restarts and Library loads. Best-effort: a
    missing or unreadable session file must never break the render.
    """
    if not indices:
        return
    try:
        data_file = session_path / "session_data.json"
        if not data_file.exists():
            log("Session data file not found — processed clips not recorded")
            return
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        existing = data.get("processed_highlights") or []
        merged = sorted({i for i in existing if isinstance(i, int)} | set(indices))
        data["processed_highlights"] = merged
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log(f"Marked {len(indices)} clip(s) as processed in session data")
    except Exception as exc:
        log(f"Warning: could not record processed clips in session data: {exc}")


def _resolve_credit_text(
    credit_config: dict[str, Any] | None,
    options: dict[str, Any],
    session_path: Path,
    log: LogFn,
) -> dict[str, Any] | None:
    """Apply per-clip credit text overrides and resolve the {channel} placeholder.

    Priority:
      1. `options.creditText` — the value typed in the process confirm dialog
         (this is what the user actually sees, so it wins over saved config).
      2. `ai.credit_watermark.text` from the saved app config.
    Then `{channel}` is replaced with the real YouTube channel name.
    """
    if not credit_config:
        return None
    text = str(credit_config.get("text") or "").strip()
    dialog_text = str(options.get("creditText") or "").strip()
    if dialog_text:
        text = dialog_text

    if "{channel}" in text:
        channel = _load_session_channel(session_path)
        if channel:
            text = text.replace("{channel}", channel)
            log(f"Credit text channel: {channel}")
        else:
            # Keep the template but note that the channel name was unavailable.
            log("Credit text: {channel} left unresolved (no channel info in session)")

    resolved = dict(credit_config)
    resolved["text"] = text
    return resolved


def _resolve_gpu_config(gpu_config: dict[str, Any] | None, log: LogFn) -> dict[str, Any] | None:
    """Ensure an enabled GPU config carries an encoder.

    Older builds saved only `{"enabled": true}` — no encoder/preset — so the
    backend saw `encoder=None` and silently encoded with libx264 (CPU). If
    enabled but missing an encoder, re-detect once at runtime so existing users
    get hardware encoding without re-toggling the setting.

    The returned dict carries both key shapes: the current `enabled` /
    `encoder` / `preset` shape used by portrait/split_screen, plus the
    legacy `available` / `name` shape still expected by
    `build_video_enc_args` (hook/caption burn steps) and video_processor's
    cut encode. Without this, those steps silently fall back to CPU even
    with GPU acceleration enabled.
    """
    if not gpu_config or not gpu_config.get("enabled"):
        return gpu_config
    encoder = gpu_config.get("encoder")
    if not encoder:
        try:
            from .gpu import detect_gpu
            det = detect_gpu()
            enc = (det or {}).get("encoder") or {}
            if enc.get("available") and enc.get("name"):
                encoder = enc["name"]
                gpu_config = {
                    "enabled": True,
                    "encoder": encoder,
                    "preset": enc.get("preset"),
                }
                log(f"GPU config missing encoder — resolved: {encoder} (preset={enc.get('preset')})")
            else:
                log("GPU acceleration enabled but no encoder available — falling back to CPU")
                return gpu_config
        except Exception as e:
            log(f"GPU re-detect failed ({e}) — falling back to CPU")
            return gpu_config
    # Normalize: legacy consumers (hook/caption burn, cut encode) expect
    # {"available": True, "name": <encoder>}.
    normalized = dict(gpu_config)
    normalized["available"] = True
    normalized["name"] = normalized.get("name") or encoder
    return normalized


def _run_portrait(input_path: str, output_path: str, options: dict[str, Any], log: LogFn, gpu_config: dict[str, Any] | None = None) -> str:
    """Run portrait conversion — face-tracked or centered, based on reframeMode."""
    reframe_mode = options.get("reframeMode", "face")
    if reframe_mode == "centered":
        background = options.get("centeredBackground", "black")
        return convert_to_portrait_centered(input_path, output_path, background=background, log=log, gpu_config=gpu_config)
    return convert_to_portrait(input_path, output_path, log=log, gpu_config=gpu_config)


def process_selected_highlights(
    url: str,
    highlights: list[dict[str, Any]],
    session_dir: str,
    options: dict[str, Any],
    ai: dict[str, Any],
    log: LogFn,
    local_path: str | None = None,
) -> dict[str, Any]:
    """Process selected highlights and return output info.

    `local_path` (optional): when set, sections are cut from this local file
    with `cut_video_section` instead of being downloaded from YouTube.

    options keys: addCaptions, addHook, addWatermark, addCreditWatermark,
                  introPath, outroPath, gpuAcceleration (optional, for hardware encoding)
    ai keys: api_key, base_url, model, hook_style (dict, includes duration_seconds)
    """
    gpu_config = _resolve_gpu_config(options.get("gpuAcceleration"), log)
    session_path = Path(session_dir)
    clips_dir = session_path / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # Persistent source library (DOWNLOAD ONCE, CLIP MANY TIMES): stored
    # sources live under output/source_videos/, shared across sessions, so
    # a later batch of clips for the same URL cuts from the saved file
    # instead of downloading again.
    library_root, _library_db = library_paths(session_path)

    temp_dir = session_path / "_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    total = len(highlights)
    results: list[dict[str, Any]] = []

    add_hook = options.get("addHook", False)
    add_captions = options.get("addCaptions", False)
    add_watermark = options.get("addWatermark", False)
    add_credit_watermark = options.get("addCreditWatermark", False)
    add_intro_outro = options.get("addIntroOutro", False)
    intro_path = options.get("introPath")
    outro_path = options.get("outroPath")
    try:
        crossfade_duration = float(options.get("crossfadeDuration", 0.9))
    except (TypeError, ValueError):
        crossfade_duration = 0.9
    caption_style = options.get("captionStyle", "Creator Pop")


    # Split screen mode: stack a local video (webcam) under the main video.
    split_screen = options.get("splitScreen") or {}
    split_enabled = bool(split_screen.get("enabled")) and bool(split_screen.get("webcamPath"))
    split_webcam_path = str(split_screen.get("webcamPath", ""))
    if split_enabled and not Path(split_webcam_path).exists():
        log(f"Split screen disabled: local video not found at {split_webcam_path}")
        split_enabled = False
    try:
        split_top_ratio = float(split_screen.get("topRatio", 0.80))
    except (TypeError, ValueError):
        split_top_ratio = 0.80
    # Audio balance for split-screen (0.0-1.0 each). Default 1.0 = source volume.
    try:
        split_main_volume = float(split_screen.get("mainVolume", 1.0))
    except (TypeError, ValueError):
        split_main_volume = 1.0
    try:
        split_second_volume = float(split_screen.get("secondVolume", 1.0))
    except (TypeError, ValueError):
        split_second_volume = 1.0
    split_main_volume = max(0.0, min(2.0, split_main_volume))
    split_second_volume = max(0.0, min(2.0, split_second_volume))

    # Position of webcam: "top" or "bottom" (default: "bottom")
    split_position = split_screen.get("position", "bottom")
    if split_position not in ("top", "bottom"):
        split_position = "bottom"
    # Mode for second pane: "landscape" (default) or "portrait"
    second_pane_mode = split_screen.get("secondPaneMode", "portrait")

    # Word-level caption timing for the full source video (from the original
    # subtitle track). Empty if unavailable — captions are then skipped.
    caption_words = _load_caption_words(session_path, log) if add_captions else []
    if add_captions and not caption_words:
        log("Captions requested but no subtitle word-timing available — clips will have no captions")

    for i, h in enumerate(highlights, 1):
        log(f"Processing clip {i}/{total}: {h.get('title', 'Untitled')}")

        # Use highlight_index from the highlight data if available (for dedup)
        highlight_index = h.get("_highlight_index", i - 1)

        # Check if this highlight was already processed. A titled file from
        # this build wins; a legacy master.mp4 from older builds still counts
        # so previously processed clips are not re-processed.
        clip_folder = clips_dir / f"clip_{highlight_index:03d}"
        titled_file = clip_folder / f"{sanitize_clip_filename(h.get('title', 'Untitled'))}.mp4"
        legacy_master = clip_folder / "master.mp4"
        if titled_file.exists():
            existing_file = titled_file
        elif legacy_master.exists():
            existing_file = legacy_master
        else:
            existing_file = None
        if existing_file is not None:
            log(f"[{i}/{total}] Already processed (clip_{highlight_index:03d}), skipping")
            results.append({
                "clip_index": highlight_index,
                "output_path": str(existing_file),
                "title": h.get("title", ""),
                "skipped": True,
            })
            continue

        section_path = str(temp_dir / f"section_{i:03d}.mp4")

        # Step 1: Get video section — download from YouTube OR cut from a local file
        # Download quality: 1080p (default) / 720p / 480p — set by the user in
        # the ProcessConfirmDialog. Smaller values download less data (halves or
        # quarters the file) but slightly reduce source sharpness. For Shorts
        # (1080x1920 output), 720p is the sweet spot between speed and quality.
        quality_map = {"1080p": 1080, "720p": 720, "480p": 480, "360p": 360, "240p": 240}
        max_height = quality_map.get(options.get("downloadQuality", "720p"), 720)

        if local_path:
            if not Path(local_path).exists():
                raise RuntimeError(f"Local source video not found: {local_path}")
            log(f"[{i}/{total}] Source: local file — cutting {h['start_time']} -> {h['end_time']}...")
            video_path = cut_video_section(
                full_path=local_path,
                output_path=section_path,
                start_time=h["start_time"],
                end_time=h["end_time"],
                log=lambda m: log(f"[{i}/{total}] {m}"),
                gpu_config=gpu_config,
            )
        else:
            log(f"[{i}/{total}] Download quality: max {max_height}p")
            log(f"[{i}/{total}] Downloading video section {h['start_time']} -> {h['end_time']}...")
            video_path = download_video_section(
                url=url,
                start_time=h["start_time"],
                end_time=h["end_time"],
                output_path=section_path,
                log=log,
                max_height=max_height,
                gpu_config=gpu_config,
                library_root=str(library_root),
                force_redownload=bool(options.get("forceRedownload", False)),
            )
        log(f"[{i}/{total}] Section ready: {video_path}")

        # Step 2: Portrait conversion (or split-screen composition)
        portrait_path = str(temp_dir / f"portrait_{i:03d}.mp4")
        if split_enabled:
            # Split-screen: FIRST reframe the main video into a face-tracked
            # portrait pane sized to the top pane (1080 x {ratio} of 1920),
            # so the top half is a true portrait crop with no black bars.
            # Then stack the local video (cover-cropped landscape strip)
            # underneath.
            log(f"[{i}/{total}] Split-screen mode: reframing main video to portrait pane (face tracking)...")
            pane_path = str(temp_dir / f"split_pane_top_{i:03d}.mp4")
            top_h = int(round(OUTPUT_HEIGHT * split_top_ratio))
            # Convert main video to portrait pane (top) — face-tracked reframe,
            # encoded with the same GPU encoder as the rest of the pipeline.
            video_path = convert_to_portrait_pane(
                video_path, pane_path,
                output_height=top_h,
                log=lambda m: log(f"[{i}/{total}] {m}"),
                gpu_config=gpu_config,
            )
            # Bottom pane stays LANDSCAPE: the raw webcam/local file goes straight
            # to combine_split_screen, which cover-crops it into a 1080x{bottom_h}
            # landscape strip (no portrait reframe — phones/webcams feed natively).
            bottom_h = OUTPUT_HEIGHT - top_h
            log(f"[{i}/{total}] Split-screen: top portrait (face tracking) {split_top_ratio:.0%} + bottom landscape {1 - split_top_ratio:.0%} — stacking")
            video_path = combine_split_screen(
                main_video_path=video_path,
                second_video_path=split_webcam_path,
                output_path=portrait_path,
                top_ratio=split_top_ratio,
                main_volume=split_main_volume,
                second_volume=split_second_volume,
                log=lambda m: log(f"[{i}/{total}] {m}"),
                gpu_config=gpu_config,
                position=split_position,
            )
        else:
            video_path = _run_portrait(video_path, portrait_path, options, log, gpu_config)
            log(f"[{i}/{total}] Portrait conversion complete")

        # Step 3: Hook generation (text overlay on the opening seconds)
        if add_hook:
            hook_text = h.get("hook_text", "")
            if hook_text:
                hook_style = ai.get("hook_style") or {}
                hook_duration = hook_style.get("duration_seconds", 5.0)

                hook_output_path = str(temp_dir / f"hooked_{i:03d}.mp4")
                video_path = generate_hook(
                    input_video_path=video_path,
                    hook_text=hook_text,
                    output_path=hook_output_path,
                    duration=hook_duration,
                    hook_style=hook_style,
                    log=log,
                    gpu_config=gpu_config,
                )
                log(f"[{i}/{total}] Hook generation complete")
            else:
                log(f"[{i}/{total}] No hook text, skipping hook generation")
        else:
            log(f"[{i}/{total}] Hook generation skipped (disabled)")

        # Step 4: Caption generation (word-by-word, from original subtitle track)
        clip_had_captions = False
        clip_start = parse_timestamp(h["start_time"])
        clip_end = parse_timestamp(h["end_time"])
        if add_captions and caption_words:
            clip_words = _words_for_clip(caption_words, clip_start, clip_end)

            if clip_words:
                caption_output_path = str(temp_dir / f"captioned_{i:03d}.mp4")
                video_path = generate_captions_from_words(
                    input_video_path=video_path,
                    output_path=caption_output_path,
                    words=clip_words,
                    caption_style=caption_style,
                    log=log,
                    gpu_config=gpu_config,
                )
                clip_had_captions = True
                log(f"[{i}/{total}] Caption generation complete ({len(clip_words)} words)")
            else:
                log(f"[{i}/{total}] No subtitle words in this clip's range — captions skipped")
        elif add_captions and local_path:
            # Local source: captions use segment timing from the Whisper
            # transcription SRT (segment-level, not word-by-word).
            local_srt = session_path / "transcript.srt"
            if local_srt.exists():
                segments = [
                    s for s in parse_srt_segments(str(local_srt))
                    if float(s["end"]) > clip_start and float(s["start"]) < clip_end
                ]
                clip_words = [
                    {
                        "word": str(s["text"]).strip().upper(),
                        "start": float(s["start"]) - clip_start,
                        "end": float(s["end"]) - clip_start,
                    }
                    for s in segments
                    if str(s["text"]).strip()
                ]
                if clip_words:
                    caption_output_path = str(temp_dir / f"captioned_{i:03d}.mp4")
                    video_path = generate_captions_from_words(
                        input_video_path=video_path,
                        output_path=caption_output_path,
                        words=clip_words,
                        caption_style=caption_style,
                        log=log,
                        gpu_config=gpu_config,
                    )
                    clip_had_captions = True
                    log(f"[{i}/{total}] Caption generation complete ({len(clip_words)} segments, from transcription)")
                else:
                    log(f"[{i}/{total}] No transcript segments in this clip's range — captions skipped")
            else:
                log(f"[{i}/{total}] No transcript for local captions — captions skipped")
        elif add_captions:
            log(f"[{i}/{total}] Caption generation skipped (no subtitle word-timing)")
        else:
            log(f"[{i}/{total}] Caption generation skipped (disabled)")

        # Step 5: Watermark overlay (logo + credit text)
        if add_watermark or add_credit_watermark:
            wm_config = ai.get("watermark") if add_watermark else None
            credit_config = _resolve_credit_text(
                ai.get("credit_watermark") if add_credit_watermark else None,
                options,
                session_path,
                log,
            )

            watermark_output_path = str(temp_dir / f"watermarked_{i:03d}.mp4")
            video_path = apply_watermark(
                input_video_path=video_path,
                output_path=watermark_output_path,
                watermark=wm_config,
                credit_watermark=credit_config,
                log=log,
                gpu_config=gpu_config,
            )
            log(f"[{i}/{total}] Watermark overlay complete")
        else:
            log(f"[{i}/{total}] Watermark overlay skipped (disabled)")

        # Step 5.5: Intro/Outro (if enabled)
        if add_intro_outro and (intro_path or outro_path):
            intro_outro_output_path = str(temp_dir / f"with_intro_outro_{i:03d}.mp4")
            intro_outro_result = apply_intro_outro(
                input_path=video_path,
                output_path=intro_outro_output_path,
                intro_path=intro_path,
                outro_path=outro_path,
                log=lambda m: log(f"[{i}/{total}] {m}"),
                gpu_config=gpu_config,
                crossfade_duration=crossfade_duration,
            )
            if intro_outro_result == video_path:
                # apply_intro_outro returns the input unchanged when the
                # render fails (e.g. an intro file that cannot be opened).
                # Say so plainly instead of logging success: the saved clip
                # has no intro/outro in that case.
                log(f"[{i}/{total}] WARNING: Intro/Outro FAILED — clip saved WITHOUT intro/outro (see FFmpeg error above)")
            else:
                video_path = intro_outro_result
                log(f"[{i}/{total}] Intro/Outro processing complete")

        # Save the final video as output, named after the clip title
        clip_folder = clips_dir / f"clip_{highlight_index:03d}"
        clip_folder.mkdir(parents=True, exist_ok=True)
        output_file = clip_folder / f"{sanitize_clip_filename(h.get('title', 'Untitled'))}.mp4"
        shutil.copy2(video_path, output_file)

        # Save metadata
        data = {
            "highlight_index": highlight_index,
            "title": h.get("title", "Untitled"),
            "hook_text": h.get("hook_text", ""),
            "start_time": h["start_time"],
            "end_time": h["end_time"],
            "duration_seconds": h.get("duration_seconds", 0),
            "has_hook": add_hook and bool(h.get("hook_text")),
            "has_captions": clip_had_captions,
            "has_intro_outro": add_intro_outro and (intro_path or outro_path),
            "intro_path": intro_path,
            "outro_path": outro_path,
            "youtube_title": h.get("title", ""),
            "youtube_description": h.get("description", ""),
            "processed_at": datetime.now().isoformat(),
        }
        with open(clip_folder / "data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        log(f"[{i}/{total}] Clip saved: {output_file}")
        results.append({
            "clip_index": highlight_index,
            "output_path": str(output_file),
            "title": h.get("title", ""),
            "skipped": False,
        })

    # v2.0.132: record the freshly rendered clips so the highlights page
    # can show the "Clip ready" footer (View + open folder button).
    done_indices = [r["clip_index"] for r in results if not r.get("skipped")]
    _mark_processed_highlights(session_path, done_indices, log)

    log(f"Processed {len(results)} clip(s)")
    return {
        "session_dir": session_dir,
        "clips_dir": str(clips_dir),
        "total_clips": total,
        "results": results,
    }


def _probe_video(path: str, ffmpeg_path: str) -> tuple[float, int | None, int | None, float | None]:
    """Probe one video file with ``ffmpeg -i`` (no ffprobe in the bundle).

    Parses ``Duration:`` and the first ``Video:`` stream line from stderr,
    the same way the rest of the codebase probes media. Returns
    ``(duration_seconds, width, height, fps)``; any value that cannot be
    read comes back as 0.0 / None. Never raises.
    """
    try:
        probe = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, timeout=30,
            creationflags=_SUBPROCESS_FLAGS,
            # ffmpeg writes UTF-8; without this, Windows decodes stderr as
            # cp1252 and every non-ASCII character in the log turns into
            # mojibake (e.g. "…" shows up as "Ã¢â‚¬Â¦").
            encoding="utf-8", errors="replace",
        )
    except Exception:
        return 0.0, None, None, None
    stderr = probe.stderr or ""
    duration = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    if m:
        h, mi, s = m.groups()
        try:
            duration = int(h) * 3600 + int(mi) * 60 + float(s)
        except ValueError:
            duration = 0.0
    width = height = None
    fps = None
    for line in stderr.splitlines():
        if ": Video:" not in line:
            continue
        vm = re.search(r",\s*(\d+)x(\d+)[,\s]", line)
        if vm:
            try:
                width, height = int(vm.group(1)), int(vm.group(2))
            except ValueError:
                width = height = None
        fm = re.search(r"(\d+(?:\.\d+)?)\s*fps", line)
        if fm:
            try:
                fps = float(fm.group(1))
            except ValueError:
                fps = None
        break
    return duration, width, height, fps


def apply_intro_outro(
    input_path: str,
    output_path: str,
    intro_path: str | None,
    outro_path: str | None,
    log: LogFn,
    gpu_config: dict[str, Any] | None = None,
    crossfade_duration: float = 0.9,
) -> str:
    """Apply intro and/or outro video with a crossfade transition
    (default 0.9s; the dialog slider allows 0.1–1.0s).

    Every video input is normalized to the clip's resolution/fps first
    (xfade requires identical size, fps and pixel format on both sides,
    else it fails with -22 EINVAL), and each fade is placed at the
    junction (end of the first video) instead of offset 0. If probing
    fails, falls back to the previous behaviour (no normalization,
    offset 0) so a working case never gets worse.

    Args:
        input_path: Path to the clip video
        output_path: Path for the output video with intro/outro
        intro_path: Path to intro video (optional)
        outro_path: Path to outro video (optional)
        log: Logging function
        crossfade_duration: Crossfade length in seconds (0.1–1.0,
            clamped; default 0.9)

    Returns:
        Path to the output video (or input_path on failure)
    """
    try:
        try:
            crossfade_dur = float(crossfade_duration)
        except (TypeError, ValueError):
            crossfade_dur = 0.9
        crossfade_dur = min(1.0, max(0.1, crossfade_dur))
        # Resolve ffmpeg the same way as every other step in this codebase
        # (bundled ffmpeg first, then PATH) — a bare "ffmpeg" is not on
        # PATH in the portable install and fails with WinError 2.
        ffmpeg_path = get_ffmpeg_path()

        # v2.0.133: encode with the same GPU encoder as every other step
        # (h264_qsv on the Latitude 3400). The xfade filter itself still
        # runs on CPU frames — xfade cannot process hardware frames — but
        # the encode, the heavy part, moves to the GPU. Falls back to
        # libx264 when GPU is off or unavailable.
        from .gpu import build_video_enc_args
        video_enc_args = build_video_enc_args(gpu_config)
        enc_name = (gpu_config or {}).get("name") if gpu_config and gpu_config.get("available") else None
        if enc_name:
            log(f"Using GPU encoder: {enc_name} (preset={(gpu_config or {}).get('preset')})")
        else:
            log("Using CPU encoder: libx264")

        # Probe the clip (the normalization target) and the intro/outro
        # (the crossfade offsets). ffprobe is not shipped in the bundle,
        # so this parses `ffmpeg -i` stderr like the rest of the codebase.
        clip_dur, clip_w, clip_h, clip_fps = _probe_video(input_path, ffmpeg_path)
        intro_dur = outro_dur = 0.0
        if intro_path:
            intro_dur, _, _, _ = _probe_video(intro_path, ffmpeg_path)
        if outro_path:
            outro_dur, _, _, _ = _probe_video(outro_path, ffmpeg_path)

        # Normalize every input to the clip's resolution/fps when we know
        # them. If probing failed, fall back to the previous behaviour.
        normalized = bool(clip_w and clip_h and clip_fps)
        if normalized:
            tw, th, tfps = clip_w, clip_h, clip_fps

            def vprep(idx: int, label: str) -> str:
                return (
                    f"[{idx}:v]scale={tw}:{th}:force_original_aspect_ratio=increase,"
                    f"crop={tw}:{th},fps={tfps:g},format=yuv420p,setsar=1[{label}];"
                )
        else:
            def vprep(idx: int, label: str) -> str:
                return f"[{idx}:v]format=yuv420p[{label}];"

        # Offset puts the fade at the junction (end of the first video),
        # not at offset 0 (the first 0.9s). Unknown durations fall back to 0.
        def off(dur: float) -> float:
            return max(0.0, dur - crossfade_dur)

        if intro_path and outro_path:
            # Both intro and outro: concat with crossfade at both ends
            if normalized:
                video = (
                    vprep(0, "v_intro")
                    + vprep(1, "v_clip")
                    + vprep(2, "v_outro")
                    + f"[v_intro][v_clip]xfade=transition=fade:duration={crossfade_dur}:offset={off(intro_dur):g}[v0];"
                    + f"[v0][v_outro]xfade=transition=fade:duration={crossfade_dur}:offset={off(intro_dur + clip_dur - crossfade_dur):g}[v];"
                )
            else:
                video = (
                    "[0:v]format=yuv420p[v_intro];"
                    f"[v_intro][1:v]xfade=transition=fade:duration={crossfade_dur}:offset=0[v0];"
                    f"[v0][2:v]xfade=transition=fade:duration={crossfade_dur}:offset=0[v];"
                )
            cmd = [
                ffmpeg_path, "-y",
                "-i", intro_path,
                "-i", input_path,
                "-i", outro_path,
                "-filter_complex",
                video
                + f"[0:a][1:a]acrossfade=d={crossfade_dur}[ma];"
                + f"[ma][2:a]acrossfade=d={crossfade_dur}[a]",
                "-map", "[v]",
                "-map", "[a]",
                *video_enc_args,
                "-pix_fmt", "yuv420p",
                output_path
            ]
            log("Building intro + outro with crossfade")
        elif intro_path:
            # Intro only
            if normalized:
                video = (
                    vprep(0, "v_intro")
                    + vprep(1, "v_clip")
                    + f"[v_intro][v_clip]xfade=transition=fade:duration={crossfade_dur}:offset={off(intro_dur):g}[v];"
                )
            else:
                video = (
                    "[0:v]format=yuv420p[v0];"
                    f"[v0][1:v]xfade=transition=fade:duration={crossfade_dur}:offset=0[v];"
                )
            cmd = [
                ffmpeg_path, "-y",
                "-i", intro_path,
                "-i", input_path,
                "-filter_complex",
                video
                + f"[0:a][1:a]acrossfade=d={crossfade_dur}[a]",
                "-map", "[v]",
                "-map", "[a]",
                *video_enc_args,
                "-pix_fmt", "yuv420p",
                output_path
            ]
            log("Building intro only")
        elif outro_path:
            # Outro only
            if normalized:
                video = (
                    vprep(0, "v_clip")
                    + vprep(1, "v_outro")
                    + f"[v_clip][v_outro]xfade=transition=fade:duration={crossfade_dur}:offset={off(clip_dur):g}[v];"
                )
            else:
                video = (
                    "[0:v]format=yuv420p[v0];"
                    f"[v0][1:v]xfade=transition=fade:duration={crossfade_dur}:offset=0[v];"
                )
            cmd = [
                ffmpeg_path, "-y",
                "-i", input_path,
                "-i", outro_path,
                "-filter_complex",
                video
                + f"[0:a][1:a]acrossfade=d={crossfade_dur}[a]",
                "-map", "[v]",
                "-map", "[a]",
                *video_enc_args,
                "-pix_fmt", "yuv420p",
                output_path
            ]
            log("Building outro only")
        else:
            log("No intro or outro provided")
            return input_path

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            creationflags=_SUBPROCESS_FLAGS,
            # ffmpeg writes UTF-8; without this, Windows decodes stderr as
            # cp1252 and every non-ASCII character in the log turns into
            # mojibake (e.g. "…" shows up as "Ã¢â‚¬Â¦").
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            log(f"FFmpeg error: {result.stderr}")
            return input_path

        log("Intro/outro processing complete")
        return output_path
    except Exception as e:
        log(f"Intro/outro processing failed: {e}")
        return input_path
