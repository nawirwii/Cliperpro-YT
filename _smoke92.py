"""Smoke tests for the v2.0.92 cut-timestamp fix.

User log (real, v2.0.91 on Windows):

    [1/3] Source: local file - cutting 00:06:20,000 -> 00:08:00,000...
    [1/3] Cut encode: CPU libx264 (ultrafast)
    [1/3] Cut (primary): 00:06:20,000 -> 00:08:00,000
    ERROR: Failed to cut video section with ffmpeg: ffmpeg version
    8.1.2-full_build-www.gyan.dev ... --enable-sdl2 --e

Two independent defects, both verified here:

  1. THE CUT NEVER RAN. The timestamps are SRT/SubRip form
     ('00:06:20,000'). ffmpeg rejects a comma in a command-line time value
     with exit 234 "Invalid argument" -- a comma is only legal inside
     subtitle *files*. Measured on ffmpeg 7.1.4: every comma form fails,
     every dot form succeeds. So this path could only ever fail.
  2. THE REAL ERROR WAS INVISIBLE. The handler raised
     `result.stderr[:600]`, but ffmpeg prints its version banner FIRST, so
     the head of stderr is ~always pure banner and the actual reason was
     truncated away. Every other ffmpeg call site in this project slices
     [-N:] for exactly this reason -- this one was the odd one out.

The behavioural tests drive the REAL ffmpeg binary against a real generated
video, because the whole point of this fix is a claim about ffmpeg's parser,
and a mock would only encode my assumption about it.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

FAILS: list[str] = []
PASSES = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSES
    if cond:
        PASSES += 1
    else:
        FAILS.append(f"{name}{(' -> ' + detail) if detail else ''}")


FFMPEG = shutil.which("ffmpeg")


def make_video(path: str, seconds: int = 20) -> None:
    subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", path],
        capture_output=True, check=True,
    )


def duration_of(path: str) -> float:
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path],
                       capture_output=True, text=True)
    for line in p.stderr.splitlines():
        if "Duration:" in line:
            hms = line.split("Duration:")[1].split(",")[0].strip()
            h, mnt, s = hms.split(":")
            return int(h) * 3600 + int(mnt) * 60 + float(s)
    return -1.0


def main() -> int:
    import yt_short_clipper_core.video_processor as vp

    # ---------- pure helpers ----------
    t2s, fts = vp._timestamp_to_seconds, vp._ffmpeg_timestamp

    # The parser must accept the SRT comma form that actually arrives, AND
    # the bare-seconds form that _smoke77 passes. Unrecognised input must
    # return None so the caller passes it through untouched -- returning 0.0
    # here silently corrupted "1.0" into 00:00:00.000 (real regression).
    for text, want in [
        ("00:06:20,000", 380.0), ("00:08:00,000", 480.0),
        ("00:06:20.000", 380.0), ("00:06:20", 380.0),
        ("01:02:03,500", 3723.5), ("9:59,250", 599.25),
        ("1.0", 1.0), ("90", 90.0), ("3723.5", 3723.5),
    ]:
        got = t2s(text)
        check(f"parse {text!r} -> {want}", got is not None and abs(got - want) < 1e-6,
              f"got {got}")

    for text in ("", "   ", "not-a-time", "abc:xyz"):
        check(f"parse {text!r} -> None", t2s(text) is None, f"got {t2s(text)!r}")

    # The formatter must emit a DOT. This is the whole bug.
    for secs, want in [(380.0, "00:06:20.000"), (480.0, "00:08:00.000"),
                       (0.0, "00:00:00.000"), (3723.5, "01:02:03.500")]:
        got = fts(secs)
        check(f"format {secs} -> {want}", got == want, f"got {got}")
        check(f"format {secs} has no comma", "," not in got, got)

    for secs in (0.0, 380.0, 3723.5, 599.25):
        back = t2s(fts(secs))
        check(f"roundtrip {secs}", abs(back - secs) < 1e-3, f"got {back}")

    # ---------- source-level guarantees ----------
    src = (ROOT / "yt_short_clipper_core" / "video_processor.py").read_text(encoding="utf-8")

    check("tidak ada helper format koma yang tersisa",
          "_seconds_to_timestamp" not in src)
    check("run_cut memakai -hide_banner", '"-hide_banner", "-loglevel", "error"' in src)
    check("error ambil EKOR stderr", "stderr or \"\").strip()[-800:]" in src)
    check("error tidak ambil KEPALA stderr", "result.stderr[:600]" not in src)
    check("error menyertakan exit code", "exit {result.returncode}" in src)
    check("error menyertakan command", "command: {' '.join(cmd)}" in src)
    check("rentang dinormalisasi sebelum ffmpeg",
          "start_time = _ffmpeg_timestamp(start_s)" in src
          and "end_time = _ffmpeg_timestamp(end_s)" in src)

    # Every ffmpeg failure site in the project must read the TAIL, never the
    # head. Comment lines are exempt: prose legitimately quotes the bad form
    # in order to explain why it is wrong.
    for mod in sorted((ROOT / "yt_short_clipper_core").glob("*.py")):
        text = mod.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "stderr[" in stripped and "[:" in stripped:
                check(f"{mod.name}:{lineno} tidak slicing stderr dari depan",
                      False, stripped[:70])

    # ---------- behavioural: the real ffmpeg ----------
    if not FFMPEG:
        check("ffmpeg tersedia (lewati uji perilaku)", True, "SKIPPED")
    else:
        vp.get_ffmpeg_path = lambda: FFMPEG
        d = tempfile.mkdtemp()
        srcv = os.path.join(d, "src.mp4")
        make_video(srcv, 20)

        logs: list[str] = []

        # THE REPORTED BUG: comma timestamps must now cut successfully.
        try:
            out = vp.cut_video_section(
                srcv, os.path.join(d, "c1.mp4"),
                "00:00:05,000", "00:00:12,000", log=logs.append)
            dur = duration_of(out)
            check("timestamp koma sekarang berhasil", os.path.exists(out))
            check(f"durasi hasil ~7s (didapat {dur:.2f})", abs(dur - 7.0) < 1.5)
            sent = [l for l in logs if l.startswith("Cut (")]
            check("ffmpeg menerima bentuk titik", sent and "." in sent[0].split("->")[0],
                  sent[0] if sent else "<no log>")
        except Exception as e:  # noqa: BLE001
            check("timestamp koma sekarang berhasil", False, f"{type(e).__name__}: {e}")

        # No regression for the form that already worked.
        logs.clear()
        try:
            out = vp.cut_video_section(
                srcv, os.path.join(d, "c2.mp4"),
                "00:00:05.000", "00:00:12.000", log=logs.append)
            check("timestamp titik tetap berhasil", abs(duration_of(out) - 7.0) < 1.5)
        except Exception as e:  # noqa: BLE001
            check("timestamp titik tetap berhasil", False, f"{type(e).__name__}: {e}")

        # Bare-seconds call sites (_smoke77 uses these) must keep working.
        # This regressed once: the parser returned 0.0 for "1.0", producing
        # 00:00:00.000 -> 00:00:00.000 and "-to value smaller than -ss".
        logs.clear()
        try:
            out = vp.cut_video_section(
                srcv, os.path.join(d, "c2b.mp4"), "1.0", "2.5", log=logs.append)
            check("timestamp detik polos tetap berhasil",
                  abs(duration_of(out) - 1.5) < 0.6)
        except Exception as e:  # noqa: BLE001
            check("timestamp detik polos tetap berhasil", False, f"{type(e).__name__}: {e}")

        # An unparseable timestamp must reach ffmpeg verbatim, not become 0.
        logs.clear()
        try:
            vp.cut_video_section(srcv, os.path.join(d, "c2c.mp4"),
                                 "not-a-time", "00:00:05.000", log=logs.append)
            check("format tak dikenal diteruskan, bukan jadi 0", False, "tidak error")
        except RuntimeError as e:
            sent = [l for l in logs if l.startswith("Cut (")]
            check("format tak dikenal diteruskan, bukan jadi 0",
                  bool(sent) and "not-a-time" in sent[0],
                  sent[0] if sent else str(e)[:80])
        except Exception as e:  # noqa: BLE001
            check("format tak dikenal diteruskan, bukan jadi 0", False, type(e).__name__)

        # Start past the end: a clear message, not an opaque ffmpeg failure.
        logs.clear()
        try:
            vp.cut_video_section(srcv, os.path.join(d, "c3.mp4"),
                                 "00:00:50,000", "00:00:55,000", log=logs.append)
            check("start melewati EOF ditolak dengan jelas", False, "tidak error")
        except RuntimeError as e:
            msg = str(e)
            check("start melewati EOF ditolak dengan jelas", "only" in msg and "long" in msg, msg[:80])
            check("pesan tidak bocor banner ffmpeg", "ffmpeg version" not in msg)
        except Exception as e:  # noqa: BLE001
            check("start melewati EOF ditolak dengan jelas", False, type(e).__name__)

        # End past the end: clamp and still produce a clip.
        logs.clear()
        try:
            out = vp.cut_video_section(
                srcv, os.path.join(d, "c4.mp4"),
                "00:00:15,000", "00:09:00,000", log=logs.append)
            check("end melewati EOF di-clamp", os.path.exists(out))
            check("clamp memberi tahu user",
                  any("clamping" in l for l in logs), str(logs))
            check("hasil clamp ~5s", abs(duration_of(out) - 5.0) < 1.5)
        except Exception as e:  # noqa: BLE001
            check("end melewati EOF di-clamp", False, f"{type(e).__name__}: {e}")

        shutil.rmtree(d, ignore_errors=True)

    print(f"_smoke92: {PASSES} checks, {len(FAILS)} failed")
    for f in FAILS:
        print(f"  FAIL: {f}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
