"use client";

import { useState } from "react";
import type { PipelineStep, RAGResponse } from "@/types/chat";
import { Spinner } from "@/components/ui/Spinner";

interface Props {
  steps: PipelineStep[];
  ragResponse?: RAGResponse;
  isLoading: boolean;
}

const INTENT_COLOR: Record<string, string> = {
  SIMPLE: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  COMPLEX: "bg-purple-500/20 text-purple-300 border-purple-500/30",
  COMPARISON: "bg-amber-500/20 text-amber-300 border-amber-500/30",
};

export function ThinkingPanel({ steps, ragResponse, isLoading }: Props) {
  const [open, setOpen] = useState(false);

  const doneCount = steps.filter((s) => s.status === "done").length;
  const label = isLoading
    ? `Processing… (${doneCount}/${steps.length})`
    : "View pipeline steps";

  return (
    <div className="mb-2 rounded-lg border border-white/10 bg-white/5 text-sm overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-gray-400 hover:text-gray-200 transition-colors"
      >
        <span className="flex-1 font-medium">{label}</span>
        {isLoading && <Spinner size={13} />}
        {!isLoading && ragResponse?.intent && (
          <span
            className={`rounded border px-1.5 py-0.5 text-xs font-semibold ${INTENT_COLOR[ragResponse.intent] ?? "bg-white/10 text-gray-300 border-white/20"}`}
          >
            {ragResponse.intent}
          </span>
        )}
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className={`transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="border-t border-white/10 px-3 py-2 space-y-2">
          {steps.map((step, i) => (
            <div key={i} className="flex items-start gap-2.5">
              <StepIcon status={step.status} />
              <div className="min-w-0">
                <span
                  className={
                    step.status === "done"
                      ? "text-gray-200"
                      : step.status === "skipped"
                        ? "text-gray-500 line-through"
                        : "text-gray-400"
                  }
                >
                  {step.label}
                </span>
                {step.detail && (
                  <span className="ml-2 text-xs text-gray-500">
                    {step.detail}
                  </span>
                )}
              </div>
            </div>
          ))}

          {!isLoading && ragResponse && (
            <div className="mt-3 pt-2 border-t border-white/10 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500">
              {ragResponse.model && (
                <div>
                  <span className="text-gray-400">Model</span>{" "}
                  {ragResponse.model}
                </div>
              )}
              {ragResponse.usage && (
                <div>
                  <span className="text-gray-400">Tokens</span>{" "}
                  {ragResponse.usage.total_tokens.toLocaleString()}
                  {ragResponse.usage.cache_read_tokens
                    ? ` (${ragResponse.usage.cache_read_tokens.toLocaleString()} cached)`
                    : ""}
                </div>
              )}
              {ragResponse.sources.length > 0 && (
                <div>
                  <span className="text-gray-400">Sources</span>{" "}
                  {ragResponse.sources.length} chunk
                  {ragResponse.sources.length !== 1 ? "s" : ""}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StepIcon({ status }: { status: PipelineStep["status"] }) {
  if (status === "pending") return <Spinner size={12} />;
  if (status === "skipped")
    return <span className="mt-0.5 h-3 w-3 text-gray-600">–</span>;
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      className="mt-0.5 shrink-0 text-emerald-400"
    >
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}
