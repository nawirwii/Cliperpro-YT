"""Pre/post padding for highlight boundaries.

A clip cut exactly at the AI's chosen start often begins mid-sentence and ends
before the payoff, which is the single most common reason a good moment still
feels unpolished. Padding gives the clip breathing room on both sides.

The non-obvious part is that padding is not "shift the numbers". A clip has a
hard duration budget (58-120s for short-form) and a hard container (the source
video), so naively adding seconds silently produces clips that violate both:
over-long ones get rejected by validation, and ones padded past 0s or past the
video end produce negative or out-of-range timestamps that ffmpeg either
mangles or refuses.

So padding is applied as a *budget-aware* expansion: grow by the requested
amount, then pull back in and, if the clip would exceed the cap, trim from the
end of the padding rather than from the highlight itself.
"""

from __future__ import annotations

from typing import Any

# The selection prompt already asks the model for 58-120s clips.
MIN_CLIP_SECONDS = 58.0
MAX_CLIP_SECONDS = 120.0

DEFAULT_PRE_PADDING = 3.0
DEFAULT_POST_PADDING = 5.0
MAX_PADDING = 30.0


def clamp_padding(value: Any, default: float = 0.0) -> float:
    """Accept anything the UI might send, return a sane non-negative number."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(0.0, min(MAX_PADDING, v))


def apply_padding(
    start: float,
    end: float,
    pre: float = DEFAULT_PRE_PADDING,
    post: float = DEFAULT_POST_PADDING,
    duration: float | None = None,
    max_seconds: float = MAX_CLIP_SECONDS,
) -> tuple[float, float, dict[str, Any]]:
    """Return (start, end, notes) after padding within the available budget.

    ``notes`` records what was clamped so the UI can explain a clip that came
    back shorter than the user asked for, instead of silently ignoring them.
    """
    notes: dict[str, Any] = {}
    pre = clamp_padding(pre)
    post = clamp_padding(post)

    raw_len = end - start

    new_start = start - pre
    new_end = end + post

    # 1. Stay inside the video.
    if new_start < 0:
        notes["start_clamped"] = -new_start
        new_start = 0.0
    if duration is not None and new_end > duration:
        notes["end_clamped"] = new_end - duration
        new_end = float(duration)

    # 2. Stay inside the clip budget. Trim the *padding*, never the highlight:
    #    the highlight is the reason the clip exists.
    if new_end - new_start > max_seconds:
        overflow = (new_end - new_start) - max_seconds
        if post >= overflow:
            new_end -= overflow
            notes["post_trimmed"] = overflow
        else:
            new_end -= post
            remaining = overflow - post
            # Only give up 'pre' if there is nothing else left to give.
            take_pre = min(remaining, pre)
            new_start += take_pre
            notes["pre_trimmed"] = take_pre
            if remaining - take_pre > 0:
                new_end -= (remaining - take_pre)
                notes["end_trimmed"] = remaining - take_pre

    # 3. Never let padding invert or empty the clip.
    if new_end <= new_start:
        new_start, new_end = start, end
        notes["padding_dropped"] = True

    new_start = round(max(0.0, new_start), 2)
    new_end = round(new_end, 2)
    notes["original"] = {"start": round(start, 2), "end": round(end, 2)}
    notes["final_duration"] = round(new_end - new_start, 2)
    return new_start, new_end, notes


def apply_padding_to_highlights(
    highlights: list[dict[str, Any]],
    pre: float,
    post: float,
    duration: float | None = None,
    max_seconds: float = MAX_CLIP_SECONDS,
) -> list[dict[str, Any]]:
    """Pad every highlight in place, keeping the transcript slice in sync.

    ``transcript_text`` is re-extracted by the caller after padding, so it is
    cleared here rather than left describing the unpadded range.
    """
    for h in highlights:
        try:
            start = float(h["start_time"])
            end = float(h["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        new_start, new_end, notes = apply_padding(
            start, end, pre, post, duration=duration, max_seconds=max_seconds
        )
        h["start_time"] = new_start
        h["end_time"] = new_end
        h["padding_notes"] = notes
        h["duration_seconds"] = round(new_end - new_start, 2)
        h["transcript_text"] = None
    return highlights
