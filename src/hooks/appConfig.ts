import { invoke } from "@tauri-apps/api/core";
import type {
  ReframeMode,
  CenteredBackground,
  DownloadQuality,
} from "@/hooks/processClips";

export interface AIProviderSettings {
  baseUrl: string;
  apiKey: string;
  model: string;
  systemMessage?: string;
  /**
   * Optional separate Whisper endpoint used ONLY for transcribing LOCAL
   * video files. When empty, local transcription falls back to the same
   * baseUrl/apiKey/model as chat — which only works if that endpoint
   * implements /audio/transcriptions (OpenAI, Groq, whisper servers).
   */
  transcriptionBaseUrl?: string;
  transcriptionModel?: string;
  transcriptionApiKey?: string;
}

export interface WatermarkSettings {
  enabled: boolean;
  imagePath: string;
  positionX: number;
  positionY: number;
  opacity: number;
  scale: number;
}

export interface CreditWatermarkSettings {
  enabled: boolean;
  text: string;
  color: string;
  fontSize: number;
  opacity: number;
  positionX: number;
  positionY: number;
}

export interface HookStyleSettings {
  fontName: string;
  fontPath: string;
  fontSize: number;
  fontColor: string;
  bgColor: string;
  cornerRadius: number;
  positionX: number;
  positionY: number;
  durationSeconds: number;
}

export interface ReplizSettings {
  accessKey: string;
  secretKey: string;
}

export interface IntroOutroSettings {
  enabled: boolean;
  introPath: string;
  outroPath: string;
}

/**
 * Last-used Process Clips dialog choices (v2.0.136). The dialog restores
 * these when it opens, so its inputs survive an app restart exactly as
 * they were left. The four toggle/text fields that also live in the
 * settings pages (intro/outro enabled, watermark enabled, credit enabled
 * + text) are NOT duplicated here — the dialog writes those straight back
 * into their settings sections, keeping one source of truth.
 */
export interface ProcessDialogSettings {
  addCaptions: boolean;
  addHook: boolean;
  /** Per-render intro pick (NOT the settings-page default file). */
  introPath: string | null;
  /** Per-render outro pick (NOT the settings-page default file). */
  outroPath: string | null;
  crossfadeDuration: number;
  reframeMode: ReframeMode;
  captionStyle: string;
  hookStyle: string;
  /** Hook font picked in the dialog (name + bundled path). Empty = follow
      the font chosen on the Hook Style settings page. */
  hookFontName: string;
  hookFontPath: string;
  centeredBackground: CenteredBackground;
  downloadQuality: DownloadQuality;
  splitEnabled: boolean;
  /** Absolute path to the bottom (webcam / narasumber) video. */
  splitWebcamPath: string;
  splitMainVolume: number;
  splitSecondVolume: number;
}

export interface AppConfig {
  /** Single AI provider shared by highlight finding and title generation. */
  ai: AIProviderSettings;
  gpuAcceleration: {
    enabled: boolean;
    /** FFmpeg hardware encoder name (e.g. h264_qsv), saved when enabled. */
    encoder?: string | null;
    /** Encoder preset (e.g. "faster"), saved when enabled. */
    preset?: string | null;
  };
  watermark: WatermarkSettings;
  creditWatermark: CreditWatermarkSettings;
  hookStyle: HookStyleSettings;
  introOutro: IntroOutroSettings;
  repliz: ReplizSettings;
  /** Last-used Process Clips dialog choices (see ProcessDialogSettings). */
  processDialog: ProcessDialogSettings;
  /** Stable per-install UUID, generated on first run. Persists across updates. */
  installationId: string;
}

export const DEFAULT_CONFIG: AppConfig = {
  ai: {
    baseUrl: "https://ai-api.ytclip.org/v1",
    apiKey: "",
    model: "",
    systemMessage: "",
    transcriptionBaseUrl: "",
    transcriptionModel: "",
    transcriptionApiKey: "",
  },
  gpuAcceleration: {
    enabled: false,
    encoder: null,
    preset: null,
  },
  watermark: {
    enabled: false,
    imagePath: "",
    positionX: 0.85,
    positionY: 0.05,
    opacity: 0.8,
    scale: 0.15,
  },
  creditWatermark: {
    enabled: false,
    text: "Source: {channel}",
    color: "#FFFFFF",
    fontSize: 20,
    opacity: 0.7,
    positionX: 0.5,
    positionY: 0.3,
  },
  hookStyle: {
    fontName: "Arial",
    fontPath: "",
    fontSize: 0.054,
    fontColor: "#FFD700",
    bgColor: "#FFFFFF",
    cornerRadius: 0,
    positionX: 0.5,
    positionY: 0.333,
    durationSeconds: 5,
  },
  introOutro: {
    enabled: false,
    introPath: "",
    outroPath: "",
  },
  repliz: {
    accessKey: "",
    secretKey: "",
  },
  processDialog: {
    addCaptions: true,
    addHook: true,
    introPath: null,
    outroPath: null,
    crossfadeDuration: 0.9,
    reframeMode: "face",
    captionStyle: "Creator Pop",
    hookStyle: "Clean White Box",
    hookFontName: "",
    hookFontPath: "",
    centeredBackground: "black",
    downloadQuality: "720p",
    splitEnabled: false,
    splitWebcamPath: "",
    splitMainVolume: 100,
    splitSecondVolume: 100,
  },
  installationId: "",
};

export async function loadAppConfig(): Promise<AppConfig> {
  const config = await invoke<Partial<AppConfig>>("load_app_config");
  return mergeConfig(config);
}

export async function saveAppConfig(config: AppConfig): Promise<AppConfig> {
  const saved = await invoke<Partial<AppConfig>>("save_app_config", { config });
  return mergeConfig(saved);
}

export async function listAIModels(apiKey: string, baseUrl: string): Promise<string[]> {
  return invoke<string[]>("list_ai_models", { apiKey, baseUrl });
}

export interface GpuInfo {
  type: string | null;
  name: string;
  available: boolean;
}

export interface GpuEncoder {
  name: string | null;
  preset: string | null;
  available: boolean;
  reason: string;
}

export interface GpuDetection {
  gpu: GpuInfo;
  encoder: GpuEncoder;
}

export async function detectGpu(): Promise<GpuDetection> {
  return invoke<GpuDetection>("detect_gpu");
}

export interface FontInfo {
  name: string;
  path: string;
}

export async function listHookFonts(): Promise<FontInfo[]> {
  return invoke<FontInfo[]>("list_hook_fonts");
}

export async function readFontAsBase64(path: string): Promise<string> {
  return invoke<string>("read_file_as_base64", { path });
}

export interface SavedWatermark {
  path: string;
  dataUrl: string;
}

export async function saveWatermark(
  fileName: string,
  bytes: Uint8Array
): Promise<SavedWatermark> {
  return invoke<SavedWatermark>("save_watermark", {
    fileName,
    bytes: Array.from(bytes),
  });
}

export async function readWatermark(path: string): Promise<string> {
  return invoke<string>("read_watermark", { path });
}

export interface SavedIntroOutro {
  path: string;
}

export async function saveIntroOutro(
  fileName: string,
  bytes: Uint8Array
): Promise<SavedIntroOutro> {
  return invoke<SavedIntroOutro>("save_intro_outro", {
    fileName,
    bytes: Array.from(bytes),
  });
}

function mergeConfig(config: Partial<AppConfig> | undefined): AppConfig {
  // Migrate from the legacy per-task shape (aiProviders.highlightFinder) so
  // users who already configured a key don't have to re-enter it.
  const legacyAi = (config as { aiProviders?: { highlightFinder?: Partial<AIProviderSettings> } } | undefined)
    ?.aiProviders?.highlightFinder;
  return {
    ai: {
      ...DEFAULT_CONFIG.ai,
      ...legacyAi,
      ...config?.ai,
    },
    gpuAcceleration: {
      ...DEFAULT_CONFIG.gpuAcceleration,
      ...config?.gpuAcceleration,
    },
    watermark: {
      ...DEFAULT_CONFIG.watermark,
      ...config?.watermark,
    },
    creditWatermark: (() => {
      const cw = {
        ...DEFAULT_CONFIG.creditWatermark,
        ...config?.creditWatermark,
      };
      // Migrate configs saved before v2.0.99: position used to anchor the
      // TOP-LEFT corner of the credit text; since v2.0.99 it anchors the
      // CENTER of the text.
      // - legacy default x=0.03 as a center point pushes the text off the
      //   left edge of the frame → reset to 0.5.
      // - old default y=0.72 was previously migrated to y=0.3. The credit
      //   now intentionally belongs in the lower-third area requested by the
      //   user, so migrate that old upper-third default back down.
      if (cw.positionX === 0.03 && cw.positionY === 0.72) {
        cw.positionX = 0.5;
        cw.positionY = 0.3;
      } else if (cw.positionX === 0.03) {
        cw.positionX = 0.5;
      }

      return cw;
    })(),
    hookStyle: {
      ...DEFAULT_CONFIG.hookStyle,
      ...config?.hookStyle,
    },
    introOutro: {
      ...DEFAULT_CONFIG.introOutro,
      ...config?.introOutro,
    },
    repliz: {
      ...DEFAULT_CONFIG.repliz,
      ...config?.repliz,
    },
    processDialog: (() => {
      const pd = {
        ...DEFAULT_CONFIG.processDialog,
        ...config?.processDialog,
      };
      // Guard the numeric fields against hand-edited or stale values so a
      // bad number can never leave the dialog in an unusable state.
      pd.crossfadeDuration = clampNumber(pd.crossfadeDuration, 0.1, 1.0, 0.9);
      pd.splitMainVolume = clampNumber(pd.splitMainVolume, 0, 100, 100);
      pd.splitSecondVolume = clampNumber(pd.splitSecondVolume, 0, 100, 100);
      return pd;
    })(),
    installationId: config?.installationId ?? DEFAULT_CONFIG.installationId,
  };
}

/** Non-numeric or out-of-range input falls back to `fallback`. */
function clampNumber(
  value: unknown,
  min: number,
  max: number,
  fallback: number
): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(max, Math.max(min, value))
    : fallback;
}
