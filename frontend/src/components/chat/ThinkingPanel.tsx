"use client";

import { useState } from "react";
import type { AgentResponse, PipelineStep, PipelineTrace, RAGResponse } from "@/types/chat";
import { Spinner } from "@/components/ui/Spinner";

interface Props {
  steps: PipelineStep[];
  ragResponse?: RAGResponse;
  isLoading: boolean;
  isAgent?: boolean;
  agentResponse?: AgentResponse;
}

const QUERY_TYPE_COLOR: Record<string, string> = {
  SIMPLE: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  COMPLEX: "bg-purple-500/20 text-purple-300 border-purple-500/30",
  COMPARISON: "bg-amber-500/20 text-amber-300 border-amber-500/30",
};

const INTENT_COLOR: Record<string, string> = {
  SAFE: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  BORDERLINE: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  MEDICAL_REFUSE: "bg-red-500/20 text-red-300 border-red-500/30",
  EATING_RISK: "bg-red-500/20 text-red-300 border-red-500/30",
  OUT_OF_SCOPE: "bg-gray-500/20 text-gray-300 border-gray-500/30",
};

const STRATEGY_COLOR: Record<string, string> = {
  aggregate: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  chain: "bg-purple-500/20 text-purple-300 border-purple-500/30",
  compare: "bg-amber-500/20 text-amber-300 border-amber-500/30",
};

function Badge({ label, colorClass }: { label: string; colorClass: string }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-xs font-semibold ${colorClass}`}>
      {label}
    </span>
  );
}

function TraceDetail({ index, trace }: { index: number; trace: PipelineTrace }) {
  switch (index) {
    case 1: {
      const l2 = trace.guardrail_l2;
      if (!l2 || l2.status === "skipped" || !l2.intent) return null;
      return (
        <div className="mt-1.5 ml-5 space-y-1">
          <div className="flex items-center gap-2">
            <Badge label={l2.intent} colorClass={INTENT_COLOR[l2.intent] ?? "bg-white/10 text-gray-300 border-white/20"} />
          </div>
          {l2.reason && (
            <p className="text-xs text-gray-500 leading-relaxed">{l2.reason}</p>
          )}
        </div>
      );
    }
    case 2: {
      const qp = trace.query_processor;
      if (!qp) return null;
      return (
        <div className="mt-1.5 ml-5 space-y-1.5">
          <Badge
            label={qp.query_type}
            colorClass={QUERY_TYPE_COLOR[qp.query_type] ?? "bg-white/10 text-gray-300 border-white/20"}
          />
          {qp.sub_questions.length > 1 && (
            <ul className="space-y-0.5">
              {qp.sub_questions.map((q, i) => (
                <li key={i} className="flex gap-1.5 text-xs text-gray-500">
                  <span className="shrink-0 text-gray-600">{i + 1}.</span>
                  <span>{q}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      );
    }
    case 3: {
      const r = trace.retrieval;
      if (!r) return null;
      return (
        <div className="mt-1.5 ml-5 space-y-0.5">
          {r.results_per_query.map((count, i) => (
            <div key={i} className="text-xs text-gray-500">
              Query {i + 1}: <span className="text-gray-400">{count} result{count !== 1 ? "s" : ""}</span>
            </div>
          ))}
          {r.results_per_query.length > 1 && (
            <div className="text-xs text-gray-500 pt-0.5 border-t border-white/5">
              Merged: <span className="text-gray-400">{r.total_merged} chunks</span>
            </div>
          )}
        </div>
      );
    }
    case 4: {
      const ctx = trace.context;
      if (!ctx) return null;
      return (
        <div className="mt-1.5 ml-5 flex flex-wrap gap-1.5 items-center">
          <Badge
            label={ctx.strategy}
            colorClass={STRATEGY_COLOR[ctx.strategy] ?? "bg-white/10 text-gray-300 border-white/20"}
          />
          <span className="text-xs text-gray-500">{ctx.chunks_used} chunks used</span>
          {ctx.conflict_count > 0 && (
            <span className="text-xs text-amber-400">
              ⚠ {ctx.conflict_count} conflict{ctx.conflict_count !== 1 ? "s" : ""}
            </span>
          )}
        </div>
      );
    }
    default:
      return null;
  }
}

export function ThinkingPanel({ steps, ragResponse, isLoading, isAgent, agentResponse }: Props) {
  const [open, setOpen] = useState(false);
  const trace = ragResponse?.trace ?? null;

  const doneCount = steps.filter((s) => s.status === "done").length;
  const queryType = trace?.query_processor?.query_type ?? ragResponse?.intent;
  const label = isLoading
    ? `${isAgent ? "Agent running" : "Processing"}… (${doneCount}/${steps.length})`
    : isAgent ? "View agent steps" : "View pipeline steps";

  return (
    <div className={`mb-2 rounded-lg border text-sm overflow-hidden ${isAgent ? "border-purple-500/20 bg-purple-950/20" : "border-white/10 bg-white/5"}`}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-gray-400 hover:text-gray-200 transition-colors"
      >
        <span className="flex-1 font-medium">{label}</span>
        {isLoading && <Spinner size={13} />}
        {!isLoading && queryType && (
          <Badge
            label={queryType}
            colorClass={
              QUERY_TYPE_COLOR[queryType] ??
              INTENT_COLOR[queryType] ??
              "bg-white/10 text-gray-300 border-white/20"
            }
          />
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
            <div key={i}>
              <div className="flex items-start gap-2.5">
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
                  {step.detail && step.status !== "done" && (
                    <span className="ml-2 text-xs text-gray-500">
                      {step.detail}
                    </span>
                  )}
                </div>
              </div>
              {trace && step.status === "done" && (
                <TraceDetail index={i} trace={trace} />
              )}
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
          {!isLoading && isAgent && agentResponse && (
            <div className="mt-3 pt-2 border-t border-purple-500/20 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500">
              <div>
                <span className="text-gray-400">Iterations</span>{" "}
                {agentResponse.iterations}
              </div>
              <div>
                <span className="text-gray-400">Tokens</span>{" "}
                {agentResponse.usage.total_tokens.toLocaleString()}
              </div>
              <div className="col-span-2">
                <span className="text-gray-400">Tools called</span>{" "}
                {[...new Set(agentResponse.tools_used)].join(", ") || "none"}
              </div>
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
