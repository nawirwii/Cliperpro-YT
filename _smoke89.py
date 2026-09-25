"""Smoke v2.0.89 — AI heatmap ("Momen Panas") + clip padding.

The feature request was for a YouTube-style "Most Replayed" heatmap on local
files. That is not implementable, and this suite exists partly to keep that
fact from drifting back into a lie: a local MP4 has no viewers, and YouTube's
own endpoint returns the heatmap metadata with zero markers. So the product
ships an AI estimate and must LABEL it as one.

Covers: window bucketing, lenient score parsing, non-overlapping hot range
selection, budget-aware padding, and the padding-before-transcript-slice
ordering that is easy to get wrong.
"""

import json
import pathlib
import re
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, "/opt/data/workspace/Cliperpro-YT")

from yt_short_clipper_core import heatmap, padding, session  # noqa: E402

REPO = pathlib.Path("/opt/data/workspace/Cliperpro-YT")
src_heatmap = (REPO / "yt_short_clipper_core/heatmap.py").read_text(encoding="utf-8")
src_padding = (REPO / "yt_short_clipper_core/padding.py").read_text(encoding="utf-8")
src_session = (REPO / "yt_short_clipper_core/session.py").read_text(encoding="utf-8")
src_create = (REPO / "src/pages/CreatePage.tsx").read_text(encoding="utf-8")

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {passed:<3} {name}")
    else:
        failed += 1
        print(f"PASS {passed:<3} FAIL {name}  [{detail}]")


# ---------------------------------------------------------------- honesty
print("\n=== 1. The 'Most Replayed' claim must not leak into the product ===")
ui_all = "\n".join(
    (REPO / p).read_text(encoding="utf-8")
    for p in [
        "src/pages/CreatePage.tsx",
        "src/config/aiProviders.ts",
        "src/pages/AIModelsPage.tsx",
    ]
)
# Strip JSX/TS comments first. The source explains to future maintainers that
# the feature is NOT called "Most Replayed", and that comment is not a promise
# to any user — scanning raw source flagged it as one.
ui_visible = re.sub(r"\{/\*.*?\*/\}", "", ui_all, flags=re.DOTALL)
ui_visible = re.sub(r"//[^\n]*", "", ui_visible)
ui_visible = re.sub(r"/\*.*?\*/", "", ui_visible, flags=re.DOTALL)
# A *promise* of viewer data is what we must never ship. Naming it while
# denying it is available is the opposite — that sentence is the reason a user
# does not go hunting for a heatmap panel that will not exist.
mentions = re.findall(r".{0,90}Most Replayed.{0,60}", ui_visible, re.DOTALL)
promises = [m for m in mentions
            if not re.search(r"tidak punya|tidak bisa|nggak ada|tidak ada", m)]
check("UI never promises a viewer heatmap",
      not promises, f"promising text: {promises[:2]}")
check("the one visible mention explains why it is unavailable",
      len(mentions) > 0 and all(
          re.search(r"tidak punya|tidak bisa|nggak ada|tidak ada", m) for m in mentions),
      mentions)
check("UI calls it Momen Panas instead", "Momen Panas" in src_create)
check("UI states it is an AI estimate, not viewer data",
      "estimasi AI" in src_create and "bukan data penonton" in src_create)
check("module documents why the real heatmap is unavailable",
      "Most Replayed" in src_heatmap and "viewers" in src_heatmap)

# ---------------------------------------------------------------- windows
print("\n=== 2. Window bucketing ===")
SRT = """1
00:00:00,000 --> 00:00:04,000
halo dunia

2
00:01:30,000 --> 00:01:34,000
menarik sekali

3
00:03:05,000 --> 00:03:09,000
momen panas
"""
with tempfile.TemporaryDirectory() as td:
    p = pathlib.Path(td) / "t.srt"
    p.write_text(SRT, encoding="utf-8")

    w = heatmap.build_windows(str(p), 60)
    check("three spoken windows from a 3-minute transcript", len(w) == 3, f"got {len(w)}")
    check("window 0 starts at 0", w[0]["start"] == 0.0)
    check("window 1 starts at 60s", w[1]["start"] == 60.0, f"got {w[1]['start']}")
    check("window 2 starts at 180s", w[2]["start"] == 180.0, f"got {w[2]['start']}")
    check("every window carries text", all(x["text"] for x in w))

    # A gap in speech must not become a bucket full of empty prompts.
    SRT_GAP = """1
00:00:00,000 --> 00:00:04,000
awal

2
00:10:00,000 --> 00:10:04,000
akhir
"""
    p.write_text(SRT_GAP, encoding="utf-8")
    wg = heatmap.build_windows(str(p), 60)
    check("silent gap is dropped, not scored as empty", len(wg) == 2, f"got {len(wg)}")

    # Long window text is truncated so a 45-min video stays cheap.
    long_srt = "1\n00:00:00,000 --> 00:00:59,000\n" + ("kata " * 2000) + "\n"
    p.write_text(long_srt, encoding="utf-8")
    wl = heatmap.build_windows(str(p), 60)
    check("oversized window text is truncated",
          len(wl[0]["text"]) <= heatmap.MAX_CHARS_PER_WINDOW + 2,
          f"len {len(wl[0]['text'])}")
    check("truncation is marked so the model knows it is partial",
          wl[0]["text"].endswith("…"))

# ---------------------------------------------------------------- parsing
print("\n=== 3. Score parsing is lenient but not credulous ===")
wins = [{"index": i, "start": float(i * 60), "end": float(i * 60 + 60), "text": "x"} for i in range(5)]
logs: list[str] = []
nolog = logs.append

s = heatmap.parse_heatmap('[{"i":0,"s":12},{"i":3,"s":88}]', wins, nolog)
check("clean JSON parses", s == {0: 0.12, 3: 0.88}, s)

s = heatmap.parse_heatmap('```json\n[{"i":1,"s":50}]\n```', wins, nolog)
check("code fence is stripped", s == {1: 0.5}, s)

s = heatmap.parse_heatmap('[{"i":1,"s":140},{"i":2,"s":-5}]', wins, nolog)
check("out-of-range scores are clamped", s.get(1) == 1.0 and s.get(2) == 0.0, s)

s = heatmap.parse_heatmap('[{"i":1,"s":50},{"i":99,"s":90}]', wins, nolog)
check("score for an unknown window is discarded", 99 not in s, s)

logs.clear()
s = heatmap.parse_heatmap('{"i":1, "s": 77', wins, nolog)
check("truncated JSON is salvaged by pattern", s == {1: 0.77}, s)
check("salvage is announced in the log", any("salvaged" in m for m in logs), logs)

logs.clear()
s = heatmap.parse_heatmap("model refused to answer", wins, nolog)
check("garbage yields no scores", s == {}, s)
check("empty result is announced, not silently empty", any("no recognisable" in m for m in logs), logs)

# A partially-scored map is still useful; the gaps must be ABSENT, not 0.0,
# because 0 means "scored and found boring".
s = heatmap.parse_heatmap('[{"i":0,"s":5},{"i":4,"s":95}]', wins, nolog)
check("unscored windows are absent, not zero", 0 not in s or s[0] == 0.05, s)
check("partial map keeps the hot window", s.get(4) == 0.95, s)

# ---------------------------------------------------------------- hot range
print("\n=== 4. Hot ranges are non-overlapping and merged ===")
rng = heatmap.hottest_ranges({0: 0.2, 1: 0.9, 2: 0.85, 5: 0.95}, limit=5)
overlap = any(not (b[1] <= a[0] or b[0] >= a[1]) for i, a in enumerate(rng) for b in rng[i + 1:])
check("no two hot ranges overlap", not overlap, rng)
check("adjacent hot windows merge into one range",
      any(a == 0.0 and b == 180.0 for a, b in rng), rng)
check("hottest window is included", any(a <= 300 < b for a, b in rng), rng)
check("empty map yields no ranges", heatmap.hottest_ranges({}, 5) == [])

# A uniformly hot video must NOT collapse into one range covering everything —
# the selector needs several distinct moments to cut from.
uniform = {i: 0.8 for i in range(30)}
ru = heatmap.hottest_ranges(uniform, limit=6)
check("a uniformly hot video still yields several ranges", len(ru) >= 5, f"got {len(ru)}")
check("no range exceeds the merge ceiling",
      all(b - a <= heatmap.MAX_MERGE_SECONDS + 0.01 for a, b in ru),
      [(a, b) for a, b in ru if b - a > heatmap.MAX_MERGE_SECONDS])
check("merged ranges never overlap each other",
      not any(not (b[1] <= a[0] or b[0] >= a[1])
              for i, a in enumerate(ru) for b in ru[i + 1:]), ru)

hint = heatmap.format_hot_hint(rng)
check("hint names itself Momen Panas, not Most Replayed", "Momen Panas" in hint)
check("hint is advisory, not a hard filter", "jangan abaikan" in hint)
check("no hint without ranges", heatmap.format_hot_hint([]) == "")

# ---------------------------------------------------------------- padding
print("\n=== 5. Padding respects the container and the budget ===")
check("no padding when both are zero",
      padding.apply_padding(100, 160, 0, 0, duration=600)[:2] == (100.0, 160.0))

s, e, n = padding.apply_padding(300, 360, 3, 5, duration=600)
check("normal padding grows both sides", (s, e) == (297.0, 365.0), (s, e))

s, e, _ = padding.apply_padding(2, 62, 10, 5, duration=600)
check("start clamps at zero, does not go negative", s == 0.0 and e > 0, (s, e))

s, e, _ = padding.apply_padding(540, 600, 3, 20, duration=600)
check("end clamps to the video duration", e == 600.0, e)

for raw_len, pre, post in [(115, 3, 5), (118, 10, 10), (120, 30, 30), (300, 30, 30)]:
    s, e, _ = padding.apply_padding(300, 300 + raw_len, pre, post, duration=600)
    check(f"{raw_len}s clip + {pre}/{post} padding stays under the 120s cap",
          e - s <= padding.MAX_CLIP_SECONDS + 0.01, f"len {e - s}")

# The highlight is the reason the clip exists: padding is what gives way.
s, e, n = padding.apply_padding(300, 415, 3, 5, duration=600)
check("trim comes out of the padding, not the highlight",
      415 <= e and s <= 300, (s, e, n))

s, e, _ = padding.apply_padding(100, 101, 0.2, 0.1, duration=600)
check("padding can never invert a clip", e > s, (s, e))

for bad, want in [("abc", 0.0), (None, 0.0), (-5, 0.0), (999, 30.0), (float("nan"), 0.0)]:
    got = padding.clamp_padding(bad)
    check(f"clamp_padding({bad!r}) -> {want}", got == want, got)

hl = [{"start_time": 300.0, "end_time": 360.0, "transcript_text": "old text"}]
out = padding.apply_padding_to_highlights(hl, 3, 5, duration=600)
check("highlights are padded in place", out[0]["start_time"] == 297.0, out[0])
check("stale transcript text is cleared, not left describing the old range",
      out[0]["transcript_text"] is None, out[0])
check("duration_seconds is recomputed", out[0]["duration_seconds"] == 68.0, out[0])

# ---------------------------------------------------------------- ordering
print("\n=== 6. Ordering: pad, THEN slice the transcript ===")
m = re.search(
    r"(# Padding happens BEFORE.*?)\n(    log\(\"Extracting transcript)",
    src_session, re.DOTALL,
)
check("padding is applied before the transcript slice", m is not None)
check("the comment says why the order matters",
      "would leave the text describing a range we no longer cut"
      in src_session)

check("session passes the heatmap ranges into selection", "hot_ranges=hot_ranges" in src_session)
check("session passes the video duration for clamping", "duration=_duration or None" in src_session)
check("heatmap is stored in the session data", '"heatmap": heatmap_data' in src_session)
check("a heatmap failure cannot kill the run",
      "never let a nice-to-have kill the run" in src_session)
check("short videos skip the map instead of scoring noise",
      "MIN_WINDOWS_FOR_HEATMAP" in src_heatmap)
check("the heatmap can be switched off", 'ai.get("use_heatmap", True)' in src_session)
check("padding can be switched off with both fields at zero",
      "if pre == 0 and post == 0" in src_session)

# ---------------------------------------------------------------- UI
print("\n=== 7. UI plumbing ===")
check("pre_padding is sent to the sidecar", "pre_padding: prePadding" in src_create)
check("post_padding is sent to the sidecar", "post_padding: postPadding" in src_create)
check("the toggle is sent to the sidecar", "use_heatmap: useHeatmap" in src_create)
check("UI clamps padding to the same 0..30 as the sidecar",
      "Math.max(0, Math.min(30" in src_create)
check("UI padding fields only show for local source",
      'source === "local" && (' in src_create)

print(f"\nPASS {passed}  FAIL {failed}")
sys.exit(1 if failed else 0)
