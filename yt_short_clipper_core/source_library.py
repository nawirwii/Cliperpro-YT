"""Persistent source-video library: DOWNLOAD ONCE, CLIP MANY TIMES.

The in-memory ``_FULL_SOURCE_CACHE`` in :mod:`video_processor` already stops
a single batch of clips from re-downloading the same video, but it dies with
the sidecar process — and the downloaded file itself lives in the session's
``_temp`` dir, so the next session (or the next app start) downloads the
whole video again.

This module adds the durable layer the pipeline was missing:

* ``source_videos/`` — one stored copy of each downloaded source video,
  keyed by ``<video_id>_<max_height>p`` (same quality-cap semantics as the
  in-memory cache, so a 720p and a 1080p source never collide).
* ``database/video_history.json`` — an index of what was downloaded, where
  it lives, and how big/long it is, so a later run can recognise a source
  without re-downloading it.
* Validation before reuse: a library entry is only trusted when its file
  exists, is non-empty, and ffprobe/ffmpeg reports a real duration. A
  missing or corrupt entry is dropped (and its file removed) so the caller
  re-downloads exactly once, then stores the fresh copy.

Layout (relative to the app's ``output/`` dir, i.e. the parent of
``output/sessions/<id>``)::

    output/
    ├── source_videos/
    │   ├── dQw4w9WgXcQ_720p.mp4
    │   └── ...
    ├── database/
    │   └── video_history.json
    └── sessions/
        └── <id>/
            └── clips/ ...

Clips themselves stay in their session's ``clips/`` dir (the Library UI
reads them from there) — only the *source* moves to the shared library.
Sources are kept until the user deletes them manually from the folder.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .helpers import debug_log, get_ffmpeg_path

LogFn = Callable[[str], None]

# YouTube video IDs are 11 chars. The patterns cover the URL shapes users
# actually paste: watch?v=, youtu.be/, /shorts/, /live/, /embed/, /v/.
_VIDEO_ID_PATTERNS: list[str] = [
    r"[?&]v=([A-Za-z0-9_-]{11})",
    r"youtu\.be/([A-Za-z0-9_-]{11})",
    r"/shorts/([A-Za-z0-9_-]{11})",
    r"/live/([A-Za-z0-9_-]{11})",
    r"/embed/([A-Za-z0-9_-]{11})",
    r"/v/([A-Za-z0-9_-]{11})",
]

_DURATION_RE = re.compile(rb"Duration:\s*(\d+):(\d+):(\d+\.?\d*)")


def extract_video_id(url: str) -> str | None:
    """Return the 11-char YouTube video ID in ``url``, or None if unknown."""
    for pattern in _VIDEO_ID_PATTERNS:
        m = re.search(pattern, url or "")
        if m:
            return m.group(1)
    return None


def library_key(url: str, max_height: int) -> str:
    """Stable library key for one (video, quality cap) pair.

    Falls back to a hash of the URL when no video ID can be parsed, so
    non-YouTube or oddly-shaped URLs still get a deterministic key.
    """
    video_id = extract_video_id(url)
    base = video_id if video_id else hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return f"{base}_{max_height}p"


def library_paths(session_dir: str | Path) -> tuple[Path, Path]:
    """Return ``(source_videos_dir, video_history_path)`` for a session.

    ``session_dir`` is ``<app_data>/output/sessions/<id>``, so its
    grandparent is ``output/`` — the shared root for the library.
    """
    output_root = Path(session_dir).parent.parent
    return (
        output_root / "source_videos",
        output_root / "database" / "video_history.json",
    )


def database_path_for_library(library_root: str | Path) -> Path:
    """Return the ``video_history.json`` path for a ``source_videos`` dir."""
    return Path(library_root).parent / "database" / "video_history.json"


def _load_history(db_path: Path) -> dict[str, Any]:
    """Load the history index; an absent or corrupt file reads as empty."""
    try:
        if db_path.exists():
            with open(db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_history(db_path: Path, data: dict[str, Any]) -> None:
    """Atomically-ish save the history index (temp file + replace)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(db_path)


def probe_duration_seconds(path: Path, ffmpeg_path: str | None = None) -> float:
    """Return the media duration in seconds, or 0.0 when it cannot be read.

    Uses the same ``ffmpeg -i`` stderr parsing as ``cut_video_section``,
    so no new binary dependency is introduced.
    """
    ffmpeg = ffmpeg_path or get_ffmpeg_path()
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        probe = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-i", str(path)],
            capture_output=True,
            creationflags=flags,
        )
    except Exception:
        return 0.0
    m = _DURATION_RE.search(probe.stderr or b"")
    if not m:
        return 0.0
    h, mi, s = m.groups()
    try:
        return int(h) * 3600 + int(mi) * 60 + float(s)
    except ValueError:
        return 0.0


def validate_source(path: Path, ffmpeg_path: str | None = None) -> bool:
    """True when ``path`` is a usable source video: present, non-empty, probed."""
    try:
        if not path.is_file():
            return False
        if path.stat().st_size <= 0:
            return False
    except OSError:
        return False
    return probe_duration_seconds(path, ffmpeg_path) > 0


def lookup_source(
    library_root: str | Path,
    url: str,
    max_height: int,
    log: LogFn | None = None,
    ffmpeg_path: str | None = None,
) -> Path | None:
    """Return the stored source for ``(url, max_height)`` when valid, else None.

    A stale entry (file missing or corrupt) is dropped from the index and
    its file removed, so the caller re-downloads exactly once.
    """
    log = log or debug_log
    root = Path(library_root)
    db_path = database_path_for_library(root)
    key = library_key(url, max_height)
    entry = _load_history(db_path).get(key)
    if not isinstance(entry, dict):
        return None
    candidate = Path(str(entry.get("path") or ""))
    if validate_source(candidate, ffmpeg_path):
        return candidate
    log(
        f"⚠️ Video sumber di library tidak valid ({key}) — "
        "entri dihapus, akan download ulang."
    )
    try:
        if candidate.is_file():
            candidate.unlink()
    except OSError:
        pass
    try:
        data = _load_history(db_path)
        data.pop(key, None)
        _save_history(db_path, data)
    except Exception:
        pass
    return None


def record_source(
    library_root: str | Path,
    url: str,
    max_height: int,
    staged_path: str | Path,
    log: LogFn | None = None,
    ffmpeg_path: str | None = None,
) -> Path | None:
    """Move a freshly downloaded ``staged_path`` into the library.

    Returns the library path on success, or None when anything fails — in
    which case the staged file is left untouched so the caller can still cut
    from it (today's behaviour) instead of failing the clip.
    """
    log = log or debug_log
    root = Path(library_root)
    staged = Path(staged_path)
    try:
        if not validate_source(staged, ffmpeg_path):
            log("⚠️ File hasil download tidak valid — tidak disimpan ke library.")
            return None
        root.mkdir(parents=True, exist_ok=True)
        key = library_key(url, max_height)
        dest = root / f"{key}.mp4"
        if dest.exists():
            dest.unlink()
        shutil.move(str(staged), str(dest))
        duration = probe_duration_seconds(dest, ffmpeg_path)
        db_path = database_path_for_library(root)
        data = _load_history(db_path)
        data[key] = {
            "url": url,
            "video_id": extract_video_id(url),
            "max_height": max_height,
            "path": str(dest),
            "size_bytes": dest.stat().st_size,
            "duration_seconds": duration,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_history(db_path, data)
        log(f"💾 Video sumber disimpan ke library: {dest.name}")
        return dest
    except Exception as e:
        log(f"⚠️ Gagal menyimpan video sumber ke library: {e} — memakai file sementara.")
        return None
