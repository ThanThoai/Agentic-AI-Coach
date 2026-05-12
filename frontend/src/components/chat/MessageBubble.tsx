"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message, WorkoutDataSummary } from "@/types/chat";
import { ThinkingPanel } from "./ThinkingPanel";
import { SourceList } from "./SourceList";
import { Spinner } from "@/components/ui/Spinner";

interface Props {
  message: Message;
}

export function MessageBubble({ message }: Props) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-2.5 text-sm text-white leading-relaxed">
          {message.content}
        </div>
      </div>
    );
  }

  const isStreaming = !!message.isLoading && !!message.content;
  const isAnalysis = message.commandMode === "analysis";

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] min-w-[240px]">
        {/* Pipeline thinking panel */}
        {message.pipelineSteps && (
          <ThinkingPanel
            steps={message.pipelineSteps}
            ragResponse={message.ragResponse}
            isLoading={!!message.isLoading}
          />
        )}

        {/* Answer bubble */}
        <div className="rounded-2xl rounded-tl-sm bg-white/[0.08] px-4 py-3 text-sm leading-relaxed">
          {message.isLoading && !message.content ? (
            <div className="flex items-center gap-2 text-gray-400">
              <Spinner size={14} />
              <span>Thinking…</span>
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

        {/* Analysis data summary panel */}
        {isAnalysis && message.workoutResponse && !message.isLoading && (
          <DataSummaryPanel summary={message.workoutResponse.data_summary} />
        )}

        {/* RAG sources */}
        {!isAnalysis && message.ragResponse?.sources && message.ragResponse.sources.length > 0 && !message.isLoading && (
          <SourceList sources={message.ragResponse.sources} />
        )}
      </div>
    </div>
  );
}

function DataSummaryPanel({ summary }: { summary: WorkoutDataSummary }) {
  if (summary.insufficient_data) {
    return (
      <div className="mt-2 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-300">
        Not enough workout data in the selected date range to run a full analysis.
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3">
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-gray-600">
        Data used
      </p>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
        <StatRow label="Sessions" value={String(summary.sessions_analysed)} />
        <StatRow label="Exercises" value={String(summary.exercises_found)} />
        <StatRow
          label="Date range"
          value={`${summary.date_range.from} → ${summary.date_range.to}`}
          wide
        />
        <StatRow
          label="Muscle groups"
          value={summary.muscle_groups_found.join(", ") || "—"}
          wide
        />
        {summary.deload_weeks_detected > 0 && (
          <StatRow
            label="Deload weeks"
            value={String(summary.deload_weeks_detected)}
          />
        )}
      </div>
    </div>
  );
}

function StatRow({
  label,
  value,
  wide,
}: {
  label: string;
  value: string;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "col-span-2" : ""}>
      <span className="text-gray-500">{label}: </span>
      <span className="text-gray-300">{value}</span>
    </div>
  );
}
