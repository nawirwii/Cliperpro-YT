"""Smoke v2.0.90 — folder scan for local videos.

Covers the Tauri command (extension allowlist, zero-byte rejection, natural
ordering) and the frontend wiring. The Rust itself cannot be compiled in this
environment — the toolchain install is broken — so CI on windows-latest is the
compile gate. These checks pin the *decisions* in that code, because the ones
listed below are all things a reasonable-looking rewrite would silently break.
"""

import pathlib
import re
import sys

REPO = pathlib.Path("/opt/data/workspace/Cliperpro-YT")
rs = (REPO / "src-tauri/src/commands/mod.rs").read_text(encoding="utf-8")
lib = (REPO / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
create = (REPO / "src/pages/CreatePage.tsx").read_text(encoding="utf-8")

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


def body(fn_name: str) -> str:
    """Scope to one function body, the way a naive slice would not.

    Matches private `fn` as well as `pub fn` — natural_cmp is deliberately
    module-private, and requiring `pub` here silently returned "" for it.
    """
    i = -1
    for prefix in (f"pub fn {fn_name}", f"fn {fn_name}"):
        i = rs.find(prefix)
        if i != -1:
            break
    if i == -1:
        return ""
    j = rs.find("\n#[", i)
    return rs[i: j if j != -1 else len(rs)]


print("\n=== 1. Command exists and is registered ===")
scan = body("scan_videos")
check("scan_videos is defined", scan != "")
check("scan_videos is a tauri command", "#[tauri::command]\npub fn scan_videos" in rs)
check("registered in the invoke handler", "commands::scan_videos" in lib)
check("takes a dir and returns Result", "dir: String) -> Result<Vec<ScannedVideo>, String>" in scan)

print("\n=== 2. It must not become a recursive folder crawler ===")
check("uses read_dir (single level)", "fs::read_dir(&root)" in scan)
check("no walkdir / recursive traversal", "walkdir" not in rs.lower())
check("no recurse flag", "recursive" not in scan.lower() or "non-recursive" in scan.lower())
check("subdirectories are skipped", "if !path.is_file()" in scan)
check("the reason is documented in the code",
      "Deliberately non-recursive" in rs)

print("\n=== 3. What counts as a video ===")
exts = re.search(r"const VIDEO_EXTENSIONS: \[&str; \d+\] = \[(.*?)\];", rs, re.DOTALL)
check("extension allowlist exists", exts is not None)
listed = set(re.findall(r'"([a-z0-9]+)"', exts.group(1))) if exts else set()
for want in ("mp4", "mov", "mkv", "webm", "avi", "m4v", "mpg", "mpeg", "wmv", "flv"):
    check(f"{want} is accepted", want in listed, sorted(listed))
check("the declared length matches the list", exts is not None and
      f"&str; {len(listed)}" in exts.group(0), exts.group(0) if exts else "")
check("extension compare is case-insensitive", "to_ascii_lowercase()" in scan)
check("a non-video file is skipped", "if !VIDEO_EXTENSIONS.contains" in scan)

print("\n=== 4. Files that would fail later are rejected now ===")
check("zero-byte files are skipped", "if size == 0" in scan)
check("the reason is stated", "would fail later inside ffmpeg" in rs)
check("a bad folder returns a clear error", "Not a folder" in scan)
check("an unreadable folder returns a clear error", "Cannot read folder" in scan)

print("\n=== 5. Natural ordering (episode 2 before episode 10) ===")
check("natural_cmp exists", "fn natural_cmp" in rs)
check("used for sorting", "natural_cmp(&a.file_name, &b.file_name)" in rs)
nc = body("natural_cmp")
check("digit runs are compared as numbers", "is_ascii_digit()" in nc)
check("numeric compare happens on u128, not strings",
      "u128" in nc and ".parse()" in nc)
check("fallback is case-insensitive", "to_ascii_lowercase()" in nc)
check("both iterators always make progress (no infinite loop)",
      nc.count(".next()") >= 2, nc.count(".next()"))

print("\n=== 6. Frontend wiring ===")
check("CreatePage imports invoke", 'from "@tauri-apps/api/core"' in create)
check("calls the command with a dir arg", 'invoke<ScannedVideo[]>("scan_videos", { dir })' in create)
check("folder dialog, not a file dialog", "directory: true" in create)
check("scanning flag drives a spinner", "scanning" in create and "Memindai" in create)
check("an empty folder is informational, not an error toast",
      "toast.info" in create and "Tidak ada video di folder ini" in create)
check("a real failure still shows an error toast", "Gagal memindai folder" in create)
check("the list only shows for local source", 'source === "local" &&' in create)
check("clicking a scanned file loads it into the existing single-file flow",
      "setLocalPath(v.path)" in create and "setLocalFileName(v.fileName)" in create)
check("file size is shown in MB", "1024 * 1024" in create)

print("\n=== 7. Nothing quietly broke along the way ===")
check("DIRECTION_MAX is still 1000 (mirrors the backend)",
      "const DIRECTION_MAX = 1000;" in create)
check("no duplicate AUTO_LANGUAGE declaration",
      create.count("const AUTO_LANGUAGE") == 0 and "AUTO_LANGUAGE," in create)
check("scan result type mirrors the Rust struct",
      "fileName: string" in create and "sizeBytes: number" in create)
check("the earlier 2.0.89 features are still wired",
      "pre_padding: prePadding" in create and "use_heatmap: useHeatmap" in create)

print(f"\nPASS {passed}  FAIL {failed}")
sys.exit(1 if failed else 0)
