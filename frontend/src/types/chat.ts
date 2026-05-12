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
  ragResponse?: RAGResponse;
  pipelineSteps?: PipelineStep[];
  isLoading?: boolean;
  error?: string;
}
