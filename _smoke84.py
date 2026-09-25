"""Smoke v2.0.84 — GPU ladder keeps fallbacks + packaging ships aria2c.

Two regressions:
  1. split_screen cached a winning pipeline and then, if that one failed,
     produced ONE attempt and jumped straight to CPU. A session that was
     already using the GPU silently lost it. The cache must reorder the
     ladder, not truncate it.
  2. package-portable.ps1 copied an explicit file list; aria2c was added to
     fetch-deps.ps1 and tauri.conf.json but NOT there, so it shipped in no
     release. Verified against the real v2.0.81/.82/.83 assets: aria2c=False.
"""
import inspect
import re
import sys

sys.path.insert(0, "/opt/data/workspace/Cliperpro-YT")
import yt_short_clipper_core.split_screen as S

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{extra}]" if extra else ""))


src = inspect.getsource(S)
fn = None
for cand in ("create_split_screen", "split_screen", "compose_split_screen"):
    if hasattr(S, cand):
        fn = getattr(S, cand)
        break
if fn is not None:
    src = inspect.getsource(fn)

print("\n=== 1. ladder is a list, not an if/elif chain ===")
check("no single-attempt cache branch",
      'attempts = [("hwupload", qsv_head, qsv_graph, video_enc_args)]' not in src,
      "the old if/elif made a 1-item ladder")
check("builds full hw_attempts list", "hw_attempts" in src)
check("mf still appended", 'hw_attempts.append(("mf"' in src)

print("\n=== 2. cache reorders, never truncates ===")
check("cache only reorders",
      "preferred = [a for a in hw_attempts" in src
      and "rest = [a for a in hw_attempts" in src
      and "attempts = preferred + rest" in src,
      "all hardware shapes stay armed")
check("tells the user fallbacks are armed", "hardware fallback(s) armed" in src)
check("no empty attempts on unknown cache value",
      "attempts = []" not in src,
      "old code produced ZERO attempts if cache held a stale label")

print("\n=== 3. CPU fallback + cache reset still intact ===")
check("CPU fallback present", "retrying with CPU (libx264)" in src)
check("resets cache after hardware failure", "_qsv_pipeline = None" in src)
check("raises with stderr tail", "Split screen composition failed" in src)

print("\n=== 4. packaging ships aria2c (the verified real bug) ===")
ps = open("/opt/data/workspace/Cliperpro-YT/scripts/package-portable.ps1", encoding="utf-8").read()
check("declares $Aria2c", "$Aria2c " in ps)
check("aria2c in required-artifact check",
      re.search(r'"aria2c\s+\(npm run deps\)"', ps) is not None)
check("aria2c copied to stage bin\\",
      'bin\\aria2c.exe' in ps)
check("aria2c in update zip too", '(Join-Path $Stage "bin")' in ps)
check("post-build verification added", "Verified: aria2c" in ps)
check("verification fails the build on absence",
      "Packaged zip is missing required binaries" in ps)

print("\n=== 5. fetch-deps still fetches it (upstream half) ===")
fd = open("/opt/data/workspace/Cliperpro-YT/scripts/fetch-deps.ps1", encoding="utf-8").read()
# The script interpolates PowerShell variables, so match the real shapes
# rather than a pre-expanded string.
check("aria2c version pinned", '$aria2Version = "1.37.0"' in fd)
check("downloads the win-64bit build1 zip",
      "aria2-$aria2Version-win-64bit-build1.zip" in fd)
check("lands in binaries\\bin (matches package-portable.ps1)",
      '$BinDir = Join-Path $BinariesDir "bin"' in fd
      and '$Aria2Exe = Join-Path $BinDir "aria2c.exe"' in fd)
check("fails loudly if the exe is missing from the archive",
      "aria2c.exe not found in extracted archive" in fd)

print("\n=== 6. tauri resource map also lists it ===")
import json
cfg = json.load(open("/opt/data/workspace/Cliperpro-YT/src-tauri/tauri.conf.json"))
res = cfg["bundle"]["resources"]
check("aria2c in tauri resources", any("aria2c" in k for k in res),
      f"{[k for k in res if 'aria2c' in k]}")

print(f"\n{'=' * 58}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  FAILED:", f)
    sys.exit(1)
print("v2.0.84 ladder + packaging smoke: all green")
