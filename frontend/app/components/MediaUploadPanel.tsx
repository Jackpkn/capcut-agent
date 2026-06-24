"use client";

import { useRef, useState } from "react";

type UploadedFile = { name: string; path: string; size: number };

type Props = {
  api: string;
  disabled?: boolean;
  exportProjectPath?: string;
  onProjectCreated: (path: string, name: string) => void;
  onAutoEdit?: (path: string) => void;
  onLog?: (message: string, type?: "info" | "success" | "error") => void;
};

export function MediaUploadPanel({
  api,
  disabled,
  exportProjectPath,
  onProjectCreated,
  onAutoEdit,
  onLog,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [projectName, setProjectName] = useState("");
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [lastProjectPath, setLastProjectPath] = useState("");

  const log = (message: string, type: "info" | "success" | "error" = "info") => {
    onLog?.(message, type);
  };

  const uploadAndCreate = async (autoEdit: boolean) => {
    if (!files.length || busy) return;
    setBusy(true);
    log(`Uploading ${files.length} file(s)…`);
    try {
      const form = new FormData();
      for (const f of files) form.append("files", f);

      const uploadRes = await fetch(`${api}/media/upload`, { method: "POST", body: form });
      const uploadData = await uploadRes.json();
      if (!uploadRes.ok) throw new Error(uploadData.detail || "Upload failed");

      const mediaPaths = (uploadData.files as UploadedFile[]).map((f) => f.path);
      log(`Uploaded ${mediaPaths.length} file(s) — creating CapCut project…`);

      const createRes = await fetch(`${api}/projects/create-from-media`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          media_paths: mediaPaths,
          project_name: projectName.trim() || undefined,
        }),
      });
      const created = await createRes.json();
      if (!createRes.ok) throw new Error(created.detail || "Project creation failed");

      const path = String(created.project_path);
      const name = String(created.project_name);
      setLastProjectPath(path);
      onProjectCreated(path, name);
      log(
        `Project "${name}" ready — ${created.imported_count} clip(s), ${Number(created.timeline_duration_sec).toFixed(1)}s`,
        "success",
      );
      setFiles([]);
      setProjectName("");

      if (autoEdit && onAutoEdit) onAutoEdit(path);
    } catch (e) {
      log(e instanceof Error ? e.message : "Upload failed", "error");
    } finally {
      setBusy(false);
    }
  };

  const exportTarget = exportProjectPath || lastProjectPath;

  const exportProject = async () => {
    if (!exportTarget || exporting) return;
    setExporting(true);
    log("Triggering CapCut export (RPA)…");
    try {
      const res = await fetch(`${api}/project/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_path: exportTarget }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Export failed");
      log(data.detail || "Export started in CapCut", "success");
    } catch (e) {
      log(e instanceof Error ? e.message : "Export failed", "error");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-semibold text-capcut uppercase tracking-wider">New from clips</p>
      <p className="text-[10px] text-white/40 leading-relaxed">
        Upload videos or photos — we create a CapCut project and you edit it here. No manual import needed.
      </p>

      <input
        ref={inputRef}
        type="file"
        accept="video/*,image/*,audio/*"
        multiple
        className="hidden"
        onChange={(e) => {
          const picked = e.target.files ? Array.from(e.target.files) : [];
          setFiles(picked);
          e.target.value = "";
        }}
      />

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={disabled || busy}
        className="btn-secondary w-full text-xs py-2 cursor-pointer disabled:opacity-40"
      >
        {files.length ? `${files.length} file(s) selected` : "Choose clips…"}
      </button>

      {files.length > 0 && (
        <ul className="text-[10px] text-white/50 space-y-0.5 max-h-20 overflow-y-auto">
          {files.map((f) => (
            <li key={f.name + f.size} className="truncate">
              {f.name}
            </li>
          ))}
        </ul>
      )}

      <input
        className="input-field w-full text-xs px-3 py-2"
        placeholder="Project name (optional)"
        value={projectName}
        onChange={(e) => setProjectName(e.target.value)}
        disabled={disabled || busy}
      />

      <button
        type="button"
        onClick={() => uploadAndCreate(false)}
        disabled={disabled || busy || !files.length}
        className="btn-secondary w-full text-xs py-2.5 cursor-pointer disabled:opacity-40"
      >
        {busy ? "Creating project…" : "Create CapCut project"}
      </button>

      <button
        type="button"
        onClick={() => uploadAndCreate(true)}
        disabled={disabled || busy || !files.length || !onAutoEdit}
        className="btn-primary w-full text-xs py-2.5 cursor-pointer disabled:opacity-40"
      >
        {busy ? "Working…" : "Create & auto edit"}
      </button>

      {exportTarget && (
        <button
          type="button"
          onClick={exportProject}
          disabled={exporting || disabled}
          className="btn-secondary w-full text-xs py-2 cursor-pointer disabled:opacity-40"
        >
          {exporting ? "Exporting…" : "Export via CapCut (RPA)"}
        </button>
      )}
    </div>
  );
}
