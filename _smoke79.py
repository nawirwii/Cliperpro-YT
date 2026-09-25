"""v2.0.79 smoke — transcription timeout handling.

Reproduces the real-world failure: an under-cap 19.6 MB file held ~97 s then
"Server disconnected". Here the mock server DROPS any upload whose audio is
longer than LIMIT_SECONDS, emulating a provider edge that gives up on
long-running transcriptions. The client must split down until pieces are short
enough, and still merge a correct SRT.
"""
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from yt_short_clipper_core import session as S  # noqa: E402

FF = S.get_ffmpeg_path()
ROOT = Path("/tmp/smoke79")
LIMIT_SECONDS = 180.0  # mock edge refuses anything longer than this
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {extra}")


def make_wav(path, seconds):
    subprocess.run(
        [FF, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={seconds}", "-ac", "1", "-ar", "16000",
         str(path)],
        check=True, capture_output=True,
    )


class Handler(BaseHTTPRequestHandler):
    uploads = []          # (filename, nbytes)
    drops = 0

    def log_message(self, *a):
        pass

    def _file_duration(self, body: bytes) -> float:
        """Extract the uploaded file part and measure it with ffmpeg."""
        ctype = self.headers.get("Content-Type", "")
        bm = re.search(r"boundary=(.+)$", ctype)
        if not bm:
            return 0.0
        boundary = bm.group(1).strip().strip('"').encode()
        for part in body.split(b"--" + boundary):
            if b'filename="' not in part:
                continue
            head, _, data = part.partition(b"\r\n\r\n")
            if b'name="file"' not in head:
                continue
            data = data.rstrip(b"\r\n")
            tmp = ROOT / f"_ul_{len(Handler.uploads)}.mp3"
            tmp.write_bytes(data)
            dur = S._probe_duration(FF, tmp)
            tmp.unlink(missing_ok=True)
            return dur
        return 0.0

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        m = re.search(rb'filename="([^"]+)"', body)
        name = m.group(1).decode() if m else "?"
        Handler.uploads.append((name, len(body)))
        if not self.path.endswith("/audio/transcriptions"):
            self.send_error(404)
            return
        # Real duration of the uploaded audio: mock edge refuses long jobs,
        # exactly like a provider whose proxy times out during transcription.
        dur = self._file_duration(body)
        if dur > LIMIT_SECONDS:
            Handler.drops += 1
            self.close_connection = True   # drop without response
            return
        srt = (
            "1\n00:00:00,000 --> 00:00:02,000\nhello\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nworld\n"
        )
        data = srt.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_case(title, wav_seconds, chunk_seconds, expect_ok=True,
             model="whisper-large-v3-turbo", pin=True):
    print(f"\n[{title}]")
    case = ROOT / title
    if case.exists():
        shutil.rmtree(case)
    case.mkdir(parents=True)
    wav = case / "audio.wav"
    make_wav(wav, wav_seconds)

    Handler.uploads, Handler.drops = [], 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/v1"

    old_chunk, old_max = S.CHUNK_SECONDS, S.MAX_UPLOAD_SECONDS
    old_for = S._chunk_seconds_for
    S.CHUNK_SECONDS, S.MAX_UPLOAD_SECONDS = chunk_seconds, chunk_seconds
    # Pin the model-aware helper so run_case's chunk_seconds is authoritative.
    # pin=False keeps the real model-aware logic (for S5/S6).
    if pin:
        S._chunk_seconds_for = lambda _m: chunk_seconds
    srt_out = case / "out.srt"
    logs = []
    try:
        S._transcribe_audio(
            {"api_key": "k", "base_url": base, "model": model},
            wav, srt_out, logs.append,
        )
        ok = True
        err = ""
    except Exception as e:  # noqa: BLE001
        ok = False
        err = str(e)[:220]
    finally:
        S.CHUNK_SECONDS, S.MAX_UPLOAD_SECONDS = old_chunk, old_max
        S._chunk_seconds_for = old_for
        srv.shutdown()

    for line in logs:
        print("    | " + line)
    if err:
        print("    ! " + err)
    check(f"{title}: success", ok == expect_ok)
    print(f"    uploads={len(Handler.uploads)} drops={Handler.drops} "
          f"names={[u[0] for u in Handler.uploads][:8]}")
    if ok:
        segs = S.parse_srt_segments(str(srt_out))
        check(f"{title}: srt has segments", len(segs) >= 2, f"n={len(segs)}")
        last = max(float(x["end"]) for x in segs)
        check(f"{title}: coverage reaches {wav_seconds:.0f}s",
              last >= wav_seconds - chunk_seconds - 4, f"last_end={last:.1f}")
    return Handler.uploads, Handler.drops


def main():
    global LIMIT_SECONDS
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True)
    print("v2.0.79 smoke — timeout-driven splitting")

    # S1: short audio, single upload, no splitting.
    LIMIT_SECONDS = 360.0
    up, _ = run_case("S1_short", 60, 300)
    check("S1_short: exactly 1 upload", len(up) == 1, f"n={len(up)}")
    check("S1_short: no part files",
          not any("_p0" in n for n, _ in up))

    # S2: 900 s audio, provider tolerates 300 s → plain chunking, no halving.
    up, drops = run_case("S2_900s", 900, 300)
    check("S2_900s: 3-4 uploads", 3 <= len(up) <= 4, f"n={len(up)}")
    check("S2_900s: no drops", drops == 0, f"drops={drops}")

    # S3: provider that refuses >180 s → 300 s chunks must halve to 150 s.
    LIMIT_SECONDS = 180.0
    up, drops = run_case("S3_halve", 300, 300)
    check("S3_halve: first attempt dropped", drops >= 1, f"drops={drops}")
    check("S3_halve: retried as halves", any("_p0" in n for n, _ in up),
          f"names={[n for n, _ in up]}")

    # S4: unsplittable (splitting disabled) → friendly error, no crash.
    old_min = S.MIN_SPLIT_SECONDS
    S.MIN_SPLIT_SECONDS = 10_000  # disable splitting
    LIMIT_SECONDS = 1.0  # everything drops
    run_case("S4_nosplit", 120, 300, expect_ok=False)
    LIMIT_SECONDS = 180.0
    S.MIN_SPLIT_SECONDS = old_min

    # S5: slow model (large-v3) must split 200 s into 150 s pieces even though
    # 200 s < MAX_UPLOAD_SECONDS — this is the exact case that timed out live.
    # Here we do NOT pin _chunk_seconds_for, so the real model-aware logic runs.
    LIMIT_SECONDS = 180.0
    up, drops = run_case("S5_slowmodel", 200, 150, model="whisper-large-v3", pin=False)
    check("S5_slowmodel: 2 uploads of ~150s", len(up) == 2, f"n={len(up)} names={[n for n,_ in up]}")
    check("S5_slowmodel: no drops (150s passes)", drops == 0, f"drops={drops}")

    # S6: same audio on turbo → 200 s fits in one 300 s request, no split.
    # Provider limit raised to 250 s so a single 200 s request is accepted;
    # if the app were (wrongly) splitting, we would see 2+ uploads.
    LIMIT_SECONDS = 250.0
    up, drops = run_case("S6_turbo", 200, 300, model="whisper-large-v3-turbo", pin=False)
    check("S6_turbo: exactly 1 upload", len(up) == 1, f"n={len(up)} names={[n for n,_ in up]}")
    check("S6_turbo: no drops", drops == 0, f"drops={drops}")

    # Pure helpers: model-aware piece length + human label.
    check("_chunk_seconds_for turbo = 300",
          S._chunk_seconds_for("whisper-large-v3-turbo") == 300,
          str(S._chunk_seconds_for("whisper-large-v3-turbo")))
    check("_chunk_seconds_for large-v3 = 150 (slow model)",
          S._chunk_seconds_for("whisper-large-v3") == 150,
          str(S._chunk_seconds_for("whisper-large-v3")))
    check("_chunk_seconds_for whisper-1 = 150 (slow model)",
          S._chunk_seconds_for("whisper-1") == 150,
          str(S._chunk_seconds_for("whisper-1")))
    check("_chunk_label(300)", S._chunk_label(300) == "5 menit", S._chunk_label(300))
    check("_chunk_label(150)",
          S._chunk_label(150) == "2 menit 30 detik", S._chunk_label(150))
    check("_chunk_label(45)", S._chunk_label(45) == "45 detik", S._chunk_label(45))

    print(f"\n{'='*52}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
        return 1
    print("ALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
