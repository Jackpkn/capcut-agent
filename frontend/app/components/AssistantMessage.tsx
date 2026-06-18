"use client";

import { useState } from "react";
import { RichAgentContent } from "./RichAgentContent";
import { EditorTimelineReport, type EditorTimelinePayload } from "./EditorTimelineReport";

export type AgentStep = {
  id: string;
  label: string;
  status: "running" | "done" | "error";
  detail?: string;
};

function DotLoader({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 ${className}`} aria-hidden>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1 w-1 rounded-full bg-white/45 animate-bounce"
          style={{ animationDelay: `${i * 0.14}s` }}
        />
      ))}
    </span>
  );
}

function LightbulbIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`shrink-0 ${className}`}
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M9 18h6" />
      <path d="M10 22h4" />
      <path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z" />
    </svg>
  );
}

function ThinkingLine({
  thinking,
  streaming,
  thinkingSeconds,
}: {
  thinking?: string;
  streaming?: boolean;
  thinkingSeconds?: number;
}) {
  const [open, setOpen] = useState(false);
  const [prevStreaming, setPrevStreaming] = useState(streaming);
  const hasThinking = Boolean(thinking?.trim());

  if (streaming !== prevStreaming) {
    setPrevStreaming(streaming);
    if (streaming) {
      setOpen(false);
    }
  }

  if (!streaming && !hasThinking) return null;

  const label = streaming
    ? "Thinking"
    : thinkingSeconds != null && thinkingSeconds > 0
      ? `Thought for ${thinkingSeconds.toFixed(1)} seconds`
      : "Thought";

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => hasThinking && setOpen((v) => !v)}
        className={`flex items-center gap-2 text-[13px] text-white/45 transition-colors ${
          hasThinking ? "hover:text-white/60 cursor-pointer" : "cursor-default"
        }`}
        disabled={!hasThinking}
      >
        <LightbulbIcon />
        <span>{label}</span>
        {streaming && <DotLoader />}
        {hasThinking && (
          <span className="text-white/25 text-[10px] ml-0.5">{open ? "▾" : "▸"}</span>
        )}
      </button>
      {open && hasThinking && (
        <div className="mt-2 pl-5 pr-1 max-h-48 overflow-y-auto">
          <pre className="text-[11px] leading-relaxed text-white/40 whitespace-pre-wrap font-sans">
            {thinking}
          </pre>
        </div>
      )}
    </div>
  );
}

function TracePanel({ steps, streaming }: { steps: AgentStep[]; streaming?: boolean }) {
  const [open, setOpen] = useState(false);
  const running = steps.some((s) => s.status === "running");
  const doneCount = steps.filter((s) => s.status === "done").length;
  const errCount = steps.filter((s) => s.status === "error").length;

  if (!steps.length) return null;

  const grouped = steps.reduce<Record<string, AgentStep[]>>((acc, step) => {
    const phase = step.id.split("_")[0] ?? "agent";
    acc[phase] = acc[phase] ?? [];
    acc[phase].push(step);
    return acc;
  }, {});

  return (
    <div className="mb-2 rounded-lg border border-white/[0.06] bg-black/20 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2.5 py-2 text-left hover:bg-white/[0.03] transition-colors cursor-pointer"
      >
        <span
          className={`h-1.5 w-1.5 rounded-full shrink-0 ${
            running || streaming ? "bg-capcut animate-pulse" : errCount ? "bg-rose-400" : "bg-emerald-400/80"
          }`}
        />
        <p className="text-[10px] text-white/35 flex-1">
          {streaming || running ? "Working…" : `${doneCount} step${doneCount !== 1 ? "s" : ""}`}
        </p>
        <span className="text-white/25 text-[10px]">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="border-t border-white/[0.05] px-2 py-2 max-h-40 overflow-y-auto space-y-1.5">
          {Object.entries(grouped).map(([phase, phaseSteps]) => (
            <div key={phase}>
              <p className="text-[9px] uppercase tracking-wider text-white/25 font-medium px-1 mb-0.5">
                {phase.replace(/_/g, " ")}
              </p>
              {phaseSteps.map((step) => (
                <div key={step.id} className="flex gap-2 items-start text-[10px] px-1 py-0.5">
                  <StepIcon status={step.status} />
                  <span className={step.status === "error" ? "text-rose-300/80" : "text-white/55"}>
                    {step.label}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StepIcon({ status }: { status: AgentStep["status"] }) {
  if (status === "running") {
    return <DotLoader className="mt-1 shrink-0" />;
  }
  if (status === "error") {
    return <span className="text-rose-400 text-[9px] shrink-0">✕</span>;
  }
  return <span className="text-emerald-400/70 text-[9px] shrink-0">✓</span>;
}

export function AssistantMessage({
  content,
  thinking,
  thinkingStreaming,
  thinkingSeconds,
  agent: _thinkingAgent,
  steps = [],
  proposals = [],
  editorReport,
  streaming,
  waiting,
}: {
  content?: string;
  thinking?: string;
  thinkingStreaming?: boolean;
  thinkingSeconds?: number;
  agent?: string;
  steps?: AgentStep[];
  proposals?: string[];
  editorReport?: EditorTimelinePayload | null;
  streaming?: boolean;
  waiting?: boolean;
}) {
  const showInitialDots =
    streaming && !content && !thinking && !thinkingStreaming && !waiting;
  const showWaitingDots = waiting && !content && !thinking;

  return (
    <div className="space-y-2 w-full">
      {editorReport && <EditorTimelineReport report={editorReport} />}

      {(showInitialDots || showWaitingDots) && (
        <div className="flex items-center gap-2 py-1 pl-0.5">
          <DotLoader />
        </div>
      )}

      <ThinkingLine
        thinking={thinking}
        streaming={thinkingStreaming}
        thinkingSeconds={thinkingSeconds}
      />

      <TracePanel steps={steps} streaming={streaming} />

      {content && (
        <div className="text-[13px] leading-relaxed text-white/90">
          <RichAgentContent text={content} />
          {streaming && (
            <span className="inline-block w-0.5 h-3.5 ml-0.5 bg-white/50 animate-pulse align-middle rounded-full" />
          )}
        </div>
      )}

      {proposals.length > 0 && (
        <div className="rounded-xl border border-capcut/30 bg-capcut/[0.07] overflow-hidden mt-3">
          <div className="px-4 py-2 border-b border-capcut/20 bg-capcut/[0.05]">
            <p className="text-[10px] uppercase tracking-wider font-semibold text-capcut">
              Proposed edits — approve to apply
            </p>
          </div>
          <ul className="px-4 py-3 space-y-2">
            {proposals.map((p, i) => (
              <li
                key={i}
                className="flex gap-3 text-[12px] text-white/90 bg-white/[0.03] border border-white/[0.05] rounded-lg px-3 py-2"
              >
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-capcut/15 text-capcut text-[10px] font-bold">
                  {i + 1}
                </span>
                <span className="leading-snug pt-0.5">{p}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
