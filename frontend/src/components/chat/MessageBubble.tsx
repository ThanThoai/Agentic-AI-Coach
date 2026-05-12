"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message, WorkoutDataSummary, AgentResponse } from "@/types/chat";
import { SourceList } from "./SourceList";
import { Spinner } from "@/components/ui/Spinner";

interface Props {
  message: Message;
}

export function MessageBubble({ message }: Props) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] bg-indigo-600 px-4 py-2.5 text-sm text-white leading-relaxed">
          {message.content}
        </div>
      </div>
    );
  }

  const isStreaming = !!message.isLoading && !!message.content;
  const isAnalysis = message.commandMode === "analysis";
  const isAgent = message.commandMode === "agent";

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] min-w-[240px] space-y-2">

        {/* Answer bubble */}
        <div className="border border-neutral-200 bg-white px-4 py-3 text-sm leading-relaxed">
          {/* Agent badge */}
          {isAgent && !message.isLoading && (
            <div className="flex items-center gap-1.5 mb-2 pb-2 border-b border-neutral-100">
              <span className="text-base">🤖</span>
              <span className="text-[10px] font-bold uppercase tracking-widest text-violet-600">Coach Agent</span>
            </div>
          )}

          {message.isLoading && !message.content ? (
            <div className="flex items-center gap-2 text-neutral-400">
              <Spinner size={14} />
              <span>{isAgent ? "Agent is thinking…" : "Thinking…"}</span>
            </div>
          ) : message.error ? (
            <ErrorBlock message={message.error} code={message.errorCode} />
          ) : (
            <div className="prose prose-neutral prose-sm max-w-none
              prose-p:my-1.5 prose-ul:my-1.5 prose-ol:my-1.5
              prose-li:my-0.5 prose-headings:mb-2 prose-headings:mt-3
              prose-strong:text-neutral-800 prose-code:text-indigo-700
              prose-code:bg-indigo-50 prose-code:px-1 prose-code:rounded
              prose-blockquote:border-indigo-400 prose-blockquote:text-neutral-500">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
              {isStreaming && (
                <span className="ml-0.5 inline-block h-[1em] w-0.5 translate-y-[2px] animate-pulse rounded-sm bg-neutral-400" />
              )}
            </div>
          )}
        </div>

        {/* Agent metadata panel */}
        {isAgent && message.agentResponse && !message.isLoading && (
          <AgentMetaPanel response={message.agentResponse} />
        )}

        {/* Analysis data summary panel */}
        {isAnalysis && message.workoutResponse && !message.isLoading && (
          <DataSummaryPanel
            summary={message.workoutResponse.data_summary}
            dataOwner={message.dataOwner}
          />
        )}

        {/* RAG sources */}
        {!isAnalysis && !isAgent && message.ragResponse?.sources && message.ragResponse.sources.length > 0 && !message.isLoading && (
          <SourceList sources={message.ragResponse.sources} />
        )}
      </div>
    </div>
  );
}

// ── Error block ───────────────────────────────────────────────────────────────

function ErrorBlock({ message, code }: { message: string; code?: number }) {
  const isAuth = code === 401 || code === 403;
  const isOverload = code === 429 || code === 503 || code === 502 || code === 504;

  const icon = isAuth ? "🔒" : isOverload ? "⏳" : "⚠️";

  return (
    <div className="flex items-start gap-3 border border-red-200 bg-red-50 px-4 py-3">
      <span className="mt-0.5 text-base leading-none shrink-0">{icon}</span>
      <div className="min-w-0">
        <p className="text-sm text-red-700 leading-relaxed">{message}</p>
        {code !== undefined && (
          <p className="mt-1 text-xs text-red-400">
            Error {code}
            {code === 422 && " · Validation"}
            {code === 403 && " · Forbidden"}
            {code === 401 && " · Unauthorized"}
            {code === 429 && " · Rate limited"}
            {(code === 502 || code === 503 || code === 504) && " · Unavailable"}
            {code >= 500 && code < 600 && code !== 502 && code !== 503 && code !== 504 && " · Server error"}
          </p>
        )}
      </div>
    </div>
  );
}

// ── Agent metadata panel ──────────────────────────────────────────────────────

const TOOL_META: Record<string, { emoji: string; label: string }> = {
  analyze_history: { emoji: "📊", label: "Workout data" },
  rag_search:      { emoji: "📚", label: "Knowledge base" },
};

function AgentMetaPanel({ response }: { response: AgentResponse }) {
  const uniqueTools = [...new Set(response.tools_used)];
  return (
    <div className="border border-neutral-200 bg-neutral-50 px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-neutral-400">Agent run</p>
        <span className="text-[10px] text-neutral-500">
          {response.iterations} iteration{response.iterations !== 1 ? "s" : ""}
          {" · "}
          {response.usage.total_tokens.toLocaleString()} tokens
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {uniqueTools.length === 0 ? (
          <span className="text-xs text-neutral-400">No tools used</span>
        ) : uniqueTools.map((t) => {
          const meta = TOOL_META[t] ?? { emoji: "🔧", label: t };
          return (
            <span
              key={t}
              className="flex items-center gap-1 border border-neutral-200 bg-white px-2.5 py-0.5 text-xs text-neutral-600"
            >
              {meta.emoji} {meta.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ── Analysis data summary panel ───────────────────────────────────────────────

function DataSummaryPanel({
  summary,
  dataOwner,
}: {
  summary: WorkoutDataSummary;
  dataOwner?: { key: string; name: string };
}) {
  if (summary.insufficient_data) {
    return (
      <div className="border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-700">
        Not enough workout data in the selected date range to run a full analysis.
      </div>
    );
  }

  return (
    <div className="border border-neutral-200 bg-neutral-50 px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-neutral-400">Data used</p>
        {dataOwner && (
          <span className="text-[10px] text-neutral-500">{dataOwner.name}&apos;s data</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
        <StatRow label="Sessions" value={String(summary.sessions_analysed)} />
        <StatRow label="Exercises" value={String(summary.exercises_found)} />
        <StatRow label="Date range" value={`${summary.date_range.from} → ${summary.date_range.to}`} wide />
        <StatRow label="Muscle groups" value={summary.muscle_groups_found.join(", ") || "—"} wide />
        {summary.deload_weeks_detected > 0 && (
          <StatRow label="Deload weeks" value={String(summary.deload_weeks_detected)} />
        )}
      </div>
    </div>
  );
}

function StatRow({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? "col-span-2" : ""}>
      <span className="text-neutral-400">{label}: </span>
      <span className="text-neutral-700">{value}</span>
    </div>
  );
}
