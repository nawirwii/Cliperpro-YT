export interface AIProviderPreset {
  key: string;
  name: string;
  baseUrl: string;
  description: string;
  docsUrl: string;
  /** Key-format hint; omit when the provider's format is unknown or varies. */
  apiKeyFormat?: string;
  requiresLoad: boolean;
  /** When set, the page shows a "get your API key" callout linking here. */
  signupUrl?: string;
}

export const AI_PROVIDER_PRESETS: AIProviderPreset[] = [
  {
    key: "ytclip",
    name: "⭐ YTClip AI",
    baseUrl: "https://ai-api.ytclip.org/v1",
    description: "YTClip AI - optimized for video content processing",
    docsUrl: "https://ytclip.org/api-keys",
    apiKeyFormat: "sk-*",
    requiresLoad: true,
    signupUrl: "https://ai.ytclip.org",
  },
  {
    key: "apismart",
    name: "⭐ ApiSmart",
    baseUrl: "https://gw.apismart.ai/v1",
    description: "ApiSmart - OpenAI-compatible multi-model gateway",
    docsUrl: "https://www.apismart.ai",
    requiresLoad: true,
    signupUrl: "https://www.apismart.ai",
  },
  {
    key: "openai",
    name: "🔴 OpenAI",
    baseUrl: "https://api.openai.com/v1",
    description: "OpenAI GPT models (GPT-4o, GPT-4, etc.)",
    docsUrl: "https://platform.openai.com/api-keys",
    apiKeyFormat: "sk-*",
    requiresLoad: true,
  },
  {
    key: "google",
    name: "🔵 Google Gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta",
    description: "Google Generative AI (Gemini models)",
    docsUrl: "https://aistudio.google.com/app/apikey",
    apiKeyFormat: "AIza*",
    requiresLoad: false,
  },
  {
    key: "groq",
    name: "⚡ Groq",
    baseUrl: "https://api.groq.com/openai/v1",
    description: "Groq fast inference API",
    docsUrl: "https://console.groq.com/keys",
    apiKeyFormat: "gsk-*",
    requiresLoad: true,
  },
  {
    key: "custom",
    name: "⚙️ Custom / Local",
    baseUrl: "http://localhost:8000/v1",
    description: "Custom OpenAI-compatible endpoint (vLLM, Ollama, etc.)",
    docsUrl: "https://github.com/vllm-project/vllm",
    apiKeyFormat: "optional",
    requiresLoad: false,
  },
];

/** Fallback model suggestions for the model dropdown before a Load. */
export const FALLBACK_MODELS = ["gpt-4o", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"];

export function presetForBaseUrl(baseUrl: string): AIProviderPreset {
  const match = AI_PROVIDER_PRESETS.find(
    (p) => p.key !== "custom" && baseUrl.includes(new URL(p.baseUrl).host)
  );
  return match ?? AI_PROVIDER_PRESETS[AI_PROVIDER_PRESETS.length - 1];
}

/** Host of a signup URL without a leading "www." — used as the link label. */
export function signupLabel(url: string): string {
  return new URL(url).host.replace(/^www\./, "");
}

export interface TranscriptionPreset {
  key: string;
  name: string;
  baseUrl: string;
  model: string;
  description: string;
  /** Where to mint the key. */
  signupUrl: string;
  /** Token prefix, so the user knows they pasted the right credential. */
  apiKeyFormat: string;
  /** True for the in-process engine: no network, no key, no upload cap. */
  local?: boolean;
  /** Model choices offered as a dropdown instead of a free-text field. */
  models?: string[];
  /** Shown under the picker so the speed/quality trade-off is explicit. */
  localNote?: string;
}

/** faster-whisper model ids, smallest first. Sizes are on-disk download sizes. */
export const LOCAL_WHISPER_MODELS = [
  { id: "tiny", sizeMB: 75, note: "paling cepat, akurasi paling rendah" },
  { id: "base", sizeMB: 145, note: "cepat, cukup untuk draf" },
  { id: "small", sizeMB: 465, note: "seimbang — rekomendasi untuk CPU lama" },
  { id: "medium", sizeMB: 1500, note: "akurat, lambat di CPU" },
  { id: "large-v3", sizeMB: 3100, note: "paling akurat, paling lambat & besar" },
  { id: "turbo", sizeMB: 1600, note: "akurasi large-v3, ~4x lebih cepat dari large-v3" },
];

/**
 * Presets for the "Transcription (local videos)" card.
 *
 * v2.0.87: Hugging Face was added because the old endpoint people were told to
 * use, `api-inference.huggingface.co`, no longer resolves at all — verified
 * with getent, the hostname returns nothing, so *every* transcription attempt
 * failed at DNS before a single byte was uploaded. The OpenAI-compatible
 * surface is now `https://router.huggingface.co/v1` (HTTP 200 on /v1/models;
 * /v1/audio/transcriptions answers 401 without a token, i.e. the route is
 * live and only auth is missing). Model names are the real HF repo ids, each
 * confirmed via the public model API as `automatic-speech-recognition`.
 */
export const TRANSCRIPTION_PRESETS: TranscriptionPreset[] = [
  {
    key: "local",
    name: "🏠 Lokal (faster-whisper) — gratis, tanpa API",
    baseUrl: "local://faster-whisper",
    model: "small",
    description:
      "Jalan di komputer sendiri. Tidak ada biaya API, tidak ada batas ukuran upload, dan tidak ada data yang keluar dari PC",
    signupUrl: "https://github.com/SYSTRAN/faster-whisper",
    apiKeyFormat: "tidak perlu API key",
    local: true,
    models: LOCAL_WHISPER_MODELS.map((m) => m.id),
    localNote:
      "Model diunduh sekali saat pertama dipakai (butuh internet), lalu tersimpan dan bisa dipakai offline. CATATAN: di CPU lama, transkripsi bisa lebih LAMBAT dari durasi video — video 10 menit bisa butuh 20–40 menit. Untuk CPU lemah pilih 'small' atau 'base', bukan 'turbo'.",
  },
  {
    key: "huggingface",
    name: "🤗 Hugging Face",
    baseUrl: "https://router.huggingface.co/v1",
    model: "openai/whisper-large-v3-turbo",
    description:
      "Hugging Face Inference Providers (OpenAI-compatible). Token bertipe hf_",
    signupUrl: "https://huggingface.co/settings/tokens",
    apiKeyFormat: "hf_*",
  },
  {
    key: "groq",
    name: "⚡ Groq",
    baseUrl: "https://api.groq.com/openai/v1",
    model: "whisper-large-v3-turbo",
    description: "Groq fast inference API",
    signupUrl: "https://console.groq.com/keys",
    apiKeyFormat: "gsk-*",
  },
  {
    key: "openai",
    name: "🔴 OpenAI",
    baseUrl: "https://api.openai.com/v1",
    model: "whisper-1",
    description: "OpenAI Whisper endpoint",
    signupUrl: "https://platform.openai.com/api-keys",
    apiKeyFormat: "sk-*",
  },
  {
    key: "custom",
    name: "⚙️ Custom / Local",
    baseUrl: "http://localhost:8000/v1",
    model: "whisper-1",
    description: "Custom OpenAI-compatible endpoint (faster-whisper server, vLLM, dll)",
    signupUrl: "https://github.com/faster-whisper/faster-whisper",
    apiKeyFormat: "optional",
  },
];

export function transcriptionPresetFor(
  baseUrl: string,
  model: string
): TranscriptionPreset {
  const hit = TRANSCRIPTION_PRESETS.find((p) => {
    if (p.key === "custom" || !baseUrl) return false;
    // The local engine is identified by its sentinel, not by host matching —
    // it has no host, and `new URL("local://...").host` is meaningless.
    if (p.local) return baseUrl.trim().toLowerCase().startsWith(p.baseUrl);
    try {
      return (
        baseUrl.includes(new URL(p.baseUrl).host) &&
        (model === p.model || !model)
      );
    } catch {
      return false;
    }
  });
  return hit ?? TRANSCRIPTION_PRESETS[TRANSCRIPTION_PRESETS.length - 1];
}
