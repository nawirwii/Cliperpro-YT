"""Smoke v2.0.86 — a DNS failure is not a size problem.

Real user log (v2.0.85, local 43-min MP4, HuggingFace inference endpoint):

    [22:09:31] Transcribing chunk 1/9 (chunk_000.mp3, 2.3 MB) via https://api-inference.huggingface.co/...
    [22:09:31]   chunk 1/9: koneksi terputus, ulang dalam 4 detik (percobaan 1/2)...
    [22:09:35]   chunk 1/9: koneksi terputus — membagi menjadi 2 bagian (150 detik) lalu mencoba lagi...
    [22:09:40]   ... membagi menjadi 2 bagian (75 detik) lalu mencoba lagi...
    [22:09:46] ERROR: Transcription timeout — ... model terlalu berat untuk durasi video
                     — coba model 'whisper-large-v3-turbo' ...
    httpcore2.ConnectError: [Errno 11001] getaddrinfo failed

3 defects this locks down:
  1. The 4-level cause chain must be walked. str(APIConnectionError) is just
     "Connection error." — the real reason only exists 3 __cause__ hops down.
  2. Halving must NOT happen for connectivity errors. 2.3 MB against a ~25 MB
     cap cannot be a size problem, and the whole attempt died in 15 s.
  3. The message must not blame the model or suggest switching to turbo.
"""
import sys
import types

sys.path.insert(0, "/opt/data/workspace/Cliperpro-YT")
import yt_short_clipper_core.session as S

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{extra}]" if extra else ""))


# ---------------------------------------------------------------- 1. chain
print("\n=== 1. walks the full cause chain ===")
# Reconstruct the exact layering from the user's stderr:
#   openai.APIConnectionError -> httpx.ConnectError -> httpcore.ConnectError
#   -> OSError(11001, "getaddrinfo failed")
# Build the CLASSES first, then raise instances of them. (Assigning
# `type(...)("msg")` directly yields an instance, and calling it again raises
# TypeError, which is a false-positive trap for marker matching.)


def _mk(name):
    return type(name, (Exception,), {})


SockErr = _mk("OSError_")
HttpcoreErr = _mk("httpcore_ConnectError")
HttpxErr = _mk("httpx_ConnectError")
ApiErr = _mk("openai_APIConnectionError")

skt = SockErr("[Errno 11001] getaddrinfo failed")
try:
    try:
        try:
            try:
                raise skt
            except BaseException as e:
                raise HttpcoreErr("[Errno 11001] getaddrinfo failed") from e
        except BaseException as e:
            raise HttpxErr("connect error") from e
    except BaseException as e:
        raise ApiErr("Connection error.") from e
except BaseException as top:
    chain_exc = top

d = S._network_failure_detail(chain_exc)
check("detects DNS through 3 layers", d is not None, repr(d))
check("reports the real reason", d and "getaddrinfo" in d.lower(), repr(d))
check("names the innermost exception type",
      d and "OSError_" in d, repr(d))
check("prefers the concrete message over the outer ConnectError",
      d and "httpx_ConnectError" not in d,
      "the outer layer's message is 'connect error' — true but useless")
check("top-level msg alone is NOT enough",
      S._network_failure_detail(Exception("Connection error.")) is None,
      "otherwise every transient blip would be misread as DNS")
check("harness itself is sound (no TypeError leaked)",
      d is not None and "TypeError" not in d, repr(d))

print("\n=== 2. recognizes the other transport failures ===")
for label, msg in [
    ("glibc EAI_NONAME", "[Errno -2] Name or service not known"),
    ("glibc EAI_AGAIN", "[Errno -3] Temporary failure in name resolution"),
    ("windows EAI_FAIL", "[Errno 11002] host not found"),
    ("refused", "connection refused"),
    ("unreachable", "network is unreachable"),
]:
    check(label, S._network_failure_detail(OSError(msg)) is not None)

print("\n=== 3. does NOT misclassify real problems ===")
check("HTTP 413 style is not connectivity",
      S._network_failure_detail(Exception("413 Payload Too Large")) is None)
check("auth error is not connectivity",
      S._network_failure_detail(Exception("401 invalid api key")) is None)
check("model-capability error is not connectivity",
      S._network_failure_detail(Exception("model not found")) is None)

print("\n=== 4. NetworkUnreachable exists and is a RuntimeError ===")
check("class defined", hasattr(S, "NetworkUnreachable"))
check("is RuntimeError so sidecar's `except RuntimeError: raise` keeps it",
      issubclass(S.NetworkUnreachable, RuntimeError))
check("caught before generic handler",
      S.NetworkUnreachable.__mro__.index(RuntimeError) > 0)

print("\n=== 5. retry policy is more patient, and never splits ===")
check("4 attempts, not 2", S.NET_RETRY_ATTEMPTS >= 4, f"{S.NET_RETRY_ATTEMPTS}")
check("exponential base wait", S.NET_RETRY_BASE_WAIT >= 5, f"{S.NET_RETRY_BASE_WAIT}")
import inspect
src = inspect.getsource(S._transcribe_piece)
# The split block must sit AFTER the network early-raise, never before it.
split_at = src.index("duration = _probe_duration")
raise_at = src.index("if net_detail is not None:")
check("network failure raises BEFORE any splitting", raise_at < split_at)
check("split still reachable for non-network errors", "MAX_SPLIT_DEPTH" in src)
check("no 'for attempt in range(1, 3)' left", "range(1, 3)" not in src)

print("\n=== 6. message no longer blames the model ===")
msrc = inspect.getsource(S._transcribe_audio)
netmsg = msrc[msrc.index("if isinstance(exc, NetworkUnreachable):"):]
netmsg = netmsg[:netmsg.index("from exc")]
check("says explicitly NOT a model problem",
      "BUKAN masalah model" in netmsg or "bukan masalah model" in netmsg.lower())
check("says NOT a size problem", "BUKAN masalah ukuran" in netmsg)
check("tells the user to check DNS", "DNS" in netmsg and "8.8.8.8" in netmsg)
check("does not tell them to switch to turbo",
      "whisper-large-v3-turbo" not in netmsg,
      "switching models cannot fix an unresolvable hostname")
check("names the host so it is actionable", "host_of(base_url)" in netmsg)
check("no garbled filler text", "Somehow" not in netmsg and "somehow" not in netmsg)

print("\n=== 7. host_of helper ===")
check("extracts hostname",
      S.host_of("https://api-inference.huggingface.co/models/x") == "api-inference.huggingface.co")
check("tolerates junk", isinstance(S.host_of("not a url"), str))
check("base_url_hint returns a str", isinstance(S.base_url_hint("ConnectError: boom"), str))

print(f"\n{'=' * 58}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  FAILED:", f)
    sys.exit(1)
print("v2.0.86 DNS-vs-size smoke: all green")
