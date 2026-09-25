"""Smoke v2.0.87 — transcription provider presets + the retired HF host.

The failure that prompted this, verified directly rather than assumed:

    $ getent hosts api-inference.huggingface.co     -> (nothing; NO RESOLVE)
    $ getent hosts router.huggingface.co            -> 13.249.231.23
    $ curl -o /dev/null -w %{http_code} https://router.huggingface.co/v1/models
    200
    $ ... /v1/audio/transcriptions  -> 401   (route live, auth missing)

So `api-inference.huggingface.co` is simply gone: the user's network was never
the problem, and telling them to change DNS or use a hotspot was wrong advice.
The preset must therefore never emit that host, and must emit the router URL
instead.
"""
import re
import sys
import pathlib

REPO = pathlib.Path("/opt/data/workspace/Cliperpro-YT")
cfg = (REPO / "src/config/aiProviders.ts").read_text(encoding="utf-8")
page = (REPO / "src/pages/AIModelsPage.tsx").read_text(encoding="utf-8")

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{extra}]" if extra else ""))


def strip_comments(ts: str) -> str:
    """Drop /* */ and // comments so a URL in prose is not mistaken for a value.

    The retired host is deliberately named in a doc comment explaining why it
    was replaced; only its presence in *shipped values* is a bug.
    """
    ts = re.sub(r"/\*.*?\*/", "", ts, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in ts.split("\n"))


# Only the transcription block is in scope. The main AI_PROVIDER_PRESETS list
# legitimately contains other providers (Google's base URL ends in /v1beta),
# so checking every baseUrl in the file would assert nonsense.
TR_BLOCK = cfg.split("export const TRANSCRIPTION_PRESETS")[1].split("\n];")[0]
TR_CODES = strip_comments(cfg)
PAGE_CODES = strip_comments(page)

print("\n=== 1. the retired host ships as a value nowhere ===")
check("aiProviders.ts values free of api-inference.huggingface.co",
      "api-inference.huggingface.co" not in TR_CODES)
check("AIModelsPage.tsx free of api-inference.huggingface.co",
      "api-inference.huggingface.co" not in PAGE_CODES)
check("it is still documented in a comment (why we replaced it)",
      "api-inference.huggingface.co" in cfg)

print("\n=== 2. Hugging Face preset points at the live router ===")
check("huggingface preset exists", 'key: "huggingface"' in TR_BLOCK)
check("base URL is the router",
      "https://router.huggingface.co/v1" in TR_BLOCK)
check("model is a real HF repo id",
      "openai/whisper-large-v3-turbo" in TR_BLOCK)
check("key format is hf_", 'apiKeyFormat: "hf_*"' in TR_BLOCK)
check("signup link points at token settings",
      "https://huggingface.co/settings/tokens" in TR_BLOCK)

print("\n=== 3. transcription base URLs are well-shaped ===")
tr_urls = re.findall(r'baseUrl:\s*"(https?://[^"]+)"', TR_BLOCK)
print("      transcription base URLs:", tr_urls)
check("every transcription base URL ends in /v1",
      all(u.rstrip("/").endswith("/v1") for u in tr_urls),
      f"http:// too — localhost custom uses http, not https")
check("no base URL contains /models/",
      not any("/models/" in u for u in tr_urls),
      "that shape produced /models/<id>/audio/transcriptions, which cannot exist")
check("found all 4 transcription presets", len(tr_urls) == 4, str(len(tr_urls)))

print("\n=== 4. presets cover the realistic choices ===")
for key in ("huggingface", "groq", "openai", "custom"):
    check(f"preset '{key}'", f'key: "{key}"' in TR_BLOCK)
check("Hugging Face is listed FIRST (the common case)",
      TR_BLOCK.index('key: "huggingface"') < TR_BLOCK.index('key: "groq"'))

print("\n=== 5. page wires the picker ===")
imports = page.split("from \"@/config/aiProviders\";")[0]
check("imports TRANSCRIPTION_PRESETS",
      "TRANSCRIPTION_PRESETS" in imports.split("import {")[-1])
check("imports transcriptionPresetFor", "transcriptionPresetFor" in imports)
check("renders a provider <select>", "Provider Transkripsi" in page)
check("select is controlled", "value={transcriptionPresetKey}" in page)
check("change handler wired", "handleTranscriptionPresetChange" in page)
check("handler prefills url", "setTranscriptionUrl(preset.baseUrl)" in page)
check("handler prefills model", "setTranscriptionModel(preset.model)" in page)
check("handler does NOT wipe the API key",
      "setTranscriptionKey(" not in page.split("handleTranscriptionPresetChange =")[1].split("};")[0],
      "discarding a typed credential would be a data-loss bug")
check("picker seeds from saved settings",
      "transcriptionPresetFor(settings.transcriptionBaseUrl" in page)

print("\n=== 6. old misleading text is gone ===")
check("no 'Optional — used ONLY when'", "Optional — used ONLY when" not in page)
check("no stale 'leave empty to reuse main model' placeholder",
      "whisper-1 (leave empty to reuse main model)" not in page)
check("placeholders now come from the preset",
      page.count("placeholder={transcriptionPreset.") == 2)

print("\n=== 7. signing up is reachable in-app ===")
check("key link present", "Ambil API key di" in page)
check("links the preset's own signup page",
      "transcriptionPreset.signupUrl" in page)
check("opens safely in a new tab", 'rel="noreferrer"' in page)

print("\n=== 8. presetFor matcher does not blow up on junk ===")
check("guarded with try/catch", "} catch {" in cfg.split("transcriptionPresetFor")[1])
check("skips the custom row when matching",
      'p.key === "custom"' in cfg.split("transcriptionPresetFor")[1])

print(f"\n{'=' * 58}\nPASS {len(PASS)}  FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  FAILED:", f)
    sys.exit(1)
print("v2.0.87 transcription preset smoke: all green")
