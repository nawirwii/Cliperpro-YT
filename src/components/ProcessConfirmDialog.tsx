import { useState, useEffect } from "react";
import { X, Film, AlignLeft, Quote, Image as ImageIcon, User, ScanFace, Square, Eye, Sparkles, Zap, MonitorPlay, FolderOpen, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Card } from "@/components/ui/card";
import { useConfigStore } from "@/stores/configStore";
import type { ReframeMode, CenteredBackground } from "@/hooks/processClips";
// @ts-ignore
const open = async (options:any): Promise<string | null> => null;

// Placeholder caption styles – replace with real list if needed
const CAPTION_STYLES = ["default"];

export type { ProcessOptions } from "@/hooks/processClips";
import type { ProcessOptions } from "@/hooks/processClips";

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
  captionsAvailable?: boolean;
  onConfirm: (options: ProcessOptions) => void;
  onCancel: () => void;
}

export function ProcessConfirmDialog({ clipCount, captionsAvailable = true, onConfirm, onCancel }: ProcessConfirmDialogProps) {
  const { config } = useConfigStore();

  const [addCaptions, setAddCaptions] = useState(captionsAvailable);
  const [addHook, setAddHook] = useState(true);
  const [addWatermark, setAddWatermark] = useState(config.watermark.enabled);
  const [addCreditWatermark, setAddCreditWatermark] = useState(config.creditWatermark.enabled);
  const [creditText, setCreditText] = useState("");
  const [captionStyle, setCaptionStyle] = useState(CAPTION_STYLES[0]);
  const [reframeMode, setReframeMode] = useState<ReframeMode>("face");
  const [centeredBackground, setCenteredBackground] = useState<CenteredBackground>("black");
  const [splitEnabled, setSplitEnabled] = useState(true);
  const [splitWebcamPath, setSplitWebcamPath] = useState("");
  const [splitWebcamName, setSplitWebcamName] = useState("");
  const [splitMainVolume, setSplitMainVolume] = useState(100);
  const [splitSecondVolume, setSplitSecondVolume] = useState(100);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);

  // Escape handling
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

  const handlePickWebcam = async () => {
    try {
      const selected = await open({ multiple: false, filters: [{ name: "Video", extensions: ["mp4", "mov", "mkv", "webm", "avi", "m4v"] }] });
      if (typeof selected === "string") {
        setSplitWebcamPath(selected);
        const name = selected.split(/[\\/]/).pop() ?? selected;
        setSplitWebcamName(name);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleConfirm = () => {
    onConfirm({
      addCaptions,
      addHook,
      addWatermark,
      addCreditWatermark,
      creditText: addCreditWatermark ? creditText : undefined,
      captionStyle,
      reframeMode,
      centeredBackground,
      downloadQuality: "720p" as const,
      splitScreen: {
        enabled: splitEnabled && !!splitWebcamPath,
        webcamPath: splitWebcamPath,
        topRatio: 0.5,
        mainVolume: splitMainVolume / 100,
        secondVolume: splitSecondVolume / 100,
      },
    });
  };

  const previewImage = reframeMode === "centered" ? BG_SAMPLE_IMAGES[centeredBackground] : SAMPLE_IMAGES[reframeMode];
  const previewLabel = reframeMode === "centered" ? `${BG_SAMPLE_LABELS[centeredBackground]} background` : SAMPLE_LABELS[reframeMode];
  const toggleOptions: any[] = [
    {
      key: "addCaptions" as const,
      label: "Captions",
      description: captionsAvailable ? "Word‑by‑word captions from the original YouTube subtitle track" : "Unavailable — this video has no original subtitle track",
      icon: <AlignLeft className="w-5 h-5 text-[var(--color-accent)]" />, 
      enabled: addCaptions && captionsAvailable,
      onToggle: setAddCaptions,
      disabled: !captionsAvailable,
    },
    {
      key: "addHook" as const,
      label: "Hook Text",
      description: "AI‑generated hook shown over the opening seconds",
      icon: <Quote className="w-5 h-5 text-[var(--color-accent)]" />, 
      enabled: addHook,
      onToggle: setAddHook,
      disabled: false,
    },
    {
      key: "addWatermark" as const,
      label: "Logo Watermark",
      description: "Overlay a logo image on each clip",
      icon: <ImageIcon className="w-5 h-5 text-[var(--color-accent)]" />, 
      enabled: addWatermark,
      onToggle: setAddWatermark,
      disabled: false,
    },
    {
      key: "addCreditWatermark" as const,
      label: "Credit Text",
      description: "Source channel credit overlay",
      icon: <User className="w-5 h-5 text-[var(--color-accent)]" />, 
      enabled: addCreditWatermark,
      onToggle: setAddCreditWatermark,
      disabled: false,
    },
  ];

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
        <Card className="w-full max-w-md mx-4 p-0 overflow-hidden shadow-[var(--shadow-lg)] max-h-[90vh] overflow-y-auto">
          <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border-light)] sticky top-0 bg-[var(--color-bg-primary)]">
            <div className="flex items-center gap-2">
              <Film className="w-5 h-5 text-[var(--color-accent)]" />
              <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">Process Clips</h2>
            </div>
            <Button variant="ghost" size="icon" onClick={onCancel} className="h-8 w-8"><X className="w-4 h-4" /></Button>
          </div>
          <div className="px-5 py-4 space-y-4">
            <p className="text-sm text-[var(--color-text-secondary)]">Processing <span className="font-semibold text-[var(--color-text-primary)]">{clipCount}</span> clip{clipCount !== 1 ? "s" : ""}. Choose which enhancements to apply:</p>
            {/* Reframe mode */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">Reframe Mode</p>
                <button onClick={() => setPreviewSrc(previewImage)} className="flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline"><Eye className="w-3.5 h-3.5" /> View example</button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button onClick={() => setReframeMode("face")} className={`relative flex flex-col gap-1.5 p-3 rounded-[var(--radius-sm)] border text-left transition-colors ${reframeMode === "face" ? "border-[var(--color-accent)] bg-[var(--color-bg-secondary)]" : "border-transparent bg-[var(--color-bg-secondary)] hover:border-[var(--color-border-light)]"}`}>
                  <span className="absolute top-1.5 right-1.5 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-[var(--color-success-bg)] text-[var(--color-success)] text-[10px] font-semibold"><Sparkles className="w-2.5 h-2.5" /> Better Result</span>
                  <ScanFace className="w-5 h-5 text-[var(--color-accent)]" />
                  <p className="text-sm font-medium text-[var(--color-text-primary)]">Face Tracking</p>
                  <p className="text-xs text-[var(--color-text-muted)]">AI tracks the speaker — slower</p>
                </button>
                <button onClick={() => setReframeMode("centered")} className={`relative flex flex-col gap-1.5 p-3 rounded-[var(--radius-sm)] border text-left transition-colors ${reframeMode === "centered" ? "border-[var(--color-accent)] bg-[var(--color-bg-secondary)]" : "border-transparent bg-[var(--color-bg-secondary)] hover:border-[var(--color-border-light)]"}`}>
                  <span className="absolute top-1.5 right-1.5 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-[var(--color-warning-bg)] text-[var(--color-warning)] text-[10px] font-semibold"><Zap className="w-2.5 h-2.5" /> 13x Faster</span>
                  <Square className="w-5 h-5 text-[var(--color-accent)]" />
                  <p className="text-sm font-medium text-[var(--color-text-primary)]">Centered</p>
                  <p className="text-xs text-[var(--color-text-muted)]">Video centered in frame — much faster</p>
                </button>
              </div>
            </div>
            {/* Background selector for centered mode */}
            {reframeMode === "centered" && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">Background</p>
                <div className="grid grid-cols-2 gap-2">
                  <button onClick={() => setCenteredBackground("black")} className={`flex items-center gap-2 p-2.5 rounded-[var(--radius-sm)] border text-left transition-colors ${centeredBackground === "black" ? "border-[var(--color-accent)] bg-[var(--color-bg-secondary)]" : "border-transparent bg-[var(--color-bg-secondary)] hover:border-[var(--color-border-light)]"}`}>
                    <span className="w-4 h-4 rounded-sm bg-black border border-[var(--color-border-light)] shrink-0" />
                    <span className="text-sm text-[var(--color-text-primary)]">Black bars</span>
                  </button>
                  <button onClick={() => setCenteredBackground("blurred")} className={`flex items-center gap-2 p-2.5 rounded-[var(--radius-sm)] border text-left transition-colors ${centeredBackground === "blurred" ? "border-[var(--color-accent)] bg-[var(--color-bg-secondary)]" : "border-transparent bg-[var(--color-bg-secondary)] hover:border-[var(--color-border-light)]"}`}>
                    <span className="w-4 h-4 rounded-sm bg-gradient-to-br from-[var(--color-accent)]/30 to-[var(--color-accent)]/60 shrink-0" />
                    <span className="text-sm text-[var(--color-text-primary)]">Blurred</span>
                  </button>
                </div>
                <button onClick={() => setPreviewSrc(previewImage)} className="flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline"><Eye className="w-3.5 h-3.5" /> Preview {BG_SAMPLE_LABELS[centeredBackground]}</button>
              </div>
            )}
            {/* Split screen toggle */}
            <div className="flex items-center justify-between gap-3 p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)]">
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <MonitorPlay className="w-5 h-5 text-[var(--color-accent)] shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-[var(--color-text-primary)]">Split Screen</p>
                  <p className="text-xs text-[var(--color-text-muted)] truncate">Portrait top & bottom 50 % each, face‑tracked</p>
                </div>
              </div>
              <Switch checked={splitEnabled} onCheckedChange={setSplitEnabled} />
            </div>
            {splitEnabled && (
              <div className="p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)] space-y-3">
                <Button variant="outline" onClick={handlePickWebcam} className="w-full gap-2 h-9 text-sm"><FolderOpen className="w-4 h-4" /> {splitWebcamName ? "Replace video" : "Choose local video"}</Button>
                {splitWebcamName && <p className="text-xs text-[var(--color-text-muted)] truncate">{splitWebcamName}</p>}
                {!splitWebcamPath && <p className="text-xs text-[var(--color-warning)]">Pick a video file — Split Screen only activates when one is chosen.</p>}
                <div className="space-y-3 pt-1 border-t border-[var(--color-border-light)]">
                  <div className="flex items-center gap-2"><Volume2 className="w-4 h-4 text-[var(--color-accent)] shrink-0" /><p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">Volume Balance</p></div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between"><span className="text-xs text-[var(--color-text-secondary)]">Top (source)</span><span className="text-xs text-[var(--color-text-muted)]">{splitMainVolume}%</span></div>
                    <Slider value={[splitMainVolume]} min={0} max={100} step={5} onValueChange={(v) => setSplitMainVolume(v[0] ?? 100)} aria-label="Top video volume" />
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between"><span className="text-xs text-[var(--color-text-secondary)]">Bottom (webcam)</span><span className="text-xs text-[var(--color-text-muted)]">{splitSecondVolume}%</span></div>
                    <Slider value={[splitSecondVolume]} min={0} max={100} step={5} onValueChange={(v) => setSplitSecondVolume(v[0] ?? 100)} aria-label="Bottom video volume" />
                  </div>
                  <p className="text-[10px] text-[var(--color-text-muted)] italic">Adjust each pane's audio before mixing.</p>
                </div>
              </div>
            )}
            {/* Credit watermark */}
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3 p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)]">
                <div className="flex items-center gap-3 min-w-0 flex-1">
                  <User className="w-5 h-5 text-[var(--color-accent)] shrink-0" />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-[var(--color-text-primary)]">Credit Text</p>
                    <p className="text-xs text-[var(--color-text-muted)] truncate">Source channel credit overlay</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 w-full">
                  <Switch checked={addCreditWatermark} onCheckedChange={setAddCreditWatermark} />
                  <input value={creditText} onChange={(e) => setCreditText(e.target.value)} disabled={!addCreditWatermark} className="flex-1 px-3 py-2 text-sm bg-[var(--color-bg-secondary)] rounded-[var(--radius-sm)] border border-[var(--color-border-light)] focus:outline-none focus:border-[var(--color-accent)] disabled:bg-[var(--color-bg-muted)]" placeholder="e.g. Source: {channel}" />
                </div>
              </div>
            </div>
            {/* Caption style selector */}
            {addCaptions && (
              <div className="p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)] space-y-3">
                <div className="flex items-center gap-2"><ImageIcon className="w-4 h-4 text-[var(--color-accent)]" /><p className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wide">Caption Style</p></div>
                <div className="grid grid-cols-2 gap-1.5">
                  {CAPTION_STYLES.map((s) => (
                    <button key={s} onClick={() => setCaptionStyle(s)} className={`px-2 py-1.5 rounded-[var(--radius-sm)] border text-[10px] font-medium transition-colors ${captionStyle === s ? "border-[var(--color-accent)] bg-[var(--color-bg-primary)] text-[var(--color-accent)]" : "border-transparent bg-[var(--color-bg-primary)] text-[var(--color-text-muted)] hover:border-[var(--color-border-light)]"}`}>{s}</button>
                  ))}
                </div>
              </div>
            )}
            {/* Other toggles */}
            <div className="space-y-2">
              {toggleOptions.map((opt) => (
                <div key={opt.key} className="flex items-center justify-between p-3 rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)]">
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    {opt.icon}
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-[var(--color-text-primary)]">{opt.label}</p>
                      <p className="text-xs text-[var(--color-text-muted)] truncate">{opt.description}</p>
                    </div>
                  </div>
                  <Switch checked={opt.enabled} onCheckedChange={opt.onToggle} disabled={opt.disabled} />
                </div>
              ))}
            </div>
          </div>
          <div className="flex gap-3 px-5 py-4 border-t border-[var(--color-border-light)] bg-[var(--color-bg-secondary)] sticky bottom-0">
            <Button variant="outline" onClick={onCancel} className="flex-1">Cancel</Button>
            <Button onClick={handleConfirm} className="flex-1 gap-2"><Film className="w-4 h-4" />Process {clipCount} Clip{clipCount !== 1 ? "s" : ""}</Button>
          </div>
        </Card>
      </div>
      {previewSrc && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget) setPreviewSrc(null); }}>
          <div className="relative max-w-sm w-full mx-4">
            <button onClick={() => setPreviewSrc(null)} className="absolute -top-10 right-0 text-white/80 hover:text-white"><X className="w-6 h-6" /></button>
            <p className="text-center text-sm text-white/80 mb-2 font-medium">Example: {previewLabel}</p>
            <img src={previewSrc} alt={`Example: ${previewLabel}`} className="w-full rounded-[var(--radius-md)] shadow-2xl" />
          </div>
        </div>
      )}
    </>
  );
}
