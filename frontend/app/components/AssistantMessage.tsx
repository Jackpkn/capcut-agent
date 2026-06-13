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

function TracePanel({ steps, streaming }: { steps: AgentStep[]; streaming?: boolean }) {
  const [open, setOpen] = useState(streaming ?? false);
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
    <div className="mb-3 rounded-xl border border-white/[0.07] bg-black/30 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left hover:bg-white/[0.03] transition-colors cursor-pointer"
      >
        <span
          className={`h-2.5 w-2.5 rounded-full shrink-0 ${
            running || streaming ? "bg-capcut animate-pulse shadow-[0_0_8px_rgba(0,203,214,0.5)]" : errCount ? "bg-rose-400" : "bg-emerald-400"
          }`}
        />
        <div className="flex-1 min-w-0">
          <p className="text-[10px] uppercase tracking-wider font-semibold text-white/55">
            {streaming || running ? "Agent working" : "What the agent did"}
          </p>
          <p className="text-[11px] text-white/35 truncate">
            {doneCount} step{doneCount !== 1 ? "s" : ""} completed
            {errCount > 0 ? ` · ${errCount} issue${errCount !== 1 ? "s" : ""}` : ""}
          </p>
        </div>
        <span className="text-white/30 text-xs shrink-0">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="border-t border-white/[0.06] px-2 py-2 max-h-52 overflow-y-auto space-y-2">
          {Object.entries(grouped).map(([phase, phaseSteps]) => (
            <div key={phase}>
              <p className="text-[9px] uppercase tracking-wider text-white/30 font-semibold px-2 mb-1">
                {phase.replace(/_/g, " ")}
              </p>
              <div className="space-y-0.5">
                {phaseSteps.map((step) => (
                  <div
                    key={step.id}
                    className="flex gap-2.5 items-start text-[11px] rounded-lg px-2 py-1.5 hover:bg-white/[0.02]"
                  >
                    <StepIcon status={step.status} />
                    <div className="min-w-0 flex-1">
                      <p className={`font-medium leading-snug ${step.status === "error" ? "text-rose-300" : "text-white/80"}`}>
                        {step.label}
                      </p>
                      {step.detail && (
                        <p className="text-white/35 text-[10px] mt-0.5 leading-relaxed break-words">
                          {step.detail}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StepIcon({ status }: { status: AgentStep["status"] }) {
  if (status === "running") {
    return (
      <span className="w-4 h-4 mt-0.5 shrink-0 rounded-full border-2 border-capcut border-t-transparent animate-spin" />
    );
  }
  if (status === "error") {
    return (
      <span className="w-4 h-4 mt-0.5 shrink-0 rounded-full bg-rose-500/15 border border-rose-500/30 text-rose-400 text-[9px] leading-[14px] text-center font-bold">
        ✕
      </span>
    );
  }
  return (
    <span className="w-4 h-4 mt-0.5 shrink-0 rounded-full bg-emerald-500/15 border border-emerald-500/25 text-emerald-400 text-[9px] leading-[14px] text-center font-bold">
      ✓
    </span>
  );
}

export function AssistantMessage({
  content,
  steps = [],
  proposals = [],
  editorReport,
  streaming,
  waiting,
}: {
  content?: string;
  steps?: AgentStep[];
  proposals?: string[];
  editorReport?: EditorTimelinePayload | null;
  streaming?: boolean;
  waiting?: boolean;
}) {
  return (
    <div className="space-y-3 w-full">
      {editorReport && <EditorTimelineReport report={editorReport} />}

      <TracePanel steps={steps} streaming={streaming} />

      {(content || streaming || waiting) && (
        <div className="rounded-xl border border-white/[0.07] bg-gradient-to-b from-white/[0.03] to-transparent px-4 py-3.5 shadow-sm">
          {content ? (
            <RichAgentContent text={content} />
          ) : (
            <div className="flex items-center gap-2.5 py-2">
              <span className="h-4 w-4 rounded-full border-2 border-capcut/60 border-t-capcut animate-spin shrink-0" />
              <p className="text-white/45 text-xs">
                {waiting ? "Agent is composing a response…" : "Thinking…"}
              </p>
            </div>
          )}
          {streaming && content && (
            <span className="inline-block w-0.5 h-4 ml-0.5 bg-capcut animate-pulse align-middle rounded-full" />
          )}
        </div>
      )}

      {proposals.length > 0 && (
        <div className="rounded-xl border border-capcut/30 bg-capcut/[0.07] overflow-hidden">
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
