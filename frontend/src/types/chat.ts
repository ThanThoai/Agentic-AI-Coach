export interface RAGSource {
  doc_title: string;
  section_title: string;
  source_file: string;
  score: number;
  excerpt: string;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cache_read_tokens?: number;
}

export interface GuardrailL1Trace {
  status: "passed" | "blocked";
  block_reason: string | null;
}

export interface GuardrailL2Trace {
  status: "run" | "skipped";
  intent: string | null;
  reason: string | null;
}

export interface QueryProcessorTrace {
  query_type: string;
  sub_questions: string[];
}

export interface RetrievalTrace {
  results_per_query: number[];
  total_merged: number;
}

export interface ContextTrace {
  strategy: string;
  conflict_count: number;
  chunks_used: number;
}

export interface PipelineTrace {
  guardrail_l1: GuardrailL1Trace;
  guardrail_l2: GuardrailL2Trace | null;
  query_processor: QueryProcessorTrace | null;
  retrieval: RetrievalTrace | null;
  context: ContextTrace | null;
}

export interface RAGResponse {
  answer: string;
  in_scope: boolean;
  sources: RAGSource[];
  intent: string | null;
  model: string | null;
  usage: TokenUsage | null;
  trace: PipelineTrace | null;
}

// ── Workout analysis types ────────────────────────────────────────────────────

export interface WorkoutDataSummary {
  sessions_analysed: number;
  date_range: { from: string; to: string };
  exercises_found: number;
  muscle_groups_found: string[];
  deload_weeks_detected: number;
  insufficient_data: boolean;
}

export interface WorkoutAnalysisResponse {
  answer: string;
  data_summary: WorkoutDataSummary;
  question_type?: string;
  focus?: string | null;
  model: string | null;
  usage: TokenUsage | null;
}

// ── Agent types ───────────────────────────────────────────────────────────────

export interface AgentToolCall {
  name: string;
  input: Record<string, unknown>;
  result_chars: number;
}

export interface AgentResponse {
  answer: string;
  tools_used: string[];
  tool_calls: AgentToolCall[];
  iterations: number;
  usage: TokenUsage;
}

// ── User / command types ──────────────────────────────────────────────────────

export type UserRole = "athlete" | "coach";

export interface DemoUser {
  user_id: string;
  access_token: string;
  name: string;
  /** "alex" | "binh" | "coach" */
  key: string;
  role: UserRole;
}

/** Fixed athlete users the coach can select as target */
export const ATHLETE_KEYS = ["alex", "binh"] as const;
export type AthleteKey = (typeof ATHLETE_KEYS)[number];

export type CommandMode = "question" | "analysis" | "agent";

export interface SlashCommand {
  name: string;
  mode: CommandMode;
  description: string;
  placeholder: string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  {
    name: "/question",
    mode: "question",
    description: "Search the fitness knowledge base",
    placeholder: "Ask a fitness question…",
  },
  {
    name: "/analysis",
    mode: "analysis",
    description: "Analyse my workout history with AI",
    placeholder: "What do you want to know about your training?",
  },
  {
    name: "/agent",
    mode: "agent",
    description: "Coach Assist — ask about your athletes",
    placeholder: 'Ask about your athletes… e.g. "Is Alex ready to increase weight?"',
  },
];

// ── Message types ─────────────────────────────────────────────────────────────

export type MessageRole = "user" | "assistant";

export interface PipelineStep {
  label: string;
  detail?: string;
  status: "pending" | "done" | "skipped";
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  commandMode?: CommandMode;
  /** For analysis / agent messages: the athlete whose data was queried. */
  dataOwner?: { key: string; name: string };
  ragResponse?: RAGResponse;
  workoutResponse?: WorkoutAnalysisResponse;
  agentResponse?: AgentResponse;
  pipelineSteps?: PipelineStep[];
  isLoading?: boolean;
  error?: string;
  errorCode?: number;
}
