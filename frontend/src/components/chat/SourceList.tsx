"use client";

import { useState } from "react";
import type { RAGSource } from "@/types/chat";

interface Props {
  sources: RAGSource[];
}

export function SourceList({ sources }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (sources.length === 0) return null;

  return (
    <div className="mt-3 space-y-1.5">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
        Sources
      </p>
      {sources.map((src, i) => (
        <div
          key={i}
          className="rounded-lg border border-white/10 bg-white/5 overflow-hidden"
        >
          <button
            onClick={() => setExpanded(expanded === i ? null : i)}
            className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-white/5 transition-colors"
          >
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-white/10 text-xs font-bold text-gray-400">
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-gray-300">
                {src.doc_title}
              </div>
              <div className="truncate text-xs text-gray-500">
                {src.section_title}
              </div>
            </div>
            <div className="shrink-0 flex items-center gap-2">
              <ScoreBar score={src.score} />
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className={`text-gray-600 transition-transform ${expanded === i ? "rotate-180" : ""}`}
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </div>
          </button>

          {expanded === i && (
            <div className="border-t border-white/10 px-3 py-2 text-xs text-gray-400 leading-relaxed">
              <p className="mb-1 text-gray-500 font-medium">
                {src.source_file}
              </p>
              <p className="italic">{src.excerpt}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color =
    pct >= 80
      ? "bg-emerald-500"
      : pct >= 60
        ? "bg-amber-500"
        : "bg-gray-500";
  return (
    <div className="flex items-center gap-1" title={`Score: ${pct}%`}>
      <div className="h-1.5 w-12 rounded-full bg-white/10">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-600">{pct}%</span>
    </div>
  );
}
