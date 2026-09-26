"""Smoke tests for the v2.0.91 onefile-extraction fix.

Bos hit this on Windows:

    [09:50:59] INFO: Starting...
    [09:52:11] ERROR: Sidecar returned no response. stderr:
    Traceback (most recent call last):
      File "pyiboot01_bootstrap.py", line 95, in <module>
      ...
    FileNotFoundError: [Errno 2] No such file or directory:
      'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\_MEI000029042\\base_library.zip'

Root cause: the sidecar is a PyInstaller *onefile* build, so it unpacks
~181 MB into a fresh %TEMP%\\_MEIxxxxxx on EVERY process start, and
`spawn_sidecar` runs once per command. Antivirus / temp cleaners watch exactly
that pattern and can delete the folder mid-extraction.

Two things are asserted here, and they are deliberately different in kind:

  1. `is_extraction_failure` is transcribed from the Rust source and run
     against the REAL traceback Bos pasted. This is behavioural evidence that
     the signature matches reality, not that a regex was typed correctly.
  2. The Rust source is checked structurally (every call site goes through the
     retry wrapper, no stale raw-string call sites left behind) because the
     local Rust toolchain is broken, so CI is the only real compile gate.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUST = ROOT / "src-tauri" / "src" / "commands" / "mod.rs"

FAILS: list[str] = []
PASSES = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSES
    if cond:
        PASSES += 1
    else:
        FAILS.append(f"{name}{(' -> ' + detail) if detail else ''}")


# --- The exact traceback from the bug report -------------------------------
REAL_STDERR = (
    'Traceback (most recent call last):\n'
    'File "pyiboot01_bootstrap.py", line 95, in <module>\n'
    'File "pyiboot01_bootstrap.py", line 75, in _pyi_bootstrap\n'
    'File "pyimod03_ctypes.py", line 96, in install\n'
    'File "<frozen importlib._bootstrap>", line 1176, in _find_and_load\n'
    'File "<frozen importlib._bootstrap>", line 1147, in _find_and_load_unlocked\n'
    'File "<frozen importlib._bootstrap>", line 690, in _load_unlocked\n'
    'File "pyimod02_importers.py", line 457, in exec_module\n'
    'File "ctypes\\util.py", line 2, in <module>\n'
    'File "<frozen importlib._bootstrap>", line 1176, in _find_and_load\n'
    'File "<frozen importlib._bootstrap>", line 1147, in _find_and_load_unlocked\n'
    'File "<frozen importlib._bootstrap>", line 690, in _load_unlocked\n'
    'File "pyimod02_importers.py", line 457, in exec_module\n'
    'File "shutil.py", line 10, in <module>\n'
    'File "<frozen importlib._bootstrap>", line 1176, in _find_and_load\n'
    'File "<frozen importlib._bootstrap>", line 1147, in _find_and_load_unlocked\n'
    'File "<frozen importlib._bootstrap>", line 690, in _load_unlocked\n'
    'File "pyimod02_importers.py", line 457, in exec_module\n'
    'File "fnmatch.py", line 14, in <module>\n'
    'File "<frozen importlib._bootstrap>", line 1176, in _find_and_load\n'
    'File "<frozen importlib._bootstrap>", line 1147, in _find_and_load_unlocked\n'
    'File "<frozen importlib._bootstrap>", line 1138, in _find_and_load_unlocked\n'
    'File "<frozen importlib._bootstrap>", line 1078, in _find_spec\n'
    'File "<frozen importlib._bootstrap_external>", line 1507, in find_spec\n'
    'File "<frozen importlib._bootstrap_external>", line 1479, in _get_spec\n'
    'File "<frozen zipimport>", line 169, find_spec\n'
    'File "<frozen importlib._bootstrap>", line 435, in spec_from_loader\n'
    'File "<frozen importlib._bootstrap_external>", line 798, in spec_from_file_location\n'
    'File "<frozen zipimport>", line 228, in get_filename\n'
    'File "<frozen zipimport>", line 758, in _get_module_code\n'
    'File "<frozen zipimport>", line 592, in _get_data\n'
    'FileNotFoundError: [Errno 2] No such file or directory: '
    "'C:\\\\Users\\\\ADMINI~1\\\\AppData\\\\Local\\\\Temp\\\\_MEI000029042\\\\base_library.zip'"
)


# --- Mirror of the Rust detector -------------------------------------------
def is_extraction_failure(stderr: str) -> bool:
    if stderr.strip() == "":
        return False
    mentions_mei = "_MEI" in stderr
    bootloader = ("pyiboot" in stderr) or ("pyimod" in stderr)
    missing = (
        "base_library.zip" in stderr
        or "FileNotFoundError" in stderr
        or "Errno 2" in stderr
    )
    return mentions_mei and (bootloader or missing)


def main() -> int:
    # 1. The real traceback must be recognised.
    check("traceback asli Bos terdeteksi", is_extraction_failure(REAL_STDERR))

    # 2. Positives: the fingerprints the bootloader actually emits.
    for name, text in [
        ("_MEI + base_library.zip", "x _MEI1 base_library.zip"),
        ("_MEI + Errno 2", "_MEI000 ... Errno 2"),
        ("_MEI + pyimod", "pyimod03_ctypes _MEI"),
        ("_MEI + pyiboot", "pyiboot01_bootstrap _MEI"),
    ]:
        check(f"positif: {name}", is_extraction_failure(text))

    # 3. Negatives. These matter most: a real Python bug must NOT be reported
    #    to the user as "your antivirus deleted our files", which would send
    #    them down a completely wrong path.
    for name, text in [
        ("stderr kosong", ""),
        ("whitespace saja", "   \n  "),
        (
            "FileNotFoundError tanpa _MEI",
            "FileNotFoundError: [Errno 2] No such file or directory: 'cookies.txt'",
        ),
        ("sidecar KeyError", "Traceback...\nKeyError: 'SID'"),
        ("connection error", "httpcore.ConnectError [Errno 11001]"),
        ("_MEI tanpa sinyal hilang", "_MEI dir cleanup"),
        ("JSON error payload", 'ok=false error=Something'),
    ]:
        check(f"negatif: {name}", not is_extraction_failure(text))

    # 4. Structural checks on the Rust source (local toolchain is broken, so
    #    these + CI are the compile evidence).
    src = RUST.read_text(encoding="utf-8")

    check("sumber Rust ada", bool(src))
    check("no_response_error didefinisikan 1x", src.count("fn no_response_error(") == 1)
    check(
        "no_response_error dipakai di 3 call site",
        len(re.findall(r"no_response_error\(&stderr\)", src)) == 3,
    )
    check("is_extraction_failure didefinisikan 1x", src.count("fn is_extraction_failure(") == 1)
    check("with_extraction_retry didefinisikan 1x", src.count("fn with_extraction_retry") == 1)
    check("MARKER didefinisikan 1x", src.count("const EXTRACTION_FAILURE_MARKER") == 1)

    # 5. Every request path must go through the retry wrapper. If one of the
    #    three kept calling *_once directly, the fix would only cover some
    #    commands — exactly the kind of partial fix that ships silently.
    for name in ("call_sidecar", "call_sidecar_streaming_process", "call_sidecar_streaming"):
        m = re.search(
            rf"fn {name}\(.*?\n\) -> Result<serde_json::Value, String> \{{\n(.*?)\n\}}",
            src,
            re.S,
        )
        check(f"{name} ada", m is not None)
        if m:
            body = m.group(1)
            check(f"{name} dibungkus retry", "with_extraction_retry" in body)
            check(f"{name} memanggil *_once", f"{name}_once" in body)
        check(f"{name}_once didefinisikan", f"fn {name}_once(" in src)

    # 6. The extraction must be redirected out of %TEMP%.
    check("sidecar_scratch_dir ada", "fn sidecar_scratch_dir(" in src)
    check("TEM P di-set ke scratch", 'cmd.env("TEMP", dir)' in src and 'cmd.env("TMP", dir)' in src)
    check(
        "scratch di app_data (bukan Program Files)",
        re.search(r"app_data_dir\(\)\.ok\(\)\?\.join\(\"sidecar-scratch\"\)", src) is not None,
    )
    # spawn_command gained a 3rd parameter; every call site must pass it.
    check("spawn_command deklarasi 3 param", "scratch: Option<&std::path::Path>," in src)
    check(
        "spawn_command dipanggil dengan scratch",
        "spawn_command(path, &[], scratch.as_deref())" in src,
    )

    # 7. Leftovers: the old raw message must survive ONLY inside the fallback
    #    branch of no_response_error.
    raw = src.count("Sidecar returned no response. stderr:")
    check("string pesan lama hanya di fallback", raw == 1, f"ditemukan {raw}x")

    # 8. No Cyrillic/homoglyph contamination in the user-facing help text.
    #    A real slip happened here: "Cliperpro" was written with a Cyrillic
    #    'е' (U+0435), which is invisible but ships to the user.
    m = re.search(r'fn extraction_failure_help.*?format!\((.*?)\n    \)', src, re.S)
    check("extraction_failure_help ada", m is not None)
    if m:
        body = m.group(1)
        non_ascii = {c for c in body if ord(c) > 127}
        check("help text ASCII-only", not non_ascii, f"karakter: {non_ascii}")
        check("help text menyebut Cliperpro", "Cliperpro" in body)
        check("help text memberi langkah antivirus", "Exclusions" in body)

    # 9. Brace balance as a cheap syntax smoke (CI is the real gate).
    check("kurung kurawal seimbang", src.count("{") == src.count("}"),
          f'{{={src.count("{")} }}={src.count("}")}')

    print(f"_smoke91: {PASSES} checks, {len(FAILS)} failed")
    for f in FAILS:
        print(f"  FAIL: {f}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
