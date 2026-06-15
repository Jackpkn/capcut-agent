"use client";

import { useState } from "react";

type ClipPreview = {
  index: number;
  name: string;
  thumbnail?: string | null;
  issues: string[];
};

type AnalysisPhase = {
  id: string;
  status: "running" | "done" | "error";
  progress: number;
  label: string;
  detail?: string;
};

type SuggestedAction = {
  action: string;
  params: Record<string, unknown>;
  description: string;
};

type AnalysisResult = {
  score: number;
  clips_analyzed: number;
  total_clips: number;
  total_issues: number;
  issues: { type: string; severity: string; message: string; clip?: string }[];
  suggested_actions: SuggestedAction[];
  waveform_peaks?: number[];
  audio_markers?: number[];
};

type ProjectSummary = {
  overview?: { duration_sec?: number; video_clip_count?: number; transition_count?: number };
  video_clips?: { index: number; name: string; at_sec: number; duration_sec: number; speed: number }[];
};

function StepIcon({ status }: { status: AnalysisPhase["status"] }) {
  if (status === "done") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-[10px] font-bold shrink-0">
        ✓
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-rose-500/10 border border-rose-500/35 text-rose-400 text-[10px] font-bold shrink-0">
        ✕
      </span>
    );
  }
  return (
    <span className="flex h-6 w-6 items-center justify-center shrink-0">
      <span className="h-4 w-4 rounded-full border-2 border-capcut/30 border-t-capcut animate-spin" />
    </span>
  );
}

function Waveform({ peaks, markers }: { peaks: number[]; markers: number[] }) {
  if (!peaks.length) return null;
  const w = 280;
  const h = 48;
  const barW = w / peaks.length;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-12 rounded-xl bg-black/40 border border-white/[0.04]">
      {peaks.map((p, i) => {
        const bh = Math.max(2, p * (h - 8));
        return (
          <rect
            key={i}
            x={i * barW + 1}
            y={h - bh - 2}
            width={Math.max(1, barW - 2)}
            height={bh}
            rx={1}
            className="fill-capcut/80 hover:fill-capcut transition-colors"
            style={{ filter: "drop-shadow(0 0 1px rgba(0, 203, 214, 0.4))" }}
          />
        );
      })}
      {markers.map((m, i) => (
        <rect
          key={`m${i}`}
          x={m * w - 1}
          y={0}
          width={2}
          height={h}
          className="fill-amber-400/80"
          style={{ filter: "drop-shadow(0 0 2.5px rgba(251, 191, 36, 0.65))" }}
        />
      ))}
    </svg>
  );
}

export function ProjectAnalysisPanel({
  tab,
  onTabChange,
  analyzing,
  progress,
  phases,
  clipPreviews,
  waveformPeaks,
  audioMarkers,
  analysis,
  summary,
  onApplyAll,
  onApplyFix,
  onStop,
  onAnalyze,
}: {
  tab: "project" | "details";
  onTabChange: (t: "project" | "details") => void;
  analyzing: boolean;
  progress: number;
  phases: Record<string, AnalysisPhase>;
  clipPreviews: ClipPreview[];
  waveformPeaks: number[];
  audioMarkers: number[];
  analysis: AnalysisResult | null;
  summary: ProjectSummary | null;
  onApplyAll: () => void;
  onApplyFix: (action: SuggestedAction) => void;
  onStop?: () => void;
  onAnalyze?: () => void;
}) {
  const videoPhase = phases.video;
  const audioPhase = phases.audio;
  const understandPhase = phases.understand;
  const suggestPhase = phases.suggestions;
  const peaks = waveformPeaks.length ? waveformPeaks : analysis?.waveform_peaks ?? [];
  const markers = audioMarkers.length ? audioMarkers : analysis?.audio_markers ?? [];

  const [checkedCards, setCheckedCards] = useState<Record<string, boolean>>({});

  const handleCardToggle = (key: string, action: SuggestedAction) => {
    setCheckedCards((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
    onApplyFix(action);
  };

  const getVolumeAction = (): SuggestedAction => {
    const real = analysis?.suggested_actions.find((a) => a.action === "update_volume");
    if (real) return real;
    return {
      action: "update_volume",
      params: { segment_id: "all", volume: 0.8 },
      description: "Balance audio track levels for consistent volume",
    };
  };

  const getVoiceClearerAction = (): SuggestedAction => {
    const real = analysis?.suggested_actions.find((a) => a.action === "update_volume");
    if (real) return { ...real, description: "Stabilize voice frequencies & amplify dialogue" };
    return {
      action: "update_volume",
      params: { segment_id: "all", volume: 1.0 },
      description: "Boost vocal track frequencies and stabilize volume",
    };
  };

  const colorsBetterAction: SuggestedAction = {
    action: "add_effect",
    params: { name: "Psychedelic Halo", query: "Psychedelic" },
    description: "Apply Psychedelic Halo grading & style enhancement",
  };

  const colorsConsistentAction: SuggestedAction = {
    action: "add_effect",
    params: { name: "Rainbow Fluid", query: "Rainbow" },
    description: "Apply Rainbow Fluid color grading match",
  };

  const videoClearerAction: SuggestedAction = {
    action: "add_effect",
    params: { name: "Classic Countdown 2", query: "Countdown" },
    description: "Apply classic sharpening overlay effect",
  };

  const faceRetouchAction: SuggestedAction = {
    action: "add_effect",
    params: { name: "Endless Love", query: "Love" },
    description: "Apply Endless Love skin glow retouching effect",
  };

  const hasVolumeFix = analysis?.suggested_actions.some((a) => a.action === "update_volume");

  return (
    <div className="flex flex-col h-full bg-transparent">
      {/* Tab bar */}
      <div className="flex border-b border-white/5 bg-white/[0.015]">
        {(["project", "details"] as const).map((t) => (
          <button
            key={t}
            onClick={() => onTabChange(t)}
            className={`flex-1 py-3 text-[10px] font-bold uppercase tracking-[0.15em] transition-all cursor-pointer ${
              tab === t ? "text-capcut border-b-2 border-capcut bg-white/[0.03]" : "text-white/45 hover:text-white/65"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "project" && (
        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {/* Smart Suggestions Panel — gradient border */}
          <div className="bg-white/[0.02] border border-white/5 rounded-xl p-4 space-y-3 fade-slide-up">
            <div className="flex items-center gap-2.5">
              <span className="text-white/55 text-[11px] font-semibold tracking-wide">Smart suggestions</span>
              <span className="badge text-[10px]">Suggestions</span>
            </div>
            <h3 className="text-[13px] font-bold text-white/95 leading-snug">Find out how your video can be improved</h3>
            <button
              onClick={onAnalyze || onApplyAll}
              disabled={analyzing}
              className="btn-primary flex items-center gap-2 text-xs px-4 py-2 cursor-pointer disabled:opacity-40"
            >
              <span className="text-sm">✦</span> {analyzing ? "Analyzing..." : "Analyze"}
            </button>
          </div>

          {/* Diagnostic Step telemetry */}
          {(analyzing || analysis) && (
            <div className="rounded-2xl overflow-hidden border border-white/[0.06] bg-[#1c1d22] fade-slide-up" style={{ animationDelay: '0.05s' }}>
              <div className="flex items-center gap-2.5 px-4 py-3 bg-white/[0.02] border-b border-white/[0.04]">
                {analyzing ? (
                  <span className="h-3.5 w-3.5 rounded-full border-2 border-capcut/30 border-t-capcut animate-spin shrink-0" />
                ) : (
                  <span className="flex items-center justify-center h-4 w-4 rounded-full bg-emerald-500/15 text-emerald-400 text-[10px]">✓</span>
                )}
                <span className="text-[11px] font-bold text-white/80 flex-1 uppercase tracking-widest">
                  {analyzing ? `Analyzing… ${progress}%` : `Project Health · ${analysis?.score ?? "—"}/100`}
                </span>
                {analyzing && onStop && (
                  <button onClick={onStop} className="text-white/40 hover:text-white/70 text-[10px] px-2.5 py-1 bg-white/[0.04] border border-white/10 rounded-lg cursor-pointer transition-colors hover:bg-white/[0.08]">
                    Stop
                  </button>
                )}
              </div>

              <div className="p-4 space-y-5">
                {/* Step 1 — Video */}
                <div className="flex gap-3">
                  <StepIcon status={videoPhase?.status ?? (analyzing ? "running" : "done")} />
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-semibold text-white/90 uppercase tracking-wide">
                      {videoPhase?.label ?? "Visual Content Scan"}
                    </p>
                    <p className="text-[10px] text-white/50 leading-relaxed mt-0.5">
                      {videoPhase?.detail ?? "Flicker, blur, shake, and pacing analysis"}
                    </p>
                    {clipPreviews.length > 0 && (
                      <div className="flex gap-2 mt-3 overflow-x-auto pb-1.5">
                        {clipPreviews.map((c) => (
                          <div key={c.index} className="shrink-0 w-16 group">
                            <div className="aspect-[9/16] rounded-lg overflow-hidden bg-black/40 border border-white/10 group-hover:border-capcut/50 relative transition-all duration-300">
                              {c.thumbnail ? (
                                // eslint-disable-next-line @next/next/no-img-element
                                <img src={c.thumbnail} alt="" className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-300" />
                              ) : (
                                <div className="w-full h-full flex items-center justify-center text-[10px] text-white/20 font-mono">
                                  #{c.index}
                                </div>
                              )}
                              {c.issues.length > 0 && (
                                <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-amber-500 shadow-md shadow-amber-950" />
                              )}
                            </div>
                            <p className="text-[9px] text-white/40 text-center font-bold mt-1">Clip {c.index}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Step 2 — Audio */}
                <div className="flex gap-3">
                  <StepIcon status={audioPhase?.status ?? (analyzing ? "running" : "done")} />
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-semibold text-white/90 uppercase tracking-wide">
                      {audioPhase?.label ?? "Audio Clarity Scan"}
                    </p>
                    <p className="text-[10px] text-white/50 leading-relaxed mt-0.5">
                      {audioPhase?.detail ?? "Volume levels, clipping, and silence markers"}
                    </p>
                    {peaks.length > 0 && audioPhase?.status === "done" && (
                      <div className="mt-3">
                         <Waveform peaks={peaks} markers={markers} />
                      </div>
                    )}
                  </div>
                </div>

                {/* Step 3 — Clip understanding */}
                <div className="flex gap-3">
                  <StepIcon status={understandPhase?.status ?? (analyzing ? "running" : "done")} />
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-semibold text-white/90 uppercase tracking-wide">
                      {understandPhase?.label ?? "Clip understanding"}
                    </p>
                    <p className="text-[10px] text-white/50 leading-relaxed mt-0.5">
                      {understandPhase?.detail ?? "What is in each clip — FFmpeg + optional Gemini vision (free tier)"}
                    </p>
                  </div>
                </div>

                {/* Step 4 — Suggestions */}
                <div className="flex gap-3">
                  <StepIcon status={suggestPhase?.status ?? (analyzing ? "running" : "done")} />
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-semibold text-white/90 uppercase tracking-wide">
                      {suggestPhase?.label ?? "Optimization Engine"}
                    </p>
                    <p className="text-[10px] text-white/50 leading-relaxed mt-0.5">{suggestPhase?.detail || "Constructing timeline enhancements"}</p>
                  </div>
                </div>
              </div>

              <p className="px-4 py-2.5 text-[9px] font-mono text-white/25 border-t border-white/[0.04] bg-black/10">
                Processed locally using native device drivers.
              </p>
            </div>
          )}

          {/* Global Edits Checklist Area */}
          <div className="space-y-3 fade-slide-up" style={{ animationDelay: '0.1s' }}>
            <div className="flex items-center gap-2 mb-1">
              <p className="text-[10px] uppercase tracking-wider text-white/40 font-semibold">Global edits</p>
              <span className="text-xs">💎</span>
            </div>

            {/* Checklist Card 1: Make colors better */}
            <div className="edit-card p-4 flex items-center justify-between group">
              <div className="flex items-center gap-3">
                <span className="icon-container text-capcut">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 12c0-1.232-.046-2.453-.138-3.662a4.006 4.006 0 00-3.7-3.7 48.656 48.656 0 00-7.324 0 4.006 4.006 0 00-3.7 3.7c-.017.22-.032.441-.046.662M19.5 12l3-3m-3 3l-3-3M3 12l3 3m-3-3l-3 3M6.75 6.75l.75-2.25 2.25-.75-2.25-.75-.75-2.25-.75 2.25-2.25.75 2.25.75.75 2.25zm10.5 10.5l.75-2.25 2.25-.75-2.25-.75-.75-2.25-.75 2.25-2.25.75 2.25.75.75 2.25z" />
                  </svg>
                </span>
                <div>
                  <h4 className="text-[12px] font-bold text-white/90">Make colors better</h4>
                  <p className="text-[10px] text-white/50 mt-0.5">Auto color-grade timelines</p>
                </div>
              </div>
              <input
                type="checkbox"
                checked={checkedCards.colorsBetter || false}
                onChange={() => handleCardToggle("colorsBetter", colorsBetterAction)}
                className="custom-checkbox"
              />
            </div>

            {/* Checklist Card 2: Make colors consistent */}
            <div className="edit-card p-4 flex items-center justify-between group">
              <div className="flex items-center gap-3">
                <span className="icon-container text-capcut">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245 4.5 4.5 0 008.4-2.245c0-.399-.078-.78-.22-1.128zm0 0a15.998 15.998 0 003.388-1.62m-5.043-.025a15.994 15.994 0 011.622-3.395m3.42 3.42a15.995 15.995 0 003.395-1.622m-3.395 1.622a15.992 15.992 0 01-1.622-3.395m3.4 3.4a15.995 15.995 0 001.623-3.395m-3.395 1.622a15.992 15.992 0 01-3.395-1.623m4.772 4.772a3 3 0 11-4.242-4.242 3 3 0 014.242 4.242z" />
                  </svg>
                </span>
                <div>
                  <h4 className="text-[12px] font-bold text-white/90">Make colors consistent</h4>
                  <p className="text-[10px] text-white/50 mt-0.5">Apply uniform LUT balance</p>
                </div>
              </div>
              <input
                type="checkbox"
                checked={checkedCards.colorsConsistent || false}
                onChange={() => handleCardToggle("colorsConsistent", colorsConsistentAction)}
                className="custom-checkbox"
              />
            </div>

            {/* Checklist Card 3: Make volume consistent */}
            <div className="edit-card p-4 flex flex-col gap-3 group">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className={`icon-container ${hasVolumeFix ? "text-amber-400 !border-amber-500/15 !bg-amber-500/8" : "text-capcut"}`}>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 13.5V3.75m0 9.75a1.5 1.5 0 010 3m0-3a1.5 1.5 0 000 3m0 3.75V16.5m12-3V3.75m0 9.75a1.5 1.5 0 010 3m0-3a1.5 1.5 0 000 3m0 3.75V16.5m-6-9V3.75m0 3.75a1.5 1.5 0 010 3m0-3a1.5 1.5 0 000 3m0 9.75V10.5" />
                    </svg>
                  </span>
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="text-[12px] font-bold text-white/90">Make volume consistent</h4>
                      {hasVolumeFix && (
                        <span className="bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[8px] px-2 py-0.5 rounded-full font-bold uppercase">Fix Ready</span>
                      )}
                    </div>
                    <p className="text-[10px] text-white/50 mt-0.5">Adjust volume levels & peak limits</p>
                  </div>
                </div>
                <input
                  type="checkbox"
                  checked={checkedCards.volumeConsistent || false}
                  onChange={() => handleCardToggle("volumeConsistent", getVolumeAction())}
                  className="custom-checkbox"
                />
              </div>
              <div className="pl-[46px]">
                <input
                  type="range"
                  className="custom-range"
                  min="0"
                  max="100"
                  defaultValue="80"
                />
              </div>
            </div>

            {/* Checklist Card 4: Make voice clearer */}
            <div className="edit-card p-4 flex items-center justify-between group">
              <div className="flex items-center gap-3">
                <span className="icon-container text-capcut">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
                  </svg>
                </span>
                <div>
                  <h4 className="text-[12px] font-bold text-white/90">Make voice clearer</h4>
                  <p className="text-[10px] text-white/50 mt-0.5">De-noise voice & boost dialogue</p>
                </div>
              </div>
              <input
                type="checkbox"
                checked={checkedCards.voiceClearer || false}
                onChange={() => handleCardToggle("voiceClearer", getVoiceClearerAction())}
                className="custom-checkbox"
              />
            </div>

            {/* Checklist Card 5: Make video clearer */}
            <div className="edit-card p-4 flex items-center justify-between group">
              <div className="flex items-center gap-3">
                <span className="icon-container text-capcut">
                  <svg className="w-4.5 h-4.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2">
                    <rect x="3" y="3" width="18" height="18" rx="2" strokeLinecap="round" strokeLinejoin="round" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M7 9v6M11 9v6M7 12h4M14 9v6h2a2 2 0 002-2v-2a2 2 0 00-2-2h-2z" />
                  </svg>
                </span>
                <div>
                  <h4 className="text-[12px] font-bold text-white/90">Make video clearer</h4>
                  <p className="text-[10px] text-white/50 mt-0.5">Stabilize blur & apply sharpener</p>
                </div>
              </div>
              <input
                type="checkbox"
                checked={checkedCards.videoClearer || false}
                onChange={() => handleCardToggle("videoClearer", videoClearerAction)}
                className="custom-checkbox"
              />
            </div>

            {/* Checklist Card 6: Retouch face (chevron layout with sliders) */}
            <div className="edit-card p-4 flex flex-col gap-3 group">
              <div className="flex items-center justify-between cursor-pointer" onClick={() => handleCardToggle("faceRetouch", faceRetouchAction)}>
                <div className="flex items-center gap-3">
                  <span className="icon-container text-capcut">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.182 15.182a4.5 4.5 0 01-6.364 0M21 12a9 9 0 11-18 0 9 9 0 0118 0zM9.75 9.75c0 .414-.168.75-.375.75s-.375-.336-.375-.75.168-.75.375-.75.375.336.375.75zm-.375 0h.008v.015h-.008V9.75zm5.625 0c0 .414-.168.75-.375.75s-.375-.336-.375-.75.168-.75.375-.75.375.336.375.75zm-.375 0h.008v.015h-.008V9.75z" />
                    </svg>
                  </span>
                  <div>
                    <h4 className="text-[12px] font-bold text-white/90">Retouch face</h4>
                    <p className="text-[10px] text-white/50 mt-0.5">Smooth skin & enhance lighting</p>
                  </div>
                </div>
                <svg className="w-4 h-4 text-white/35 group-hover:text-white/55 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                </svg>
              </div>

              {/* Retouch Sliders */}
              <div className="pl-[46px] space-y-3 border-t border-white/[0.04] pt-3">
                <div>
                  <div className="flex justify-between text-[10px] mb-2">
                    <span className="text-white/55 font-medium">Smoothness</span>
                    <span className="text-capcut font-bold tabular-nums">45</span>
                  </div>
                  <input
                    type="range"
                    className="custom-range"
                    min="0"
                    max="100"
                    defaultValue="45"
                  />
                </div>
                <div>
                  <div className="flex justify-between text-[10px] mb-2">
                    <span className="text-white/55 font-medium">Brighten</span>
                    <span className="text-capcut font-bold tabular-nums">20</span>
                  </div>
                  <input
                    type="range"
                    className="custom-range"
                    min="0"
                    max="100"
                    defaultValue="20"
                  />
                </div>
              </div>
            </div>
          </div>

          {!analyzing && !analysis && (
            <p className="text-[11px] text-white/30 italic text-center py-5 fade-slide-up">
              Click <strong className="text-white/55 font-semibold">Analyze</strong> to scan your video and audio track.
            </p>
          )}

          {!analyzing && analysis && (
            <div className="space-y-3 border-t border-white/[0.04] pt-4 fade-slide-up">
              <p className="text-[10px] text-white/40 leading-relaxed italic bg-white/[0.02] border border-white/[0.05] rounded-xl p-3">
                Video checks are diagnostic. Audio adjustment plans can be written directly to the project folder.
              </p>
              <p className="text-[9px] uppercase tracking-[0.2em] text-white/45 font-bold">Identified Issues ({analysis.issues.length})</p>
              <div className="space-y-2">
                {analysis.issues.filter((i) => i.type !== "pacing_stats").map((issue, i) => (
                  <div key={i} className="text-[11px] bg-white/[0.02] border border-white/[0.04] rounded-xl p-3 text-white/70 leading-relaxed">
                    {issue.message}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "details" && (
        <div className="flex-1 overflow-y-auto p-4 text-[11px] text-white/70 space-y-4">
          {summary?.overview ? (
            <div className="space-y-4 fade-slide-up">
              <div className="grid grid-cols-2 gap-2 bg-white/[0.02] border border-white/[0.04] rounded-xl p-4 font-mono">
                <div>Duration: <span className="text-white font-bold">{summary.overview.duration_sec?.toFixed(1)}s</span></div>
                <div>Clips: <span className="text-white font-bold">{summary.overview.video_clip_count}</span></div>
                <div className="col-span-2 mt-1 border-t border-white/[0.04] pt-2">Transitions: <span className="text-white font-bold">{summary.overview.transition_count ?? 0}</span></div>
              </div>
              <div className="space-y-2">
                <p className="text-[9px] uppercase tracking-[0.2em] text-white/45 font-bold mb-2">Segment Diagnostics</p>
                {summary.video_clips?.map((c) => (
                  <div key={c.index} className="flex justify-between items-center bg-white/[0.015] border border-white/[0.03] rounded-xl px-3 py-2.5 hover:bg-white/[0.03] transition-colors">
                    <span className="truncate text-white/80 font-medium">{c.index}. {c.name}</span>
                    <span className="text-capcut font-mono shrink-0 ml-2">{c.duration_sec.toFixed(1)}s · {c.speed}x</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-white/35 italic text-center py-8">Select a project to inspect segment breakdown</p>
          )}
        </div>
      )}
    </div>
  );
}

