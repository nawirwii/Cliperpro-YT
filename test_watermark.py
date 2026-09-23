"""End-to-end test: watermark overlay with credit text using resolved font."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from yt_short_clipper_core.watermark import apply_watermark, _find_text_font, _escape_filter_path

# 1. Font resolution must return an EXISTING font on this machine
font = _find_text_font()
print(f"[1] resolved font: {font}")
assert font and Path(font).exists(), f"font not found: {font}"
assert Path(font).suffix.lower() in (".ttf", ".ttc", ".otf"), f"unexpected font ext: {font}"

# 2. Path escaping: Windows drive letter must become C\:/...
escaped = _escape_filter_path(r"C:\Windows\Fonts\arial.ttf")
print(f"[2] escaped win path: {escaped}")
assert escaped == r"'C\:/Windows/Fonts/arial.ttf'", f"bad escape: {escaped}"

escaped2 = _escape_filter_path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
print(f"[2b] escaped linux path: {escaped2}")

# 3. Real watermark overlay on a generated video
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    src = td / "input.mp4"
    out = td / "output.mp4"

    # Generate a 2s 640x360 test video (color bars + tone) with ffmpeg
    import subprocess
    gen = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(src)],
        capture_output=True, text=True,
    )
    assert gen.returncode == 0, gen.stderr[-500:]

    # Apply CREDIT watermark (the exact code path that failed on Windows)
    apply_watermark(
        str(src),
        str(out),
        credit_watermark={
            "text": "© Jiwa's Studio",
            "color": "#FFFFFF",
            "font_size": 24,
            "opacity": 0.7,
            "position_x": 0.03,
            "position_y": 0.10,
        },
        log=lambda m: print(f"    [log] {m}"),
    )
    assert out.exists() and out.stat().st_size > 1000, "output missing"
    print(f"[3] watermark overlay OK: {out.name} ({out.stat().st_size} bytes)")

    # 4. LOGO + CREDIT combined
    logo = td / "logo.png"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red@0.8:s=100x50:d=1",
         "-frames:v", "1", str(logo)],
        capture_output=True, text=True,
    ).check_returncode()
    out2 = td / "output2.mp4"
    apply_watermark(
        str(src),
        str(out2),
        watermark={"image_path": str(logo), "position_x": 0.85, "position_y": 0.05,
                   "opacity": 0.8, "scale": 0.15},
        credit_watermark={"text": "Jiwa Studio © 2026", "color": "#FFFFFF",
                          "font_size": 20, "opacity": 0.7,
                          "position_x": 0.03, "position_y": 0.92},
        log=lambda m: print(f"    [log] {m}"),
    )
    assert out2.exists() and out2.stat().st_size > 1000
    print(f"[4] logo+credit overlay OK: {out2.name} ({out2.stat().st_size} bytes)")

print("\nALL WATERMARK TESTS PASSED ✅")