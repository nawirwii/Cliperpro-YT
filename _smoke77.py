"""Smoke test v2.0.77 — transcription override + actionable error.

Simulates two OpenAI-compatible endpoints:
  1. A "chat-only" gateway (like Bos's Hermes gateway) that returns 400
     for /audio/transcriptions  -> must raise a clear RuntimeError hint.
  2. A real Whisper endpoint that returns SRT -> must write transcript.srt
     and use the transcription_* override (not the main chat model).
Regression: cut_video_section + parse_srt_segments still pass.
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
# stub heavy native deps
sys.modules.setdefault("cv2", type(sys)("cv2"))
sys.modules.setdefault("numpy", type(sys)("numpy"))
sys.modules.setdefault("mediapipe", type(sys)("mediapipe"))

SRT_SAMPLE = (
    "1\n00:00:00,000 --> 00:00:01,500\nHallo bos!\n\n"
    "2\n00:00:01,500 --> 00:00:03,000\nIni transkripsi lokal.\n\n"
    "3\n00:00:03,000 --> 00:00:04,000\nSelesai.\n\n"
)

class MockHandler(BaseHTTPRequestHandler):
    mode = "chat_only"  # patched per-test
    hits = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/v1/models":
            body = json.dumps({"data": [{"id": "Hermes_combo"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        MockHandler.hits.append(self.path)
        if self.mode == "chat_only":
            body = json.dumps({
                "error": {
                    "message": "Invalid model format",
                    "type": "invalid_request_error",
                    "code": "bad_request",
                }
            }).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # whisper mode: return SRT
        body = SRT_SAMPLE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve():
    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    from yt_short_clipper_core import session
    from yt_short_clipper_core.srt_parser import parse_srt_segments
    from yt_short_clipper_core.video_processor import cut_video_section

    server = serve()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}/v1"
    logs = []

    def log(msg):
        logs.append(msg)

    tmp = Path("/tmp/smoke77")
    tmp.mkdir(parents=True, exist_ok=True)
    wav = tmp / "audio.wav"
    wav.write_bytes(b"RIFF-fake-wav")

    passed = 0
    failed = 0

    def check(name, cond, extra=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  PASS {name}")
        else:
            failed += 1
            print(f"  FAIL {name} {extra}")

    # --- Scenario 1: chat-only gateway, NO transcription override -> clear hint
    MockHandler.mode = "chat_only"
    MockHandler.hits.clear()
    srt1 = tmp / "t1.srt"
    try:
        session._transcribe_audio(
            {"base_url": base, "api_key": "k", "model": "Hermes_combo"},
            wav, srt1, log,
        )
        check("S1 raises on chat-only endpoint", False, "expected RuntimeError")
    except RuntimeError as e:
        msg = str(e)
        check("S1 raises RuntimeError", True)
        check("S1 mentions Settings → AI Model", "Settings → AI Model" in msg)
        check("S1 suggests whisper-1/groq", "whisper-1" in msg and "groq" in msg)
        print(f"    DEBUG S1 hits={MockHandler.hits} detail={msg[-120:]!r}")

    # --- Scenario 2: whisper endpoint via transcription_* override
    MockHandler.mode = "whisper"
    MockHandler.hits.clear()
    srt2 = tmp / "t2.srt"
    session._transcribe_audio(
        {
            "base_url": base.replace("v1", "v2"),  # main chat endpoint DIFFERENT
            "api_key": "k",
            "model": "Hermes_combo",
            "transcription_base_url": base,  # override -> mock whisper server
            "transcription_model": "whisper-1",
            "transcription_api_key": "wk",
        },
        wav, srt2, log,
    )
    check("S2 writes transcript.srt", srt2.exists())
    content = srt2.read_text(encoding="utf-8")
    check("S2 SRT content matches", content.strip() == SRT_SAMPLE.strip())
    check("S2 used override base_url", "Transcribing audio with whisper-1 via" in str(logs))
    print(f"    DEBUG S2 hits={MockHandler.hits}")

    # --- Scenario 3: fallback to main model when override is empty
    MockHandler.mode = "whisper"
    MockHandler.hits.clear()
    logs.clear()
    srt3 = tmp / "t3.srt"
    session._transcribe_audio(
        {"base_url": base, "api_key": "k", "model": "Hermes_combo"},
        wav, srt3, log,
    )
    check("S3 fallback uses main model", "Transcribing audio with Hermes_combo via" in str(logs))
    check("S3 writes SRT", srt3.exists())

    # --- Scenario 4: missing api key -> clear error
    try:
        session._transcribe_audio({"base_url": base}, wav, tmp / "t4.srt", log)
        check("S4 missing key raises", False)
    except RuntimeError as e:
        check("S4 missing key raises", "API key is missing" in str(e))

    # --- Regression: parse_srt_segments + cut_video_section still work
    srt_file = tmp / "sample.srt"
    srt_file.write_text(SRT_SAMPLE, encoding="utf-8")
    segs = parse_srt_segments(srt_file)
    check("REG parse_srt_segments 3 items", len(segs) == 3)
    check("REG seg2 start 1.5", abs(segs[1]["start"] - 1.5) < 1e-6)

    import subprocess
    ff = "ffmpeg"
    vid = tmp / "src.mp4"
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(vid)], check=True)
    out = tmp / "cut.mp4"
    cut_video_section(str(vid), str(out), "1.0", "2.5")
    check("REG cut output exists", out.exists())
    probe = subprocess.run([ff, "-hide_banner", "-i", str(out)], capture_output=True, text=True)
    dur = 0.0
    import re
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", probe.stderr or "")
    if m:
        h, mi, s = m.groups()
        dur = int(h) * 3600 + int(mi) * 60 + float(s)
    check("REG cut duration ~1.5s", abs(dur - 1.5) < 0.2, f"dur={dur}")

    server.shutdown()
    print(f"\nRESULT: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()