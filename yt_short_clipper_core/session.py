"""Session orchestration for the find-highlights phase."""

import json
import re
import shutil
import subprocess
import sys
import time
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

# Whisper upload constraints (both matter — see v2.0.79):
#   1. size  — Groq/OpenAI reject files above ~25 MB per request.
#   2. time  — the provider edge (Cloudflare-style) drops the connection when a
#      single request runs too long. A 43-min file compressed to 19.6 MB
#      (well under the size cap) stayed connected for 97 s and was then reset.
#      So we split by DURATION, not only by size: 5-min pieces keep every
#      request far below any timeout, for any model (turbo or large-v3).
GROQ_UPLOAD_LIMIT = 22 * 1024 * 1024
MAX_UPLOAD_SECONDS = 300  # transcribe longer audio as <=5-min requests
CHUNK_SECONDS = 300
MIN_SPLIT_SECONDS = 45  # below this a failing piece is not worth splitting
MAX_SPLIT_DEPTH = 3  # 300 -> 150 -> 75 -> 45 s worst case

# whisper-large-v3 is ~4x slower than large-v3-turbo (Groq's own docs call
# turbo "optimized for speed"). The same request that times out on large-v3
# can pass on turbo, so slow models get shorter pieces up front instead of
# waiting for the first disconnect.
SLOW_MODELS = ("whisper-large-v3", "whisper-1")
SLOW_MODEL_CHUNK_SECONDS = 150  # 2.5-min pieces for large-v3 / whisper-1


def _chunk_seconds_for(model: str) -> int:
    """Shorter pieces for slow models; same value for turbo-class models."""
    name = (model or "").lower()
    if name in SLOW_MODELS or "large-v3" in name and "turbo" not in name:
        return SLOW_MODEL_CHUNK_SECONDS
    return CHUNK_SECONDS


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


def _probe_duration(ffmpeg_path: str, path: Path) -> float:
    """Duration in seconds via ffmpeg (works for audio and video, no ffprobe)."""
    probe = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, creationflags=_SUBPROCESS_FLAGS,
    )
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", probe.stderr or "")
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def _split_audio(
    ffmpeg_path: str, src: Path, dst: Path, start: float, duration: float
) -> None:
    """Cut [start, start+duration) out of an audio file into ``dst`` (MP3)."""
    _run_ffmpeg([
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
        "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k", str(dst),
    ])


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


def _is_too_large(exc: BaseException) -> bool:
    """True for HTTP 413 from any provider.

    The OpenAI SDK does NOT map 413 onto ``BadRequestError`` — it raises the
    generic ``APIStatusError`` — so this must be checked via ``status_code``,
    never via ``isinstance(exc, BadRequestError)``.
    """
    from openai import APIStatusError

    return isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) == 413


def _transcribe_piece(
    client: Any,
    model: str,
    ffmpeg_path: str,
    audio_path: Path,
    log: LogFn,
    label: str,
    depth: int = 0,
) -> list[dict[str, Any]]:
    """Upload one audio piece; on a dropped connection OR an explicit 413,
    halve it and transcribe each half.

    Two distinct server-side refusals, one remedy — a smaller piece:
      * ``APIConnectionError`` — the provider edge (Cloudflare and friends)
        closes over-long requests without a response, surfacing as
        ``APIConnectionError: Server disconnected without sending a response``.
        Transient, so one retry first.
      * **HTTP 413** — the provider's body cap is smaller than this piece.
        Retrying the identical payload can never succeed, so we split
        immediately.

    Returns segments relative to ``audio_path``.
    """
    from openai import APIConnectionError, APIStatusError

    last_error: Exception | None = None
    reason = "koneksi terputus"
    for attempt in range(1, 3):
        try:
            srt_text = _transcribe_upload(client, model, audio_path)
            srt_file = audio_path.with_suffix(".srt")
            srt_file.write_text(srt_text, encoding="utf-8")
            return parse_srt_segments(str(srt_file))
        except APIStatusError as exc:
            if not _is_too_large(exc):
                raise
            # Explicit "too large": the piece itself is the problem.
            last_error, reason = exc, "file ditolak terlalu besar (413)"
            size_mb = audio_path.stat().st_size / 1024 / 1024
            log(f"  ⚠️ {label}: {reason} — {size_mb:.1f} MB, "
                "membelah langsung tanpa mengulang...")
            break
        except APIConnectionError as exc:
            last_error = exc
            if attempt < 2:
                wait = 4 * attempt
                log(f"  ⚠️ {label}: koneksi terputus, ulang dalam {wait} detik "
                    f"(percobaan {attempt}/2)...")
                time.sleep(wait)

    duration = _probe_duration(ffmpeg_path, audio_path)
    if depth < MAX_SPLIT_DEPTH and duration >= MIN_SPLIT_SECONDS * 2:
        half = duration / 2
        log(f"  ⚠️ {label}: {reason} — membagi menjadi 2 bagian "
            f"({half:.0f} detik) lalu mencoba lagi...")
        segments: list[dict[str, Any]] = []
        for i, start in enumerate((0.0, half)):
            part = audio_path.with_name(f"{audio_path.stem}_p{i}.mp3")
            _split_audio(ffmpeg_path, audio_path, part, start, half)
            segments.extend(
                _transcribe_piece(
                    client, model, ffmpeg_path, part, log,
                    f"{label} bagian {i + 1}/2", depth + 1,
                )
            )
        return segments

    raise last_error if last_error else RuntimeError(
        f"Transcription of {label} failed with no response from the provider."
    )


def _chunk_label(seconds: int | None = None) -> str:
    """Human label for a piece length ("5 menit" / "2 menit 30 detik")."""
    total = CHUNK_SECONDS if seconds is None else int(seconds)
    if total % 60 == 0:
        return f"{total // 60} menit"
    if total > 60:
        return f"{total // 60} menit {total % 60} detik"
    return f"{total} detik"


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
    size cap. Audio longer than ``MAX_UPLOAD_SECONDS`` is additionally split
    into short pieces, because a large-but-under-cap file still fails when the
    provider's edge times out while transcribing (observed: 19.6 MB held for
    97 s, then "Server disconnected"). Each piece is retried and, if it keeps
    dropping, halved recursively. Pieces are merged back into one SRT with
    shifted offsets.
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

    # Our own retry/halve logic gives better feedback than the SDK's silent
    # retries, so keep those off and let _transcribe_piece decide what to do.
    client = OpenAI(
        api_key=api_key, base_url=base_url, max_retries=0, timeout=300.0
    )

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
        duration = _probe_duration(get_ffmpeg_path(), mp3_path)
        chunk_seconds = _chunk_seconds_for(model)
        max_seconds = min(MAX_UPLOAD_SECONDS, chunk_seconds)
        too_big = size > GROQ_UPLOAD_LIMIT
        too_long = duration > max_seconds
        if not too_big and not too_long:
            log(f"Transcribing audio with {model} via {base_url} "
                f"({size / 1024 / 1024:.1f} MB, {duration:.0f}s)...")
            srt_path.write_text(_transcribe_upload(client, model, mp3_path), encoding="utf-8")
            log(f"Transcription saved: {srt_path}")
            return

        # 2) Long and/or large → fixed-length pieces, merged with offset.
        reason = []
        if too_long:
            reason.append(f"durasi {duration / 60:.1f} menit")
        if too_big:
            reason.append(f"ukuran {size / 1024 / 1024:.1f} MB")
        if chunk_seconds < CHUNK_SECONDS:
            log(f"ℹ️ Model '{model}' ~4x lebih lambat dari 'whisper-large-v3-turbo' "
                f"→ pakai potongan lebih pendek.")
        log(f"Audio {' dan '.join(reason)} melebihi batas upload — memecah menjadi "
            f"bagian {_chunk_label(chunk_seconds)} agar tidak timeout...")
        chunk_dir = wav_path.parent / "chunks"
        if chunk_dir.exists():
            shutil.rmtree(chunk_dir)  # stale chunks from a previous run
        chunk_dir.mkdir(parents=True, exist_ok=True)
        _run_ffmpeg([
            get_ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(mp3_path), "-f", "segment", "-segment_time", str(chunk_seconds),
            "-reset_timestamps", "1", "-c:a", "libmp3lame", "-b:a", "64k",
            str(chunk_dir / "chunk_%03d.mp3"),
        ])
        chunks = sorted(chunk_dir.glob("chunk_*.mp3"))
        if not chunks:
            raise RuntimeError("Audio chunking produced no chunks.")

        segments: list[dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            offset = i * chunk_seconds
            # Always name the endpoint + piece size: when a provider refuses a
            # chunk (413/400) this line is the only place that proves WHICH
            # endpoint rejected it and how big the payload actually was.
            log(f"Transcribing chunk {i + 1}/{len(chunks)} ({chunk.name}, "
                f"{chunk.stat().st_size / 1024 / 1024:.1f} MB) via {base_url}...")
            for seg in _transcribe_piece(
                client, model, get_ffmpeg_path(), chunk, log,
                f"chunk {i + 1}/{len(chunks)}",
            ):
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
        # failure means depends on the error class / status:
        #   - APIConnectionError  → edge dropped an over-long request
        #   - 413                 → provider's body cap is smaller than our piece
        #   - AuthenticationError → bad API key (401)
        #   - 400/404/405/422     → endpoint does not implement transcription
        # Do NOT use isinstance(exc, BadRequestError) for 413: the OpenAI SDK
        # raises a plain APIStatusError for that status, so the check silently
        # never fires and every 413 used to be mislabelled as "endpoint does
        # not support audio transcription" (v2.0.80 bug, real user report).
        from openai import APIConnectionError, APIStatusError, AuthenticationError

        detail = str(getattr(exc, "body", "") or exc).strip()
        status = getattr(exc, "status_code", None)
        if isinstance(exc, APIConnectionError):
            raise RuntimeError(
                "Transcription timeout — provider memutus koneksi saat memproses "
                "audio. App sudah mengompres (MP3 64k mono) dan memecah audio jadi "
                f"bagian {_chunk_label(_chunk_seconds_for(model))}, lalu mencoba "
                "membagi lagi otomatis. Usually 1 dari 2 penyebab: (1) model terlalu "
                "berat untuk durasi video — coba model 'whisper-large-v3-turbo' "
                "(lebih cepat, hampir sama akuratnya), atau (2) koneksi ke provider "
                "tidak stabil"
                f"— cek {base_url} lalu coba lagi. Details: {str(exc)[:200]}"
            ) from exc
        if isinstance(exc, AuthenticationError):
            raise RuntimeError(
                "Transcription API key ditolak (401) — cek API key di "
                "Settings → AI Model → Transcription "
                f"(Groq: https://console.groq.com). Details: {detail[:300]}"
            ) from exc
        if _is_too_large(exc):
            raise RuntimeError(
                f"Provider menolak file sebagai terlalu besar (HTTP 413) — batas "
                f"body {base_url} lebih kecil dari potongan audio kita. App sudah "
                "mencoba memecah dan membelah otomatis; jika tetap gagal, pakai "
                "endpoint yang limit-nya lebih besar (mis. Groq "
                "https://api.groq.com/openai/v1, maks ~25 MB) atau pilih model "
                "'whisper-large-v3-turbo'."
                f" Details: {detail[:300]}"
            ) from exc
        if isinstance(exc, APIStatusError) and status in (400, 404, 405, 422, 501):
            raise RuntimeError(
                f"Endpoint {base_url} tidak mendukung /audio/transcriptions "
                f"(HTTP {status}). Di Settings → AI Model → Transcription, isi "
                "Base URL + model Whisper, contoh: "
                "https://api.groq.com/openai/v1 dengan whisper-large-v3-turbo, "
                f"atau https://api.openai.com/v1 dengan whisper-1. "
                f"Details: {detail[:300]}"
            ) from exc
        raise RuntimeError(
            f"Transcription gagal (HTTP {status}) — cek {base_url} dan model "
            f"{model}. Details: {detail[:300]}"
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
