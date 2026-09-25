"""Local transcription with faster-whisper — no API, no per-request cost.

Why this exists
---------------
The cloud path (OpenAI / Groq / Hugging Face) has three failure modes that
have each cost us a release cycle: a ~25 MB upload cap, a provider edge that
disconnects on long audio, and provider hosts that get retired underneath a
hard-coded URL. Running Whisper in-process removes all three — there is no
upload, no cap and no remote endpoint involved. It trades them for CPU time,
which is the honest cost the user accepts by picking this option.

Design notes
------------
- **Import is lazy.** ``faster_whisper`` drags in ctranslate2 (~60 MB), av
  (~32 MB) and tokenizers (~12 MB). Importing it at module scope would make
  every session pay the cost even when transcribing via the cloud, so it is
  resolved on first *use*.
- **onnxruntime stays excluded from the frozen build.** faster-whisper imports
  it lazily, inside ``vad.py``'s VAD class, and only when ``vad_filter=True``.
  We never enable VAD, so the ~67 MB dependency is unnecessary. If a future
  faster-whisper release hoists that import to module level, the user gets a
  clear error instead of a crash — see ``_import_error_message``.
- **The model is cached on disk** under the Tauri app-data dir and downloaded
  from Hugging Face on first use. It is *not* bundled: ``turbo`` alone is
  ~1.6 GB.
- **The loaded model is cached per process.** Loading large-v3 costs 10–20 s,
  and one session transcribes many chunks; reloading per chunk would dominate
  the runtime.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

LogFn = Callable[[str], None]

#: Sentinel written into ``transcription_base_url`` so the rest of the app
#: keeps using the existing settings fields instead of a parallel config path.
LOCAL_SCHEME = "local://faster-whisper"

#: faster-whisper model ids, smallest first. The trade-off is stark on CPU:
#: ``tiny`` is roughly real-time, ``turbo`` is 3–5x slower than real-time on a
#: low-power laptop CPU. The UI explains this; we only enforce validity here.
KNOWN_MODELS = ("tiny", "tiny.en", "base", "base.en", "small", "small.en",
                "medium", "large-v2", "large-v3", "turbo", "distil-large-v3")

#: Rough on-disk size, so the UI can warn before a 1.6 GB surprise download.
MODEL_SIZES_MB = {
    "tiny": 75, "tiny.en": 75,
    "base": 145, "base.en": 145,
    "small": 465, "small.en": 465,
    "medium": 1500,
    "large-v2": 3000, "large-v3": 3100,
    "distil-large-v3": 1500,
    "turbo": 1600,
}

_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}


def is_local_base_url(url: str | None) -> bool:
    """True when the configured transcription base URL means 'in-process'."""
    return (url or "").strip().lower().startswith("local://")


def _model_cache_dir() -> Path:
    """Where downloaded Whisper weights live.

    Prefers the Tauri app-data dir so uninstalling the app can be understood
    by users, and falls back to the temp dir on a bare sidecar run.
    """
    try:
        from .helpers import _tauri_app_data_dir

        base = _tauri_app_data_dir()
        if base is not None:
            d = base / "whisper-models"
            d.mkdir(parents=True, exist_ok=True)
            return d
    except Exception:
        pass
    import tempfile

    d = Path(tempfile.gettempdir()) / "cliperpro-whisper-models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _point_hf_at_our_cache() -> None:
    """Make huggingface_hub download into our cache dir.

    Must run before the first ``from faster_whisper import ...``. Otherwise
    HF defaults to ``~/.cache/huggingface``, which a user clearing app data
    would not expect to be holding gigabytes.
    """
    cache = _model_cache_dir()
    os.environ.setdefault("HF_HOME", str(cache))
    # Older hub versions read these separately.
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(cache / "hub"))


def normalise_model(name: str | None) -> str:
    """Map a user-entered model onto a known faster-whisper id.

    Users arrive from the cloud world and type things like
    ``openai/whisper-large-v3-turbo``. Accepting those verbatim would send
    huggingface_hub off to fetch a *different, much larger* repo, so we strip
    the provider prefix and map the leftovers.
    """
    raw = (name or "").strip()
    if not raw:
        return "turbo"
    low = raw.lower()
    # Drop a provider prefix: "openai/whisper-large-v3-turbo" -> "large-v3-turbo"
    if "/" in low:
        low = low.rsplit("/", 1)[-1]
    # HF spells the distilled distil model "distil-whisper/distil-large-v3".
    if low.startswith("whisper-"):
        low = low[len("whisper-"):]
    if low in KNOWN_MODELS:
        return low
    # "large-v3-turbo" and "turbo" both mean the turbo distillation.
    for cand in ("turbo",):
        if low.endswith(cand) or low == cand:
            return cand
    # Accept the cloud spelling of large-v3 ("whisper-large-v3" -> "large-v3").
    if low.startswith("large-v3"):
        return "large-v3"
    if low.startswith("large-v2"):
        return "large-v2"
    if low.startswith("distil-large-v3"):
        return "distil-large-v3"
    # Unknown id: hand it to faster-whisper, which supports HF repo ids too.
    return raw


def _import_faster_whisper():
    """Import WhisperModel, translating any failure into actionable text."""
    _point_hf_at_our_cache()
    try:
        from faster_whisper import WhisperModel  # type: ignore

        return WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Mesin transkripsi lokal (faster-whisper) tidak tersedia di build "
            "ini. Install dengan 'pip install faster-whisper' atau pakai "
            "provider cloud (Hugging Face / Groq / OpenAI). "
            f"Detail: {exc}"
        ) from exc
    except Exception as exc:  # native lib load failures land here
        raise RuntimeError(
            "Gagal memuat pustaka native faster-whisper (ctranslate2). "
            "Biasanya berarti build sidecar tidak lengkap — pasang ulang "
            f"versi portable terbaru. Detail: {exc}"
        ) from exc


def _pick_device() -> tuple[str, str]:
    """Choose (device, compute_type) for this machine.

    CUDA when a usable GPU is present, otherwise CPU + int8. int8 is the right
    default for CPU: it is markedly faster than float32 at negligible accuracy
    cost for speech, and it roughly halves the memory footprint.
    """
    try:
        import ctranslate2  # type: ignore

        count = ctranslate2.get_cuda_device_count()
        if count and count > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _load_model(model: str, device: str | None, compute: str | None,
                log: LogFn):
    """Return a cached WhisperModel, downloading the weights on first use."""
    key = (model, device or "auto", compute or "auto")
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached

    WhisperModel = _import_faster_whisper()

    if device in (None, "", "auto") or compute in (None, "", "auto"):
        auto_device, auto_compute = _pick_device()
        device = device if device not in (None, "", "auto") else auto_device
        compute = compute if compute not in (None, "", "auto") else auto_compute

    size_mb = MODEL_SIZES_MB.get(model)
    size_txt = f" (~{size_mb} MB)" if size_mb else ""
    log(f"Memuat model Whisper lokal '{model}'{size_txt} di {device}/{compute}. "
        "Kesabaran, unduhan pertama cukup besar dan butuh koneksi internet.")

    try:
        loaded = WhisperModel(model, device=device, compute_type=compute)
    except Exception as exc:
        raise RuntimeError(
            f"Gagal memuat model Whisper '{model}'. Kalau ini model yang "
            f"belum pernah diunduh, pastikan ada koneksi internet "
            f"(diunduh dari Hugging Face). Detail: {exc}"
        ) from exc

    _MODEL_CACHE[key] = loaded
    return loaded


def transcribe(
    audio_path: Path,
    model: str = "turbo",
    language: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
    log: LogFn | None = None,
) -> list[dict[str, Any]]:
    """Transcribe one audio/video file locally.

    Returns a list of ``{"start", "end", "text"}`` dicts in seconds, ordered
    by start time. Timestamps are real, so callers build a far more accurate
    SRT than the cloud path can produce from a single blob of text.
    """
    emit: LogFn = log or (lambda _m: None)
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"Audio tidak ditemukan: {audio_path}")

    mdl = normalise_model(model)
    loaded = _load_model(mdl, device, compute_type, emit)

    # vad_filter stays off deliberately: it needs onnxruntime, which the
    # frozen build excludes, and for speech-dense Indonesian video the filter
    # is not needed.
    #
    # NOTE: faster_whisper returns a GENERATOR, not a list — decoding happens
    # lazily while we iterate. So we cannot ask for a total up front, and any
    # decode error surfaces mid-loop, not at the call. That generator contract
    # is easy to get wrong: calling len() on it raises TypeError, which is
    # exactly the bug the first real end-to-end run caught.
    segments, info = loaded.transcribe(
        str(audio_path),
        language=(language or None),
        vad_filter=False,
        beam_size=5,
    )

    out: list[dict[str, Any]] = []
    seen = 0
    try:
        for seg in segments:
            text = (getattr(seg, "text", "") or "").strip()
            seen += 1
            if not text:
                continue
            out.append({
                "start": float(getattr(seg, "start", 0.0) or 0.0),
                "end": float(getattr(seg, "end", 0.0) or 0.0),
                "text": text,
            })
            if seen % 25 == 0:
                emit(f"  transkripsi lokal: {len(out)} segmen")
    except Exception as exc:
        # No bare `except RuntimeError: raise` here, unlike session.py: this
        # module has no control-flow exceptions to preserve, and ctranslate2
        # signals out-of-memory as a plain RuntimeError. Letting that through
        # unwrapped would surface "ct2 out of memory" with no hint that the
        # fix is a smaller model or a bigger compute budget.
        raise RuntimeError(
            f"Mesin transkripsi lokal gagal di tengah pemrosesan setelah "
            f"{len(out)} segmen. Kalau errornya soal memori atau lambat, "
            f"coba model yang lebih kecil ('small' atau 'base'). "
            f"Detail: {exc}"
        ) from exc

    lang = getattr(info, "language", None) or language or "?"
    dur = getattr(info, "duration", None)
    emit(f"Transkripsi lokal selesai: {len(out)} segmen "
         f"(bahasa {lang}"
         + (f", audio {dur:.0f} dtk" if isinstance(dur, (int, float)) else "")
         + ").")
    return out


def probe() -> dict[str, Any]:
    """Report local-engine status without loading any weights.

    Used by the UI so the "Lokal" option can say *why* it is unavailable
    instead of failing at the moment the user submits a job.
    """
    try:
        _point_hf_at_our_cache()
        import faster_whisper  # type: ignore

        # `faster_whisper.version` is a MODULE, not a string — reading the
        # attribute off the package yields a module object. Report something
        # a human can read instead.
        try:
            from importlib.metadata import version as _pkg_version

            version = _pkg_version("faster-whisper")
        except Exception:
            ver_mod = getattr(faster_whisper, "version", None)
            version = getattr(ver_mod, "__version__", "unknown")
    except Exception as exc:
        return {"available": False, "reason": str(exc), "version": None}
    device, compute = _pick_device()
    return {
        "available": True,
        "version": version,
        "device": device,
        "compute_type": compute,
        "cache_dir": str(_model_cache_dir()),
        "models": list(KNOWN_MODELS),
    }
