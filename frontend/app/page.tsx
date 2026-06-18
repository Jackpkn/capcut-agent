"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { AssistantMessage } from "./components/AssistantMessage";
import type { EditorTimelinePayload } from "./components/EditorTimelineReport";
import { TeamPlanCard, type TeamPlanPayload } from "./components/TeamPlanCard";
import { ProjectAnalysisPanel } from "./components/ProjectAnalysisPanel";
import { TaskQueuePanel, type TeamGoal, type TeamTask } from "./components/TaskQueuePanel";

const API = "http://localhost:8000";

function sseContent(event: Record<string, unknown>): string {
  return String(event.content ?? event.delta ?? "");
}

async function consumeSSE(
  response: Response,
  onEvent: (event: Record<string, unknown>) => void
) {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith("data: ")) {
        onEvent(JSON.parse(line.slice(6)));
      }
    }
  }
}

function upsertStep(steps: AgentStep[], incoming: AgentStep): AgentStep[] {
  const idx = steps.findIndex((s) => s.id === incoming.id);
  if (idx >= 0) {
    const next = [...steps];
    next[idx] = { ...next[idx], ...incoming };
    return next;
  }
  return [...steps, incoming];
}

type AgentStep = {
  id: string;
  label: string;
  status: "running" | "done" | "error";
  detail?: string;
};

type Message = {
  role: string;
  content: string;
  thinking?: string;
  thinkingStreaming?: boolean;
  thinkingAgent?: string;
  thinkingStartedAt?: number;
  thinkingSeconds?: number;
  steps?: AgentStep[];
  proposals?: string[];
  editorReport?: EditorTimelinePayload | null;
  streaming?: boolean;
  pendingActions?: PendingAction[];
  teamPlan?: TeamPlanPayload;
};
type Project = { id: string; name: string; path: string };
type PendingAction = { action: string; params: Record<string, unknown>; description: string; reason?: string };

type EditDiffRow = {
  category: string;
  target: string;
  field: string;
  before: string;
  after: string;
};

type EditDiff = {
  rows: EditDiffRow[];
  overview: {
    transitions_before: number;
    transitions_after: number;
    music_before: string;
    music_after: string;
    change_count: number;
  };
};

type AnalysisIssue = {
  type: string;
  severity: "critical" | "warning" | "info";
  message: string;
  clip?: string;
};

type AnalysisResult = {
  score: number;
  clips_analyzed: number;
  total_clips: number;
  total_issues: number;
  issues: AnalysisIssue[];
  report?: string;
  suggested_actions: PendingAction[];
  waveform_peaks?: number[];
  audio_markers?: number[];
  clip_intelligence?: {
    index?: number;
    name?: string;
    content?: string;
    emotion?: string;
    suggested_use?: string;
    hook_strength?: number;
    quality_score?: number;
  }[];
};

type ProjectSummary = {
  overview?: {
    duration_sec?: number;
    fps?: number;
    video_clip_count?: number;
    text_overlay_count?: number;
    transition_count?: number;
  };
  text_overlays?: { text_id: string; content: string; at_sec: number }[];
  video_clips?: {
    index: number;
    segment_id: string;
    name: string;
    at_sec: number;
    duration_sec: number;
    speed: number;
  }[];
};

type SystemStatus = {
  backend: string;
  ffmpeg: boolean;
  catalog_total: number;
  cdp_connected: boolean;
  cdp_pages: number;
  capcut_launch_hint?: string | null;
  capcut_running?: boolean;
  apply_queue?: { status: string; count: number; message: string } | null;
  accessibility_enabled?: boolean;
  accessibility_host_app?: string;
  whisper?: { available: boolean; install_hint: string };
};

type LibraryResult = {
  id: string;
  name: string;
  type: string;
  origin: string;
  resource_id?: string;
  cached?: boolean;
  path?: string;
};

type Activity = { time: string; message: string; type: "info" | "success" | "error" };

const QUICK_PROMPTS = [
  "Edit this like a travel vlog — captions, music, transitions",
  "TikTok viral — fast cuts, hype music, captions",
  "Make it energetic — 1.2x clips 2-3, Pull in, hype music",
  "Analyze my project and suggest improvements",
];

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [autoEditing, setAutoEditing] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedPath, setSelectedPath] = useState("");
  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [analysisPhases, setAnalysisPhases] = useState<Record<string, {
    id: string; status: "running" | "done" | "error"; progress: number; label: string; detail?: string;
  }>>({});
  const [clipPreviews, setClipPreviews] = useState<{ index: number; name: string; thumbnail?: string | null; issues: string[] }[]>([]);
  const [waveformPeaks, setWaveformPeaks] = useState<number[]>([]);
  const [audioMarkers, setAudioMarkers] = useState<number[]>([]);
  const [analysisPanelTab, setAnalysisPanelTab] = useState<"project" | "details">("project");
  const analysisAbortRef = useRef<AbortController | null>(null);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState("");
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);
  const [editDiff, setEditDiff] = useState<EditDiff | null>(null);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [rightTab, setRightTab] = useState<"analysis" | "library">("analysis");
  const [libraryQuery, setLibraryQuery] = useState("");
  const [libraryType, setLibraryType] = useState("all");
  const [libraryResults, setLibraryResults] = useState<LibraryResult[]>([]);
  const [librarySearching, setLibrarySearching] = useState(false);
  const [librarySyncing, setLibrarySyncing] = useState(false);
  const [teamMode, setTeamMode] = useState(false);
  const [teamSessionId, setTeamSessionId] = useState<string | null>(null);
  const [teamAutoEdit, setTeamAutoEdit] = useState(false);
  const [teamTasks, setTeamTasks] = useState<TeamTask[]>([]);
  const [teamGoals, setTeamGoals] = useState<TeamGoal[]>([]);
  const [teamChapters, setTeamChapters] = useState<
    { id?: string; index?: number; label?: string; start_sec?: number; end_sec?: number; clip_count?: number; status?: string }[]
  >([]);
  const [teamPaused, setTeamPaused] = useState(false);
  const [teamFeedbackDraft, setTeamFeedbackDraft] = useState("");
  const [agentLive, setAgentLive] = useState<{
    active: boolean;
    title: string;
    steps: AgentStep[];
    proposals: string[];
    directorBrief?: string;
    criticNotes: string[];
    routeMode?: string;
    routeReason?: string;
  }>({ active: false, title: "", steps: [], proposals: [], criticNotes: [] });
  const [queueWaiting, setQueueWaiting] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [libraryStats, setLibraryStats] = useState<{
    music: number;
    effects: number;
    transitions: number;
    stickers: number;
    text_templates: number;
    catalog_total: number;
    named_from_projects: number;
  } | null>(null);

  const log = useCallback((message: string, type: Activity["type"] = "info") => {
    setActivity((prev) => [
      { time: new Date().toLocaleTimeString(), message, type },
      ...prev.slice(0, 19),
    ]);
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/status`);
      if (!res.ok) throw new Error("Status check failed");
      const data = await res.json();
      setStatus(data);
      setConnected(true);
      setError("");
      if (data.apply_queue?.status === "waiting") setQueueWaiting(true);
    } catch {
      setConnected(false);
      setStatus(null);
      setError("Backend offline — run: uv run uvicorn main:app --reload --port 8000");
    }
  }, []);

  const loadProjects = useCallback(async () => {
    try {
      const res = await fetch(`${API}/projects`);
      if (res.ok) setProjects(await res.json());
    } catch { /* ignore */ }
  }, []);

  const loadSummary = useCallback(async (path: string) => {
    if (!path) { setSummary(null); return; }
    try {
      const res = await fetch(`${API}/project/summary?path=${encodeURIComponent(path)}`);
      if (res.ok) setSummary(await res.json());
    } catch { setSummary(null); }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadStatus();
    loadProjects();
    const interval = setInterval(() => { loadStatus(); loadProjects(); }, 10000);
    return () => clearInterval(interval);
  }, [loadStatus, loadProjects]);

  const loadLibraryStats = useCallback(async () => {
    try {
      const res = await fetch(`${API}/library/stats`);
      if (res.ok) setLibraryStats(await res.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadSummary(selectedPath);
    setAnalysis(null);
    setPendingActions([]);
    loadLibraryStats();
  }, [selectedPath, loadSummary, loadLibraryStats]);

  const rebuildCatalog = async () => {
    if (librarySyncing) return;
    setLibrarySyncing(true);
    log("Rebuilding local asset catalog from CapCut cache...", "info");
    try {
      const res = await fetch(`${API}/catalog/build`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Catalog build failed");
      log(`Catalog rebuilt — ${data.total ?? 0} assets indexed`, "success");
      await loadLibraryStats();
      await loadStatus();
    } catch (e) {
      log(e instanceof Error ? e.message : "Catalog build failed", "error");
    } finally {
      setLibrarySyncing(false);
    }
  };

  const searchLibrary = async () => {
    setLibrarySearching(true);
    log(`Searching library: "${libraryQuery}"`, "info");
    try {
      const res = await fetch(
        `${API}/library/search?q=${encodeURIComponent(libraryQuery)}&type=${libraryType}&limit=15`
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Search failed");
      setLibraryResults(data.results ?? []);
      log(`Found ${data.count} result(s) in local catalog (${data.stats?.catalog_total ?? 0} total)`, "success");
      await loadLibraryStats();
    } catch (e) {
      log(e instanceof Error ? e.message : "Library search failed", "error");
    } finally {
      setLibrarySearching(false);
    }
  };

  const runAnalysis = async () => {
    if (!selectedPath || analyzing) return;
    analysisAbortRef.current?.abort();
    const ac = new AbortController();
    analysisAbortRef.current = ac;

    setAnalyzing(true);
    setError("");
    setRightTab("analysis");
    setAnalysisPanelTab("project");
    setAnalysisProgress(0);
    setAnalysisPhases({});
    setClipPreviews([]);
    setWaveformPeaks([]);
    setAudioMarkers([]);
    log("Analyzing project (video → audio → understand clips → fixes)…", "info");

    try {
      const res = await fetch(
        `${API}/analyze/stream?path=${encodeURIComponent(selectedPath)}&max_clips=8`,
        { method: "POST", signal: ac.signal }
      );
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Analysis failed");
      }

      await consumeSSE(res, (event) => {
        const type = event.type as string;
        if (type === "phase") {
          const id = String(event.id);
          setAnalysisProgress(Number(event.progress ?? 0));
          setAnalysisPhases((prev) => ({
            ...prev,
            [id]: {
              id,
              status: (event.status as "running" | "done" | "error") ?? "running",
              progress: Number(event.progress ?? 0),
              label: String(event.label ?? ""),
              detail: event.detail ? String(event.detail) : undefined,
            },
          }));
        } else if (type === "clip_preview") {
          setClipPreviews((prev) => [
            ...prev,
            {
              index: Number(event.index),
              name: String(event.name ?? ""),
              thumbnail: event.thumbnail ? String(event.thumbnail) : null,
              issues: (event.issues as string[]) ?? [],
            },
          ]);
        } else if (type === "clip_understanding") {
          const clip = event.clip as {
            index?: number;
            name?: string;
            content?: string;
            emotion?: string;
            suggested_use?: string;
            hook_strength?: number;
          };
          if (clip?.index != null) {
            setClipPreviews((prev) => {
              const existing = prev.find((p) => p.index === clip.index);
              const summary = [clip.content, clip.emotion, clip.suggested_use]
                .filter(Boolean)
                .join(" · ");
              const issues = summary ? [summary] : [];
              if (existing) {
                return prev.map((p) =>
                  p.index === clip.index ? { ...p, issues: [...p.issues, ...issues] } : p
                );
              }
              return [
                ...prev,
                { index: clip.index!, name: clip.name ?? `Clip ${clip.index}`, thumbnail: null, issues },
              ];
            });
          }
        } else if (type === "waveform") {
          setWaveformPeaks((event.peaks as number[]) ?? []);
          setAudioMarkers((event.markers as number[]) ?? []);
        } else if (type === "done") {
          const result = event.result as AnalysisResult;
          setAnalysis(result);
          log(`Analysis complete — score ${result.score}/100, ${result.clip_intelligence?.length ?? 0} clip(s) understood`, "success");
          setMessages((prev) => [...prev, {
            role: "assistant",
            content: `**Project analysis complete** (score ${result.score}/100)\n\n${result.clip_intelligence?.length ? `${result.clip_intelligence.length} clip(s) understood for smarter edits. ` : ""}${result.suggested_actions.length} auto-fix(es) ready in the Analysis panel. Say **apply analysis fixes** or click Apply all.`,
          }]);
        }
      });
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") {
        log("Analysis stopped", "info");
        return;
      }
      const msg = e instanceof Error ? e.message : "Analysis failed";
      setError(msg);
      log(msg, "error");
    } finally {
      setAnalyzing(false);
      analysisAbortRef.current = null;
    }
  };

  const applyAnalysisFixes = (actions: PendingAction[]) => {
    if (!actions.length || executing) return;
    setPendingActions(actions);
    setRightTab("analysis");
    log(`Loaded ${actions.length} fix(es) — scroll to amber Approve bar below chat`, "info");
  };

  const pushAgentLive = useCallback((patch: Partial<typeof agentLive>) => {
    flushSync(() => {
      setAgentLive((prev) => ({ ...prev, ...patch }));
    });
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const fetchEditPreview = async (actions: PendingAction[]) => {
    if (!selectedPath || !actions.length) return;
    try {
      const res = await fetch(`${API}/preview/edits`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_path: selectedPath, actions }),
      });
      if (res.ok) setEditDiff(await res.json());
    } catch { /* ignore */ }
  };

  const formatProposalLabel = (description: string, anchor?: { at_sec?: number; target?: string }) => {
    if (anchor?.at_sec != null) {
      const where = anchor.target ? ` · ${anchor.target}` : "";
      return `${description} @ ${Number(anchor.at_sec).toFixed(1)}s${where}`;
    }
    return description;
  };

  const patchStreamingAssistant = (patch: Partial<Message>) => {
    setMessages((prev) => {
      const idx = prev.findLastIndex((m) => m.role === "assistant" && m.streaming);
      if (idx < 0) return prev;
      const next = [...prev];
      next[idx] = { ...next[idx], ...patch };
      return next;
    });
  };

  const streamTeamSession = async (sessionId: string, initialTasks: TeamTask[] = []) => {
    const res = await fetch(`${API}/team/stream/${sessionId}`);
    if (!res.ok) throw new Error("Team stream failed");

    let steps: AgentStep[] = [];
    let proposals: string[] = [];
    let reply = "";
    let thinking = "";
    let tasks: TeamTask[] = initialTasks;

    await consumeSSE(res, (event) => {
      const type = event.type as string;
      if (type === "model_thinking_start") {
        const agent = event.agent ? String(event.agent) : "model";
        steps = upsertStep(steps, {
          id: "model_thinking",
          label: `Model reasoning — ${agent}`,
          status: "running",
          detail: "Streaming…",
        });
        flushSync(() =>
          patchStreamingAssistant({
            thinking: thinking || "",
            thinkingStreaming: true,
            thinkingAgent: agent,
            steps: [...steps],
          })
        );
      } else if (type === "model_thinking") {
        thinking += sseContent(event);
        steps = upsertStep(steps, {
          id: "model_thinking",
          label: "Model reasoning",
          status: "running",
          detail: thinking.length > 600 ? `…${thinking.slice(-600)}` : thinking,
        });
        flushSync(() =>
          patchStreamingAssistant({ thinking, thinkingStreaming: true, steps: [...steps] })
        );
      } else if (type === "model_thinking_end") {
        steps = upsertStep(steps, {
          id: "model_thinking",
          label: "Model reasoning",
          status: "done",
          detail: thinking || "Complete",
        });
        flushSync(() =>
          patchStreamingAssistant({ thinking: thinking || undefined, thinkingStreaming: false, steps: [...steps] })
        );
      } else if (type === "editor_timeline") {
        patchStreamingAssistant({
          editorReport: event.report as EditorTimelinePayload,
          streaming: true,
        });
      } else if (type === "route_decision") {
        const mode = String(event.mode ?? "");
        const reason = String(event.reason ?? "");
        pushAgentLive({
          routeMode: mode,
          routeReason: reason,
          title: String(event.label ?? "Routing…"),
        });
        steps = upsertStep(steps, {
          id: "orchestrator",
          label: String(event.label ?? "Orchestrator"),
          status: "done",
          detail: reason,
        });
        patchStreamingAssistant({ steps: [...steps] });
      } else if (type === "workflow" && event.workflow === "team" && event.session_id) {
        setTeamSessionId(String(event.session_id));
        pushAgentLive({ title: "Sequential team — one specialist at a time" });
      } else if (type === "agent_activity") {
        const anchor = event.anchor as { at_sec?: number; target?: string } | undefined;
        const at =
          anchor?.at_sec != null ? ` @ ${Number(anchor.at_sec).toFixed(1)}s` : "";
        const idx =
          event.index && event.total ? `[${event.index}/${event.total}] ` : "";
        const id = `activity_${String(event.agent)}_${event.index ?? steps.length}`;
        steps = upsertStep(steps, {
          id,
          label: `${idx}${event.agent}: ${event.phase}${at}`,
          status: event.phase === "ready" ? "done" : "running",
          detail: [
            event.detail ? String(event.detail) : "",
            anchor?.target ? `→ ${anchor.target}` : "",
          ]
            .filter(Boolean)
            .join(" "),
        });
        pushAgentLive({ steps: [...steps] });
        patchStreamingAssistant({ steps: [...steps], streaming: true });
      } else if (type === "team_start") {
        pushAgentLive({ title: "Sequential team session started" });
      } else if (type === "step") {
        steps = upsertStep(steps, {
          id: String(event.id),
          label: String(event.label),
          status: (event.status as AgentStep["status"]) ?? "running",
          detail: event.detail ? String(event.detail) : undefined,
        });
        pushAgentLive({ steps: [...steps] });
        patchStreamingAssistant({ steps: [...steps], streaming: true });
      } else if (type === "director_brief") {
        pushAgentLive({ title: "Director brief ready — planning tasks…" });
        patchStreamingAssistant({ content: "", streaming: true });
        if (Array.isArray(event.goals)) setTeamGoals(event.goals as TeamGoal[]);
      } else if (type === "task_queue") {
        tasks = (event.tasks as TeamTask[]) ?? tasks;
        setTeamTasks(tasks);
        pushAgentLive({ title: `Planner queued ${tasks.length} task(s)` });
      } else if (type === "team_plan") {
        const plan = event.plan as TeamPlanPayload;
        patchStreamingAssistant({ teamPlan: plan, content: "", proposals: [] });
      } else if (type === "task_started") {
        const task = event.task as TeamTask;
        if (task) {
          tasks = tasks.map((t) => (t.id === task.id ? { ...t, status: "running" } : t));
          setTeamTasks([...tasks]);
        }
      } else if (type === "task_proposed") {
        const task = event.task as TeamTask;
        if (task) {
          tasks = tasks.map((t) =>
            t.id === task.id ? { ...t, status: "awaiting_approval", qa_approved: true } : t
          );
          setTeamTasks([...tasks]);
          const anchor = event.anchor as { at_sec?: number; target?: string } | undefined;
          const desc = formatProposalLabel(
            task.description || task.instruction,
            anchor
          );
          if (!proposals.includes(desc)) proposals = [...proposals, desc];
          pushAgentLive({ proposals: [...proposals] });
        }
      } else if (type === "task_rejected") {
        const task = event.task as TeamTask;
        if (task) {
          tasks = tasks.map((t) => (t.id === task.id ? { ...t, status: "rejected" } : t));
          setTeamTasks([...tasks]);
        }
      } else if (type === "loop_paused") {
        setTeamPaused(true);
        pushAgentLive({ active: false, title: "Team paused — click Resume to continue" });
        patchStreamingAssistant({ streaming: false });
        log("Team paused by human", "info");
      } else if (type === "critic_note") {
        const note = String(event.content ?? "");
        setAgentLive((prev) => ({
          ...prev,
          criticNotes: prev.criticNotes.includes(note) ? prev.criticNotes : [...prev.criticNotes, note],
        }));
      } else if (type === "response_start") {
        patchStreamingAssistant({ content: "", streaming: true });
      } else if (type === "text_delta") {
        reply += sseContent(event);
        flushSync(() => patchStreamingAssistant({ content: reply, streaming: true }));
      } else if (type === "agent_message") {
        reply += sseContent(event);
        flushSync(() => patchStreamingAssistant({ content: reply, streaming: true }));
      } else if (type === "error") {
        throw new Error(String(event.message ?? "Team error"));
      } else if (type === "done") {
        setTeamPaused(false);
        reply = String(event.reply ?? reply);
        const actions = (event.pending_actions as PendingAction[]) ?? (event.actions as PendingAction[]) ?? [];
        const diff = (event.edit_diff as EditDiff | undefined) ?? null;
        const teamPlan = (event.team_plan as TeamPlanPayload | undefined) ?? undefined;
        const isAnswer = !teamPlan && actions.length === 0;
        setPendingActions(actions);
        if (diff) setEditDiff(diff);
        else if (actions.length) void fetchEditPreview(actions);
        patchStreamingAssistant({
          content: reply,
          thinking: String(event.thinking ?? thinking ?? "") || undefined,
          teamPlan,
          steps,
          proposals: teamPlan ? [] : proposals,
          streaming: false,
          thinkingStreaming: false,
          pendingActions: actions,
        });
        pushAgentLive({
          active: false,
          title: isAnswer
            ? "Answer ready"
            : tasks.length === 0
              ? "Team finished — no edits queued"
              : "Team plan ready — review & approve",
        });
        if (actions.length) log(`Team ready — ${actions.length} task(s) awaiting approval`, "success");
      }
    });
  };

  const pauseTeamSession = async () => {
    if (!teamSessionId) return;
    try {
      await fetch(`${API}/team/session/${teamSessionId}/pause`, { method: "POST" });
      setTeamPaused(true);
      log("Pausing team after current task…", "info");
    } catch {
      log("Pause request failed", "error");
    }
  };

  const resumeTeamSession = async () => {
    if (!teamSessionId || loading) return;
    setLoading(true);
    setTeamPaused(false);
    pushAgentLive({ active: true, title: "Resuming team session…" });
    try {
      await fetch(`${API}/team/session/${teamSessionId}/resume`, { method: "POST" });
      await streamTeamSession(teamSessionId, teamTasks);
    } catch (e) {
      const m = e instanceof Error ? e.message : "Resume failed";
      setError(m);
      log(m, "error");
    } finally {
      setLoading(false);
    }
  };

  const submitTeamFeedback = async () => {
    const text = teamFeedbackDraft.trim();
    if (!teamSessionId || !text) return;
    try {
      await fetch(`${API}/team/session/${teamSessionId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback: text }),
      });
      setTeamFeedbackDraft("");
      log(`Feedback sent to team: ${text.slice(0, 50)}`, "info");
    } catch {
      log("Feedback failed", "error");
    }
  };

  const rejectTeamTask = async (taskId: string) => {
    if (!teamSessionId) return;
    try {
      const res = await fetch(`${API}/team/session/${teamSessionId}/task/${taskId}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "Rejected by user" }),
      });
      if (res.ok) {
        // Find task details
        const task = teamTasks.find((t) => t.id === taskId);
        const taskDesc = task ? (task.description || task.instruction).trim() : "";
        
        setTeamTasks((prev) =>
          prev.map((t) => (t.id === taskId ? { ...t, status: "rejected" } : t))
        );
        
        if (taskDesc) {
          setPendingActions((prev) =>
            prev.filter((a) => (a.description || "").trim() !== taskDesc)
          );
        }
        
        log(`Rejected task: ${taskId.slice(0, 8)}`, "info");
      }
    } catch {
      log("Failed to reject task", "error");
    }
  };

  const sendMessageTeam = async (msg: string) => {
    if (!selectedPath) {
      setError("Select a project first");
      return;
    }

    setTeamSessionId(null);
    setTeamAutoEdit(false);
    setTeamTasks([]);
    setTeamGoals([]);
    setTeamPaused(false);
    pushAgentLive({
      active: true,
      title: "Director assembling the editing team…",
      steps: [],
      proposals: [],
      criticNotes: [],
      directorBrief: undefined,
    });

    try {
      const startRes = await fetch(`${API}/team/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, project_path: selectedPath }),
      });
      if (!startRes.ok) {
        const data = await startRes.json();
        throw new Error(data.detail || "Team start failed");
      }
      const session = await startRes.json();
      setTeamSessionId(session.id);
      setTeamGoals(session.goals ?? []);
      setTeamTasks(session.tasks ?? []);
      await streamTeamSession(session.id, session.tasks ?? []);
    } catch (e) {
      const m = e instanceof Error ? e.message : "Team error";
      setError(m);
      log(m, "error");
      patchStreamingAssistant({ content: m, streaming: false });
      pushAgentLive({ active: false, title: "Team error" });
    }
  };

  const handleAgentStreamEvent = (
    event: Record<string, unknown>,
    ctx: {
      steps: AgentStep[];
      proposals: string[];
      reply: string;
      thinking: string;
      thinkingStreaming: boolean;
      thinkingStartedAt: number | null;
      tasks: TeamTask[];
      patchAssistant: (patch: Partial<Message>) => void;
    }
  ) => {
    const type = event.type as string;
    let { steps, proposals, reply, tasks } = ctx;

    if (type === "model_thinking_start") {
      const agent = event.agent ? String(event.agent) : "model";
      if (!ctx.thinkingStreaming) {
        ctx.thinking = "";
        ctx.thinkingStartedAt = Date.now();
      }
      ctx.thinkingStreaming = true;
      steps = upsertStep(steps, {
        id: "model_thinking",
        label: `Model reasoning — ${agent}`,
        status: "running",
        detail: "Streaming…",
      });
      flushSync(() =>
        ctx.patchAssistant({
          thinking: ctx.thinking,
          thinkingStreaming: true,
          thinkingAgent: agent,
          thinkingStartedAt: ctx.thinkingStartedAt ?? Date.now(),
          steps: [...steps],
        })
      );
    } else if (type === "model_thinking") {
      ctx.thinking += sseContent(event);
      steps = upsertStep(steps, {
        id: "model_thinking",
        label: steps.find((s) => s.id === "model_thinking")?.label ?? "Model reasoning",
        status: "running",
        detail: ctx.thinking.length > 600 ? `…${ctx.thinking.slice(-600)}` : ctx.thinking,
      });
      flushSync(() =>
        ctx.patchAssistant({
          thinking: ctx.thinking,
          thinkingStreaming: true,
          steps: [...steps],
        })
      );
    } else if (type === "model_thinking_end") {
      const thinkingSeconds =
        ctx.thinkingStartedAt != null
          ? (Date.now() - ctx.thinkingStartedAt) / 1000
          : undefined;
      ctx.thinkingStreaming = false;
      steps = upsertStep(steps, {
        id: "model_thinking",
        label: steps.find((s) => s.id === "model_thinking")?.label ?? "Model reasoning",
        status: "done",
        detail: ctx.thinking
          ? ctx.thinking.length > 800
            ? `…${ctx.thinking.slice(-800)}`
            : ctx.thinking
          : "Complete",
      });
      flushSync(() =>
        ctx.patchAssistant({
          thinking: ctx.thinking || undefined,
          thinkingStreaming: false,
          thinkingSeconds,
          steps: [...steps],
        })
      );
    } else if (type === "editor_timeline") {
      ctx.patchAssistant({
        editorReport: event.report as EditorTimelinePayload,
        streaming: true,
      });
    } else if (type === "auto_edit_start") {
      const label = String(event.label ?? "Auto edit");
      pushAgentLive({ title: label, routeMode: "auto_edit" });
      steps = upsertStep(steps, {
        id: "auto_edit",
        label,
        status: "running",
        detail: event.hint ? String(event.hint) : "Pro full-timeline edit — all chapters",
      });
      ctx.patchAssistant({ steps: [...steps], streaming: true });
    } else if (type === "route_decision") {
      pushAgentLive({
        routeMode: String(event.mode ?? ""),
        routeReason: String(event.reason ?? ""),
        title: String(event.label ?? "Routing…"),
      });
      steps = upsertStep(steps, {
        id: "orchestrator",
        label: String(event.label ?? "Orchestrator"),
        status: "done",
        detail: String(event.reason ?? ""),
      });
      ctx.patchAssistant({ steps: [...steps] });
    } else if (type === "workflow" && event.workflow === "team" && event.session_id) {
      const isAuto = Boolean(event.auto_edit);
      setTeamSessionId(String(event.session_id));
      setTeamAutoEdit(isAuto);
      pushAgentLive({
        title: isAuto
          ? "Auto edit — Director → all chapters → one approve"
          : "Sequential team — specialists run one-by-one",
      });
      if (isAuto) {
        steps = upsertStep(steps, {
          id: "auto_edit",
          label: "Auto edit pipeline",
          status: "running",
        });
        ctx.patchAssistant({ steps: [...steps], streaming: true });
      }
    } else if (type === "chapter_map") {
      const chs = (event.chapters as typeof teamChapters) ?? [];
      setTeamChapters(chs);
      steps = upsertStep(steps, {
        id: "director_chapters",
        label: `Director — ${chs.length} chapter(s) mapped`,
        status: "done",
        detail: chs.map((c) => c.label).join(" → "),
      });
      pushAgentLive({ steps: [...steps], title: "Chapter structure ready" });
      ctx.patchAssistant({ steps: [...steps], streaming: true });
    } else if (type === "chapter_started") {
      const ch = event.chapter as { label?: string; index?: number };
      const idx = event.index as number;
      const total = event.total as number;
      steps = upsertStep(steps, {
        id: `chapter_${idx}`,
        label: `Scene Planner — ${ch?.label ?? `Chapter ${idx}`} (${idx}/${total})`,
        status: "running",
      });
      pushAgentLive({ steps: [...steps] });
      ctx.patchAssistant({ steps: [...steps], streaming: true });
    } else if (type === "chapter_planned") {
      const ch = event.chapter as { label?: string };
      const idx = event.index as number;
      const taskCount = event.task_count as number;
      steps = upsertStep(steps, {
        id: `chapter_${idx}`,
        label: `Scene Planner — ${ch?.label ?? `Chapter ${idx}`}`,
        status: "done",
        detail: `${taskCount} task(s) queued`,
      });
      pushAgentLive({ steps: [...steps] });
      ctx.patchAssistant({ steps: [...steps], streaming: true });
    } else if (type === "agent_activity") {
      const anchor = event.anchor as { at_sec?: number; target?: string } | undefined;
      const at = anchor?.at_sec != null ? ` @ ${Number(anchor.at_sec).toFixed(1)}s` : "";
      const idx = event.index && event.total ? `[${event.index}/${event.total}] ` : "";
      steps = upsertStep(steps, {
        id: `activity_${String(event.agent)}_${event.index ?? steps.length}`,
        label: `${idx}${event.agent}: ${event.phase}${at}`,
        status: event.phase === "ready" ? "done" : "running",
        detail: [event.detail, anchor?.target ? `→ ${anchor.target}` : ""]
          .filter(Boolean)
          .map(String)
          .join(" "),
      });
      pushAgentLive({ steps: [...steps] });
      ctx.patchAssistant({ steps: [...steps], streaming: true });
    } else if (type === "phase" && event.id === "understand") {
      steps = upsertStep(steps, {
        id: "understand",
        label: String(event.label ?? "Understanding clips"),
        status: (event.status as AgentStep["status"]) ?? "running",
        detail: event.detail ? String(event.detail) : undefined,
      });
      pushAgentLive({ steps: [...steps], title: String(event.label ?? "Understanding clips…") });
      ctx.patchAssistant({ steps: [...steps], streaming: true });
    } else if (type === "team_start") {
      pushAgentLive({ title: "Sequential team session" });
    } else if (type === "step") {
      steps = upsertStep(steps, {
        id: String(event.id),
        label: String(event.label),
        status: (event.status as AgentStep["status"]) ?? "running",
        detail: event.detail ? String(event.detail) : undefined,
      });
      pushAgentLive({ steps: [...steps] });
      ctx.patchAssistant({ steps: [...steps], streaming: true });
      if (event.status === "done") log(String(event.label), "success");
    } else if (type === "tool_call") {
      const id = `tool_${event.name}`;
      steps = upsertStep(steps, {
        id,
        label: `Tool: ${event.name}`,
        status: "running",
        detail: JSON.stringify(event.args ?? {}).slice(0, 80),
      });
      pushAgentLive({ steps: [...steps] });
      ctx.patchAssistant({ steps: [...steps] });
    } else if (type === "tool_result") {
      const id = `tool_${event.name}`;
      steps = upsertStep(steps, {
        id,
        label: `Tool: ${event.name}`,
        status: "done",
        detail: String(event.summary ?? ""),
      });
      pushAgentLive({ steps: [...steps] });
      ctx.patchAssistant({ steps: [...steps] });
    } else if (type === "director_brief") {
      const md = String(event.markdown ?? "");
      pushAgentLive({ directorBrief: md, title: "Director brief ready" });
      if (Array.isArray(event.goals)) setTeamGoals(event.goals as TeamGoal[]);
      ctx.patchAssistant({ content: md ? md + "\n\n_Planning tasks…_" : "", streaming: true });
    } else if (type === "task_queue") {
      tasks = (event.tasks as TeamTask[]) ?? tasks;
      setTeamTasks(tasks);
    } else if (type === "team_plan") {
      ctx.patchAssistant({ teamPlan: event.plan as TeamPlanPayload, proposals: [] });
    } else if (type === "task_proposed") {
      const task = event.task as TeamTask;
      const anchor = event.anchor as { at_sec?: number; target?: string } | undefined;
      if (task) {
        const desc = formatProposalLabel(task.description || task.instruction, anchor);
        if (!proposals.includes(desc)) proposals = [...proposals, desc];
        pushAgentLive({ proposals: [...proposals] });
      }
    } else if (type === "critic_note") {
      const note = String(event.content ?? "");
      setAgentLive((prev) => ({
        ...prev,
        criticNotes: prev.criticNotes.includes(note) ? prev.criticNotes : [...prev.criticNotes, note],
      }));
    } else if (type === "proposal") {
      const anchor = event.anchor as { at_sec?: number; target?: string } | undefined;
      const desc = formatProposalLabel(String(event.description ?? ""), anchor);
      if (!proposals.includes(desc)) proposals = [...proposals, desc];
      pushAgentLive({ proposals: [...proposals] });
      ctx.patchAssistant({ proposals: [...proposals] });
    } else if (type === "response_start") {
      reply = "";
      ctx.patchAssistant({ content: "", streaming: true });
    } else if (type === "text_delta" || type === "agent_message") {
      reply += sseContent(event);
      flushSync(() => ctx.patchAssistant({ content: reply, streaming: true }));
    } else if (type === "error") {
      throw new Error(String(event.message ?? "Agent error"));
    } else if (type === "done") {
      reply = String(event.reply ?? reply);
      const finalThinking = String(event.thinking ?? ctx.thinking ?? "").trim();
      if (finalThinking) ctx.thinking = finalThinking;
      const actions = (event.pending_actions as PendingAction[]) ?? (event.actions as PendingAction[]) ?? [];
      const diff = (event.edit_diff as EditDiff | undefined) ?? null;
      const teamPlan = (event.team_plan as TeamPlanPayload | undefined) ?? undefined;
      setPendingActions(actions);
      if (diff) {
        setEditDiff(diff);
      } else if (actions.length) {
        void fetchEditPreview(actions);
      }
      ctx.patchAssistant({
        content: reply,
        thinking: finalThinking || ctx.thinking || undefined,
        teamPlan,
        steps,
        proposals: teamPlan ? [] : proposals,
        streaming: false,
        thinkingStreaming: false,
        pendingActions: actions,
      });
        // keep editorReport on message
      pushAgentLive({
        active: false,
        title: teamPlan
          ? teamPlan.approved_tasks?.length
            ? "Team plan ready — review & approve"
            : "Team finished — no edits queued"
          : actions.length
            ? "Review & approve"
            : "Done",
      });
    }

    ctx.steps = steps;
    ctx.proposals = proposals;
    ctx.reply = reply;
    ctx.tasks = tasks;
  };

  const sendMessage = async (
    text?: string,
    opts?: { autoEdit?: boolean },
  ) => {
    const autoEdit = opts?.autoEdit ?? false;
    const hint = (text ?? input).trim();
    const msg = autoEdit
      ? hint || "Travel vlog — captions, music, transitions"
      : hint;
    if (!msg || loading || autoEditing) return;
    if (!selectedPath) {
      setError("Select a CapCut project in the sidebar first — timeline visuals need project data.");
      return;
    }

    const userDisplay = autoEdit
      ? `**Auto edit**${hint ? ` — ${hint}` : " — pro full timeline"}`
      : msg;

    setMessages((prev) => [
      ...prev,
      { role: "user", content: userDisplay },
      { role: "assistant", content: "", steps: [], proposals: [], editorReport: null, streaming: true },
    ]);
    setInput("");
    setLoading(true);
    if (autoEdit) setAutoEditing(true);
    setError("");
    setPendingActions([]);
    setTeamSessionId(null);
    setTeamAutoEdit(false);
    setTeamTasks([]);
    setTeamGoals([]);
    setTeamChapters([]);
    pushAgentLive({
      active: true,
      title: autoEdit ? "Starting auto edit…" : "Understanding your request…",
      steps: [],
      proposals: [],
      criticNotes: [],
      directorBrief: undefined,
      routeMode: autoEdit ? "auto_edit" : undefined,
      routeReason: undefined,
    });
    log(autoEdit ? `Auto edit: ${msg.slice(0, 60)}` : `You: ${msg.slice(0, 60)}${msg.length > 60 ? "..." : ""}`);

    const patchAssistant = (patch: Partial<Message>) => {
      setMessages((prev) => {
        const idx = prev.findLastIndex((m) => m.role === "assistant" && m.streaming);
        if (idx < 0) return prev;
        const next = [...prev];
        next[idx] = { ...next[idx], ...patch };
        return next;
      });
    };

    try {
      const res = await fetch(`${API}/agent/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: msg,
          project_path: selectedPath || undefined,
          force_team: teamMode && !autoEdit,
          auto_edit: autoEdit,
        }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Agent failed");
      }

      const ctx = {
        steps: [] as AgentStep[],
        proposals: [] as string[],
        reply: "",
        thinking: "",
        thinkingStreaming: false,
        thinkingStartedAt: null as number | null,
        tasks: [] as TeamTask[],
        patchAssistant,
      };

      await consumeSSE(res, (event) => handleAgentStreamEvent(event, ctx));
    } catch (e) {
      const m = e instanceof Error ? e.message : "Error";
      setError(m);
      log(m, "error");
      patchAssistant({ content: m, streaming: false });
      pushAgentLive({ active: false, title: "Agent error" });
    } finally {
      setLoading(false);
      setAutoEditing(false);
    }
  };

  const runAutoEdit = () => {
    if (!selectedPath || loading || autoEditing) return;
    sendMessage(undefined, { autoEdit: true });
  };

  const executeTeamApprove = async () => {
    const actionsToApply = [...pendingActions];
    if (!selectedPath || !actionsToApply.length || executing) return;
    setExecuting(true);
    setPendingActions([]);
    setEditDiff(null);
    setError("");
    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: "", steps: [], streaming: true },
    ]);
    pushAgentLive({
      active: true,
      title: status?.capcut_running ? "Applying team tasks with live reload…" : "Applying team plan…",
      steps: [],
      proposals: [],
    });
    log("Applying team-approved tasks one-by-one…", "info");

    const patchApply = (patch: Partial<Message>) => {
      setMessages((prev) => {
        const idx = prev.findLastIndex((m) => m.role === "assistant" && m.streaming);
        if (idx < 0) return prev;
        const next = [...prev];
        next[idx] = { ...next[idx], ...patch };
        return next;
      });
    };

    try {
      const sessionId = teamSessionId ?? "expired";
      const res = await fetch(`${API}/team/session/${sessionId}/approve/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_path: selectedPath,
          actions: actionsToApply,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Team apply failed");
      }

      let steps: AgentStep[] = [];
      let reply = "";
      let wasQueued = false;

      await consumeSSE(res, (event) => {
        const type = event.type as string;
        if (type === "step") {
          steps = upsertStep(steps, {
            id: String(event.id),
            label: String(event.label),
            status: (event.status as AgentStep["status"]) ?? "running",
            detail: event.detail ? String(event.detail) : undefined,
          });
          pushAgentLive({ steps: [...steps] });
          patchApply({ steps: [...steps] });
        } else if (type === "task_applied") {
          const taskId = String(event.task_id ?? "");
          if (taskId) {
            setTeamTasks((prev) =>
              prev.map((t) => (t.id === taskId ? { ...t, status: "done" } : t))
            );
          }
        } else if (type === "error") {
          throw new Error(String(event.message ?? "Team apply failed"));
        } else if (type === "done") {
          reply = String(event.reply ?? "");
          patchApply({ content: reply, steps, streaming: false });
          if (event.queued) {
            wasQueued = true;
            setQueueWaiting(true);
            log("Team tasks queued — click Home in CapCut or grant Accessibility", "info");
          }
        }
      });

      pushAgentLive({
        active: wasQueued,
        title: wasQueued ? "Waiting for CapCut to unlock…" : "Team apply complete",
      });
      if (!wasQueued) log("Team edits applied in CapCut", "success");
      loadSummary(selectedPath);
      loadStatus();
    } catch (e) {
      const m = e instanceof Error ? e.message : "Team apply failed";
      setError(m);
      log(m, "error");
      patchApply({ content: m, streaming: false });
      pushAgentLive({ active: false });
    } finally {
      setExecuting(false);
    }
  };

  const executeActions = async (actions: PendingAction[]) => {
    if (!selectedPath || !actions.length || executing) return;
    setExecuting(true);
    setPendingActions([]);
    setEditDiff(null);
    setError("");
    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: "", steps: [], streaming: true },
    ]);
    pushAgentLive({
      active: true,
      title: status?.capcut_running ? "Queuing edits…" : `Applying ${actions.length} change(s)…`,
      steps: [],
      proposals: [],
    });
    log(`Applying ${actions.length} change(s) to CapCut project...`, "info");

    const patchApply = (patch: Partial<Message>) => {
      setMessages((prev) => {
        const idx = prev.findLastIndex((m) => m.role === "assistant" && m.streaming);
        if (idx < 0) return prev;
        const next = [...prev];
        next[idx] = { ...next[idx], ...patch };
        return next;
      });
    };

    try {
      const res = await fetch(`${API}/execute/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_path: selectedPath, actions }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Execute failed");
      }

      let steps: AgentStep[] = [];
      let reply = "";
      let wasQueued = false;

      await consumeSSE(res, (event) => {
        const type = event.type as string;
        if (type === "step") {
          steps = upsertStep(steps, {
            id: String(event.id),
            label: String(event.label),
            status: (event.status as AgentStep["status"]) ?? "running",
            detail: event.detail ? String(event.detail) : undefined,
          });
          pushAgentLive({ steps: [...steps] });
          patchApply({ steps: [...steps] });
        } else if (type === "error") {
          throw new Error(String(event.message ?? "Execute failed"));
        } else if (type === "done") {
          reply = String(event.reply ?? "");
          patchApply({ content: reply, steps, streaming: false });
          if (event.queued) {
            wasQueued = true;
            setQueueWaiting(true);
            log("Queued — click Home in CapCut or grant Accessibility to auto-apply", "info");
          }
        }
      });

      pushAgentLive({
        active: wasQueued,
        title: wasQueued ? "Waiting for CapCut to quit…" : "Apply complete",
      });
      if (!wasQueued) log(`Applied ${actions.length} change(s)`, "success");
      loadSummary(selectedPath);
      loadStatus();
    } catch (e) {
      const m = e instanceof Error ? e.message : "Execute failed";
      setError(m);
      log(m, "error");
      patchApply({ content: m, streaming: false });
      pushAgentLive({ active: false });
    } finally {
      setExecuting(false);
    }
  };

  useEffect(() => {
    if (!queueWaiting) return;
    const poll = setInterval(async () => {
      try {
        const res = await fetch(`${API}/queue/status`);
        const data = await res.json();
        if (data.status === "done") {
          setQueueWaiting(false);
          setMessages((prev) => [...prev, { role: "assistant", content: data.message || "Edits applied." }]);
          log("Auto-applied queued edits — CapCut reopening", "success");
          loadSummary(selectedPath);
          loadStatus();
        } else if (data.status === "failed") {
          setQueueWaiting(false);
          setError(data.message || "Auto-apply failed");
        } else if (data.status === "applying") {
          pushAgentLive({ active: true, title: "CapCut closed — applying edits now…" });
        }
      } catch { /* ignore */ }
    }, 1500);
    return () => clearInterval(poll);
  }, [queueWaiting, selectedPath, loadStatus, log, pushAgentLive, loadSummary]);

  const rejectActions = async () => {
    setPendingActions([]);
    setEditDiff(null);
    setTeamSessionId(null);
    setTeamAutoEdit(false);
    setTeamTasks([]);
    await fetch(`${API}/reject`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    log("Changes rejected", "info");
  };

  const restoreBackup = async () => {
    if (!selectedPath || executing) return;
    setExecuting(true);
    setError("");
    log("Restoring cleaned edits from backup (CapCut must be quit)...", "info");
    try {
      const res = await fetch(
        `${API}/project/restore-backup?path=${encodeURIComponent(selectedPath)}`,
        { method: "POST" }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Restore failed");
      setMessages((prev) => [...prev, { role: "assistant", content: data.message }]);
      log(data.message, "success");
      loadSummary(selectedPath);
    } catch (e) {
      const m = e instanceof Error ? e.message : "Restore failed";
      setError(m);
      log(m, "error");
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="relative flex h-screen bg-[#0e0e10] text-white p-4 gap-4 overflow-hidden font-sans">
      <div className="absolute inset-0 pointer-events-none overflow-hidden z-0" aria-hidden>
        <div className="absolute -top-48 left-1/2 -translate-x-1/2 w-[560px] h-[360px] rounded-full bg-[#00cbd6]/6 blur-[100px]" />
      </div>

      {/* Left — Project */}
      <aside className="w-80 glass-panel rounded-2xl flex flex-col shrink-0 overflow-hidden z-10">
        <div className="p-4 border-b border-white/5">
          <p className="text-[10px] font-semibold text-capcut uppercase tracking-wider">Project</p>
          <div className="relative mt-2">
            <select
              className="input-field w-full text-xs px-3 py-2.5 cursor-pointer appearance-none"
              value={selectedPath}
              onChange={(e) => setSelectedPath(e.target.value)}
            >
              <option value="">Select CapCut project...</option>
              {projects.map((p) => (
                <option key={p.id} value={p.path}>{p.name}</option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3 text-white/40 text-[10px]">
              ▼
            </div>
          </div>
          {selectedPath && (
            <div className="mt-4 space-y-2">
              <button
                onClick={runAutoEdit}
                disabled={autoEditing || loading || !selectedPath}
                className="btn-primary w-full text-xs py-2.5 cursor-pointer bg-gradient-to-r from-[#00cbd6] to-[#0099a8] hover:from-[#00dce8] hover:to-[#00a8b8] border-0"
              >
                {autoEditing ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="h-3.5 w-3.5 rounded-full border-2 border-white/20 border-t-white animate-spin" />
                    Auto editing…
                  </span>
                ) : (
                  "Auto Edit Project"
                )}
              </button>
              <p className="text-[10px] text-white/40 leading-relaxed px-0.5">
                Director plans all chapters → specialists → one approve. Optional vibe in chat first.
              </p>
              <button
                onClick={runAnalysis}
                disabled={analyzing}
                className="btn-secondary w-full text-xs py-2.5 cursor-pointer"
              >
                {analyzing ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="h-3.5 w-3.5 rounded-full border-2 border-white/20 border-t-white animate-spin" />
                    Analyzing Timeline...
                  </span>
                ) : (
                  "Analyze Video & Audio"
                )}
              </button>
              <button
                onClick={restoreBackup}
                disabled={executing || (status?.capcut_running ?? false)}
                className="btn-secondary w-full text-xs py-2 disabled:opacity-30 cursor-pointer"
              >
                Restore from backup
              </button>
            </div>
          )}
        </div>

        <div className="px-4 py-3 border-b border-white/5 space-y-1.5">
          <StatusRow label="Agent" ok={connected} detail={connected ? "Online" : "Offline"} />
          <StatusRow label="FFmpeg" ok={status?.ffmpeg ?? false} detail={status?.ffmpeg ? "Ready" : "Not found"} />
          <StatusRow label="Asset Catalog" ok={(status?.catalog_total ?? 0) > 0} detail={`${status?.catalog_total ?? 0} indexed`} />
          <StatusRow label="CapCut CDP" ok={status?.cdp_connected ?? false} detail={status?.cdp_connected ? "Live reload" : "Offline"} />
          <StatusRow label="CapCut app" ok={status?.capcut_running ?? false} detail={status?.capcut_running ? "Running" : "Not running"} />
          <StatusRow
            label="Whisper captions"
            ok={status?.whisper?.available ?? false}
            detail={
              status?.whisper?.available
                ? "Ready"
                : (status?.whisper?.install_hint ?? "Unavailable")
            }
          />
        </div>

        {summary && (
          <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
            <div className="grid grid-cols-2 gap-2">
              <MiniStat label="Duration" value={`${summary.overview?.duration_sec ?? 0}s`} />
              <MiniStat label="Clips" value={String(summary.overview?.video_clip_count ?? 0)} />
              <MiniStat label="Texts" value={String(summary.overview?.text_overlay_count ?? 0)} />
              <MiniStat label="FPS" value={String(summary.overview?.fps ?? "—")} />
            </div>
            <div className="space-y-1.5 pt-2">
              <p className="text-[10px] uppercase tracking-wider text-white/40 font-semibold mb-2">Timeline</p>
              {summary.video_clips?.slice(0, 5).map((v) => (
                <div key={v.segment_id} className="flex justify-between items-center bg-white/[0.02] border border-white/5 rounded-lg px-2.5 py-1.5 text-[10px] text-white/60 hover:text-white/85 transition-colors truncate">
                  <span className="text-capcut font-semibold shrink-0 tabular-nums">{v.at_sec}s</span>
                  <span className="truncate ml-2 text-right">{v.name}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>

      {/* Center — Chat */}
      <div className="glass-panel rounded-2xl flex flex-col flex-1 min-w-0 overflow-hidden z-10">
        <header className="px-5 py-3.5 border-b border-white/5 flex items-center gap-3 flex-wrap">
          <div>
            <h1 className="font-semibold text-sm">CapCut AI Editor</h1>
            <p className="text-[11px] text-white/45 mt-0.5">Talk to your timeline — no manual clicking</p>
          </div>
          <label className="ml-auto flex items-center gap-2 text-xs cursor-pointer text-white/70">
            <input
              type="checkbox"
              checked={teamMode}
              onChange={(e) => setTeamMode(e.target.checked)}
              className="rounded accent-[#00cbd6]"
            />
            <span className="font-medium text-white/85">Force team</span>
            <span className="text-capcut text-[10px]">Big re-edits only — simple edits use edit agent</span>
          </label>
        </header>

        {error && (
          <div className="mx-5 mt-4 px-4 py-3 alert-error rounded-xl text-xs flex items-start gap-2">
            <span className="font-medium shrink-0">Error</span>
            <span className="flex-1 leading-relaxed opacity-90">{error}</span>
          </div>
        )}

        {(agentLive.active || teamPaused) && (
          <div className="mx-5 mt-4 p-4 trace-panel">
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <span className={`w-2 h-2 rounded-full bg-capcut ${agentLive.active ? "animate-pulse" : ""}`} />
              <p className="text-xs font-semibold text-white/90">{agentLive.title}</p>
              {agentLive.routeMode && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-capcut/15 text-capcut border border-capcut/25">
                  {agentLive.routeMode}
                </span>
              )}
            </div>
            {agentLive.routeReason && (
              <p className="text-[11px] text-white/45 mb-3 leading-relaxed">{agentLive.routeReason}</p>
            )}
            {agentLive.directorBrief && (
              <div className="mt-3 pt-3 border-t border-white/5">
                <p className="text-[10px] uppercase tracking-wider text-capcut font-semibold mb-1.5">Director brief</p>
                <div className="text-xs text-white/80 leading-relaxed whitespace-pre-wrap max-h-36 overflow-y-auto bg-black/25 border border-white/5 rounded-xl p-3">
                  {agentLive.directorBrief}
                </div>
              </div>
            )}
            {agentLive.criticNotes.length > 0 && (
              <div className="mt-3 pt-3 border-t border-white/5">
                <p className="text-[10px] uppercase tracking-wider text-rose-400/90 font-semibold mb-1.5">Critic review</p>
                <ul className="text-xs text-white/65 space-y-1 bg-rose-500/5 border border-rose-500/10 rounded-xl p-3">
                  {agentLive.criticNotes.map((n, i) => <li key={i}>• {n}</li>)}
                </ul>
              </div>
            )}
            {agentLive.proposals.length > 0 && (
              <div className="mt-3 pt-3 border-t border-white/5">
                <p className="text-[10px] uppercase tracking-wider text-capcut font-semibold mb-1.5">Proposals</p>
                <ul className="text-xs text-white/75 space-y-1 max-h-28 overflow-y-auto bg-black/25 border border-white/5 rounded-xl p-3">
                  {agentLive.proposals.map((p, i) => <li key={i}>• {p}</li>)}
                </ul>
              </div>
            )}
            {teamChapters.length > 0 && (
              <div className="mt-3 pt-3 border-t border-white/5">
                <p className="text-[10px] uppercase tracking-wider text-capcut font-semibold mb-1.5">
                  Chapters
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {teamChapters.map((ch) => (
                    <span
                      key={ch.id ?? ch.index}
                      className="text-[10px] px-2 py-1 rounded-lg bg-white/[0.04] border border-white/[0.06] text-white/70"
                    >
                      {ch.index}. {ch.label}
                      {ch.start_sec != null && (
                        <span className="text-white/35 ml-1">
                          {ch.start_sec.toFixed(0)}–{ch.end_sec?.toFixed(0)}s
                        </span>
                      )}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <TaskQueuePanel
              tasks={teamTasks}
              goals={teamGoals}
              streaming={agentLive.active && !teamPaused}
              paused={teamPaused}
              onPause={teamSessionId && loading ? pauseTeamSession : undefined}
              onResume={teamSessionId && teamPaused ? resumeTeamSession : undefined}
              feedbackDraft={teamFeedbackDraft}
              onFeedbackChange={setTeamFeedbackDraft}
              onFeedback={teamSessionId ? submitTeamFeedback : undefined}
              onRejectTask={teamSessionId ? rejectTeamTask : undefined}
            />
          </div>
        )}

        {queueWaiting && (
          <div className="mx-5 mt-4 p-4 alert-success rounded-xl text-xs flex flex-col gap-2">
            <div className="flex items-center gap-2 font-medium">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span>Edits queued</span>
            </div>
            <p className="leading-relaxed">
              ⏳ Edits queued — applying when CapCut unlocks (~2s).
              {status?.accessibility_host_app && !status?.accessibility_enabled && (
                <> Enable <strong>{status.accessibility_host_app}</strong> in System Settings → Privacy → Accessibility (not CapCut), then restart that app.</>
              )}
              {status?.accessibility_enabled && (
                <> Accessibility is on — agent uses CapCut menu <strong>Back to home page</strong> automatically on Approve.</>
              )}
            </p>
          </div>
        )}

        {pendingActions.length > 0 && (
          <div className="mx-5 mt-4 p-4 alert-warning rounded-xl">
            <p className="text-xs font-medium mb-1">
              Review {pendingActions.length} proposed change{pendingActions.length > 1 ? "s" : ""}
            </p>
            <p className="text-[11px] opacity-75 leading-relaxed mb-4">
              Approve briefly closes the project in CapCut, writes edits, then reopens it.
            </p>

            {editDiff && editDiff.rows.length > 0 && (
              <div className="mb-4 rounded-xl border border-white/[0.06] bg-black/45 overflow-hidden">
                <div className="px-3.5 py-2.5 bg-white/[0.02] text-[10px] uppercase font-bold tracking-wider text-white/50 border-b border-white/[0.04]">
                  Before &amp; After Comparison
                </div>
                <div className="px-3.5 py-2 text-[10px] text-white/40 flex gap-4 border-b border-white/[0.04] bg-white/[0.01]">
                  <span>Transitions: <strong className="text-white/70">{editDiff.overview.transitions_before} → {editDiff.overview.transitions_after}</strong></span>
                  <span className="truncate">Music: <strong className="text-white/70">{editDiff.overview.music_before || "None"} → {editDiff.overview.music_after}</strong></span>
                </div>
                <div className="max-h-56 overflow-y-auto">
                  <table className="w-full text-xs text-left border-collapse">
                    <thead className="text-[10px] text-white/40 uppercase tracking-wider sticky top-0 bg-neutral-900 border-b border-white/[0.04]">
                      <tr>
                        <th className="px-3.5 py-2 font-medium">Type</th>
                        <th className="px-3.5 py-2 font-medium">Target</th>
                        <th className="px-3.5 py-2 font-medium text-right">Before</th>
                        <th className="px-3.5 py-2 font-medium text-right">After</th>
                      </tr>
                    </thead>
                    <tbody className="text-white/80">
                      {editDiff.rows.map((row, i) => (
                        <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.01]">
                          <td className="px-3.5 py-2.5 font-medium whitespace-nowrap text-white/60">{row.category}</td>
                          <td className="px-3.5 py-2.5 max-w-[150px] truncate text-white/80" title={row.target}>{row.target}</td>
                          <td className="px-3.5 py-2.5 text-right text-rose-400/80 font-mono text-[11px]">{row.before || "—"}</td>
                          <td className="px-3.5 py-2.5 text-right text-emerald-400 font-mono text-[11px]">{row.after}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <ul className="text-xs text-amber-100/75 space-y-1 mb-4 bg-amber-500/5 border border-amber-500/10 rounded-xl p-3">
              {pendingActions.map((a, i) => (
                <li key={i} className="leading-relaxed">• {a.description}</li>
              ))}
            </ul>
            <div className="flex gap-2 flex-wrap">
              <button
                onClick={() =>
                  teamSessionId && pendingActions.length
                    ? executeTeamApprove()
                    : executeActions(pendingActions)
                }
                disabled={executing}
                className="btn-primary px-4 py-2 text-xs cursor-pointer"
              >
                {executing
                  ? "Applying…"
                  : teamSessionId && teamAutoEdit
                    ? "Approve auto edit in CapCut"
                    : teamSessionId
                      ? "Approve team plan in CapCut"
                      : "Approve & apply"}
              </button>
              <button onClick={rejectActions} className="btn-secondary px-4 py-2 text-xs cursor-pointer">
                Reject
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full max-w-md mx-auto text-center space-y-5 px-4">
              <div className="space-y-2">
                <p className="text-sm font-medium text-white/95">What should we edit?</p>
                <p className="text-xs text-white/55 leading-relaxed">
                  Ask anything about your timeline, or describe edits. The orchestrator routes to Q&A, a single edit agent, or a sequential team for big jobs.
                </p>
              </div>
              {selectedPath && (
                <div className="flex flex-wrap gap-2 justify-center pt-1">
                  {QUICK_PROMPTS.map((p) => (
                    <button key={p} onClick={() => sendMessage(p)} className="chip">
                      {p}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {messages.map((msg, i) => {
            const isStreamingTeamMessage =
              msg.role === "assistant" &&
              msg.streaming &&
              teamSessionId &&
              (agentLive.active || teamPaused) &&
              !msg.content &&
              !(msg.steps?.length);
            return (
              <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                {msg.role === "user" ? (
                  <div className="max-w-2xl px-4 py-3 text-xs leading-relaxed msg-user">{msg.content}</div>
                ) : (
                  <div className="max-w-3xl w-full msg-assistant px-1 py-1">
                    {isStreamingTeamMessage ? (
                      <p className="text-white/50 text-xs animate-pulse flex items-center gap-2 px-3 py-2">
                        <span className="h-3 w-3 rounded-full border-2 border-[#00cbd6] border-t-transparent animate-spin shrink-0" />
                        {teamPaused
                          ? "Team session paused. Resume or provide feedback in the panel."
                          : "Multi-agent team planning…"}
                      </p>
                    ) : msg.teamPlan ? (
                      <div className="space-y-2">
                        <AssistantMessage
                          steps={msg.steps}
                          thinking={msg.thinking}
                          thinkingStreaming={msg.thinkingStreaming}
                          thinkingSeconds={msg.thinkingSeconds}
                          agent={msg.thinkingAgent}
                          editorReport={msg.editorReport}
                          streaming={msg.streaming}
                        />
                        <TeamPlanCard plan={msg.teamPlan} summary={msg.content} />
                      </div>
                    ) : (
                      <AssistantMessage
                        content={msg.content}
                        thinking={msg.thinking}
                        thinkingStreaming={msg.thinkingStreaming}
                        thinkingSeconds={msg.thinkingSeconds}
                        agent={msg.thinkingAgent}
                        steps={msg.steps}
                        proposals={msg.proposals}
                        editorReport={msg.editorReport}
                        streaming={msg.streaming}
                        waiting={msg.streaming && !msg.content && !msg.thinking && (msg.steps?.length ?? 0) > 0 && !msg.editorReport}
                      />
                    )}
                  </div>
                )}
              </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>

        <footer className="p-4 border-t border-white/5 bg-black/20">
          <div className="flex gap-2 max-w-3xl mx-auto">
            <input
              className="input-field flex-1 px-4 py-2.5 text-xs disabled:opacity-40"
              placeholder={selectedPath ? "Describe your edit…" : "Select a project first"}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
              disabled={loading || !connected}
            />
            <button
              onClick={() => sendMessage()}
              disabled={loading || !connected || !input.trim()}
              className="btn-primary px-5 py-2.5 text-xs cursor-pointer"
            >
              Send
            </button>
          </div>
        </footer>
      </div>

      {/* Right — Analysis / Library + Activity */}
      <aside className="w-[420px] glass-panel rounded-2xl flex flex-col shrink-0 overflow-hidden z-10">
        <div className="p-2 border-b border-white/5 flex gap-1">
          {(["analysis", "library"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setRightTab(tab)}
              className={`flex-1 text-xs py-2 rounded-xl font-semibold capitalize transition-all cursor-pointer ${
                rightTab === tab
                  ? "bg-capcut/20 text-capcut border border-capcut/30"
                  : "text-white/50 hover:text-white/75"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {rightTab === "analysis" && (
          <ProjectAnalysisPanel
            tab={analysisPanelTab}
            onTabChange={setAnalysisPanelTab}
            analyzing={analyzing}
            progress={analysisProgress}
            phases={analysisPhases}
            clipPreviews={clipPreviews}
            waveformPeaks={waveformPeaks}
            audioMarkers={audioMarkers}
            analysis={analysis}
            summary={summary}
            onApplyAll={() => analysis && applyAnalysisFixes(analysis.suggested_actions)}
            onApplyFix={(action) => applyAnalysisFixes([action])}
            onStop={() => analysisAbortRef.current?.abort()}
            onAnalyze={runAnalysis}
          />
        )}

        {rightTab === "library" && (
          <>
            <div className="p-4 border-b border-white/5 space-y-3">
              {libraryStats && (
                <p className="text-[10px] text-white/45 leading-relaxed">
                  📚 {libraryStats.catalog_total} assets indexed · {libraryStats.music} music · {libraryStats.effects} fx ·{" "}
                  {libraryStats.transitions} transitions
                </p>
              )}
              {status?.capcut_launch_hint && (
                <p className="text-[10px] alert-warning leading-relaxed rounded-lg p-2">{status.capcut_launch_hint}</p>
              )}
              <div className="flex gap-2">
                <input
                  className="input-field flex-1 px-3 py-2 text-[11px]"
                  placeholder="Search catalog..."
                  value={libraryQuery}
                  onChange={(e) => setLibraryQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && searchLibrary()}
                />
                <select className="input-field px-1.5 text-[10px] cursor-pointer"
                  value={libraryType} onChange={(e) => setLibraryType(e.target.value)}>
                  <option value="all">All</option>
                  <option value="music">Music</option>
                  <option value="effect">Effects</option>
                  <option value="transition">Transitions</option>
                  <option value="sticker">Stickers</option>
                  <option value="text_template">Text templates</option>
                </select>
              </div>
              <div className="flex gap-2">
                <button onClick={searchLibrary} disabled={librarySearching || librarySyncing}
                  className="btn-primary flex-1 text-[11px] py-2 cursor-pointer">
                  {librarySearching ? "Searching…" : "Search"}
                </button>
                <button
                  onClick={rebuildCatalog}
                  disabled={librarySyncing || librarySearching}
                  title="Rescan CapCut cache folders and rebuild SQLite catalog"
                  className="btn-secondary flex-1 text-[11px] py-2 cursor-pointer disabled:opacity-30"
                >
                  {librarySyncing ? "Indexing..." : "Rebuild Index"}
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {libraryResults.map((item, i) => (
                <button key={i}
                  onClick={() => sendMessage(`Add music "${item.name}" at the start of the timeline`)}
                  className="w-full text-left text-xs bg-white/[0.02] hover:bg-white/[0.05] border border-white/5 hover:border-capcut/30 rounded-xl p-3 transition-colors cursor-pointer">
                  <p className="font-medium truncate text-white/90">{item.name}</p>
                  <p className="text-[10px] text-white/40 mt-1 flex justify-between">
                    <span>{item.type}</span>
                    <span className="text-capcut">{item.cached ? "cached" : ""}</span>
                  </p>
                </button>
              ))}
              {libraryResults.length === 0 && (
                <p className="text-xs text-white/35 text-center py-8">Search music, effects, or transitions</p>
              )}
            </div>
          </>
        )}

        <div className="border-t border-white/5 p-3 max-h-40 overflow-y-auto bg-black/15">
          <p className="text-[10px] text-white/40 uppercase tracking-wider font-semibold mb-2">Activity</p>
          {activity.length === 0 && <p className="text-[10px] text-white/30 italic">No activity yet</p>}
          {activity.map((a, i) => (
            <div key={i} className="text-[10px] font-mono leading-relaxed mb-1 flex items-start gap-2">
              <span className="text-white/30 shrink-0 tabular-nums">{a.time}</span>
              <span className={`break-words ${
                a.type === "success" ? "text-emerald-400" : a.type === "error" ? "text-rose-400" : "text-white/55"
              }`}>
                {a.message}
              </span>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}

function AgentStepsPanel({ steps, streaming }: { steps: AgentStep[]; streaming?: boolean }) {
  return <AssistantMessage steps={steps} streaming={streaming} />;
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-wider text-white/35 font-semibold mb-0.5">{label}</div>
      <div className="text-sm font-bold text-white/95 tabular-nums">{value}</div>
    </div>
  );
}

function StatusRow({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <div className="flex items-center gap-2.5 text-[11px] bg-white/[0.02] border border-white/[0.04] rounded-lg px-2.5 py-1.5 w-full">
      <div className={`w-2 h-2 rounded-full shrink-0 ${ok ? "bg-emerald-500" : "bg-white/15"}`} />
      <span className="text-white/60 font-medium">{label}</span>
      <span className="text-white/35 ml-auto truncate max-w-[140px] text-[10px]" title={detail}>{detail}</span>
    </div>
  );
}
