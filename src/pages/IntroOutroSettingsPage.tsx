import React, { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Film, Upload, Play, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { useConfigStore } from "@/stores/configStore";
import { saveIntroOutro } from "@/hooks/appConfig";
import type { IntroOutroSettings } from "@/hooks/appConfig";
import { toast } from "sonner";

export function IntroOutroSettingsPage() {
  const navigate = useNavigate();
  const { config, setIntroOutro } = useConfigStore();
  const settings = config.introOutro;

  const [enabled, setEnabled] = useState(settings.enabled);
  const [introPath, setIntroPath] = useState(settings.introPath);
  const [outroPath, setOutroPath] = useState(settings.outroPath);
  const [saving, setSaving] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewTitle, setPreviewTitle] = useState<string>("");

  const introFileRef = useRef<HTMLInputElement>(null);
  const outroFileRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>, type: "intro" | "outro") => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      const arrayBuffer = await file.arrayBuffer();
      const bytes = new Uint8Array(arrayBuffer);
      const res = await saveIntroOutro(file.name, bytes);
      if (type === "intro") {
        setIntroPath(res.path);
        toast.success("Intro video uploaded successfully");
      } else {
        setOutroPath(res.path);
        toast.success("Outro video uploaded successfully");
      }
    } catch (err) {
      toast.error(`Failed to save ${type} video: ${err}`);
    }
  };

  const handleSave = async () => {
    if (enabled && !introPath && !outroPath) {
      toast.error("Please upload at least an intro or an outro video");
      return;
    }
    setSaving(true);
    try {
      await setIntroOutro({
        enabled,
        introPath,
        outroPath,
      });
      toast.success("Intro & Outro settings saved");
      navigate("/settings");
    } catch {
      toast.error("Failed to save Intro & Outro settings");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5 max-w-3xl">
      <Button
        variant="ghost"
        onClick={() => navigate("/settings")}
        className="gap-2 text-[var(--color-text-secondary)]"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Settings
      </Button>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[var(--color-text-primary)]">Intro & Outro Videos</h1>
          <p className="text-sm text-[var(--color-text-muted)] mt-1">
            Automatically prepend an intro and/or append an outro to all exported clips with 0.9s cross-fade.
          </p>
        </div>
        <Switch checked={enabled} onCheckedChange={setEnabled} />
      </div>

      <div
        className={`grid grid-cols-1 md:grid-cols-2 gap-5 transition-opacity ${
          enabled ? "opacity-100" : "opacity-50 pointer-events-none"
        }`}
      >
        {/* Intro Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Film className="w-4 h-4 text-[var(--color-accent)]" />
              Intro Video
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <input
              ref={introFileRef}
              type="file"
              accept="video/mp4,video/quicktime,video/webm"
              onChange={(e) => handleFileSelect(e, "intro")}
              className="hidden"
            />
            <Button
              variant="outline"
              onClick={() => introFileRef.current?.click()}
              className="w-full gap-2 h-11"
            >
              <Upload className="w-4 h-4" />
              {introPath ? "Replace Intro Video" : "Upload Intro MP4"}
            </Button>
            {introPath && (
              <div className="flex items-center justify-between text-xs text-[var(--color-text-muted)] bg-[var(--color-bg-secondary)] p-2 rounded">
                <span className="truncate">{introPath.split(/[\\/]/).pop()}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setPreviewUrl(introPath);
                    setPreviewTitle("Intro Video Preview");
                  }}
                  className="h-6 px-2 text-[var(--color-accent)]"
                >
                  <Play className="w-3 h-3 mr-1" /> Preview
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Outro Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Film className="w-4 h-4 text-[var(--color-accent)]" />
              Outro Video
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <input
              ref={outroFileRef}
              type="file"
              accept="video/mp4,video/quicktime,video/webm"
              onChange={(e) => handleFileSelect(e, "outro")}
              className="hidden"
            />
            <Button
              variant="outline"
              onClick={() => outroFileRef.current?.click()}
              className="w-full gap-2 h-11"
            >
              <Upload className="w-4 h-4" />
              {outroPath ? "Replace Outro Video" : "Upload Outro MP4"}
            </Button>
            {outroPath && (
              <div className="flex items-center justify-between text-xs text-[var(--color-text-muted)] bg-[var(--color-bg-secondary)] p-2 rounded">
                <span className="truncate">{outroPath.split(/[\\/]/).pop()}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setPreviewUrl(outroPath);
                    setPreviewTitle("Outro Video Preview");
                  }}
                  className="h-6 px-2 text-[var(--color-accent)]"
                >
                  <Play className="w-3 h-3 mr-1" /> Preview
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="flex justify-end gap-3 pt-4">
        <Button variant="outline" onClick={() => navigate("/settings")}>
          Cancel
        </Button>
        <Button onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save Changes"}
        </Button>
      </div>

      {/* Video preview modal */}
      {previewUrl && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) setPreviewUrl(null); }}
        >
          <div className="relative max-w-sm w-full mx-4 bg-[var(--color-bg-primary)] p-4 rounded-[var(--radius-md)] shadow-2xl">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm font-medium text-[var(--color-text-primary)]">{previewTitle}</p>
              <button onClick={() => setPreviewUrl(null)} className="text-[var(--color-text-muted)] hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>
            <video src={`asset://localhost/${previewUrl}`} controls autoPlay className="w-full rounded" />
          </div>
        </div>
      )}
    </div>
  );
}
