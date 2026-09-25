"""Smoke v2.0.88 — local faster-whisper transcription.

Feature: transcribe an uploaded local video with Whisper running in-process,
no API key, no upload, no ~25 MB cap, no per-request cost.

This module was verified against a real install: faster-whisper 1.2.1 into a
throwaway venv, then a real transcription of real speech (an 11.3 s TTS
clip) through `local_whisper.transcribe()` with the `tiny` model. That run is
what caught the generator bug asserted in section 4 — a mocked model would
have returned a list and sailed straight past it.
"""

import pathlib
import re
import sys
from types import SimpleNamespace
from unittest import mock

REPO = pathlib.Path("/opt/data/workspace/Cliperpro-YT")
sys.path.insert(0, str(REPO))

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {label}  [{detail}]")


src = (REPO / "yt_short_clipper_core/local_whisper.py").read_text(encoding="utf-8")
sess = (REPO / "yt_short_clipper_core/session.py").read_text(encoding="utf-8")
reqs = (REPO / "requirements.txt").read_text(encoding="utf-8")
spec = (REPO / "build/spec/sidecar.spec").read_text(encoding="utf-8")
page = (REPO / "src/pages/AIModelsPage.tsx").read_text(encoding="utf-8")
cfg = (REPO / "src/config/aiProviders.ts").read_text(encoding="utf-8")

from yt_short_clipper_core import local_whisper as lw  # noqa: E402

print("=== 1. the sentinel distinguishes local from cloud ===")
check("recognises the sentinel", lw.is_local_base_url("local://faster-whisper"))
check("case/space tolerant", lw.is_local_base_url("  LOCAL://Faster-Whisper  "))
for cloud in ("https://router.huggingface.co/v1", "https://api.groq.com/openai/v1",
              "https://api.openai.com/v1", "", None):
    check(f"not local: {cloud!r}", not lw.is_local_base_url(cloud))

print("\n=== 2. model ids are normalised, never passed through verbatim ===")
# A user coming from the cloud world types the HF spelling. Handing that to
# huggingface_hub verbatim would fetch a different and much larger repo.
for typed, want in [
    ("turbo", "turbo"),
    ("openai/whisper-large-v3-turbo", "turbo"),
    ("whisper-large-v3-turbo", "turbo"),
    ("whisper-large-v3", "large-v3"),
    ("large-v3", "large-v3"),
    ("distil-whisper/distil-large-v3", "distil-large-v3"),
    ("base.en", "base.en"),
    ("", "turbo"),
    (None, "turbo"),
]:
    check(f"{typed!r} -> {want}", lw.normalise_model(typed) == want,
          lw.normalise_model(typed))

print("\n=== 3. the local branch runs BEFORE the API-key check ===")
branch = sess.index("if local_whisper.is_local_base_url(base_url)")
keycheck = sess.index('if not api_key:')
check("branch precedes the key check", branch < keycheck,
      f"branch@{branch} keycheck@{keycheck}")
check("local branch returns before the cloud path",
      "_transcribe_audio_local(ai, wav_path, srt_path, log, model)\n        return" in sess)
# Scope to ONLY the local function body: a naive slice up to the branch also
# swallows _transcribe_audio's cloud code, which legitimately reads the key.
_fn_start = sess.index("def _transcribe_audio_local")
_fn_end = sess.index("\ndef ", _fn_start + 1)
check("no key required for local",
      "transcription_api_key" not in sess[_fn_start:_fn_end])
check("local fn does not touch an API client",
      "OpenAI" not in sess[_fn_start:_fn_end] and "client" not in sess[_fn_start:_fn_end])

print("\n=== 4. faster_whisper's transcribe() returns a GENERATOR ===")
# Verified live: `len(segments)` raised TypeError on the first real run.
check("no len() on the segments result", "len(segments)" not in src)
check("iterates the result", "for seg in segments:" in src)
check("a mid-decode failure is reported, not swallowed",
      "gagal di tengah pemrosesan" in src)
# Strip comment lines first: the explanation above deliberately names
# `except RuntimeError: raise`, which a naive substring search would match.
_code = "\n".join(l for l in src.split("\n")
                  if not l.lstrip().startswith("#"))
check("ct2 OOM is wrapped, not re-raised bare",
      "except RuntimeError:" not in _code,
      "a bare re-raise would leak 'ct2 out of memory' with no guidance")
check("the wrap-up suggests a smaller model", "model yang lebih kecil" in src)
check("counts as it iterates", "seen += 1" in src)

seg = SimpleNamespace(start=1.5, end=3.25, text="  halo dunia  ")
info = SimpleNamespace(language="id", duration=11.3)
fake_model = mock.Mock()
fake_model.transcribe.return_value = (iter([seg]), info)

# transcribe() guards on the file existing, so use a real (tiny) file.
AUDIO = REPO / "requirements.txt"  # any real path; contents are never read
with mock.patch.object(lw, "_load_model", return_value=fake_model):
    out = lw.transcribe(AUDIO, model="tiny")
check("segment text is stripped", out and out[0]["text"] == "halo dunia", str(out))
check("timestamps are floats", out and out[0]["start"] == 1.5 and out[0]["end"] == 3.25)
check("vad_filter stays off (onnxruntime is excluded)",
      fake_model.transcribe.call_args.kwargs.get("vad_filter") is False)

empty = mock.Mock()
empty.transcribe.return_value = (iter([]), info)
with mock.patch.object(lw, "_load_model", return_value=empty):
    check("no segments -> empty list, no crash", lw.transcribe(AUDIO) == [])

def _boom_gen():
    """Raises only when ITERATED, like a real decode failure mid-stream.

    A bare `(_ for _ in ()).throw(...)` is evaluated eagerly, so it would
    escape while the test is still being built instead of exercising the
    handler in local_whisper.transcribe().
    """
    raise RuntimeError("ct2 out of memory")
    yield  # pragma: no cover - makes this a generator function


boom = mock.Mock()
boom.transcribe.return_value = (_boom_gen(), info)
with mock.patch.object(lw, "_load_model", return_value=boom):
    try:
        lw.transcribe(AUDIO)
        check("decode error surfaces as RuntimeError", False, "no raise")
    except RuntimeError as e:
        check("decode error surfaces as RuntimeError", "gagal di tengah" in str(e),
              str(e)[:60])

print("\n=== 5. the model is cached per process ===")
check("module-level cache exists", "_MODEL_CACHE" in src)
check("cache key includes model+device+compute",
      re.search(r"key = \(model, device[^)]*compute[^)]*\)", src) is not None)
check("cache is read before loading", "_MODEL_CACHE.get(key)" in src)
check("HF_HOME is redirected to our cache dir", "HF_HOME" in src)

print("\n=== 6. import failure is actionable, not a crash ===")
real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__


def blocked(name, *a, **k):
    if name == "faster_whisper" or name.startswith("faster_whisper."):
        raise ImportError("No module named 'faster_whisper'")
    return real_import(name, *a, **k)


with mock.patch("builtins.__import__", side_effect=blocked):
    try:
        lw._import_faster_whisper()
        check("missing engine raises", False, "no raise")
    except RuntimeError as e:
        check("missing engine raises RuntimeError", True)
        check("tells the user what to do", "faster-whisper" in str(e)
              and "provider cloud" in str(e), str(e)[:70])

p = lw.probe()
# This venv does not have faster-whisper installed, so `available` is False and
# version is legitimately None. The real string-version path was verified in
# the install venv, where probe() returned '1.2.1'. Assert the contract, not
# the presence of an optional dependency.
check("probe() reports availability as a bool", isinstance(p.get("available"), bool), str(p)[:60])
check("probe() version is a string or None",
      p.get("version") is None or isinstance(p["version"], str), repr(p.get("version")))
if p.get("available"):
    check("version is a string when available", isinstance(p["version"], str), repr(p["version"]))
else:
    check("unavailable probe explains why", bool(p.get("reason")), repr(p.get("reason")))

print("\n=== 7. onnxruntime stays out of the frozen build ===")
check("still excluded in sidecar.spec", "'onnxruntime'," in spec)
check("requirements explains why it is absent",
      "onnxruntime" in reqs and "VAD" in reqs)
check("faster-whisper is a declared dependency", "faster-whisper" in reqs)
for pkg in ("ctranslate2", "tokenizers", "av", "huggingface_hub"):
    check(f"native libs collected: {pkg}", f"'{pkg}'" in spec)

print("\n=== 8. the UI never asks for a key it does not need ===")
check("local preset exists", 'key: "local"' in cfg)
check("preset is flagged local", "local: true" in cfg)
check("sentinel is the base url", 'baseUrl: "local://faster-whisper"' in cfg)
check("apiKeyFormat says none needed", "tidak perlu API key" in cfg)
check("API key field hidden for local", "transcriptionPreset.local ?" in page)
check("url field is read-only for local", "readOnly={transcriptionPreset.local}" in page)
check("model picker is a dropdown for local",
      "transcriptionPreset.models ?" in page)
check("sizes are shown before downloading", "sizeMB" in cfg)
check("the CPU-speed warning is shown", "LAMBAT dari durasi video" in cfg)
check("presetFor resolves the local sentinel",
      "baseUrl.trim().toLowerCase().startsWith(p.baseUrl)" in cfg)

print(f"\n{'=' * 56}\nPASS {PASS}  FAIL {FAIL}")
if FAIL:
    raise SystemExit(1)
print("v2.0.88 local faster-whisper smoke: all green")
