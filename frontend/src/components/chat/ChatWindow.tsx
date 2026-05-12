"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import type { Message, PipelineStep, RAGResponse } from "@/types/chat";
import { queryRAGStream, RAGError } from "@/lib/api/rag";
import { MessageBubble } from "./MessageBubble";
import { ChatInput } from "./ChatInput";

// Pipeline steps shown in the thinking panel
const PIPELINE_LABELS: { label: string; delayMs: number }[] = [
  { label: "Checking guardrails (Layer 1)", delayMs: 0 },
  { label: "Classifying intent (Layer 2)", delayMs: 300 },
  { label: "Processing query", delayMs: 700 },
  { label: "Running hybrid search", delayMs: 1200 },
  { label: "Assembling context", delayMs: 1800 },
  { label: "Generating answer", delayMs: 2300 },
];

function initialSteps(): PipelineStep[] {
  return PIPELINE_LABELS.map(({ label }) => ({
    label,
    status: "pending",
  }));
}

function finaliseSteps(
  steps: PipelineStep[],
  response: RAGResponse,
): PipelineStep[] {
  const trace = response.trace;
  return steps.map((s, i) => {
    switch (i) {
      case 0: {
        const l1 = trace?.guardrail_l1;
        if (l1?.status === "blocked") {
          return { ...s, status: "done", detail: `blocked: ${l1.block_reason}` };
        }
        return { ...s, status: "done", detail: "passed" };
      }
      case 1: {
        const l2 = trace?.guardrail_l2;
        if (!l2 || l2.status === "skipped") {
          return { ...s, status: "skipped", detail: "no risk signals" };
        }
        return { ...s, status: "done", detail: l2.intent ?? undefined };
      }
      case 2: {
        const qp = trace?.query_processor;
        if (!qp) return { ...s, status: "done" };
        const n = qp.sub_questions.length;
        return {
          ...s,
          status: "done",
          detail: `${qp.query_type} · ${n} sub-question${n !== 1 ? "s" : ""}`,
        };
      }
      case 3: {
        const r = trace?.retrieval;
        if (!r) return { ...s, status: "done" };
        return { ...s, status: "done", detail: `${r.total_merged} chunks merged` };
      }
      case 4: {
        const ctx = trace?.context;
        if (!ctx) return { ...s, status: "done" };
        const conflictNote = ctx.conflict_count > 0
          ? ` · ${ctx.conflict_count} conflict${ctx.conflict_count !== 1 ? "s" : ""}`
          : "";
        return {
          ...s,
          status: "done",
          detail: `${ctx.strategy} · ${ctx.chunks_used} chunks${conflictNote}`,
        };
      }
      case 5:
        if (!response.in_scope) return { ...s, status: "skipped" };
        return { ...s, status: "done", detail: response.model ?? undefined };
      default:
        return { ...s, status: "done" };
    }
  });
}

export function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const updateMessage = useCallback(
    (id: string, patch: Partial<Message>) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === id ? { ...m, ...patch } : m)),
      );
    },
    [],
  );

  async function send(text: string) {
    if (loading) return;
    setLoading(true);

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };

    const assistantId = crypto.randomUUID();
    const assistantMsg: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      isLoading: true,
      pipelineSteps: initialSteps(),
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    // Animate pipeline steps while waiting for the real response
    timersRef.current.forEach(clearTimeout);
    timersRef.current = PIPELINE_LABELS.map(({ delayMs }, i) =>
      setTimeout(() => {
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== assistantId) return m;
            const steps = [...(m.pipelineSteps ?? [])];
            steps[i] = { ...steps[i], status: "done" };
            return { ...m, pipelineSteps: steps };
          }),
        );
      }, delayMs),
    );

    try {
      const response = await queryRAGStream(
        text,
        (token) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id !== assistantId
                ? m
                : { ...m, content: m.content + token },
            ),
          );
        },
      );

      timersRef.current.forEach(clearTimeout);

      updateMessage(assistantId, {
        content: response.answer,
        ragResponse: response,
        pipelineSteps: finaliseSteps(initialSteps(), response),
        isLoading: false,
      });
    } catch (err) {
      timersRef.current.forEach(clearTimeout);
      const msg =
        err instanceof RAGError
          ? `Error ${err.status}: ${err.message}`
          : "Something went wrong. Please try again.";
      updateMessage(assistantId, {
        content: "",
        error: msg,
        pipelineSteps: initialSteps().map((s) => ({ ...s, status: "done" })),
        isLoading: false,
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-screen flex-col bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="flex items-center gap-3 border-b border-white/10 px-6 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold">
          C
        </div>
        <div>
          <h1 className="text-sm font-semibold">Coach Agent</h1>
          <p className="text-xs text-gray-500">AI fitness coaching</p>
        </div>
      </header>

      {/* Messages */}
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-6 px-4 py-6">
          {messages.length === 0 && (
            <EmptyState onExample={send} disabled={loading} />
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          <div ref={bottomRef} />
        </div>
      </main>

      {/* Input */}
      <footer className="border-t border-white/10 px-4 py-4">
        <div className="mx-auto max-w-2xl">
          <ChatInput
            value={input}
            onChange={setInput}
            onSend={send}
            disabled={loading}
          />
          <p className="mt-2 text-center text-xs text-gray-600">
            Press Enter to send · Shift+Enter for new line
          </p>
        </div>
      </footer>
    </div>
  );
}

const EXAMPLES = [
  "How many sets per week do I need for chest hypertrophy?",
  "Is PPL or Upper/Lower better for an intermediate lifter?",
  "How should I structure my PPL split and what intensity for hypertrophy?",
];

function EmptyState({
  onExample,
  disabled,
}: {
  onExample: (q: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-col items-center gap-6 py-12 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-600/20 text-3xl">
        🏋️
      </div>
      <div>
        <h2 className="text-lg font-semibold text-gray-200">
          Fitness Knowledge Base
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          Ask about training, nutrition, and programming.
        </p>
      </div>
      <div className="w-full space-y-2">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            onClick={() => onExample(q)}
            disabled={disabled}
            className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-left text-sm text-gray-300 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
