"""Hook generation: render hook text as an overlay on the opening seconds of the clip."""

import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .helpers import get_ffmpeg_path
from .gpu import build_video_enc_args

LogFn = Callable[[str], None]

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Default hook style
DEFAULT_HOOK_STYLE = {
    "font_name": "Arial",
    "font_path": "",
    "font_size": 0.054,
    "font_color": "#FFD700",
    "bg_color": "#FFFFFF",
    "corner_radius": 0,
    "position_x": 0.5,
    "position_y": 0.333,
    "duration_seconds": 5.0,
}

DEFAULT_HOOK_DURATION = 5.0

HOOK_STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "Bold Yellow Brush": {"font_color": "#111111", "bg_color": "#FFD93D", "corner_radius": 0, "font_size": 0.058},
    "Viral Creator": {"font_color": "#FFFFFF", "bg_color": "#FF6B6B", "corner_radius": 18, "font_size": 0.056},
    "Clean White Box": {"font_color": "#111111", "bg_color": "#FFFFFF", "corner_radius": 8},
    "Pop Comic": {"font_color": "#111111", "bg_color": "#B8F2E6", "corner_radius": 24, "font_size": 0.06},
    "Minimal Kinetic": {"font_color": "#FFFFFF", "bg_color": "#111111", "corner_radius": 0, "font_size": 0.05},
    "Red Alert": {"font_color": "#FFFFFF", "bg_color": "#EF4444", "corner_radius": 4, "font_size": 0.06},
    "Neon Digital": {"font_color": "#111111", "bg_color": "#A3FF12", "corner_radius": 2},
    "Cinematic Title": {"font_color": "#FFFFFF", "bg_color": "#111111", "corner_radius": 0, "font_size": 0.048, "position_y": 0.72},
    "Highlight Marker": {"font_color": "#111111", "bg_color": "#FDE047", "corner_radius": 0},
    "Photo Story Hook": {"font_color": "#FFFFFF", "bg_color": "#2563EB", "corner_radius": 12, "font_size": 0.052},
    "AI Future Poster": {"font_color": "#111111", "bg_color": "#FFD21F", "corner_radius": 0, "font_size": 0.06, "brush": True, "shadow": True},
    "Quote Split Screen": {"font_color": "#FFFFFF", "bg_color": "#000000", "corner_radius": 0, "font_size": 0.052, "outline": True, "outline_width": 8, "position_y": 0.48},
}


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color string to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def _find_system_font_bold() -> str:
    """Find a bold system font as fallback."""
    if sys.platform == "win32":
        candidates = [
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]

    for c in candidates:
        if Path(c).exists():
            return c
    return ""


def generate_hook(
    input_video_path: str,
    hook_text: str,
    output_path: str,
    duration: float = DEFAULT_HOOK_DURATION,
    hook_style: dict[str, Any] | None = None,
    log: LogFn | None = None,
    gpu_config: dict[str, Any] | None = None,
) -> str:
    """Overlay hook text on top of the opening seconds of the input video.

    The video keeps playing (and keeps its audio) underneath the text. The
    hook text is shown from t=0 until ``duration`` seconds, then disappears.

    Steps:
    1. Probe the input video resolution
    2. Render the hook text overlay with PIL (transparent PNG)
    3. Burn the overlay onto the video for the first ``duration`` seconds

    Returns the output path.
    """
    log = log or (lambda m: None)
    style_name = (hook_style or {}).get("style_name", "")
    style = {**DEFAULT_HOOK_STYLE, **(hook_style or {})}
    if style_name in HOOK_STYLE_PRESETS:
        style.update(HOOK_STYLE_PRESETS[style_name])
    ffmpeg_path = get_ffmpeg_path()
    temp_dir = Path(output_path).parent

    # Select video encoder based on GPU config
    video_enc_args = build_video_enc_args(gpu_config)
    if gpu_config and gpu_config.get("available"):
        log(f"Using GPU encoder: {gpu_config.get('name')} (preset={gpu_config.get('preset')})")
    else:
        log(f"Using CPU encoder: libx264")

    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = DEFAULT_HOOK_DURATION
    if duration <= 0:
        duration = DEFAULT_HOOK_DURATION

    # Step 1: Probe input video resolution
    probe_cmd = [ffmpeg_path, "-i", input_video_path]
    result = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=_SUBPROCESS_FLAGS)

    res_match = re.search(r"(\d{3,4})x(\d{3,4})", result.stderr)
    if res_match:
        width, height = int(res_match.group(1)), int(res_match.group(2))
    else:
        width, height = 1080, 1920

    # Step 2: Render text overlay with PIL
    log(f"Rendering hook text overlay ({duration:.1f}s)...")
    from PIL import Image, ImageDraw, ImageFont

    font_size_frac = float(style.get("font_size", 0.054))
    font_color_hex = style.get("font_color", "#FFD700")
    bg_color_hex = style.get("bg_color", "#FFFFFF")
    corner_radius = int(style.get("corner_radius", 0))
    pos_x = float(style.get("position_x", 0.5))
    pos_y = float(style.get("position_y", 0.333))
    user_font_path = style.get("font_path") or ""

    # Resolve font
    font_px = max(20, int(font_size_frac * width))
    pil_font = None
    for candidate in [user_font_path, _find_system_font_bold()]:
        if not candidate or not Path(candidate).exists():
            continue
        try:
            pil_font = ImageFont.truetype(candidate, font_px)
            break
        except Exception:
            pass
    if pil_font is None:
        pil_font = ImageFont.load_default()

    font_color_rgb = _hex_to_rgb(font_color_hex)
    bg_color_rgb = _hex_to_rgb(bg_color_hex)

    # Format hook text into lines (3 words per line)
    hook_upper = hook_text.upper()
    words = hook_upper.split()
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        if len(current_line) >= 3:
            lines.append(" ".join(current_line))
            current_line = []
    if current_line:
        lines.append(" ".join(current_line))

    # Calculate line metrics
    padding = max(10, int(font_px * 0.22))
    line_spacing = max(6, int(font_px * 0.25))

    line_metrics = []
    for line in lines:
        try:
            bbox = pil_font.getbbox(line)
        except AttributeError:
            w_t, h_t = pil_font.getsize(line)
            bbox = (0, 0, w_t, h_t)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        line_metrics.append({
            "text": line,
            "bbox": bbox,
            "box_w": text_w + padding * 2,
            "box_h": text_h + padding * 2,
        })

    total_h = sum(m["box_h"] for m in line_metrics)
    if len(line_metrics) > 1:
        total_h += line_spacing * (len(line_metrics) - 1)

    center_x = int(pos_x * width)
    center_y = int(pos_y * height)
    block_top = center_y - total_h // 2

    # Compose overlay image. Quote Split Screen is a real editorial layout:
    # the source video remains visible above an opaque lower quote panel, with
    # a high-contrast divider separating the two regions.
    overlay_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay_img)
    is_quote_split = style_name == "Quote Split Screen"
    if is_quote_split:
        panel_top = int(height * 0.62)
        divider_h = max(6, int(height * 0.006))
        draw.rectangle([0, panel_top, width, height], fill=(12, 12, 14, 248))
        draw.rectangle([0, panel_top, width, panel_top + divider_h], fill=(255, 211, 31, 255))
        panel_padding = max(32, int(width * 0.08))
        quote_font_px = max(26, int(width * 0.055))
        try:
            quote_font = ImageFont.truetype(user_font_path or _find_system_font_bold(), quote_font_px)
        except Exception:
            quote_font = pil_font
        quote_lines = []
        current = []
        max_quote_width = width - panel_padding * 2
        for word in hook_upper.split():
            candidate = " ".join(current + [word])
            bbox = draw.textbbox((0, 0), candidate, font=quote_font, stroke_width=2)
            if current and bbox[2] > max_quote_width:
                quote_lines.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            quote_lines.append(" ".join(current))
        quote_spacing = max(10, int(quote_font_px * 0.22))
        quote_heights = [draw.textbbox((0, 0), line, font=quote_font, stroke_width=2)[3] for line in quote_lines]
        quote_total = sum(quote_heights) + quote_spacing * max(0, len(quote_lines) - 1)
        quote_y = panel_top + divider_h + max(24, (height - panel_top - divider_h - quote_total) // 2)
        for line, line_h in zip(quote_lines, quote_heights):
            bbox = draw.textbbox((0, 0), line, font=quote_font, stroke_width=2)
            text_x = (width - (bbox[2] - bbox[0])) // 2
            draw.text((text_x + 3, quote_y + 3), line, font=quote_font, fill=(0, 0, 0, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
            draw.text((text_x, quote_y), line, font=quote_font, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
            quote_y += line_h + quote_spacing
    cur_y = block_top
    for m in line_metrics:
        if is_quote_split:
            break
        box_w = m["box_w"]
        box_h = m["box_h"]
        box_x1 = center_x - box_w // 2
        box_y1 = cur_y
        box_x2 = box_x1 + box_w
        box_y2 = box_y1 + box_h

        if style.get("brush"):
            brush = [box_x1 - 10, box_y1 + 4, box_x2 + 10, box_y2 - 2]
            draw.polygon([(brush[0], brush[1] + 6), (brush[0] + 18, brush[1]), (brush[2] - 14, brush[1] + 3), (brush[2], brush[1] + 12), (brush[2] - 12, brush[3]), (brush[0] + 8, brush[3] - 4)], fill=(0, 0, 0, 230))
            draw.polygon([(v + (4 if i % 2 == 0 else 3)) for i, v in enumerate(brush)], fill=(*bg_color_rgb, 255))
        elif style.get("outline"):
            # Transparent editorial quote: preserve the speaker behind text.
            pass
        elif corner_radius > 0 and hasattr(draw, "rounded_rectangle"):
            r = min(corner_radius, box_w // 2, box_h // 2)
            draw.rounded_rectangle(
                [box_x1, box_y1, box_x2, box_y2],
                radius=r,
                fill=(*bg_color_rgb, 255),
            )
        else:
            draw.rectangle(
                [box_x1, box_y1, box_x2, box_y2],
                fill=(*bg_color_rgb, 255),
            )

        text_x = box_x1 + padding - m["bbox"][0]
        text_y = box_y1 + padding - m["bbox"][1]
        if style.get("shadow"):
            draw.text((text_x + 8, text_y + 8), m["text"], font=pil_font, fill=(0, 0, 0, 240), stroke_width=4, stroke_fill=(0, 0, 0, 240))
        draw.text(
            (text_x, text_y),
            m["text"],
            font=pil_font,
            fill=(*font_color_rgb, 255),
            stroke_width=int(style.get("outline_width", 0)),
            stroke_fill=(0, 0, 0, 255) if style.get("outline") else None,
        )

        cur_y = box_y2 + line_spacing

    overlay_png = str(temp_dir / f"hook_overlay_{int(time.time() * 1000)}.png")
    overlay_img.save(overlay_png, "PNG")

    # Step 3: Overlay text onto the video for the first `duration` seconds.
    # The underlying video keeps playing and keeps its audio track.
    log("Burning hook text onto video...")
    overlay_cmd = [
        ffmpeg_path, "-y",
        "-i", input_video_path,
        "-i", overlay_png,
        "-filter_complex",
        f"[0:v][1:v]overlay=0:0:enable='lte(t,{duration})'[v]",
        "-map", "[v]",
        "-map", "0:a?",
        *video_enc_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        output_path,
    ]
    result = subprocess.run(overlay_cmd, capture_output=True, text=True, creationflags=_SUBPROCESS_FLAGS)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to overlay hook text: {result.stderr[-500:]}")

    # Cleanup temp files
    try:
        Path(overlay_png).unlink(missing_ok=True)
    except Exception:
        pass

    log("Hook generation complete")
    return output_path
