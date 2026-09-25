"""Smoke v2.0.83 — extraction-failure propagation + stale-cookie diagnosis.

Regression focus: the worker thread used to swallow yt-dlp's DownloadError,
so the user saw "Downloaded section file not found" instead of the real
cause ("The page needs to be reloaded" => stale cookies).
"""
import sys
import threading
import time

sys.path.insert(0, "/opt/data/workspace/Cliperpro-YT")
import yt_short_clipper_core.video_processor as V

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{extra}]" if extra else ""))


print("\n=== 1. reproduce the old bug: thread swallows the error ===")
# This is the OLD shape: bare lambda target, exception dies in the thread.
holder_old = {"got": None}
def old_style():
    try:
        raise RuntimeError("The page needs to be reloaded.")
    except BaseException as e:
        pass  # swallowed, exactly like a bare lambda target
t = threading.Thread(target=old_style)
t.start(); t.join()
check("old shape lost the error", holder_old["got"] is None,
      "lambda-target swallows; is_alive() then False == 'success'")

print("\n=== 2. new shape captures the exception ===")
holder = {}
def new_style():
    try:
        raise RuntimeError("The page needs to be reloaded.")
    except BaseException as e:
        holder["exc"] = e
t = threading.Thread(target=new_style)
t.start(); t.join()
check("new shape captured error", "exc" in holder)
check("message preserved", "page needs to be reloaded" in str(holder.get("exc")))

print("\n=== 3. _run_download re-raises (source-verified) ===")
# download_video_section is a thin wrapper; the real body lives in
# _download_section_module, which is where the download thread is started.
import inspect
fn = getattr(V, "_download_section_module", None)
check("inner _download_section_module exists", fn is not None)
src = inspect.getsource(fn)
check("no bare lambda download target",
      "lambda: yt_dlp.YoutubeDL" not in src,
      "bare lambda was the swallow")
check("uses a named _target", "def _target()" in src)
check("captures BaseException", "except BaseException as exc" in src)
check("stores in holder", 'holder["exc"] = exc' in src)
check("re-raises after join", 'if "exc" in holder' in src and 'raise holder["exc"]' in src)

print("\n=== 4. stale-cookie diagnosis reachable ===")
check("detects 'page needs to be reloaded'",
      "page needs to be reloaded" in src)
check("detects 'video unavailable'", "video unavailable" in src)
check("tells user to re-export cookies",
      "Get cookies.txt LOCALLY" in src)
check("explains it is NOT a network problem",
      "bukan masalah jaringan" in src)
# 403 must keep its own distinct message (older, separate path)
check("403 path preserved", "HTTP 403" in src)
# guard: the diagnosis calls a raising helper
check("cookie lookup guarded inside diagnosis", "except Exception:" in src)

print("\n=== 5. _SustainedThrottle still distinct ===")
check("still a RuntimeError", issubclass(V._SustainedThrottle, RuntimeError))
check("not plain RuntimeError", type(V._SustainedThrottle("x")) is not RuntimeError)

print(f"\n{'=' * 56}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  FAILED:", f)
    sys.exit(1)
print("v2.0.83 propagation smoke: all green")
