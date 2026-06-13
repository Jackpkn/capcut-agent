"use client";

export type TeamPlanBrief = {
  preset_label?: string;
  platform?: string;
  audience?: string;
  hook?: string;
  arc?: string;
  music_direction?: string;
  caption_direction?: string;
  creative_notes?: string[];
};

export type TeamPlanTask = {
  id?: string;
  description?: string;
  specialist?: string;
  action?: string;
  status?: string;
  qa_feedback?: string[];
};

export type TeamPlanChapter = {
  id?: string;
  index?: number;
  label?: string;
  start_sec?: number;
  end_sec?: number;
  pacing?: string;
  clip_count?: number;
  status?: string;
};

export type TeamPlanPayload = {
  goals_count?: number;
  queued_count?: number;
  approved_count?: number;
  rejected_count?: number;
  brief?: TeamPlanBrief;
  warnings?: string[];
  approved_tasks?: TeamPlanTask[];
  rejected_tasks?: TeamPlanTask[];
  chapters?: TeamPlanChapter[];
  session_memory?: {
    style_brief?: string;
    constraints?: string[];
    avoid?: string[];
  };
};

function BriefRow({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="grid grid-cols-[88px_1fr] gap-2 text-[12px] leading-snug">
      <span className="text-white/40 font-medium">{label}</span>
      <span className="text-white/85">{value}</span>
    </div>
  );
}

export function TeamPlanCard({ plan, summary }: { plan: TeamPlanPayload; summary?: string }) {
  const brief = plan.brief ?? {};
  const approved = plan.approved_tasks ?? [];
  const rejected = plan.rejected_tasks ?? [];
  const warnings = plan.warnings ?? [];

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-white/[0.08] bg-gradient-to-br from-white/[0.04] to-transparent px-4 py-3">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-capcut font-semibold">Team plan</p>
            <h3 className="text-sm font-semibold text-white/95 mt-0.5">
              {brief.preset_label ?? "Edit plan"}
            </h3>
          </div>
          <div className="text-[10px] text-white/40 text-right tabular-nums leading-relaxed">
            <div>{plan.goals_count ?? 0} goals</div>
            <div>{plan.approved_count ?? approved.length} to apply</div>
            {(plan.rejected_count ?? rejected.length) > 0 && (
              <div className="text-rose-400/80">{plan.rejected_count ?? rejected.length} skipped</div>
            )}
          </div>
        </div>

        <div className="space-y-1.5 border-t border-white/[0.06] pt-3">
          <BriefRow label="Platform" value={brief.platform} />
          <BriefRow label="Audience" value={brief.audience} />
          <BriefRow label="Hook" value={brief.hook} />
          <BriefRow label="Arc" value={brief.arc} />
          <BriefRow label="Music" value={brief.music_direction} />
          <BriefRow label="Captions" value={brief.caption_direction} />
        </div>

        {(brief.creative_notes?.length ?? 0) > 0 && (
          <ul className="mt-2 space-y-0.5 text-[11px] text-white/55 list-disc list-inside">
            {brief.creative_notes!.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        )}
      </div>

      {(plan.chapters?.length ?? 0) > 0 && (
        <div className="rounded-xl border border-white/[0.08] bg-black/25 px-3 py-2.5">
          <p className="text-[10px] uppercase tracking-wider font-semibold text-capcut mb-2">
            Chapters ({plan.chapters!.length})
          </p>
          <div className="space-y-1.5">
            {plan.chapters!.map((ch) => (
              <div
                key={ch.id ?? ch.index}
                className="flex items-center gap-2 text-[11px] text-white/75 bg-white/[0.02] rounded-lg px-2 py-1.5"
              >
                <span className="text-capcut font-bold tabular-nums shrink-0">{ch.index}</span>
                <span className="font-medium text-white/90 truncate">{ch.label}</span>
                <span className="text-white/35 tabular-nums ml-auto shrink-0">
                  {ch.start_sec != null ? `${ch.start_sec.toFixed(0)}–${ch.end_sec?.toFixed(0)}s` : ""}
                  {ch.clip_count != null ? ` · ${ch.clip_count} clips` : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {plan.session_memory?.style_brief && (
        <p className="text-[11px] text-white/50 leading-relaxed px-1">
          <span className="text-white/35">Memory: </span>
          {plan.session_memory.style_brief.slice(0, 200)}
        </p>
      )}

      {warnings.length > 0 && (
        <div className="rounded-xl border border-amber-500/25 bg-amber-500/[0.06] px-3 py-2.5 space-y-1">
          <p className="text-[10px] uppercase tracking-wider font-semibold text-amber-300/90">Warnings</p>
          {warnings.map((w, i) => (
            <p key={i} className="text-[11px] text-amber-100/80 leading-relaxed">
              {w}
            </p>
          ))}
        </div>
      )}

      {approved.length > 0 && (
        <div className="rounded-xl border border-capcut/25 bg-capcut/[0.06] px-4 py-3">
          <p className="text-[10px] uppercase tracking-wider font-semibold text-capcut mb-2">
            Ready to apply ({approved.length})
          </p>
          <ul className="space-y-2">
            {approved.map((t, i) => (
              <li key={t.id ?? i} className="flex gap-2 text-[12px] text-white/90">
                <span className="text-emerald-400 shrink-0 font-bold">✓</span>
                <span>
                  {t.specialist && (
                    <span className="text-white/45 text-[10px] mr-1.5">{t.specialist}</span>
                  )}
                  {t.description}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {rejected.length > 0 && (
        <div className="rounded-xl border border-rose-500/20 bg-rose-500/[0.04] px-4 py-3">
          <p className="text-[10px] uppercase tracking-wider font-semibold text-rose-300/90 mb-2">
            Skipped by QA ({rejected.length})
          </p>
          <ul className="space-y-2">
            {rejected.map((t, i) => (
              <li key={t.id ?? i} className="text-[11px] text-white/60">
                <span className="text-rose-400 font-bold mr-1.5">✕</span>
                {t.description}
                {t.qa_feedback?.length ? (
                  <span className="block text-rose-300/70 mt-0.5 ml-4">{t.qa_feedback.join("; ")}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {summary && (
        <p className="text-[11px] text-white/50 px-1">{summary}</p>
      )}
    </div>
  );
}
