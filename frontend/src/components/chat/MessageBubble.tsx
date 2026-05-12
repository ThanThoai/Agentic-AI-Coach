"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message, WorkoutDataSummary, AgentResponse } from "@/types/chat";
import { ThinkingPanel } from "./ThinkingPanel";
import { SourceList } from "./SourceList";
import { Spinner } from "@/components/ui/Spinner";

interface Props {
  message: Message;
}

export function MessageBubble({ message }: Props) {
  if (message.role === "user") {
    const hasAgentMention = message.content.includes("@AgentAssist");
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-2.5 text-sm text-white leading-relaxed">
          {hasAgentMention ? (
            <>
              {message.content.split("@AgentAssist").flatMap((part, i, arr) => [
                part,
                i < arr.length - 1 ? (
                  <span key={i} className="font-semibold text-purple-200">@AgentAssist</span>
                ) : null,
              ])}
            </>
          ) : message.content}
        </div>
      </div>
    );
  }

  const isStreaming = !!message.isLoading && !!message.content;
  const isAnalysis = message.commandMode === "analysis";
  const isAgent = message.commandMode === "agent";

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] min-w-[240px]">
        {/* Pipeline thinking panel */}
        {message.pipelineSteps && (
          <ThinkingPanel
            steps={message.pipelineSteps}
            ragResponse={message.ragResponse}
            isLoading={!!message.isLoading}
            isAgent={isAgent}
            agentResponse={message.agentResponse}
          />
        )}

        {/* Answer bubble */}
        <div className={`rounded-2xl rounded-tl-sm px-4 py-3 text-sm leading-relaxed ${isAgent ? "bg-purple-950/40 border border-purple-500/20" : "bg-white/[0.08]"}`}>
          {/* Agent badge */}
          {isAgent && !message.isLoading && (
            <div className="flex items-center gap-1.5 mb-2 pb-2 border-b border-purple-500/20">
              <span className="text-base">🤖</span>
              <span className="text-[10px] font-bold uppercase tracking-widest text-purple-400">Coach Agent</span>
              {message.dataOwner && (
                <span className="ml-auto text-[10px] text-purple-600">
                  re: {message.dataOwner.name}
                </span>
              )}
            </div>
          )}

          {message.isLoading && !message.content ? (
            <div className="flex items-center gap-2 text-gray-400">
              <Spinner size={14} />
              <span>{isAgent ? "Agent is thinking…" : "Thinking…"}</span>
            </div>
          ) : message.error ? (
            <p className="text-red-400">{message.error}</p>
          ) : (
            <div className="prose prose-invert prose-sm max-w-none
              prose-p:my-1.5 prose-ul:my-1.5 prose-ol:my-1.5
              prose-li:my-0.5 prose-headings:mb-2 prose-headings:mt-3
              prose-strong:text-gray-200 prose-code:text-indigo-300
              prose-code:bg-white/10 prose-code:px-1 prose-code:rounded
              prose-blockquote:border-indigo-500 prose-blockquote:text-gray-400">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
              {isStreaming && (
                <span className="ml-0.5 inline-block h-[1em] w-0.5 translate-y-[2px] animate-pulse rounded-sm bg-gray-400" />
              )}
            </div>
          )}
        </div>

        {/* Agent metadata panel */}
        {isAgent && message.agentResponse && !message.isLoading && (
          <AgentMetaPanel response={message.agentResponse} dataOwner={message.dataOwner} />
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

// ── Agent metadata panel ──────────────────────────────────────────────────────

const TOOL_META: Record<string, { emoji: string; label: string; color: string }> = {
  analyze_history: { emoji: "📊", label: "Workout data",    color: "text-emerald-400" },
  rag_search:      { emoji: "📚", label: "Knowledge base",  color: "text-indigo-400"  },
};

function AgentMetaPanel({
  response,
  dataOwner,
}: {
  response: AgentResponse;
  dataOwner?: { key: string; name: string };
}) {
  const uniqueTools = [...new Set(response.tools_used)];
  return (
    <div className="mt-2 rounded-xl border border-purple-500/15 bg-purple-950/20 px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-purple-600">
          Agent run
        </p>
        <span className="text-[10px] text-gray-600">
          {response.iterations} iteration{response.iterations !== 1 ? "s" : ""}
          {" · "}
          {response.usage.total_tokens.toLocaleString()} tokens
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {uniqueTools.length === 0 ? (
          <span className="text-xs text-gray-600">No tools used</span>
        ) : uniqueTools.map((t) => {
          const meta = TOOL_META[t] ?? { emoji: "🔧", label: t, color: "text-gray-400" };
          return (
            <span
              key={t}
              className={`flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-xs ${meta.color}`}
            >
              <span>{meta.emoji}</span>
              {meta.label}
            </span>
          );
        })}
        {dataOwner && (
          <span className="ml-auto text-[10px] text-gray-600 self-center">
            athlete: {dataOwner.name}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Analysis data summary panel ───────────────────────────────────────────────

const USER_COLOR: Record<string, string> = {
  alex: "text-indigo-400",
  binh: "text-emerald-400",
};

function DataSummaryPanel({
  summary,
  dataOwner,
}: {
  summary: WorkoutDataSummary;
  dataOwner?: { key: string; name: string };
}) {
  if (summary.insufficient_data) {
    return (
      <div className="mt-2 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-300">
        Not enough workout data in the selected date range to run a full analysis.
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-600">
          Data used
        </p>
        {dataOwner && (
          <span className={`text-[10px] font-semibold ${USER_COLOR[dataOwner.key] ?? "text-gray-400"}`}>
            {dataOwner.name}&apos;s data
          </span>
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
      <span className="text-gray-500">{label}: </span>
      <span className="text-gray-300">{value}</span>
    </div>
  );
}
