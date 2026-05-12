"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import type { Message, PipelineStep, RAGResponse } from "@/types/chat";
import { queryRAG, RAGError } from "@/lib/api/rag";
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
  return steps.map((s, i) => {
    // Layer 2 (index 1) is "skipped" if the response didn't go through intent classification
    // We infer this by checking if in_scope is true and intent is not a risk label
    if (i === 1) {
      const riskLabels = ["MEDICAL_REFUSE", "EATING_RISK", "OUT_OF_SCOPE", "BORDERLINE"];
      const hasRisk = response.intent && riskLabels.includes(response.intent);
      return {
        ...s,
        status: hasRisk ? "done" : "skipped",
        detail: hasRisk ? response.intent ?? undefined : "no risk signals",
      };
    }
    if (i === 2 && response.intent) {
      return { ...s, status: "done", detail: response.intent };
    }
    if (i === 3 && response.sources.length > 0) {
      return {
        ...s,
        status: "done",
        detail: `${response.sources.length} chunk${response.sources.length !== 1 ? "s" : ""} retrieved`,
      };
    }
    return { ...s, status: "done" };
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
      const response: RAGResponse = await queryRAG(text);

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
