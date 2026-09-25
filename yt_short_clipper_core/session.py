"""Session orchestration for the find-highlights phase."""

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .constants import resolve_output_language
from .helpers import debug_log, get_ffmpeg_path
from .highlight_finder import find_highlights, parse_requested_ranges
from .srt_parser import extract_transcript_for_highlight, parse_srt, parse_srt_segments
from .subtitle_downloader import download_caption_words, download_subtitle_only

LogFn = Callable[[str], None]

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Groq/OpenAI Whisper upload cap is ~25 MB per request. We keep a margin so
# a long local video never trips it: mono MP3 @64kbps ≈ 4.8 MB per 10 min.
GROQ_UPLOAD_LIMIT = 22 * 1024 * 1024
CHUNK_SECONDS = 600  # 10-min chunks for audio longer than the upload cap


def find_highlights_only(
    url: str,
    num_clips: int,
    subtitle_language: str,
    output_dir: str | Path,
    cookies_path: str,
    ai: dict[str, Any],
    user_direction: str | None = None,
    output_language: str | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Phase 1: download subtitle, run AI highlight detection, save session.

    Args:
        ai: dict with keys api_key, base_url, model, system_message (optional),
            temperature (optional).
        user_direction: optional free-text steer from the Create page (time
            range, topic to chase, things to avoid) injected into the prompt.
        output_language: language code for titles/hooks, or "auto"/None to
            follow the video's subtitle language.

    Returns session data dict.
    """
    log = log or debug_log

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(output_dir)
    session_dir = output_dir / "sessions" / timestamp
    session_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = session_dir / "_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    log(f"Session directory: {session_dir}")

    # Step 1: subtitle only
    log(f"Downloading {subtitle_language.upper()} subtitle (no video)...")
    srt_path, video_info = download_subtitle_only(
        url=url,
        subtitle_language=subtitle_language,
        temp_dir=temp_dir,
        cookies_path=cookies_path,
        log=log,
    )

    if not srt_path:
        raise RuntimeError(
            f"No subtitle available for language: {subtitle_language.upper()}. "
            "Try another subtitle language or a video that has subtitles."
        )

    if video_info.get("title"):
        log(f"Video: {video_info['title']}")
    if video_info.get("channel"):
        log(f"Channel: {video_info['channel']}")
    log(f"Subtitle download success: {srt_path}")

    # Step 1b: original-language caption word-timing (for word-by-word captions).
    # Independent of the highlight subtitle language; skipped silently if the
    # video has no original auto-caption track.
    caption_words_path: str | None = None
    try:
        caption_words_path = download_caption_words(
            url=url,
            temp_dir=session_dir,
            cookies_path=cookies_path,
            log=log,
        )
    except Exception as e:
        log(f"Caption word-timing unavailable: {str(e)[:200]}")

    # Step 2: AI highlights
    highlights, token_usage = _ai_highlights(
        srt_path=srt_path,
        num_clips=num_clips,
        video_info=video_info,
        ai=ai,
        user_direction=user_direction,
        output_language=output_language,
        subtitle_language=subtitle_language,
        log=log,
    )

    log(f"Found {len(highlights)} valid highlights")

    session_data = {
        "session_dir": str(session_dir),
        "url": url,
        "srt_path": srt_path,
        "subtitle_language": subtitle_language,
        "user_direction": (user_direction or "").strip() or None,
        "output_language": (output_language or "auto").strip().lower(),
        "output_language_name": resolve_output_language(output_language, subtitle_language),
        "caption_words_path": caption_words_path,
        "caption_available": bool(caption_words_path),
        "highlights": highlights,
        "video_info": video_info,
        "token_usage": token_usage,
        "created_at": datetime.now().isoformat(),
        "status": "highlights_found",
    }

    session_data_file = session_dir / "session_data.json"
    with open(session_data_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False)

    log(f"Session data saved to: {session_data_file}")

    return session_data


def _ai_highlights(
    srt_path: str,
    num_clips: int,
    video_info: dict[str, Any],
    ai: dict[str, Any],
    user_direction: str | None,
    output_language: str | None,
    subtitle_language: str | None,
    log: LogFn,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Shared AI highlight step for YouTube and local-file sessions."""
    transcript = parse_srt(srt_path)
    transcript_lines = transcript.count("\n") + 1 if transcript else 0
    log(f"Parsed transcript: {transcript_lines} lines, {len(transcript)} chars")

    # find_highlights() logs the model, endpoint and temperature itself.
    resolved_language = resolve_output_language(output_language, subtitle_language)
    log(f"Writing titles and hooks in {resolved_language}")
    log("Finding highlights with AI...")
    log(f"Requesting {num_clips} clips (AI may return extra for filtering)...")
    if (user_direction or "").strip():
        log(f"Applying AI direction: {' '.join(user_direction.split())[:200]}")
        exact = parse_requested_ranges(user_direction)
        if exact:
            spans = ", ".join(f"{a:.0f}s-{b:.0f}s" for a, b in exact)
            log(f"Exact time range(s) requested, exempt from the 58-120s rule: {spans}")
    highlights, token_usage = find_highlights(
        transcript=transcript,
        video_info=video_info,
        num_clips=num_clips,
        api_key=ai["api_key"],
        base_url=ai.get("base_url", "https://api.openai.com/v1"),
        model=ai["model"],
        system_prompt=ai.get("system_message") or None,
        # None lets find_highlights pick: colder when a direction must be obeyed.
        temperature=ai.get("temperature"),
        user_direction=user_direction,
        output_language=resolved_language,
        log=log,
    )

    if not highlights:
        raise RuntimeError(
            "No valid highlights found. The AI may have failed, or the transcript "
            "is too short. Try a different model or a longer video."
        )

    if token_usage:
        log(
            f"AI token usage: {token_usage.get('prompt_tokens', 0)} prompt + "
            f"{token_usage.get('completion_tokens', 0)} completion"
        )

    log("Extracting transcript text for each highlight...")
    for h in highlights:
        h["transcript_text"] = extract_transcript_for_highlight(
            srt_path, h["start_time"], h["end_time"]
        )

    return highlights, token_usage


def _probe_local_video(ffmpeg_path: str, video_path: Path, log: LogFn) -> tuple[float, bool]:
    """Duration (seconds) + whether the local file has an audio track.

    Uses ffmpeg only (the Windows bundle ships no ffprobe).
    """
    probe = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-i", str(video_path)],
        capture_output=True, text=True, creationflags=_SUBPROCESS_FLAGS,
    )
    stderr = probe.stderr or ""
    has_audio = "Audio:" in stderr
    duration = 0.0
    m = __import__("re").search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", stderr)
    if m:
        h, mi, s = m.groups()
        duration = int(h) * 3600 + int(mi) * 60 + float(s)
    log(f"Local video: {video_path.name} — duration {duration:.1f}s, audio={'yes' if has_audio else 'no'}")
    return duration, has_audio


def _extract_audio(ffmpeg_path: str, video_path: Path, wav_path: Path, log: LogFn) -> None:
    """Extract 16kHz mono WAV for Whisper transcription."""
    cmd = [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(wav_path),
    ]
    log("Extracting audio track for transcription...")
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=_SUBPROCESS_FLAGS)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to extract audio from local video: {(result.stderr or '')[-400:]}"
        )


def _run_ffmpeg(cmd: list[str]) -> None:
    result = subprocess.run(
        cmd, capture_output=True, text=True, creationflags=_SUBPROCESS_FLAGS
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {(result.stderr or '')[-400:]}")


def _format_srt_time(seconds: float) -> str:
    ms = int(round((seconds - int(seconds)) * 1000))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(path: Path, segments: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        start = float(seg["start"])
        end = float(seg["end"])
        lines.append(
            f"{i}\n{_format_srt_time(start)} --> {_format_srt_time(end)}\n{seg['text']}\n"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _transcribe_upload(client: Any, model: str, audio_path: Path) -> str:
    """POST one audio file to /audio/transcriptions; returns SRT text."""
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=model,
            file=(audio_path.name, f, "audio/mpeg"),
            response_format="srt",
        )
    text = result if isinstance(result, str) else getattr(result, "text", "")
    if not text or not text.strip():
        raise RuntimeError("Whisper transcription returned an empty result.")
    return text


def _transcribe_audio(ai: dict[str, Any], wav_path: Path, srt_path: Path, log: LogFn) -> None:
    """Transcribe local audio via an OpenAI-compatible Whisper endpoint.

    Uses the transcription-specific provider when configured
    (``transcription_base_url`` / ``transcription_model`` /
    ``transcription_api_key``); otherwise it falls back to the SAME
    provider used for highlight detection (base_url + api_key + model).
    The endpoint must support ``/audio/transcriptions``
    (e.g. whisper-1 / groq whisper / a local whisper gateway).

    The extracted WAV is re-encoded to a small mono MP3 before upload so a
    long video (43 min of WAV ≈ 82 MB) stays under the provider's ~25 MB
    cap — otherwise the server drops the connection mid-upload. Audio that
    is still too big is split into 10-minute chunks, transcribed
    separately, and merged back into a single SRT with shifted offsets.
    """
    from openai import OpenAI

    base_url = (
        (ai.get("transcription_base_url") or "").strip()
        or ai.get("base_url")
        or "https://api.openai.com/v1"
    )
    api_key = (
        (ai.get("transcription_api_key") or "").strip()
        or ai.get("api_key")
        or ""
    )
    model = (
        (ai.get("transcription_model") or "").strip()
        or ai.get("model")
        or "whisper-1"
    )

    if not api_key:
        raise RuntimeError(
            "Transcription API key is missing. Set the main AI API key or the "
            "transcription API key in Settings → AI Model."
        )

    client = OpenAI(api_key=api_key, base_url=base_url)

    try:
        # 1) Compress: mono 64k MP3 (43-min WAV = 82 MB → ~21 MB).
        mp3_path = wav_path.with_suffix(".mp3")
        log(f"Compressing audio for upload ({wav_path.name})...")
        _run_ffmpeg([
            get_ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(wav_path), "-ac", "1", "-ar", "16000",
            "-c:a", "libmp3lame", "-b:a", "64k", str(mp3_path),
        ])

        size = mp3_path.stat().st_size
        if size <= GROQ_UPLOAD_LIMIT:
            log(f"Transcribing audio with {model} via {base_url} ({size / 1024 / 1024:.1f} MB)...")
            srt_text = _transcribe_upload(client, model, mp3_path)
            srt_path.write_text(srt_text, encoding="utf-8")
            log(f"Transcription saved: {srt_path}")
            return

        # 2) Long audio → split into fixed 10-min chunks and merge with offset.
        log(f"Audio {size / 1024 / 1024:.1f} MB exceeds upload cap — splitting into "
            f"{CHUNK_SECONDS // 60}-minute chunks...")
        chunk_dir = wav_path.parent / "chunks"
        if chunk_dir.exists():
            shutil.rmtree(chunk_dir)  # stale chunks from a previous run
        chunk_dir.mkdir(parents=True, exist_ok=True)
        _run_ffmpeg([
            get_ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(mp3_path), "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
            "-reset_timestamps", "1", "-c:a", "libmp3lame", "-b:a", "64k",
            str(chunk_dir / "chunk_%03d.mp3"),
        ])
        chunks = sorted(chunk_dir.glob("chunk_*.mp3"))
        if not chunks:
            raise RuntimeError("Audio chunking produced no chunks.")

        segments: list[dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            offset = i * CHUNK_SECONDS
            log(f"Transcribing chunk {i + 1}/{len(chunks)} ({chunk.name})...")
            chunk_srt = chunk.with_suffix(".srt")
            chunk_srt.write_text(_transcribe_upload(client, model, chunk), encoding="utf-8")
            for seg in parse_srt_segments(str(chunk_srt)):
                segments.append({
                    "start": float(seg["start"]) + offset,
                    "end": float(seg["end"]) + offset,
                    "text": seg["text"],
                })
        _write_srt(srt_path, segments)
        log(f"Transcription saved (merged {len(chunks)} chunks): {srt_path}")
    except RuntimeError:
        raise
    except Exception as exc:
        # Give an actionable message instead of a raw API body. What the
        # failure means depends on the error class:
        #   - APIConnectionError  → upload dropped (file too big / network)
        #   - AuthenticationError → bad API key (401)
        #   - BadRequestError     → endpoint does not implement transcription
        from openai import APIConnectionError, AuthenticationError, BadRequestError

        detail = str(getattr(exc, "body", "") or exc).strip()
        if isinstance(exc, APIConnectionError):
            raise RuntimeError(
                "Transcription connection error — koneksi terputus saat upload "
                "(audio terlalu besar atau jaringan tidak stabil). App sudah "
                "mengompres & memotong audio otomatis; cek koneksi internet ke "
                f"{base_url} lalu coba lagi. Details: {str(exc)[:200]}"
            ) from exc
        if isinstance(exc, AuthenticationError):
            raise RuntimeError(
                "Transcription API key ditolak (401) — cek API key di "
                "Settings → AI Model → Transcription "
                f"(Groq: https://console.groq.com). Details: {detail[:300]}"
            ) from exc
        if isinstance(exc, BadRequestError) and getattr(exc, "status_code", None) == 413:
            raise RuntimeError(
                "Transcription file terlalu besar — provider menerima maks "
                "~25 MB per upload."
            ) from exc
        raise RuntimeError(
            "Transcription failed — this AI endpoint does not support "
            "audio transcription. In Settings → AI Model, fill in "
            "'Transcription Base URL' (e.g. https://api.openai.com/v1 with "
            "model whisper-1, or https://api.groq.com/openai/v1 with "
            f"whisper-large-v3-turbo). Details: {detail[:300]}"
        ) from exc


def find_local_highlights_only(
    local_path: str,
    num_clips: int,
    output_dir: str | Path,
    ai: dict[str, Any],
    user_direction: str | None = None,
    output_language: str | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Phase 1 (local file): copy source, transcribe, AI highlight detection.

    Shares the AI highlight pipeline with the YouTube flow; instead of
    downloading a subtitle it transcribes the local video's audio via the
    configured OpenAI-compatible provider (Whisper endpoint).

    Returns session data dict with ``source == "local"`` and
    ``local_video_path`` pointing at the session copy of the file.
    """
    log = log or debug_log

    source = Path(local_path)
    if not source.exists():
        raise RuntimeError(f"Local video file not found: {local_path}")
    if not source.is_file():
        raise RuntimeError(f"Local source is not a file: {local_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(output_dir)
    session_dir = output_dir / "sessions" / timestamp
    temp_dir = session_dir / "_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    log(f"Session directory: {session_dir}")

    # Copy the source into the session so the session stays self-contained
    # (re-processing from Library keeps working if the user moves the original).
    source_copy = temp_dir / f"source{source.suffix.lower() or '.mp4'}"
    log(f"Copying local video into session ({source.name})...")
    shutil.copy2(source, source_copy)
    log(f"Source ready: {source_copy}")

    ffmpeg_path = get_ffmpeg_path()
    _duration, has_audio = _probe_local_video(ffmpeg_path, source_copy, log)
    if not has_audio:
        log("⚠️ Local video has no audio track — highlights will be limited (empty transcript).")
        srt_path = None
        highlights: list[dict[str, Any]] = []
        token_usage: dict[str, Any] = {}
    else:
        wav_path = temp_dir / "audio.wav"
        _extract_audio(ffmpeg_path, source_copy, wav_path, log)
        srt_path = session_dir / "transcript.srt"
        _transcribe_audio(ai, wav_path, srt_path, log)
        highlights, token_usage = _ai_highlights(
            srt_path=str(srt_path),
            num_clips=num_clips,
            video_info=_local_video_info(source),
            ai=ai,
            user_direction=user_direction,
            output_language=output_language,
            subtitle_language=None,
            log=log,
        )

    video_info = _local_video_info(source)
    session_data = {
        "session_dir": str(session_dir),
        "source": "local",
        "local_video_path": str(source_copy),
        "url": "",
        "srt_path": str(srt_path) if srt_path else None,
        "subtitle_language": "transcribed",
        "user_direction": (user_direction or "").strip() or None,
        "output_language": (output_language or "auto").strip().lower(),
        "output_language_name": resolve_output_language(output_language, None),
        "caption_words_path": None,
        "caption_available": False,
        "highlights": highlights,
        "video_info": video_info,
        "token_usage": token_usage,
        "created_at": datetime.now().isoformat(),
        "status": "highlights_found",
    }

    session_data_file = session_dir / "session_data.json"
    with open(session_data_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False)

    log(f"Session data saved to: {session_data_file}")

    return session_data


def _local_video_info(source: Path) -> dict[str, str]:
    """Minimal video_info for local files (title = filename stem)."""
    return {
        "title": source.stem,
        "description": "Video lokal — diproses dari file media di perangkat ini.",
        "channel": "File Lokal",
    }
