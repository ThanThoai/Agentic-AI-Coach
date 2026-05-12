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
import { TraceSidebar } from "./TraceSidebar";

const RAG_PIPELINE_LABELS: { label: string; delayMs: number }[] = [
  { label: "Checking guardrails (L1)", delayMs: 0 },
  { label: "Classifying intent (L2)", delayMs: 300 },
  { label: "Processing query", delayMs: 700 },
  { label: "Hybrid search", delayMs: 1200 },
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
  { label: "Routing to agent", delayMs: 0 },
  { label: "Selecting tools", delayMs: 600 },
  { label: "Running tools in parallel", delayMs: 1400 },
  { label: "Synthesising answer", delayMs: 2400 },
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
        if (l1?.status === "blocked") return { ...s, status: "done", detail: `blocked` };
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
        return { ...s, status: "done", detail: `${qp.query_type} · ${n} sub-q` };
      }
      case 3: {
        const r = trace?.retrieval;
        if (!r) return { ...s, status: "done" };
        return { ...s, status: "done", detail: `${r.total_merged} chunks` };
      }
      case 4: {
        const ctx = trace?.context;
        if (!ctx) return { ...s, status: "done" };
        const c = ctx.conflict_count > 0 ? ` · ${ctx.conflict_count} conflict${ctx.conflict_count !== 1 ? "s" : ""}` : "";
        return { ...s, status: "done", detail: `${ctx.strategy}${c}` };
      }
      case 5:
        if (!response.in_scope) return { ...s, status: "skipped" };
        return { ...s, status: "done", detail: response.model ?? undefined };
      default:
        return { ...s, status: "done" };
    }
  });
}

function toFriendlyMessage(status: number, raw: string, mode: CommandMode): string {
  switch (status) {
    case 401:
      return "Your session has expired. Please refresh the page and try again.";
    case 403:
      return mode === "agent"
        ? "Only coach accounts can use Agent Assist. Please switch to the coach account."
        : "You don't have permission for this action.";
    case 422:
      return "Your request couldn't be processed. Try rephrasing your question.";
    case 429:
      return "Too many requests — please wait a moment before trying again.";
    case 502:
    case 503:
    case 504:
      return "The service is temporarily unavailable. Please try again in a moment.";
    default:
      if (status >= 500) return "Something went wrong on our end. Please try again.";
      // For other codes use the API message if it's meaningful
      return raw && !raw.startsWith("Request failed") ? raw : "Something went wrong. Please try again.";
  }
}

export function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeMode, setActiveMode] = useState<CommandMode>("question");
  const [activeUser, setActiveUser] = useState<DemoUser | null>(null);
  const [demoUsers, setDemoUsers] = useState<DemoUser[]>([]);
  const [userLoading, setUserLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const isCoach = activeUser?.role === "coach";
  const hasMessages = messages.length > 0;
  const isTyping = input.length > 0;

  const lastAssistantMsg = [...messages].reverse().find(m => m.role === "assistant") ?? null;

  useEffect(() => {
    async function loadUsers() {
      setUserLoading(true);
      try {
        const users = await Promise.all(ALL_DEMO_KEYS.map(fetchDemoToken));
        setDemoUsers(users);
        setActiveUser(users[0]);
      } catch { /* silent */ }
      finally { setUserLoading(false); }
    }
    void loadUsers();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const updateMessage = useCallback((id: string, patch: Partial<Message>) => {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, ...patch } : m));
  }, []);

  function animatePipeline(assistantId: string, labels: { label: string; delayMs: number }[]) {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = labels.map(({ delayMs }, i) =>
      setTimeout(() => {
        setMessages(prev => prev.map(m => {
          if (m.id !== assistantId) return m;
          const steps = [...(m.pipelineSteps ?? [])];
          steps[i] = { ...steps[i], status: "done" };
          return { ...m, pipelineSteps: steps };
        }));
      }, delayMs),
    );
  }

  async function send(rawText: string, mode: CommandMode) {
    if (loading) return;
    const text = mode === "agent" ? rawText.replace(/^@AgentAssist\s*/i, "").trim() : rawText;
    const user = activeUser;
    setLoading(true);

    const dataOwnerForMode = mode === "analysis" && user
      ? { key: user.key, name: user.name }
      : undefined;

    const labels = mode === "agent" ? AGENT_PIPELINE_LABELS
      : mode === "analysis" ? ANALYSIS_PIPELINE_LABELS
      : RAG_PIPELINE_LABELS;

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

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    animatePipeline(assistantId, labels);

    try {
      if (mode === "agent") {
        if (!user || !isCoach) throw new AgentError(403, "Only coaches can use the agent.");
        const response = await askAgent(text, user.access_token);
        timersRef.current.forEach(clearTimeout);
        updateMessage(assistantId, {
          content: response.answer,
          agentResponse: response,
          pipelineSteps: initialSteps(AGENT_PIPELINE_LABELS).map(s => ({ ...s, status: "done" })),
          isLoading: false,
        });
      } else if (mode === "analysis") {
        if (!user) throw new WorkoutError(401, "No user selected");
        const response = await analyzeWorkout(text, user.access_token);
        timersRef.current.forEach(clearTimeout);
        updateMessage(assistantId, {
          content: response.answer,
          workoutResponse: response,
          pipelineSteps: initialSteps(labels).map(s => ({ ...s, status: "done" })),
          isLoading: false,
        });
      } else {
        const response = await queryRAGStream(text, (token) => {
          setMessages(prev => prev.map(m =>
            m.id !== assistantId ? m : { ...m, content: m.content + token }
          ));
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
      let code: number | undefined;
      if (err instanceof RAGError || err instanceof WorkoutError || err instanceof AgentError) {
        code = err.status;
        msg = toFriendlyMessage(err.status, err.message, mode);
      }
      updateMessage(assistantId, {
        content: "",
        error: msg,
        errorCode: code,
        pipelineSteps: initialSteps(labels).map(s => ({ ...s, status: "done" })),
        isLoading: false,
      });
    } finally {
      setLoading(false);
    }
  }

  function handleUserSelect(user: DemoUser) {
    setActiveUser(user);
    if (user.role !== "coach" && activeMode === "agent") setActiveMode("question");
  }

  // ── Landing view (no messages yet) ──────────────────────────────────────────
  if (!hasMessages) {
    return (
      <div className="flex h-screen flex-col bg-neutral-50">

        {/* Minimal top bar */}
        <header className="flex items-center justify-between px-6 py-3.5 shrink-0">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center bg-indigo-600 text-xs font-bold text-white">C</div>
            <span className="text-sm font-semibold text-neutral-800">Coach Agent</span>
          </div>
          {demoUsers.length > 0 && activeUser && (
            <UserSelector
              users={demoUsers}
              activeKey={activeUser.key}
              onSelect={handleUserSelect}
              loading={userLoading || loading}
            />
          )}
        </header>

        {/* Centered content */}
        <div className="flex flex-1 flex-col items-center px-6 pb-16" style={{ paddingTop: "8vh" }}>

          {/* Hero — collapses when typing starts */}
          <div className={`w-full max-w-xl text-center overflow-hidden transition-all duration-300 ease-out ${
            isTyping ? "max-h-0 opacity-0 mb-0" : "max-h-56 opacity-100 mb-10"
          }`}>
            <div className="flex h-16 w-16 items-center justify-center bg-indigo-600 text-2xl font-bold text-white mx-auto mb-5">
              C
            </div>
            <h1 className="text-2xl font-semibold text-neutral-900">Coach Agent</h1>
            <p className="mt-2 text-sm text-neutral-500 max-w-xs mx-auto leading-relaxed">
              {isCoach
                ? "AI-powered coaching — analyze athletes and get training insights."
                : "Ask anything about training, nutrition, and programming."}
            </p>
          </div>

          {/* Input box — expands (zoom ra) when typing */}
          <div className={`w-full transition-all duration-300 ease-out ${
            isTyping ? "max-w-3xl" : "max-w-xl"
          }`}>
            <ChatInput
              value={input}
              onChange={setInput}
              onSend={send}
              disabled={loading}
              activeMode={activeMode}
              onModeChange={setActiveMode}
              isCoach={isCoach}
            />
          </div>

          {/* Example prompts — collapse when typing */}
          <div className={`w-full max-w-xl overflow-hidden transition-all duration-300 ease-out ${
            isTyping ? "max-h-0 opacity-0 mt-0" : "max-h-72 opacity-100 mt-6"
          }`}>
            <LandingExamples
              onExample={send}
              disabled={loading}
              activeMode={activeMode}
              isCoach={isCoach}
            />
          </div>

          <p className={`mt-4 text-center text-xs text-neutral-300 transition-opacity duration-300 ${
            isTyping ? "opacity-0" : "opacity-100"
          }`}>
            Enter to send · Shift+Enter for new line{!isCoach && " · / to switch mode"}
          </p>
        </div>
      </div>
    );
  }

  // ── Chat view (has messages) ─────────────────────────────────────────────────
  return (
    <div className="flex h-screen flex-col bg-neutral-50">

      {/* Full header */}
      <header className="flex items-center justify-between border-b border-neutral-200 bg-white px-5 py-3 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center bg-indigo-600 text-sm font-bold text-white">
            C
          </div>
          <div>
            <h1 className="text-sm font-semibold text-neutral-900">Coach Agent</h1>
            <p className="text-xs text-neutral-400">AI fitness coaching</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {demoUsers.length > 0 && activeUser && (
            <UserSelector
              users={demoUsers}
              activeKey={activeUser.key}
              onSelect={handleUserSelect}
              loading={userLoading || loading}
            />
          )}
          <button
            onClick={() => setSidebarOpen(v => !v)}
            className={`flex items-center gap-1.5 border px-3 py-1.5 text-xs font-medium transition-colors ${
              sidebarOpen
                ? "border-indigo-200 bg-indigo-50 text-indigo-700"
                : "border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-50"
            }`}
            title="Toggle trace sidebar"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="0" />
              <path d="M15 3v18" />
            </svg>
            Trace
          </button>
        </div>
      </header>

      {/* Body: chat + sidebar */}
      <div className="flex flex-1 overflow-hidden">

        {/* Chat column */}
        <div className="flex flex-1 flex-col overflow-hidden">
          <main className="flex-1 overflow-y-auto">
            <div className="mx-auto max-w-3xl space-y-6 px-6 py-8">
              {messages.map(msg => (
                <MessageBubble key={msg.id} message={msg} />
              ))}
              <div ref={bottomRef} />
            </div>
          </main>

          {/* Input footer */}
          <footer className="border-t border-neutral-200 bg-white px-6 py-4 shrink-0">
            <div className="mx-auto max-w-3xl">
              <ChatInput
                value={input}
                onChange={setInput}
                onSend={send}
                disabled={loading}
                activeMode={activeMode}
                onModeChange={setActiveMode}
                isCoach={isCoach}
              />
              <p className="mt-2 text-center text-xs text-neutral-300">
                Enter to send · Shift+Enter for new line{!isCoach && " · / to switch mode"}
              </p>
            </div>
          </footer>
        </div>

        {/* Trace sidebar */}
        {sidebarOpen && (
          <aside className="flex w-72 shrink-0 flex-col border-l border-neutral-200 bg-white overflow-hidden">
            <TraceSidebar message={lastAssistantMsg} onClose={() => setSidebarOpen(false)} />
          </aside>
        )}
      </div>
    </div>
  );
}

// ── Landing examples ──────────────────────────────────────────────────────────

const RAG_EXAMPLES = [
  "How many sets per week do I need for chest hypertrophy?",
  "Is PPL or Upper/Lower better for an intermediate lifter?",
  "How should I structure my PPL split for hypertrophy?",
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

function LandingExamples({
  onExample, disabled, activeMode, isCoach,
}: {
  onExample: (q: string, mode: CommandMode) => void;
  disabled: boolean;
  activeMode: CommandMode;
  isCoach: boolean;
}) {
  const effectiveMode: CommandMode = isCoach ? "agent" : activeMode;
  const examples = isCoach ? AGENT_EXAMPLES : activeMode === "analysis" ? ANALYSIS_EXAMPLES : RAG_EXAMPLES;

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-neutral-300 text-center mb-3">
        Try asking
      </p>
      {examples.map(q => (
        <button
          key={q}
          onClick={() => onExample(q, effectiveMode)}
          disabled={disabled}
          className="w-full border border-neutral-200 bg-white px-4 py-3 text-left text-sm text-neutral-600 transition-colors hover:bg-neutral-50 hover:text-neutral-800 disabled:opacity-50"
        >
          {q}
        </button>
      ))}
    </div>
  );
}
