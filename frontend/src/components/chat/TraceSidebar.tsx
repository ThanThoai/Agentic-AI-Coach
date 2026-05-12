"use client";

import type { Message, PipelineStep, PipelineTrace, AgentToolCall } from "@/types/chat";
import { Spinner } from "@/components/ui/Spinner";

interface Props {
  message: Message | null;
  onClose: () => void;
}

// ── Badge helpers ─────────────────────────────────────────────────────────────

const QUERY_TYPE_BADGE: Record<string, string> = {
  SIMPLE:     "bg-blue-50 text-blue-700 border-blue-200",
  COMPLEX:    "bg-violet-50 text-violet-700 border-violet-200",
  COMPARISON: "bg-amber-50 text-amber-700 border-amber-200",
};
const INTENT_BADGE: Record<string, string> = {
  SAFE:           "bg-emerald-50 text-emerald-700 border-emerald-200",
  BORDERLINE:     "bg-amber-50 text-amber-700 border-amber-200",
  MEDICAL_REFUSE: "bg-red-50 text-red-700 border-red-200",
  EATING_RISK:    "bg-red-50 text-red-700 border-red-200",
  OUT_OF_SCOPE:   "bg-neutral-100 text-neutral-500 border-neutral-200",
};
const STRATEGY_BADGE: Record<string, string> = {
  aggregate: "bg-blue-50 text-blue-700 border-blue-200",
  chain:     "bg-violet-50 text-violet-700 border-violet-200",
  compare:   "bg-amber-50 text-amber-700 border-amber-200",
};
const ANALYSIS_TYPE_BADGE: Record<string, string> = {
  TREND:   "bg-blue-50 text-blue-700 border-blue-200",
  BALANCE: "bg-violet-50 text-violet-700 border-violet-200",
  NEGLECT: "bg-amber-50 text-amber-700 border-amber-200",
  PLAN:    "bg-emerald-50 text-emerald-700 border-emerald-200",
  GENERAL: "bg-neutral-100 text-neutral-500 border-neutral-200",
};
const TOOL_META: Record<string, { emoji: string; label: string }> = {
  analyze_history: { emoji: "📊", label: "Workout data" },
  rag_search:      { emoji: "📚", label: "Knowledge base" },
};

function Badge({ label, cls }: { label: string; cls: string }) {
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold ${cls}`}>
      {label}
    </span>
  );
}

// ── Step icon ─────────────────────────────────────────────────────────────────

function StepIcon({ status }: { status: PipelineStep["status"] }) {
  if (status === "pending") return <Spinner size={12} />;
  if (status === "skipped")
    return <span className="w-3 h-3 flex items-center justify-center text-neutral-300 text-xs">–</span>;
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
      className="shrink-0 text-emerald-500">
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}

// ── RAG per-step detail ───────────────────────────────────────────────────────

function RAGStepDetail({ index, trace }: { index: number; trace: PipelineTrace }) {
  switch (index) {
    case 1: {
      const l2 = trace.guardrail_l2;
      if (!l2 || l2.status === "skipped" || !l2.intent) return null;
      return (
        <div className="mt-1.5 space-y-1">
          <Badge label={l2.intent} cls={INTENT_BADGE[l2.intent] ?? "bg-neutral-100 text-neutral-500 border-neutral-200"} />
          {l2.reason && <p className="text-[11px] text-neutral-400 leading-relaxed">{l2.reason}</p>}
        </div>
      );
    }
    case 2: {
      const qp = trace.query_processor;
      if (!qp) return null;
      return (
        <div className="mt-1.5 space-y-1.5">
          <Badge label={qp.query_type} cls={QUERY_TYPE_BADGE[qp.query_type] ?? "bg-neutral-100 text-neutral-500 border-neutral-200"} />
          {qp.sub_questions.length > 1 && (
            <ol className="space-y-0.5 pl-1">
              {qp.sub_questions.map((q, i) => (
                <li key={i} className="flex gap-1.5 text-[11px] text-neutral-500">
                  <span className="shrink-0 text-neutral-300">{i + 1}.</span>
                  <span>{q}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      );
    }
    case 3: {
      const r = trace.retrieval;
      if (!r) return null;
      return (
        <div className="mt-1.5 space-y-0.5">
          {r.results_per_query.map((count, i) => (
            <div key={i} className="text-[11px] text-neutral-500">
              Query {i + 1}: <span className="text-neutral-700">{count} result{count !== 1 ? "s" : ""}</span>
            </div>
          ))}
          {r.results_per_query.length > 1 && (
            <div className="text-[11px] text-neutral-500 pt-0.5 border-t border-neutral-100">
              Merged: <span className="text-neutral-700">{r.total_merged} chunks</span>
            </div>
          )}
        </div>
      );
    }
    case 4: {
      const ctx = trace.context;
      if (!ctx) return null;
      return (
        <div className="mt-1.5 flex flex-wrap gap-1.5 items-center">
          <Badge label={ctx.strategy} cls={STRATEGY_BADGE[ctx.strategy] ?? "bg-neutral-100 text-neutral-500 border-neutral-200"} />
          <span className="text-[11px] text-neutral-500">{ctx.chunks_used} chunks</span>
          {ctx.conflict_count > 0 && (
            <span className="text-[11px] text-amber-600">⚠ {ctx.conflict_count} conflict{ctx.conflict_count !== 1 ? "s" : ""}</span>
          )}
        </div>
      );
    }
    default:
      return null;
  }
}

// ── Tool call card ────────────────────────────────────────────────────────────

function ToolCallCard({ tc }: { tc: AgentToolCall }) {
  const meta = TOOL_META[tc.name] ?? { emoji: "🔧", label: tc.name };

  return (
    <div className="rounded border border-neutral-200 bg-neutral-50 overflow-hidden">
      {/* Card header */}
      <div className="flex items-center gap-1.5 border-b border-neutral-200 bg-white px-3 py-1.5">
        <span className="text-sm">{meta.emoji}</span>
        <span className="text-[11px] font-semibold text-neutral-700">{meta.label}</span>
        <span className="ml-auto text-[10px] text-neutral-400 font-mono">{tc.name}</span>
      </div>

      {/* Params */}
      <div className="px-3 py-2 space-y-1.5">
        {tc.name === "analyze_history" && (
          <AnalyzeHistoryParams input={tc.input} />
        )}
        {tc.name === "rag_search" && (
          <RAGSearchParams input={tc.input} />
        )}
        {tc.name !== "analyze_history" && tc.name !== "rag_search" && (
          <GenericParams input={tc.input} />
        )}

        {/* Result size */}
        <div className="flex items-center gap-1 pt-1 border-t border-neutral-200 mt-1">
          <span className="text-[10px] text-neutral-400">Result</span>
          <span className="text-[10px] font-medium text-neutral-600">
            ~{tc.result_chars.toLocaleString()} chars
          </span>
        </div>
      </div>
    </div>
  );
}

function AnalyzeHistoryParams({ input }: { input: Record<string, unknown> }) {
  return (
    <>
      {input.athlete != null && (
        <ParamRow label="athlete" value={String(input.athlete)} />
      )}
      {input.question != null && (
        <ParamRow label="question" value={String(input.question)} truncate />
      )}
      {(input.date_from != null || input.date_to != null) && (
        <ParamRow
          label="period"
          value={`${input.date_from ?? "?"} → ${input.date_to ?? "?"}`}
        />
      )}
    </>
  );
}

function RAGSearchParams({ input }: { input: Record<string, unknown> }) {
  return (
    <>
      {input.query != null && (
        <ParamRow label="query" value={String(input.query)} truncate />
      )}
    </>
  );
}

function GenericParams({ input }: { input: Record<string, unknown> }) {
  return (
    <>
      {Object.entries(input).map(([k, v]) => (
        <ParamRow key={k} label={k} value={String(v)} truncate />
      ))}
    </>
  );
}

function ParamRow({ label, value, truncate }: { label: string; value: string; truncate?: boolean }) {
  const display = truncate && value.length > 80 ? value.slice(0, 80) + "…" : value;
  return (
    <div className="flex gap-1.5">
      <span className="shrink-0 text-[10px] text-neutral-400 w-14">{label}</span>
      <span className="text-[11px] text-neutral-700 break-words leading-relaxed">{display}</span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function TraceSidebar({ message, onClose }: Props) {
  const steps = message?.pipelineSteps ?? [];
  const trace = message?.ragResponse?.trace ?? null;
  const mode = message?.commandMode ?? "question";
  const isAgent = mode === "agent";
  const isAnalysis = mode === "analysis";
  const isLoading = !!message?.isLoading;
  const doneCount = steps.filter(s => s.status === "done").length;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Sidebar header */}
      <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-neutral-700">Trace</span>
          {isLoading && steps.length > 0 && (
            <span className="text-xs text-neutral-400">{doneCount}/{steps.length}</span>
          )}
          {isLoading && <Spinner size={12} />}
        </div>
        <button
          onClick={onClose}
          className="flex h-6 w-6 items-center justify-center text-neutral-400 hover:text-neutral-700 transition-colors"
          aria-label="Close trace"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Empty state */}
      {!message && (
        <div className="flex flex-1 items-center justify-center px-6 text-center">
          <div>
            <p className="text-sm font-medium text-neutral-400">No trace yet</p>
            <p className="mt-1 text-xs text-neutral-300">Send a message to see the pipeline trace here.</p>
          </div>
        </div>
      )}

      {/* Trace content */}
      {message && (
        <div className="flex-1 overflow-y-auto">

          {/* ── Pipeline steps ──────────────────────────────────────────────── */}
          {steps.length > 0 && (
            <section className="border-b border-neutral-100 px-4 py-4">
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-neutral-400">
                {isAgent ? "Agent steps" : isAnalysis ? "Analysis steps" : "Pipeline steps"}
              </p>
              <div className="space-y-3">
                {steps.map((step, i) => (
                  <div key={i}>
                    <div className="flex items-start gap-2.5">
                      <span className="mt-0.5 flex h-3 w-3 shrink-0 items-center justify-center">
                        <StepIcon status={step.status} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <span className={`text-xs ${
                          step.status === "done"    ? "text-neutral-800" :
                          step.status === "skipped" ? "text-neutral-300 line-through" :
                          "text-neutral-400"
                        }`}>
                          {step.label}
                        </span>
                        {step.detail && step.status === "done" && (
                          <span className="ml-1.5 text-[11px] text-neutral-400">{step.detail}</span>
                        )}
                      </div>
                    </div>
                    {/* RAG per-step inline detail */}
                    {!isAgent && !isAnalysis && trace && step.status === "done" && (
                      <div className="ml-5">
                        <RAGStepDetail index={i} trace={trace} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ── AGENT: tool call cards ─────────────────────────────────────── */}
          {isAgent && !isLoading && message.agentResponse && message.agentResponse.tool_calls.length > 0 && (
            <section className="border-b border-neutral-100 px-4 py-4">
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-neutral-400">
                Tool calls ({message.agentResponse.tool_calls.length})
              </p>
              <div className="space-y-2.5">
                {message.agentResponse.tool_calls.map((tc, i) => (
                  <ToolCallCard key={i} tc={tc} />
                ))}
              </div>
            </section>
          )}

          {/* ── AGENT: run stats ──────────────────────────────────────────── */}
          {isAgent && !isLoading && message.agentResponse && (
            <section className="border-b border-neutral-100 px-4 py-4">
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-neutral-400">Run stats</p>
              <div className="space-y-2 text-xs">
                <Row label="Iterations" value={String(message.agentResponse.iterations)} />
                <Row label="Total tokens" value={message.agentResponse.usage.total_tokens.toLocaleString()} />
                {(message.agentResponse.usage.cache_read_tokens ?? 0) > 0 && (
                  <Row label="Cache hits" value={`${message.agentResponse.usage.cache_read_tokens!.toLocaleString()} tokens`} />
                )}
              </div>
            </section>
          )}

          {/* ── ANALYSIS: question classification ─────────────────────────── */}
          {isAnalysis && !isLoading && message.workoutResponse?.question_type && (
            <section className="border-b border-neutral-100 px-4 py-4">
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-neutral-400">Question</p>
              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  label={message.workoutResponse.question_type}
                  cls={ANALYSIS_TYPE_BADGE[message.workoutResponse.question_type] ?? "bg-neutral-100 text-neutral-500 border-neutral-200"}
                />
                {message.workoutResponse.focus && (
                  <span className="text-[11px] text-neutral-500">
                    Focus: <span className="text-neutral-700 font-medium">{message.workoutResponse.focus}</span>
                  </span>
                )}
              </div>
            </section>
          )}

          {/* ── ANALYSIS: data summary ────────────────────────────────────── */}
          {isAnalysis && !isLoading && message.workoutResponse && (
            <section className="border-b border-neutral-100 px-4 py-4">
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-neutral-400">Data used</p>
              <div className="space-y-2 text-xs">
                <Row label="Sessions" value={String(message.workoutResponse.data_summary.sessions_analysed)} />
                <Row label="Exercises" value={String(message.workoutResponse.data_summary.exercises_found)} />
                <Row
                  label="Period"
                  value={`${message.workoutResponse.data_summary.date_range.from} → ${message.workoutResponse.data_summary.date_range.to}`}
                />
                {message.workoutResponse.data_summary.deload_weeks_detected > 0 && (
                  <Row label="Deload weeks" value={String(message.workoutResponse.data_summary.deload_weeks_detected)} />
                )}
                {message.workoutResponse.data_summary.muscle_groups_found.length > 0 && (
                  <Row label="Muscles" value={message.workoutResponse.data_summary.muscle_groups_found.join(", ")} />
                )}
                {message.workoutResponse.model && (
                  <Row label="Model" value={message.workoutResponse.model} />
                )}
              </div>
            </section>
          )}

          {/* ── QUESTION (RAG): response stats ────────────────────────────── */}
          {!isAgent && !isAnalysis && !isLoading && message.ragResponse && (
            <section className="border-b border-neutral-100 px-4 py-4">
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-neutral-400">Response</p>
              <div className="space-y-2 text-xs">
                {message.ragResponse.model && (
                  <Row label="Model" value={message.ragResponse.model} />
                )}
                {message.ragResponse.usage && (
                  <>
                    <Row label="Tokens" value={message.ragResponse.usage.total_tokens.toLocaleString()} />
                    {(message.ragResponse.usage.cache_read_tokens ?? 0) > 0 && (
                      <Row label="Cache hits" value={`${message.ragResponse.usage.cache_read_tokens!.toLocaleString()} tokens`} />
                    )}
                  </>
                )}
                {message.ragResponse.sources.length > 0 && (
                  <Row label="Sources" value={`${message.ragResponse.sources.length} chunk${message.ragResponse.sources.length !== 1 ? "s" : ""}`} />
                )}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-neutral-400">{label}</span>
      <span className="text-right text-neutral-700 font-medium">{value}</span>
    </div>
  );
}
