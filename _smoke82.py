"""Smoke v2.0.82 — YouTube throttle mitigations.

Covers the four mitigations and the crash-regression that nearly shipped:

  1. aria2c multi-connection opts (+ safe native fallback when absent)
  2. sustained-throttle detection window
  3. client ladder shape (names verified against yt-dlp INNERTUBE_CLIENTS)
  4. throttle warning does NOT crash when cookies.txt is missing
     (regression: _get_cookies_path() RAISES in exactly that case)
"""
import sys
import types
import time

sys.path.insert(0, "/opt/data/workspace/Cliperpro-YT")
import yt_short_clipper_core.video_processor as V

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{extra}]" if extra else ""))


print("\n=== 1. aria2c downloader opts ===")
logs = []
o = V._build_downloader_opts("C:/app/bin/aria2c.exe", logs.append)
check("returns external_downloader", "external_downloader" in o, str(sorted(o)))
check("http uses abs path", o["external_downloader"]["http"] == "C:/app/bin/aria2c.exe")
check("https uses abs path", o["external_downloader"]["https"] == "C:/app/bin/aria2c.exe")
args = o["external_downloader_args"]["http"]
check("-x16 present (16 conns/server)", "-x16" in args, str(args))
check("-s16 present (16 splits)", "-s16" in args)
check("-j16 present (16 parallel dls)", "-j16" in args)
check("-k1M present (min split size)", "-k1M" in args)
check("no file pre-allocation", "--file-allocation=none" in args)
check("silences aria2 status line", "--summary-interval=0" in args)
check("ignores user aria2.conf", "--no-conf" in args)
check("http/https args identical",
      o["external_downloader_args"]["http"] == o["external_downloader_args"]["https"])

print("\n=== 2. fallback when aria2c missing (must not break download) ===")
logs2 = []
o2 = V._build_downloader_opts(None, logs2.append)
check("empty opts => yt-dlp native", o2 == {}, str(o2))
check("explains fallback to user", any("aria2c tidak ditemukan" in m for m in logs2))

print("\n=== 3. sustained-throttle window ===")
check("threshold is 40 KiB/s", V._SUSTAINED_THROTTLE_BPS == 40 * 1024, str(V._SUSTAINED_THROTTLE_BPS))
check("window is 60s", V._SUSTAINED_THROTTLE_SECS == 60, str(V._SUSTAINED_THROTTLE_SECS))
check("40 KiB/s aborts (real case: 63 KiB/s crawl)",
      V._SUSTAINED_THROTTLE_BPS < 63 * 1024)
# 47 MiB at 40 KiB/s ~= 20 min, so aborting beats waiting
mins = (47 * 1024 * 1024) / V._SUSTAINED_THROTTLE_BPS / 60
check("abort beats waiting (>10min saved)", mins > 10, f"{mins:.0f} min at 40KiB/s")

print("\n=== 4. detection state machine ===")
st = {}
t0 = time.monotonic()
V._sustained_throttle_check({"status": "downloading", "speed": 10 * 1024}, st, lambda m: None)
check("slow sets timer", st.get("throttle_since") is not None)
# First slow sample only arms the timer; the flag stays unset (falsy) until
# the window actually elapses.
check("not yet sustained", not st.get("sustained_throttle"), repr(st.get("sustained_throttle")))
st["throttle_since"] = time.monotonic() - (V._SUSTAINED_THROTTLE_SECS + 1)
V._sustained_throttle_check({"status": "downloading", "speed": 10 * 1024}, st, lambda m: None)
check("sustained after window", st.get("sustained_throttle") is True)
# recovery must clear the flag so a retry isn't aborted instantly
V._sustained_throttle_check({"status": "downloading", "speed": 900 * 1024}, st, lambda m: None)
check("recovery clears timer", st.get("throttle_since") is None)
check("recovery clears flag", st.get("sustained_throttle") is False)
# healthy speed must never start the timer
st2 = {}
V._sustained_throttle_check({"status": "downloading", "speed": 900 * 1024}, st2, lambda m: None)
check("healthy speed no timer", st2.get("throttle_since") is None)
# non-downloading status ignored
st3 = {}
V._sustained_throttle_check({"status": "finished", "speed": 1}, st3, lambda m: None)
check("finished status ignored", st3.get("throttle_since") is None)

print("\n=== 5. client ladder (names verified vs yt-dlp INNERTUBE_CLIENTS) ===")
VALID = {
    "android", "android_vr", "client", "ios", "mweb", "tv", "tv_downgraded",
    "tv_simply", "visionos", "web", "web_creator", "web_embedded",
    "web_music", "web_safari",
}
check("ladder has 3 rungs", len(V._CLIENT_LADDER) == 3, str(len(V._CLIENT_LADDER)))
all_c = [c for rung in V._CLIENT_LADDER for c in rung]
unknown = [c for c in all_c if c not in VALID]
check("every client name is real", not unknown, f"unknown={unknown}")
check("no 'web' (needs po_token/JS)",
      not any("web" == c for c in all_c), str(all_c))
check("first rung matches previous default",
      V._CLIENT_LADDER[0] == ["visionos", "ios", "android", "tv_downgraded"],
      str(V._CLIENT_LADDER[0]))
# rungs must differ, else a retry re-uses the same identity
check("rungs are distinct", len({tuple(r) for r in V._CLIENT_LADDER}) == 3)

print("\n=== 6. REGRESSION: throttle warning must not crash without cookies ===")
# _get_cookies_path() RAISES when cookies.txt is absent. The warning fires
# exactly when cookies are often missing, so it must be guarded.
orig_get = V._get_cookies_path
def _raise():
    raise RuntimeError("cookies.txt not found. Please upload cookies first.")
V._get_cookies_path = _raise
V._progress_hook_state["throttle_warned_ts"] = 0.0
out = []
try:
    V._maybe_warn_throttled({"speed": 50 * 1024}, out.append)
    check("does NOT crash when cookies missing", True)
    check("warns anyway", bool(out), str(out[:1]))
    if out:
        m = out[0]
        check("no longer claims fake x8 mitigation",
              "parallel fragments" not in m and "×8" not in m, m[:90])
        check("reports cookies as missing", "TIDAK ada" in m)
        check("gives a concrete path", "taruh di:" in m)
        check("names multi-connection status", "Multi-koneksi" in m)
except Exception as e:  # noqa: BLE001
    check("does NOT crash when cookies missing", False, f"{type(e).__name__}: {e}")

# and with cookies present it must report them
V._get_cookies_path = lambda: "C:/app/cookies.txt"
V._progress_hook_state["throttle_warned_ts"] = 0.0
out2 = []
try:
    V._maybe_warn_throttled({"speed": 50 * 1024}, out2.append)
    check("reports cookies found", bool(out2) and "terbaca" in out2[0], str(out2[:1]))
except Exception as e:  # noqa: BLE001
    check("reports cookies found", False, f"{type(e).__name__}: {e}")
V._get_cookies_path = orig_get

# healthy speed must stay silent (no noise)
V._progress_hook_state["throttle_warned_ts"] = 0.0
out3 = []
V._maybe_warn_throttled({"speed": 900 * 1024}, out3.append)
check("silent above threshold", out3 == [], str(out3[:1]))

print("\n=== 7. _SustainedThrottle is distinguishable ===")
check("is a RuntimeError", issubclass(V._SustainedThrottle, RuntimeError))
e = V._SustainedThrottle("x")
check("catchable as RuntimeError", isinstance(e, RuntimeError))
check("NOT a plain RuntimeError",
      type(e) is not RuntimeError, type(e).__name__)

print(f"\n{'=' * 56}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  FAILED:", f)
    sys.exit(1)
print("v2.0.82 throttle smoke: all green")
