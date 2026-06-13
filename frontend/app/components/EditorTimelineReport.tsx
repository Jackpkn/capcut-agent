"use client";

import type { ReactNode } from "react";

export type EditorClip = {
  index: number;
  name?: string;
  at_sec?: number;
  duration_sec?: number;
  thumbnail?: string | null;
  issues?: string[];
};

export type EditorCaption = {
  index: number;
  content?: string;
  at_sec?: number;
  duration_sec?: number;
};

export type TimelineMarker = {
  at_sec: number;
  label?: string;
  kind?: string;
};

export type EditorPhase = {
  status: "running" | "done" | "pending" | "error";
  label: string;
  detail?: string;
};

export type TimelineView = "clips" | "captions" | "audio" | "edits" | "full_scan";

export type EditorTimelinePayload = {
  view?: TimelineView;
  reason?: string;
  score?: number | null;
  duration_sec?: number;
  clip_count?: number;
  clips?: EditorClip[];
  captions?: EditorCaption[];
  markers?: TimelineMarker[];
  waveform_peaks?: number[];
  audio_markers?: number[];
  suggestions?: { type: string; severity: string; message: string }[];
  phases?: {
    video?: EditorPhase;
    audio?: EditorPhase;
    suggestions?: EditorPhase;
    captions?: EditorPhase;
    edits?: EditorPhase;
  };
};

const VIEW_TITLES: Record<TimelineView, string> = {
  clips: "Clips",
  captions: "Captions",
  audio: "Audio",
  edits: "Edit placements",
  full_scan: "Project scan",
};

function StepIcon({ status }: { status: EditorPhase["status"] }) {
  if (status === "running") {
    return (
      <span className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#1c1d22] border-2 border-capcut/40">
        <span className="h-3.5 w-3.5 rounded-full border-2 border-capcut border-t-transparent animate-spin" />
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-rose-500/15 border border-rose-500/40 text-rose-400 text-xs font-bold">
        ✕
      </span>
    );
  }
  if (status === "pending") {
    return (
      <span className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/[0.04] border border-white/10 text-white/25 text-xs">
        ○
      </span>
    );
  }
  return (
    <span className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 border border-emerald-500/35 text-emerald-400 text-sm font-bold">
      ✓
    </span>
  );
}

function Waveform({ peaks, markers }: { peaks: number[]; markers: number[] }) {
  if (!peaks.length) return null;
  const w = 320;
  const h = 56;
  const barW = w / peaks.length;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-14 rounded-xl bg-[#0d0e12] border border-white/[0.06]">
      {peaks.map((p, i) => {
        const bh = Math.max(2, p * (h - 10));
        return (
          <rect
            key={i}
            x={i * barW + 0.5}
            y={h - bh - 4}
            width={Math.max(1.5, barW - 1)}
            height={bh}
            rx={1}
            className="fill-[#3b82f6]/90"
          />
        );
      })}
      {markers.map((m, i) => (
        <g key={`m${i}`}>
          <rect x={m * w - 1.5} y={0} width={3} height={h} className="fill-amber-400/90" />
          <circle cx={m * w} cy={4} r={3} className="fill-amber-400" />
        </g>
      ))}
    </svg>
  );
}

function ClipStrip({ clips }: { clips: EditorClip[] }) {
  if (!clips.length) return null;
  return (
    <div className="flex gap-2 mt-3 overflow-x-auto pb-1 scrollbar-thin">
      {clips.map((c) => (
        <div key={c.index} className="shrink-0 w-[52px]">
          <div className="aspect-[9/16] rounded-md overflow-hidden bg-black/50 border border-white/10 relative">
            {c.thumbnail ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={c.thumbnail} alt="" className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-[10px] text-white/25 font-mono bg-gradient-to-b from-white/5 to-transparent">
                {c.index}
              </div>
            )}
            <span className="absolute bottom-0 left-0 right-0 text-center text-[9px] font-bold text-white/90 bg-black/60 py-0.5">
              {c.index}
            </span>
            {(c.issues?.length ?? 0) > 0 && (
              <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-amber-500 shadow-sm" />
            )}
          </div>
          {c.at_sec != null && (
            <p className="text-[9px] text-white/35 text-center mt-1">{c.at_sec.toFixed(1)}s</p>
          )}
        </div>
      ))}
    </div>
  );
}

function TimelineRuler({
  durationSec,
  clips,
  captions,
  markers,
}: {
  durationSec: number;
  clips: EditorClip[];
  captions: EditorCaption[];
  markers: TimelineMarker[];
}) {
  if (!durationSec || durationSec <= 0) return null;
  const pct = (sec: number) => `${Math.min(100, Math.max(0, (sec / durationSec) * 100))}%`;

  return (
    <div className="mt-3 rounded-xl bg-[#0d0e12] border border-white/[0.06] p-3">
      <div className="relative h-10 rounded-md bg-white/[0.04] overflow-hidden">
        {clips.map((c) => {
          const start = c.at_sec ?? 0;
          const dur = c.duration_sec ?? 0;
          if (dur <= 0) return null;
          return (
            <div
              key={`clip-${c.index}`}
              className="absolute top-1 bottom-1 rounded bg-capcut/25 border border-capcut/40"
              style={{ left: pct(start), width: pct(dur) }}
              title={`${c.name ?? `Clip ${c.index}`} · ${start.toFixed(1)}s`}
            />
          );
        })}
        {captions.map((cap) => {
          const start = cap.at_sec ?? 0;
          const dur = cap.duration_sec ?? 1;
          return (
            <div
              key={`cap-${cap.index}`}
              className="absolute h-1.5 rounded-full bg-amber-400/70 bottom-0.5"
              style={{ left: pct(start), width: pct(Math.max(dur, 0.3)) }}
              title={cap.content}
            />
          );
        })}
        {markers.map((m, i) => (
          <div
            key={`pin-${i}`}
            className="absolute top-0 bottom-0 w-0.5 bg-rose-400 z-10"
            style={{ left: pct(m.at_sec) }}
            title={m.label}
          >
            <span className="absolute -top-0.5 left-1/2 -translate-x-1/2 w-2 h-2 rounded-full bg-rose-400 border border-[#0d0e12]" />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[9px] text-white/30 mt-1.5 font-mono">
        <span>0s</span>
        <span>{durationSec.toFixed(0)}s</span>
      </div>
      {markers.length > 0 && (
        <ul className="mt-2 space-y-1">
          {markers.map((m, i) => (
            <li key={i} className="text-[10px] text-white/60 flex gap-2">
              <span className="text-rose-300 font-mono shrink-0">{m.at_sec.toFixed(1)}s</span>
              <span>{m.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CaptionList({ captions }: { captions: EditorCaption[] }) {
  if (!captions.length) return null;
  return (
    <ul className="mt-3 space-y-1.5">
      {captions.map((c) => (
        <li
          key={c.index}
          className="text-[11px] text-white/75 flex gap-2 items-start bg-white/[0.03] rounded-lg px-2.5 py-1.5 border border-white/[0.05]"
        >
          <span className="shrink-0 text-[9px] font-mono text-white/40 w-10">
            {c.at_sec != null ? `${c.at_sec.toFixed(1)}s` : `#${c.index}`}
          </span>
          <span className="leading-snug">{c.content || "—"}</span>
        </li>
      ))}
    </ul>
  );
}

function TimelineStep({
  phase,
  children,
  isLast,
}: {
  phase: EditorPhase;
  children?: ReactNode;
  isLast?: boolean;
}) {
  return (
    <div className={`relative flex gap-3 ${isLast ? "" : "pb-6"}`}>
      {!isLast && (
        <div className="absolute left-[13px] top-7 bottom-0 w-px bg-white/10" aria-hidden />
      )}
      <StepIcon status={phase.status} />
      <div className="flex-1 min-w-0 pt-0.5">
        <p className="text-[13px] font-semibold text-white/95 leading-snug">{phase.label}</p>
        {phase.detail && (
          <p className="text-[11px] text-white/45 leading-relaxed mt-1">{phase.detail}</p>
        )}
        {children}
      </div>
    </div>
  );
}

export function EditorTimelineReport({ report }: { report: EditorTimelinePayload }) {
  const view: TimelineView = report.view ?? "clips";
  const phases = report.phases ?? {};
  const clips = report.clips ?? [];
  const captions = report.captions ?? [];
  const markers = report.markers ?? [];
  const peaks = report.waveform_peaks ?? [];
  const audioMarkers = report.audio_markers ?? [];
  const duration = report.duration_sec ?? 0;

  const title = VIEW_TITLES[view] ?? "Timeline";

  return (
    <div className="rounded-2xl border border-white/[0.08] bg-[#1a1b20] overflow-hidden shadow-lg">
      <div className="px-4 py-3 border-b border-white/[0.06] flex items-center justify-between gap-2">
        <div>
          <p className="text-[10px] uppercase tracking-widest text-capcut font-semibold">{title}</p>
          <p className="text-[11px] text-white/40 mt-0.5">
            {report.reason ||
              `${report.clip_count ?? clips.length} clips${duration ? ` · ${duration.toFixed(0)}s` : ""}`}
            {view === "full_scan" && report.score != null ? ` · health ${report.score}/100` : ""}
          </p>
        </div>
      </div>

      <div className="p-4">
        {view === "clips" && (
          <TimelineStep phase={phases.video ?? { status: "done", label: "Clips on your timeline" }} isLast>
            <TimelineRuler durationSec={duration} clips={clips} captions={[]} markers={[]} />
            <ClipStrip clips={clips} />
          </TimelineStep>
        )}

        {view === "captions" && (
          <TimelineStep phase={phases.captions ?? { status: "done", label: "Captions on your timeline" }} isLast>
            <TimelineRuler durationSec={duration} clips={clips} captions={captions} markers={[]} />
            <CaptionList captions={captions} />
          </TimelineStep>
        )}

        {view === "audio" && (
          <TimelineStep phase={phases.audio ?? { status: "pending", label: "Audio" }} isLast>
            {peaks.length > 0 ? (
              <div className="mt-3">
                <Waveform peaks={peaks} markers={audioMarkers} />
              </div>
            ) : (
              <p className="text-[11px] text-white/40 mt-2">Run Analyze in the sidebar for a full audio scan.</p>
            )}
          </TimelineStep>
        )}

        {view === "edits" && (
          <TimelineStep phase={phases.edits ?? { status: "done", label: "Where edits will land" }} isLast>
            <TimelineRuler durationSec={duration} clips={clips} captions={[]} markers={markers} />
          </TimelineStep>
        )}

        {view === "full_scan" && (
          <>
            <TimelineStep phase={phases.video ?? { status: "done", label: "Video check" }}>
              <ClipStrip clips={clips} />
            </TimelineStep>
            <TimelineStep phase={phases.audio ?? { status: "pending", label: "Audio" }}>
              {peaks.length > 0 && (
                <div className="mt-3">
                  <Waveform peaks={peaks} markers={audioMarkers} />
                </div>
              )}
            </TimelineStep>
            <TimelineStep phase={phases.suggestions ?? { status: "pending", label: "Suggestions" }} isLast>
              {(report.suggestions?.length ?? 0) > 0 && (
                <ul className="mt-3 space-y-1.5">
                  {report.suggestions!.slice(0, 5).map((s, i) => (
                    <li
                      key={i}
                      className="text-[11px] text-white/70 flex gap-2 items-start bg-white/[0.03] rounded-lg px-2.5 py-1.5 border border-white/[0.05]"
                    >
                      <span
                        className={`shrink-0 text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${
                          s.severity === "critical"
                            ? "bg-rose-500/20 text-rose-300"
                            : s.severity === "warning"
                              ? "bg-amber-500/20 text-amber-200"
                              : "bg-white/10 text-white/50"
                        }`}
                      >
                        {s.type.replace(/_/g, " ")}
                      </span>
                      <span className="leading-snug">{s.message}</span>
                    </li>
                  ))}
                </ul>
              )}
            </TimelineStep>
          </>
        )}
      </div>
    </div>
  );
}
