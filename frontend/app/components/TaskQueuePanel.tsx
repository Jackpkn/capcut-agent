"use client";

export type TeamTask = {
  id: string;
  type: string;
  instruction: string;
  description: string;
  specialist: string;
  status: string;
  qa_approved?: boolean;
  qa_feedback?: string[];
  agent_reasoning?: string;
};

export type TeamGoal = {
  id: string;
  description: string;
  type: string;
  priority: number;
};

function statusColor(status: string): string {
  switch (status) {
    case "done":
      return "text-emerald-400 bg-emerald-500/10 border-emerald-500/25";
    case "running":
      return "text-capcut bg-capcut/15 border-capcut/30";
    case "awaiting_approval":
      return "text-amber-300 bg-amber-500/10 border-amber-500/25";
    case "rejected":
    case "failed":
      return "text-rose-400 bg-rose-500/10 border-rose-500/25";
    default:
      return "text-white/45 bg-white/[0.03] border-white/[0.06]";
  }
}

function statusIcon(status: string): string {
  switch (status) {
    case "done":
      return "✓";
    case "running":
      return "…";
    case "awaiting_approval":
      return "◉";
    case "rejected":
    case "failed":
      return "✕";
    default:
      return "○";
  }
}

const TYPE_LABEL: Record<string, string> = {
  video: "Video",
  audio: "Audio",
  text: "Text",
  effects: "FX",
  assets: "Assets",
};

export function TaskQueuePanel({
  tasks,
  goals,
  streaming,
  paused,
  onPause,
  onResume,
  onFeedback,
  feedbackDraft,
  onFeedbackChange,
  onRejectTask,
}: {
  tasks: TeamTask[];
  goals?: TeamGoal[];
  streaming?: boolean;
  paused?: boolean;
  onPause?: () => void;
  onResume?: () => void;
  onFeedback?: () => void;
  feedbackDraft?: string;
  onFeedbackChange?: (value: string) => void;
  onRejectTask?: (taskId: string) => void;
}) {
  if (!tasks.length && !(goals?.length)) return null;

  const bySpecialist = tasks.reduce<Record<string, TeamTask[]>>((acc, t) => {
    const key = t.specialist || TYPE_LABEL[t.type] || t.type;
    (acc[key] ??= []).push(t);
    return acc;
  }, {});

  return (
    <div className="mt-3 pt-3 border-t border-white/5 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] uppercase tracking-wider text-capcut font-semibold">
          {paused ? "Team paused" : streaming ? "Team working…" : "Task queue"}
        </p>
        {(onPause || onResume) && (
          <div className="flex gap-1.5 shrink-0">
            {streaming && !paused && onPause && (
              <button type="button" onClick={onPause} className="btn-secondary text-[10px] px-2 py-1 cursor-pointer">
                Pause
              </button>
            )}
            {paused && onResume && (
              <button type="button" onClick={onResume} className="btn-primary text-[10px] px-2 py-1 cursor-pointer">
                Resume
              </button>
            )}
          </div>
        )}
      </div>

      {onFeedback && onFeedbackChange && (
        <div className="flex gap-1.5 bg-black/25 border border-white/5 rounded-xl p-1.5">
          <input
            type="text"
            value={feedbackDraft ?? ""}
            onChange={(e) => onFeedbackChange(e.target.value)}
            placeholder="Redirect the team…"
            className="flex-1 min-w-0 text-xs bg-transparent rounded px-2 py-1.5 text-white/85 placeholder:text-white/30 outline-none"
            onKeyDown={(e) => e.key === "Enter" && onFeedback()}
          />
          <button
            type="button"
            onClick={onFeedback}
            disabled={!feedbackDraft?.trim()}
            className="btn-primary text-[10px] px-2.5 py-1 cursor-pointer disabled:opacity-30"
          >
            Send
          </button>
        </div>
      )}

      {goals && goals.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-white/40 font-semibold mb-1">Director goals</p>
          <ul className="text-xs text-white/75 space-y-0.5 bg-white/[0.02] border border-white/5 rounded-xl p-2.5">
            {goals.map((g) => (
              <li key={g.id}>
                <span className="text-capcut font-semibold">[{TYPE_LABEL[g.type] ?? g.type}]</span>{" "}
                {g.description}
              </li>
            ))}
          </ul>
        </div>
      )}

      {Object.entries(bySpecialist).map(([agent, agentTasks]) => (
        <div key={agent}>
          <p className="text-[10px] uppercase tracking-wider text-white/40 font-semibold mb-1">{agent}</p>
          <ul className="space-y-1">
            {agentTasks.map((t) => (
              <li key={t.id} className="flex gap-2 text-xs items-center justify-between rounded-lg p-2 bg-black/20 border border-white/[0.04]">
                <div className="flex gap-2 items-start min-w-0 flex-1">
                  <span className={`shrink-0 flex items-center justify-center w-5 h-5 rounded-full border text-[10px] font-bold ${statusColor(t.status)}`}>
                    {statusIcon(t.status)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-white/80" title={t.description}>
                      {t.description || t.instruction}
                    </p>
                    {t.qa_feedback && t.qa_feedback.length > 0 && (
                      <p className="text-rose-300/80 text-[10px] mt-0.5">{t.qa_feedback.join("; ")}</p>
                    )}
                  </div>
                </div>
                {onRejectTask && (t.status === "awaiting_approval" || t.status === "pending") && (
                  <button
                    type="button"
                    onClick={() => onRejectTask(t.id)}
                    title="Reject this task"
                    className="shrink-0 text-[10px] border border-rose-500/30 text-rose-400 hover:bg-rose-500/10 px-2 py-0.5 rounded-md transition-colors cursor-pointer"
                  >
                    Reject
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
