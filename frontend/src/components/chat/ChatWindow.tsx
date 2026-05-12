"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import type { Message, PipelineStep, RAGResponse, CommandMode, DemoUser } from "@/types/chat";
import { queryRAGStream, RAGError } from "@/lib/api/rag";
import { analyzeWorkout, WorkoutError } from "@/lib/api/workout";
import { askAgent, AgentError } from "@/lib/api/agent";
import { fetchDemoToken } from "@/lib/api/auth";
import { MessageBubble } from "./MessageBubble";
import { ChatInput } from "./ChatInput";
import { UserSelector } from "./UserSelector";

const RAG_PIPELINE_LABELS: { label: string; delayMs: number }[] = [
  { label: "Checking guardrails (Layer 1)", delayMs: 0 },
  { label: "Classifying intent (Layer 2)", delayMs: 300 },
  { label: "Processing query", delayMs: 700 },
  { label: "Running hybrid search", delayMs: 1200 },
  { label: "Assembling context", delayMs: 1800 },
  { label: "Generating answer", delayMs: 2300 },
];

const ANALYSIS_PIPELINE_LABELS: { label: string; delayMs: number }[] = [
  { label: "Fetching workout history", delayMs: 0 },
  { label: "Computing analytics", delayMs: 400 },
  { label: "Classifying question", delayMs: 900 },
  { label: "Building context", delayMs: 1400 },
  { label: "Generating answer", delayMs: 1900 },
];

const AGENT_PIPELINE_LABELS: { label: string; delayMs: number }[] = [
  { label: "Routing to Coach Agent", delayMs: 0 },
  { label: "Selecting tools to call", delayMs: 600 },
  { label: "Running tools in parallel", delayMs: 1400 },
  { label: "Synthesising coaching advice", delayMs: 2400 },
];

const ALL_DEMO_KEYS = ["alex", "binh", "coach"] as const;

function initialSteps(labels: { label: string }[]): PipelineStep[] {
  return labels.map(({ label }) => ({ label, status: "pending" }));
}

function finaliseRAGSteps(steps: PipelineStep[], response: RAGResponse): PipelineStep[] {
  const trace = response.trace;
  return steps.map((s, i) => {
    switch (i) {
      case 0: {
        const l1 = trace?.guardrail_l1;
        if (l1?.status === "blocked") return { ...s, status: "done", detail: `blocked: ${l1.block_reason}` };
        return { ...s, status: "done", detail: "passed" };
      }
      case 1: {
        const l2 = trace?.guardrail_l2;
        if (!l2 || l2.status === "skipped") return { ...s, status: "skipped", detail: "no risk signals" };
        return { ...s, status: "done", detail: l2.intent ?? undefined };
      }
      case 2: {
        const qp = trace?.query_processor;
        if (!qp) return { ...s, status: "done" };
        const n = qp.sub_questions.length;
        return { ...s, status: "done", detail: `${qp.query_type} · ${n} sub-question${n !== 1 ? "s" : ""}` };
      }
      case 3: {
        const r = trace?.retrieval;
        if (!r) return { ...s, status: "done" };
        return { ...s, status: "done", detail: `${r.total_merged} chunks merged` };
      }
      case 4: {
        const ctx = trace?.context;
        if (!ctx) return { ...s, status: "done" };
        const conflictNote = ctx.conflict_count > 0 ? ` · ${ctx.conflict_count} conflict${ctx.conflict_count !== 1 ? "s" : ""}` : "";
        return { ...s, status: "done", detail: `${ctx.strategy} · ${ctx.chunks_used} chunks${conflictNote}` };
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
  const [activeMode, setActiveMode] = useState<CommandMode>("question");
  const [activeUser, setActiveUser] = useState<DemoUser | null>(null);
  const [demoUsers, setDemoUsers] = useState<DemoUser[]>([]);
  const [userLoading, setUserLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const isCoach = activeUser?.role === "coach";

  // Load all demo tokens on mount
  useEffect(() => {
    async function loadUsers() {
      setUserLoading(true);
      try {
        const users = await Promise.all(ALL_DEMO_KEYS.map(fetchDemoToken));
        setDemoUsers(users);
        setActiveUser(users[0]);
      } catch {
        // Continue without auth
      } finally {
        setUserLoading(false);
      }
    }
    void loadUsers();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const updateMessage = useCallback((id: string, patch: Partial<Message>) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));
  }, []);

  function animatePipeline(assistantId: string, labels: { label: string; delayMs: number }[]) {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = labels.map(({ delayMs }, i) =>
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
  }

  async function send(rawText: string, mode: CommandMode) {
    if (loading) return;
    // Strip @AgentAssist mention from text (ChatInput already does this for typed messages,
    // but example buttons call send() directly with the raw string)
    const text = mode === "agent" ? rawText.replace(/^@AgentAssist\s*/i, "").trim() : rawText;
    // Snapshot state at call time to guard against mid-await changes
    const user = activeUser;
    setLoading(true);

    // Determine data owner label (agent resolves athlete from message text server-side)
    const dataOwnerForMode =
      mode === "analysis" && user
        ? { key: user.key, name: user.name }
        : undefined;

    const labels =
      mode === "agent" ? AGENT_PIPELINE_LABELS :
      mode === "analysis" ? ANALYSIS_PIPELINE_LABELS :
      RAG_PIPELINE_LABELS;

    const userMsg: Message = { id: crypto.randomUUID(), role: "user", content: text, commandMode: mode };
    const assistantId = crypto.randomUUID();
    const assistantMsg: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      isLoading: true,
      commandMode: mode,
      dataOwner: dataOwnerForMode,
      pipelineSteps: initialSteps(labels),
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    animatePipeline(assistantId, labels);

    try {
      if (mode === "agent") {
        if (!user || !isCoach) throw new AgentError(403, "Only coaches can use the agent.");
        const response = await askAgent(text, user.access_token);
        timersRef.current.forEach(clearTimeout);
        updateMessage(assistantId, {
          content: response.answer,
          agentResponse: response,
          pipelineSteps: initialSteps(AGENT_PIPELINE_LABELS).map((s) => ({ ...s, status: "done" })),
          isLoading: false,
        });
      } else if (mode === "analysis") {
        if (!user) throw new WorkoutError(401, "No user selected");
        const response = await analyzeWorkout(text, user.access_token);
        timersRef.current.forEach(clearTimeout);
        updateMessage(assistantId, {
          content: response.answer,
          workoutResponse: response,
          pipelineSteps: initialSteps(labels).map((s) => ({ ...s, status: "done" })),
          isLoading: false,
        });
      } else {
        const response = await queryRAGStream(text, (token) => {
          setMessages((prev) =>
            prev.map((m) => m.id !== assistantId ? m : { ...m, content: m.content + token }),
          );
        });
        timersRef.current.forEach(clearTimeout);
        updateMessage(assistantId, {
          content: response.answer,
          ragResponse: response,
          pipelineSteps: finaliseRAGSteps(initialSteps(RAG_PIPELINE_LABELS), response),
          isLoading: false,
        });
      }
    } catch (err) {
      timersRef.current.forEach(clearTimeout);
      let msg = "Something went wrong. Please try again.";
      if (err instanceof RAGError) msg = `Error ${err.status}: ${err.message}`;
      else if (err instanceof WorkoutError) msg = `Error ${err.status}: ${err.message}`;
      else if (err instanceof AgentError) msg = `Agent error ${err.status}: ${err.message}`;
      updateMessage(assistantId, {
        content: "",
        error: msg,
        pipelineSteps: initialSteps(labels).map((s) => ({ ...s, status: "done" })),
        isLoading: false,
      });
    } finally {
      setLoading(false);
    }
  }

  function handleUserSelect(user: DemoUser) {
    setActiveUser(user);
    // When switching to athlete, reset mode from agent if needed
    if (user.role !== "coach" && activeMode === "agent") {
      setActiveMode("question");
    }
  }

  return (
    <div className="flex h-screen flex-col bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="border-b border-white/10 px-6 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold">
              C
            </div>
            <div>
              <h1 className="text-sm font-semibold">Coach Agent</h1>
              <p className="text-xs text-gray-500">AI fitness coaching</p>
            </div>
          </div>
          {demoUsers.length > 0 && activeUser && (
            <UserSelector
              users={demoUsers}
              activeKey={activeUser.key}
              onSelect={handleUserSelect}
              loading={userLoading || loading}
            />
          )}
        </div>

        {/* Coach hint */}
        {isCoach && (
          <div className="mt-1.5 text-[10px] text-gray-600 text-right">
            Mention <span className="text-purple-400 font-mono">@AgentAssist</span> and an athlete name (e.g. "Alex", "Binh") in your message
          </div>
        )}
      </header>

      {/* Messages */}
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-6 px-4 py-6">
          {messages.length === 0 && (
            <EmptyState onExample={send} disabled={loading} activeMode={activeMode} isCoach={isCoach} />
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
            activeMode={activeMode}
            onModeChange={setActiveMode}
            isCoach={isCoach}
          />
          <p className="mt-2 text-center text-xs text-gray-600">
            Enter to send · Shift+Enter for new line
            {!isCoach && " · / to switch mode"}
          </p>
        </div>
      </footer>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

const RAG_EXAMPLES = [
  "How many sets per week do I need for chest hypertrophy?",
  "Is PPL or Upper/Lower better for an intermediate lifter?",
  "How should I structure my PPL split and what intensity for hypertrophy?",
];

const ANALYSIS_EXAMPLES = [
  "How has my training volume changed over the past few months?",
  "Which muscle groups am I neglecting in my training?",
  "Have I had any deload weeks recently?",
];

const AGENT_EXAMPLES = [
  "Is Alex ready to increase bench press weight?",
  "Compare Alex and Binh's push/pull volume — who needs more pulling work?",
  "Summarise both athletes' progress and suggest next steps.",
];

function EmptyState({
  onExample,
  disabled,
  activeMode,
  isCoach,
}: {
  onExample: (q: string, mode: CommandMode) => void;
  disabled: boolean;
  activeMode: CommandMode;
  isCoach: boolean;
}) {
  const isAgent = activeMode === "agent" || (isCoach && activeMode === "question");
  const isAnalysis = activeMode === "analysis";

  const title = isCoach
    ? "Coach Dashboard"
    : isAnalysis
      ? "Workout Analysis"
      : "Fitness Knowledge Base";

  const subtitle = isCoach
    ? "Pick a mode from the tab bar — Knowledge, Analyze, or Agent Assist."
    : isAnalysis
      ? "Ask about your training history and progress."
      : "Ask about training, nutrition, and programming.";

  const emoji = isCoach ? "🎯" : isAnalysis ? "📊" : "🏋️";

  const examples = isCoach ? AGENT_EXAMPLES : isAnalysis ? ANALYSIS_EXAMPLES : RAG_EXAMPLES;
  const exampleMode: CommandMode = isCoach ? "agent" : activeMode;

  return (
    <div className="flex flex-col items-center gap-6 py-12 text-center">
      <div className={`flex h-14 w-14 items-center justify-center rounded-2xl text-3xl ${isCoach ? "bg-purple-600/20" : isAnalysis ? "bg-emerald-600/20" : "bg-indigo-600/20"}`}>
        {emoji}
      </div>
      <div>
        <h2 className="text-lg font-semibold text-gray-200">{title}</h2>
        <p className="mt-1 text-sm text-gray-500 max-w-sm">{subtitle}</p>
      </div>
      <div className="w-full space-y-2">
        {examples.map((q) => (
          <button
            key={q}
            onClick={() => onExample(q, exampleMode)}
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
