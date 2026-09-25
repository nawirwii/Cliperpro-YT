"""AI heatmap — a "Momen Panas" map built from the transcript, not from viewers.

What this is NOT
----------------
It is **not** YouTube's "Most Replayed" heatmap. That is viewer retention data
and it only exists for a published YouTube video. A local MP4 has never been
watched by anyone, so there is no retention signal to read — and as of
v2.0.89 even YouTube's own endpoint returns the metadata with zero markers
(verified against four videos including the most-viewed ones; the ANDROID and
iOS clients need API keys). So this module scores the *transcript* instead,
and the UI calls it "Momen Panas" so nobody mistakes an AI estimate for real
audience data.

Why two passes
--------------
Selecting highlights in one shot from a 100k-char transcript asks the model to
do triage, scoring and boundary-finding at once, which is why clip quality
swung so much between videos. Scoring first gives a coarse map, and selection
then only has to cut precise boundaries out of regions already known to be
interesting. Cheap: pass 1 sees a truncated slice per window, not the whole
transcript.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .srt_parser import parse_srt_segments

LogFn = Callable[[str], None]

# 60s buckets line up with how short-form viewers actually retain: a hook has
# to land inside roughly the first ten seconds, and a clip worth keeping is
# 58-120s long, so a one-minute window is the smallest bucket that can contain
# a whole candidate clip.
WINDOW_SECONDS = 60

# Per-window text sent to the model. Enough to judge tone and content, small
# enough that a 45-minute video costs a fraction of the selection pass.
MAX_CHARS_PER_WINDOW = 600

# Below this the map is noise, so a failed pass should not block the run.
MIN_WINDOWS_FOR_HEATMAP = 3

# Ceiling on how much adjacent hot stretch is collapsed into one range. Three
# windows is a 3-minute region: long enough to cut a 58-120s clip from, short
# enough that a uniformly hot video still yields several distinct moments.
MAX_MERGE_SECONDS = 180.0

HEATMAP_SYSTEM_PROMPT = """\
Kamu adalah editor video yang menilai SustainReplay dari sebuah video \
podcast atau vlog. Untuk setiap WINDOW yang diberikan, nilai 0-100 seberapa \
menarik window itu kalau dijadiin klip pendek vertikal.

Rentang skor:
- 80-100 = ada hook kuat di awal, cerita yang memanas, atau pengungkapan \
yang bikin penasaran
- 50-79  = enak didengar tapi tanpa momentum khusus
- 20-49  = percakapan biasa, transisi, atau basa-basi
- 0-19   = bising, hening, salam, atau tidak ada konten

Dasar penilaian:
1. Hook di 10 detik pertama window (kalimat pembuka, pertanyaan, klaim berani)
2. Momentum dan eskalasi cerita
3. Informatif — apakah ada fakta, angka, atau pengalaman nyata
4. Emosi — lucu, terkejut, marah, terharu (bukan sekadar netral)
5. Kelengkapan — apakah window bisa berdiri sendiri sebagai klip

Balas HANYA dengan JSON array, tanpa teks lain:
[{{"i": <nomor window>, "s": <0-100>, "r": "<alasan singkat, maks 12 kata>"}}]

Nilai SEMUA window yang diberi. Balas JSON saja.\
"""

# Model output is unpredictable; the salvage path below recovers most of it.
_SCORE_RE = re.compile(
    r'"i"\s*:\s*(?P<i>-?\d+)\s*,\s*"s"\s*:\s*(?P<s>-?\d+(?:\.\d+)?)',
)
_LOOSE_RE = re.compile(
    r'\{[^{}]*?"?i"?\s*[:=]\s*(?P<i>\d+)[^{}]*?"?s"?\s*[:=]\s*'
    r'(?P<s>\d+(?:\.\d+)?)[^{}]*?\}'
)


def build_windows(
    srt_path: str,
    window_seconds: int = WINDOW_SECONDS,
) -> list[dict[str, Any]]:
    """Bucket the transcript into fixed time windows for scoring.

    Windows are built from the segment timeline, not the raw duration, so a
    silent tail never becomes a run of empty buckets.
    """
    segments = parse_srt_segments(srt_path)
    if not segments:
        return []

    last_end = max(float(s["end"]) for s in segments)
    count = max(1, int(last_end // window_seconds) + (1 if last_end % window_seconds else 0))

    buckets: list[dict[str, Any]] = [
        {
            "index": i,
            "start": float(i * window_seconds),
            "end": float(min((i + 1) * window_seconds, last_end)),
            "text": [],
        }
        for i in range(count)
    ]

    for seg in segments:
        start = float(seg["start"])
        idx = min(int(start // window_seconds), count - 1)
        buckets[idx]["text"].append(str(seg["text"]).strip())

    out: list[dict[str, Any]] = []
    for b in buckets:
        text = " ".join(t for t in b["text"] if t).strip()
        if not text:
            continue  # a silent gap is not a candidate moment
        if len(text) > MAX_CHARS_PER_WINDOW:
            text = text[:MAX_CHARS_PER_WINDOW].rsplit(" ", 1)[0] + " …"
        out.append({"index": b["index"], "start": b["start"], "end": b["end"], "text": text})
    return out


def render_prompt(windows: list[dict[str, Any]]) -> str:
    lines = []
    for w in windows:
        mm, ss = divmod(int(w["start"]), 60)
        lines.append(
            f'[WINDOW {w["index"]} | {mm:d}:{ss:02d} - '
            f'{int(w["end"]) // 60:d}:{int(w["end"]) % 60:02d}]\n{w["text"]}'
        )
    return "\n\n".join(lines)


def parse_heatmap(raw: str, windows: list[dict[str, Any]], log: LogFn) -> dict[int, float]:
    """Map window index -> 0..1 score. Tolerates partial or malformed replies.

    A model that scores 30 of 45 windows still gave us something useful, so
    missing entries are simply absent rather than defaulted to zero — zero
    means "scored and found boring", and conflating that with "never looked at"
    would sink a good region.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"```json?\n?", "", raw)
        raw = re.sub(r"```\n?", "", raw)

    pairs: list[tuple[int, float]] = []
    try:
        parsed = json.loads(raw)
        items = parsed if isinstance(parsed, list) else [parsed]
        for it in items:
            if isinstance(it, dict) and "i" in it and "s" in it:
                pairs.append((int(it["i"]), float(it["s"])))
    except (json.JSONDecodeError, TypeError, ValueError):
        pairs = [(int(m.group("i")), float(m.group("s")))
                 for m in _SCORE_RE.finditer(raw)]
        if not pairs:
            pairs = [(int(m.group("i")), float(m.group("s")))
                     for m in _LOOSE_RE.finditer(raw)]
        if pairs:
            log(f"Heatmap JSON was malformed — salvaged {len(pairs)} scores by pattern")
        else:
            log("Heatmap response contained no recognisable scores")

    valid = {w["index"] for w in windows}
    out: dict[int, float] = {}
    for idx, score in pairs:
        if idx not in valid:
            continue
        # Clamp: models do emit -5 and 130, and an out-of-range score would
        # silently distort the colour scale in the UI.
        out[idx] = max(0.0, min(100.0, score)) / 100.0
    if windows and not out:
        log("Heatmap scoring returned nothing usable — continuing without a map")
    return out


def score_windows(
    srt_path: str,
    api_key: str,
    base_url: str,
    model: str,
    log: LogFn,
    window_seconds: int = WINDOW_SECONDS,
) -> tuple[list[dict[str, Any]], dict[int, float]]:
    """Return (windows, {index: 0..1}). Never raises on an AI failure.

    The heatmap is an *enhancement*: if the provider is down, rate-limiting, or
    the video is too short to map, the run continues into the existing
    single-pass selection. Failing the whole job over a pretty picture would be
    the wrong trade.
    """
    windows = build_windows(srt_path, window_seconds)
    if len(windows) < MIN_WINDOWS_FOR_HEATMAP:
        log(
            f"Only {len(windows)} window(s) of speech — too few to map "
            f"(need {MIN_WINDOWS_FOR_HEATMAP}). Skipping heatmap."
        )
        return windows, {}

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=300.0, max_retries=1)
    log(
        f"Scoring {len(windows)} windows with {model} at {base_url} "
        f"(AI heatmap / Momen Panas)..."
    )
    try:
        chunks: list[str] = []
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": HEATMAP_SYSTEM_PROMPT},
                {"role": "user", "content": render_prompt(windows)},
            ],
            temperature=0.2,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
    except Exception as exc:
        log(f"⚠️ AI heatmap gagal ({exc}). Lanjut tanpa peta panas.")
        return windows, {}

    scores = parse_heatmap("".join(chunks), windows, log)
    if scores:
        hottest = max(scores.items(), key=lambda kv: kv[1])
        w = next(x for x in windows if x["index"] == hottest[0])
        log(
            f"AI heatmap selesai: {len(scores)}/{len(windows)} window dinilai. "
            f"Puncak di {int(w['start']) // 60:d}:{int(w['start']) % 60:02d} "
            f"(skor {hottest[1]:.0%})."
        )
    return windows, scores


def hottest_ranges(
    scores: dict[int, float],
    limit: int = 5,
) -> list[tuple[float, float]]:
    """Top-N non-overlapping hot ranges, best first.

    Adjacent hot windows are merged rather than returned separately: two
    neighbouring 60s buckets in a hot stretch are one moment, and handing the
    selector both would produce two near-duplicate clips.
    """
    if not scores:
        return []
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    WINDOW_SECONDS_GLOBAL = WINDOW_SECONDS
    chosen: list[tuple[float, float]] = []
    used: set[int] = set()

    for idx, _score in ordered:
        if len(chosen) >= limit:
            break
        if idx in used:
            continue
        start = float(idx * WINDOW_SECONDS_GLOBAL)
        end = start + WINDOW_SECONDS_GLOBAL
        if any(not (end <= s or start >= e) for s, e in chosen):
            continue
        used.add(idx)

        # Absorb immediate neighbours into this clip so the range covers the
        # whole hot stretch rather than clipping it mid-sentence.
        #
        # This runs BEFORE the append. Tuples are immutable, so appending first
        # and then widening start/end only rebinds the locals — `chosen` kept
        # the unmerged bounds and the merge silently did nothing.
        #
        # n is always exactly one bucket away, so it always touches or overlaps
        # and never needs an overlap test — an earlier version used one and
        # refused to merge, because touching windows compare `ne > start` as
        # False at the seam (window 0 ends at 60, window 1 starts at 60).
        #
        # MAX_MERGE_SECONDS bounds the result. Without it a uniformly hot video
        # collapses into one range covering the entire runtime, and the
        # selector then has nowhere to cut N distinct clips from.
        for n in (idx - 1, idx + 1):
            if n in scores and n not in used:
                ns = float(n * WINDOW_SECONDS_GLOBAL)
                ne = ns + WINDOW_SECONDS_GLOBAL
                if ne - start <= MAX_MERGE_SECONDS:
                    start, end = min(start, ns), max(end, ne)
                    used.add(n)

        chosen.append((start, end))
    return sorted(chosen)


def format_hot_hint(ranges: list[tuple[float, float]]) -> str:
    """One line of guidance appended to the selection prompt."""
    if not ranges:
        return ""
    parts = []
    for s, e in ranges:
        parts.append(f"{int(s) // 60:d}:{int(s) % 60:02d}-"
                     f"{int(e) // 60:d}:{int(e) % 60:02d}")
    return (
        "ANALISIS HEATMAP (Momen Panas) — rentang paling menarik menurut AI: "
        + ", ".join(parts)
        + ". Prioritaskan momen di dalam rentang ini, tapi jangan abaikan momen "
        "bagus di luar heatmap bila sangat kuat."
    )
