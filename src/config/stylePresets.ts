import type {
  CenteredBackground,
  DownloadQuality,
  ReframeMode,
} from "@/hooks/processClips";

/**
 * The per-job options a style preset controls. These mirror the fields of
 * ProcessOptions shown in the Process Clips dialog, minus anything that
 * needs a per-video file pick (split-screen webcam video).
 */
export interface StylePresetOptions {
  addCaptions: boolean;
  addHook: boolean;
  addWatermark: boolean;
  addCreditWatermark: boolean;
  captionStyle: string;
  reframeMode: ReframeMode;
  centeredBackground: CenteredBackground;
  downloadQuality: DownloadQuality;
}

export interface StylePreset {
  id: string;
  name: string;
  tagline: string;
  options: StylePresetOptions;
}

/** localStorage key remembering the last used preset. */
export const STYLE_PRESET_STORAGE_KEY = "clipperpro:style-preset";

export const STYLE_PRESETS: StylePreset[] = [
  {
    id: "podcast",
    name: "Podcast",
    tagline: "Speaker focus, clean captions",
    options: {
      addCaptions: true,
      addHook: true,
      addWatermark: true,
      addCreditWatermark: true,
      captionStyle: "Boxed White",
      reframeMode: "face",
      centeredBackground: "black",
      downloadQuality: "720p",
    },
  },
  {
    id: "gaming",
    name: "Gaming",
    tagline: "Fast & punchy for gameplay",
    options: {
      addCaptions: true,
      addHook: true,
      addWatermark: true,
      addCreditWatermark: true,
      captionStyle: "Neon Green",
      reframeMode: "centered",
      centeredBackground: "blurred",
      downloadQuality: "720p",
    },
  },
  {
    id: "ceramah",
    name: "Ceramah",
    tagline: "Elegant for sermons & talks",
    options: {
      addCaptions: true,
      addHook: true,
      addWatermark: true,
      addCreditWatermark: true,
      captionStyle: "Gold Outline",
      reframeMode: "face",
      centeredBackground: "black",
      downloadQuality: "720p",
    },
  },
];

export function getStylePreset(
  id: string | null | undefined
): StylePreset | undefined {
  if (!id) return undefined;
  return STYLE_PRESETS.find((p) => p.id === id);
}
