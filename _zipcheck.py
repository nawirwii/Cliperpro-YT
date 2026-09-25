"""Verify a *shipped* release zip really contains the binaries the app needs.

Run after a release:
    python3 _zipcheck.py 2.0.84

This is the check that would have caught the aria2c bug at v2.0.82 instead of
the user reporting "aria2c tidak ditemukan". Verified against the real
v2.0.81/.82/.83 assets: all three shipped aria2c=False, and the only signal
we had (portable zip size) was pure noise — the zips differed by ~4 KB.
"""
import io
import sys
import time
import urllib.error
import urllib.request
import zipfile

# What the app looks for at runtime, and therefore what must ship.
# Path -> whether the update zip needs it too.
REQUIRED = {
    "bin\\aria2c.exe": True,   # v2.0.82 multi-connection downloader
    "bin\\deno.exe": False,
    "ffmpeg\\ffmpeg.exe": False,
    "models\\face_landmarker.task": False,
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def resolve(url: str) -> str:
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(urllib.request.Request(url, method="HEAD"), timeout=60) as r:
            return r.headers.get("Location") or url
    except urllib.error.HTTPError as e:
        return e.headers.get("Location") or url


def _get(url: str, start: int, end: int) -> bytes:
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    req.add_header("User-Agent", "hermes")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return resp.read()
        except Exception:
            if attempt == 4:
                raise
            time.sleep(6)


class HttpFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests (reads only the
    central directory, not the 275 MB payload)."""

    def __init__(self, url: str):
        self._url, self._pos = url, 0
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "hermes")
        with urllib.request.urlopen(req, timeout=60) as r:
            self._size = int(r.headers["Content-Length"])

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, offset, whence=io.SEEK_SET):
        self._pos = (offset if whence == io.SEEK_SET
                     else self._pos + offset if whence == io.SEEK_CUR
                     else self._size + offset)
        return self._pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self._size - self._pos
        if n == 0 or self._pos >= self._size:
            return b""
        end = min(self._pos + n, self._size) - 1
        data = _get(self._url, self._pos, end)
        self._pos += len(data)
        return data


def check(ver: str, kind: str) -> bool:
    url = (f"https://github.com/nawirwii/Cliperpro-YT/releases/download/v{ver}/"
           f"YTShortClipperV2_{ver}_x64_{kind}.zip")
    real = resolve(url)
    names = []
    for _ in range(6):
        try:
            with zipfile.ZipFile(HttpFile(real)) as zf:
                names = [i.filename.replace("/", "\\") for i in zf.infolist()]
            break
        except Exception as e:  # noqa: BLE001
            print(f"  attempt failed: {type(e).__name__}: {e}", flush=True)
            time.sleep(8)
    if not names:
        print(f"v{ver} {kind}: COULD NOT READ")
        return False

    print(f"v{ver} {kind}.zip  entries={len(names)}")
    ok = True
    for want, needed_here in REQUIRED.items():
        found = any(want in n for n in names)
        if kind == "update" and not needed_here:
            continue
        mark = "OK " if found else "MISS"
        if not found:
            ok = False
        print(f"   [{mark}] {want}")
    print(f"   => {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    vers = sys.argv[1:] or ["2.0.84"]
    all_ok = True
    for v in vers:
        for kind in ("portable", "update"):
            all_ok &= check(v, kind)
            print()
    sys.exit(0 if all_ok else 1)
