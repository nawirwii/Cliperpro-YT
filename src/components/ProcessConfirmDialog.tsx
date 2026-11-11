import { useState, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { X, Film, AlignLeft, Quote, Image as ImageIcon, User, ScanFace, Square, Eye, Sparkles, Zap, MonitorPlay, FolderOpen, DownloadCloud, Volume2, Mic, Gamepad2, MoonStar, type LucideIcon } from "lucide-react";
import { open } from "@tauri-apps/plugin-dialog";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Card } from "@/components/ui/card";
import { useConfigStore } from "@/stores/configStore";
import { listHookFonts, readFontAsBase64, type FontInfo } from "@/hooks/appConfig";
import type { ReframeMode, CenteredBackground, DownloadQuality } from "@/hooks/processClips";

export type { ProcessOptions } from "@/hooks/processClips";
import type { ProcessOptions } from "@/hooks/processClips";
import { STYLE_PRESETS, STYLE_PRESET_STORAGE_KEY, getStylePreset, type StylePreset } from "@/config/stylePresets";

const QUALITY_OPTIONS: { value: DownloadQuality; label: string; badge: string; badgeClass: string; note: string }[] = [
  {
    value: "1080p",
    label: "1080p",
    badge: "Best Quality",
    badgeClass: "bg-[var(--color-success-bg)] text-[var(--color-success)]",
    note: "Largest file — slow on slow internet",
  },
  {
    value: "720p",
    label: "720p",
    badge: "Recommended",
    badgeClass: "bg-[var(--color-warning-bg)] text-[var(--color-warning)]",
    note: "Balanced — ~50% smaller",
  },
  {
    value: "480p",
    label: "480p",
    badge: "Small",
    badgeClass: "bg-[var(--color-success-bg)] text-[var(--color-success)]",
    note: "~75% smaller — phone-quality OK",
  },
  {
    value: "360p",
    label: "360p",
    badge: "Smallest",
    badgeClass: "bg-[var(--color-success-bg)] text-[var(--color-success)]",
    note: "~85% smaller — fastest, for slow links",
  },
  {
    value: "240p",
    label: "240p",
    badge: "Tiniest",
    badgeClass: "bg-[var(--color-success-bg)] text-[var(--color-success)]",
    note: "~90% smaller — ~200MB & below, softest image",
  },
];

const SAMPLE_IMAGES: Record<ReframeMode, string> = {
  face: "/sample-face-tracking.png",
  centered: "/sample-centered-black.png",
};

const SAMPLE_LABELS: Record<ReframeMode, string> = {
  face: "Face Tracking",
  centered: "Centered (Black bars)",
};

const BG_SAMPLE_IMAGES: Record<CenteredBackground, string> = {
  black: "/sample-centered-black.png",
  blurred: "/sample-centered-blur.png",
};

const BG_SAMPLE_LABELS: Record<CenteredBackground, string> = {
  black: "Black bars",
  blurred: "Blurred",
};

interface ProcessConfirmDialogProps {
  clipCount: number;
  /** Whether the source video has an original subtitle track usable for captions. */
  captionsAvailable?: boolean;
  onConfirm: (options: ProcessOptions) => void;
  onCancel: () => void;
}

/** Caption presets intentionally mirror the renderer's supported style names. */
export const CAPTION_STYLES = [
  "Creator Pop", "Kinetic White", "Midnight Neon", "Editorial Mono", "Punchy Red",
  "Soft Mint", "Karaoke Gold", "Comic Burst", "Minimal Center", "News Alert",
];

export const HOOK_STYLES = [
  "Bold Yellow Brush", "Viral Creator", "Clean White Box", "Pop Comic", "Minimal Kinetic",
  "Red Alert", "Neon Digital", "Cinematic Title", "Highlight Marker", "Photo Story Hook",
];

const STYLE_SWATCHES: Record<string, string> = {
  "Bold Yellow Brush": "#FFD93D", "Viral Creator": "#FF6B6B", "Clean White Box": "#FFFFFF",
  "Pop Comic": "#B8F2E6", "Minimal Kinetic": "#111827", "Red Alert": "#EF4444",
  "Neon Digital": "#A3FF12", "Cinematic Title": "#D4AF37", "Highlight Marker": "#FDE047",
  "Photo Story Hook": "#60A5FA", "Creator Pop": "#55FFFF", "Kinetic White": "#FFFFFF",
  "Midnight Neon": "#FF66FF", "Editorial Mono": "#D6FF5C", "Punchy Red": "#FF6600",
  "Soft Mint": "#B6FFAA", "Karaoke Gold": "#FFD700", "Comic Burst": "#FF6B6B",
  "Minimal Center": "#E5E7EB", "News Alert": "#EF4444",
};

function StyleChoice({ name, selected, onClick }: { name: string; selected: boolean; onClick: () => void }) {
  return <button type="button" onClick={onClick} aria-pressed={selected}
    className={`flex items-center gap-2 px-2 py-2 rounded-[var(--radius-sm)] border text-[10px] font-medium text-left transition-colors ${selected ? "border-[var(--color-accent)] bg-[var(--color-bg-primary)] text-[var(--color-accent)]" : "border-transparent bg-[var(--color-bg-primary)] text-[var(--color-text-muted)] hover:border-[var(--color-border-light)]"}`}>
    <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: STYLE_SWATCHES[name] ?? "#888" }} />{name}
  </button>;
}

const PRESET_ICONS: Record<string, LucideIcon> = {
  podcast: Mic,
  gaming: Gamepad2,
  ceramah: MoonStar,
};

/** File name (with extension) from a Windows or POSIX path; "" stays "". */
function fileNameOf(path: string): string {
  return path.split(/[\\/]/).pop() ?? "";
}

export function ProcessConfirmDialog({ clipCount, captionsAvailable = true, onConfirm, onCancel }: ProcessConfirmDialogProps) {
  const { config, setProcessDialog } = useConfigStore();

  // v2.0.136: every choice restores from the last-used values saved in the
  // app config, so the dialog reopens exactly as it was left — even after
  // the app is closed and reopened. The four settings-page-backed fields
  // (intro/outro, watermark, credit) still seed from their settings
  // sections, and are written back there on change (see the save effect).
  const [addCaptions, setAddCaptions] = useState(config.processDialog.addCaptions);
  const [addHook, setAddHook] = useState(config.processDialog.addHook);
  const [addIntroOutro, setAddIntroOutro] = useState(config.introOutro.enabled);
  const [introPath, setIntroPath] = useState<string | null>(config.processDialog.introPath);
  const [outroPath, setOutroPath] = useState<string | null>(config.processDialog.outroPath);
  const [crossfadeDuration, setCrossfadeDuration] = useState(config.processDialog.crossfadeDuration);
  const [addWatermark, setAddWatermark] = useState(config.watermark.enabled);
  const [addCreditWatermark, setAddCreditWatermark] = useState(config.creditWatermark.enabled);
  const [creditText, setCreditText] = useState(config.creditWatermark.text);
  const [reframeMode, setReframeMode] = useState<ReframeMode>(config.processDialog.reframeMode);
  const [captionStyle, setCaptionStyle] = useState(config.processDialog.captionStyle);

  const [hookStyle, setHookStyle] = useState(config.processDialog.hookStyle);
  // v2.0.138: the hook font can be picked here too, not only on the Hook
  // Style settings page. Empty saved pick = follow the settings font.
  const [hookFontName, setHookFontName] = useState(config.processDialog.hookFontName || config.hookStyle.fontName);
  const [hookFontPath, setHookFontPath] = useState(config.processDialog.hookFontPath || config.hookStyle.fontPath);
  const [hookFonts, setHookFonts] = useState<FontInfo[]>([]);
  const [hookFontDataUrl, setHookFontDataUrl] = useState<string | null>(null);
  const [centeredBackground, setCenteredBackground] = useState<CenteredBackground>(config.processDialog.centeredBackground);
  const [downloadQuality, setDownloadQuality] = useState<DownloadQuality>(config.processDialog.downloadQuality);
  const [splitEnabled, setSplitEnabled] = useState(config.processDialog.splitEnabled);
  const [splitWebcamPath, setSplitWebcamPath] = useState(config.processDialog.splitWebcamPath);
  const [splitWebcamName, setSplitWebcamName] = useState(() => fileNameOf(config.processDialog.splitWebcamPath));
  const [splitMainVolume, setSplitMainVolume] = useState(config.processDialog.splitMainVolume);
  const [splitSecondVolume, setSplitSecondVolume] = useState(config.processDialog.splitSecondVolume);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const [activePreset, setActivePreset] = useState<string | null>(null);

  // Latest file picks, so the mount-time existence check below only clears
  // a pick the user has not already replaced by the time it resolves.
  const latestPathsRef = useRef({ intro: introPath, outro: outroPath, webcam: splitWebcamPath });
  latestPathsRef.current = { intro: introPath, outro: outroPath, webcam: splitWebcamPath };

  // Drop persisted file picks whose files no longer exist (moved/deleted),
  // so the dialog never shows a stale file name after a restart. A failed
  // probe keeps the saved path — never delete the user's pick on an error.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const checks: {
        path: string | null;
        clear: () => void;
        isCurrent: () => boolean;
      }[] = [
        {
          path: introPath,
          clear: () => setIntroPath(null),
          isCurrent: () => latestPathsRef.current.intro === introPath,
        },
        {
          path: outroPath,
          clear: () => setOutroPath(null),
          isCurrent: () => latestPathsRef.current.outro === outroPath,
        },
        {
          path: splitWebcamPath || null,
          clear: () => {
            setSplitWebcamPath("");
            setSplitWebcamName("");
          },
          isCurrent: () => latestPathsRef.current.webcam === splitWebcamPath,
        },
      ];
      for (const { path, clear, isCurrent } of checks) {
        if (!path) continue;
        try {
          const exists = await invoke<boolean>("path_exists", { path });
          if (!exists && !cancelled && isCurrent()) clear();
        } catch {
          /* probe failed — keep the saved path */
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // Runs once on mount, validating the restored picks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // v2.0.138: load the bundled hook fonts and resolve the restored pick
  // against the real list. A saved font that no longer ships (e.g. the
  // removed Capo Sfogliato) falls back to the settings font, then to the
  // first bundled font — the dialog never offers a font that renders boxes.
  useEffect(() => {
    let cancelled = false;
    listHookFonts()
      .then((result) => {
        if (cancelled) return;
        setHookFonts(result);
        if (result.length === 0) return;
        const seeded = hookFontName;
        const found = result.find((f) => f.name === seeded);
        const settingsFont = result.find((f) => f.name === config.hookStyle.fontName);
        const pick = found || settingsFont || result[0];
        if (pick.name !== seeded || pick.path !== hookFontPath) {
          setHookFontName(pick.name);
          setHookFontPath(pick.path);
        }
      })
      .catch(() => {
        /* list failed — keep the seeded pick; the backend falls back */
      });
    return () => {
      cancelled = true;
    };
    // Runs once on mount; the bundled font list is fixed per install.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load the picked font as a data URL so the preview line below renders
  // in the actual font.
  useEffect(() => {
    if (!hookFontPath) {
      setHookFontDataUrl(null);
      return;
    }
    let cancelled = false;
    readFontAsBase64(hookFontPath)
      .then((url) => {
        if (!cancelled) setHookFontDataUrl(url);
      })
      .catch(() => {
        if (!cancelled) setHookFontDataUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [hookFontPath]);

  const handleHookFontSelect = (name: string) => {
    const found = hookFonts.find((f) => f.name === name);
    if (!found) return;
    setHookFontName(found.name);
    setHookFontPath(found.path);
    setActivePreset(null);
  };

  // Persist every dialog choice on change (no debounce: the write is one
  // tiny local JSON file, and a debounced write could still be pending when
  // the user closes the app). The first run is skipped so merely opening
  // the dialog does not rewrite the config.
  const firstSave = useRef(true);
  useEffect(() => {
    if (firstSave.current) {
      firstSave.current = false;
      return;
    }
    setProcessDialog(
      {
        addCaptions,
        addHook,
        introPath,
        outroPath,
        crossfadeDuration,
        reframeMode,
        captionStyle,
        hookStyle,
        hookFontName,
        hookFontPath,
        centeredBackground,
        downloadQuality,
        splitEnabled,
        splitWebcamPath,
        splitMainVolume,
        splitSecondVolume,
      },
      { addIntroOutro, addWatermark, addCreditWatermark, creditText }
    ).catch(() => {
      /* saving is best-effort — the dialog still works this session */
    });
  }, [
    addCaptions,
    addHook,
    addIntroOutro,
    introPath,
    outroPath,
    crossfadeDuration,
    addWatermark,
    addCreditWatermark,
    creditText,
    reframeMode,
    captionStyle,
    hookStyle,
    hookFontName,
    hookFontPath,
    centeredBackground,
    downloadQuality,
    splitEnabled,
    splitWebcamPath,
    splitMainVolume,
    splitSecondVolume,
    setProcessDialog,
  ]);

  const handlePickWebcam = async () => {
    try {
      const selected = await open({
        multiple: false,
        filters: [
          { name: "Video", extensions: ["mp4", "mov", "mkv", "webm", "avi", "m4v"] },
          { name: "All files", extensions: ["*"] },
        ],
      });
      if (typeof selected === "string" && selected) {
        setSplitWebcamPath(selected);
        setSplitWebcamName(fileNameOf(selected));
      }
    } catch (err) {
      console.error("Failed to pick video", err);
    }
  };

  const handlePickIntro = async () => {
    try {
      const selected = await open({
        multiple: false,
        filters: [
          { name: "Video", extensions: ["mp4", "mov", "mkv", "webm", "avi", "m4v"] },
          { name: "All files", extensions: ["*"] },
        ],
      });
      if (typeof selected === "string" && selected) {
        setIntroPath(selected);
      }
    } catch (err) {
      console.error("Failed to pick intro video", err);
    }
  };

  const handlePickOutro = async () => {
    try {
      const selected = await open({
        multiple: false,
        filters: [
          { name: "Video", extensions: ["mp4", "mov", "mkv", "webm", "avi", "m4v"] },
          { name: "All files", extensions: ["*"] },
        ],
      });
      if (typeof selected === "string" && selected) {
        setOutroPath(selected);
      }
    } catch (err) {
      console.error("Failed to pick outro video", err);
    }
  };

  const applyPreset = (preset: StylePreset) => {
    const o = preset.options;
    setAddCaptions(o.addCaptions);
    setAddHook(o.addHook);
    setAddWatermark(o.addWatermark);
    setAddCreditWatermark(o.addCreditWatermark);
    setCaptionStyle(o.captionStyle);
    setHookStyle(o.hookStyle || "Clean White Box");
    setReframeMode(o.reframeMode);
    setCenteredBackground(o.centeredBackground);
    setDownloadQuality(o.downloadQuality);
    setActivePreset(preset.id);
    try {
      localStorage.setItem(STYLE_PRESET_STORAGE_KEY, preset.id);
    } catch {
      /* storage unavailable — preset still applies for this session */
    }
  };

  // Auto-apply the last used preset when the dialog opens, so the style
  // doesn't have to be re-picked for every video.
  useEffect(() => {
    try {
      const preset = getStylePreset(localStorage.getItem(STYLE_PRESET_STORAGE_KEY));
      if (preset) applyPreset(preset);
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Trap Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (previewSrc) setPreviewSrc(null);
        else onCancel();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCancel, previewSrc]);

  const handleConfirm = () => {
    onConfirm({
      addCaptions: addCaptions && captionsAvailable,
      addHook,
      addIntroOutro: addIntroOutro && (introPath !== null || outroPath !== null),
      introPath: introPath || undefined,
      outroPath: outroPath || undefined,
      crossfadeDuration,
      addWatermark,
      addCreditWatermark,
      creditText: addCreditWatermark ? creditText : undefined,
      captionStyle,

      hookStyle,
      hookFontName,
      hookFontPath,
      reframeMode,
      centeredBackground,
      downloadQuality,
      splitScreen: {
        enabled: splitEnabled && !!splitWebcamPath,
        webcamPath: splitWebcamPath,
        topRatio: 0.8,
        mainVolume: splitMainVolume / 100,
        secondVolume: splitSecondVolume / 100,
      },
    });
  };

  const currentPreviewSrc = reframeMode === "centered"
    ? BG_SAMPLE_IMAGES[centeredBackground]
    : SAMPLE_IMAGES[reframeMode];
  const currentPreviewLabel = reframeMode === "centered"
    ? `${BG_SAMPLE_LABELS[centeredBackground]} background`
    : SAMPLE_LABELS[reframeMode];

  const options: {
    key: keyof ProcessOptions;
    label: string;
    description: string;
    icon: React.ReactNode;
    enabled: boolean;
    onToggle: (v: boolean) => void;
    disabled?: boolean;
  }[] = [
    {
      key: "addCaptions",
      label: "Captions",
      description: captionsAvailable
        ? "Word-by-word captions from the original YouTube subtitle track"
        : "Unavailable — this video has no original subtitle track",
      icon: <AlignLeft className="w-5 h-5 text-[var(--color-accent)]" />,
      enabled: addCaptions && captionsAvailable,
      onToggle: (v: boolean) => { setAddCaptions(v); setActivePreset(null); },
      disabled: !captionsAvailable,
    },
    {
      key: "addHook",
      label: "Hook Text",
      description: "AI-generated hook shown over the opening seconds",
      icon: <Quote className="w-5 h-5 text-[var(--color-accent)]" />,
      enabled: addHook,
      onToggle: (v: boolean) => { setAddHook(v); setActivePreset(null); },
    },
    {
      key: "addWatermark",
      label: "Logo Watermark",
      description: "Overlay a logo image on each clip",
      icon: <ImageIcon className="w-5 h-5 text-[var(--color-accent)]" />,
      enabled: addWatermark,
      onToggle: (v: boolean) => { setAddWatermark(v); setActivePreset(null); },
    },
    {
      key: "addIntroOutro",
      label: "Intro & Outro",
      description: "Prepend intro & append outro videos with 0.9s cross-fade",
      icon: <Film className="w-5 h-5 text-[var(--color-accent)]" />,
      enabled: addIntroOutro,
      onToggle: (v: boolean) => { setAddIntroOutro(v); setActivePreset(null); },
    },
    {
      key: "addCreditWatermark",
      label: "Credit Text",
      description: "Source channel credit overlay",
      icon: <User className="w-5 h-5 text-[var(--color-accent)]" />,
      enabled: addCreditWatermark,
      onToggle: setAddCreditWatermark,
    },
  ];

  return (
    <>
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
        onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
      >
        <Card className="w-full max-w-md mx-4 p-0 overflow-hidden shadow-[var(--shadow-lg)] max-h-[90vh] overflow-y-auto">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border-light)] sticky top-0 bg-[var(--color-bg-primary)] z-10">
            <div className="flex items-center gap-2">
              <Film className="w-5 h-5 text-[var(--color-accent)]" />
              <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">
                Process Clips
              </h2>
            </div>
            <Button variant="ghost" size="icon" onClick={onCancel} className="h-8 w-8">
              <X className="w-4 h-4" />
            </Button>
          </div>

          {/* Body */}
          <div className="px-5 py-4 space-y-4">
            <p className="text-sm text-[var(--color-text-secondary)]">
              Processing <span className="font-semibold text-[var(--color-text-primary)]">{clipCount}</span> clip{clipCount !== 1 ? "s" : ""}. 
              Choose which enhancements to apply:
            </p>

            {/* Style presets — one click applies caption style, reframe mode, watermark toggles & quality */}
            <div className="space-y-2">
              <p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">
                Style Preset
              </p>
              <div className="grid grid-cols-3 gap-2">
                {STYLE_PRESETS.map((preset) => {
                  const Icon = PRESET_ICONS[preset.id] ?? Sparkles;
                  const active = activePreset === preset.id;
                  return (
                    <button
                      key={preset.id}
                      onClick={() => applyPreset(preset)}
                      className={`flex flex-col items-center gap-1 p-3 rounded-[var(--radius-sm)] border text-center transition-colors ${
                        active
                          ? "border-[var(--color-accent)] bg-[var(--color-bg-secondary)]"
                          : "border-transparent bg-[var(--color-bg-secondary)] hover:border-[var(--color-border-light)]"
                      }`}
                    >
                      <Icon className="w-5 h-5 text-[var(--color-accent)]" />
                      <p className="text-sm font-medium text-[var(--color-text-primary)]">{preset.name}</p>
                      <p className="text-[10px] text-[var(--color-text-muted)] leading-tight">{preset.tagline}</p>
                    </button>
                  );
                })}
              </div>
              <p className="text-[10px] text-[var(--color-text-muted)] italic">
                One click applies the full style. Your last preset is applied automatically next time.
              </p>
            </div>

            {/* Download quality selector */}
            <div className="space-y-2">
              <div className="flex items-center gap-1.5">
                <DownloadCloud className="w-4 h-4 text-[var(--color-accent)]" />
                <p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">
                  Source Video Quality
                </p>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {QUALITY_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => { setDownloadQuality(opt.value); setActivePreset(null); }}
                    className={`relative flex flex-col items-center gap-1 p-2.5 rounded-[var(--radius-sm)] border text-center transition-colors ${
                      downloadQuality === opt.value
                        ? "border-[var(--color-accent)] bg-[var(--color-bg-secondary)]"
                        : "border-transparent bg-[var(--color-bg-secondary)] hover:border-[var(--color-border-light)]"
                    }`}
                  >
                    <span className="text-sm font-semibold text-[var(--color-text-primary)]">{opt.label}</span>
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${opt.badgeClass}`}>{opt.badge}</span>
                    <span className="text-[10px] text-[var(--color-text-muted)] leading-tight">{opt.note}</span>
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-[var(--color-text-muted)] italic">
                Lower quality = smaller file &amp; faster download. 720p is sharp enough for Shorts.
              </p>
            </div>

            {/* Reframe mode selector */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">
                  Reframe Mode
                </p>
                <button
                  onClick={() => setPreviewSrc(currentPreviewSrc)}
                  className="flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline"
                >
                  <Eye className="w-3.5 h-3.5" />
                  View example
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => { setReframeMode("face"); setActivePreset(null); }}
                  className={`relative flex flex-col gap-1.5 p-3 rounded-[var(--radius-sm)] border text-left transition-colors ${
                    reframeMode === "face"
                      ? "border-[var(--color-accent)] bg-[var(--color-bg-secondary)]"
                      : "border-transparent bg-[var(--color-bg-secondary)] hover:border-[var(--color-border-light)]"
                  }`}
                >
                  <span className="absolute top-1.5 right-1.5 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-[var(--color-success-bg)] text-[var(--color-success)] text-[10px] font-semibold">
                    <Sparkles className="w-2.5 h-2.5" />
                    Better Result
                  </span>
                  <ScanFace className="w-5 h-5 text-[var(--color-accent)]" />
                  <p className="text-sm font-medium text-[var(--color-text-primary)]">Face Tracking</p>
                  <p className="text-xs text-[var(--color-text-muted)]">AI tracks the speaker — slower</p>
                </button>
                <button
                  onClick={() => { setReframeMode("centered"); setActivePreset(null); }}
                  className={`relative flex flex-col gap-1.5 p-3 rounded-[var(--radius-sm)] border text-left transition-colors ${
                    reframeMode === "centered"
                      ? "border-[var(--color-accent)] bg-[var(--color-bg-secondary)]"
                      : "border-transparent bg-[var(--color-bg-secondary)] hover:border-[var(--color-border-light)]"
                  }`}
                >
                  <span className="absolute top-1.5 right-1.5 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-[var(--color-warning-bg)] text-[var(--color-warning)] text-[10px] font-semibold">
                    <Zap className="w-2.5 h-2.5" />
                    13x Faster
                  </span>
                  <Square className="w-5 h-5 text-[var(--color-accent)]" />
                  <p className="text-sm font-medium text-[var(--color-text-primary)]">Centered</p>
                  <p className="text-xs text-[var(--color-text-muted)]">Video centered in frame — much faster</p>
                </button>
              </div>
            </div>

            {/* Background sub-selector (centered mode only) */}
            {reframeMode === "centered" && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">
                  Background
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => { setCenteredBackground("black"); setActivePreset(null); }}
                    className={`flex items-center gap-2 p-2.5 rounded-[var(--radius-sm)] border text-left transition-colors ${
                      centeredBackground === "black"
                        ? "border-[var(--color-accent)] bg-[var(--color-bg-secondary)]"
                        : "border-transparent bg-[var(--color-bg-secondary)] hover:border-[var(--color-border-light)]"
                    }`}
                  >
                    <span className="w-4 h-4 rounded-sm bg-black border border-[var(--color-border-light)] shrink-0" />
                    <span className="text-sm text-[var(--color-text-primary)]">Black bars</span>
                  </button>
                  <button
                    onClick={() => { setCenteredBackground("blurred"); setActivePreset(null); }}
                    className={`flex items-center gap-2 p-2.5 rounded-[var(--radius-sm)] border text-left transition-colors ${
                      centeredBackground === "blurred"
                        ? "border-[var(--color-accent)] bg-[var(--color-bg-secondary)]"
                        : "border-transparent bg-[var(--color-bg-secondary)] hover:border-[var(--color-border-light)]"
                    }`}
                  >
                    <span className="w-4 h-4 rounded-sm bg-gradient-to-br from-[var(--color-accent)]/30 to-[var(--color-accent)]/60 shrink-0" />
                    <span className="text-sm text-[var(--color-text-primary)]">Blurred</span>
                  </button>
                </div>
                <button
                  onClick={() => setPreviewSrc(BG_SAMPLE_IMAGES[centeredBackground])}
                  className="flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline"
                >
                  <Eye className="w-3.5 h-3.5" />
                  Preview {BG_SAMPLE_LABELS[centeredBackground]}
                </button>
              </div>
            )}

            {/* Split screen mode */}
            <div className="flex items-center justify-between gap-3 p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)]">
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <MonitorPlay className="w-5 h-5 text-[var(--color-accent)] shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-[var(--color-text-primary)]">Split Screen</p>
                  <p className="text-xs text-[var(--color-text-muted)] truncate">
                                        Split-screen: portrait top (source) and portrait bottom (webcam) 50% each, face‑tracked
                                      </p>
                </div>
              </div>
              <Switch checked={splitEnabled} onCheckedChange={setSplitEnabled} />
            </div>

            {splitEnabled && (
              <div className="p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)] space-y-3">
                <p className="text-[10px] text-[var(--color-text-muted)] italic leading-relaxed">
                  Main video (top) is auto-reframed to portrait with face tracking (80%);
                  your video fills the bottom strip in landscape (20%).
                </p>
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs text-[var(--color-text-muted)]">Bottom video (webcam / narasumber)</p>
                </div>
                <Button variant="outline" onClick={handlePickWebcam} className="w-full gap-2 h-9 text-sm">
                  <FolderOpen className="w-4 h-4" />
                  {splitWebcamName ? "Replace video" : "Choose local video"}
                </Button>
                {splitWebcamName && (
                  <p className="text-xs text-[var(--color-text-muted)] truncate">{splitWebcamName}</p>
                )}
                {!splitWebcamPath && (
                  <p className="text-xs text-[var(--color-warning)]">
                    Pick a video file — Split Screen only activates when one is chosen.
                  </p>
                )}

                {/* Volume balance sliders */}
                <div className="space-y-3 pt-1 border-t border-[var(--color-border-light)]">
                  <div className="flex items-center gap-2">
                    <Volume2 className="w-4 h-4 text-[var(--color-accent)] shrink-0" />
                    <p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">
                      Volume Balance
                    </p>
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-[var(--color-text-secondary)]">Main video (top)</span>
                      <span className="text-xs text-[var(--color-text-muted)]">{splitMainVolume}%</span>
                    </div>
                    <Slider
                      value={[splitMainVolume]}
                      min={0}
                      max={100}
                      step={5}
                      onValueChange={(v) => setSplitMainVolume(v[0] ?? 100)}
                      aria-label="Main video volume"
                    />
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-[var(--color-text-secondary)]">Webcam (bottom)</span>
                      <span className="text-xs text-[var(--color-text-muted)]">{splitSecondVolume}%</span>
                    </div>
                    <Slider
                      value={[splitSecondVolume]}
                      min={0}
                      max={100}
                      step={5}
                      onValueChange={(v) => setSplitSecondVolume(v[0] ?? 100)}
                      aria-label="Webcam volume"
                    />
                  </div>
                  <p className="text-[10px] text-[var(--color-text-muted)] italic">
                    Adjusts each sound volume before mixing. 100% = original volume.
                  </p>
                </div>
              </div>
            )}

              {/* Credit watermark toggle & text input */}
              <div className="space-y-2">
                <div
                  className="flex items-center justify-between gap-3 p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)]"
                >
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <User className="w-5 h-5 text-[var(--color-accent)] shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-[var(--color-text-primary)]">
                        Credit Text
                      </p>
                      <p className="text-xs text-[var(--color-text-muted)] truncate">
                        Source channel credit overlay
                      </p>
                    </div>
                  </div>
                  <Switch checked={addCreditWatermark} onCheckedChange={(v) => { setAddCreditWatermark(v); setActivePreset(null); }} />
                </div>

                {addCreditWatermark && (
                  <div className="space-y-1">
                    <input
                      value={creditText}
                      onChange={(e) => setCreditText(e.target.value)}
                      className="w-full px-3 py-2 text-sm bg-[var(--color-bg-secondary)] rounded-[var(--radius-sm)] border border-[var(--color-border-light)] focus:outline-none focus:border-[var(--color-accent)]"
                      placeholder="e.g. Source: {channel}"
                    />
                    <p className="text-xs text-[var(--color-text-muted)]">
                      Size: <strong>{config.creditWatermark.fontSize}px</strong> from Credit Watermark Settings · scaled for final video
                    </p>
                  </div>
                )}

              {/* Intro & Outro selection */}
              {addIntroOutro && (
                <div className="p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)] space-y-3">
                  <div className="flex items-center gap-2"><Film className="w-4 h-4 text-[var(--color-accent)]" /><p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">Intro Video</p></div>
                  <div className="flex gap-2 items-center">
                    <Button variant="outline" onClick={handlePickIntro} className="flex-1 text-sm">
                      <FolderOpen className="w-4 h-4 mr-2" />
                      {introPath ? "Change Intro" : "Pick Intro Video"}
                    </Button>
                    {introPath && (
                      <span className="text-xs text-[var(--color-text-muted)] max-w-[150px] truncate">{introPath.split(/[\\/]/).pop()}</span>
                    )}
                    {introPath && (
                      <Button variant="outline" onClick={() => setIntroPath(null)} className="text-sm" aria-label="Remove intro video">
                        <X className="w-4 h-4 mr-1" />
                        Remove
                      </Button>
                    )}
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-[var(--color-text-secondary)]">Crossfade duration</span>
                      <span className="text-xs text-[var(--color-text-muted)]">{crossfadeDuration.toFixed(1)}s</span>
                    </div>
                    <Slider
                      value={[crossfadeDuration]}
                      min={0.1}
                      max={1}
                      step={0.1}
                      onValueChange={(v) => setCrossfadeDuration(v[0] ?? 0.9)}
                      aria-label="Intro/outro crossfade duration"
                    />
                  </div>
                  <p className="text-[10px] text-[var(--color-text-muted)] italic">{crossfadeDuration.toFixed(1)}s crossfade with main video</p>

                  <div className="flex items-center gap-2"><Film className="w-4 h-4 text-[var(--color-accent)]" /><p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">Outro Video <span className="normal-case tracking-normal">(optional)</span></p></div>
                  <div className="flex gap-2 items-center">
                    <Button variant="outline" onClick={handlePickOutro} className="flex-1 text-sm">
                      <FolderOpen className="w-4 h-4 mr-2" />
                      {outroPath ? "Change Outro" : "Pick Outro Video"}
                    </Button>
                    {outroPath && (
                      <span className="text-xs text-[var(--color-text-muted)] max-w-[150px] truncate">{outroPath.split(/[\\/]/).pop()}</span>
                    )}
                    {outroPath && (
                      <Button variant="outline" onClick={() => setOutroPath(null)} className="text-sm" aria-label="Remove outro video">
                        <X className="w-4 h-4 mr-1" />
                        Remove
                      </Button>
                    )}
                  </div>
                  <p className="text-[10px] text-[var(--color-text-muted)] italic">{crossfadeDuration.toFixed(1)}s crossfade with main video</p>
                </div>
              )}

              {addHook && (
                <div className="p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)] space-y-3">
                  <div className="flex items-center gap-2"><Quote className="w-4 h-4 text-[var(--color-accent)]" /><p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">Hook Visual Style</p></div>
                  <div className="grid grid-cols-2 gap-1.5">{HOOK_STYLES.map((s) => <StyleChoice key={s} name={s} selected={hookStyle === s} onClick={() => { setHookStyle(s); setActivePreset(null); }} />)}</div>
                  {/* v2.0.138: hook font picker (30 bundled fonts, no 3D) */}
                  <div className="space-y-1.5 pt-1">
                    <p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">Hook Font</p>
                    <select
                      value={hookFontName}
                      onChange={(e) => handleHookFontSelect(e.target.value)}
                      className="w-full rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-sm text-[var(--color-text-primary)]"
                    >
                      {hookFonts.map((f) => (
                        <option key={f.path} value={f.name}>{f.name}</option>
                      ))}
                    </select>
                    {hookFontDataUrl && (
                      <>
                        <style>{`
                          @font-face {
                            font-family: "hook-dialog-font";
                            src: url("${hookFontDataUrl}") format("truetype");
                          }
                        `}</style>
                        <p className="text-center text-lg leading-tight text-[var(--color-text-primary)]" style={{ fontFamily: `"hook-dialog-font", ${hookFontName}, sans-serif` }}>
                          HOOK PREVIEW
                        </p>
                      </>
                    )}
                  </div>
                </div>
              )}
              {addCaptions && (
                <div className="p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)] space-y-3">
                  <div className="flex items-center gap-2"><ImageIcon className="w-4 h-4 text-[var(--color-accent)]" /><p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">Caption Style</p></div>
                  <div className="grid grid-cols-2 gap-1.5">{CAPTION_STYLES.map((s) => <StyleChoice key={s} name={s} selected={captionStyle === s} onClick={() => { setCaptionStyle(s); setActivePreset(null); }} />)}</div>

                </div>
              )}
            </div>

            <div className="space-y-2">
              {options.filter(o => o.key !== "addCreditWatermark").map((opt) => (
                <div
                  key={opt.key}
                  className="flex items-center justify-between gap-3 p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)]"
                >
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    {opt.icon}
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-[var(--color-text-primary)]">
                        {opt.label}
                      </p>
                      <p className="text-xs text-[var(--color-text-muted)] truncate">
                        {opt.description}
                      </p>
                    </div>
                  </div>
                  <Switch checked={opt.enabled} onCheckedChange={opt.onToggle} disabled={opt.disabled} />
                </div>
              ))}
            </div>
          </div>

          {/* Footer */}
          <div className="flex gap-3 px-5 py-4 border-t border-[var(--color-border-light)] bg-[var(--color-bg-secondary)] sticky bottom-0">
            <Button variant="outline" onClick={onCancel} className="flex-1">
              Cancel
            </Button>
            <Button onClick={handleConfirm} className="flex-1 gap-2">
              <Film className="w-4 h-4" />
              Process {clipCount} Clip{clipCount !== 1 ? "s" : ""}
            </Button>
          </div>
        </Card>
      </div>

      {/* Preview modal */}
      {previewSrc && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80"
          onClick={(e) => { if (e.target === e.currentTarget) setPreviewSrc(null); }}
        >
          <div className="relative max-w-sm w-full mx-4">
            <button
              onClick={() => setPreviewSrc(null)}
              className="absolute -top-10 right-0 text-white/80 hover:text-white"
            >
              <X className="w-6 h-6" />
            </button>
            <p className="text-center text-sm text-white/80 mb-2 font-medium">
              Example: {currentPreviewLabel}
            </p>
            <img
              src={previewSrc}
              alt={`Example: ${currentPreviewLabel}`}
              className="w-full rounded-[var(--radius-md)] shadow-2xl"
            />
          </div>
        </div>
      )}
    </>
  );
}