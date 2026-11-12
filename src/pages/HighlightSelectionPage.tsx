import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Check,
  CheckSquare,
  Copy,
  Square,
  Flame,
  Zap,
  Sparkle,
  Clock,
  Quote,
  MessageSquareText,
  Film,
  FolderOpen,
  Play,
  Loader2,
  Sparkles,
  X,
} from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useSessionStore } from "@/stores/sessionStore";
import { useConfigStore } from "@/stores/configStore";
import type { Highlight } from "@/hooks/highlights";
import { ProcessConfirmDialog } from "@/components/ProcessConfirmDialog";

// Mirror of sanitize_clip_filename in yt_short_clipper_core/clip_processor.py:
// Windows-illegal chars and control chars become "-", whitespace runs collapse
// to one space, leading/trailing spaces and dots are stripped, capped at 120
// chars, "Untitled" fallback. Other Unicode is kept as-is.
function sanitizeClipFilename(title: string): string {
  let name = (title || "").replace(/[<>:\"/\\|?*\u0000-\u001f]/g, "-");
  name = name.replace(/\s+/g, " ").replace(/^[ .]+/, "").replace(/[ .]+$/, "");
  if (name.length > 120) {
    name = name.slice(0, 120).replace(/[ .]+$/, "");
  }
  return name || "Untitled";
}

function viralityStyle(score: number) {
  if (score >= 7) {
    return {
      label: "High",
      color: "var(--color-success)",
      bg: "var(--color-success-bg)",
      Icon: Flame,
    };
  }
  if (score >= 5) {
    return {
      label: "Medium",
      color: "var(--color-warning)",
      bg: "var(--color-warning-bg)",
      Icon: Zap,
    };
  }
  return {
    label: "Low",
    color: "var(--color-error)",
    bg: "var(--color-error-bg)",
    Icon: Sparkle,
  };
}

function stripMs(ts: string): string {
  return ts.split(",")[0];
}

/** File name (with extension) from a Windows or POSIX path; "" stays "".
    Same helper as ProcessConfirmDialog (v2.0.142). */
function fileNameOf(path: string): string {
  return path.split(/[\\/]/).pop() ?? "";
}

export function HighlightSelectionPage() {
  const navigate = useNavigate();
  const { session, origin, selectedIndices, toggleSelected, selectAll, deselectAll, getSelectedHighlights, highlightTopics, setHighlightTopic, highlightIntros, highlightOutros, setHighlightIntro, setHighlightOutro } =
    useSessionStore();

  const [showProcessDialog, setShowProcessDialog] = useState(false);

  useEffect(() => {
    if (!session) navigate("/");
  }, [session, navigate]);

  const sessionDir = session?.session_dir;

  // v2.0.142: drop per-highlight intro/outro picks whose files no longer
  // exist (moved/deleted) - same rule as the Process Clips dialog
  // (v2.0.136). A failed probe keeps the saved pick; a pick replaced
  // while probing keeps the new value.
  useEffect(() => {
    if (!sessionDir) return;
    let cancelled = false;
    (async () => {
      const store = useSessionStore.getState();
      const checks: { path: string; clear: () => void; isCurrent: () => boolean }[] = [];
      for (const [key, path] of Object.entries(store.highlightIntros[sessionDir] ?? {})) {
        const i = Number(key);
        checks.push({
          path,
          clear: () => useSessionStore.getState().setHighlightIntro(sessionDir, i, null),
          isCurrent: () => useSessionStore.getState().highlightIntros[sessionDir]?.[i] === path,
        });
      }
      for (const [key, path] of Object.entries(store.highlightOutros[sessionDir] ?? {})) {
        const i = Number(key);
        checks.push({
          path,
          clear: () => useSessionStore.getState().setHighlightOutro(sessionDir, i, null),
          isCurrent: () => useSessionStore.getState().highlightOutros[sessionDir]?.[i] === path,
        });
      }
      for (const { path, clear, isCurrent } of checks) {
        try {
          const exists = await invoke<boolean>("path_exists", { path });
          if (!exists && !cancelled && isCurrent()) clear();
        } catch {
          /* probe failed - keep the saved pick */
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // Runs once per session, validating the stored picks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionDir]);

  if (!session) return null;

  const backTo = origin === "library" ? "/library" : "/";
  const backLabel = origin === "library" ? "Back to Library" : "Back to Create";

  const highlights = session.highlights;
  const processedSet = new Set(session.processed_highlights ?? []);
  // Only count unprocessed selected highlights
  const selectedCount = [...selectedIndices].filter((i) => !processedSet.has(i)).length;

  return (
    <div className="space-y-5">
      <Button
        variant="ghost"
        onClick={() => navigate(backTo)}
        className="gap-2 text-[var(--color-text-secondary)]"
      >
        <ArrowLeft className="w-4 h-4" />
        {backLabel}
      </Button>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[var(--color-text-primary)]">
            Select Highlights
          </h1>
          <p className="text-sm text-[var(--color-text-muted)] mt-1">
            {highlights.length} viral moments found in{" "}
            <span className="text-[var(--color-text-secondary)]">
              {session.video_info.title || "the video"}
            </span>
          </p>
        </div>
      </div>

      {/* Legend + bulk actions */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3 text-xs text-[var(--color-text-muted)]">
          <span className="flex items-center gap-1">
            <Flame className="w-3.5 h-3.5 text-[var(--color-success)]" /> 7-10 High
          </span>
          <span className="flex items-center gap-1">
            <Zap className="w-3.5 h-3.5 text-[var(--color-warning)]" /> 5-6 Medium
          </span>
          <span className="flex items-center gap-1">
            <Sparkle className="w-3.5 h-3.5 text-[var(--color-error)]" /> 1-4 Low
          </span>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={selectAll} className="gap-1.5">
            <CheckSquare className="w-3.5 h-3.5" /> Select all
          </Button>
          <Button variant="outline" size="sm" onClick={deselectAll} className="gap-1.5">
            <Square className="w-3.5 h-3.5" /> Clear
          </Button>
        </div>
      </div>

      {/* Highlight cards */}
      <div className="space-y-3">
        {highlights.map((h, i) => (
          <HighlightCard
            key={i}
            index={i}
            highlight={h}
            selected={selectedIndices.has(i) && !processedSet.has(i)}
            processed={processedSet.has(i)}
            sessionDir={session.session_dir}
            topic={highlightTopics[session.session_dir]?.[i] ?? h.title}
            onTopicChange={(t) => setHighlightTopic(session.session_dir, i, t)}
            intro={highlightIntros[session.session_dir]?.[i] ?? null}
            outro={highlightOutros[session.session_dir]?.[i] ?? null}
            onIntroChange={(p) => setHighlightIntro(session.session_dir, i, p)}
            onOutroChange={(p) => setHighlightOutro(session.session_dir, i, p)}
            onToggle={() => { if (!processedSet.has(i)) toggleSelected(i); }}
          />
        ))}
      </div>

      {/* Sticky action bar */}
      <div className="sticky bottom-0 -mx-6 px-6 py-4 bg-[var(--color-bg-secondary)] border-t-4 border-black">
        <Button
          size="lg"
          disabled={selectedCount === 0}
          onClick={() => setShowProcessDialog(true)}
          className="w-full h-13 gap-2 shadow-[var(--shadow)]"
        >
          <Film className="w-5 h-5" />
          Process {selectedCount} clip{selectedCount === 1 ? "" : "s"}
        </Button>
      </div>

      {/* Process confirmation modal */}
      {showProcessDialog && (
        <ProcessConfirmDialog
          clipCount={selectedCount}
          captionsAvailable={session.caption_available ?? true}
          onConfirm={(options) => {
            setShowProcessDialog(false);
            const selected = getSelectedHighlights();
            // Attach original highlight index for dedup tracking
            const highlightsWithIndex = selected.map((h) => {
              const originalIndex = highlights.indexOf(h);
              return {
                ...h,
                _highlight_index: originalIndex,
                // v2.0.142: per-highlight intro/outro override (null = fall
                // back to the global intro/outro from the Process Clips
                // dialog for this clip).
                introPath: highlightIntros[session.session_dir]?.[originalIndex] ?? null,
                outroPath: highlightOutros[session.session_dir]?.[originalIndex] ?? null,
              };
            });
            // v2.0.142: the dialog only enables Intro & Outro when a GLOBAL
            // file is picked; a per-highlight pick enables it for its clip
            // too. The dialog toggle still gates the global fallback, not
            // the per-highlight picks - a pick is an explicit per-clip
            // choice and always applies to its clip.
            const hasPerHighlightPick = highlightsWithIndex.some((h) => h.introPath || h.outroPath);
            navigate("/processing-clips", {
              state: {
                url: session.url,
                localPath: session.local_video_path,
                highlights: highlightsWithIndex,
                sessionDir: session.session_dir,
                options: { ...options, addIntroOutro: options.addIntroOutro || hasPerHighlightPick },
              },
            });
          }}
          onCancel={() => setShowProcessDialog(false)}
        />
      )}
    </div>
  );
}

interface HighlightCardProps {
  index: number;
  highlight: Highlight;
  selected: boolean;
  processed: boolean;
  sessionDir: string;
  topic: string;
  onTopicChange: (topic: string) => void;
  intro: string | null;
  outro: string | null;
  onIntroChange: (path: string | null) => void;
  onOutroChange: (path: string | null) => void;
  onToggle: () => void;
}

function HighlightCard({ index, highlight, selected, processed, sessionDir, topic, onTopicChange, intro, outro, onIntroChange, onOutroChange, onToggle }: HighlightCardProps) {
  const navigate = useNavigate();
  const { config } = useConfigStore();
  const v = viralityStyle(highlight.virality_score);
  // v2.0.141: per-card state only - generating/copy never touch other cards.
  const [generating, setGenerating] = useState(false);
  const [copied, setCopied] = useState(false);

  const clipPath = `${sessionDir}\\clips\\clip_${String(index).padStart(3, "0")}\\${sanitizeClipFilename(highlight.title)}.mp4`;

  const copyTopic = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(topic);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // silent
    }
  };

  // v2.0.141: generate an intro-video topic from this highlight, reusing the
  // same generate_social_title command as ClipDetailPage. Only the returned
  // title is used; the clip title (and filename) is never touched.
  const handleGenerateTopic = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const tg = config.ai;
    if (!tg.apiKey || !tg.model) {
      toast.error("AI provider not configured. Go to AI Models settings.");
      return;
    }
    setGenerating(true);
    try {
      const result = await invoke<{ title: string; description: string; fallback?: boolean }>("generate_social_title", {
        title: highlight.title,
        hookText: highlight.hook_text,
        description: highlight.description,
        apiKey: tg.apiKey,
        baseUrl: tg.baseUrl,
        model: tg.model,
        sessionDir,
      });
      if (!result?.title) {
        toast.error("AI mengembalikan respons kosong. Coba model atau prompt berbeda.");
        return;
      }
      if (result.fallback) {
        onTopicChange(highlight.title);
        toast.warning("AI tidak mengembalikan teks - dipakai judul asli. Coba model lain atau periksa provider.");
      } else {
        onTopicChange(result.title);
        toast.success("Topik intro generated");
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Generation failed: ${msg}`);
    } finally {
      setGenerating(false);
    }
  };

  const handleOpenClip = (e: React.MouseEvent) => {
    e.stopPropagation();
    invoke("open_path_in_explorer", { path: clipPath }).catch(console.error);
  };

  // v2.0.142: pick an intro/outro video for THIS highlight, using the same
  // Tauri file dialog (video filter) as ProcessConfirmDialog.
  const pickVideo = async (): Promise<string | null> => {
    try {
      const selected = await open({
        multiple: false,
        filters: [
          { name: "Video", extensions: ["mp4", "mov", "mkv", "webm", "avi", "m4v"] },
          { name: "All files", extensions: ["*"] },
        ],
      });
      return typeof selected === "string" && selected ? selected : null;
    } catch (err) {
      console.error("Failed to pick video", err);
      return null;
    }
  };

  const handlePickIntro = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const picked = await pickVideo();
    if (picked) onIntroChange(picked);
  };

  const handlePickOutro = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const picked = await pickVideo();
    if (picked) onOutroChange(picked);
  };

  const handleRemoveIntro = (e: React.MouseEvent) => {
    e.stopPropagation();
    onIntroChange(null);
  };

  const handleRemoveOutro = (e: React.MouseEvent) => {
    e.stopPropagation();
    onOutroChange(null);
  };

  const handleViewClip = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate("/clip", {
      state: {
        clipPath,
        title: highlight.title,
        hookText: highlight.hook_text,
        description: highlight.description,
        startTime: highlight.start_time.split(",")[0],
        endTime: highlight.end_time.split(",")[0],
        sessionDir,
        highlightIndex: index,
      },
    });
  };

  return (
    <Card
      className={`p-0 overflow-hidden transition-all duration-200 ${
        processed
          ? "border-[var(--color-success)]/30 bg-[var(--color-success-bg)]/20"
          : selected
          ? "border-[var(--color-accent)] ring-1 ring-[var(--color-accent)]/30 cursor-pointer"
          : "hover:border-[var(--color-border)] cursor-pointer"
      }`}
      onClick={processed ? undefined : onToggle}
    >
      <div className="flex">
        {/* Selection indicator strip */}
        <div
          className={`w-1 shrink-0 transition-colors ${
            selected ? "bg-[var(--color-accent)]" : "bg-transparent"
          }`}
        />

        <div className="flex-1 p-4 space-y-3">
          {/* Top row */}
          <div className="flex items-start gap-3">
            <div className="pt-0.5">
              {processed ? (
                <CheckSquare className="w-5 h-5 text-[var(--color-success)]" />
              ) : selected ? (
                <CheckSquare className="w-5 h-5 text-[var(--color-accent)]" />
              ) : (
                <Square className="w-5 h-5 text-[var(--color-text-muted)]" />
              )}
            </div>

            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-[var(--color-text-primary)] leading-snug">
                <span className="text-[var(--color-text-muted)]">#{index + 1}</span>{" "}
                {highlight.title}
              </p>
            </div>

            {/* Virality badge */}
            <span
              className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-full shrink-0"
              style={{ color: v.color, backgroundColor: v.bg }}
            >
              <v.Icon className="w-3.5 h-3.5" />
              {highlight.virality_score}/10
            </span>
          </div>

          {/* Hook */}
          {highlight.hook_text && (
            <div className="flex items-start gap-2 text-sm">
              <Quote className="w-4 h-4 shrink-0 mt-0.5 text-[var(--color-accent)]" />
              <span className="font-medium text-[var(--color-text-primary)]">
                {highlight.hook_text}
              </span>
            </div>
          )}

          {/* Description */}
          {highlight.description && (
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
              {highlight.description}
            </p>
          )}

          {/* Transcript preview */}
          {highlight.transcript_text && (
            <div className="rounded-[var(--radius-sm)] bg-[var(--color-bg-secondary)] p-3">
              <div className="flex items-center gap-1.5 mb-1 text-xs font-medium text-[var(--color-text-muted)]">
                <MessageSquareText className="w-3.5 h-3.5" />
                Transcript
              </div>
              <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed line-clamp-3">
                {highlight.transcript_text}
              </p>
            </div>
          )}

          {/* Topik Intro (v2.0.141): separate from the clip title - the user
              copies this to an AI video tool to generate the intro video
              before processing. It never changes the clip title/filename. */}
          <div className="space-y-1.5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between gap-2">
              <label className="text-xs font-medium text-[var(--color-text-muted)]">Topik Intro</label>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleGenerateTopic}
                  disabled={generating}
                  className="h-6 px-2 gap-1 text-xs text-[var(--color-accent)]"
                  aria-label="Generate intro topic with AI"
                >
                  {generating ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Sparkles className="w-3.5 h-3.5" />
                  )}
                  {generating ? "Generating..." : "Generate with AI"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={copyTopic}
                  className="h-6 px-2 text-xs"
                  aria-label="Copy intro topic"
                >
                  {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                </Button>
              </div>
            </div>
            <Input
              value={topic}
              onChange={(e) => onTopicChange(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              placeholder="Topik untuk video intro"
              className="h-8 text-sm"
            />
          </div>

          {/* Video Intro & Outro per highlight (v2.0.142): picked here,
              before Process Clips. A pick wins for this clip; without one,
              the global intro/outro from the Process Clips dialog is used
              as fallback. Mirrors the dialog rows (file name + Change +
              Remove). */}
          <div className="space-y-3" onClick={(e) => e.stopPropagation()}>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <label className="text-xs font-medium text-[var(--color-text-muted)]">Video Intro</label>
                {intro && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleRemoveIntro}
                    className="h-6 px-2 gap-1 text-xs"
                    aria-label="Remove intro video"
                  >
                    <X className="w-3.5 h-3.5" />
                    Remove
                  </Button>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={handlePickIntro} className="gap-1.5">
                  <FolderOpen className="w-3.5 h-3.5" />
                  {intro ? "Change Intro" : "Pick Intro Video"}
                </Button>
                {intro && (
                  <span className="text-xs text-[var(--color-text-muted)] truncate">{fileNameOf(intro)}</span>
                )}
              </div>
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <label className="text-xs font-medium text-[var(--color-text-muted)]">Video Outro <span className="normal-case">(optional)</span></label>
                {outro && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleRemoveOutro}
                    className="h-6 px-2 gap-1 text-xs"
                    aria-label="Remove outro video"
                  >
                    <X className="w-3.5 h-3.5" />
                    Remove
                  </Button>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={handlePickOutro} className="gap-1.5">
                  <FolderOpen className="w-3.5 h-3.5" />
                  {outro ? "Change Outro" : "Pick Outro Video"}
                </Button>
                {outro && (
                  <span className="text-xs text-[var(--color-text-muted)] truncate">{fileNameOf(outro)}</span>
                )}
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
            <Clock className="w-3.5 h-3.5" />
            {stripMs(highlight.start_time)} → {stripMs(highlight.end_time)}
            <span className="text-[var(--color-text-secondary)]">
              ({Math.round(highlight.duration_seconds)}s)
            </span>
            {processed && (
              <span className="ml-auto flex items-center gap-2">
                <span className="flex items-center gap-1 text-[var(--color-success)]">
                  <Film className="w-3.5 h-3.5" />
                  Clip ready
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleViewClip}
                  className="h-6 px-2 gap-1 text-xs text-[var(--color-accent)]"
                >
                  <Play className="w-3.5 h-3.5" />
                  View
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleOpenClip}
                  className="h-6 px-2 gap-1 text-xs text-[var(--color-text-muted)]"
                >
                  <FolderOpen className="w-3.5 h-3.5" />
                  Open
                </Button>
              </span>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
