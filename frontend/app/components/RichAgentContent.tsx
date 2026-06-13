"use client";

import { type ReactNode } from "react";

type Block =
  | { type: "h1" | "h2" | "h3"; text: string }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "kv"; items: { label: string; value: string }[] }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "p"; text: string }
  | { type: "hr" };

function renderInline(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) {
      parts.push(
        <strong key={k++} className="font-semibold text-white/95">
          {tok.slice(2, -2)}
        </strong>
      );
    } else if (tok.startsWith("*")) {
      parts.push(
        <em key={k++} className="text-white/75 italic">
          {tok.slice(1, -1)}
        </em>
      );
    } else {
      parts.push(
        <code key={k++} className="text-[11px] bg-white/[0.06] px-1.5 py-0.5 rounded font-mono text-capcut">
          {tok.slice(1, -1)}
        </code>
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function parseTableRow(line: string): string[] {
  return line
    .split("|")
    .map((c) => c.trim())
    .filter((c, i, arr) => !(i === 0 && c === "") && !(i === arr.length - 1 && c === ""));
}

function isTableSeparator(line: string): boolean {
  return /^\|?[\s:-]+\|[\s|:-]+\|?$/.test(line.trim());
}

export function parseAgentMarkdown(text: string): Block[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    if (/^---+$/.test(trimmed)) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    if (trimmed.startsWith("### ")) {
      blocks.push({ type: "h3", text: trimmed.slice(4) });
      i++;
      continue;
    }
    if (trimmed.startsWith("## ")) {
      blocks.push({ type: "h2", text: trimmed.slice(3) });
      i++;
      continue;
    }
    if (trimmed.startsWith("# ")) {
      blocks.push({ type: "h1", text: trimmed.slice(2) });
      i++;
      continue;
    }

    if (trimmed.startsWith("|") && trimmed.includes("|")) {
      const headers = parseTableRow(trimmed);
      i++;
      if (i < lines.length && isTableSeparator(lines[i])) i++;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(parseTableRow(lines[i]));
        i++;
      }
      if (headers.length) blocks.push({ type: "table", headers, rows });
      continue;
    }

    const kvBatch: { label: string; value: string }[] = [];
    while (i < lines.length) {
      const l = lines[i].trim();
      const kv = l.match(/^\*\*([^*]+)\*\*:?\s*(.*)$/);
      if (kv) {
        kvBatch.push({ label: kv[1].trim(), value: kv[2].trim() });
        i++;
        continue;
      }
      break;
    }
    if (kvBatch.length) {
      blocks.push({ type: "kv", items: kvBatch });
      continue;
    }

    if (/^\d+\.\s/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
        i++;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    if (/^[-•*]\s/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^[-•*]\s/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-•*]\s+/, ""));
        i++;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    const para: string[] = [trimmed];
    i++;
    while (i < lines.length && lines[i].trim() && !lines[i].trim().startsWith("#") && !lines[i].trim().startsWith("|")) {
      const next = lines[i].trim();
      if (/^[-•*]\s/.test(next) || /^\d+\.\s/.test(next) || /^\*\*[^*]+\*\*:?/.test(next)) break;
      para.push(next);
      i++;
    }
    blocks.push({ type: "p", text: para.join(" ") });
  }

  return blocks;
}

function SectionCard({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] overflow-hidden">
      {title && (
        <div className="px-3.5 py-2 border-b border-white/[0.06] bg-white/[0.02]">
          <p className="text-[10px] uppercase tracking-wider font-semibold text-capcut">{title}</p>
        </div>
      )}
      <div className="px-3.5 py-3">{children}</div>
    </div>
  );
}

function DataTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-left text-[11px] border-collapse min-w-[280px]">
        <thead>
          <tr className="border-b border-white/10">
            {headers.map((h, i) => (
              <th
                key={i}
                className="px-2.5 py-2 font-semibold text-white/50 uppercase tracking-wide text-[9px] whitespace-nowrap"
              >
                {renderInline(h)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr
              key={ri}
              className="border-b border-white/[0.04] hover:bg-white/[0.03] transition-colors"
            >
              {headers.map((_, ci) => (
                <td key={ci} className="px-2.5 py-2 text-white/85 align-top max-w-[200px]">
                  <span className="line-clamp-3">{renderInline(row[ci] ?? "")}</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KeyValueGrid({ items }: { items: { label: string; value: string }[] }) {
  return (
    <dl className="grid gap-2">
      {items.map((item, i) => (
        <div key={i} className="grid grid-cols-[minmax(72px,28%)_1fr] gap-x-3 gap-y-0.5 text-[12px]">
          <dt className="text-white/45 font-medium">{item.label}</dt>
          <dd className="text-white/90 leading-snug">{renderInline(item.value || "—")}</dd>
        </div>
      ))}
    </dl>
  );
}

export function RichAgentContent({ text }: { text: string }) {
  const blocks = parseAgentMarkdown(text);

  if (!blocks.length) return null;

  return (
    <div className="space-y-3">
      {blocks.map((block, i) => {
        if (block.type === "h1") {
          return (
            <h2 key={i} className="text-base font-bold text-white/95 tracking-tight">
              {renderInline(block.text)}
            </h2>
          );
        }
        if (block.type === "h2") {
          return (
            <h3 key={i} className="text-sm font-semibold text-white/90 pt-1">
              {renderInline(block.text)}
            </h3>
          );
        }
        if (block.type === "h3") {
          return (
            <p key={i} className="text-[12px] font-semibold text-capcut uppercase tracking-wide">
              {renderInline(block.text)}
            </p>
          );
        }
        if (block.type === "hr") {
          return <hr key={i} className="border-white/[0.06]" />;
        }
        if (block.type === "table") {
          return (
            <SectionCard key={i} title="Timeline data">
              <DataTable headers={block.headers} rows={block.rows} />
            </SectionCard>
          );
        }
        if (block.type === "kv") {
          return (
            <SectionCard key={i}>
              <KeyValueGrid items={block.items} />
            </SectionCard>
          );
        }
        if (block.type === "ul") {
          return (
            <ul key={i} className="space-y-1.5 pl-1">
              {block.items.map((item, j) => (
                <li key={j} className="flex gap-2 text-[12px] text-white/85 leading-relaxed">
                  <span className="text-capcut shrink-0 mt-0.5">•</span>
                  <span>{renderInline(item)}</span>
                </li>
              ))}
            </ul>
          );
        }
        if (block.type === "ol") {
          return (
            <ol key={i} className="space-y-1.5 list-none pl-1">
              {block.items.map((item, j) => (
                <li key={j} className="flex gap-2.5 text-[12px] text-white/85 leading-relaxed">
                  <span className="text-white/35 font-mono text-[10px] w-4 shrink-0 tabular-nums">
                    {j + 1}.
                  </span>
                  <span>{renderInline(item)}</span>
                </li>
              ))}
            </ol>
          );
        }
        return (
          <p key={i} className="text-[13px] leading-relaxed text-white/88">
            {renderInline(block.text)}
          </p>
        );
      })}
    </div>
  );
}
